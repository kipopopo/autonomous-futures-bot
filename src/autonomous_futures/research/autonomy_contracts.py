"""Typed contracts for the evidence-first autonomous research base.

These contracts keep embedded AI untrusted and make failure history, learning
outputs, and next-experiment plans immutable evidence rather than authority.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_failure_feedback import CreatorQualificationFailureFeedback
from .qualification_artifacts import QualificationGateResult

Hash64 = str
StrategyFamily = Literal[
    "regime_gated_breakout",
    "range_mean_reversion",
    "donchian_channel_breakout",
    "volatility_compression_breakout",
    "volume_confirmed_momentum",
    "experimental",
]
NoveltyDimension = Literal[
    "entry_logic",
    "exit_logic",
    "feature_set",
    "regime_filter",
    "risk_design",
    "strategy_family",
]

_HASH_PATTERN = r"^[0-9a-f]{64}$"
_BASE_ID_PATTERN = r"^base-[a-z0-9][a-z0-9-]{0,63}$"
_RUN_ID_PATTERN = r"^run-[a-z0-9][a-z0-9-]{0,63}$"


class FailureMemoryEntry(DomainModel):
    """One immutable, non-authoritative failure observation."""

    memory_version: Literal[1] = 1
    entry_id: str = Field(pattern=r"^failure-[0-9a-f]{64}$")
    base_run_id: str = Field(pattern=_BASE_ID_PATTERN)
    source_type: Literal["seed_feedback", "cycle_result"]
    source_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    sequence: int = Field(ge=0, strict=True)
    cycle_id: str | None = Field(default=None, pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    cycle_hash: str | None = Field(default=None, pattern=_HASH_PATTERN)
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=_HASH_PATTERN)
    qualification_hash: str = Field(pattern=_HASH_PATTERN)
    qualification_policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    bundle_hash: str = Field(pattern=_HASH_PATTERN)
    dataset_registry_hash: str = Field(pattern=_HASH_PATTERN)
    failed_gates: tuple[QualificationGateResult, ...] = Field(min_length=1)
    failure_reason_codes: tuple[str, ...] = Field(min_length=1)
    source_hashes: tuple[str, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    recorded_at: datetime
    memory_hash: str = Field(pattern=_HASH_PATTERN)

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("failure memory recorded_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("failed_gates")
    @classmethod
    def gates_are_canonical(
        cls, values: tuple[QualificationGateResult, ...]
    ) -> tuple[QualificationGateResult, ...]:
        gate_ids = tuple(gate.gate_id for gate in values)
        if gate_ids != tuple(sorted(set(gate_ids))):
            raise ValueError("failure memory gates must be sorted and unique")
        if any(gate.passed for gate in values):
            raise ValueError("failure memory may contain failed gates only")
        return values

    @field_validator("failure_reason_codes", "source_hashes")
    @classmethod
    def lists_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("failure memory lists must contain non-empty values")
        if values != tuple(sorted(set(values))):
            raise ValueError("failure memory lists must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_source_and_hash(self) -> FailureMemoryEntry:
        if self.source_type == "seed_feedback":
            if self.sequence != 0 or self.cycle_id is not None or self.cycle_hash is not None:
                raise ValueError("seed failure memory entry has invalid cycle binding")
        else:
            if self.sequence < 1 or self.cycle_id is None or self.cycle_hash is None:
                raise ValueError("cycle failure memory entry requires cycle binding")
        if self.memory_hash != "0" * 64 and failure_memory_content_hash(self) != self.memory_hash:
            raise ValueError("failure memory hash mismatch")
        if self.entry_id != f"failure-{self.memory_hash}" and self.memory_hash != "0" * 64:
            raise ValueError("failure memory entry ID must be hash-derived")
        return self


class FailureLearningRequest(DomainModel):
    """Bounded input context for an embedded failure-learning call."""

    research_run_id: str = Field(pattern=_RUN_ID_PATTERN)
    base_run_id: str = Field(pattern=_BASE_ID_PATTERN)
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=_HASH_PATTERN)
    dataset_registry_hash: str = Field(pattern=_HASH_PATTERN)
    cycle_index: int = Field(ge=1, strict=True)
    failure_memory: tuple[FailureMemoryEntry, ...] = Field(min_length=1, max_length=8)
    forbidden_candidate_ids: tuple[str, ...] = ()
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    output_schema_id: Literal["failure-learning-v1"] = "failure-learning-v1"
    attempt: Literal[1] = 1

    @field_validator("failure_memory")
    @classmethod
    def failure_memory_is_canonical(
        cls, values: tuple[FailureMemoryEntry, ...]
    ) -> tuple[FailureMemoryEntry, ...]:
        ids = tuple(item.memory_hash for item in values)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("failure memory must be sorted and unique")
        return values

    @field_validator("forbidden_candidate_ids", "input_evidence_refs")
    @classmethod
    def refs_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("failure learning references must be non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("failure learning references must be sorted and unique")
        return values

    @model_validator(mode="after")
    def memory_scope_matches(self) -> FailureLearningRequest:
        for entry in self.failure_memory:
            if (
                entry.base_run_id != self.base_run_id
                or entry.bundle_hash != self.bundle_hash
                or entry.dataset_registry_hash != self.dataset_registry_hash
            ):
                raise ValueError("failure memory scope does not match learning request")
        if any(
            entry.candidate_id not in self.forbidden_candidate_ids for entry in self.failure_memory
        ):
            raise ValueError("learning request must forbid every historical candidate")
        return self


class FailureLearningArtifact(DomainModel):
    """Immutable learned constraints derived from the complete failure memory."""

    learning_version: Literal[1] = 1
    learning_id: str = Field(pattern=r"^learn-[0-9a-f]{64}$")
    research_run_id: str = Field(pattern=_RUN_ID_PATTERN)
    base_run_id: str = Field(pattern=_BASE_ID_PATTERN)
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    cycle_index: int = Field(ge=1, strict=True)
    source_failure_hashes: tuple[str, ...] = Field(min_length=1, max_length=8)
    failure_patterns: tuple[str, ...] = Field(min_length=1, max_length=8)
    learned_constraints: tuple[str, ...] = Field(min_length=1, max_length=16)
    recommended_novelty_dimensions: tuple[NoveltyDimension, ...] = Field(min_length=1)
    decision: Literal["accepted", "stop"] = "accepted"
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    learning_hash: str = Field(pattern=_HASH_PATTERN)

    @field_validator(
        "source_failure_hashes",
        "failure_patterns",
        "learned_constraints",
        "recommended_novelty_dimensions",
    )
    @classmethod
    def lists_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("learning lists must contain non-empty values")
        if values != tuple(sorted(set(values))):
            raise ValueError("learning lists must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_hash(self) -> FailureLearningArtifact:
        if (
            self.learning_hash != "0" * 64
            and failure_learning_content_hash(self) != self.learning_hash
        ):
            raise ValueError("failure learning hash mismatch")
        if self.learning_id != f"learn-{self.learning_hash}" and self.learning_hash != "0" * 64:
            raise ValueError("failure learning ID must be hash-derived")
        return self


class FailureLearningResult(DomainModel):
    """Sanitized result of one untrusted learner transport call."""

    decision: Literal["accepted", "rejected"]
    artifact: FailureLearningArtifact | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)
    schema_diagnostics: tuple[str, ...] = ()
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    raw_output: None = None
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("reason_codes", "schema_diagnostics")
    @classmethod
    def result_lists_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(not value for value in values):
            raise ValueError("learning result lists must be sorted and unique")
        return values

    @model_validator(mode="after")
    def decision_matches_artifact(self) -> FailureLearningResult:
        if (self.decision == "accepted") != (self.artifact is not None):
            raise ValueError("learning result decision does not match artifact")
        return self


class ResearchPlanRequest(DomainModel):
    """Complete evidence context supplied to the next-experiment planner."""

    research_run_id: str = Field(pattern=_RUN_ID_PATTERN)
    base_run_id: str = Field(pattern=_BASE_ID_PATTERN)
    cycle_id: str = Field(pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=_HASH_PATTERN)
    dataset_registry_hash: str = Field(pattern=_HASH_PATTERN)
    cycle_index: int = Field(ge=1, strict=True)
    failure_memory: tuple[FailureMemoryEntry, ...] = Field(min_length=1, max_length=8)
    learning: FailureLearningArtifact
    forbidden_candidate_ids: tuple[str, ...] = ()
    prior_plan_hashes: tuple[str, ...] = ()
    prior_thesis_hashes: tuple[str, ...] = ()
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    output_schema_id: Literal["research-plan-v1"] = "research-plan-v1"
    attempt: Literal[1] = 1

    @field_validator("failure_memory")
    @classmethod
    def request_memory_is_canonical(
        cls, values: tuple[FailureMemoryEntry, ...]
    ) -> tuple[FailureMemoryEntry, ...]:
        hashes = tuple(item.memory_hash for item in values)
        if hashes != tuple(sorted(set(hashes))):
            raise ValueError("research plan failure memory must be sorted and unique")
        return values

    @field_validator(
        "forbidden_candidate_ids",
        "prior_plan_hashes",
        "prior_thesis_hashes",
        "input_evidence_refs",
    )
    @classmethod
    def request_lists_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("research plan lists must contain non-empty values")
        if values != tuple(sorted(set(values))):
            raise ValueError("research plan lists must be sorted and unique")
        return values

    @model_validator(mode="after")
    def request_bindings_are_valid(self) -> ResearchPlanRequest:
        if (
            self.learning.base_run_id != self.base_run_id
            or self.learning.symbol != self.symbol
            or self.learning.cycle_index != self.cycle_index
        ):
            raise ValueError("learning artifact does not match plan request")
        memory_hashes = tuple(item.memory_hash for item in self.failure_memory)
        if self.learning.source_failure_hashes != memory_hashes:
            raise ValueError("learning artifact must consume complete failure memory")
        if any(
            entry.candidate_id not in self.forbidden_candidate_ids for entry in self.failure_memory
        ):
            raise ValueError("plan request must forbid every historical candidate")
        return self


class ResearchPlan(DomainModel):
    """Immutable, falsifiable next-experiment plan; never a promotion decision."""

    plan_version: Literal[1] = 1
    plan_id: str = Field(pattern=r"^plan-[0-9a-f]{64}$")
    research_run_id: str = Field(pattern=_RUN_ID_PATTERN)
    base_run_id: str = Field(pattern=_BASE_ID_PATTERN)
    cycle_id: str = Field(pattern=r"^cycle-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    cycle_index: int = Field(ge=1, strict=True)
    bundle_hash: str = Field(pattern=_HASH_PATTERN)
    dataset_registry_hash: str = Field(pattern=_HASH_PATTERN)
    source_failure_hashes: tuple[str, ...] = Field(min_length=1, max_length=8)
    learning_hash: str = Field(pattern=_HASH_PATTERN)
    forbidden_candidate_ids: tuple[str, ...] = ()
    hypothesis: str = Field(min_length=1, max_length=2000)
    expected_regime: str = Field(min_length=1, max_length=128)
    strategy_family: StrategyFamily
    novelty_dimensions: tuple[NoveltyDimension, ...] = Field(min_length=1)
    falsification_criteria: tuple[str, ...] = Field(min_length=1, max_length=8)
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    thesis_hash: str = Field(pattern=_HASH_PATTERN)
    plan_hash: str = Field(pattern=_HASH_PATTERN)

    @field_validator(
        "source_failure_hashes",
        "forbidden_candidate_ids",
        "novelty_dimensions",
        "falsification_criteria",
        "input_evidence_refs",
    )
    @classmethod
    def plan_lists_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("research plan lists must contain non-empty values")
        if values != tuple(sorted(set(values))):
            raise ValueError("research plan lists must be sorted and unique")
        return values

    @model_validator(mode="after")
    def plan_hash_is_valid(self) -> ResearchPlan:
        if self.thesis_hash != "0" * 64 and research_plan_thesis_hash(self) != self.thesis_hash:
            raise ValueError("research plan thesis hash mismatch")
        if self.plan_hash != "0" * 64 and research_plan_content_hash(self) != self.plan_hash:
            raise ValueError("research plan hash mismatch")
        if self.plan_id != f"plan-{self.plan_hash}" and self.plan_hash != "0" * 64:
            raise ValueError("research plan ID must be hash-derived")
        return self


class ResearchPlanResult(DomainModel):
    """Sanitized result of one untrusted planner transport call."""

    decision: Literal["accepted", "rejected"]
    plan: ResearchPlan | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)
    schema_diagnostics: tuple[str, ...] = ()
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    raw_output: None = None
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("reason_codes", "schema_diagnostics")
    @classmethod
    def plan_result_lists_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(not value for value in values):
            raise ValueError("plan result lists must be sorted and unique")
        return values

    @model_validator(mode="after")
    def decision_matches_plan(self) -> ResearchPlanResult:
        if (self.decision == "accepted") != (self.plan is not None):
            raise ValueError("plan result decision does not match plan")
        return self


def failure_memory_content_hash(entry: FailureMemoryEntry) -> str:
    payload = entry.model_dump(mode="json", exclude={"entry_id", "memory_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_failure_memory_entry(
    *,
    base_run_id: str,
    source_type: Literal["seed_feedback", "cycle_result"],
    source_id: str,
    sequence: int,
    feedback: CreatorQualificationFailureFeedback,
    cycle_id: str | None,
    cycle_hash: str | None,
    recorded_at: datetime,
) -> FailureMemoryEntry:
    source_hashes = {feedback.qualification_hash}
    if cycle_hash is not None:
        source_hashes.add(cycle_hash)
    provisional = FailureMemoryEntry.model_construct(
        memory_version=1,
        entry_id="failure-" + "0" * 64,
        base_run_id=base_run_id,
        source_type=source_type,
        source_id=source_id,
        sequence=sequence,
        cycle_id=cycle_id,
        cycle_hash=cycle_hash,
        candidate_id=feedback.candidate_id,
        candidate_artifact_hash=feedback.candidate_artifact_hash,
        qualification_hash=feedback.qualification_hash,
        qualification_policy_id=feedback.qualification_policy_id,
        bundle_hash=feedback.bundle_hash,
        dataset_registry_hash=feedback.dataset_registry_hash,
        failed_gates=feedback.failed_gates,
        failure_reason_codes=feedback.failure_reason_codes,
        source_hashes=tuple(sorted(source_hashes)),
        data_source="cached_only",
        exchange_access=False,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        recorded_at=recorded_at,
        memory_hash="0" * 64,
    )
    memory_hash = failure_memory_content_hash(provisional)
    return FailureMemoryEntry.model_validate(
        {
            **provisional.model_dump(),
            "entry_id": f"failure-{memory_hash}",
            "memory_hash": memory_hash,
        }
    )


def failure_learning_content_hash(artifact: FailureLearningArtifact) -> str:
    payload = artifact.model_dump(mode="json", exclude={"learning_id", "learning_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


class _SchemaContractError(DataQualityError):
    """Internal schema failure with redacted, typed diagnostics only."""

    diagnostics: tuple[str, ...]

    def __init__(self, diagnostics: tuple[str, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("schema contract rejected")


def _safe_schema_diagnostics(
    error: ValidationError, *, allowed_fields: frozenset[str]
) -> tuple[str, ...]:
    diagnostics: set[str] = set()
    for detail in error.errors():
        location = detail.get("loc", ())
        if not isinstance(location, tuple):
            continue
        if location and (not isinstance(location[0], str) or location[0] not in allowed_fields):
            continue
        path_parts = []
        for part in location:
            if isinstance(part, str) and part in allowed_fields:
                path_parts.append(part)
            elif isinstance(part, int) and 0 <= part <= 1024:
                path_parts.append(str(part))
            else:
                path_parts.append("unknown")
        path = ".".join(path_parts) or "__root__"
        error_type = detail.get("type")
        if not isinstance(error_type, str) or not error_type:
            error_type = "validation_error"
        diagnostics.add(f"{path}:{error_type[:64]}")
    return tuple(sorted(diagnostics)) or ("__root__:validation_error",)


def parse_failure_learning(
    payload: Mapping[str, object], request: FailureLearningRequest
) -> FailureLearningArtifact:
    data = {
        **payload,
        "learning_version": 1,
        "learning_id": "learn-" + "0" * 64,
        "research_run_id": request.research_run_id,
        "base_run_id": request.base_run_id,
        "symbol": request.symbol,
        "cycle_index": request.cycle_index,
        "source_failure_hashes": tuple(item.memory_hash for item in request.failure_memory),
        "data_source": "cached_only",
        "exchange_access": False,
        "promotion_state": "unpromoted",
        "paper_activation": False,
        "execution_authority": False,
        "learning_hash": "0" * 64,
    }
    try:
        validated = FailureLearningArtifact.model_validate(data)
    except ValidationError as exc:
        raise _SchemaContractError(
            _safe_schema_diagnostics(
                exc,
                allowed_fields=frozenset(
                    {
                        "decision",
                        "failure_patterns",
                        "learned_constraints",
                        "recommended_novelty_dimensions",
                    }
                ),
            )
        ) from None
    except TypeError:
        raise _SchemaContractError(("__root__:type_error",)) from None
    learning_hash = failure_learning_content_hash(validated)
    return FailureLearningArtifact.model_validate(
        {
            **validated.model_dump(),
            "learning_id": f"learn-{learning_hash}",
            "learning_hash": learning_hash,
        }
    )


def research_plan_content_hash(plan: ResearchPlan) -> str:
    payload = plan.model_dump(mode="json", exclude={"plan_id", "plan_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def research_plan_thesis_hash(plan: ResearchPlan) -> str:
    payload = {
        "expected_regime": plan.expected_regime,
        "hypothesis": plan.hypothesis,
        "novelty_dimensions": plan.novelty_dimensions,
        "strategy_family": plan.strategy_family,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def parse_research_plan(
    payload: Mapping[str, object], request: ResearchPlanRequest
) -> ResearchPlan:
    data = {
        **payload,
        "plan_version": 1,
        "plan_id": "plan-" + "0" * 64,
        "research_run_id": request.research_run_id,
        "base_run_id": request.base_run_id,
        "cycle_id": request.cycle_id,
        "symbol": request.symbol,
        "cycle_index": request.cycle_index,
        "bundle_hash": request.bundle_hash,
        "dataset_registry_hash": request.dataset_registry_hash,
        "source_failure_hashes": tuple(item.memory_hash for item in request.failure_memory),
        "learning_hash": request.learning.learning_hash,
        "forbidden_candidate_ids": request.forbidden_candidate_ids,
        "input_evidence_refs": request.input_evidence_refs,
        "data_source": "cached_only",
        "exchange_access": False,
        "promotion_state": "unpromoted",
        "paper_activation": False,
        "execution_authority": False,
        "thesis_hash": "0" * 64,
        "plan_hash": "0" * 64,
    }
    try:
        validated = ResearchPlan.model_validate(data)
    except ValidationError as exc:
        raise _SchemaContractError(
            _safe_schema_diagnostics(
                exc,
                allowed_fields=frozenset(
                    {
                        "expected_regime",
                        "falsification_criteria",
                        "hypothesis",
                        "novelty_dimensions",
                        "strategy_family",
                    }
                ),
            )
        ) from None
    except TypeError:
        raise _SchemaContractError(("__root__:type_error",)) from None
    thesis_hash = research_plan_thesis_hash(validated)
    bound = ResearchPlan.model_validate(
        {
            **validated.model_dump(),
            "thesis_hash": thesis_hash,
            "plan_hash": "0" * 64,
        }
    )
    plan_hash = research_plan_content_hash(bound)
    return ResearchPlan.model_validate(
        {
            **bound.model_dump(),
            "plan_id": f"plan-{plan_hash}",
            "plan_hash": plan_hash,
        }
    )


_SAFE_PROVIDER_METADATA_KEYS = frozenset(
    {
        "choice_count",
        "content_kind",
        "content_length",
        "content_sha256",
        "error_code",
        "error_reason",
        "error_status",
        "finish_reason",
        "response_keys",
        "status_code",
        "transport_error_type",
    }
)


def _safe_provider_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in sorted(_SAFE_PROVIDER_METADATA_KEYS) if key in value}


FailureLearningTransport = Callable[[FailureLearningRequest], Mapping[str, object]]
ResearchPlanTransport = Callable[[ResearchPlanRequest], Mapping[str, object]]


class FailureLearner:
    """Call an injected learner transport without granting it authority."""

    def __init__(self, transport: FailureLearningTransport) -> None:
        self.transport = transport

    def learn(self, request: FailureLearningRequest) -> FailureLearningResult:
        try:
            payload = self.transport(request)
        except Exception as exc:
            return FailureLearningResult(
                decision="rejected",
                reason_codes=("provider_error",),
                provider_metadata=_safe_provider_metadata(getattr(exc, "metadata", None)),
            )
        if not isinstance(payload, Mapping):
            return FailureLearningResult(decision="rejected", reason_codes=("schema_rejected",))
        provider_metadata = _safe_provider_metadata(getattr(payload, "metadata", None))
        try:
            artifact = parse_failure_learning(payload, request)
        except _SchemaContractError as exc:
            return FailureLearningResult(
                decision="rejected",
                reason_codes=("schema_rejected",),
                schema_diagnostics=exc.diagnostics,
                provider_metadata=provider_metadata,
            )
        except DataQualityError:
            return FailureLearningResult(
                decision="rejected",
                reason_codes=("schema_rejected",),
                schema_diagnostics=("learning_payload_invalid",),
                provider_metadata=provider_metadata,
            )
        return FailureLearningResult(
            decision="accepted",
            artifact=artifact,
            reason_codes=("schema_valid",),
            provider_metadata=provider_metadata,
        )


class ResearchPlanner:
    """Call an injected planner transport and enforce complete-history binding."""

    def __init__(self, transport: ResearchPlanTransport) -> None:
        self.transport = transport

    def plan(self, request: ResearchPlanRequest) -> ResearchPlanResult:
        try:
            payload = self.transport(request)
        except Exception as exc:
            return ResearchPlanResult(
                decision="rejected",
                reason_codes=("provider_error",),
                provider_metadata=_safe_provider_metadata(getattr(exc, "metadata", None)),
            )
        if not isinstance(payload, Mapping):
            return ResearchPlanResult(decision="rejected", reason_codes=("schema_rejected",))
        provider_metadata = _safe_provider_metadata(getattr(payload, "metadata", None))
        try:
            plan = parse_research_plan(payload, request)
        except _SchemaContractError as exc:
            return ResearchPlanResult(
                decision="rejected",
                reason_codes=("schema_rejected",),
                schema_diagnostics=exc.diagnostics,
                provider_metadata=provider_metadata,
            )
        except DataQualityError:
            return ResearchPlanResult(
                decision="rejected",
                reason_codes=("schema_rejected",),
                schema_diagnostics=("research_plan_payload_invalid",),
                provider_metadata=provider_metadata,
            )
        if plan.novelty_dimensions and not (
            set(plan.novelty_dimensions) & set(request.learning.recommended_novelty_dimensions)
        ):
            return ResearchPlanResult(
                decision="rejected",
                reason_codes=("learning_not_consumed",),
                provider_metadata=provider_metadata,
            )
        if plan.plan_hash in request.prior_plan_hashes:
            return ResearchPlanResult(
                decision="rejected",
                reason_codes=("plan_replayed",),
                provider_metadata=provider_metadata,
            )
        if plan.thesis_hash in request.prior_thesis_hashes:
            return ResearchPlanResult(
                decision="rejected",
                reason_codes=("thesis_replayed",),
                provider_metadata=provider_metadata,
            )
        return ResearchPlanResult(
            decision="accepted",
            plan=plan,
            reason_codes=("plan_valid",),
            provider_metadata=provider_metadata,
        )


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


def read_failure_memory_entry(path: Path) -> FailureMemoryEntry:
    try:
        entry = FailureMemoryEntry.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted failure memory entry") from exc
    if failure_memory_content_hash(entry) != entry.memory_hash:
        raise DomainViolation(f"failure memory hash mismatch: {path}")
    if entry.entry_id != f"failure-{entry.memory_hash}":
        raise DomainViolation(f"failure memory ID mismatch: {path}")
    return entry


def write_failure_memory_entry(path: Path, entry: FailureMemoryEntry) -> FailureMemoryEntry:
    if failure_memory_content_hash(entry) != entry.memory_hash:
        raise DomainViolation("failure memory hash mismatch")
    if path.exists():
        existing = read_failure_memory_entry(path)
        if existing != entry:
            raise DomainViolation(f"failure memory path is immutable: {path}")
        return existing
    payload = json.dumps(entry.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    _write_once(path, payload)
    readback = read_failure_memory_entry(path)
    if readback != entry:
        raise DomainViolation(f"failure memory path is immutable: {path}")
    return readback


def read_failure_learning_artifact(path: Path) -> FailureLearningArtifact:
    try:
        artifact = FailureLearningArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted failure learning artifact") from exc
    if failure_learning_content_hash(artifact) != artifact.learning_hash:
        raise DomainViolation(f"failure learning hash mismatch: {path}")
    return artifact


def write_failure_learning_artifact(
    path: Path, artifact: FailureLearningArtifact
) -> FailureLearningArtifact:
    if failure_learning_content_hash(artifact) != artifact.learning_hash:
        raise DomainViolation("failure learning hash mismatch")
    if path.exists():
        existing = read_failure_learning_artifact(path)
        if existing != artifact:
            raise DomainViolation(f"failure learning path is immutable: {path}")
        return existing
    payload = json.dumps(artifact.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    _write_once(path, payload)
    readback = read_failure_learning_artifact(path)
    if readback != artifact:
        raise DomainViolation(f"failure learning path is immutable: {path}")
    return readback


def read_research_plan(path: Path) -> ResearchPlan:
    try:
        plan = ResearchPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted research plan") from exc
    if research_plan_content_hash(plan) != plan.plan_hash:
        raise DomainViolation(f"research plan hash mismatch: {path}")
    return plan


def write_research_plan(path: Path, plan: ResearchPlan) -> ResearchPlan:
    if research_plan_content_hash(plan) != plan.plan_hash:
        raise DomainViolation("research plan hash mismatch")
    if path.exists():
        existing = read_research_plan(path)
        if existing != plan:
            raise DomainViolation(f"research plan path is immutable: {path}")
        return existing
    payload = json.dumps(plan.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    _write_once(path, payload)
    readback = read_research_plan(path)
    if readback != plan:
        raise DomainViolation(f"research plan path is immutable: {path}")
    return readback


__all__ = [
    "FailureLearner",
    "FailureLearningArtifact",
    "FailureLearningRequest",
    "FailureLearningResult",
    "FailureLearningTransport",
    "FailureMemoryEntry",
    "NoveltyDimension",
    "ResearchPlan",
    "ResearchPlanRequest",
    "ResearchPlanResult",
    "ResearchPlanTransport",
    "StrategyFamily",
    "build_failure_memory_entry",
    "failure_learning_content_hash",
    "failure_memory_content_hash",
    "parse_failure_learning",
    "parse_research_plan",
    "read_failure_learning_artifact",
    "read_failure_memory_entry",
    "read_research_plan",
    "research_plan_content_hash",
    "research_plan_thesis_hash",
    "write_failure_learning_artifact",
    "write_failure_memory_entry",
    "write_research_plan",
]
