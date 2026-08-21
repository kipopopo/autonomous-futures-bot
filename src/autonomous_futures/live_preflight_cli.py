"""Run a manual, network-free live preflight."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .live_activation import SqliteLiveActivationTokens
from .live_preflight import evaluate_live_preflight


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a manual live preflight without network access."
    )
    parser.add_argument("--token-db", type=Path, required=True)
    parser.add_argument("--credential-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--account-reconciled", action="store_true")
    parser.add_argument("--positions-flat", action="store_true")
    parser.add_argument("--kill-switch-ready", action="store_true")
    parser.add_argument("--now", help="UTC ISO-8601 timestamp; defaults to current UTC")
    return parser


def _now(value: str | None) -> datetime:
    parsed = datetime.now(UTC) if value is None else datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("--now must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        tokens = SqliteLiveActivationTokens(args.token_db).read()
        if not tokens:
            raise ValueError("no live activation token available")
        decision = evaluate_live_preflight(
            tokens[-1],
            credential_dir=args.credential_dir,
            base_url=args.base_url,
            account_reconciled=args.account_reconciled,
            positions_flat=args.positions_flat,
            kill_switch_ready=args.kill_switch_ready,
            now=_now(args.now),
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"error_code": "invalid_input", "message": str(exc)}))
        return 2
    print(json.dumps(decision.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
    return 0 if decision.status == "ready_for_manual_activation" else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
