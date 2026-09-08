"""Bounded closed-loop Autonomous Pipeline Cycle.

Integrates:
  verified cached market data + prior failure/paper outcome evidence
  -> learner review / critic evaluation (extracting revision actions)
  -> strategy creation/revision (generating new immutable candidate)
  -> deterministic out-of-sample walk-forward trade simulation
  -> qualification gate decision (WalkForwardQualificationPolicy)
  -> paper strategy admission decision (protecting active positions)
  -> safe candidate adoption in paper trading runtime.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pandas as pd
from pydantic import Field, field_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..paper.admission import AdmissionOutcome, StrategyAdmissionDecider
from ..research.cached_evaluation import CachedEvaluationWindow
from ..research.cached_oos_walk_forward import CachedSimulator, evaluate_cached_oos_walk_forward
from ..research.candidate_window_simulation import simulate_candidate_window
from ..research.creator_artifacts import (
    CreatorCandidateArtifact,
    write_creator_candidate_artifact,
)
from ..research.creator_failure_feedback import CreatorQualificationFailureFeedback
from ..research.creator_generator import (
    CreatorGenerationRequest,
    CreatorGenerator,
    ProposalTransport,
)
from ..research.creator_proposals import build_candidate_from_proposal
from ..research.learner_critic import CriticTransport, LearnerCritic, LearnerCriticRequest
from ..research.learner_critic_evidence import (
    build_learner_critique_evidence,
    persist_learner_critique_evidence,
)
from ..research.qualification_artifacts import (
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from ..research.trade_simulation import TradeSimulationConfig, TradeSimulationResult

if TYPE_CHECKING:
    from ..paper.live_engine import LivePaperEngine


CycleStatus = Literal["completed_admitted", "completed_unadmitted", "stopped", "failed"]


class AutonomousCycleConfig(DomainModel):
    """Configuration and bounded constraints for one autonomous cycle."""

    cycle_id: str = Field(pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_policy: WalkForwardQualificationPolicy
    artifact_root: Path
    max_attempts: int = Field(default=1, ge=1, le=5)
    require_flat: bool = False
    data_source: Literal["cached_only"] = "cached_only"
    promotion_state: Literal["unpromoted"] = "unpromoted"
    execution_authority: Literal[False] = False


class AutonomousCycleResult(DomainModel):
    """Immutable, auditable outcome of one bounded autonomous cycle."""

    cycle_version: Literal[1] = 1
    cycle_id: str = Field(pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    cycle_status: CycleStatus
    prior_feedback_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    critique_evidence_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    candidate_id: str | None = Field(default=None, pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    qualification_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    qualification_decision: Literal["qualified", "rejected"] | None = None
    admission_decision: AdmissionOutcome | None = None
    admission_decision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    stop_reasons: tuple[str, ...] = ()
    active_candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    data_source: Literal["cached_only"] = "cached_only"
    promotion_state: Literal["unpromoted"] = "unpromoted"
    execution_authority: Literal[False] = False
    provider: str = Field(default="demo", pattern=r"^[a-z0-9_]+$")
    model: str = Field(default="deterministic-heuristic", min_length=1)
    call_status: str = Field(default="success", pattern=r"^(success|failed|skipped)$")
    latency_ms: float = Field(default=0.0, ge=0.0)
    completed_at: datetime
    cycle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("completed_at")
    @classmethod
    def completed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("cycle completed_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("stop_reasons")
    @classmethod
    def stop_reasons_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("stop reasons must be sorted and unique")
        return values


def autonomous_cycle_content_hash(result: AutonomousCycleResult) -> str:
    """Compute deterministic SHA-256 hash over canonical autonomous cycle result fields."""
    payload = result.model_dump(mode="json", exclude={"cycle_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def execute_autonomous_cycle(
    *,
    config: AutonomousCycleConfig,
    windows: Sequence[CachedEvaluationWindow],
    prior_feedback: CreatorQualificationFailureFeedback,
    critic_transport: CriticTransport,
    creator_transport: ProposalTransport,
    paper_engine: LivePaperEngine | None = None,
    simulator: CachedSimulator | None = None,
    now: datetime | None = None,
    provider: str = "demo",
    model: str = "deterministic-heuristic",
    call_status: str = "success",
    latency_ms: float = 0.0,
) -> AutonomousCycleResult:
    """Execute one complete, bounded, auditable closed-loop autonomous cycle."""
    timestamp = now or datetime.now(UTC)
    active_cand_id = (
        paper_engine.candidates[config.symbol].candidate_id
        if paper_engine and config.symbol in paper_engine.candidates
        else prior_feedback.candidate_id
    )

    def _compute_latency(raw_ms: float) -> float:
        if provider == "demo" and (now is not None or latency_ms == 0.0):
            return 0.0
        if latency_ms > 0.0:
            return latency_ms
        return round(raw_ms, 2)

    # 1. Intake verification: Ensure feedback matches bundle and registry scope
    if (
        prior_feedback.bundle_hash != config.bundle_hash
        or prior_feedback.dataset_registry_hash != config.dataset_registry_hash
    ):
        raise DataQualityError("prior failure feedback does not match cycle bundle scope")

    feedback_hash = prior_feedback.qualification_hash

    # 2. Step 2: Learner Review / Critic Evaluation
    critic_request = LearnerCriticRequest(
        research_run_id=f"run-critic-{config.cycle_id}",
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

    t_critic_start = time.perf_counter()
    critic = LearnerCritic(critic_transport)
    critic_result = critic.review(critic_request)
    critic_latency_ms = (time.perf_counter() - t_critic_start) * 1000.0

    if critic_result.decision != "accepted" or critic_result.critique is None:
        reasons = tuple(sorted(set(critic_result.reason_codes)))
        is_provider_failure = any(
            r.startswith("provider_") or r == "schema_rejected" for r in reasons
        )
        effective_call_status = "failed" if is_provider_failure else call_status
        return _build_cycle_result(
            cycle_id=config.cycle_id,
            symbol=config.symbol,
            cycle_status="failed",
            provider=provider,
            model=model,
            call_status=effective_call_status,
            latency_ms=_compute_latency(critic_latency_ms),
            prior_feedback_hash=feedback_hash,
            stop_reasons=reasons,
            active_candidate_id=active_cand_id,
            completed_at=timestamp,
        )

    critique_evidence = build_learner_critique_evidence(
        request=critic_request,
        critique=critic_result.critique,
        evidence_id=f"critic-evidence-{config.cycle_id}",
        created_at=timestamp,
    )

    # Persist critique evidence if artifact_root is configured
    critique_dir = config.artifact_root / "evidence" / "critic"
    critique_dir.mkdir(parents=True, exist_ok=True)
    persist_learner_critique_evidence(
        critique_dir / f"{critique_evidence.evidence_id}.json",
        critique_evidence,
    )

    if critic_result.critique.decision == "stop":
        # Critic advised stopping revisions
        return _build_cycle_result(
            cycle_id=config.cycle_id,
            symbol=config.symbol,
            cycle_status="stopped",
            provider=provider,
            model=model,
            call_status=call_status,
            latency_ms=_compute_latency(critic_latency_ms),
            prior_feedback_hash=feedback_hash,
            critique_evidence_hash=critique_evidence.review_hash,
            stop_reasons=("critic_stopped_revision",),
            active_candidate_id=active_cand_id,
            completed_at=timestamp,
        )

    # 3. Step 3: Strategy Creation / Revision (Guided by Critic Actions)
    creator_request = CreatorGenerationRequest(
        research_run_id=f"run-creator-{config.cycle_id}",
        input_evidence_refs=tuple(
            sorted(
                (
                    f"critique/{critique_evidence.review_hash}",
                    f"feedback/{prior_feedback.qualification_hash}",
                )
            )
        ),
        output_schema_id="creator-proposal-v1",
        attempt=1,
        forbidden_candidate_ids=(prior_feedback.candidate_id,),
    )

    t_creator_start = time.perf_counter()
    generator = CreatorGenerator(transport=creator_transport)
    generation_result = generator.generate(creator_request)
    creator_latency_ms = (time.perf_counter() - t_creator_start) * 1000.0

    if generation_result.decision != "accepted" or generation_result.proposal is None:
        reasons = tuple(sorted(set(generation_result.reason_codes)))
        is_provider_failure = any(
            r.startswith("provider_") or r == "schema_rejected" for r in reasons
        )
        effective_call_status = "failed" if is_provider_failure else call_status
        return _build_cycle_result(
            cycle_id=config.cycle_id,
            symbol=config.symbol,
            cycle_status="failed",
            provider=provider,
            model=model,
            call_status=effective_call_status,
            latency_ms=_compute_latency(critic_latency_ms + creator_latency_ms),
            prior_feedback_hash=feedback_hash,
            critique_evidence_hash=critique_evidence.review_hash,
            stop_reasons=reasons,
            active_candidate_id=active_cand_id,
            completed_at=timestamp,
        )

    candidate = build_candidate_from_proposal(
        proposal=generation_result.proposal,
        bundle_hash=config.bundle_hash,
        dataset_registry_hash=config.dataset_registry_hash,
        creator_run_id=f"creator-{config.cycle_id}",
        research_seed=100,
        created_at=timestamp,
    )

    # Persist newly generated candidate
    cand_dir = config.artifact_root / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    write_creator_candidate_artifact(cand_dir / f"{candidate.candidate_id}.json", candidate)

    # 4. Step 4: Deterministic Walk-Forward OOS Evaluation
    eval_run_id = f"eval-{config.cycle_id}"
    if simulator is not None:
        effective_simulator = simulator
    else:
        sim_config = TradeSimulationConfig(
            starting_equity=Decimal("100.00"),
            position_fraction=Decimal("0.10"),
            taker_fee_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.0001"),
        )

        def effective_simulator(
            c: CreatorCandidateArtifact,
            frame: pd.DataFrame,
            w: CachedEvaluationWindow,
        ) -> TradeSimulationResult:
            return simulate_candidate_window(
                c,
                frame,
                symbol=w.spec.symbol,
                config=sim_config,
            )

    aggregation = evaluate_cached_oos_walk_forward(
        candidate=candidate,
        windows=windows,
        simulator=effective_simulator,
    )

    # 5. Step 5: Candidate Qualification
    qualification = build_walk_forward_qualification_artifact(
        candidate=candidate,
        aggregation=aggregation,
        policy=config.qualification_policy,
        evaluator_run_id=eval_run_id,
        evaluator_version="1.0.0",
        evaluated_at=timestamp,
    )

    # Persist qualification artifact
    qual_dir = config.artifact_root / "qualifications"
    qual_dir.mkdir(parents=True, exist_ok=True)
    write_creator_candidate_qualification_artifact(
        qual_dir / f"{qualification.qualification_hash}.json",
        qualification,
    )

    # 6. Step 6: Strategy Admission Decision
    admission_decider = StrategyAdmissionDecider()
    active_trades = paper_engine.active_trades if paper_engine is not None else None
    admission = admission_decider.evaluate_admission(
        candidate=candidate,
        qualification=qualification,
        symbol=config.symbol,
        active_trades=active_trades,
        require_flat=config.require_flat,
        evaluated_at=timestamp,
    )

    # 7. Step 7: Safe Candidate Adoption in Paper Trading
    if admission.decision == "admitted" and paper_engine is not None:
        paper_engine.admit_candidate(candidate, qualification, require_flat=config.require_flat)
        active_cand_id = candidate.candidate_id

    cycle_status: CycleStatus = (
        "completed_admitted" if admission.decision == "admitted" else "completed_unadmitted"
    )

    # 8. Step 8: Build and return auditable cycle result
    return _build_cycle_result(
        cycle_id=config.cycle_id,
        symbol=config.symbol,
        cycle_status=cycle_status,
        provider=provider,
        model=model,
        call_status=call_status,
        latency_ms=_compute_latency(critic_latency_ms + creator_latency_ms),
        prior_feedback_hash=feedback_hash,
        critique_evidence_hash=critique_evidence.review_hash,
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
        qualification_hash=qualification.qualification_hash,
        qualification_decision=qualification.decision,
        admission_decision=admission.decision,
        admission_decision_hash=admission.decision_hash,
        stop_reasons=admission.reason_codes if admission.decision != "admitted" else (),
        active_candidate_id=active_cand_id,
        completed_at=timestamp,
    )


def _build_cycle_result(
    *,
    cycle_id: str,
    symbol: str,
    cycle_status: CycleStatus,
    active_candidate_id: str,
    completed_at: datetime,
    provider: str = "demo",
    model: str = "deterministic-heuristic",
    call_status: str = "success",
    latency_ms: float = 0.0,
    prior_feedback_hash: str | None = None,
    critique_evidence_hash: str | None = None,
    candidate_id: str | None = None,
    candidate_artifact_hash: str | None = None,
    qualification_hash: str | None = None,
    qualification_decision: Literal["qualified", "rejected"] | None = None,
    admission_decision: AdmissionOutcome | None = None,
    admission_decision_hash: str | None = None,
    stop_reasons: tuple[str, ...] = (),
) -> AutonomousCycleResult:
    sorted_reasons = tuple(sorted(set(stop_reasons)))
    provisional = AutonomousCycleResult.model_validate(
        {
            "cycle_version": 1,
            "cycle_id": cycle_id,
            "symbol": symbol,
            "cycle_status": cycle_status,
            "provider": provider,
            "model": model,
            "call_status": call_status,
            "latency_ms": latency_ms,
            "prior_feedback_hash": prior_feedback_hash,
            "critique_evidence_hash": critique_evidence_hash,
            "candidate_id": candidate_id,
            "candidate_artifact_hash": candidate_artifact_hash,
            "qualification_hash": qualification_hash,
            "qualification_decision": qualification_decision,
            "admission_decision": admission_decision,
            "admission_decision_hash": admission_decision_hash,
            "stop_reasons": sorted_reasons,
            "active_candidate_id": active_candidate_id,
            "data_source": "cached_only",
            "promotion_state": "unpromoted",
            "execution_authority": False,
            "completed_at": completed_at,
            "cycle_hash": "0" * 64,
        }
    )
    c_hash = autonomous_cycle_content_hash(provisional)
    return provisional.model_copy(update={"cycle_hash": c_hash})


__all__ = [
    "AutonomousCycleConfig",
    "AutonomousCycleResult",
    "CycleStatus",
    "autonomous_cycle_content_hash",
    "execute_autonomous_cycle",
]
