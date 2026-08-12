"""Fail-closed paper safety evaluation; it cannot authorize activation."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..domain.contracts import DomainModel, PaperExecutionRequest


class PaperSafetyEvidence(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_decision: Literal["rejected", "qualified"]
    zero_oos_liquidations: bool


class PaperSafetyDecision(DomainModel):
    allowed: Literal[False] = False
    reason_codes: tuple[str, ...] = Field(min_length=1)
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False


def evaluate_paper_safety(
    request: PaperExecutionRequest, evidence: PaperSafetyEvidence
) -> PaperSafetyDecision:
    """Return a deterministic blocked decision from explicit evidence only."""
    reasons: list[str] = []
    if (
        request.candidate_id != evidence.candidate_id
        or request.candidate_artifact_hash != evidence.candidate_artifact_hash
    ):
        reasons.append("candidate_evidence_mismatch")
    if not evidence.zero_oos_liquidations:
        reasons.append("oos_liquidations_present")
    reasons.append("paper_activation_not_authorized")
    if evidence.qualification_decision != "qualified":
        reasons.append("qualification_not_qualified")
    return PaperSafetyDecision(reason_codes=tuple(sorted(reasons)))
