from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autonomous_futures.research_lab.model_audit import ModelCallAudit
from autonomous_futures.research_lab.model_policy import (
    LLMRolePolicy,
    ResearchModelPolicy,
    build_research_model_policy,
)
from autonomous_futures.research_lab.research_run_audit import (
    ResearchRunAuditEnvelope,
    build_research_run_audit_envelope,
    research_run_audit_content_hash,
)


def _policy() -> ResearchModelPolicy:
    return build_research_model_policy(
        policy_id="research-model-policy-v1",
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="hypothesis_generator",
                provider="google_ai_studio",
                model_id="gemma-4-26b-a4b-it",
                temperature=Decimal("0.20"),
                max_output_tokens=800,
                max_requests_per_batch=4,
                max_retries=0,
            ),
        ),
    )


def _audit(policy: ResearchModelPolicy, call_id: str) -> ModelCallAudit:
    return ModelCallAudit.build(
        research_run_id="research-run-0001",
        call_id=call_id,
        role="hypothesis_generator",
        policy_id=policy.policy_id,
        policy_hash=policy.policy_hash,
        provider="google_ai_studio",
        model_id="gemma-4-26b-a4b-it",
        prompt_template_hash="b" * 64,
        system_policy_version="research-system-policy-v1",
        input_evidence_refs=("dataset-manifest:abc",),
        output_schema_id="hypothesis-v1",
        outcome="succeeded",
        output_hash="c" * 64,
        input_tokens=100,
        output_tokens=200,
        declared_price_tier="free",
        rate_limit_delay_ms=0,
        retry_count=0,
        error_code=None,
        observed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )


def test_research_run_audit_envelope_is_sorted_policy_bound_and_hashed() -> None:
    policy = _policy()
    envelope = build_research_run_audit_envelope(
        research_run_id="research-run-0001",
        policy=policy,
        audits=(_audit(policy, "model-call-0002"), _audit(policy, "model-call-0001")),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert tuple(audit.call_id for audit in envelope.audits) == (
        "model-call-0001",
        "model-call-0002",
    )
    assert envelope.policy_id == policy.policy_id
    assert envelope.policy_hash == policy.policy_hash
    assert envelope.status == "audit_only"
    assert research_run_audit_content_hash(envelope) == envelope.envelope_hash


def test_research_run_audit_envelope_rejects_duplicate_call_ids() -> None:
    policy = _policy()

    with pytest.raises((ValidationError, ValueError), match="unique"):
        ResearchRunAuditEnvelope(
            research_run_id="research-run-0001",
            policy_id=policy.policy_id,
            policy_hash=policy.policy_hash,
            audits=(_audit(policy, "model-call-0001"), _audit(policy, "model-call-0001")),
            status="audit_only",
            prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
            envelope_hash="0" * 64,
        )


def test_research_run_audit_envelope_rejects_run_and_policy_binding_drift() -> None:
    policy = _policy()
    with pytest.raises((ValidationError, ValueError), match="research ID binding"):
        build_research_run_audit_envelope(
            research_run_id="research-run-0002",
            policy=policy,
            audits=(_audit(policy, "model-call-0001"),),
            prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        )

    drifted_policy = build_research_model_policy(
        policy_id=policy.policy_id,
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="hypothesis_generator",
                provider="google_ai_studio",
                model_id="gemma-4-26b-a4b-it",
                temperature=Decimal("0.25"),
                max_output_tokens=800,
                max_requests_per_batch=4,
                max_retries=0,
            ),
        ),
    )
    with pytest.raises((ValidationError, ValueError), match="policy binding"):
        build_research_run_audit_envelope(
            research_run_id="research-run-0001",
            policy=drifted_policy,
            audits=(_audit(policy, "model-call-0001"),),
            prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
        )


def test_research_run_audit_content_hash_excludes_preparation_time() -> None:
    policy = _policy()
    first = build_research_run_audit_envelope(
        research_run_id="research-run-0001",
        policy=policy,
        audits=(_audit(policy, "model-call-0001"),),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = build_research_run_audit_envelope(
        research_run_id="research-run-0001",
        policy=policy,
        audits=(_audit(policy, "model-call-0001"),),
        prepared_at=first.prepared_at + timedelta(hours=1),
    )

    assert first.envelope_hash == second.envelope_hash
    assert first.prepared_at != second.prepared_at
