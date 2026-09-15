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

from autonomous_futures.data.parquet import DataQualityError  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.pipeline.autonomous_base import (  # noqa: E402
    AutonomousBaseConfig,
    AutonomousResearchBase,
    make_autonomous_cycle_runner,
)
from autonomous_futures.research.autonomy_contracts import (  # noqa: E402
    FailureLearner,
    FailureLearningRequest,
    ResearchPlanner,
    ResearchPlanRequest,
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
    """Deterministic critic transport."""

    def __call__(self, request: LearnerCriticRequest) -> Mapping[str, object]:
        return {
            "decision": "approved",
            "critique": "Proposal matches failure feedback guidance.",
            "strengths": ["Adapts lookback to market regime"],
            "weaknesses": ["Requires out-of-sample confirmation"],
        }


class DeterministicOfflineCreator:
    """Deterministic creator proposal transport."""

    def __call__(self, request: CreatorGenerationRequest) -> Mapping[str, object]:
        plan = request.research_plan
        symbol = plan.symbol if plan is not None else "BTCUSDT"
        cycle_ref = request.research_run_id
        strategy_payload: dict[str, object] = {
            "dsl_version": 1,
            "strategy_id": f"cand-{cycle_ref}",
            "family": "momentum_breakout",
            "universe": {
                "symbols": [symbol],
                "timeframe": "5m",
                "regime_context_timeframe": "15m",
            },
            "features": [{"name": "rsi", "lookback": 14, "shift": 1}],
            "entry": {"long": "rsi <= 30", "short": "rsi >= 70"},
            "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
            "vetoes": ["testing_only_no_promotion"],
        }
        return {
            "candidate_id": f"cand-{cycle_ref}",
            "rationale": f"Candidate generated for run {cycle_ref}",
            "strategy": strategy_payload,
        }


def _make_default_windows(
    symbol: str,
    bundle_hash: str,
    dataset_registry_hash: str,
) -> tuple[CachedEvaluationWindow, ...]:
    """Create default evaluation windows with canonical 5m bars for offline base execution."""
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    spec = CachedEvaluationWindowSpec(
        window_id="win-base-cli-001",
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        time_start=start,
        time_end=start + timedelta(minutes=15),
    )
    frame = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * i) for i in range(3)],
            "open": [Decimal("100"), Decimal("101"), Decimal("102")],
            "high": [Decimal("101"), Decimal("102"), Decimal("103")],
            "low": [Decimal("99"), Decimal("100"), Decimal("101")],
            "close": [Decimal("100.5"), Decimal("101.5"), Decimal("102.5")],
        }
    )
    window = CachedEvaluationWindow(spec=spec, frame=frame)
    return (window,)


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

    base_run_id = args.base_run_id or f"base-{uuid4().hex[:16]}"
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
    windows = _make_default_windows(
        symbol=config.symbol,
        bundle_hash=config.bundle_hash,
        dataset_registry_hash=config.dataset_registry_hash,
    )
    qualification_policy = WalkForwardQualificationPolicy(
        policy_id="policy-offline-wf-001",
        minimum_windows=1,
        minimum_trades=1,
        minimum_profit_factor=Decimal("1.1"),
        maximum_drawdown_pct=Decimal("0.15"),
        minimum_average_return_pct=Decimal("0.0"),
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
        learner=FailureLearner(_offline_learner_transport),
        planner=ResearchPlanner(_offline_planner_transport),
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
