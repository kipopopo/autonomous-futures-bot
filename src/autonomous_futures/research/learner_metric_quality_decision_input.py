from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact
from .learner_metric_quality_decision import (
    LearnerMetricQualityDecisionEvidence,
    LearnerMetricQualityPolicy,
    build_learner_metric_quality_decision,
    learner_metric_quality_policy_content_hash,
    read_learner_metric_quality_decision,
)
from .learner_metric_quality_review_input import load_verified_learner_metric_quality_review


def load_verified_learner_metric_quality_decision(
    decision_path: Path,
    review_path: Path,
    metric_evaluation_path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    policy: LearnerMetricQualityPolicy,
) -> LearnerMetricQualityDecisionEvidence:
    """Load a persisted decision only after verifying its complete evidence chain."""
    review = load_verified_learner_metric_quality_review(
        review_path,
        metric_evaluation_path,
        learner=learner,
        candidate=candidate,
    )
    decision = read_learner_metric_quality_decision(decision_path)
    if (
        decision.policy_id != policy.policy_id
        or decision.policy_hash != learner_metric_quality_policy_content_hash(policy)
    ):
        raise DomainViolation("metric quality decision policy binding is invalid")

    expected = build_learner_metric_quality_decision(
        review,
        policy=policy,
        evaluated_at=decision.evaluated_at,
    )
    if expected != decision:
        raise DomainViolation("metric quality decision evidence binding is invalid")
    return decision


__all__ = ["load_verified_learner_metric_quality_decision"]
