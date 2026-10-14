"""Run shared-wallet multi-symbol portfolio qualification with exact Decimal accounting."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.research.portfolio_qualification import (  # noqa: E402
    PortfolioMemberSpec,
    qualify_scalper_portfolio,
)
from autonomous_futures.research.runtime_qualification import (  # noqa: E402
    bind_equity_scenario,
    qualification_capital,
)

D = Decimal


def _parse_member_spec(raw: str) -> PortfolioMemberSpec:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) == 1:
        symbol = parts[0].upper()
        return PortfolioMemberSpec(
            member_id=f"macro-scalper-{symbol.lower()}-baseline",
            symbol=symbol,
        )
    if len(parts) == 3:
        symbol = parts[0].upper()
        dist = D(parts[1])
        tp = D(parts[2])
        return PortfolioMemberSpec(
            member_id=f"macro-scalper-{symbol.lower()}-d{dist}-t{tp}",
            symbol=symbol,
            distance_threshold=dist,
            target_atr_multiplier=tp,
        )
    if len(parts) == 7:
        symbol = parts[0].upper()
        dist, tp, sl, rsi, vol = D(parts[1]), D(parts[2]), D(parts[3]), D(parts[4]), D(parts[5])
        hold = int(parts[6])
        return PortfolioMemberSpec(
            member_id=(
                f"macro-scalper-{symbol.lower()}-d{dist}-t{tp}-sl{sl}-r{rsi}-v{vol}-h{hold}"
            ),
            symbol=symbol,
            distance_threshold=dist,
            target_atr_multiplier=tp,
            stop_atr_multiplier=sl,
            rsi_threshold=rsi,
            vol_spike_multiplier=vol,
            max_hold_bars=hold,
        )
    if len(parts) == 8:
        member_id = parts[0]
        symbol = parts[1].upper()
        dist, tp, sl, rsi, vol = D(parts[2]), D(parts[3]), D(parts[4]), D(parts[5]), D(parts[6])
        hold = int(parts[7])
        return PortfolioMemberSpec(
            member_id=member_id,
            symbol=symbol,
            distance_threshold=dist,
            target_atr_multiplier=tp,
            stop_atr_multiplier=sl,
            rsi_threshold=rsi,
            vol_spike_multiplier=vol,
            max_hold_bars=hold,
        )
    raise ValueError(
        "Member spec must be SYMBOL, SYMBOL:DIST:TP, "
        "SYMBOL:DIST:TP:SL:RSI:VOL:HOLD, or MEMBER_ID:SYMBOL:DIST:TP:SL:RSI:VOL:HOLD"
    )


def _members_from_selection(path: Path) -> list[PortfolioMemberSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    selected = data.get("selected_candidates") or data.get("members") or []
    if not isinstance(selected, list) or not selected:
        raise ValueError(f"Selection manifest contains no selected_candidates: {path}")
    members: list[PortfolioMemberSpec] = []
    for entry in selected:
        params = entry.get("parameters", entry)
        member_id = str(entry.get("member_id") or entry["candidate_id"])
        members.append(
            PortfolioMemberSpec(
                member_id=member_id,
                symbol=str(entry["symbol"]).upper(),
                family=str(entry.get("family", "MACRO_SCALPER")),
                distance_threshold=D(str(params.get("distance_threshold", "-2.5"))),
                target_atr_multiplier=D(str(params.get("target_atr_multiplier", "2.0"))),
                stop_atr_multiplier=D(str(params.get("stop_atr_multiplier", "1.2"))),
                rsi_threshold=D(str(params.get("rsi_threshold", "26.0"))),
                vol_spike_multiplier=D(str(params.get("vol_spike_multiplier", "2.2"))),
                max_hold_bars=int(params.get("max_hold_bars", 8)),
            )
        )
    return members


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPO / "research/immutable-data/runtime-official-20261013",
    )
    parser.add_argument(
        "--funding-dir",
        type=Path,
        default=REPO / "research/immutable-data/runtime-official-20261013/funding",
    )
    parser.add_argument(
        "--filters",
        type=Path,
        default=REPO / "artifacts/qualification/runtime-inputs/testnet-exchange-filters.json",
    )
    parser.add_argument(
        "--commissions",
        type=Path,
        default=REPO
        / "artifacts/qualification/runtime-inputs/testnet-commissions-1791824521337.json",
    )
    parser.add_argument(
        "--selection-manifest",
        type=Path,
        help="Optional frozen selected-candidates manifest to load portfolio members from.",
    )
    parser.add_argument(
        "--member",
        action="append",
        default=[],
        help="Explicit portfolio member spec SYMBOL or SYMBOL:DIST:TP (repeatable).",
    )
    parser.add_argument("--oos-start", default="2024-01-01")
    parser.add_argument("--oos-end-exclusive", default=None)
    capital = parser.add_mutually_exclusive_group()
    capital.add_argument("--starting-equity", type=Decimal)
    capital.add_argument("--equity-evidence", type=Path)
    parser.add_argument(
        "--development-only",
        action="store_true",
        default=False,
        help=(
            "Mark report decision as DEVELOPMENT_ONLY when replaying "
            "an inspected development interval."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "artifacts/qualification/portfolio-scalper",
    )
    args = parser.parse_args()

    members: list[PortfolioMemberSpec] = []
    if args.selection_manifest is not None:
        members.extend(_members_from_selection(args.selection_manifest))
    for spec_str in args.member:
        members.append(_parse_member_spec(spec_str))
    if not members:
        raise ValueError("Provide --selection-manifest and/or at least one --member")

    policy, capital_scenario = qualification_capital(
        repo=REPO,
        starting_equity=args.starting_equity,
        equity_evidence_path=args.equity_evidence,
    )
    start_ms = int(datetime.fromisoformat(args.oos_start).replace(tzinfo=UTC).timestamp() * 1000)
    end_ms = (
        int(datetime.fromisoformat(args.oos_end_exclusive).replace(tzinfo=UTC).timestamp() * 1000)
        if args.oos_end_exclusive
        else None
    )

    report: dict[str, Any] = qualify_scalper_portfolio(
        cache=args.cache,
        funding_dir=args.funding_dir,
        filters_path=args.filters,
        commissions_path=args.commissions,
        members=members,
        oos_start_ms=start_ms,
        oos_end_ms=end_ms,
        repo=REPO,
        policy=policy,
    )
    report = bind_equity_scenario(report, capital_scenario, REPO)
    if args.development_only or args.oos_start < "2026-08-01":
        from autonomous_futures.research.runtime_qualification import content_hash

        report["portfolio_decision_on_development_sample"] = report.pop("decision")
        report["decision"] = "DEVELOPMENT_ONLY"
        report["execution_authority"] = False
        report.pop("report_hash", None)
        report["report_hash"] = content_hash(report)

    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / f"portfolio-{report['report_hash'][:16]}.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != report:
        raise ValueError("Immutable portfolio qualification report collision")
    path.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(
        json.dumps(
            {
                "event": "PORTFOLIO_QUALIFICATION_RECORDED",
                "path": str(path),
                "decision": report["decision"],
                "portfolio_decision_on_development_sample": report.get(
                    "portfolio_decision_on_development_sample"
                ),
                "execution_authority": report["execution_authority"],
                "symbols": report["symbols"],
                "metrics": report["metrics"],
                "gates": report["gates"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
