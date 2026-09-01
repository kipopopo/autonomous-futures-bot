from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from autonomous_futures.research_lab.model_policy import (
    GemmaModelId,
    LLMRolePolicy,
    ResearchModelPolicy,
    build_research_model_policy,
    research_model_policy_content_hash,
)


def _role(role: str, model_id: GemmaModelId = "gemma-4-26b-a4b-it") -> LLMRolePolicy:
    return LLMRolePolicy(
        role=role,
        provider="google_ai_studio",
        model_id=model_id,
        temperature=Decimal("0.20"),
        max_output_tokens=800,
        max_requests_per_batch=4,
        max_retries=0,
    )


def test_research_model_policy_is_pinned_sorted_and_canonically_hashed() -> None:
    policy = build_research_model_policy(
        policy_id="research-model-policy-v1",
        policy_version=1,
        roles=(
            _role("strategy_spec_author", "gemma-4-31b-it"),
            _role("failure_analyst"),
            _role("hypothesis_generator"),
            _role("economic_critic", "gemma-4-31b-it"),
        ),
    )

    assert tuple(role.role for role in policy.roles) == (
        "economic_critic",
        "failure_analyst",
        "hypothesis_generator",
        "strategy_spec_author",
    )
    assert {(role.provider, role.model_id) for role in policy.roles} == {
        ("google_ai_studio", "gemma-4-26b-a4b-it"),
        ("google_ai_studio", "gemma-4-31b-it"),
    }
    assert research_model_policy_content_hash(policy) == policy.policy_hash
    assert len(policy.policy_hash) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", Decimal("NaN")),
        ("temperature", Decimal("2.01")),
        ("max_output_tokens", 0),
        ("max_requests_per_batch", 0),
        ("max_retries", 1),
        ("max_retries", -1),
    ],
)
def test_role_policy_rejects_invalid_budget_values(field: str, value: Decimal | int) -> None:
    payload: dict[str, object] = {
        "role": "hypothesis_generator",
        "provider": "google_ai_studio",
        "model_id": "gemma-4-26b-a4b-it",
        "temperature": Decimal("0.20"),
        "max_output_tokens": 800,
        "max_requests_per_batch": 4,
        "max_retries": 0,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        LLMRolePolicy.model_validate(payload)


def test_research_model_policy_rejects_duplicate_roles() -> None:
    with pytest.raises(ValidationError, match="unique"):
        build_research_model_policy(
            policy_id="research-model-policy-v1",
            policy_version=1,
            roles=(_role("hypothesis_generator"), _role("hypothesis_generator")),
        )


def test_research_model_policy_rejects_caller_supplied_hash_drift() -> None:
    roles = (_role("economic_critic"),)

    with pytest.raises(ValidationError, match="hash mismatch"):
        ResearchModelPolicy(
            policy_id="research-model-policy-v1",
            policy_version=1,
            roles=roles,
            policy_hash="f" * 64,
        )
