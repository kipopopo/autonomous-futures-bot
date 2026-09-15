"""Scalable, evidence-first orchestration for autonomous research.

The base coordinates untrusted learner/planner transports with the existing
bounded deterministic cycle. It persists every boundary as immutable evidence
and deliberately has no paper, testnet, or live execution handle.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from ..research.autonomy_contracts import (
    FailureLearner,
    FailureLearningArtifact,
    FailureLearningRequest,
    FailureMemoryEntry,
    ResearchPlan,
    ResearchPlanner,
    ResearchPlanRequest,
    build_failure_memory_entry,
    read_failure_learning_artifact,
    read_failure_memory_entry,
    read_research_plan,
    write_failure_learning_artifact,
    write_failure_memory_entry,
    write_research_plan,
)
from ..research.cached_evaluation import CachedEvaluationWindow
from ..research.cached_oos_walk_forward import CachedSimulator
from ..research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
    build_creator_qualification_failure_feedback,
)
from ..research.creator_generator import ProposalTransport
from ..research.learner_critic import CriticTransport
from ..research.qualification_artifacts import (
    WalkForwardQualificationPolicy,
    read_creator_candidate_qualification_artifact,
)
from .autonomous_cycle import (
    AutonomousCycleConfig,
    AutonomousCycleResult,
    execute_autonomous_cycle,
)


class AutonomousBaseConfig(DomainModel):
    """Fixed scope and resource bound for one offline base run."""

    base_run_id: str = Field(pattern=r"^base-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_root: Path
    max_cycles: int = Field(ge=1, le=5, strict=True)
    data_source: str = "cached_only"
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    exchange_access: bool = False

    @model_validator(mode="after")
    def safety_is_fixed(self) -> AutonomousBaseConfig:
        if (
            self.data_source,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
            self.exchange_access,
        ) != ("cached_only", "unpromoted", False, False, False):
            raise ValueError("autonomous base must remain offline and unpromoted")
        return self


class AutonomousBaseCycleRequest(DomainModel):
    """All typed context a bounded cycle runner may receive."""

    base_run_id: str = Field(pattern=r"^base-[a-z0-9][a-z0-9-]{0,63}$")
    sequence: int = Field(ge=1, strict=True)
    cycle_id: str = Field(pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    prior_feedback: CreatorQualificationFailureFeedback
    learning: FailureLearningArtifact
    plan: ResearchPlan
    forbidden_candidate_ids: tuple[str, ...] = ()
    artifact_root: Path
    now: datetime

    @field_validator("forbidden_candidate_ids")
    @classmethod
    def candidate_ids_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("forbidden candidate IDs must be non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("forbidden candidate IDs must be sorted and unique")
        return values

    @field_validator("now")
    @classmethod
    def now_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("base cycle now must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bindings_are_valid(self) -> AutonomousBaseCycleRequest:
        if self.prior_feedback.candidate_id not in self.forbidden_candidate_ids:
            raise ValueError("cycle request must forbid its prior candidate")
        if (
            self.learning.base_run_id != self.base_run_id
            or self.learning.symbol != self.plan.symbol
            or self.learning.cycle_index != self.sequence
        ):
            raise ValueError("learning binding does not match cycle request")
        if (
            self.plan.base_run_id != self.base_run_id
            or self.plan.cycle_id != self.cycle_id
            or self.plan.research_run_id != self.research_run_id
            or self.plan.cycle_index != self.sequence
        ):
            raise ValueError("research plan binding does not match cycle request")
        if self.plan.forbidden_candidate_ids != self.forbidden_candidate_ids:
            raise ValueError("research plan forbidden-candidate binding is invalid")
        if (
            self.plan.bundle_hash != self.prior_feedback.bundle_hash
            or self.plan.dataset_registry_hash != self.prior_feedback.dataset_registry_hash
        ):
            raise ValueError("research plan dataset binding is invalid")
        return self


class AutonomousBaseCycleExecution(DomainModel):
    """Cycle output accepted by the base; paper admission is impossible here."""

    result: AutonomousCycleResult
    next_feedback: CreatorQualificationFailureFeedback | None = None

    @model_validator(mode="after")
    def execution_is_offline_and_bound(self) -> AutonomousBaseCycleExecution:
        if (
            self.result.cycle_status == "completed_admitted"
            or self.result.admission_decision == "admitted"
        ):
            raise ValueError("offline autonomous base rejects admitted cycle output")
        if self.result.execution_authority:
            raise ValueError("offline autonomous base rejects execution authority")
        if self.next_feedback is not None:
            if self.result.qualification_decision != "rejected":
                raise ValueError("next feedback requires a rejected qualification")
            if (
                self.result.qualification_hash != self.next_feedback.qualification_hash
                or self.result.candidate_id != self.next_feedback.candidate_id
                or self.result.candidate_artifact_hash != self.next_feedback.candidate_artifact_hash
            ):
                raise ValueError("next feedback does not bind to cycle result")
        elif self.result.qualification_decision == "rejected":
            raise ValueError("rejected cycle must provide typed next feedback")
        return self


class AutonomousBaseCycleRecord(DomainModel):
    """Immutable checkpoint for one completed base cycle."""

    record_version: int = 1
    base_run_id: str = Field(pattern=r"^base-[a-z0-9][a-z0-9-]{0,63}$")
    sequence: int = Field(ge=1, strict=True)
    cycle_id: str = Field(pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learning_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    thesis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_memory_hashes: tuple[str, ...] = Field(min_length=1, max_length=8)
    result: AutonomousCycleResult
    next_feedback: CreatorQualificationFailureFeedback | None = None
    recorded_at: datetime
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("failure_memory_hashes")
    @classmethod
    def memory_hashes_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("cycle record failure memory hashes must be sorted and unique")
        return values

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("base cycle record recorded_at must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def record_bindings_are_valid(self) -> AutonomousBaseCycleRecord:
        if self.result.cycle_id != self.cycle_id or self.result.symbol != self.symbol:
            raise ValueError("cycle record result binding is invalid")
        if (
            self.result.cycle_status == "completed_admitted"
            or self.result.admission_decision == "admitted"
        ):
            raise ValueError("cycle record cannot contain admission")
        if self.next_feedback is not None:
            if self.result.qualification_decision != "rejected":
                raise ValueError("cycle record next feedback requires rejected qualification")
            if (
                self.result.qualification_hash != self.next_feedback.qualification_hash
                or self.result.candidate_id != self.next_feedback.candidate_id
            ):
                raise ValueError("cycle record feedback binding is invalid")
        elif self.result.qualification_decision == "rejected":
            raise ValueError("cycle record must preserve rejected qualification feedback")
        if (
            self.record_hash != "0" * 64
            and autonomous_base_cycle_record_content_hash(self) != self.record_hash
        ):
            raise ValueError("autonomous base cycle record hash mismatch")
        return self


class AutonomousBaseResult(DomainModel):
    """Immutable final outcome of a bounded offline base run."""

    base_version: int = 1
    base_run_id: str = Field(pattern=r"^base-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str = Field(pattern=r"^(completed|stopped|blocked)$")
    terminal_reason: str = Field(min_length=1, max_length=128)
    cycles_executed: int = Field(ge=0, le=5, strict=True)
    cycle_ids: tuple[str, ...] = ()
    cycle_hashes: tuple[str, ...] = ()
    learning_hashes: tuple[str, ...] = ()
    plan_hashes: tuple[str, ...] = ()
    thesis_hashes: tuple[str, ...] = ()
    failure_memory_entry_hashes: tuple[str, ...] = Field(min_length=1, max_length=8)
    data_source: str = "cached_only"
    promotion_state: str = "unpromoted"
    paper_activation: bool = False
    execution_authority: bool = False
    exchange_access: bool = False
    completed_at: datetime
    base_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("completed_at")
    @classmethod
    def completed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("autonomous base completed_at must be UTC")
        return value.astimezone(UTC)

    @field_validator(
        "cycle_ids",
        "cycle_hashes",
        "learning_hashes",
        "plan_hashes",
        "thesis_hashes",
        "failure_memory_entry_hashes",
    )
    @classmethod
    def hash_lists_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("autonomous base lineage lists must be unique")
        return values

    @model_validator(mode="after")
    def result_is_consistent(self) -> AutonomousBaseResult:
        if self.cycles_executed != len(self.cycle_ids):
            raise ValueError("cycle count does not match cycle IDs")
        if self.cycles_executed != len(self.cycle_hashes):
            raise ValueError("cycle count does not match cycle hashes")
        if len(self.learning_hashes) < self.cycles_executed:
            raise ValueError("learning lineage is shorter than cycle history")
        if len(self.plan_hashes) < self.cycles_executed:
            raise ValueError("plan lineage is shorter than cycle history")
        if self.cycles_executed != len(self.thesis_hashes):
            raise ValueError("cycle count does not match thesis hashes")
        if (
            self.data_source,
            self.promotion_state,
            self.paper_activation,
            self.execution_authority,
            self.exchange_access,
        ) != ("cached_only", "unpromoted", False, False, False):
            raise ValueError("autonomous base result safety state is invalid")
        if (
            self.base_hash != "0" * 64
            and autonomous_base_result_content_hash(self) != self.base_hash
        ):
            raise ValueError("autonomous base result hash mismatch")
        return self


BaseCycleRunner = Callable[[AutonomousBaseCycleRequest], AutonomousBaseCycleExecution]


def autonomous_base_cycle_record_content_hash(record: AutonomousBaseCycleRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"recorded_at", "record_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def autonomous_base_result_content_hash(result: AutonomousBaseResult) -> str:
    payload = result.model_dump(mode="json", exclude={"completed_at", "base_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_autonomous_base_cycle_record(
    *,
    base_run_id: str,
    sequence: int,
    symbol: str,
    bundle_hash: str,
    dataset_registry_hash: str,
    learning: FailureLearningArtifact,
    plan: ResearchPlan,
    failure_memory_hashes: tuple[str, ...],
    execution: AutonomousBaseCycleExecution,
    recorded_at: datetime,
) -> AutonomousBaseCycleRecord:
    provisional = AutonomousBaseCycleRecord.model_construct(
        record_version=1,
        base_run_id=base_run_id,
        sequence=sequence,
        cycle_id=execution.result.cycle_id,
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        learning_hash=learning.learning_hash,
        plan_hash=plan.plan_hash,
        thesis_hash=plan.thesis_hash,
        failure_memory_hashes=tuple(sorted(failure_memory_hashes)),
        result=execution.result,
        next_feedback=execution.next_feedback,
        recorded_at=recorded_at,
        record_hash="0" * 64,
    )
    record_hash = autonomous_base_cycle_record_content_hash(provisional)
    return AutonomousBaseCycleRecord.model_validate(
        {**provisional.model_dump(), "record_hash": record_hash}
    )


def build_autonomous_base_result(
    *,
    config: AutonomousBaseConfig,
    status: str,
    terminal_reason: str,
    records: Sequence[AutonomousBaseCycleRecord],
    failure_memory_entry_hashes: tuple[str, ...],
    completed_at: datetime,
    learning_hashes: Sequence[str] | None = None,
    plan_hashes: Sequence[str] | None = None,
) -> AutonomousBaseResult:
    ordered = tuple(sorted(records, key=lambda record: record.sequence))
    provisional = AutonomousBaseResult.model_construct(
        base_version=1,
        base_run_id=config.base_run_id,
        symbol=config.symbol,
        bundle_hash=config.bundle_hash,
        dataset_registry_hash=config.dataset_registry_hash,
        status=status,
        terminal_reason=terminal_reason,
        cycles_executed=len(ordered),
        cycle_ids=tuple(record.cycle_id for record in ordered),
        cycle_hashes=tuple(record.result.cycle_hash for record in ordered),
        learning_hashes=(
            tuple(learning_hashes)
            if learning_hashes is not None
            else tuple(record.learning_hash for record in ordered)
        ),
        plan_hashes=(
            tuple(plan_hashes)
            if plan_hashes is not None
            else tuple(record.plan_hash for record in ordered)
        ),
        thesis_hashes=tuple(record.thesis_hash for record in ordered),
        failure_memory_entry_hashes=failure_memory_entry_hashes,
        data_source="cached_only",
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        exchange_access=False,
        completed_at=completed_at,
        base_hash="0" * 64,
    )
    base_hash = autonomous_base_result_content_hash(provisional)
    return AutonomousBaseResult.model_validate({**provisional.model_dump(), "base_hash": base_hash})


def _write_once(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    try:
        os.link(temporary_path, path)
    except FileExistsError:
        pass
    finally:
        temporary_path.unlink(missing_ok=True)


def read_autonomous_base_cycle_record(path: Path) -> AutonomousBaseCycleRecord:
    try:
        record = AutonomousBaseCycleRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted autonomous base cycle record") from exc
    if autonomous_base_cycle_record_content_hash(record) != record.record_hash:
        raise DomainViolation(f"autonomous base cycle record hash mismatch: {path}")
    return record


def write_autonomous_base_cycle_record(
    path: Path, record: AutonomousBaseCycleRecord
) -> AutonomousBaseCycleRecord:
    if autonomous_base_cycle_record_content_hash(record) != record.record_hash:
        raise DomainViolation("autonomous base cycle record hash mismatch")
    if path.exists():
        existing = read_autonomous_base_cycle_record(path)
        if existing != record:
            raise DomainViolation(f"autonomous base cycle record path is immutable: {path}")
        return existing
    payload = json.dumps(record.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    _write_once(path, payload)
    readback = read_autonomous_base_cycle_record(path)
    if readback != record:
        raise DomainViolation(f"autonomous base cycle record path is immutable: {path}")
    return readback


def read_autonomous_base_result(path: Path) -> AutonomousBaseResult:
    try:
        result = AutonomousBaseResult.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted autonomous base result") from exc
    if autonomous_base_result_content_hash(result) != result.base_hash:
        raise DomainViolation(f"autonomous base result hash mismatch: {path}")
    return result


def write_autonomous_base_result(path: Path, result: AutonomousBaseResult) -> AutonomousBaseResult:
    if autonomous_base_result_content_hash(result) != result.base_hash:
        raise DomainViolation("autonomous base result hash mismatch")
    if path.exists():
        existing = read_autonomous_base_result(path)
        if existing != result:
            raise DomainViolation(f"autonomous base result path is immutable: {path}")
        return existing
    payload = json.dumps(result.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    _write_once(path, payload)
    readback = read_autonomous_base_result(path)
    if readback != result:
        raise DomainViolation(f"autonomous base result path is immutable: {path}")
    return readback


def _derived_id(prefix: str, base_run_id: str, sequence: int) -> str:
    digest = sha256(f"{base_run_id}:{sequence}".encode()).hexdigest()[:32]
    return f"{prefix}-{digest}"


class AutonomousResearchBase:
    """Run a finite, restart-safe offline learner/planner/research loop."""

    def __init__(
        self,
        *,
        config: AutonomousBaseConfig,
        learner: FailureLearner,
        planner: ResearchPlanner,
        cycle_runner: BaseCycleRunner,
    ) -> None:
        self.config = config
        self.learner = learner
        self.planner = planner
        self.cycle_runner = cycle_runner

    def _validate_initial_feedback(self, feedback: CreatorQualificationFailureFeedback) -> None:
        if (
            feedback.bundle_hash != self.config.bundle_hash
            or feedback.dataset_registry_hash != self.config.dataset_registry_hash
        ):
            raise DataQualityError("initial failure feedback does not match base scope")

    def _finalize(
        self,
        *,
        status: str,
        terminal_reason: str,
        records: Sequence[AutonomousBaseCycleRecord],
        memory_hashes: tuple[str, ...],
        completed_at: datetime,
        learning_hashes: Sequence[str] | None = None,
        plan_hashes: Sequence[str] | None = None,
    ) -> AutonomousBaseResult:
        result = build_autonomous_base_result(
            config=self.config,
            status=status,
            terminal_reason=terminal_reason,
            records=records,
            failure_memory_entry_hashes=memory_hashes,
            completed_at=completed_at,
            learning_hashes=learning_hashes,
            plan_hashes=plan_hashes,
        )
        return write_autonomous_base_result(self.config.artifact_root / "base-result.json", result)

    def _load_existing_records(
        self,
        *,
        initial_feedback: CreatorQualificationFailureFeedback,
        seed_memory: FailureMemoryEntry,
    ) -> tuple[
        list[AutonomousBaseCycleRecord],
        list[FailureMemoryEntry],
        CreatorQualificationFailureFeedback,
        set[str],
        list[str],
        list[str],
    ]:
        cycles_root = self.config.artifact_root / "cycles"
        paths = tuple(cycles_root.glob("cycle-*.json")) if cycles_root.exists() else ()
        records = sorted(
            (read_autonomous_base_cycle_record(path) for path in paths),
            key=lambda x: x.sequence,
        )
        if any(record.base_run_id != self.config.base_run_id for record in records):
            raise DomainViolation("autonomous base cycle record belongs to another base run")
        expected_sequences = tuple(range(1, len(records) + 1))
        if tuple(record.sequence for record in records) != expected_sequences:
            raise DomainViolation("autonomous base cycle checkpoints are not contiguous")
        if records and seed_memory.memory_hash not in records[0].failure_memory_hashes:
            raise DomainViolation("initial failure feedback does not match persisted base history")
        referenced_learning = {record.learning_hash for record in records}
        for path in (self.config.artifact_root / "learning").glob("learn-*.json"):
            artifact = read_failure_learning_artifact(path)
            if artifact.learning_hash not in referenced_learning:
                raise DomainViolation(
                    "uncheckpointed failure learning artifact requires reconciliation"
                )
        referenced_plans = {record.plan_hash for record in records}
        for path in (self.config.artifact_root / "plans").glob("plan-*.json"):
            plan = read_research_plan(path)
            if plan.plan_hash not in referenced_plans:
                raise DomainViolation("uncheckpointed research plan requires reconciliation")
        referenced_memories = {seed_memory.memory_hash}
        for record in records:
            referenced_memories.update(record.failure_memory_hashes)
        for path in (self.config.artifact_root / "failure-memory").glob("failure-*.json"):
            try:
                entry = read_failure_memory_entry(path)
            except Exception as exc:
                raise DomainViolation(
                    f"tampered or corrupted failure memory checkpoint: {path}"
                ) from exc
            if path.name != f"failure-{entry.memory_hash}.json":
                raise DomainViolation(f"tampered failure memory filename mismatch: {path.name}")
            if entry.base_run_id == self.config.base_run_id:
                if entry.memory_hash not in referenced_memories:
                    raise DomainViolation(
                        "uncheckpointed failure memory entry requires reconciliation"
                    )
        if not records:
            return [], [seed_memory], initial_feedback, {initial_feedback.candidate_id}, [], []
        memory_by_hash: dict[str, FailureMemoryEntry] = {seed_memory.memory_hash: seed_memory}
        for record in records:
            for memory_hash in record.failure_memory_hashes:
                path = self.config.artifact_root / "failure-memory" / f"failure-{memory_hash}.json"
                memory_by_hash[memory_hash] = read_failure_memory_entry(path)
        if any(
            entry.base_run_id != self.config.base_run_id
            or entry.bundle_hash != self.config.bundle_hash
            or entry.dataset_registry_hash != self.config.dataset_registry_hash
            for entry in memory_by_hash.values()
        ):
            raise DomainViolation("autonomous base failure memory scope is invalid")
        feedback = initial_feedback
        forbidden = {initial_feedback.candidate_id}
        for record in records:
            if record.result.candidate_id:
                forbidden.add(record.result.candidate_id)
            if record.next_feedback is not None:
                feedback = record.next_feedback
                forbidden.add(feedback.candidate_id)
        memory = [memory_by_hash[key] for key in sorted(memory_by_hash)]
        return (
            records,
            memory,
            feedback,
            forbidden,
            [record.learning_hash for record in records],
            [record.plan_hash for record in records],
        )

    def run(
        self,
        *,
        initial_feedback: CreatorQualificationFailureFeedback,
        now: datetime,
    ) -> AutonomousBaseResult:
        """Run or resume one finite base run without touching runtime execution."""
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise DataQualityError("base run now must be timezone-aware UTC")
        timestamp = now.astimezone(UTC)
        self._validate_initial_feedback(initial_feedback)
        result_path = self.config.artifact_root / "base-result.json"
        if result_path.exists():
            existing = read_autonomous_base_result(result_path)
            if (
                existing.base_run_id != self.config.base_run_id
                or existing.symbol != self.config.symbol
                or existing.bundle_hash != self.config.bundle_hash
                or existing.dataset_registry_hash != self.config.dataset_registry_hash
            ):
                raise DomainViolation("persisted autonomous base result scope mismatch")
            return existing

        failure_memory_root = self.config.artifact_root / "failure-memory"
        existing_seed: FailureMemoryEntry | None = None
        if failure_memory_root.exists():
            for path in sorted(failure_memory_root.glob("failure-*.json")):
                try:
                    candidate_entry = read_failure_memory_entry(path)
                except Exception as exc:
                    raise DomainViolation(
                        f"tampered or corrupted failure memory checkpoint: {path}"
                    ) from exc
                if (
                    candidate_entry.base_run_id == self.config.base_run_id
                    and candidate_entry.sequence == 0
                    and candidate_entry.source_type == "seed_feedback"
                ):
                    existing_seed = candidate_entry
                    break

        if existing_seed is not None:
            if (
                existing_seed.candidate_id != initial_feedback.candidate_id
                or existing_seed.candidate_artifact_hash != initial_feedback.candidate_artifact_hash
                or existing_seed.qualification_hash != initial_feedback.qualification_hash
                or existing_seed.qualification_policy_id != initial_feedback.qualification_policy_id
            ):
                raise DomainViolation(
                    "persisted seed failure memory does not match initial feedback"
                )
            seed_memory = existing_seed
        else:
            seed_memory = build_failure_memory_entry(
                base_run_id=self.config.base_run_id,
                source_type="seed_feedback",
                source_id=f"seed-{initial_feedback.qualification_hash[:32]}",
                sequence=0,
                feedback=initial_feedback,
                cycle_id=None,
                cycle_hash=None,
                recorded_at=timestamp,
            )
            seed_path = failure_memory_root / f"failure-{seed_memory.memory_hash}.json"
            seed_memory = write_failure_memory_entry(seed_path, seed_memory)

        records, memory, feedback, forbidden, learning_hashes, plan_hashes = (
            self._load_existing_records(
                initial_feedback=initial_feedback,
                seed_memory=seed_memory,
            )
        )
        memory_hashes = [entry.memory_hash for entry in memory]
        start_sequence = len(records) + 1

        if records:
            last = records[-1]
            if last.result.qualification_decision == "qualified":
                return self._finalize(
                    status="completed",
                    terminal_reason="qualified_unadmitted",
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                )
            if last.next_feedback is None:
                terminal = (
                    "cycle_failed" if last.result.cycle_status == "failed" else "cycle_stopped"
                )
                return self._finalize(
                    status="blocked" if last.result.cycle_status == "failed" else "stopped",
                    terminal_reason=terminal,
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                )
            if len(records) >= self.config.max_cycles:
                return self._finalize(
                    status="stopped",
                    terminal_reason="max_cycles_reached",
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                )

        for sequence in range(start_sequence, self.config.max_cycles + 1):
            ordered_memory = tuple(sorted(memory, key=lambda entry: entry.memory_hash))
            ordered_forbidden = tuple(sorted(forbidden))
            learning_request = FailureLearningRequest(
                research_run_id=_derived_id("run-learning", self.config.base_run_id, sequence),
                base_run_id=self.config.base_run_id,
                symbol=self.config.symbol,
                bundle_hash=self.config.bundle_hash,
                dataset_registry_hash=self.config.dataset_registry_hash,
                cycle_index=sequence,
                failure_memory=ordered_memory,
                forbidden_candidate_ids=ordered_forbidden,
                input_evidence_refs=tuple(
                    f"failure/{entry.memory_hash}" for entry in ordered_memory
                ),
            )
            learning_result = self.learner.learn(learning_request)
            if learning_result.decision != "accepted" or learning_result.artifact is None:
                return self._finalize(
                    status="blocked",
                    terminal_reason="learning_rejected",
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                )
            learning = write_failure_learning_artifact(
                self.config.artifact_root
                / "learning"
                / f"{learning_result.artifact.learning_id}.json",
                learning_result.artifact,
            )
            learning_hashes.append(learning.learning_hash)
            if learning.decision == "stop":
                return self._finalize(
                    status="stopped",
                    terminal_reason="learner_stopped",
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                    learning_hashes=learning_hashes,
                    plan_hashes=plan_hashes,
                )

            cycle_id = _derived_id("cycle", self.config.base_run_id, sequence)
            research_run_id = f"run-creator-{cycle_id}"
            plan_request = ResearchPlanRequest(
                research_run_id=research_run_id,
                base_run_id=self.config.base_run_id,
                cycle_id=cycle_id,
                symbol=self.config.symbol,
                bundle_hash=self.config.bundle_hash,
                dataset_registry_hash=self.config.dataset_registry_hash,
                cycle_index=sequence,
                failure_memory=ordered_memory,
                learning=learning,
                forbidden_candidate_ids=ordered_forbidden,
                prior_plan_hashes=tuple(sorted(plan_hashes)),
                prior_thesis_hashes=tuple(sorted(record.thesis_hash for record in records)),
                input_evidence_refs=tuple(
                    sorted(
                        [
                            *(f"failure/{entry.memory_hash}" for entry in ordered_memory),
                            f"learning/{learning.learning_hash}",
                        ]
                    )
                ),
            )
            plan_result = self.planner.plan(plan_request)
            if plan_result.decision != "accepted" or plan_result.plan is None:
                return self._finalize(
                    status="blocked",
                    terminal_reason="planning_rejected",
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                    learning_hashes=learning_hashes,
                    plan_hashes=plan_hashes,
                )
            plan = write_research_plan(
                self.config.artifact_root / "plans" / f"{plan_result.plan.plan_id}.json",
                plan_result.plan,
            )
            plan_hashes.append(plan.plan_hash)

            cycle_request = AutonomousBaseCycleRequest(
                base_run_id=self.config.base_run_id,
                sequence=sequence,
                cycle_id=cycle_id,
                research_run_id=research_run_id,
                prior_feedback=feedback,
                learning=learning,
                plan=plan,
                forbidden_candidate_ids=ordered_forbidden,
                artifact_root=self.config.artifact_root,
                now=timestamp,
            )
            execution = self.cycle_runner(cycle_request)
            if not isinstance(execution, AutonomousBaseCycleExecution):
                raise DataQualityError("cycle runner returned an invalid typed execution")
            if execution.result.cycle_id != cycle_id:
                raise DataQualityError("cycle runner returned an unexpected cycle ID")
            if execution.result.symbol != self.config.symbol:
                raise DataQualityError("cycle runner returned an unexpected symbol")

            if execution.next_feedback is not None:
                failure_entry = build_failure_memory_entry(
                    base_run_id=self.config.base_run_id,
                    source_type="cycle_result",
                    source_id=execution.result.cycle_id,
                    sequence=sequence,
                    feedback=execution.next_feedback,
                    cycle_id=execution.result.cycle_id,
                    cycle_hash=execution.result.cycle_hash,
                    recorded_at=timestamp,
                )
                failure_entry = write_failure_memory_entry(
                    self.config.artifact_root
                    / "failure-memory"
                    / f"failure-{failure_entry.memory_hash}.json",
                    failure_entry,
                )
                memory.append(failure_entry)
                memory_hashes.append(failure_entry.memory_hash)

            record = build_autonomous_base_cycle_record(
                base_run_id=self.config.base_run_id,
                sequence=sequence,
                symbol=self.config.symbol,
                bundle_hash=self.config.bundle_hash,
                dataset_registry_hash=self.config.dataset_registry_hash,
                learning=learning,
                plan=plan,
                failure_memory_hashes=tuple(sorted(memory_hashes)),
                execution=execution,
                recorded_at=timestamp,
            )
            record = write_autonomous_base_cycle_record(
                self.config.artifact_root / "cycles" / f"{record.cycle_id}.json", record
            )
            records.append(record)

            if execution.result.qualification_decision == "qualified":
                return self._finalize(
                    status="completed",
                    terminal_reason="qualified_unadmitted",
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                )
            if execution.next_feedback is None:
                return self._finalize(
                    status=("blocked" if execution.result.cycle_status == "failed" else "stopped"),
                    terminal_reason=(
                        "cycle_failed"
                        if execution.result.cycle_status == "failed"
                        else "cycle_stopped"
                    ),
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                )
            feedback = execution.next_feedback
            forbidden.add(feedback.candidate_id)
            if sequence == self.config.max_cycles:
                return self._finalize(
                    status="stopped",
                    terminal_reason="max_cycles_reached",
                    records=records,
                    memory_hashes=tuple(memory_hashes),
                    completed_at=timestamp,
                )

        return self._finalize(
            status="stopped",
            terminal_reason="max_cycles_reached",
            records=records,
            memory_hashes=tuple(memory_hashes),
            completed_at=timestamp,
        )


def make_autonomous_cycle_runner(
    *,
    windows: Sequence[CachedEvaluationWindow],
    qualification_policy: WalkForwardQualificationPolicy,
    critic_transport: CriticTransport,
    creator_transport: ProposalTransport,
    require_flat: bool = False,
    simulator: CachedSimulator | None = None,
) -> BaseCycleRunner:
    """Adapt the existing bounded cycle to the offline base without paper access."""

    def run_cycle(request: AutonomousBaseCycleRequest) -> AutonomousBaseCycleExecution:
        config = AutonomousCycleConfig(
            cycle_id=request.cycle_id,
            symbol=request.plan.symbol,
            bundle_hash=request.plan.bundle_hash,
            dataset_registry_hash=request.plan.dataset_registry_hash,
            qualification_policy=qualification_policy,
            artifact_root=request.artifact_root,
            max_attempts=1,
            require_flat=require_flat,
            forbidden_candidate_ids=request.forbidden_candidate_ids,
        )
        result = execute_autonomous_cycle(
            config=config,
            windows=windows,
            prior_feedback=request.prior_feedback,
            critic_transport=critic_transport,
            creator_transport=creator_transport,
            paper_engine=None,
            simulator=simulator,
            now=request.now,
            research_plan=request.plan,
            provider="demo",
            model="deterministic-heuristic",
        )
        next_feedback: CreatorQualificationFailureFeedback | None = None
        if result.qualification_decision == "rejected":
            if result.qualification_hash is None:
                raise DataQualityError("rejected cycle is missing qualification hash")
            qualification = read_creator_candidate_qualification_artifact(
                request.artifact_root / "qualifications" / f"{result.qualification_hash}.json"
            )
            next_feedback = build_creator_qualification_failure_feedback(qualification)
            if next_feedback is None:
                raise DataQualityError("rejected qualification did not produce failure feedback")
        return AutonomousBaseCycleExecution(result=result, next_feedback=next_feedback)

    return run_cycle


__all__ = [
    "AutonomousBaseConfig",
    "AutonomousBaseCycleExecution",
    "AutonomousBaseCycleRecord",
    "AutonomousBaseCycleRequest",
    "AutonomousBaseResult",
    "AutonomousResearchBase",
    "BaseCycleRunner",
    "autonomous_base_cycle_record_content_hash",
    "autonomous_base_result_content_hash",
    "build_autonomous_base_cycle_record",
    "build_autonomous_base_result",
    "make_autonomous_cycle_runner",
    "read_autonomous_base_cycle_record",
    "read_autonomous_base_result",
    "write_autonomous_base_cycle_record",
    "write_autonomous_base_result",
]
