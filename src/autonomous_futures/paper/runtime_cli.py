"""Run one explicit caller-approved local paper action; no network or scheduler."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from ..domain.contracts import PaperExecutionRequest
from .runtime import PaperRuntime
from .safety import PaperActionApproval, PaperSafetyEvidence
from .sqlite_ledger import SqlitePaperLedger


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record one explicit approved local paper action.")
    parser.add_argument("--ledger-path", type=Path, required=True)
    parser.add_argument("--request-path", type=Path, required=True)
    parser.add_argument("--evidence-path", type=Path, required=True)
    parser.add_argument("--approval-path", type=Path, required=True)
    parser.add_argument("--action", choices=("open", "close"), required=True)
    parser.add_argument("--trade-id", required=True)
    parser.add_argument("--occurred-at", required=True)
    parser.add_argument("--exit-mark-price")
    return parser


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON input") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid JSON input")
    return payload


def _parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal input") from exc
    if not parsed.is_finite():
        raise ValueError("invalid decimal input")
    return parsed


def _parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid occurred-at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("occurred-at must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _request(path: Path) -> PaperExecutionRequest:
    payload = _load_json(path)
    for field in ("mark_price", "quantity", "fee_rate", "slippage_bps"):
        if field not in payload:
            raise ValueError("invalid request input")
        payload[field] = _parse_decimal(str(payload[field]))
    return PaperExecutionRequest.model_validate(payload)


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runtime = PaperRuntime(SqlitePaperLedger(args.ledger_path))
        request = _request(args.request_path)
        evidence = PaperSafetyEvidence.model_validate(_load_json(args.evidence_path))
        approval = PaperActionApproval.model_validate(_load_json(args.approval_path))
        occurred_at = _parse_utc_timestamp(args.occurred_at)
        if args.action == "open":
            if args.exit_mark_price is not None:
                raise ValueError("exit mark is invalid for open")
            result = runtime.open(
                request,
                evidence,
                approval,
                trade_id=args.trade_id,
                occurred_at=occurred_at,
            )
        else:
            if args.exit_mark_price is None:
                raise ValueError("exit mark is required for close")
            result = runtime.close(
                request,
                evidence,
                approval,
                trade_id=args.trade_id,
                exit_mark_price=_parse_decimal(args.exit_mark_price),
                occurred_at=occurred_at,
            )
    except (OSError, ValidationError, ValueError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    _print_json(result.model_dump(mode="json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
