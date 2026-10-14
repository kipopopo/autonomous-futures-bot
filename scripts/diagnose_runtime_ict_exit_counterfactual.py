"""Diagnostic-only follow-through analysis for CISD-invalidated ICT report trades."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.research.runtime_qualification import (  # noqa: E402
    content_hash,
    verified_bars,
)

D = Decimal


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _counterfactual(
    trade: dict[str, Any], bars: list[Any], bar_opens: list[int], window_end_ms: int
) -> dict[str, Any]:
    plan = trade["plan"]
    side = plan["side"]
    sign = D("1") if side == "BUY" else D("-1")
    entry = D(plan["entry"])
    stop = D(plan["stop"])
    tp1 = next(D(part["price"]) for part in plan["exits"] if part["role"] == "TP1")
    tp2 = next(D(part["price"]) for part in plan["exits"] if part["role"] == "TP2")
    remaining = D(plan["quantity"])
    tp1_remaining = sum(
        (D(part["quantity"]) for part in plan["exits"] if part["role"] == "TP1"), D("0")
    )
    exit_ms = trade["exits"][0]["modeled_exit_ms"]
    deadline = min(trade["modeled_entry_ms"] + plan["hold_ms"], window_end_ms)
    first = bisect.bisect_left(bar_opens, exit_ms)
    stop_deadline = min(len(bars), bisect.bisect_right(bar_opens, deadline - 300_000))
    gross = D("0")
    events: list[dict[str, str]] = []

    def close(quantity: Decimal, price: Decimal, reason: str) -> None:
        nonlocal gross, remaining
        gross += sign * quantity * (price - entry)
        remaining -= quantity
        events.append({"reason": reason, "quantity": str(quantity), "price": str(price)})

    for index in range(first, stop_deadline):
        bar = bars[index]
        if bar.timestamp_ms >= window_end_ms:
            break
        stop_hit = bar.low <= stop if side == "BUY" else bar.high >= stop
        if stop_hit:
            stop_price = min(stop, bar.open) if side == "BUY" else max(stop, bar.open)
            close(remaining, stop_price, "STOP")
            break
        target1 = bar.high > tp1 if side == "BUY" else bar.low < tp1
        target2 = bar.high > tp2 if side == "BUY" else bar.low < tp2
        if target1 and tp1_remaining:
            quantity = min(remaining, tp1_remaining)
            close(quantity, tp1, "TP1")
            tp1_remaining -= quantity
        if target2 and remaining:
            close(remaining, tp2, "TP2")
            break

    if remaining and stop_deadline > first:
        final_bar = bars[stop_deadline - 1]
        covered_by_following_data = (
            stop_deadline < len(bar_opens) and bar_opens[stop_deadline] <= deadline
        )
        reason = "TIME_OR_WINDOW_PROXY" if covered_by_following_data else "DATA_END_PROXY"
        close(remaining, final_bar.close, reason)

    if not events:
        reason = "NO_FOLLOWUP_BARS"
    elif remaining:
        reason = "PARTIAL_WITHOUT_FINAL_EXIT"
    elif len(events) > 1:
        reason = "TP1_THEN_" + events[-1]["reason"]
    else:
        reason = events[-1]["reason"]
    return {
        "symbol": plan["symbol"],
        "signal_key": plan["signal_key"],
        "entry_ms": trade["modeled_entry_ms"],
        "actual_cisd_exit_ms": exit_ms,
        "counterfactual_reason": reason,
        "gross_pnl_usdt": str(gross),
        "followup_events": events,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", type=Path, required=True)
    parser.add_argument(
        "--cache", type=Path, default=REPO / "research/immutable-data/runtime-official-20261013"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "artifacts/qualification/ict-cisd-exit-counterfactual-v2-20261013.json",
    )
    args = parser.parse_args()

    report_evidence: list[dict[str, str]] = []
    trades_by_symbol: dict[str, list[tuple[dict[str, Any], int]]] = {}
    for report_path in args.report:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        expected_hash = report.pop("report_hash")
        if content_hash(report) != expected_hash:
            raise ValueError(f"Qualification report hash mismatch: {report_path}")
        for name, expected in report["implementation"].items():
            if _digest(REPO / name) != expected:
                raise ValueError(f"Qualification implementation changed: {name}")
        report_evidence.append(
            {"path": str(report_path), "sha256": _digest(report_path), "report_hash": expected_hash}
        )
        symbol = report["symbol"]
        for window in report["windows"]:
            for trade in window["trades"]:
                if [exit_["reason"] for exit_ in trade["exits"]] == ["CISD_INVALIDATION"]:
                    trades_by_symbol.setdefault(symbol, []).append((trade, window["end_ms"]))

    results: list[dict[str, Any]] = []
    market_evidence: list[dict[str, Any]] = []
    for symbol, trades in sorted(trades_by_symbol.items()):
        bars, source = verified_bars(args.cache, symbol, "5m")
        bar_opens = [bar.timestamp_ms for bar in bars]
        market_evidence.append({"symbol": symbol, **source})
        results.extend(
            _counterfactual(trade, bars, bar_opens, window_end) for trade, window_end in trades
        )

    pnl = [D(result["gross_pnl_usdt"]) for result in results]
    reasons: dict[str, int] = {}
    for result in results:
        reason = result["counterfactual_reason"]
        reasons[reason] = reasons.get(reason, 0) + 1
    summary = {
        "diagnostic_only": True,
        "execution_authority": False,
        "excluded_from_qualification": True,
        "rule_changed": "omit only the immediate CISD_INVALIDATION close after the actual entry",
        "retained_rules": ["original stop", "original TP1/TP2", "original time/window deadline"],
        "bar_resolution": "subsequent full 5m bars beginning at or after the actual 1m CISD exit",
        "ignored_effects": [
            "fees and slippage",
            "funding payments",
            "daily-loss account interaction",
            "portfolio overlap and signals blocked by the longer holding period",
            "price path within the partial 5m bar containing the actual CISD exit",
        ],
        "report_inputs": report_evidence,
        "market_inputs": market_evidence,
        "trade_count": len(results),
        "reason_counts": reasons,
        "supersedes": "artifacts/qualification/ict-cisd-exit-counterfactual-20261013.json",
        "gross_pnl_sum_usdt": str(sum(pnl, D("0"))),
        "gross_positive_trade_count": sum(value > 0 for value in pnl),
        "gross_negative_trade_count": sum(value < 0 for value in pnl),
        "trades": results,
    }
    encoded = (json.dumps(summary, sort_keys=True, indent=2) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and args.output.read_bytes() != encoded:
        raise ValueError(f"Refusing to overwrite different diagnostic output: {args.output}")
    args.output.write_bytes(encoded)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "trades": summary["trade_count"],
                "reason_counts": reasons,
                "gross_pnl_sum_usdt": summary["gross_pnl_sum_usdt"],
                "qualification": False,
            }
        )
    )


if __name__ == "__main__":
    main()
