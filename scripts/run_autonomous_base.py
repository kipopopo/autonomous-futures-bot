"""scripts/run_autonomous_base.py

Supported finite CLI entrypoint for Autonomous Research Base (R2).
Orchestrates multi-cycle offline research with deterministic bounded cycles:
- Preflights credentials safely without exposing secrets.
- Enforces zero network and offline cached-only execution by default.
- Rejects partial, tampered, or out-of-order checkpoints.
- Tracks forbidden candidate IDs and thesis fingerprints across cycles.
- Persists typed cycle records, failure memories, and final base result.
- Provides clean deterministic stop reasons (max_cycles, qualified, stopped).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

# Ensure src/ is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.data.parquet import (  # noqa: E402
    DataQualityError,
    read_canonical_parquet,
)
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.pipeline.autonomous_base import (  # noqa: E402
    AutonomousBaseConfig,
    AutonomousResearchBase,
    make_autonomous_cycle_runner,
)
from autonomous_futures.research.autonomy_contracts import (  # noqa: E402
    FailureLearner,
    FailureLearningRequest,
    FailureLearningTransport,
    ResearchPlanner,
    ResearchPlanRequest,
    ResearchPlanTransport,
)
from autonomous_futures.research.cached_evaluation import (  # noqa: E402
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.creator_failure_feedback import (  # noqa: E402
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.creator_generator import (  # noqa: E402
    CreatorGenerationRequest,
)
from autonomous_futures.research.google_ai_studio_provider import resolve_credential  # noqa: E402
from autonomous_futures.research.learner_critic import (  # noqa: E402
    LearnerCriticRequest,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    QualificationGateResult,
    WalkForwardQualificationPolicy,
)

FORBIDDEN_CREDENTIAL_FLAGS = (
    "--api-key",
    "--api_key",
    "--key",
    "-key",
    "--apikey",
    "--google-api-key",
    "--google_api_key",
    "--gemini-api-key",
    "--gemini_api_key",
    "--google-ai-studio-api-key",
    "--token",
    "--api-token",
    "-k",
    "--secret",
    "--secret-key",
    "--secret_key",
    "--password",
    "--bearer",
    "--auth-token",
    "--auth_token",
    "--binance-api-key",
    "--binance_api_key",
    "--binance-api-secret",
    "--binance_api_secret",
)

DEFAULT_BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
DEFAULT_REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"


def _check_forbidden_credential_flags(argv: Sequence[str]) -> bool:
    """Inspect raw CLI arguments for forbidden credential flags."""
    for arg in argv:
        prefix = arg.lower().split("=")[0].strip()
        if prefix in FORBIDDEN_CREDENTIAL_FLAGS:
            return True
    return False


def _build_default_seed_feedback(
    *,
    symbol: str,
    bundle_hash: str,
    dataset_registry_hash: str,
) -> CreatorQualificationFailureFeedback:
    """Build a deterministic seed failure feedback when no external feedback is provided."""
    return CreatorQualificationFailureFeedback(
        candidate_id="cand-seed-001",
        candidate_artifact_hash="a" * 64,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        qualification_hash="c" * 64,
        qualification_policy_id="policy-seed-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.85"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )


def _offline_learner_transport(request: FailureLearningRequest) -> Mapping[str, Any]:
    """Deterministic offline learner transport."""
    return {
        "failure_patterns": ["oos_profit_factor_below_threshold"],
        "learned_constraints": ["preserve_all_qualification_gates"],
        "recommended_novelty_dimensions": ["entry_logic", "feature_set"],
    }


def _offline_planner_transport(request: ResearchPlanRequest) -> Mapping[str, Any]:
    """Deterministic offline planner transport."""
    return {
        "hypothesis": (
            "Use adaptive volatility entry confirmation with trend filter "
            f"(cycle {request.cycle_index})."
        ),
        "expected_regime": "volatile_trend",
        "strategy_family": "volume_confirmed_momentum",
        "novelty_dimensions": ["entry_logic", "feature_set"],
        "falsification_criteria": [
            "reject if OOS profit factor remains below the pinned policy",
            "reject if any walk-forward window has zero trades",
        ],
    }


class DeterministicOfflineCritic:
    """Deterministic critic transport matching LearnerCritique schema."""

    def __call__(self, request: LearnerCriticRequest) -> Mapping[str, object]:
        cid = request.candidate_id.lower().replace("_", "-")
        review_id = f"review-{cid}"[:64]
        return {
            "review_id": review_id,
            "research_run_id": request.research_run_id,
            "candidate_id": request.candidate_id,
            "decision": "revise",
            "failure_reason_codes": sorted(set(request.feedback.failure_reason_codes)),
            "revision_actions": sorted(["adjust_stop_multiplier", "adjust_take_profit_multiplier"]),
        }


class DeterministicOfflineCreator:
    """Deterministic creator proposal transport matching CreatorProposal schema."""

    def __call__(self, request: CreatorGenerationRequest) -> Mapping[str, object]:
        plan = request.research_plan
        symbol = plan.symbol if plan is not None else "BTCUSDT"
        cycle_ref = request.research_run_id
        candidate_suffix = (
            "002"
            if request.forbidden_candidate_ids
            and f"cand-{symbol.lower()}-revised-001" in request.forbidden_candidate_ids
            else "001"
        )
        cand_id = f"cand-{symbol.lower()}-revised-{candidate_suffix}"[:64]
        strategy_family = (
            plan.strategy_family
            if plan is not None
            and plan.strategy_family
            in (
                "regime_gated_breakout",
                "range_mean_reversion",
                "donchian_channel_breakout",
                "volatility_compression_breakout",
                "volume_confirmed_momentum",
                "experimental",
            )
            else "experimental"
        )
        hypothesis = (
            plan.hypothesis
            if plan is not None
            else f"Adjusting ATR multipliers to capture momentum on 5m {symbol} bars"
        )
        expected_regime = plan.expected_regime if plan is not None else "trending"

        if strategy_family == "volatility_compression_breakout":
            features: list[dict[str, object]] = [
                {"name": "donchian_breakout", "lookback": 20, "shift": 1},
                {"name": "bollinger_width", "lookback": 20, "shift": 1},
            ]
            entry: dict[str, str] = {
                "long": "donchian_breakout > 0.0 and bollinger_width < 0.05",
                "short": "donchian_breakout < 0.0 and bollinger_width < 0.05",
            }
            exit: dict[str, str] = {
                "long": "donchian_breakout < 0.0",
                "short": "donchian_breakout > 0.0",
            }
        else:
            features = [{"name": "returns", "lookback": 3, "shift": 1}]
            entry = {"long": "returns > 0.001", "short": "returns < -0.001"}
            exit = {"long": "returns < -0.001", "short": "returns > 0.001"}

        strategy_payload: dict[str, object] = {
            "dsl_version": 2,
            "strategy_id": cand_id,
            "family": strategy_family,
            "universe": {
                "symbols": [symbol],
                "timeframe": "5m",
                "regime_context_timeframe": "15m",
            },
            "features": features,
            "entry": entry,
            "exit": exit,
            "vetoes": ["testing_only_no_promotion"],
            "risk": {
                "position_fraction": Decimal("0.10"),
                "stop_atr_multiplier": Decimal("2.0"),
                "take_profit_atr_multiplier": Decimal("3.0"),
                "trailing_atr_multiplier": Decimal("1.0"),
            },
        }
        return {
            "proposal_id": f"proposal-{symbol.lower()}-{cycle_ref}"[:64],
            "research_run_id": request.research_run_id,
            "hypothesis": hypothesis,
            "expected_regime": expected_regime,
            "novelty_reason": "Deterministic revision guided by plan and critic review",
            "strategy": strategy_payload,
        }


def load_and_slice_windows(
    parquet_path: Path,
    *,
    symbol: str,
    bundle_hash: str,
    dataset_registry_hash: str,
    windows_count: int,
    bars_per_window: int,
) -> tuple[CachedEvaluationWindow, ...]:
    if not parquet_path.is_file():
        raise FileNotFoundError(f"Canonical Parquet file not found: {parquet_path}")
    df = read_canonical_parquet(parquet_path, interval=timedelta(minutes=5))
    total_bars = windows_count * bars_per_window
    if len(df) < total_bars:
        raise DataQualityError(
            f"Insufficient bars in {parquet_path}: requested {total_bars} "
            f"({windows_count}x{bars_per_window}), found {len(df)}"
        )
    selected = df.iloc[-total_bars:].copy().reset_index(drop=True)
    windows: list[CachedEvaluationWindow] = []
    for i in range(windows_count):
        start_idx = i * bars_per_window
        end_idx = (i + 1) * bars_per_window
        sub = selected.iloc[start_idx:end_idx].copy().reset_index(drop=True)
        time_start = sub["timestamp"].iloc[0].to_pydatetime()
        time_end = sub["timestamp"].iloc[-1].to_pydatetime() + timedelta(minutes=5)
        spec = CachedEvaluationWindowSpec(
            window_id=f"window-{symbol.lower()}-{i + 1:03d}",
            symbol=symbol,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            time_start=time_start,
            time_end=time_end,
        )
        windows.append(CachedEvaluationWindow(spec=spec, frame=sub))
    return tuple(windows)


def _make_default_windows(
    symbol: str,
    bundle_hash: str,
    dataset_registry_hash: str,
    bars_count: int = 50,
) -> tuple[CachedEvaluationWindow, ...]:
    """Create default evaluation windows with canonical 5m bars for offline base execution."""
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    spec = CachedEvaluationWindowSpec(
        window_id="win-base-cli-001",
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        time_start=start,
        time_end=start + timedelta(minutes=5 * bars_count),
    )
    closes = [Decimal("100") + Decimal(str(i * 0.1)) for i in range(bars_count)]
    frame = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * i) for i in range(bars_count)],
            "open": closes,
            "high": [c + Decimal("0.5") for c in closes],
            "low": [c - Decimal("0.5") for c in closes],
            "close": closes,
        }
    )
    window = CachedEvaluationWindow(spec=spec, frame=frame)
    return (window,)


def make_offline_learner_transport(learning_file: Path | None = None) -> FailureLearningTransport:
    durable_payload: dict[str, Any] | None = None
    if learning_file is not None and learning_file.is_file():
        raw = json.loads(learning_file.read_text(encoding="utf-8"))
        durable_payload = {
            "failure_patterns": sorted(
                raw.get("failure_patterns", ["oos_profit_factor_below_threshold"])
            ),
            "learned_constraints": sorted(
                raw.get("learned_constraints", ["preserve_all_qualification_gates"])
            ),
            "recommended_novelty_dimensions": sorted(
                raw.get("recommended_novelty_dimensions", ["entry_logic", "feature_set"])
            ),
        }

    def transport(request: FailureLearningRequest) -> Mapping[str, Any]:
        if durable_payload is not None and request.cycle_index == 1:
            return durable_payload
        return _offline_learner_transport(request)

    return transport


def make_offline_planner_transport(plan_file: Path | None = None) -> ResearchPlanTransport:
    durable_payload: dict[str, Any] | None = None
    if plan_file is not None and plan_file.is_file():
        raw = json.loads(plan_file.read_text(encoding="utf-8"))
        durable_payload = {
            "hypothesis": raw["hypothesis"],
            "expected_regime": raw["expected_regime"],
            "strategy_family": raw["strategy_family"],
            "novelty_dimensions": sorted(raw["novelty_dimensions"]),
            "falsification_criteria": sorted(raw["falsification_criteria"]),
        }

    def transport(request: ResearchPlanRequest) -> Mapping[str, Any]:
        if durable_payload is not None and request.cycle_index == 1:
            return durable_payload
        return _offline_planner_transport(request)

    return transport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomous Research Base CLI Runner (R2).")
    parser.add_argument(
        "--base-run-id",
        default=None,
        help="Unique base run ID (e.g. base-cli-001). Generated if omitted.",
    )
    parser.add_argument(
        "--symbol",
        default="BTCUSDT",
        help="Target market symbol (e.g. BTCUSDT)",
    )
    parser.add_argument(
        "--bundle-hash",
        default=DEFAULT_BUNDLE_HASH,
        help="64-character hex dataset bundle hash",
    )
    parser.add_argument(
        "--dataset-registry-hash",
        default=DEFAULT_REGISTRY_HASH,
        help="64-character hex dataset registry hash",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Directory to persist cycle records and research base results",
    )
    parser.add_argument(
        "--feedback-file",
        type=Path,
        default=None,
        help="Optional path to initial CreatorQualificationFailureFeedback JSON",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=2,
        choices=(1, 2, 3, 4, 5),
        help="Maximum number of research cycles to execute (1 to 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preflight environment, inputs, and configuration without running cycles",
    )
    parser.add_argument(
        "--parquet-path",
        type=Path,
        default=None,
        help="Optional path to canonical 5m Parquet data file",
    )
    parser.add_argument(
        "--windows-count",
        type=int,
        default=None,
        help="Number of evaluation windows",
    )
    parser.add_argument(
        "--bars-per-window",
        type=int,
        default=None,
        help="Number of 5m bars per evaluation window",
    )
    parser.add_argument(
        "--learning-file",
        type=Path,
        default=None,
        help="Optional path to durable FailureLearningArtifact JSON to seed cycle 1",
    )
    parser.add_argument(
        "--plan-file",
        type=Path,
        default=None,
        help="Optional path to durable ResearchPlan JSON to seed cycle 1",
    )
    parser.add_argument(
        "--use-synthetic-windows",
        action="store_true",
        default=False,
        help="Force synthetic windows even if canonical parquet is available",
    )
    parser.add_argument(
        "--min-profit-factor",
        type=Decimal,
        default=Decimal("1.10"),
        help="Qualification minimum profit factor (default: 1.10)",
    )
    parser.add_argument(
        "--max-drawdown-pct",
        type=Decimal,
        default=Decimal("0.15"),
        help="Qualification maximum drawdown percentage (default: 0.15)",
    )
    parser.add_argument(
        "--min-average-return-pct",
        type=Decimal,
        default=Decimal("0.0"),
        help="Qualification minimum average return percentage (default: 0.0)",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=1,
        help="Qualification minimum trades (default: 1)",
    )
    parser.add_argument(
        "--min-windows",
        type=int,
        default=1,
        help="Qualification minimum windows (default: 1)",
    )
    parser.add_argument(
        "--policy-id",
        type=str,
        default="policy-offline-wf-001",
        help="Walk-forward qualification policy identifier",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else list(argv)

    # Security check: never accept credential flags via CLI arguments
    if _check_forbidden_credential_flags(raw_argv):
        sys.stderr.write(
            "CRITICAL: Credentials must NOT be supplied via CLI flags. "
            "Use environment variables or Secret Manager.\n"
        )
        return 3

    parser = build_parser()
    try:
        args = parser.parse_args(raw_argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    base_run_id = args.base_run_id
    if base_run_id is None and args.artifact_root is not None:
        existing_res = args.artifact_root / "base-result.json"
        if existing_res.is_file():
            try:
                res_data = json.loads(existing_res.read_text(encoding="utf-8"))
                loaded_id = res_data.get("base_run_id")
                if isinstance(loaded_id, str) and loaded_id.startswith("base-"):
                    base_run_id = loaded_id
            except Exception:
                pass
    if base_run_id is None:
        base_run_id = f"base-{uuid4().hex[:16]}"
    artifact_root = args.artifact_root or Path("artifacts") / "autonomous_base" / base_run_id

    # Safe credential preflight (no secrets exposed or printed)
    cred_resolved = False
    try:
        cred = resolve_credential()
        cred_resolved = bool(cred and len(cred) >= 10)
    except Exception:
        cred_resolved = False

    # Feedback initialization
    initial_feedback: CreatorQualificationFailureFeedback
    if args.feedback_file is not None:
        if not args.feedback_file.exists():
            sys.stderr.write(f"ERROR: Feedback file not found: {args.feedback_file}\n")
            return 1
        try:
            feedback_data = json.loads(args.feedback_file.read_text(encoding="utf-8"))
            initial_feedback = CreatorQualificationFailureFeedback.model_validate(feedback_data)
        except Exception as exc:
            sys.stderr.write(f"ERROR: Invalid feedback file schema: {exc}\n")
            return 1
    else:
        initial_feedback = _build_default_seed_feedback(
            symbol=args.symbol,
            bundle_hash=args.bundle_hash,
            dataset_registry_hash=args.dataset_registry_hash,
        )

    # Base configuration validation
    try:
        config = AutonomousBaseConfig(
            base_run_id=base_run_id,
            symbol=args.symbol,
            bundle_hash=args.bundle_hash,
            dataset_registry_hash=args.dataset_registry_hash,
            artifact_root=artifact_root,
            max_cycles=args.max_cycles,
            data_source="cached_only",
            promotion_state="unpromoted",
            paper_activation=False,
            execution_authority=False,
            exchange_access=False,
        )
    except Exception as exc:
        sys.stderr.write(f"ERROR: Configuration validation failed: {exc}\n")
        return 1

    preflight_report = {
        "status": "preflight_passed",
        "base_run_id": config.base_run_id,
        "symbol": config.symbol,
        "bundle_hash": config.bundle_hash,
        "dataset_registry_hash": config.dataset_registry_hash,
        "artifact_root": str(config.artifact_root),
        "max_cycles": config.max_cycles,
        "credential_preflight_ok": cred_resolved,
        "feedback_seed_candidate": initial_feedback.candidate_id,
        "dry_run": args.dry_run,
    }

    if args.dry_run:
        sys.stdout.write(json.dumps(preflight_report, indent=2) + "\n")
        return 0

    # Ensure output directory exists
    artifact_root.mkdir(parents=True, exist_ok=True)

    # Assemble offline deterministic runners
    parquet_path = args.parquet_path
    if parquet_path is None and not args.use_synthetic_windows:
        default_parquet = Path(f"research/immutable-data/5m/canonical/{config.symbol}-5m.parquet")
        if default_parquet.is_file():
            parquet_path = default_parquet

    windows: tuple[CachedEvaluationWindow, ...]
    if parquet_path is not None and parquet_path.is_file() and not args.use_synthetic_windows:
        w_count = args.windows_count if args.windows_count is not None else 3
        b_count = args.bars_per_window if args.bars_per_window is not None else 288
        windows = load_and_slice_windows(
            parquet_path,
            symbol=config.symbol,
            bundle_hash=config.bundle_hash,
            dataset_registry_hash=config.dataset_registry_hash,
            windows_count=w_count,
            bars_per_window=b_count,
        )
    else:
        bars_count = args.bars_per_window if args.bars_per_window is not None else 50
        windows = _make_default_windows(
            symbol=config.symbol,
            bundle_hash=config.bundle_hash,
            dataset_registry_hash=config.dataset_registry_hash,
            bars_count=bars_count,
        )

    qualification_policy = WalkForwardQualificationPolicy(
        policy_id=args.policy_id,
        minimum_windows=args.min_windows,
        minimum_trades=args.min_trades,
        minimum_profit_factor=args.min_profit_factor,
        maximum_drawdown_pct=args.max_drawdown_pct,
        minimum_average_return_pct=args.min_average_return_pct,
    )
    cycle_runner = make_autonomous_cycle_runner(
        windows=windows,
        qualification_policy=qualification_policy,
        critic_transport=DeterministicOfflineCritic(),
        creator_transport=DeterministicOfflineCreator(),
        require_flat=False,
    )

    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(make_offline_learner_transport(args.learning_file)),
        planner=ResearchPlanner(make_offline_planner_transport(args.plan_file)),
        cycle_runner=cycle_runner,
    )

    now = datetime.now(UTC)
    try:
        result = base.run(initial_feedback=initial_feedback, now=now)
    except DomainViolation as exc:
        sys.stderr.write(f"ERROR: DomainViolation during base run: {exc}\n")
        return 2
    except DataQualityError as exc:
        sys.stderr.write(f"ERROR: DataQualityError during base run: {exc}\n")
        return 1

    execution_report = {
        "status": result.status,
        "terminal_reason": result.terminal_reason,
        "base_run_id": result.base_run_id,
        "symbol": result.symbol,
        "cycles_executed": result.cycles_executed,
        "cycle_ids": list(result.cycle_ids),
        "base_hash": result.base_hash,
        "artifact_root": str(config.artifact_root),
    }
    sys.stdout.write(json.dumps(execution_report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
