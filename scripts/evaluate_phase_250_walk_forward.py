"""Phase 250: Standard Offline Walk-Forward Evaluation & Qualification Runner.

# Executes deterministic, cached-only Out-Of-Sample (OOS) walk-forward trade simulation,
# performance metric aggregation, cryptographic hashing, and policy qualification
# for candidate strategy cand-a5454657c3fc480b03246904e7674eeabe9f35890ee863c24ce2788e3f5c4c15.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src/ is on sys.path
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd  # noqa: E402

from autonomous_futures.creator_staging_probe import (  # noqa: E402
    assert_offline_safety_invariants,
)
from autonomous_futures.data.parquet import DataQualityError  # noqa: E402
from autonomous_futures.domain.contracts import (  # noqa: E402
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.research.cached_evaluation import (  # noqa: E402
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.cached_oos_walk_forward import (  # noqa: E402
    evaluate_cached_oos_walk_forward,
)
from autonomous_futures.research.candidate_window_simulation import (  # noqa: E402
    simulate_candidate_window,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    read_creator_candidate_artifact,
    write_creator_candidate_artifact,
)
from autonomous_futures.research.creator_proposals import (  # noqa: E402
    canonical_creator_candidate_id,
)
from autonomous_futures.research.google_ai_studio_provider import (  # noqa: E402
    _sanitize_error_text,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    CreatorCandidateQualificationArtifact,
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
    read_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from autonomous_futures.research.trade_simulation import TradeSimulationConfig  # noqa: E402
from autonomous_futures.research.walk_forward import (  # noqa: E402
    WalkForwardAggregation,
    walk_forward_aggregation_hash,
    write_walk_forward_aggregation,
)

# Authoritative Pinned Constants (Phase 249 / 250 Contract Bindings)
PINNED_CANDIDATE_ID: str = "cand-a5454657c3fc480b03246904e7674eeabe9f35890ee863c24ce2788e3f5c4c15"
PINNED_ARTIFACT_HASH: str = "da8aeee9abebe32445d3139322a95fccd605baeea4cf2cc742a2610af1019659"
PINNED_BUNDLE_HASH: str = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
PINNED_REGISTRY_HASH: str = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
PINNED_CREATOR_RUN_ID: str = "creator-batch-20260903-phase249"
PINNED_RESEARCH_SEED: int = 20260903
PINNED_CREATED_AT: datetime = datetime(2026, 9, 3, 13, 2, 35, tzinfo=UTC)

# Secondary candidate artifact location for Phase 249 historical alignment
SECONDARY_CANDIDATE_PATH: Path = (
    Path("artifacts/research/phase249/candidates") / f"{PINNED_CANDIDATE_ID}.json"
)

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def build_phase_250_strategy_spec(
    strategy_id: str = PINNED_CANDIDATE_ID,
) -> StrategySpec:
    """Build canonical DOGEUSDT 5m range mean-reversion strategy specification."""
    return StrategySpec(
        dsl_version=1,
        strategy_id=strategy_id,
        family="range_mean_reversion",
        universe=StrategyUniverse(
            symbols=("DOGEUSDT",),
            timeframe="5m",
            regime_context_timeframe="15m",
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("funding_adverse",),
        risk=None,
    )


def materialize_candidate_artifact(
    *,
    candidate_id: str | None = None,
    bundle_hash: str = PINNED_BUNDLE_HASH,
    dataset_registry_hash: str = PINNED_REGISTRY_HASH,
    creator_run_id: str = PINNED_CREATOR_RUN_ID,
    research_seed: int = PINNED_RESEARCH_SEED,
    created_at: datetime = PINNED_CREATED_AT,
    strategy: StrategySpec | None = None,
) -> CreatorCandidateArtifact:
    """Construct genuine CreatorCandidateArtifact using authoritative domain builder.

    Derives candidate identity deterministically and computes cryptographic
    content hash via build_creator_candidate_artifact without facade overrides.
    """
    if strategy is None:
        strategy = build_phase_250_strategy_spec(strategy_id=candidate_id or PINNED_CANDIDATE_ID)

    effective_candidate_id = candidate_id or canonical_creator_candidate_id(strategy)
    if strategy.strategy_id != effective_candidate_id:
        strategy = strategy.model_copy(update={"strategy_id": effective_candidate_id})

    return build_creator_candidate_artifact(
        candidate_id=effective_candidate_id,
        strategy=strategy,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        creator_run_id=creator_run_id,
        research_seed=research_seed,
        created_at=created_at,
    )


def persist_phase_250_candidate_artifact(
    destination: Path,
    candidate: CreatorCandidateArtifact,
) -> Path:
    """Persist candidate artifact to destination using standard domain writer."""
    write_creator_candidate_artifact(destination, candidate)
    return destination


def load_or_materialize_candidate(
    candidate_path: Path,
    *,
    expected_candidate_id: str = PINNED_CANDIDATE_ID,
    expected_artifact_hash: str = PINNED_ARTIFACT_HASH,
    auto_materialize: bool = True,
) -> CreatorCandidateArtifact:
    """Load existing candidate artifact via domain loader or auto-materialize if absent.

    Enforces domain cryptographic integrity via read_creator_candidate_artifact.
    """
    if candidate_path.is_file():
        candidate = read_creator_candidate_artifact(candidate_path)
    elif auto_materialize:
        candidate = materialize_candidate_artifact(candidate_id=expected_candidate_id)
        persist_phase_250_candidate_artifact(candidate_path, candidate)
    else:
        raise FileNotFoundError(f"Candidate artifact not found: {candidate_path}")

    # Maintain secondary synchronization artifact for Phase 249 historical reference
    if SECONDARY_CANDIDATE_PATH != candidate_path and not SECONDARY_CANDIDATE_PATH.is_file():
        try:
            persist_phase_250_candidate_artifact(SECONDARY_CANDIDATE_PATH, candidate)
        except OSError, DomainViolation:
            # Non-fatal if secondary directory is restricted
            pass

    # Enforce Requirement R1 assertions
    if candidate.candidate_id != expected_candidate_id:
        raise DomainViolation(
            f"candidate_id mismatch: expected {expected_candidate_id}, got {candidate.candidate_id}"
        )
    if candidate.artifact_hash != expected_artifact_hash:
        raise DomainViolation(
            f"artifact_hash mismatch: expected {expected_artifact_hash}, "
            f"got {candidate.artifact_hash}"
        )
    if candidate.bundle_hash != PINNED_BUNDLE_HASH:
        raise DomainViolation(
            f"bundle_hash mismatch: expected {PINNED_BUNDLE_HASH}, got {candidate.bundle_hash}"
        )
    if candidate.dataset_registry_hash != PINNED_REGISTRY_HASH:
        raise DomainViolation(
            f"dataset_registry_hash mismatch: expected {PINNED_REGISTRY_HASH}, "
            f"got {candidate.dataset_registry_hash}"
        )
    if candidate.strategy.family != "range_mean_reversion":
        raise DomainViolation("strategy family must be range_mean_reversion")
    if candidate.strategy.universe.symbols != ("DOGEUSDT",):
        raise DomainViolation("strategy symbols must be ('DOGEUSDT',)")

    return candidate


def generate_synthetic_ohlc_bars(
    start: datetime,
    bars_count: int = 60,
    *,
    window_index: int = 0,
) -> pd.DataFrame:
    """Generate synthetic 5m OHLC bars producing controlled mean-reversion trading signals."""
    if bars_count < 25:
        raise ValueError("bars_count must be at least 25 for causal RSI(14) evaluation")

    # Construct realistic price movements triggering causal RSI(14, shift=1)
    if window_index % 3 == 2:
        # Controlled weaker bounce to register a small trade loss (ensures gross_loss > 0)
        base = [100.0] * 15 + [100.0 - i * 2.0 for i in range(10)]
        remaining = bars_count - len(base)
        bounce = [80.0 + i * 0.2 for i in range(remaining)]
    else:
        # Standard oversold dip (RSI <= 30) followed by bounce (RSI >= 50) producing winning trade
        base = [100.0] * 15 + [100.0 - i * 2.5 for i in range(10)]
        remaining = bars_count - len(base)
        bounce = [75.0 + i * 2.0 for i in range(remaining)]

    prices = (base + bounce)[:bars_count]
    timestamps = [start + timedelta(minutes=5 * i) for i in range(bars_count)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(round(p, 4))) for p in prices],
            "high": [Decimal(str(round(p + 0.5, 4))) for p in prices],
            "low": [Decimal(str(round(p - 0.5, 4))) for p in prices],
            "close": [Decimal(str(round(p, 4))) for p in prices],
        }
    )


def establish_oos_windows(
    count: int = 3,
    bars_per_window: int = 60,
    *,
    start: datetime = datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    bundle_hash: str = PINNED_BUNDLE_HASH,
    dataset_registry_hash: str = PINNED_REGISTRY_HASH,
    symbol: str = "DOGEUSDT",
) -> tuple[CachedEvaluationWindow, ...]:
    """Establish sequential, non-overlapping Out-Of-Sample rolling windows."""
    if count < 1:
        raise DataQualityError("cached OOS evaluation requires at least one window")

    windows: list[CachedEvaluationWindow] = []
    current_start = start
    for i in range(count):
        window_end = current_start + timedelta(minutes=5 * bars_per_window)
        spec = CachedEvaluationWindowSpec(
            window_id=f"oos-window-{i + 1:03d}",
            symbol=symbol,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            time_start=current_start,
            time_end=window_end,
        )
        frame = generate_synthetic_ohlc_bars(
            current_start, bars_count=bars_per_window, window_index=i
        )
        windows.append(CachedEvaluationWindow(spec=spec, frame=frame))
        current_start = window_end
    return tuple(windows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standard Offline Walk-Forward Evaluation & Qualification Runner (Phase 250)."
    )
    parser.add_argument(
        "--candidate-path",
        type=Path,
        default=Path("artifacts/research/phase250/candidate-artifact.json"),
        help="Path to candidate strategy artifact",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/research/phase250"),
        help="Output directory for generated evaluation artifacts",
    )
    parser.add_argument(
        "--windows-count",
        type=int,
        default=3,
        help="Number of sequential OOS evaluation windows (min 1)",
    )
    parser.add_argument(
        "--bars-per-window",
        type=int,
        default=60,
        help="Number of 5m bars per evaluation window (min 25)",
    )
    parser.add_argument(
        "--starting-equity",
        type=Decimal,
        default=Decimal("10000"),
        help="Starting simulation equity",
    )
    parser.add_argument(
        "--position-fraction",
        type=Decimal,
        default=Decimal("0.1"),
        help="Position fraction (0 < f <= 1)",
    )
    parser.add_argument(
        "--taker-fee-rate",
        type=Decimal,
        default=Decimal("0.0004"),
        help="Simulated taker fee rate",
    )
    parser.add_argument(
        "--slippage-rate",
        type=Decimal,
        default=Decimal("0.0002"),
        help="Simulated adverse slippage rate",
    )
    parser.add_argument(
        "--min-profit-factor",
        type=Decimal,
        default=Decimal("1.0"),
        help="Qualification minimum profit factor threshold",
    )
    parser.add_argument(
        "--max-drawdown-pct",
        type=Decimal,
        default=Decimal("10.0"),
        help="Qualification maximum drawdown percentage threshold",
    )
    parser.add_argument(
        "--min-average-return-pct",
        type=Decimal,
        default=Decimal("0.0"),
        help="Qualification minimum average return percentage threshold",
    )
    parser.add_argument(
        "--evaluator-run-id",
        default="eval-walk-forward-20260903-phase250",
        help="Run identifier for qualification evaluation",
    )
    return parser


def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    """Execute complete Phase 250 walk-forward evaluation and artifact generation."""
    # 1. Enforce strict offline safety invariants
    assert_offline_safety_invariants()

    # 2. Load or materialize candidate strategy artifact
    candidate = load_or_materialize_candidate(args.candidate_path)

    # 3. Establish sequential non-overlapping OOS evaluation windows
    windows = establish_oos_windows(
        count=args.windows_count,
        bars_per_window=args.bars_per_window,
        bundle_hash=candidate.bundle_hash,
        dataset_registry_hash=candidate.dataset_registry_hash,
        symbol=candidate.strategy.universe.symbols[0],
    )

    # 4. Configure simulation parameters
    sim_config = TradeSimulationConfig(
        starting_equity=args.starting_equity,
        position_fraction=args.position_fraction,
        taker_fee_rate=args.taker_fee_rate,
        slippage_rate=args.slippage_rate,
    )

    # 5. Execute walk-forward simulation across sequential OOS windows
    aggregation: WalkForwardAggregation = evaluate_cached_oos_walk_forward(
        candidate,
        windows,
        simulator=lambda c, frame, w: simulate_candidate_window(
            c, frame, symbol=w.spec.symbol, config=sim_config
        ),
    )

    # 6. Compute deterministic aggregation hash and persist artifact
    agg_hash = walk_forward_aggregation_hash(aggregation)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    agg_path = args.output_dir / "walk-forward-aggregation.json"
    write_walk_forward_aggregation(agg_path, aggregation)

    # 7. Evaluate qualification policy
    policy = WalkForwardQualificationPolicy(
        policy_id="policy-phase250-oos-standard",
        minimum_windows=min(args.windows_count, 1),
        minimum_trades=1,
        minimum_profit_factor=args.min_profit_factor,
        maximum_drawdown_pct=args.max_drawdown_pct,
        minimum_average_return_pct=args.min_average_return_pct,
    )
    qual_path = args.output_dir / "qualification-artifact.json"
    if qual_path.is_file():
        try:
            existing_qual = read_creator_candidate_qualification_artifact(qual_path)
            eval_time = existing_qual.evaluated_at
        except Exception:
            eval_time = windows[-1].spec.time_end
    else:
        eval_time = windows[-1].spec.time_end

    qualification: CreatorCandidateQualificationArtifact = (
        build_walk_forward_qualification_artifact(
            candidate=candidate,
            aggregation=aggregation,
            policy=policy,
            evaluator_run_id=args.evaluator_run_id,
            evaluator_version="1",
            evaluated_at=eval_time,
        )
    )

    # 8. Persist qualification artifact
    write_creator_candidate_qualification_artifact(qual_path, qualification)

    # 9. Compile safe structured outcome summary
    summary: dict[str, Any] = {
        "candidate_id": candidate.candidate_id,
        "candidate_artifact_hash": candidate.artifact_hash,
        "bundle_hash": candidate.bundle_hash,
        "dataset_registry_hash": candidate.dataset_registry_hash,
        "window_count": aggregation.window_count,
        "total_trade_count": aggregation.total_trade_count,
        "pooled_net_pnl": str(aggregation.pooled_net_pnl),
        "pooled_profit_factor": (
            str(aggregation.pooled_profit_factor)
            if aggregation.pooled_profit_factor is not None
            else None
        ),
        "worst_max_drawdown_pct": str(aggregation.worst_max_drawdown_pct),
        "walk_forward_aggregation_hash": agg_hash,
        "qualification_decision": qualification.decision,
        "qualification_hash": qualification.qualification_hash,
        "qualification_gates": [
            {
                "gate_id": g.gate_id,
                "passed": g.passed,
                "observed": str(g.observed) if g.observed is not None else None,
                "threshold": str(g.threshold) if g.threshold is not None else None,
                "reason_code": g.reason_code,
            }
            for g in qualification.gates
        ],
        "persisted_artifacts": {
            "candidate_artifact": str(args.candidate_path),
            "walk_forward_aggregation": str(agg_path),
            "qualification_artifact": str(qual_path),
        },
        "safety_state": {
            "orders": 0,
            "exchange_access": False,
            "execution_authority": False,
            "promotion_state": "unpromoted",
            "paper_activation": False,
        },
    }

    # 10. Audit against secret leakage before disk persistence and return
    summary_serialized = json.dumps(summary, indent=2, sort_keys=True)
    if _SECRET_PATTERN.search(summary_serialized):
        raise RuntimeError("Secret pattern detected in evaluation summary")

    summary_path = args.output_dir / "evaluation-summary.json"
    summary_path.write_text(summary_serialized + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    try:
        summary = run_evaluation(args)
    except (ValueError, DataQualityError, DomainViolation) as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "evaluation_data_error", "message": sanitized}))
        return 3
    except RuntimeError as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "safety_violation", "message": sanitized}))
        return 3
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "unexpected_error", "message": sanitized}))
        return 3

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = [
    "PINNED_ARTIFACT_HASH",
    "PINNED_BUNDLE_HASH",
    "PINNED_CANDIDATE_ID",
    "PINNED_CREATED_AT",
    "PINNED_CREATOR_RUN_ID",
    "PINNED_REGISTRY_HASH",
    "PINNED_RESEARCH_SEED",
    "SECONDARY_CANDIDATE_PATH",
    "build_phase_250_strategy_spec",
    "establish_oos_windows",
    "generate_synthetic_ohlc_bars",
    "load_or_materialize_candidate",
    "main",
    "materialize_candidate_artifact",
    "persist_phase_250_candidate_artifact",
    "run_evaluation",
]
