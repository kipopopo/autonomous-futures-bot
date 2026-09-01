from __future__ import annotations

from collections.abc import Mapping

import pytest

from autonomous_futures.research.creator_failure_feedback import CreatorQualificationFailureFeedback
from autonomous_futures.research.learner_critic import (
    LearnerCritic,
    LearnerCriticRequest,
    LearnerCritique,
    learner_critic_schema_diagnostics,
)


def _feedback() -> CreatorQualificationFailureFeedback:
    return CreatorQualificationFailureFeedback.model_validate(
        {
            "candidate_id": "cand-critic-001",
            "candidate_artifact_hash": "a" * 64,
            "bundle_hash": "b" * 64,
            "dataset_registry_hash": "c" * 64,
            "qualification_hash": "d" * 64,
            "qualification_policy_id": "policy-creator-001",
            "failed_gates": [
                {
                    "gate_id": "oos_profit_factor_min",
                    "passed": False,
                    "observed": "0.5",
                    "threshold": "1",
                    "comparator": "gte",
                    "reason_code": "oos_profit_factor_below_threshold",
                }
            ],
            "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        }
    )


def _request() -> LearnerCriticRequest:
    feedback = _feedback()
    return LearnerCriticRequest(
        research_run_id="run-critic-001",
        candidate_id=feedback.candidate_id,
        candidate_artifact_hash=feedback.candidate_artifact_hash,
        feedback=feedback,
        input_evidence_refs=("feedback/hash", "qualification/hash"),
        output_schema_id="learner-critic-v1",
        attempt=1,
    )


def test_critic_accepts_valid_injected_review_without_authority() -> None:
    review = LearnerCritique(
        review_id="review-critic-001",
        research_run_id="run-critic-001",
        candidate_id="cand-critic-001",
        decision="revise",
        failure_reason_codes=("oos_profit_factor_below_threshold",),
        revision_actions=("change_entry_threshold",),
        review_hash="0" * 64,
    )

    result = LearnerCritic(transport=lambda _: review.model_dump()).review(_request())

    assert result.decision == "accepted"
    assert result.critique is not None
    assert result.critique.review_id == "review-critic-001"
    assert result.raw_output is None
    assert result.promotion_state == "unpromoted"
    assert result.execution_authority is False


def test_critic_rejects_binding_drift_and_schema_invalid_output() -> None:
    request = _request()

    def transport(_: LearnerCriticRequest) -> Mapping[str, object]:
        return {
            "review_id": "review-critic-001",
            "research_run_id": "run-other",
            "candidate_id": request.candidate_id,
            "decision": "revise",
            "failure_reason_codes": ["oos_profit_factor_below_threshold"],
            "revision_actions": ["change_entry_threshold"],
        }

    result = LearnerCritic(transport=transport).review(request)

    assert result.decision == "rejected"
    assert result.critique is None
    assert result.reason_codes == ("research_run_mismatch",)
    assert result.raw_output is None


def test_critic_request_rejects_feedback_candidate_binding_drift() -> None:
    feedback = _feedback()

    with pytest.raises(ValueError, match="binding mismatch"):
        LearnerCriticRequest(
            research_run_id="run-critic-001",
            candidate_id="cand-other",
            candidate_artifact_hash=feedback.candidate_artifact_hash,
            feedback=feedback,
            input_evidence_refs=("feedback/hash", "qualification/hash"),
            output_schema_id="learner-critic-v1",
            attempt=1,
        )


def test_critic_schema_diagnostics_expose_field_types_not_values() -> None:
    payload = {
        "review_id": "review-critic-001",
        "research_run_id": "run-critic-001",
        "candidate_id": "cand-critic-001",
        "decision": "revise",
        "failure_reason_codes": ["oos_profit_factor_below_threshold"],
    }

    diagnostics = learner_critic_schema_diagnostics(payload)

    assert diagnostics == ("revision_actions:missing",)
    assert "cand-critic-001" not in diagnostics


def test_critic_schema_diagnostics_name_noncanonical_action_list() -> None:
    payload = {
        "review_id": "review-critic-001",
        "research_run_id": "run-critic-001",
        "candidate_id": "cand-critic-001",
        "decision": "revise",
        "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        "revision_actions": ["change_entry_threshold", "change_entry_threshold"],
    }

    assert learner_critic_schema_diagnostics(payload) == (
        "revision_actions:critic_list_not_canonical",
    )


def test_critic_provider_failure_exposes_only_safe_metadata() -> None:
    class ProviderFailure(RuntimeError):
        code = "provider_payload_invalid"
        metadata = {
            "status_code": 200,
            "finish_reason": "length",
            "content_length": 0,
            "transport_error_type": "ReadTimeout",
            "secret": "must-not-leak",
        }

    result = LearnerCritic(transport=lambda _: (_ for _ in ()).throw(ProviderFailure())).review(
        _request()
    )

    assert result.reason_codes == ("provider_payload_invalid",)
    assert result.provider_metadata == {
        "content_length": 0,
        "finish_reason": "length",
        "status_code": 200,
        "transport_error_type": "ReadTimeout",
    }
    assert "secret" not in result.provider_metadata
