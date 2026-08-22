"""Explicit learner-training bridge for Creator qualification failure feedback."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..data.parquet import DataQualityError
from .creator_artifacts import CreatorCandidateArtifact
from .creator_failure_feedback import CreatorQualificationFailureFeedback
from .learner_artifacts import LearnerArtifact
from .learner_inputs import LearnerInputWindow
from .learner_runs import LearnerRun
from .learner_training import LearnerTrainingOutput
from .learner_training_evidence import LearnerTrainingEvidence
from .learner_training_pipeline import execute_learner_training_with_evidence

CreatorFeedbackTrainer = Callable[
    [CreatorQualificationFailureFeedback, LearnerRun, dict[str, pd.DataFrame]],
    LearnerTrainingOutput,
]


def execute_creator_feedback_training_with_evidence(
    *,
    feedback: CreatorQualificationFailureFeedback,
    prepared_run: LearnerRun,
    source_learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    windows: Sequence[LearnerInputWindow],
    trainer: CreatorFeedbackTrainer,
    run_root: Path,
    prepared_run_ref: str,
    artifact_root: Path,
    source_learner_artifact_ref: str,
    output_artifact_ref: str,
    model_root: Path,
    evidence_root: Path,
    evidence_ref: str,
    artifact_created_at: datetime,
    evidence_created_at: datetime,
) -> LearnerTrainingEvidence:
    """Run one explicit feedback-aware trainer through existing evidence persistence."""
    if (
        feedback.candidate_id != candidate.candidate_id
        or feedback.candidate_artifact_hash != candidate.artifact_hash
        or feedback.bundle_hash != candidate.bundle_hash
        or feedback.dataset_registry_hash != candidate.dataset_registry_hash
    ):
        raise DataQualityError("feedback candidate binding is invalid")

    def bound_trainer(run: LearnerRun, frames: dict[str, pd.DataFrame]) -> LearnerTrainingOutput:
        return trainer(feedback, run, frames)

    return execute_learner_training_with_evidence(
        prepared_run=prepared_run,
        source_learner=source_learner,
        candidate=candidate,
        windows=windows,
        trainer=bound_trainer,
        run_root=run_root,
        prepared_run_ref=prepared_run_ref,
        artifact_root=artifact_root,
        source_learner_artifact_ref=source_learner_artifact_ref,
        output_artifact_ref=output_artifact_ref,
        model_root=model_root,
        evidence_root=evidence_root,
        evidence_ref=evidence_ref,
        artifact_created_at=artifact_created_at,
        evidence_created_at=evidence_created_at,
    )


__all__ = [
    "CreatorFeedbackTrainer",
    "execute_creator_feedback_training_with_evidence",
]
