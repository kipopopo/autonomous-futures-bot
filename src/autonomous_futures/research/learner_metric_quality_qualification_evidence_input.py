from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact
from .learner_metric_quality_decision import LearnerMetricQualityPolicy
from .learner_metric_quality_qualification import (
    LearnerMetricQualityQualificationEvidence,
    LearnerMetricQualityQualificationPolicy,
    build_verified_learner_metric_quality_qualification_evidence,
    learner_metric_quality_qualification_policy_content_hash,
    read_learner_metric_quality_qualification_evidence,
)


def load_verified_learner_metric_quality_qualification_evidence(
    qualification_evidence_path: Path,
    decision_path: Path,
    review_path: Path,
    metric_evaluation_path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    source_policy: LearnerMetricQualityPolicy,
    qualification_policy: LearnerMetricQualityQualificationPolicy,
) -> LearnerMetricQualityQualificationEvidence:
    """Load persisted qualification evidence only after rebuilding its verified chain."""
    evidence = read_learner_metric_quality_qualification_evidence(qualification_evidence_path)
    if (
        evidence.qualification_policy_id != qualification_policy.policy_id
        or evidence.qualification_policy_hash
        != learner_metric_quality_qualification_policy_content_hash(qualification_policy)
    ):
        raise DomainViolation("metric quality qualification policy binding is invalid")

    expected = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_evaluation_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
        evaluated_at=evidence.evaluated_at,
    )
    if expected != evidence:
        raise DomainViolation("metric quality qualification evidence binding is invalid")
    return evidence


__all__ = ["load_verified_learner_metric_quality_qualification_evidence"]
