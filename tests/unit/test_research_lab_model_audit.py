from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from autonomous_futures.research_lab.model_audit import (
    ModelCallAudit,
    model_call_audit_content_hash,
)


def _success_kwargs() -> dict[str, object]:
    return {
        "research_run_id": "research-run-0001",
        "call_id": "model-call-0001",
        "role": "hypothesis_generator",
        "policy_id": "research-model-policy-v1",
        "policy_hash": "a" * 64,
        "provider": "google_ai_studio",
        "model_id": "gemma-4-26b-a4b-it",
        "prompt_template_hash": "b" * 64,
        "system_policy_version": "research-system-policy-v1",
        "input_evidence_refs": ("dataset-manifest:abc", "prior-failure:def"),
        "output_schema_id": "hypothesis-v1",
        "outcome": "succeeded",
        "output_hash": "c" * 64,
        "input_tokens": 100,
        "output_tokens": 200,
        "declared_price_tier": "free",
        "rate_limit_delay_ms": 0,
        "retry_count": 0,
        "error_code": None,
        "observed_at": datetime(2026, 8, 9, tzinfo=UTC),
    }


def test_successful_model_call_audit_binds_policy_and_hashes() -> None:
    audit = ModelCallAudit.build(**_success_kwargs())  # type: ignore[arg-type]

    assert audit.policy_id == "research-model-policy-v1"
    assert audit.policy_hash == "a" * 64
    assert audit.role == "hypothesis_generator"
    assert (audit.provider, audit.model_id) == (
        "google_ai_studio",
        "gemma-4-26b-a4b-it",
    )
    assert audit.prompt_template_hash == "b" * 64
    assert audit.input_evidence_refs == ("dataset-manifest:abc", "prior-failure:def")
    assert audit.output_schema_id == "hypothesis-v1"
    assert audit.output_hash == "c" * 64
    assert (audit.input_tokens, audit.output_tokens) == (100, 200)
    assert audit.observed_at == datetime(2026, 8, 9, tzinfo=UTC)
    assert model_call_audit_content_hash(audit) == audit.audit_hash


@pytest.mark.parametrize(
    ("outcome", "updates"),
    [
        ("succeeded", {"output_hash": None}),
        (
            "provider_model_unavailable",
            {"output_hash": "c" * 64, "error_code": "provider_model_unavailable"},
        ),
        ("provider_model_unavailable", {"output_hash": None, "error_code": None}),
        ("budget_rejected", {"output_hash": None, "input_tokens": 1, "output_tokens": 1}),
    ],
)
def test_model_call_audit_rejects_invalid_outcome_metadata(
    outcome: str, updates: dict[str, object]
) -> None:
    payload = _success_kwargs() | {"outcome": outcome} | updates

    with pytest.raises(ValidationError):
        ModelCallAudit.build(**payload)  # type: ignore[arg-type]


def test_model_call_audit_requires_utc_observed_at() -> None:
    payload = _success_kwargs() | {
        "observed_at": datetime(2026, 8, 9, tzinfo=timezone(timedelta(hours=8)))
    }

    with pytest.raises(ValidationError, match="UTC"):
        ModelCallAudit.build(**payload)  # type: ignore[arg-type]


def test_model_call_audit_rejects_caller_supplied_hash_drift() -> None:
    audit = ModelCallAudit.build(**_success_kwargs())  # type: ignore[arg-type]
    payload = audit.model_dump(mode="json") | {"audit_hash": "f" * 64}

    with pytest.raises(ValidationError, match="hash mismatch"):
        ModelCallAudit.model_validate(payload)


def test_model_call_audit_content_hash_excludes_observed_at() -> None:
    first = ModelCallAudit.build(**_success_kwargs())  # type: ignore[arg-type]
    second = ModelCallAudit.build(
        **(_success_kwargs() | {"observed_at": datetime(2026, 8, 10, tzinfo=UTC)})
    )  # type: ignore[arg-type]

    assert first.audit_hash == second.audit_hash


def test_provider_model_unavailable_cannot_report_token_usage() -> None:
    payload = _success_kwargs() | {
        "outcome": "provider_model_unavailable",
        "output_hash": None,
        "input_tokens": 1,
        "output_tokens": None,
        "error_code": "provider_model_unavailable",
    }

    with pytest.raises(ValidationError, match="unavailable"):
        ModelCallAudit.build(**payload)  # type: ignore[arg-type]


def test_model_call_audit_requires_sorted_unique_input_evidence_refs() -> None:
    payload = _success_kwargs() | {
        "input_evidence_refs": ("prior-failure:def", "dataset-manifest:abc")
    }

    with pytest.raises(ValidationError, match="sorted and unique"):
        ModelCallAudit.build(**payload)  # type: ignore[arg-type]
