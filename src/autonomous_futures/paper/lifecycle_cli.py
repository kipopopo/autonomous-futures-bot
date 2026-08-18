"""Record one explicit paper lifecycle mark without a market-data source."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from .lifecycle import mark_paper_position
from .observation import PaperObservationBinding
from .sqlite_ledger import SqlitePaperLedger
from .sqlite_lifecycle import SqlitePaperLifecycle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record one explicit paper lifecycle mark.")
    parser.add_argument("--ledger-path", type=Path, required=True)
    parser.add_argument("--lifecycle-path", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate-artifact-hash", required=True)
    parser.add_argument("--trade-id", required=True)
    parser.add_argument("--mark-price", required=True)
    parser.add_argument("--marked-at", required=True)
    parser.add_argument("--previous-peak-pnl", required=True)
    parser.add_argument("--stop-loss-price")
    parser.add_argument("--take-profit-price")
    return parser


def _parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal input") from exc
    if not parsed.is_finite():
        raise ValueError("invalid decimal input")
    return parsed


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid marked-at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("marked-at must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        binding = PaperObservationBinding(
            candidate_id=args.candidate_id,
            candidate_artifact_hash=args.candidate_artifact_hash,
        )
        ledger = SqlitePaperLedger(args.ledger_path).load()
        open_entry = next(
            (
                entry
                for entry in ledger.open_positions()
                if entry.trade_id == args.trade_id
                and entry.candidate_id == binding.candidate_id
                and entry.candidate_artifact_hash == binding.candidate_artifact_hash
            ),
            None,
        )
        if open_entry is None:
            _print_json(
                {
                    "status": "unavailable",
                    "reason_codes": ["durable_open_position_missing"],
                }
            )
            return 0
        telemetry = mark_paper_position(
            open_entry,
            mark_price=_parse_decimal(args.mark_price),
            marked_at=_parse_utc(args.marked_at),
            previous_peak_pnl=_parse_decimal(args.previous_peak_pnl),
            stop_loss_price=(
                None if args.stop_loss_price is None else _parse_decimal(args.stop_loss_price)
            ),
            take_profit_price=(
                None if args.take_profit_price is None else _parse_decimal(args.take_profit_price)
            ),
        )
        SqlitePaperLifecycle(args.lifecycle_path).append(telemetry)
    except (OSError, ValidationError, ValueError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    payload = telemetry.model_dump(mode="json")
    payload["status"] = "recorded"
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
