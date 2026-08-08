from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import (
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
    read_creator_candidate_registry,
)
from .qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
    read_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from .walk_forward import read_walk_forward_aggregation


class PersistedQualificationBatchFailure(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    reason_code: str = Field(pattern=r"^[a-z0-9_]+$")


class PersistedQualificationBatchResult(DomainModel):
    batch_version: Literal[1] = 1
    selected_candidate_ids: tuple[str, ...] = ()
    unselected_candidate_ids: tuple[str, ...] = ()
    evaluated_candidate_ids: tuple[str, ...] = ()
    qualified_candidate_ids: tuple[str, ...] = ()
    rejected_candidate_ids: tuple[str, ...] = ()
    blocked_candidate_ids: tuple[str, ...] = ()
    failures: tuple[PersistedQualificationBatchFailure, ...] = ()
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_result_partitions(self) -> PersistedQualificationBatchResult:
        partitions = (
            self.selected_candidate_ids,
            self.unselected_candidate_ids,
            self.evaluated_candidate_ids,
            self.qualified_candidate_ids,
            self.rejected_candidate_ids,
            self.blocked_candidate_ids,
        )
        for identifiers in partitions:
            if identifiers != tuple(sorted(set(identifiers))):
                raise ValueError("batch candidate IDs must be sorted and unique")
        selected = set(self.selected_candidate_ids)
        evaluated = set(self.evaluated_candidate_ids)
        qualified = set(self.qualified_candidate_ids)
        rejected = set(self.rejected_candidate_ids)
        blocked = set(self.blocked_candidate_ids)
        unselected = set(self.unselected_candidate_ids)
        if selected != evaluated | blocked:
            raise ValueError("selected IDs must partition evaluated and blocked IDs")
        if evaluated != qualified | rejected or qualified & rejected:
            raise ValueError("evaluated IDs must partition qualified and rejected IDs")
        if selected & unselected:
            raise ValueError("selected and unselected IDs must be disjoint")
        if tuple(failure.candidate_id for failure in self.failures) != self.blocked_candidate_ids:
            raise ValueError("batch failures must match blocked candidate IDs")
        return self


def _resolve_batch_reference(root: Path, reference: str) -> Path:
    relative = PurePosixPath(reference)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts or "\\" in reference:
        raise DomainViolation("batch artifact reference must be a safe relative POSIX path")
    resolved_root = root.resolve()
    resolved = (root / Path(*relative.parts)).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise DomainViolation("batch artifact reference escapes its root")
    return resolved


def _candidate_failure_reason(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, FileNotFoundError):
        return "missing_candidate_artifact"
    if "hash mismatch" in message:
        return "candidate_artifact_hash_mismatch"
    if "registry binding" in message:
        return "candidate_registry_binding_mismatch"
    return "invalid_candidate_artifact"


def _aggregation_failure_reason(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, FileNotFoundError):
        return "missing_persisted_aggregation"
    if "hash mismatch" in message:
        return "aggregation_hash_mismatch"
    if "universe" in message:
        return "candidate_aggregation_binding_mismatch"
    if "immutable" in message:
        return "qualification_artifact_conflict"
    return "invalid_persisted_aggregation"


def run_persisted_qualification_batch(
    *,
    registry_path: Path,
    candidate_artifact_root: Path,
    aggregation_root: Path,
    qualification_root: Path,
    aggregation_refs: Mapping[str, str],
    policy: WalkForwardQualificationPolicy,
    evaluator_run_id: str,
    evaluator_version: str,
    evaluated_at: datetime,
    limit: int | None = None,
) -> PersistedQualificationBatchResult:
    """Qualify persisted testing candidates independently without promotion."""
    if limit is not None and limit < 1:
        raise DomainViolation("limit must be positive")

    registry = read_creator_candidate_registry(registry_path)
    testing_entries = tuple(entry for entry in registry.entries if entry.state == "testing")
    selected_entries = testing_entries if limit is None else testing_entries[:limit]
    unselected_entries = () if limit is None else testing_entries[limit:]

    evaluated: list[str] = []
    qualified: list[str] = []
    rejected: list[str] = []
    blocked: list[str] = []
    failures: list[PersistedQualificationBatchFailure] = []

    for entry in selected_entries:
        candidate_id = entry.candidate_id
        try:
            candidate_path = _resolve_batch_reference(candidate_artifact_root, entry.artifact_ref)
            candidate: CreatorCandidateArtifact = read_creator_candidate_artifact(candidate_path)
            if (
                candidate.candidate_id != entry.candidate_id
                or candidate.artifact_hash != entry.artifact_hash
                or candidate.bundle_hash != entry.bundle_hash
                or candidate.dataset_registry_hash != entry.dataset_registry_hash
            ):
                raise DomainViolation("candidate registry binding mismatch")
        except (DomainViolation, FileNotFoundError, ValidationError) as exc:
            blocked.append(candidate_id)
            failures.append(
                PersistedQualificationBatchFailure(
                    candidate_id=candidate_id,
                    reason_code=_candidate_failure_reason(exc),
                )
            )
            continue

        aggregation_reference = aggregation_refs.get(candidate_id)
        if aggregation_reference is None:
            blocked.append(candidate_id)
            failures.append(
                PersistedQualificationBatchFailure(
                    candidate_id=candidate_id,
                    reason_code="missing_persisted_aggregation",
                )
            )
            continue

        qualification_path = qualification_root / f"{candidate_id}.json"
        try:
            aggregation_path = _resolve_batch_reference(aggregation_root, aggregation_reference)
            persisted_aggregation = read_walk_forward_aggregation(aggregation_path)
            artifact = build_walk_forward_qualification_artifact(
                candidate=candidate,
                aggregation=persisted_aggregation.aggregation,
                policy=policy,
                evaluator_run_id=evaluator_run_id,
                evaluator_version=evaluator_version,
                evaluated_at=evaluated_at,
            )
            if qualification_path.exists():
                try:
                    read_creator_candidate_qualification_artifact(qualification_path)
                except (DomainViolation, FileNotFoundError, ValidationError) as exc:
                    raise DomainViolation("qualification artifact path is immutable") from exc
            persisted_artifact: CreatorCandidateQualificationArtifact = (
                write_creator_candidate_qualification_artifact(qualification_path, artifact)
            )
        except (DataQualityError, DomainViolation, FileNotFoundError, ValidationError) as exc:
            blocked.append(candidate_id)
            failures.append(
                PersistedQualificationBatchFailure(
                    candidate_id=candidate_id,
                    reason_code=_aggregation_failure_reason(exc),
                )
            )
            continue

        evaluated.append(candidate_id)
        if persisted_artifact.decision == "qualified":
            qualified.append(candidate_id)
        else:
            rejected.append(candidate_id)

    return PersistedQualificationBatchResult(
        selected_candidate_ids=tuple(entry.candidate_id for entry in selected_entries),
        unselected_candidate_ids=tuple(entry.candidate_id for entry in unselected_entries),
        evaluated_candidate_ids=tuple(evaluated),
        qualified_candidate_ids=tuple(qualified),
        rejected_candidate_ids=tuple(rejected),
        blocked_candidate_ids=tuple(blocked),
        failures=tuple(failures),
    )


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
    """Build and persist strict OOS evidence without mutating the candidate."""
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


__all__ = [
    "PersistedQualificationBatchFailure",
    "PersistedQualificationBatchResult",
    "qualify_persisted_candidate",
    "run_persisted_qualification_batch",
]
