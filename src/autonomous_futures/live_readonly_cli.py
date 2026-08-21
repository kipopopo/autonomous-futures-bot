"""Run exactly one production read-only account reconciliation."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from .live_activation import SqliteLiveActivationTokens
from .live_readonly import (
    LivePositionExpectation,
    build_live_account_request,
    fetch_live_account,
    parse_live_account_snapshot,
    reconcile_live_account,
)

# Kept local to avoid importing preflight execution policy into the GET boundary.
_CREDENTIAL_NAMES = ("BINANCE_LIVE_API_KEY", "BINANCE_LIVE_SECRET_KEY")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Perform one production read-only account reconciliation."
    )
    parser.add_argument("--token-db", type=Path, required=True)
    parser.add_argument("--credential-dir", type=Path, required=True)
    parser.add_argument("--now", help="UTC ISO-8601 timestamp; defaults to current UTC")
    return parser


def _now(value: str | None) -> datetime:
    parsed = datetime.now(UTC) if value is None else datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("--now must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _blocked(reason_codes: tuple[str, ...], token_id: str) -> int:
    print(
        json.dumps(
            {
                "live_enabled": False,
                "network_requests": 0,
                "reason_codes": list(reason_codes),
                "status": "blocked",
                "token_id": token_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 3


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        tokens = SqliteLiveActivationTokens(args.token_db).read()
        if not tokens:
            raise ValueError("no live activation token available")
        token = tokens[-1]
        if _now(args.now) >= token.expires_at:
            return _blocked(("token_expired",), token.token_id)
        values = {
            name: (args.credential_dir / name).read_text(encoding="utf-8").strip()
            for name in _CREDENTIAL_NAMES
        }
        missing = tuple(name for name, value in values.items() if not value)
        if missing:
            return _blocked(tuple(f"credential_missing_{name}" for name in missing), token.token_id)
        request = build_live_account_request(
            api_key=values["BINANCE_LIVE_API_KEY"],
            secret=values["BINANCE_LIVE_SECRET_KEY"],
            timestamp_ms=int(time.time() * 1000),
        )
        body = fetch_live_account(request)
        snapshot = parse_live_account_snapshot(body)
        reconciliation = reconcile_live_account(
            snapshot, (LivePositionExpectation(symbol=token.symbol),)
        )
        payload = {
            "asset_count": len(snapshot.assets),
            "live_enabled": False,
            "network_requests": 1,
            "nonzero_position_count": sum(
                position.position_amt != 0 for position in snapshot.positions
            ),
            "reason_codes": list(reconciliation.reason_codes),
            "status": reconciliation.status,
            "token_id": token.token_id,
        }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 0 if reconciliation.status == "reconciled" else 3
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error_code": "live_readonly_failed", "status": "error"}))
        del exc
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
