from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .creator_artifacts import CreatorCandidateArtifact, read_creator_candidate_artifact
from .qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from .walk_forward import read_walk_forward_aggregation


def qualify_persisted_candidate(
    *,
    candidate_artifact_path: Path,
    aggregation_path: Path,
    qualification_artifact_path: Path,
    policy: WalkForwardQualificationPolicy,
    evaluator_run_id: str,
    evaluator_version: str,
    evaluated_at: datetime,
) -> CreatorCandidateQualificationArtifact:
    """Build and persist strict OOS evidence without mutating the candidate.

    All inputs are independently hash-verified at their persistence boundary.
    The only write performed by this flow is the immutable qualification
    artifact; candidate state and source evidence remain untouched.
    """
    candidate: CreatorCandidateArtifact = read_creator_candidate_artifact(candidate_artifact_path)
    persisted_aggregation = read_walk_forward_aggregation(aggregation_path)
    artifact = build_walk_forward_qualification_artifact(
        candidate=candidate,
        aggregation=persisted_aggregation.aggregation,
        policy=policy,
        evaluator_run_id=evaluator_run_id,
        evaluator_version=evaluator_version,
        evaluated_at=evaluated_at,
    )
    return write_creator_candidate_qualification_artifact(
        qualification_artifact_path,
        artifact,
    )


__all__ = ["qualify_persisted_candidate"]
