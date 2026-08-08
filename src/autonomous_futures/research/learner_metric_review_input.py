from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact, verify_learner_artifact_binding
from .learner_metric_evaluation import (
    LearnerMetricEvaluationRun,
    read_learner_metric_evaluation_run,
)

ReviewResult = TypeVar("ReviewResult")
LearnerMetricReviewCallback = Callable[[LearnerMetricEvaluationRun], ReviewResult]


def _verify_review_input_binding(
    run: LearnerMetricEvaluationRun,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> None:
    try:
        verify_learner_artifact_binding(learner, candidate)
    except DomainViolation as exc:
        raise DomainViolation("learner metric review input binding is invalid") from exc

    if (
        run.learner_id != learner.learner_id
        or run.learner_artifact_hash != learner.artifact_hash
        or run.candidate_id != candidate.candidate_id
        or run.candidate_artifact_hash != candidate.artifact_hash
        or run.bundle_hash != candidate.bundle_hash
        or run.dataset_registry_hash != candidate.dataset_registry_hash
    ):
        raise DomainViolation("learner metric review input binding is invalid")

    for window in run.windows:
        if (
            window.learner_id != learner.learner_id
            or window.candidate_id != candidate.candidate_id
            or window.symbol not in learner.symbols
        ):
            raise DomainViolation("learner metric review window binding is invalid")


def load_verified_learner_metric_review_input(
    path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> LearnerMetricEvaluationRun:
    """Load one persisted metric run only after verifying its review binding."""
    run = read_learner_metric_evaluation_run(path)
    _verify_review_input_binding(run, learner=learner, candidate=candidate)
    return run


def review_persisted_learner_metric_evaluation(  # noqa: UP047
    path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    reviewer: LearnerMetricReviewCallback[ReviewResult],
) -> ReviewResult:
    """Pass verified metric evidence to an explicit caller-supplied reviewer."""
    run = load_verified_learner_metric_review_input(
        path,
        learner=learner,
        candidate=candidate,
    )
    return reviewer(run.model_copy(deep=True))


__all__ = [
    "LearnerMetricReviewCallback",
    "load_verified_learner_metric_review_input",
    "review_persisted_learner_metric_evaluation",
]
