"""Freeze policy before chronological genuine-market ICT qualification."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.research.ict_runtime_qualification import qualify_ict  # noqa: E402
from autonomous_futures.research.runtime_qualification import (  # noqa: E402
    bind_equity_scenario,
    qualification_capital,
)


def emit(data: dict[str, Any]) -> None:
    print(json.dumps(data, default=str), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument(
        "--cache", type=Path, default=REPO / "research/immutable-data/runtime-official-20261013"
    )
    parser.add_argument("--minutes", type=Path, default=REPO / "research/official-archives/1m")
    parser.add_argument(
        "--filters",
        type=Path,
        default=REPO / "artifacts/qualification/runtime-inputs/testnet-exchange-filters.json",
    )
    parser.add_argument("--commissions", type=Path, required=True)
    parser.add_argument("--oos-start", default="2024-01-01")
    capital = parser.add_mutually_exclusive_group()
    capital.add_argument(
        "--starting-equity",
        type=Decimal,
        help=(
            "Explicit positive Decimal research starting equity; does not prove an account balance."
        ),
    )
    capital.add_argument(
        "--equity-evidence",
        type=Path,
        help="Hash-bind a flat authenticated Testnet account snapshot as a sizing seed.",
    )
    parser.add_argument(
        "--entry-mode",
        choices=("limit_touch", "reclaim_retest"),
        default="limit_touch",
        help="Freeze the causal entry model used for this qualification replay.",
    )
    parser.add_argument(
        "--invalidation-mode",
        choices=("entry_close", "stop_only"),
        default="entry_close",
        help="Freeze post-entry invalidation mode (entry_close vs structural stop_only).",
    )
    parser.add_argument(
        "--stop-loss-mode",
        choices=("swing_extreme", "ote_79_adaptive", "SWING_EXTREME", "OTE_79_ADAPTIVE"),
        default="swing_extreme",
        help="Freeze Twins stop-loss placement mode (LumiTraders PDF p. 157).",
    )
    parser.add_argument(
        "--time-filter-mode",
        choices=("all_hours", "killzones", "twins_windows", "manipulation_distribution"),
        default="all_hours",
        help="Freeze LumiTraders Quarterly/Killzone time filter mode.",
    )
    parser.add_argument("--output", type=Path, default=REPO / "artifacts/qualification/runtime-ict")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    policy, capital_scenario = qualification_capital(
        repo=REPO,
        starting_equity=args.starting_equity,
        equity_evidence_path=args.equity_evidence,
    )
    frozen = {
        "policy": json.loads(json.dumps(dataclasses.asdict(policy), default=str)),
        "oos_start": args.oos_start,
        "family": "ICT_TWINS",
        "entry_mode": args.entry_mode,
        "htf_pdas": ["4h", "1h"],
        "history_bars": 250,
        "ote": [".62", ".79"],
        "trade_risk_pct": str(policy.trade_risk_pct),
    }
    sl_mode = args.stop_loss_mode.lower()
    if args.invalidation_mode != "entry_close":
        frozen["invalidation_mode"] = args.invalidation_mode
    if sl_mode != "swing_extreme":
        frozen["stop_loss_mode"] = sl_mode
    if args.time_filter_mode != "all_hours":
        frozen["time_filter_mode"] = args.time_filter_mode
    if capital_scenario is not None:
        frozen["capital_scenario"] = capital_scenario
    path = args.output / "frozen-policy.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != frozen:
        raise ValueError("Qualification policy changed after freezing")
    path.write_bytes((json.dumps(frozen, indent=2) + "\n").encode())
    emit({"event": "ICT_POLICY_FROZEN", "symbol": args.symbol})
    start = int(datetime.fromisoformat(args.oos_start).replace(tzinfo=UTC).timestamp() * 1000)
    extra_kwargs: dict[str, Any] = {}
    if args.invalidation_mode != "entry_close":
        extra_kwargs["invalidation_mode"] = args.invalidation_mode
    if sl_mode != "swing_extreme":
        extra_kwargs["stop_loss_mode"] = sl_mode
    if args.time_filter_mode != "all_hours":
        extra_kwargs["time_filter_mode"] = args.time_filter_mode
    report = qualify_ict(
        repo=REPO,
        cache=args.cache,
        minutes=args.minutes,
        symbol=args.symbol,
        filters_path=args.filters,
        commissions_path=args.commissions,
        oos_start_ms=start,
        policy=policy,
        progress=emit,
        entry_mode=args.entry_mode,
        **extra_kwargs,
    )
    report = bind_equity_scenario(report, capital_scenario, REPO)
    target = args.output / f"{args.symbol}-{report['report_hash'][:16]}.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != report:
        raise ValueError("Immutable qualification report collision")
    target.write_bytes((json.dumps(report, indent=2) + "\n").encode())
    emit(
        {
            "event": "ICT_QUALIFICATION_RECORDED",
            "symbol": args.symbol,
            "path": str(target),
            "decision": report["decision"],
            "metrics": report["metrics"],
            "gates": report["gates"],
        }
    )


if __name__ == "__main__":
    main()
