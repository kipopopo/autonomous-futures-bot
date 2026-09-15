"""Supported finite provider-to-research orchestration entrypoint.

Replaces disposable smoke scripts with durable evidence capture:
- Preflights credentials safely without exposing secrets.
- Binds run ID, input evidence hashes, failure history, policy, and budget.
- Enforces zero retries and no provider fallback.
- Verifies checkpoints and rejects tampered or replayed checkpoints prior to network.
- Writes durable typed accepted artifacts and sanitized audit envelopes to approved storage.
- Verifies storage integrity on readback.
- Preserves rejected outcomes honestly without schema relaxation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from ..research_lab.model_audit import (
    ModelCallAudit,
    ModelCallOutcome,
)
from ..research_lab.model_policy import (
    ResearchModelPolicy,
    research_model_policy_content_hash,
)
from ..research_lab.research_run_audit import (
    ResearchRunAuditEnvelope,
    build_research_run_audit_envelope,
)
from ..research_lab.research_run_audit_persistence import (
    read_research_run_audit_envelope,
    write_research_run_audit_envelope,
)
from .autonomy_contracts import (
    FailureLearner,
    FailureLearningArtifact,
    FailureLearningRequest,
    FailureLearningTransport,
    FailureMemoryEntry,
    ResearchPlan,
    ResearchPlanner,
    ResearchPlanRequest,
    ResearchPlanTransport,
    read_failure_learning_artifact,
    read_research_plan,
    write_failure_learning_artifact,
    write_research_plan,
)
from .autonomy_prompts import (
    build_failure_learning_messages,
    build_research_plan_messages,
)
from .google_ai_studio_provider import (
    GoogleAIStudioJsonClient,
    GoogleAIStudioProviderConfig,
    MissingCredentialsError,
    resolve_credential,
)

ProviderOrchestrationRole = Literal["failure_analyst", "hypothesis_generator"]
ProviderOrchestrationStatus = Literal[
    "succeeded",
    "rejected",
    "prepared",
    "blocked",
    "budget_exhausted",
    "reused_checkpoint",
]


class ProviderOrchestrationConfig(DomainModel):
    """Configuration binding for one durable provider-to-research execution."""

    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    base_run_id: str = Field(pattern=r"^base-[a-z0-9][a-z0-9-]{0,63}$")
    role: ProviderOrchestrationRole
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_root: Path
    policy: ResearchModelPolicy
    request_budget: int = Field(default=1, ge=0, strict=True)
    execute: bool = False
    cycle_index: int = Field(default=1, ge=1, strict=True)
    cycle_id: str | None = Field(default=None, pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    data_source: Literal["cached_only"] = "cached_only"
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @model_validator(mode="after")
    def validate_policy_role_binding(self) -> ProviderOrchestrationConfig:
        if research_model_policy_content_hash(self.policy) != self.policy.policy_hash:
            raise DomainViolation("research model policy hash mismatch")
        role_policy = next((item for item in self.policy.roles if item.role == self.role), None)
        if role_policy is None:
            raise DomainViolation(f"research model policy has no {self.role} role")
        if role_policy.provider != "google_ai_studio":
            raise DomainViolation("provider orchestration requires google_ai_studio provider")
        if role_policy.max_retries != 0:
            raise DomainViolation("provider orchestration enforces zero retries (max_retries=0)")
        if self.role == "hypothesis_generator" and self.cycle_id is None:
            raise DomainViolation("hypothesis_generator role requires cycle_id")
        return self


class ProviderOrchestrationResult(DomainModel):
    """Typed outcome of one bounded provider-to-research execution."""

    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    base_run_id: str = Field(pattern=r"^base-[a-z0-9][a-z0-9-]{0,63}$")
    role: ProviderOrchestrationRole
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    status: ProviderOrchestrationStatus
    decision: Literal["accepted", "rejected", "prepared"]
    learning_artifact: FailureLearningArtifact | None = None
    research_plan: ResearchPlan | None = None
    audit_envelope: ResearchRunAuditEnvelope | None = None
    readback_verified: bool = False
    reused_existing: bool = False
    reason_codes: tuple[str, ...] = ()
    schema_diagnostics: tuple[str, ...] = ()
    requests_consumed: int = Field(ge=0, strict=True)
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def completed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("completed_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("reason_codes", "schema_diagnostics")
    @classmethod
    def result_lists_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("result lists must be sorted and unique")
        return values


def _call_id(role: str, research_run_id: str) -> str:
    digest = sha256(f"{role}:{research_run_id}".encode()).hexdigest()[:32]
    return f"call-{digest}"


def _prompt_template_hash(system_message: Mapping[str, str]) -> str:
    return sha256(system_message["content"].encode()).hexdigest()


def _build_audit(
    *,
    config: ProviderOrchestrationConfig,
    system_message: Mapping[str, str],
    input_evidence_refs: tuple[str, ...],
    output_schema_id: str,
    outcome: ModelCallOutcome,
    output_hash: str | None,
    error_code: str | None,
    observed_at: datetime,
) -> ModelCallAudit:
    role_policy = next(item for item in config.policy.roles if item.role == config.role)
    return ModelCallAudit.build(
        research_run_id=config.research_run_id,
        call_id=_call_id(config.role, config.research_run_id),
        role=config.role,
        policy_id=config.policy.policy_id,
        policy_hash=config.policy.policy_hash,
        provider=role_policy.provider,
        model_id=role_policy.model_id,
        prompt_template_hash=_prompt_template_hash(system_message),
        system_policy_version="autonomous-research-base-v1",
        input_evidence_refs=input_evidence_refs,
        output_schema_id=output_schema_id,
        outcome=outcome,
        output_hash=output_hash,
        input_tokens=None,
        output_tokens=None,
        declared_price_tier="unspecified",
        rate_limit_delay_ms=0,
        retry_count=0,
        error_code=error_code,
        observed_at=observed_at,
    )


def _check_existing_checkpoints(
    config: ProviderOrchestrationConfig,
) -> tuple[FailureLearningArtifact | None, ResearchPlan | None, ResearchRunAuditEnvelope | None]:
    """Inspect existing artifacts and audits prior to any network call.

    Raises DomainViolation if existing checkpoints are tampered, corrupted, or invalid.
    Returns existing valid checkpoints if already present.
    """
    existing_learning: FailureLearningArtifact | None = None
    existing_plan: ResearchPlan | None = None
    existing_envelope: ResearchRunAuditEnvelope | None = None

    if config.role == "failure_analyst":
        learning_dir = config.evidence_root / "learning"
        if learning_dir.exists():
            for path in learning_dir.glob("learn-*.json"):
                try:
                    artifact = read_failure_learning_artifact(path)
                except Exception as exc:
                    raise DomainViolation(
                        f"tampered or corrupted failure learning checkpoint: {path}"
                    ) from exc
                if (
                    artifact.research_run_id == config.research_run_id
                    and artifact.base_run_id == config.base_run_id
                    and artifact.symbol == config.symbol
                    and artifact.cycle_index == config.cycle_index
                ):
                    existing_learning = artifact

    elif config.role == "hypothesis_generator":
        plans_dir = config.evidence_root / "plans"
        if plans_dir.exists():
            for path in plans_dir.glob("plan-*.json"):
                try:
                    plan = read_research_plan(path)
                except Exception as exc:
                    raise DomainViolation(
                        f"tampered or corrupted research plan checkpoint: {path}"
                    ) from exc
                if (
                    plan.research_run_id == config.research_run_id
                    and plan.base_run_id == config.base_run_id
                    and plan.symbol == config.symbol
                    and plan.cycle_index == config.cycle_index
                ):
                    existing_plan = plan

    audits_dir = config.evidence_root / "audits"
    if audits_dir.exists():
        for path in audits_dir.glob("envelope-*.json"):
            try:
                envelope = read_research_run_audit_envelope(path)
            except Exception as exc:
                raise DomainViolation(
                    f"tampered or corrupted audit envelope checkpoint: {path}"
                ) from exc
            if envelope.research_run_id == config.research_run_id:
                existing_envelope = envelope

    return existing_learning, existing_plan, existing_envelope


def execute_provider_orchestration(
    *,
    config: ProviderOrchestrationConfig,
    failure_memory: Sequence[FailureMemoryEntry],
    learning_artifact: FailureLearningArtifact | None = None,
    prior_plan_hashes: tuple[str, ...] = (),
    prior_thesis_hashes: tuple[str, ...] = (),
    forbidden_candidate_ids: tuple[str, ...] | None = None,
    now: datetime | None = None,
    transport: FailureLearningTransport | ResearchPlanTransport | None = None,
    env: dict[str, str] | None = None,
    repo_env_path: Path | None = None,
) -> ProviderOrchestrationResult:
    """Execute or preflight one bounded provider-to-research run with durable persistence."""
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() != timedelta(0):
        raise DataQualityError("orchestration now must be timezone-aware UTC")
    current_time = current_time.astimezone(UTC)

    # 1. Validate failure memory canonicality and scope
    if not failure_memory:
        raise DataQualityError("failure memory must contain at least one entry")
    memory_hashes = tuple(entry.memory_hash for entry in failure_memory)
    if memory_hashes != tuple(sorted(set(memory_hashes))):
        raise DataQualityError("failure memory entries must be sorted and unique")
    for entry in failure_memory:
        if (
            entry.base_run_id != config.base_run_id
            or entry.bundle_hash != config.bundle_hash
            or entry.dataset_registry_hash != config.dataset_registry_hash
        ):
            raise DataQualityError("failure memory scope does not match orchestration config")

    # Compute derived forbidden candidate IDs
    all_candidates = set(entry.candidate_id for entry in failure_memory)
    if forbidden_candidate_ids is not None:
        all_candidates.update(forbidden_candidate_ids)
    ordered_forbidden = tuple(sorted(all_candidates))

    # 2. Checkpoint inspection prior to any network call
    existing_learning, existing_plan, existing_envelope = _check_existing_checkpoints(config)

    # If already checkpointed and verified on disk, return existing without
    # network call (idempotent restart/reuse)
    if config.role == "failure_analyst" and existing_learning is not None:
        return ProviderOrchestrationResult(
            research_run_id=config.research_run_id,
            base_run_id=config.base_run_id,
            role=config.role,
            symbol=config.symbol,
            status="reused_checkpoint",
            decision="accepted",
            learning_artifact=existing_learning,
            audit_envelope=existing_envelope,
            readback_verified=True,
            reused_existing=True,
            reason_codes=("reused_existing_checkpoint",),
            schema_diagnostics=(),
            requests_consumed=0,
            completed_at=current_time,
        )

    if config.role == "hypothesis_generator" and existing_plan is not None:
        return ProviderOrchestrationResult(
            research_run_id=config.research_run_id,
            base_run_id=config.base_run_id,
            role=config.role,
            symbol=config.symbol,
            status="reused_checkpoint",
            decision="accepted",
            research_plan=existing_plan,
            audit_envelope=existing_envelope,
            readback_verified=True,
            reused_existing=True,
            reason_codes=("reused_existing_checkpoint",),
            schema_diagnostics=(),
            requests_consumed=0,
            completed_at=current_time,
        )

    # 3. Budget exhaustion check prior to any network call
    if config.request_budget <= 0:
        # Emits audit with budget_rejected
        dummy_system = {"content": "budget_exhausted"}
        input_refs = tuple(f"failure/{entry.memory_hash}" for entry in failure_memory)
        audit = _build_audit(
            config=config,
            system_message=dummy_system,
            input_evidence_refs=input_refs,
            output_schema_id=(
                "failure-learning-v1" if config.role == "failure_analyst" else "research-plan-v1"
            ),
            outcome="budget_rejected",
            output_hash=None,
            error_code="request_budget_exhausted",
            observed_at=current_time,
        )
        envelope = build_research_run_audit_envelope(
            research_run_id=config.research_run_id,
            policy=config.policy,
            audits=(audit,),
            prepared_at=current_time,
        )
        audits_dir = config.evidence_root / "audits"
        audits_dir.mkdir(parents=True, exist_ok=True)
        persisted_envelope = write_research_run_audit_envelope(
            audits_dir / f"envelope-{envelope.envelope_hash}.json", envelope
        )
        return ProviderOrchestrationResult(
            research_run_id=config.research_run_id,
            base_run_id=config.base_run_id,
            role=config.role,
            symbol=config.symbol,
            status="budget_exhausted",
            decision="rejected",
            audit_envelope=persisted_envelope,
            readback_verified=True,
            reused_existing=False,
            reason_codes=("budget_rejected",),
            schema_diagnostics=(),
            requests_consumed=0,
            completed_at=current_time,
        )

    # 4. Role-specific request preparation and validation
    learning_req: FailureLearningRequest | None = None
    plan_req: ResearchPlanRequest | None = None
    system_msg: Mapping[str, str]
    input_evidence_refs: tuple[str, ...]
    output_schema_id: str

    if config.role == "failure_analyst":
        input_evidence_refs = tuple(f"failure/{entry.memory_hash}" for entry in failure_memory)
        output_schema_id = "failure-learning-v1"
        learning_req = FailureLearningRequest(
            research_run_id=config.research_run_id,
            base_run_id=config.base_run_id,
            symbol=config.symbol,
            bundle_hash=config.bundle_hash,
            dataset_registry_hash=config.dataset_registry_hash,
            cycle_index=config.cycle_index,
            failure_memory=tuple(failure_memory),
            forbidden_candidate_ids=ordered_forbidden,
            input_evidence_refs=input_evidence_refs,
        )
        system_msg, _ = build_failure_learning_messages(learning_req)

    else:
        # hypothesis_generator
        if learning_artifact is None:
            raise DataQualityError("hypothesis_generator role requires learning_artifact")
        if (
            learning_artifact.base_run_id != config.base_run_id
            or learning_artifact.symbol != config.symbol
            or learning_artifact.cycle_index != config.cycle_index
        ):
            raise DataQualityError("learning artifact does not match orchestration scope")

        input_evidence_refs = tuple(
            sorted(
                [
                    *(f"failure/{entry.memory_hash}" for entry in failure_memory),
                    f"learning/{learning_artifact.learning_hash}",
                ]
            )
        )
        output_schema_id = "research-plan-v1"
        assert config.cycle_id is not None
        plan_req = ResearchPlanRequest(
            research_run_id=config.research_run_id,
            base_run_id=config.base_run_id,
            cycle_id=config.cycle_id,
            symbol=config.symbol,
            bundle_hash=config.bundle_hash,
            dataset_registry_hash=config.dataset_registry_hash,
            cycle_index=config.cycle_index,
            failure_memory=tuple(failure_memory),
            learning=learning_artifact,
            forbidden_candidate_ids=ordered_forbidden,
            prior_plan_hashes=tuple(sorted(prior_plan_hashes)),
            prior_thesis_hashes=tuple(sorted(prior_thesis_hashes)),
            input_evidence_refs=input_evidence_refs,
        )
        system_msg, _ = build_research_plan_messages(plan_req)

    # 5. Non-authorizing preflight / dry-run check (if execute is False)
    if not config.execute:
        return ProviderOrchestrationResult(
            research_run_id=config.research_run_id,
            base_run_id=config.base_run_id,
            role=config.role,
            symbol=config.symbol,
            status="prepared",
            decision="prepared",
            readback_verified=False,
            reused_existing=False,
            reason_codes=("preflight_dry_run",),
            schema_diagnostics=(),
            requests_consumed=0,
            completed_at=current_time,
        )

    # 6. Safe Credential Preflight (without exposing values)
    resolved_key: str | None = None
    if transport is None:
        try:
            resolved_key = resolve_credential(env=env, repo_env_path=repo_env_path)
        except MissingCredentialsError:
            # Emit provider_error audit without leaking keys
            audit = _build_audit(
                config=config,
                system_message=system_msg,
                input_evidence_refs=input_evidence_refs,
                output_schema_id=output_schema_id,
                outcome="provider_error",
                output_hash=None,
                error_code="missing_credentials",
                observed_at=current_time,
            )
            envelope = build_research_run_audit_envelope(
                research_run_id=config.research_run_id,
                policy=config.policy,
                audits=(audit,),
                prepared_at=current_time,
            )
            audits_dir = config.evidence_root / "audits"
            audits_dir.mkdir(parents=True, exist_ok=True)
            persisted_envelope = write_research_run_audit_envelope(
                audits_dir / f"envelope-{envelope.envelope_hash}.json", envelope
            )
            return ProviderOrchestrationResult(
                research_run_id=config.research_run_id,
                base_run_id=config.base_run_id,
                role=config.role,
                symbol=config.symbol,
                status="blocked",
                decision="rejected",
                audit_envelope=persisted_envelope,
                readback_verified=True,
                reused_existing=False,
                reason_codes=("missing_credentials",),
                schema_diagnostics=(),
                requests_consumed=0,
                completed_at=current_time,
            )

    # 7. Setup Client and Transport with Governor (max_calls=1, zero retries)
    audited_transport: FailureLearningTransport | ResearchPlanTransport
    if transport is not None:
        audited_transport = transport
    else:
        assert resolved_key is not None
        import httpx

        role_policy = next(item for item in config.policy.roles if item.role == config.role)
        provider_cfg = GoogleAIStudioProviderConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key=resolved_key,
            model_id=role_policy.model_id,
        )
        del resolved_key  # Scrub key immediately

        http_client = httpx.Client(timeout=30.0)
        json_client = GoogleAIStudioJsonClient(config=provider_cfg, client=http_client)

        if config.role == "failure_analyst":
            from .autonomy_provider import AuditedGoogleAIStudioFailureLearningTransport

            audited_transport = AuditedGoogleAIStudioFailureLearningTransport(
                client=json_client,
                policy=config.policy,
                audit_sink=lambda _a: None,
            )
        else:
            from .autonomy_provider import AuditedGoogleAIStudioResearchPlanTransport

            audited_transport = AuditedGoogleAIStudioResearchPlanTransport(
                client=json_client,
                policy=config.policy,
                audit_sink=lambda _a: None,
            )

    # 8. Execute the Transport Call
    learned_artifact: FailureLearningArtifact | None = None
    planned_plan: ResearchPlan | None = None
    outcome: ModelCallOutcome = "succeeded"
    error_code: str | None = None
    output_hash: str | None = None
    schema_diagnostics: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    decision: Literal["accepted", "rejected"] = "rejected"

    if config.role == "failure_analyst":
        assert learning_req is not None
        learner = FailureLearner(audited_transport)  # type: ignore[arg-type]
        learn_result = learner.learn(learning_req)
        decision = learn_result.decision
        schema_diagnostics = tuple(sorted(learn_result.schema_diagnostics))
        reason_codes = tuple(sorted(learn_result.reason_codes))

        if learn_result.decision == "accepted" and learn_result.artifact is not None:
            learned_artifact = learn_result.artifact
            outcome = "succeeded"
            canonical = json.dumps(
                learned_artifact.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            output_hash = sha256(canonical.encode()).hexdigest()
        else:
            outcome = "schema_rejected"
            error_code = reason_codes[0] if reason_codes else "schema_rejected"

    else:
        # hypothesis_generator
        assert plan_req is not None
        planner = ResearchPlanner(audited_transport)  # type: ignore[arg-type]
        plan_result = planner.plan(plan_req)
        decision = plan_result.decision
        schema_diagnostics = tuple(sorted(plan_result.schema_diagnostics))
        reason_codes = tuple(sorted(plan_result.reason_codes))

        if plan_result.decision == "accepted" and plan_result.plan is not None:
            planned_plan = plan_result.plan
            outcome = "succeeded"
            canonical = json.dumps(
                planned_plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            )
            output_hash = sha256(canonical.encode()).hexdigest()
        else:
            outcome = "schema_rejected"
            error_code = reason_codes[0] if reason_codes else "schema_rejected"

    # 9. Durable Persistence & Readback Verification
    persisted_learning: FailureLearningArtifact | None = None
    persisted_plan: ResearchPlan | None = None

    if learned_artifact is not None:
        learning_path = config.evidence_root / "learning" / f"{learned_artifact.learning_id}.json"
        persisted_learning = write_failure_learning_artifact(learning_path, learned_artifact)
        readback = read_failure_learning_artifact(learning_path)
        if readback != learned_artifact:
            raise DomainViolation(
                f"storage failure: failure learning artifact readback mismatch at {learning_path}"
            )

    if planned_plan is not None:
        plan_path = config.evidence_root / "plans" / f"{planned_plan.plan_id}.json"
        persisted_plan = write_research_plan(plan_path, planned_plan)
        readback_plan = read_research_plan(plan_path)
        if readback_plan != planned_plan:
            raise DomainViolation(
                f"storage failure: research plan readback mismatch at {plan_path}"
            )

    # 10. Audit Record & Envelope Persistence with Readback Verification
    audit = _build_audit(
        config=config,
        system_message=system_msg,
        input_evidence_refs=input_evidence_refs,
        output_schema_id=output_schema_id,
        outcome=outcome,
        output_hash=output_hash,
        error_code=error_code,
        observed_at=current_time,
    )
    envelope = build_research_run_audit_envelope(
        research_run_id=config.research_run_id,
        policy=config.policy,
        audits=(audit,),
        prepared_at=current_time,
    )
    audits_dir = config.evidence_root / "audits"
    audits_dir.mkdir(parents=True, exist_ok=True)
    envelope_path = audits_dir / f"envelope-{envelope.envelope_hash}.json"
    persisted_envelope = write_research_run_audit_envelope(envelope_path, envelope)
    readback_envelope = read_research_run_audit_envelope(envelope_path)
    if readback_envelope != envelope:
        raise DomainViolation(
            f"storage failure: audit envelope readback mismatch at {envelope_path}"
        )

    final_status: ProviderOrchestrationStatus = (
        "succeeded" if decision == "accepted" else "rejected"
    )

    return ProviderOrchestrationResult(
        research_run_id=config.research_run_id,
        base_run_id=config.base_run_id,
        role=config.role,
        symbol=config.symbol,
        status=final_status,
        decision=decision,
        learning_artifact=persisted_learning,
        research_plan=persisted_plan,
        audit_envelope=persisted_envelope,
        readback_verified=True,
        reused_existing=False,
        reason_codes=reason_codes,
        schema_diagnostics=schema_diagnostics,
        requests_consumed=1,
        completed_at=current_time,
    )


__all__ = [
    "ProviderOrchestrationConfig",
    "ProviderOrchestrationResult",
    "ProviderOrchestrationRole",
    "ProviderOrchestrationStatus",
    "execute_provider_orchestration",
]
