"""scripts/run_autonomous_cycle.py

Autonomous Pipeline Cycle CLI Runner (Milestone 2 / R2).
Orchestrates bounded, deterministic closed-loop strategy revision and paper admission:
  Feedback extraction / intake -> Critic review -> Creator proposal
  -> Deterministic OOS walk-forward simulation -> Qualification gating
  -> Strategy admission decision -> Result and audit persistence.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

# Ensure src/ is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_ENV_PATH = _REPO_ROOT / ".env"
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.data.parquet import (  # noqa: E402
    DataQualityError,
    read_canonical_parquet,
)
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.feedback_extractor import (  # noqa: E402
    PaperQualificationPolicy,
    extract_paper_feedback,
)
from autonomous_futures.paper.live_engine import LivePaperEngine  # noqa: E402
from autonomous_futures.pipeline.autonomous_cycle import (  # noqa: E402
    AutonomousCycleConfig,
    AutonomousCycleResult,
    execute_autonomous_cycle,
)
from autonomous_futures.research.cached_evaluation import (  # noqa: E402
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.creator_failure_feedback import (  # noqa: E402
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.creator_generator import (  # noqa: E402
    CreatorGenerationRequest,
    ProposalTransport,
)
from autonomous_futures.research.creator_prompts import (  # noqa: E402
    build_creator_proposal_messages,
)
from autonomous_futures.research.google_ai_studio_provider import (  # noqa: E402
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    GoogleAIStudioJsonClient,
    GoogleAIStudioProposalTransport,
    GoogleAIStudioProviderConfig,
    MissingCredentialsError,
    ProviderTransportError,
    resolve_credential,
)
from autonomous_futures.research.learner_critic import (  # noqa: E402
    CriticTransport,
    LearnerCriticRequest,
)
from autonomous_futures.research.learner_critic_provider import (  # noqa: E402
    GoogleAIStudioLearnerCriticTransport,
    build_learner_critic_messages,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    WalkForwardQualificationPolicy,
)

logger = logging.getLogger("autonomous_futures.cli.autonomous_cycle")

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)

DEFAULT_BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
DEFAULT_REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
_MISSING_CREDENTIALS_MSG = "No Google AI Studio / Gemini credential found in environment or .env."


class ProviderFailureError(RuntimeError):
    """Raised when an LLM provider call or schema validation fails."""


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
)


def _check_forbidden_credential_flags(argv: Sequence[str]) -> bool:
    """Inspect raw argv for forbidden credential flags, preventing secret leakage."""
    for arg in argv:
        prefix = arg.lower().split("=")[0].strip()
        if prefix in FORBIDDEN_CREDENTIAL_FLAGS:
            return True
    return False


class BoundedTransportCallGovernor:
    """Enforces non-bypassable ceiling: exactly 1 call allowed per transport."""

    def __init__(
        self,
        transport: Callable[[Any], Mapping[str, object]],
        *,
        max_calls: int = 1,
        name: str = "transport",
    ) -> None:
        self._transport = transport
        self._max_calls = max_calls
        self.call_count: int = 0
        self.total_latency_ms: float = 0.0
        self._name = name

    def __call__(self, request: Any) -> Mapping[str, object]:
        if self.call_count >= self._max_calls:
            raise RuntimeError(
                f"Budget ceiling breach: {self._name} exceeded limit of {self._max_calls}"
            )
        self.call_count += 1
        start = time.perf_counter()
        try:
            return self._transport(request)
        finally:
            self.total_latency_ms += (time.perf_counter() - start) * 1000.0


def _sanitize_error_text(text: str) -> str:
    """Strip potential secret tokens or sensitive values from error text."""
    return _SECRET_PATTERN.sub("[REDACTED_SECRET]", text)


def _validate_symbol(val: str) -> str:
    s = val.strip().upper()
    if not re.match(r"^[A-Z0-9]+$", s):
        raise argparse.ArgumentTypeError(f"Invalid symbol format: {val}")
    return s


def _validate_windows_count(val: str) -> int:
    try:
        n = int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid integer for windows-count: {val}") from None
    if n < 1 or n > 10:
        raise argparse.ArgumentTypeError(f"--windows-count must be between 1 and 10, got {n}")
    return n


def _validate_bars_per_window(val: str) -> int:
    try:
        n = int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid integer for bars-per-window: {val}") from None
    if n < 20 or n > 2016:
        raise argparse.ArgumentTypeError(f"--bars-per-window must be between 20 and 2016, got {n}")
    return n


def _validate_cycle_id(val: str) -> str:
    if not re.match(r"^cycle-[a-z0-9][a-z0-9-]{0,63}$", val):
        raise argparse.ArgumentTypeError(
            f"Invalid cycle-id: '{val}' does not match pattern '^cycle-[a-z0-9][a-z0-9-]{{0,63}}$'"
        )
    return val


def _validate_hex64(val: str) -> str:
    if not re.match(r"^[0-9a-f]{64}$", val):
        raise argparse.ArgumentTypeError(f"Invalid 64-character lowercase hex hash: '{val}'")
    return val


def _validate_temperature(val: str) -> float:
    try:
        t = float(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid float value: {val!r}") from None
    if not math.isfinite(t) or t < 0.0 or t > 2.0:
        raise argparse.ArgumentTypeError(
            f"--temperature must be finite and within [0.0, 2.0], got {val}"
        )
    return t


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Autonomous Cycle CLI Runner — bounded strategy revision and paper admission.",
    )
    parser.add_argument(
        "--symbol",
        type=_validate_symbol,
        required=True,
        help="Target market symbol (e.g. BTCUSDT, ETHUSDT, SOLUSDT)",
    )
    parser.add_argument(
        "--ledger-db",
        type=Path,
        default=None,
        help="Path to paper-ledger.sqlite3 or paper storage directory",
    )
    parser.add_argument(
        "--lifecycle-db",
        type=Path,
        default=None,
        help="Optional path to paper-lifecycle.sqlite3",
    )
    parser.add_argument(
        "--observations-db",
        type=Path,
        default=None,
        help="Optional path to paper-observations.sqlite3",
    )
    parser.add_argument(
        "--feedback-path",
        type=Path,
        default=None,
        help="Path to existing failure feedback JSON. If omitted, extracted from --ledger-db.",
    )
    parser.add_argument(
        "--candidate-id",
        type=str,
        default=None,
        help="Optional candidate ID filter for feedback extraction",
    )
    parser.add_argument(
        "--candidate-path",
        type=Path,
        default=None,
        help="Optional path to initial candidate artifact JSON",
    )
    parser.add_argument(
        "--parquet-path",
        type=Path,
        default=None,
        help=(
            "Path to canonical 5m Parquet data "
            "(default: research/immutable-data/5m/canonical/{symbol}-5m.parquet)"
        ),
    )
    parser.add_argument(
        "--windows-count",
        type=_validate_windows_count,
        default=3,
        help="Number of sequential evaluation windows (min 1, max 10, default 3)",
    )
    parser.add_argument(
        "--bars-per-window",
        type=_validate_bars_per_window,
        default=288,
        help="Number of 5m bars per evaluation window (min 20, max 2016, default 288)",
    )
    # Walk-forward qualification thresholds
    parser.add_argument(
        "--min-profit-factor",
        type=Decimal,
        default=Decimal("1.05"),
        help="Qualification minimum profit factor threshold (default: 1.05)",
    )
    parser.add_argument(
        "--max-drawdown-pct",
        type=Decimal,
        default=Decimal("15.0"),
        help="Qualification maximum drawdown percentage threshold (default: 15.0)",
    )
    parser.add_argument(
        "--min-average-return-pct",
        type=Decimal,
        default=Decimal("0.0"),
        help="Qualification minimum average return percentage threshold (default: 0.0)",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=5,
        help="Qualification minimum trades threshold (default: 5)",
    )
    parser.add_argument(
        "--min-windows",
        type=int,
        default=1,
        help="Qualification minimum windows threshold (default: 1)",
    )
    parser.add_argument(
        "--policy-id",
        type=str,
        default="policy-autonomous-cycle-v1",
        help="Walk-forward qualification policy identifier",
    )
    # Paper breach thresholds
    parser.add_argument(
        "--paper-net-pnl-min",
        type=Decimal,
        default=Decimal("0.00"),
        help="Paper qualification policy minimum net PnL (default: 0.00)",
    )
    parser.add_argument(
        "--paper-profit-factor-min",
        type=Decimal,
        default=Decimal("1.05"),
        help="Paper qualification policy minimum profit factor (default: 1.05)",
    )
    parser.add_argument(
        "--paper-win-rate-min",
        type=Decimal,
        default=Decimal("45.00"),
        help="Paper qualification policy minimum win rate percentage (default: 45.00)",
    )
    parser.add_argument(
        "--paper-drawdown-max",
        type=Decimal,
        default=Decimal("15.00"),
        help="Paper qualification policy maximum drawdown percentage (default: 15.00)",
    )
    parser.add_argument(
        "--paper-trades-min",
        type=int,
        default=5,
        help="Paper qualification policy minimum trades (default: 5)",
    )
    # Output & Cycle Configuration
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write autonomous-cycle-result.json and cycle-audit.json",
    )
    parser.add_argument(
        "--require-flat",
        action="store_true",
        default=False,
        help="Require zero active paper positions before admitting qualified candidate",
    )
    parser.add_argument(
        "--bundle-hash",
        type=_validate_hex64,
        default=None,
        help="Pinned bundle SHA-256 hash (64 hex characters)",
    )
    parser.add_argument(
        "--dataset-registry-hash",
        type=_validate_hex64,
        default=None,
        help="Pinned dataset registry SHA-256 hash (64 hex characters)",
    )
    parser.add_argument(
        "--cycle-id",
        type=_validate_cycle_id,
        default=None,
        help="Cycle identifier (regex ^cycle-[a-z0-9][a-z0-9-]{0,63}$)",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="Optional ISO 8601 timestamp for deterministic evaluation time",
    )
    parser.add_argument(
        "--provider",
        choices=["demo", "google_ai_studio"],
        default="demo",
        help="Strategy revision provider transport (default: demo)",
    )
    parser.add_argument(
        "--model",
        choices=["gemma-4-31b-it", "gemma-4-26b-a4b-it"],
        default="gemma-4-31b-it",
        help="Gemma model ID for Google AI Studio provider (default: gemma-4-31b-it)",
    )
    parser.add_argument(
        "--temperature",
        type=_validate_temperature,
        default=0.2,
        help="Sampling temperature for provider completions (default: 0.2)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        default=True,
        help="Run in deterministic demo mode with zero paid LLM / live exchange calls",
    )
    return parser


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


def make_demo_critic_transport() -> CriticTransport:
    def critic_transport(req: LearnerCriticRequest) -> dict[str, Any]:
        cid = req.candidate_id.lower().replace("_", "-")
        review_id = f"review-{cid}"[:64]
        return {
            "review_id": review_id,
            "research_run_id": req.research_run_id,
            "candidate_id": req.candidate_id,
            "decision": "revise",
            "failure_reason_codes": sorted(set(req.feedback.failure_reason_codes)),
            "revision_actions": sorted(["adjust_stop_multiplier", "adjust_take_profit_multiplier"]),
        }

    return critic_transport


def make_demo_creator_transport(symbol: str) -> ProposalTransport:
    def creator_transport(req: CreatorGenerationRequest) -> dict[str, Any]:
        proposal_id = f"proposal-{symbol.lower()}-revised-001"[:64]
        candidate_suffix = (
            "002"
            if req.forbidden_candidate_ids
            and f"cand-{symbol.lower()}-revised-001" in req.forbidden_candidate_ids
            else "001"
        )
        cand_id = f"cand-{symbol.lower()}-revised-{candidate_suffix}"[:64]
        return {
            "proposal_id": proposal_id,
            "research_run_id": req.research_run_id,
            "hypothesis": f"Adjusting ATR multipliers to capture momentum on 5m {symbol} bars",
            "expected_regime": "trending",
            "novelty_reason": "Learner critique incorporated on real historical bars",
            "strategy": {
                "dsl_version": 2,
                "strategy_id": cand_id,
                "family": "experimental",
                "universe": {
                    "symbols": [symbol],
                    "timeframe": "5m",
                    "regime_context_timeframe": "15m",
                },
                "features": [{"name": "returns", "lookback": 3, "shift": 1}],
                "entry": {"long": "returns > 0.001", "short": "returns < -0.001"},
                "exit": {"long": "returns < 0.0", "short": "returns > 0.0"},
                "vetoes": ["testing_only_no_promotion"],
                "risk": {
                    "position_fraction": Decimal("0.10"),
                    "stop_atr_multiplier": Decimal("2.0"),
                    "take_profit_atr_multiplier": Decimal("3.0"),
                    "trailing_atr_multiplier": Decimal("1.0"),
                },
            },
        }

    return creator_transport


def build_cycle_audit(
    result: AutonomousCycleResult,
    args: argparse.Namespace,
) -> dict[str, Any]:
    provider = getattr(result, "provider", getattr(args, "provider", "demo"))
    model = getattr(result, "model", getattr(args, "model", "deterministic-heuristic"))
    call_status = getattr(result, "call_status", "success")
    latency_ms = getattr(result, "latency_ms", 0.0)

    payload: dict[str, Any] = {
        "audit_version": 1,
        "cycle_id": result.cycle_id,
        "symbol": result.symbol,
        "cycle_status": result.cycle_status,
        "cycle_hash": result.cycle_hash,
        "completed_at": result.completed_at.isoformat(),
        "telemetry": {
            "provider": provider,
            "model": model,
            "call_status": call_status,
            "latency_ms": latency_ms,
        },
        "safety_invariants": {
            "data_source": result.data_source,
            "promotion_state": result.promotion_state,
            "execution_authority": result.execution_authority,
        },
        "lineage": {
            "prior_feedback_hash": result.prior_feedback_hash,
            "critique_evidence_hash": result.critique_evidence_hash,
            "candidate_id": result.candidate_id,
            "candidate_artifact_hash": result.candidate_artifact_hash,
            "qualification_hash": result.qualification_hash,
            "qualification_decision": result.qualification_decision,
            "admission_decision": result.admission_decision,
            "admission_decision_hash": result.admission_decision_hash,
            "active_candidate_id": result.active_candidate_id,
            "stop_reasons": list(result.stop_reasons),
        },
        "configuration": {
            "ledger_db": str(args.ledger_db) if getattr(args, "ledger_db", None) else None,
            "parquet_path": str(args.parquet_path) if getattr(args, "parquet_path", None) else None,
            "windows_count": args.windows_count,
            "bars_per_window": args.bars_per_window,
            "require_flat": args.require_flat,
            "demo": getattr(args, "provider", "demo") == "demo",
        },
        "audit_hash": "0" * 64,
    }
    raw = json.dumps(
        {k: v for k, v in payload.items() if k != "audit_hash"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["audit_hash"] = sha256(raw).hexdigest()
    return payload


def run_autonomous_cycle(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.fromisoformat(args.now).astimezone(UTC) if args.now else datetime.now(UTC)
    symbol = args.symbol.upper()
    cycle_id = args.cycle_id or f"cycle-{symbol.lower()}-{now.strftime('%Y%m%d%H%M%S')}"

    output_dir = args.output_dir or Path(f"artifacts/autonomous_cycle/{cycle_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = args.parquet_path or Path(
        f"research/immutable-data/5m/canonical/{symbol}-5m.parquet"
    )

    # 1. Feedback Intake: Load from path or extract from SQLite ledger
    prior_feedback: CreatorQualificationFailureFeedback | None = None
    if args.feedback_path:
        fb_path = Path(args.feedback_path)
        if not fb_path.is_file():
            raise FileNotFoundError(f"Feedback file not found: {fb_path}")
        prior_feedback = CreatorQualificationFailureFeedback.model_validate_json(
            fb_path.read_text(encoding="utf-8")
        )
    else:
        ledger_path = Path(args.ledger_db)
        if not ledger_path.exists():
            raise FileNotFoundError(f"Ledger DB path not found: {ledger_path}")
        paper_policy = PaperQualificationPolicy(
            policy_id="paper-policy-cli-001",
            paper_net_pnl_min=args.paper_net_pnl_min,
            paper_profit_factor_min=args.paper_profit_factor_min,
            paper_win_rate_min=args.paper_win_rate_min,
            paper_drawdown_max=args.paper_drawdown_max,
            paper_trades_min=args.paper_trades_min,
        )
        target_bundle_hash = args.bundle_hash or DEFAULT_BUNDLE_HASH
        target_registry_hash = args.dataset_registry_hash or DEFAULT_REGISTRY_HASH
        prior_feedback = extract_paper_feedback(
            ledger_path=ledger_path,
            lifecycle_path=args.lifecycle_db,
            symbol=symbol,
            candidate_id=args.candidate_id,
            candidate_artifact_path=args.candidate_path,
            policy=paper_policy,
            bundle_hash=target_bundle_hash,
            dataset_registry_hash=target_registry_hash,
        )

    # 2. Handle zero-breach scenario cleanly
    if prior_feedback is None:
        logger.info("Candidate meets paper qualification criteria; zero breaches. Cycle skipped.")
        provider = getattr(args, "provider", "demo")
        model = (
            getattr(args, "model", "gemma-4-31b-it")
            if provider == "google_ai_studio"
            else "deterministic-heuristic"
        )
        audit_skipped: dict[str, Any] = {
            "audit_version": 1,
            "cycle_id": cycle_id,
            "symbol": symbol,
            "cycle_status": "skipped_no_breaches",
            "cycle_hash": "0" * 64,
            "completed_at": now.isoformat(),
            "telemetry": {
                "provider": provider,
                "model": model,
                "call_status": "skipped",
                "latency_ms": 0.0,
            },
            "safety_invariants": {
                "data_source": "cached_only",
                "promotion_state": "unpromoted",
                "execution_authority": False,
            },
            "lineage": {
                "prior_feedback_hash": None,
                "critique_evidence_hash": None,
                "candidate_id": args.candidate_id,
                "candidate_artifact_hash": None,
                "qualification_hash": None,
                "qualification_decision": None,
                "admission_decision": None,
                "admission_decision_hash": None,
                "active_candidate_id": args.candidate_id or f"cand-{symbol.lower()}-active",
                "stop_reasons": ["skipped_no_breaches"],
            },
            "configuration": {
                "ledger_db": str(args.ledger_db) if getattr(args, "ledger_db", None) else None,
                "parquet_path": str(parquet_path),
                "windows_count": args.windows_count,
                "bars_per_window": args.bars_per_window,
                "require_flat": args.require_flat,
                "demo": getattr(args, "provider", "demo") == "demo",
            },
            "audit_hash": "0" * 64,
        }
        raw = json.dumps(
            {k: v for k, v in audit_skipped.items() if k != "audit_hash"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        audit_skipped["audit_hash"] = sha256(raw).hexdigest()
        audit_json = json.dumps(audit_skipped, indent=2, sort_keys=True)
        if _SECRET_PATTERN.search(audit_json):
            raise RuntimeError("Secret pattern detected in cycle audit")
        (output_dir / "cycle-audit.json").write_text(audit_json + "\n", encoding="utf-8")
        return audit_skipped

    # 3. Scope Alignment & Pinned Hashes
    bundle_hash = args.bundle_hash or prior_feedback.bundle_hash or DEFAULT_BUNDLE_HASH
    dataset_registry_hash = (
        args.dataset_registry_hash or prior_feedback.dataset_registry_hash or DEFAULT_REGISTRY_HASH
    )

    # 4. Market Data Windowing
    windows: Sequence[CachedEvaluationWindow] = load_and_slice_windows(
        parquet_path,
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        windows_count=args.windows_count,
        bars_per_window=args.bars_per_window,
    )

    # 5. Qualification Policy & Cycle Configuration
    qual_policy = WalkForwardQualificationPolicy(
        policy_id=args.policy_id,
        minimum_windows=args.min_windows,
        minimum_trades=args.min_trades,
        minimum_profit_factor=args.min_profit_factor,
        maximum_drawdown_pct=args.max_drawdown_pct,
        minimum_average_return_pct=args.min_average_return_pct,
    )

    cycle_config = AutonomousCycleConfig(
        cycle_id=cycle_id,
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        qualification_policy=qual_policy,
        artifact_root=output_dir,
        max_attempts=1,
        require_flat=args.require_flat,
    )

    # 6. Paper Engine Setup (if ledger-db specified)
    paper_engine: LivePaperEngine | None = None
    if args.ledger_db:
        ledger_path = Path(args.ledger_db)
        if ledger_path.is_dir():
            ledger_path.mkdir(parents=True, exist_ok=True)
            ledger_file = ledger_path / "paper-ledger.sqlite3"
            lifecycle_file = args.lifecycle_db or (ledger_path / "paper-lifecycle.sqlite3")
            obs_file = args.observations_db or (ledger_path / "paper-observations.sqlite3")
        else:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_file = ledger_path
            lifecycle_file = args.lifecycle_db or (ledger_path.parent / "paper-lifecycle.sqlite3")
            obs_file = args.observations_db or (ledger_path.parent / "paper-observations.sqlite3")

        candidates_map: dict[str, CreatorCandidateArtifact] = {}
        if args.candidate_path and Path(args.candidate_path).is_file():
            initial_cand = read_creator_candidate_artifact(Path(args.candidate_path))
            candidates_map[symbol] = initial_cand

        paper_engine = LivePaperEngine(
            symbols=(symbol,),
            candidates=candidates_map if candidates_map else None,
            ledger_db=ledger_file,
            lifecycle_db=lifecycle_file,
            observations_db=obs_file,
        )

    # 7. Transports Resolution
    critic_transport: CriticTransport
    creator_transport: ProposalTransport
    http_client: httpx.Client | None = None
    try:
        if args.provider == "google_ai_studio":
            api_key = resolve_credential(repo_env_path=_REPO_ENV_PATH)
            provider_config = GoogleAIStudioProviderConfig(
                base_url=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
                api_key=api_key,
                model_id=args.model,
            )
            del api_key  # Immediate key scrubbing

            http_client = httpx.Client(timeout=30.0)
            json_client = GoogleAIStudioJsonClient(
                config=provider_config,
                client=http_client,
            )

            dummy_critic_req = LearnerCriticRequest(
                research_run_id=f"run-critic-{cycle_id}",
                candidate_id=prior_feedback.candidate_id,
                candidate_artifact_hash=prior_feedback.candidate_artifact_hash,
                feedback=prior_feedback,
                input_evidence_refs=tuple(
                    sorted(
                        (
                            f"feedback/{prior_feedback.qualification_hash}",
                            f"policy/{prior_feedback.qualification_policy_id}",
                        )
                    )
                ),
                output_schema_id="learner-critic-v1",
                attempt=1,
            )
            critic_sys, _ = build_learner_critic_messages(dummy_critic_req)

            def _critic_builder(req: LearnerCriticRequest) -> str:
                return str(build_learner_critic_messages(req)[1]["content"])

            raw_critic_transport = GoogleAIStudioLearnerCriticTransport(
                client=json_client,
                system_prompt=str(critic_sys["content"]),
                user_prompt_builder=_critic_builder,
                temperature=args.temperature,
                max_output_tokens=4096,
            )

            dummy_creator_req = CreatorGenerationRequest(
                research_run_id=f"run-creator-{cycle_id}",
                input_evidence_refs=(f"bundle/{bundle_hash}",),
                output_schema_id="creator-proposal-v1",
                attempt=1,
                forbidden_candidate_ids=(prior_feedback.candidate_id,),
            )
            creator_sys, _ = build_creator_proposal_messages(
                dummy_creator_req, bundle_hash=bundle_hash, symbol=symbol
            )

            def _creator_builder(req: CreatorGenerationRequest) -> str:
                msgs = build_creator_proposal_messages(req, bundle_hash=bundle_hash, symbol=symbol)
                return str(msgs[1]["content"])

            raw_creator_transport = GoogleAIStudioProposalTransport(
                client=json_client,
                system_prompt=str(creator_sys["content"]),
                user_prompt_builder=_creator_builder,
                temperature=args.temperature,
                max_output_tokens=2048,
            )

            critic_governor = BoundedTransportCallGovernor(
                raw_critic_transport, max_calls=1, name="critic"
            )
            creator_governor = BoundedTransportCallGovernor(
                raw_creator_transport, max_calls=1, name="creator"
            )

            critic_transport = critic_governor
            creator_transport = creator_governor
        else:
            critic_transport = make_demo_critic_transport()
            creator_transport = make_demo_creator_transport(symbol)

        # 8. Pipeline Execution
        result = execute_autonomous_cycle(
            config=cycle_config,
            windows=windows,
            prior_feedback=prior_feedback,
            critic_transport=critic_transport,
            creator_transport=creator_transport,
            paper_engine=paper_engine,
            now=now,
            provider=args.provider,
            model=args.model if args.provider == "google_ai_studio" else "deterministic-heuristic",
        )
    finally:
        if http_client is not None:
            http_client.close()

    # 9. Result & Audit Persistence Guarded by Secret Scan
    result_json = result.model_dump_json(indent=2)
    if _SECRET_PATTERN.search(result_json):
        raise RuntimeError("Secret pattern detected in cycle result")
    (output_dir / "autonomous-cycle-result.json").write_text(result_json + "\n", encoding="utf-8")

    audit = build_cycle_audit(result, args)
    audit_json = json.dumps(audit, indent=2, sort_keys=True)
    if _SECRET_PATTERN.search(audit_json):
        raise RuntimeError("Secret pattern detected in cycle audit")
    (output_dir / "cycle-audit.json").write_text(audit_json + "\n", encoding="utf-8")

    if result.cycle_status == "failed":
        reasons = list(result.stop_reasons)
        is_provider_failure = any(
            r.startswith("provider_") or r == "schema_rejected" for r in reasons
        )
        if is_provider_failure:
            raise ProviderFailureError(f"Provider call failed: {', '.join(reasons)}")

    return audit


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if _check_forbidden_credential_flags(raw_argv):
        print(
            json.dumps(
                {
                    "error_code": "forbidden_cli_argument",
                    "message": (
                        "Passing API keys or credentials via CLI flags is forbidden. "
                        "Set GOOGLE_API_KEY, GEMINI_API_KEY, or GOOGLE_AI_STUDIO_API_KEY "
                        "in your environment or repository .env file."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = int(exc.code) if exc.code is not None and isinstance(exc.code, int) else 2
        return 2 if code != 0 else 0

    try:
        # Cross-argument validation
        if not args.feedback_path and not args.ledger_db:
            print(
                json.dumps(
                    {
                        "error_code": "missing_input_source",
                        "message": "Either --feedback-path or --ledger-db must be provided.",
                    }
                ),
                file=sys.stderr,
            )
            return 2

        summary = run_autonomous_cycle(args)
    except MissingCredentialsError as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(
            json.dumps(
                {
                    "error_code": "missing_credentials",
                    "message": _MISSING_CREDENTIALS_MSG,
                }
            )
        )
        return 3
    except ProviderFailureError as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "provider_call_failed", "message": sanitized}))
        return 3
    except ProviderTransportError as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "provider_transport_error", "message": sanitized}))
        return 3
    except (ValueError, DataQualityError, DomainViolation, FileNotFoundError) as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "autonomous_cycle_data_error", "message": sanitized}))
        return 3
    except RuntimeError as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        if "credential" in sanitized.lower() or "api_key" in sanitized.lower():
            print(
                json.dumps(
                    {
                        "error_code": "missing_credentials",
                        "message": _MISSING_CREDENTIALS_MSG,
                    }
                )
            )
            return 3
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
    "DEFAULT_BUNDLE_HASH",
    "DEFAULT_REGISTRY_HASH",
    "BoundedTransportCallGovernor",
    "ProviderFailureError",
    "build_cycle_audit",
    "build_parser",
    "load_and_slice_windows",
    "main",
    "make_demo_creator_transport",
    "make_demo_critic_transport",
    "run_autonomous_cycle",
]
