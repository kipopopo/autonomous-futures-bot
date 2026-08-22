"""Persistence handoff for Creator qualification evidence."""

from __future__ import annotations

from pathlib import Path

from .creator_qualification import CreatorQualificationResult
from .qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    write_creator_candidate_qualification_artifact,
)


def persist_creator_qualification_result(
    result: CreatorQualificationResult, *, root: Path
) -> tuple[CreatorCandidateQualificationArtifact, ...]:
    """Persist only built qualification evidence; blocked candidates produce no file."""
    persisted: list[CreatorCandidateQualificationArtifact] = []
    for artifact in result.qualifications:
        path = root / f"{artifact.candidate_id}.json"
        persisted.append(write_creator_candidate_qualification_artifact(path, artifact))
    return tuple(persisted)


__all__ = ["persist_creator_qualification_result"]
