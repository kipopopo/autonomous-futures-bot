from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.model_audit import (
    ModelCallAudit,
    model_call_audit_content_hash,
    write_model_call_audit,
)
from autonomous_futures.research_lab.model_audit_input import load_verified_model_call_audit
from autonomous_futures.research_lab.model_policy import (
    LLMRolePolicy,
    ResearchModelPolicy,
    build_research_model_policy,
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


def _audit(policy: ResearchModelPolicy) -> ModelCallAudit:
    return ModelCallAudit.build(
        research_run_id="research-run-0001",
        call_id="model-call-0001",
        role="hypothesis_generator",
        policy_id=policy.policy_id,
        policy_hash=policy.policy_hash,
        provider="opencode",
        model_id="x-preview-f-free",
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


def test_verified_model_call_audit_loader_returns_policy_bound_evidence(
    tmp_path: Path,
) -> None:
    policy = _policy()
    audit = _audit(policy)
    path = tmp_path / "audits" / "model-call-0001.json"
    write_model_call_audit(path, audit)
    source_bytes = path.read_bytes()

    loaded = load_verified_model_call_audit(path, policy=policy)

    assert loaded == audit
    assert path.read_bytes() == source_bytes


def test_verified_model_call_audit_loader_rejects_valid_policy_hash_drift(
    tmp_path: Path,
) -> None:
    policy = _policy()
    audit = _audit(policy)
    path = tmp_path / "audits" / "model-call-0001.json"
    write_model_call_audit(path, audit)
    drifted_policy = build_research_model_policy(
        policy_id=policy.policy_id,
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="hypothesis_generator",
                provider="opencode",
                model_id="x-preview-f-free",
                temperature=Decimal("0.25"),
                max_output_tokens=800,
                max_requests_per_batch=4,
                max_retries=1,
            ),
        ),
    )

    with pytest.raises(DomainViolation, match="policy binding"):
        load_verified_model_call_audit(path, policy=drifted_policy)


def test_verified_model_call_audit_loader_rejects_valid_hash_role_drift(tmp_path: Path) -> None:
    policy = _policy()
    audit = _audit(policy)
    roleless_policy = build_research_model_policy(
        policy_id=policy.policy_id,
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="economic_critic",
                provider="opencode",
                model_id="x-preview-f-free",
                temperature=Decimal("0.20"),
                max_output_tokens=800,
                max_requests_per_batch=4,
                max_retries=1,
            ),
        ),
    )
    drifted = audit.model_copy(update={"policy_hash": roleless_policy.policy_hash})
    drifted = drifted.model_copy(update={"audit_hash": model_call_audit_content_hash(drifted)})
    path = tmp_path / "audits" / "role-drift.json"
    write_model_call_audit(path, drifted)

    with pytest.raises(DomainViolation, match="role binding"):
        load_verified_model_call_audit(path, policy=roleless_policy)


def test_verified_model_call_audit_loader_rejects_unverified_caller_policy(
    tmp_path: Path,
) -> None:
    policy = _policy()
    audit = _audit(policy)
    path = tmp_path / "audits" / "model-call-0001.json"
    write_model_call_audit(path, audit)
    invalid_policy = policy.model_copy(update={"policy_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="policy hash mismatch"):
        load_verified_model_call_audit(path, policy=invalid_policy)
