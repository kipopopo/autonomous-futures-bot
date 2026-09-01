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
from autonomous_futures.research_lab.research_run_audit_input import (
    load_verified_research_run_audit_envelope,
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
                provider="google_ai_studio",
                model_id="gemma-4-26b-a4b-it",
                temperature=Decimal("0.20"),
                max_output_tokens=800,
                max_requests_per_batch=4,
                max_retries=0,
            ),
        ),
    )


def _envelope(policy: ResearchModelPolicy) -> ResearchRunAuditEnvelope:
    audit = ModelCallAudit.build(
        research_run_id="research-run-0001",
        call_id="model-call-0001",
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
    return build_research_run_audit_envelope(
        research_run_id="research-run-0001",
        policy=policy,
        audits=(audit,),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )


def test_verified_research_run_audit_loader_returns_bound_envelope(
    tmp_path: Path,
) -> None:
    policy = _policy()
    envelope = _envelope(policy)
    path = tmp_path / "research-run-0001.json"
    write_research_run_audit_envelope(path, envelope)
    source_bytes = path.read_bytes()

    loaded = load_verified_research_run_audit_envelope(path, policy=policy)

    assert loaded == envelope
    assert path.read_bytes() == source_bytes


def test_verified_research_run_audit_loader_rejects_invalid_caller_policy(
    tmp_path: Path,
) -> None:
    policy = _policy()
    envelope = _envelope(policy)
    path = tmp_path / "research-run-0001.json"
    write_research_run_audit_envelope(path, envelope)
    invalid_policy = policy.model_copy(update={"policy_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="policy hash mismatch"):
        load_verified_research_run_audit_envelope(path, policy=invalid_policy)


def test_verified_research_run_audit_loader_rejects_valid_role_drift(
    tmp_path: Path,
) -> None:
    original_policy = _policy()
    roleless_policy = build_research_model_policy(
        policy_id=original_policy.policy_id,
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="economic_critic",
                provider="google_ai_studio",
                model_id="gemma-4-26b-a4b-it",
                temperature=Decimal("0.20"),
                max_output_tokens=800,
                max_requests_per_batch=4,
                max_retries=0,
            ),
        ),
    )
    envelope = _envelope(roleless_policy)
    path = tmp_path / "research-run-0001.json"
    write_research_run_audit_envelope(path, envelope)

    with pytest.raises(DomainViolation, match="role binding"):
        load_verified_research_run_audit_envelope(path, policy=roleless_policy)
