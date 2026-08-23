from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_failure_feedback import CreatorQualificationFailureFeedback
from autonomous_futures.research.learner_critic import LearnerCriticRequest, parse_learner_critique
from autonomous_futures.research.learner_critic_evidence import (
    build_learner_critique_evidence,
    persist_learner_critique_evidence,
    read_learner_critique_evidence,
)

CREATED_AT = datetime(2026, 8, 23, tzinfo=UTC)


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


def _critique():
    return parse_learner_critique(
        {
            "review_id": "review-critic-001",
            "research_run_id": "run-critic-001",
            "candidate_id": "cand-critic-001",
            "decision": "revise",
            "failure_reason_codes": ["oos_profit_factor_below_threshold"],
            "revision_actions": ["change_entry_threshold"],
        }
    )


def test_builds_and_persists_bound_critique_evidence(tmp_path: Path) -> None:
    evidence = build_learner_critique_evidence(
        request=_request(),
        critique=_critique(),
        evidence_id="critic-evidence-001",
        created_at=CREATED_AT,
    )

    persisted = persist_learner_critique_evidence(tmp_path / "critique.json", evidence)

    assert persisted == evidence
    assert read_learner_critique_evidence(tmp_path / "critique.json") == evidence
    assert evidence.critique_decision == "revise"
    assert evidence.promotion_state == "unpromoted"
    assert evidence.execution_authority is False


def test_identical_evidence_is_idempotent_and_conflict_is_rejected(tmp_path: Path) -> None:
    first = build_learner_critique_evidence(
        request=_request(),
        critique=_critique(),
        evidence_id="critic-evidence-001",
        created_at=CREATED_AT,
    )
    second = build_learner_critique_evidence(
        request=_request(),
        critique=_critique(),
        evidence_id="critic-evidence-001",
        created_at=CREATED_AT,
    )
    persist_learner_critique_evidence(tmp_path / "critique.json", first)
    assert persist_learner_critique_evidence(tmp_path / "critique.json", second) == first

    conflict = build_learner_critique_evidence(
        request=_request(),
        critique=parse_learner_critique(
            {
                "review_id": "review-critic-001",
                "research_run_id": "run-critic-001",
                "candidate_id": "cand-critic-001",
                "decision": "revise",
                "failure_reason_codes": ["oos_profit_factor_below_threshold"],
                "revision_actions": ["change_exit_threshold"],
            }
        ),
        evidence_id="critic-evidence-001",
        created_at=CREATED_AT,
    )
    with pytest.raises(DomainViolation, match="immutable"):
        persist_learner_critique_evidence(tmp_path / "critique.json", conflict)


def test_feedback_binding_drift_is_rejected_before_persistence() -> None:
    with pytest.raises(DataQualityError, match="candidate binding"):
        bad_request = _request().model_copy(update={"candidate_id": "cand-other"})
        build_learner_critique_evidence(
            request=bad_request,
            critique=_critique(),
            evidence_id="critic-evidence-001",
            created_at=CREATED_AT,
        )
