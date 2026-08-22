from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.model_audit import ModelCallAudit
from autonomous_futures.research_lab.model_policy import (
    LLMRolePolicy,
    ResearchModelPolicy,
    build_research_model_policy,
)
from autonomous_futures.research_lab.research_run_audit import (
    ResearchRunAuditEnvelope,
    build_research_run_audit_envelope,
)
from autonomous_futures.research_lab.research_run_audit_handoff import (
    build_verified_research_run_audit_handoff,
)
from autonomous_futures.research_lab.research_run_audit_persistence import (
    write_research_run_audit_envelope,
)


def _policy() -> ResearchModelPolicy:
    return build_research_model_policy(
        policy_id="research-model-policy-v1",
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="hypothesis_generator",
                provider="opencode",
                model_id="x-preview-f-free",
                temperature=Decimal("0.20"),
                max_output_tokens=800,
                max_requests_per_batch=4,
                max_retries=1,
            ),
        ),
    )


def _audit(
    policy: ResearchModelPolicy,
    *,
    call_id: str,
    outcome: str = "succeeded",
) -> ModelCallAudit:
    succeeded = outcome == "succeeded"
    return ModelCallAudit.build(
        research_run_id="research-run-0001",
        call_id=call_id,
        role="hypothesis_generator",
        policy_id=policy.policy_id,
        policy_hash=policy.policy_hash,
        provider="opencode",
        model_id="x-preview-f-free",
        prompt_template_hash="b" * 64,
        system_policy_version="research-system-policy-v1",
        input_evidence_refs=("dataset-manifest:abc",),
        output_schema_id="hypothesis-v1",
        outcome=outcome,
        output_hash="c" * 64 if succeeded else None,
        input_tokens=100 if succeeded else None,
        output_tokens=200 if succeeded else None,
        declared_price_tier="free",
        rate_limit_delay_ms=0,
        retry_count=0,
        error_code=None if succeeded else "provider_error",
        observed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )


def _envelope(policy: ResearchModelPolicy) -> ResearchRunAuditEnvelope:
    return build_research_run_audit_envelope(
        research_run_id="research-run-0001",
        policy=policy,
        audits=(
            _audit(policy, call_id="model-call-0001"),
            _audit(policy, call_id="model-call-0002", outcome="provider_error"),
        ),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )


def test_verified_research_run_audit_handoff_summarizes_only_verified_evidence(
    tmp_path: Path,
) -> None:
    policy = _policy()
    envelope = _envelope(policy)
    path = tmp_path / "research-run-0001.json"
    write_research_run_audit_envelope(path, envelope)

    handoff = build_verified_research_run_audit_handoff(path, policy=policy)

    assert handoff.handoff_status == "verified_audit_only"
    assert handoff.research_run_id == envelope.research_run_id
    assert handoff.source_envelope_hash == envelope.envelope_hash
    assert handoff.audit_count == 2
    assert handoff.succeeded_count == 1
    assert handoff.failed_count == 1
    assert handoff.promotion_state == "unpromoted"
    assert handoff.paper_activation is False
    assert handoff.execution_authority is False


def test_research_run_audit_handoff_rejects_invalid_policy_before_summary(
    tmp_path: Path,
) -> None:
    policy = _policy()
    path = tmp_path / "research-run-0001.json"
    write_research_run_audit_envelope(path, _envelope(policy))
    invalid_policy = policy.model_copy(update={"policy_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="policy hash mismatch"):
        build_verified_research_run_audit_handoff(path, policy=invalid_policy)


def test_research_run_audit_handoff_hash_excludes_creation_time(tmp_path: Path) -> None:
    policy = _policy()
    path = tmp_path / "research-run-0001.json"
    write_research_run_audit_envelope(path, _envelope(policy))

    first = build_verified_research_run_audit_handoff(
        path,
        policy=policy,
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    second = build_verified_research_run_audit_handoff(
        path,
        policy=policy,
        created_at=datetime(2026, 8, 9, 1, tzinfo=UTC),
    )

    assert first.handoff_hash == second.handoff_hash
    assert first.created_at != second.created_at
