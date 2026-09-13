"""Direct provider adapters for the autonomous learner and planner roles."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from ..research_lab.model_audit import ModelCallAudit, ModelCallOutcome
from ..research_lab.model_policy import (
    LLMRolePolicy,
    ResearchModelPolicy,
    ResearchRole,
    research_model_policy_content_hash,
)
from .autonomy_contracts import (
    FailureLearner,
    FailureLearningRequest,
    FailureLearningTransport,
    ResearchPlanner,
    ResearchPlanRequest,
    ResearchPlanTransport,
)
from .autonomy_prompts import build_failure_learning_messages, build_research_plan_messages
from .google_ai_studio_provider import (
    GoogleAIStudioJsonClient,
    ProviderJsonPayload,
    ProviderTransportError,
)

if TYPE_CHECKING:
    from ..pipeline.autonomous_base import (
        AutonomousBaseConfig,
        AutonomousResearchBase,
        BaseCycleRunner,
    )

AuditSink = Callable[[ModelCallAudit], object]


def _role_policy(policy: ResearchModelPolicy, role: ResearchRole) -> LLMRolePolicy:
    role_policy = next((item for item in policy.roles if item.role == role), None)
    if role_policy is None:
        raise ValueError(f"research model policy has no {role} role")
    return role_policy


def _call_id(role: ResearchRole, research_run_id: str) -> str:
    digest = sha256(f"{role}:{research_run_id}".encode()).hexdigest()[:32]
    return f"call-{digest}"


def _prompt_template_hash(system_message: Mapping[str, str]) -> str:
    return sha256(system_message["content"].encode()).hexdigest()


def _safe_error_code(error: ProviderTransportError) -> str:
    if isinstance(error.error_code, str) and error.error_code:
        return error.error_code[:128]
    return error.code[:128]


def _emit_audit(
    *,
    audit_sink: AuditSink,
    request_id: str,
    role: ResearchRole,
    policy: ResearchModelPolicy,
    system_message: Mapping[str, str],
    input_evidence_refs: tuple[str, ...],
    output_schema_id: str,
    outcome: ModelCallOutcome,
    output_hash: str | None,
    error_code: str | None,
) -> None:
    role_policy = _role_policy(policy, role)
    audit = ModelCallAudit.build(
        research_run_id=request_id,
        call_id=_call_id(role, request_id),
        role=role,
        policy_id=policy.policy_id,
        policy_hash=policy.policy_hash,
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
        observed_at=datetime.now(UTC),
    )
    audit_sink(audit)


def _validate_client_binding(
    *, client: GoogleAIStudioJsonClient, policy: ResearchModelPolicy, role: ResearchRole
) -> None:
    if research_model_policy_content_hash(policy) != policy.policy_hash:
        raise ValueError("research model policy hash mismatch")
    role_policy = _role_policy(policy, role)
    if role_policy.provider != "google_ai_studio":
        raise ValueError("autonomy transport requires google_ai_studio policy binding")
    if role_policy.model_id != client.config.model_id:
        raise ValueError("research model policy model does not match provider client model")
    if role_policy.max_retries != 0:
        raise ValueError("autonomy transport requires max_retries=0")


def _output_hash(payload: ProviderJsonPayload) -> str:
    metadata_hash = payload.metadata.get("content_sha256")
    if isinstance(metadata_hash, str) and len(metadata_hash) == 64:
        return metadata_hash
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class GoogleAIStudioFailureLearningTransport:
    """Call Google AI Studio for one bounded failure-learning request."""

    client: GoogleAIStudioJsonClient
    temperature: float = 0.2
    max_output_tokens: int = 2048

    def __call__(self, request: FailureLearningRequest) -> Mapping[str, object]:
        system, user = build_failure_learning_messages(request)
        return self.client.complete_json(
            messages=(system, user),
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )


@dataclass(frozen=True, slots=True)
class GoogleAIStudioResearchPlanTransport:
    """Call Google AI Studio for one bounded next-experiment plan."""

    client: GoogleAIStudioJsonClient
    temperature: float = 0.2
    max_output_tokens: int = 2048

    def __call__(self, request: ResearchPlanRequest) -> Mapping[str, object]:
        system, user = build_research_plan_messages(request)
        return self.client.complete_json(
            messages=(system, user),
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )


@dataclass(frozen=True, slots=True)
class AuditedGoogleAIStudioFailureLearningTransport:
    """Policy-bound learner transport that emits a hash-only call audit."""

    client: GoogleAIStudioJsonClient
    policy: ResearchModelPolicy
    audit_sink: AuditSink

    def __post_init__(self) -> None:
        _validate_client_binding(client=self.client, policy=self.policy, role="failure_analyst")

    def __call__(self, request: FailureLearningRequest) -> Mapping[str, object]:
        system, user = build_failure_learning_messages(request)
        try:
            payload = self.client.complete_json(
                messages=(system, user),
                temperature=float(_role_policy(self.policy, "failure_analyst").temperature),
                max_output_tokens=_role_policy(self.policy, "failure_analyst").max_output_tokens,
            )
        except ProviderTransportError as error:
            _emit_audit(
                audit_sink=self.audit_sink,
                request_id=request.research_run_id,
                role="failure_analyst",
                policy=self.policy,
                system_message=system,
                input_evidence_refs=request.input_evidence_refs,
                output_schema_id=request.output_schema_id,
                outcome="provider_error",
                output_hash=None,
                error_code=_safe_error_code(error),
            )
            raise
        _emit_audit(
            audit_sink=self.audit_sink,
            request_id=request.research_run_id,
            role="failure_analyst",
            policy=self.policy,
            system_message=system,
            input_evidence_refs=request.input_evidence_refs,
            output_schema_id=request.output_schema_id,
            outcome="succeeded",
            output_hash=_output_hash(payload),
            error_code=None,
        )
        return payload


@dataclass(frozen=True, slots=True)
class AuditedGoogleAIStudioResearchPlanTransport:
    """Policy-bound planner transport that emits a hash-only call audit."""

    client: GoogleAIStudioJsonClient
    policy: ResearchModelPolicy
    audit_sink: AuditSink

    def __post_init__(self) -> None:
        _validate_client_binding(
            client=self.client, policy=self.policy, role="hypothesis_generator"
        )

    def __call__(self, request: ResearchPlanRequest) -> Mapping[str, object]:
        system, user = build_research_plan_messages(request)
        try:
            payload = self.client.complete_json(
                messages=(system, user),
                temperature=float(_role_policy(self.policy, "hypothesis_generator").temperature),
                max_output_tokens=_role_policy(
                    self.policy, "hypothesis_generator"
                ).max_output_tokens,
            )
        except ProviderTransportError as error:
            _emit_audit(
                audit_sink=self.audit_sink,
                request_id=request.research_run_id,
                role="hypothesis_generator",
                policy=self.policy,
                system_message=system,
                input_evidence_refs=request.input_evidence_refs,
                output_schema_id=request.output_schema_id,
                outcome="provider_error",
                output_hash=None,
                error_code=_safe_error_code(error),
            )
            raise
        _emit_audit(
            audit_sink=self.audit_sink,
            request_id=request.research_run_id,
            role="hypothesis_generator",
            policy=self.policy,
            system_message=system,
            input_evidence_refs=request.input_evidence_refs,
            output_schema_id=request.output_schema_id,
            outcome="succeeded",
            output_hash=_output_hash(payload),
            error_code=None,
        )
        return payload


def build_google_ai_studio_autonomous_base(
    *,
    config: AutonomousBaseConfig,
    learner_client: GoogleAIStudioJsonClient,
    planner_client: GoogleAIStudioJsonClient,
    policy: ResearchModelPolicy,
    audit_sink: AuditSink,
    cycle_runner: BaseCycleRunner,
) -> AutonomousResearchBase:
    """Wire policy-bound provider roles into the offline base without calling HTTP."""
    from ..pipeline.autonomous_base import AutonomousResearchBase

    return AutonomousResearchBase(
        config=config,
        learner=FailureLearner(
            AuditedGoogleAIStudioFailureLearningTransport(
                client=learner_client,
                policy=policy,
                audit_sink=audit_sink,
            )
        ),
        planner=ResearchPlanner(
            AuditedGoogleAIStudioResearchPlanTransport(
                client=planner_client,
                policy=policy,
                audit_sink=audit_sink,
            )
        ),
        cycle_runner=cycle_runner,
    )


__all__ = [
    "AuditSink",
    "AuditedGoogleAIStudioFailureLearningTransport",
    "AuditedGoogleAIStudioResearchPlanTransport",
    "build_google_ai_studio_autonomous_base",
    "FailureLearningTransport",
    "GoogleAIStudioFailureLearningTransport",
    "GoogleAIStudioResearchPlanTransport",
    "ResearchPlanTransport",
]
