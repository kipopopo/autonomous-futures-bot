"""Run an exact Macro Scalper development replay with explicit parameter overrides.

This runner is deliberately non-admissible: the selected development interval has
already been inspected and is not independent qualification evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.research import runtime_qualification as qualification  # noqa: E402
from autonomous_futures.strategy.macro_liquidity_scalper import (  # noqa: E402
    MacroLiquidityDipScalper,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_funding_path(cache: Path, funding: Path | None, symbol: str) -> Path:
    """Keep the funding file aligned with the selected market-data snapshot."""
    if funding is not None:
        return funding
    return cache / "funding" / f"{symbol}-funding.csv"


def mark_development_only(
    report: dict[str, Any], research_variant: dict[str, Any]
) -> dict[str, Any]:
    """Seal diagnostic metrics while making the result impossible to admit."""
    marked = dict(report)
    marked["candidate_decision_on_development_sample"] = marked.pop("decision")
    marked["decision"] = "DEVELOPMENT_ONLY"
    marked["execution_authority"] = False
    marked["research_variant"] = research_variant
    marked.pop("report_hash", None)
    marked["report_hash"] = qualification.content_hash(marked)
    return marked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=MacroLiquidityDipScalper.ALLOWED_SYMBOLS, required=True)
    parser.add_argument("--reference-report", type=Path, required=True)
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPO / "research/immutable-data/runtime-official-20261013",
    )
    parser.add_argument(
        "--filters",
        type=Path,
        default=REPO / "artifacts/qualification/runtime-inputs/testnet-exchange-filters.json",
    )
    parser.add_argument(
        "--commissions",
        type=Path,
        required=True,
        help="Authenticated Testnet commission snapshot used to freeze maker/taker fees.",
    )
    parser.add_argument("--funding", type=Path)
    parser.add_argument("--oos-start", default="2024-01-01")
    parser.add_argument(
        "--equity-evidence",
        type=Path,
        help="Use a hash-bound authenticated Testnet equity snapshot as the research sizing seed.",
    )
    parser.add_argument("--distance-threshold", type=Decimal, required=True)
    parser.add_argument("--target-atr-multiplier", type=Decimal, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not args.distance_threshold.is_finite() or args.distance_threshold >= 0:
        raise SystemExit("--distance-threshold must be finite and negative")
    if not args.target_atr_multiplier.is_finite() or args.target_atr_multiplier <= 0:
        raise SystemExit("--target-atr-multiplier must be finite and positive")

    reference = json.loads(args.reference_report.read_text(encoding="utf-8"))
    if reference.get("family") != "MACRO_SCALPER" or reference.get("symbol") != args.symbol:
        raise SystemExit("Reference report must be a Macro Scalper report for the selected symbol")
    if reference.get("decision") != "REJECTED":
        raise SystemExit("This development runner requires a rejected reference report")

    engine_factory = partial(
        MacroLiquidityDipScalper,
        dist_atr_threshold=args.distance_threshold,
        tp_atr_mult=args.target_atr_multiplier,
    )
    policy, capital_scenario = qualification.qualification_capital(
        repo=REPO,
        equity_evidence_path=args.equity_evidence,
    )
    policy, _commission_binding = qualification.bind_commission_policy(
        policy, args.commissions, args.symbol, REPO
    )
    start_ms = int(datetime.fromisoformat(args.oos_start).replace(tzinfo=UTC).timestamp() * 1000)
    with patch.object(qualification, "MacroLiquidityDipScalper", engine_factory):
        report = qualification.qualify_scalper(
            cache=args.cache,
            funding_path=resolve_funding_path(args.cache, args.funding, args.symbol),
            filters_path=args.filters,
            commissions_path=args.commissions,
            symbol=args.symbol,
            oos_start_ms=start_ms,
            repo=REPO,
            policy=policy,
        )

    report = qualification.bind_equity_scenario(report, capital_scenario, REPO)
    report.setdefault("implementation", {})["scripts/qualify_runtime_scalper_variant.py"] = digest(
        Path(__file__)
    )
    report = mark_development_only(
        report,
        {
            "status": "development_only_not_admissible",
            "reference_report": str(args.reference_report),
            "reference_report_sha256": digest(args.reference_report),
            "parameters": {
                "distance_threshold": str(args.distance_threshold),
                "target_atr_multiplier": str(args.target_atr_multiplier),
            },
            "reason": (
                "The reference interval informed selection; it is not an untouched holdout."
            ),
        },
    )
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / f"{args.symbol}-{report['report_hash'][:16]}.json"
    encoded = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError("Immutable development report collision")
    else:
        path.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "event": "DEVELOPMENT_REPLAY_RECORDED",
                "path": str(path),
                "decision": report["decision"],
                "candidate_decision_on_development_sample": report[
                    "candidate_decision_on_development_sample"
                ],
                "metrics": report["metrics"],
                "gates": report["gates"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
