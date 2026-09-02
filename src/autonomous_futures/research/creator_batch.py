"""Bounded in-memory Creator batch orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from .creator_artifacts import CreatorCandidateArtifact
from .creator_generator import CreatorGenerationRequest, CreatorGenerator
from .creator_proposals import build_candidate_from_proposal


class CreatorBatchTrial(DomainModel):
    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    proposal_id: str | None = Field(default=None, pattern=r"^proposal-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str | None = Field(default=None, pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    decision: Literal["accepted", "rejected"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    schema_diagnostics: tuple[str, ...] = ()
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    candidate_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("schema_diagnostics")
    @classmethod
    def schema_diagnostics_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(not value for value in values):
            raise ValueError("schema diagnostics must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_trial_binding(self) -> CreatorBatchTrial:
        if self.decision == "accepted" and (
            self.candidate_id is None or self.candidate_artifact_hash is None
        ):
            raise ValueError("accepted trial requires candidate binding")
        return self


class CreatorBatchResult(DomainModel):
    trials: tuple[CreatorBatchTrial, ...] = Field(min_length=1)
    accepted_candidates: tuple[CreatorCandidateArtifact, ...] = ()
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @model_validator(mode="after")
    def accepted_candidates_match_trials(self) -> CreatorBatchResult:
        candidate_ids = tuple(candidate.candidate_id for candidate in self.accepted_candidates)
        accepted_trial_ids = tuple(
            trial.candidate_id for trial in self.trials if trial.decision == "accepted"
        )
        if candidate_ids != accepted_trial_ids:
            raise ValueError("accepted candidates must match accepted trial order")
        return self


@dataclass(frozen=True, slots=True)
class _BatchConfig:
    bundle_hash: str
    dataset_registry_hash: str
    creator_run_id: str
    research_seed: int
    created_at: datetime


def run_creator_batch(
    requests: Sequence[CreatorGenerationRequest],
    *,
    generator: CreatorGenerator,
    bundle_hash: str,
    dataset_registry_hash: str,
    creator_run_id: str,
    research_seed: int,
    created_at: datetime,
) -> CreatorBatchResult:
    if not requests:
        raise ValueError("Creator batch requires at least one request")
    config = _BatchConfig(
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        creator_run_id=creator_run_id,
        research_seed=research_seed,
        created_at=created_at,
    )
    seen_candidate_ids: set[str] = set()
    trials: list[CreatorBatchTrial] = []
    accepted: list[CreatorCandidateArtifact] = []
    for index, request in enumerate(requests):
        generated = generator.generate(request)
        if generated.proposal is None:
            trials.append(
                CreatorBatchTrial(
                    research_run_id=request.research_run_id,
                    decision="rejected",
                    reason_codes=generated.reason_codes,
                    schema_diagnostics=generated.schema_diagnostics,
                    provider_metadata=generated.provider_metadata,
                )
            )
            continue

        proposal = generated.proposal
        candidate_id = proposal.strategy.strategy_id
        if candidate_id in seen_candidate_ids:
            trials.append(
                CreatorBatchTrial(
                    research_run_id=request.research_run_id,
                    proposal_id=proposal.proposal_id,
                    candidate_id=candidate_id,
                    decision="rejected",
                    reason_codes=("duplicate_candidate_id",),
                    provider_metadata=generated.provider_metadata,
                )
            )
            continue

        candidate = build_candidate_from_proposal(
            proposal,
            bundle_hash=config.bundle_hash,
            dataset_registry_hash=config.dataset_registry_hash,
            creator_run_id=config.creator_run_id,
            research_seed=config.research_seed + index,
            created_at=config.created_at,
        )
        seen_candidate_ids.add(candidate_id)
        accepted.append(candidate)
        trials.append(
            CreatorBatchTrial(
                research_run_id=request.research_run_id,
                proposal_id=proposal.proposal_id,
                candidate_id=candidate_id,
                decision="accepted",
                reason_codes=("candidate_accepted_for_testing",),
                provider_metadata=generated.provider_metadata,
                candidate_artifact_hash=candidate.artifact_hash,
            )
        )

    return CreatorBatchResult(trials=tuple(trials), accepted_candidates=tuple(accepted))


__all__ = ["CreatorBatchResult", "CreatorBatchTrial", "run_creator_batch"]
