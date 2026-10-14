"""Freeze policy and replay canonical scalper OOS with the actual execution planner."""

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
DEFAULT_CACHE = REPO / "research/immutable-data/runtime-official-20261013"
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.research.runtime_qualification import (  # noqa: E402
    bind_commission_policy,
    bind_equity_scenario,
    content_hash,
    digest,
    qualification_capital,
    qualify_scalper,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (  # noqa: E402
    MacroLiquidityDipScalper,
)


def resolve_funding_path(cache: Path, funding: Path | None, symbol: str) -> Path:
    """Use funding from the selected snapshot unless the caller pins another file."""
    if funding is not None:
        return funding
    return cache / "funding" / f"{symbol}-funding.csv"


def bind_runner_source(report: dict[str, Any]) -> dict[str, Any]:
    """Bind CLI policy and input-selection logic into the qualification identity."""
    sealed = dict(report)
    implementation = dict(sealed.get("implementation", {}))
    implementation["scripts/qualify_runtime_scalper.py"] = digest(Path(__file__).resolve())
    sealed["implementation"] = implementation
    sealed.pop("report_hash", None)
    sealed["report_hash"] = content_hash(sealed)
    return sealed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbol", default="SOLUSDT", choices=MacroLiquidityDipScalper.ALLOWED_SYMBOLS
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE,
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
    parser.add_argument("--oos-start", default="2024-01-01")
    parser.add_argument("--funding", type=Path)
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
        "--output", type=Path, default=REPO / "artifacts/qualification/runtime-scalper"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    policy, capital_scenario = qualification_capital(
        repo=REPO,
        starting_equity=args.starting_equity,
        equity_evidence_path=args.equity_evidence,
    )
    policy, _commission_binding = bind_commission_policy(
        policy, args.commissions, args.symbol, REPO
    )
    policy_data = json.loads(json.dumps(dataclasses.asdict(policy), default=str))
    if capital_scenario is not None:
        policy_data["capital_scenario"] = capital_scenario
    policy_path = args.output / "frozen-policy.json"
    if policy_path.exists() and json.loads(policy_path.read_text(encoding="utf-8")) != policy_data:
        raise ValueError("Qualification policy changed after freezing")
    policy_path.write_text(json.dumps(policy_data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "POLICY_FROZEN", "sha256": content_hash(policy_data)}), flush=True)
    start_ms = int(datetime.fromisoformat(args.oos_start).replace(tzinfo=UTC).timestamp() * 1000)
    report = qualify_scalper(
        cache=args.cache,
        funding_path=resolve_funding_path(args.cache, args.funding, args.symbol),
        filters_path=args.filters,
        commissions_path=args.commissions,
        symbol=args.symbol,
        oos_start_ms=start_ms,
        repo=REPO,
        policy=policy,
    )
    report = bind_equity_scenario(report, capital_scenario, REPO)
    report = bind_runner_source(report)
    path = args.output / f"{args.symbol}-{report['report_hash'][:16]}.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != report:
            raise ValueError("Immutable qualification report collision")
    else:
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "event": "QUALIFICATION_RECORDED",
                "path": str(path),
                "decision": report["decision"],
                "metrics": report["metrics"],
                "gates": report["gates"],
                "rejections": report["rejection_reasons"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
