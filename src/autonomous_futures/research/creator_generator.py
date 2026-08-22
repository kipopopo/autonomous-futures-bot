"""Provider-agnostic Creator generation boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from .creator_proposals import (
    CreatorProposal,
    creator_proposal_schema_diagnostics,
    parse_creator_proposal,
)


class CreatorGenerationRequest(DomainModel):
    """Evidence references only; prompt text is owned by the provider adapter."""

    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    output_schema_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    attempt: int = Field(ge=1, strict=True)

    @field_validator("input_evidence_refs")
    @classmethod
    def evidence_refs_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("input evidence references must be non-empty")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("input evidence references must be sorted and unique")
        return values


class CreatorGenerationResult(DomainModel):
    """Structured generation result; raw provider payload is intentionally absent."""

    decision: Literal["accepted", "rejected"]
    proposal: CreatorProposal | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)
    schema_diagnostics: tuple[str, ...] = ()
    raw_output: None = None
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(not value for value in values):
            raise ValueError("generation reason codes must be sorted and unique")
        return values

    @field_validator("schema_diagnostics")
    @classmethod
    def schema_diagnostics_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(not value for value in values):
            raise ValueError("schema diagnostics must be sorted and unique")
        return values

    @model_validator(mode="after")
    def decision_matches_proposal(self) -> CreatorGenerationResult:
        if (self.decision == "accepted") != (self.proposal is not None):
            raise ValueError(
                "accepted generation requires proposal and rejected generation forbids it"
            )
        return self


ProposalTransport = Callable[[CreatorGenerationRequest], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class CreatorGenerator:
    """Call an injected provider transport; never owns persistence or execution."""

    transport: ProposalTransport

    def generate(self, request: CreatorGenerationRequest) -> CreatorGenerationResult:
        try:
            payload = self.transport(request)
        except Exception as exc:
            provider_code = getattr(exc, "code", None)
            reason_code = (
                provider_code
                if isinstance(provider_code, str) and provider_code.startswith("provider_")
                else "provider_error"
            )
            return CreatorGenerationResult(decision="rejected", reason_codes=(reason_code,))

        try:
            proposal = parse_creator_proposal(payload)
        except Exception:
            return CreatorGenerationResult(
                decision="rejected",
                reason_codes=("schema_rejected",),
                schema_diagnostics=creator_proposal_schema_diagnostics(payload),
            )
        if proposal.research_run_id != request.research_run_id:
            return CreatorGenerationResult(
                decision="rejected", reason_codes=("research_run_mismatch",)
            )
        return CreatorGenerationResult(
            decision="accepted",
            proposal=proposal,
            reason_codes=("schema_valid",),
        )


__all__ = [
    "CreatorGenerationRequest",
    "CreatorGenerationResult",
    "CreatorGenerator",
    "ProposalTransport",
]
