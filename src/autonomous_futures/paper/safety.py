"""Fail-closed paper safety evaluation; it cannot authorize activation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel, PaperExecutionRequest


class PaperSafetyEvidence(DomainModel):
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_decision: Literal["rejected", "qualified"]
    zero_oos_liquidations: bool


class PaperActionApproval(DomainModel):
    """Caller-injected one-shot approval for one local simulated action."""

    approval_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trade_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    action: Literal["open", "close"]
    approved_at: datetime
    expires_at: datetime

    @field_validator("approved_at", "expires_at")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def expiry_follows_approval(self) -> PaperActionApproval:
        if self.expires_at <= self.approved_at:
            raise ValueError("expires_at must be after approved_at")
        return self


class PaperSafetyDecision(DomainModel):
    allowed: Literal[False] = False
    reason_codes: tuple[str, ...] = Field(min_length=1)
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False


class PaperActionPermission(DomainModel):
    """Decision for one caller-approved local simulated ledger action."""

    permitted: bool
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


def evaluate_paper_action_permission(
    request: PaperExecutionRequest,
    evidence: PaperSafetyEvidence,
    approval: PaperActionApproval,
    *,
    trade_id: str,
    action: Literal["open", "close"],
    occurred_at: datetime,
) -> PaperActionPermission:
    """Permit only one explicitly approved local simulation action."""
    if occurred_at.tzinfo is None or occurred_at.utcoffset() != UTC.utcoffset(occurred_at):
        raise ValueError("timezone-aware UTC timestamp required")
    reasons: list[str] = []
    if (
        request.candidate_id != evidence.candidate_id
        or request.candidate_artifact_hash != evidence.candidate_artifact_hash
    ):
        reasons.append("candidate_evidence_mismatch")
    if evidence.qualification_decision != "qualified":
        reasons.append("qualification_not_qualified")
    if not evidence.zero_oos_liquidations:
        reasons.append("oos_liquidations_present")
    if (
        approval.candidate_id != request.candidate_id
        or approval.candidate_artifact_hash != request.candidate_artifact_hash
    ):
        reasons.append("approval_candidate_mismatch")
    if approval.trade_id != trade_id:
        reasons.append("approval_trade_mismatch")
    if approval.action != action:
        reasons.append("approval_action_mismatch")
    if occurred_at < approval.approved_at:
        reasons.append("approval_not_yet_valid")
    if occurred_at >= approval.expires_at:
        reasons.append("approval_expired")
    return PaperActionPermission(
        permitted=not reasons,
        reason_codes=tuple(sorted(reasons)) if reasons else ("local_paper_action_permitted",),
    )
