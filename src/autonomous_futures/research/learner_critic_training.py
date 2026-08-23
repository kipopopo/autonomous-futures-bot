"""Feed persisted Learner/Critic evidence into injected learner training."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..data.parquet import DataQualityError
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact
from .learner_critic_evidence import LearnerCritiqueEvidence
from .learner_inputs import LearnerInputWindow
from .learner_runs import LearnerRun
from .learner_training import LearnerTrainingOutput
from .learner_training_evidence import LearnerTrainingEvidence
from .learner_training_pipeline import execute_learner_training_with_evidence

LearnerCriticTrainer = Callable[
    [LearnerCritiqueEvidence, LearnerRun, dict[str, pd.DataFrame]],
    LearnerTrainingOutput,
]


def execute_learner_critic_training_with_evidence(
    *,
    evidence: LearnerCritiqueEvidence,
    prepared_run: LearnerRun,
    source_learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    windows: Sequence[LearnerInputWindow],
    trainer: LearnerCriticTrainer,
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
    """Run one explicit Critic-evidence trainer through existing persistence."""
    if (
        evidence.candidate_id != candidate.candidate_id
        or evidence.candidate_artifact_hash != candidate.artifact_hash
        or evidence.bundle_hash != candidate.bundle_hash
        or evidence.dataset_registry_hash != candidate.dataset_registry_hash
    ):
        raise DataQualityError("critic evidence candidate binding is invalid")

    def bound_trainer(run: LearnerRun, frames: dict[str, pd.DataFrame]) -> LearnerTrainingOutput:
        return trainer(evidence, run, frames)

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
    "LearnerCriticTrainer",
    "execute_learner_critic_training_with_evidence",
]
