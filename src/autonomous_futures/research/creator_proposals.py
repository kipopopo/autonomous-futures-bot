"""Strict, non-authoritative Creator proposal intake and trial outcomes."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel, StrategySpec
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact, build_creator_candidate_artifact


class CreatorProposal(DomainModel):
    """Validated model proposal; raw prompts and model output are not retained."""

    proposal_version: Literal[1] = 1
    proposal_id: str = Field(pattern=r"^proposal-[a-z0-9][a-z0-9-]{0,63}$")
    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    hypothesis: str = Field(min_length=1, max_length=2000)
    expected_regime: str = Field(min_length=1, max_length=128)
    novelty_reason: str = Field(min_length=1, max_length=1000)
    strategy: StrategySpec
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def strategy_identity_matches(self) -> CreatorProposal:
        if not self.strategy.strategy_id.startswith("cand-"):
            raise ValueError("proposal strategy_id must be a candidate ID")
        return self

    def build_outcome(
        self,
        *,
        decision: Literal["accepted", "rejected"],
        candidate_artifact_hash: str | None,
        reason_codes: tuple[str, ...],
        recorded_at: datetime,
    ) -> CreatorProposalOutcome:
        return build_creator_proposal_outcome(
            proposal=self,
            decision=decision,
            candidate_artifact_hash=candidate_artifact_hash,
            reason_codes=reason_codes,
            recorded_at=recorded_at,
        )


class CreatorProposalOutcome(DomainModel):
    """Immutable trial disposition; evidence only, never promotion authority."""

    outcome_version: Literal[1] = 1
    proposal_id: str = Field(pattern=r"^proposal-[a-z0-9][a-z0-9-]{0,63}$")
    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    decision: Literal["accepted", "rejected"]
    candidate_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason_codes: tuple[str, ...] = Field(min_length=1)
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    recorded_at: datetime
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("recorded_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("reason codes must be non-empty")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("reason codes must be sorted and unique")
        return values

    @model_validator(mode="after")
    def decision_has_candidate_binding(self) -> CreatorProposalOutcome:
        if self.decision == "accepted" and self.candidate_artifact_hash is None:
            raise ValueError("accepted proposal outcome requires candidate artifact hash")
        return self


def _proposal_content_hash(proposal: CreatorProposal) -> str:
    payload = proposal.model_dump(mode="json", exclude={"proposal_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def canonical_creator_candidate_id(strategy: StrategySpec) -> str:
    payload = strategy.model_dump(mode="json", exclude={"strategy_id"})
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"cand-{digest}"


def proposal_content_hash(proposal: CreatorProposal) -> str:
    return _proposal_content_hash(proposal)


def parse_creator_proposal(payload: Mapping[str, object]) -> CreatorProposal:
    """Validate untrusted structured model output without executing or persisting it."""
    try:
        provisional = CreatorProposal.model_validate({**payload, "proposal_hash": "0" * 64})
    except ValidationError as exc:
        raise DataQualityError("invalid Creator proposal: " + str(exc)) from None
    provisional = provisional.model_copy(
        update={
            "strategy": provisional.strategy.model_copy(
                update={"strategy_id": canonical_creator_candidate_id(provisional.strategy)}
            )
        }
    )
    return provisional.model_copy(update={"proposal_hash": _proposal_content_hash(provisional)})


def creator_proposal_schema_diagnostics(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return field/type diagnostics without returning untrusted input values."""
    try:
        CreatorProposal.model_validate({**payload, "proposal_hash": "0" * 64})
    except ValidationError as exc:
        diagnostics = {
            f"{'.'.join(str(part) for part in error['loc']) or 'root'}:{error['type']}"
            for error in exc.errors()
        }
        return tuple(sorted(diagnostics))
    return ()


def build_candidate_from_proposal(
    proposal: CreatorProposal,
    *,
    bundle_hash: str,
    dataset_registry_hash: str,
    creator_run_id: str,
    research_seed: int,
    created_at: datetime,
) -> CreatorCandidateArtifact:
    if _proposal_content_hash(proposal) != proposal.proposal_hash:
        raise DomainViolation("Creator proposal hash mismatch")
    return build_creator_candidate_artifact(
        candidate_id=proposal.strategy.strategy_id,
        strategy=proposal.strategy,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        creator_run_id=creator_run_id,
        research_seed=research_seed,
        created_at=created_at,
    )


def _outcome_content_hash(outcome: CreatorProposalOutcome) -> str:
    payload = outcome.model_dump(mode="json", exclude={"recorded_at", "outcome_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_creator_proposal_outcome(
    *,
    proposal: CreatorProposal,
    decision: Literal["accepted", "rejected"],
    candidate_artifact_hash: str | None,
    reason_codes: tuple[str, ...],
    recorded_at: datetime,
) -> CreatorProposalOutcome:
    if _proposal_content_hash(proposal) != proposal.proposal_hash:
        raise DomainViolation("Creator proposal hash mismatch")
    try:
        provisional = CreatorProposalOutcome(
            proposal_id=proposal.proposal_id,
            research_run_id=proposal.research_run_id,
            proposal_hash=proposal.proposal_hash,
            candidate_id=proposal.strategy.strategy_id,
            decision=decision,
            candidate_artifact_hash=candidate_artifact_hash,
            reason_codes=tuple(sorted(reason_codes)),
            recorded_at=recorded_at,
            outcome_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid Creator proposal outcome: " + str(exc)) from None
    return provisional.model_copy(update={"outcome_hash": _outcome_content_hash(provisional)})


def read_creator_proposal_outcome(path: Path) -> CreatorProposalOutcome:
    try:
        outcome = CreatorProposalOutcome.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except ValidationError as exc:
        raise DataQualityError("invalid persisted Creator proposal outcome") from exc
    if _outcome_content_hash(outcome) != outcome.outcome_hash:
        raise DomainViolation(f"Creator proposal outcome hash mismatch: {path}")
    return outcome


def write_creator_proposal_outcome(
    path: Path, outcome: CreatorProposalOutcome
) -> CreatorProposalOutcome:
    if _outcome_content_hash(outcome) != outcome.outcome_hash:
        raise DomainViolation("Creator proposal outcome hash mismatch")
    if path.exists():
        existing = read_creator_proposal_outcome(path)
        if existing != outcome:
            raise DomainViolation(f"Creator proposal outcome path is immutable: {path}")
        return existing
    payload = json.dumps(outcome.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_creator_proposal_outcome(path)
        if existing != outcome:
            raise DomainViolation(f"Creator proposal outcome path is immutable: {path}") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_creator_proposal_outcome(path)


__all__ = [
    "CreatorProposal",
    "CreatorProposalOutcome",
    "build_candidate_from_proposal",
    "build_creator_proposal_outcome",
    "canonical_creator_candidate_id",
    "creator_proposal_schema_diagnostics",
    "parse_creator_proposal",
    "proposal_content_hash",
    "read_creator_proposal_outcome",
    "write_creator_proposal_outcome",
]
