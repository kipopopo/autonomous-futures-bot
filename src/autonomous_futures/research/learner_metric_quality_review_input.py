from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact, verify_learner_artifact_binding
from .learner_metric_evaluation import LearnerMetricEvaluationRun
from .learner_metric_quality_review import (
    LearnerMetricQualityReviewEvidence,
    read_learner_metric_quality_review_evidence,
)
from .learner_metric_review_input import load_verified_learner_metric_review_input


def _verify_quality_review_binding(
    evidence: LearnerMetricQualityReviewEvidence,
    run: LearnerMetricEvaluationRun,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> None:
    try:
        verify_learner_artifact_binding(learner, candidate)
    except DomainViolation as exc:
        raise DomainViolation("learner metric quality review binding is invalid") from exc

    if (
        evidence.metric_evaluation_run_id != run.evaluation_run_id
        or evidence.metric_evaluation_hash != run.evaluation_hash
        or evidence.learner_id != learner.learner_id
        or evidence.learner_artifact_hash != learner.artifact_hash
        or evidence.candidate_id != candidate.candidate_id
        or evidence.candidate_artifact_hash != candidate.artifact_hash
        or evidence.bundle_hash != candidate.bundle_hash
        or evidence.dataset_registry_hash != candidate.dataset_registry_hash
        or evidence.learner_id != run.learner_id
        or evidence.learner_artifact_hash != run.learner_artifact_hash
        or evidence.candidate_id != run.candidate_id
        or evidence.candidate_artifact_hash != run.candidate_artifact_hash
        or evidence.bundle_hash != run.bundle_hash
        or evidence.dataset_registry_hash != run.dataset_registry_hash
    ):
        raise DomainViolation("learner metric quality review binding is invalid")

    if len(evidence.windows) != len(run.windows):
        raise DomainViolation("learner metric quality review window binding is invalid")
    for review_window, metric_window in zip(evidence.windows, run.windows, strict=True):
        if (
            review_window.window_id != metric_window.window_id
            or review_window.symbol != metric_window.symbol
            or metric_window.learner_id != learner.learner_id
            or metric_window.candidate_id != candidate.candidate_id
            or metric_window.symbol not in learner.symbols
        ):
            raise DomainViolation("learner metric quality review window binding is invalid")


def load_verified_learner_metric_quality_review(
    review_path: Path,
    metric_evaluation_path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> LearnerMetricQualityReviewEvidence:
    """Load persisted metric-quality evidence only after verifying its full chain."""
    run = load_verified_learner_metric_review_input(
        metric_evaluation_path,
        learner=learner,
        candidate=candidate,
    )
    evidence = read_learner_metric_quality_review_evidence(review_path)
    _verify_quality_review_binding(
        evidence,
        run,
        learner=learner,
        candidate=candidate,
    )
    return evidence


__all__ = ["load_verified_learner_metric_quality_review"]
