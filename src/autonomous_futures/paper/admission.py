"""Strict, evidence-bound Strategy Admission decision contracts and decider for paper trading."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..research.creator_artifacts import (
    CreatorCandidateArtifact,
    _artifact_content_hash,
)
from ..research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    _qualification_content_hash,
)

if TYPE_CHECKING:
    from .live_engine import ActivePaperTrade

AdmissionOutcome = Literal[
    "admitted",
    "rejected",
    "deferred_active_position",
    "blocked_unqualified",
    "blocked_invalid_binding",
]


class StrategyAdmissionDecision(DomainModel):
    """Immutable paper strategy admission decision artifact."""

    decision_version: Literal[1] = 1
    decision_id: str = Field(pattern=r"^admission-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    decision: AdmissionOutcome
    reason_codes: tuple[str, ...] = Field(min_length=1)
    active_trade_retained: bool = False
    data_source: Literal["cached_only"] = "cached_only"
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: bool = True
    execution_authority: Literal[False] = False
    evaluated_at: datetime
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("admission evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("reason_codes")
    @classmethod
    def reason_codes_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or not value.strip() for value in values):
            raise ValueError("reason codes must be non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("reason codes must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_admission_contract(self) -> StrategyAdmissionDecision:
        if self.decision != "admitted" and self.active_trade_retained:
            raise ValueError("active_trade_retained is only valid for admitted decisions")
        return self


def strategy_admission_content_hash(decision: StrategyAdmissionDecision) -> str:
    """Compute deterministic SHA-256 hash over canonical admission decision fields."""
    payload = decision.model_dump(mode="json", exclude={"decision_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


class StrategyAdmissionDecider:
    """Evaluates qualification evidence and paper position state before strategy admission."""

    def evaluate_admission(
        self,
        *,
        candidate: CreatorCandidateArtifact,
        qualification: CreatorCandidateQualificationArtifact,
        symbol: str,
        active_trades: Mapping[str, ActivePaperTrade] | None = None,
        require_flat: bool = False,
        evaluated_at: datetime | None = None,
        decision_id: str | None = None,
    ) -> StrategyAdmissionDecision:
        now = evaluated_at or datetime.now(UTC)
        dec_id = decision_id or f"admission-{candidate.candidate_id[5:17]}-{int(now.timestamp())}"

        # 1. Validate cryptographic binding, scope, and content hash integrity
        if (
            qualification.candidate_id != candidate.candidate_id
            or qualification.candidate_artifact_hash != candidate.artifact_hash
            or _artifact_content_hash(candidate) != candidate.artifact_hash
            or _qualification_content_hash(qualification) != qualification.qualification_hash
        ):
            return self._build_decision(
                decision_id=dec_id,
                candidate=candidate,
                qualification=qualification,
                symbol=symbol,
                decision="blocked_invalid_binding",
                reason_codes=("candidate_hash_mismatch",),
                active_trade_retained=False,
                evaluated_at=now,
            )

        if (
            candidate.strategy.universe.symbols
            and symbol not in candidate.strategy.universe.symbols
        ):
            return self._build_decision(
                decision_id=dec_id,
                candidate=candidate,
                qualification=qualification,
                symbol=symbol,
                decision="blocked_invalid_binding",
                reason_codes=("symbol_not_in_candidate_universe",),
                active_trade_retained=False,
                evaluated_at=now,
            )

        # 2. Validate qualification state
        if qualification.decision != "qualified":
            return self._build_decision(
                decision_id=dec_id,
                candidate=candidate,
                qualification=qualification,
                symbol=symbol,
                decision="blocked_unqualified",
                reason_codes=("qualification_rejected",),
                active_trade_retained=False,
                evaluated_at=now,
            )

        # 3. Check active paper position safety
        active_trade = (active_trades or {}).get(symbol)
        has_active = active_trade is not None

        if has_active and require_flat:
            return self._build_decision(
                decision_id=dec_id,
                candidate=candidate,
                qualification=qualification,
                symbol=symbol,
                decision="deferred_active_position",
                reason_codes=("active_position_open",),
                active_trade_retained=False,
                evaluated_at=now,
            )

        # 4. Admission granted
        reason = (
            "candidate_qualified_active_trade_retained"
            if has_active
            else "candidate_qualified_for_admission"
        )
        return self._build_decision(
            decision_id=dec_id,
            candidate=candidate,
            qualification=qualification,
            symbol=symbol,
            decision="admitted",
            reason_codes=(reason,),
            active_trade_retained=has_active,
            evaluated_at=now,
        )

    def _build_decision(
        self,
        *,
        decision_id: str,
        candidate: CreatorCandidateArtifact,
        qualification: CreatorCandidateQualificationArtifact,
        symbol: str,
        decision: AdmissionOutcome,
        reason_codes: tuple[str, ...],
        active_trade_retained: bool,
        evaluated_at: datetime,
    ) -> StrategyAdmissionDecision:
        sorted_reasons = tuple(sorted(set(reason_codes)))
        provisional = StrategyAdmissionDecision.model_validate(
            {
                "decision_version": 1,
                "decision_id": decision_id,
                "candidate_id": candidate.candidate_id,
                "candidate_artifact_hash": candidate.artifact_hash,
                "qualification_hash": qualification.qualification_hash,
                "symbol": symbol,
                "decision": decision,
                "reason_codes": sorted_reasons,
                "active_trade_retained": active_trade_retained,
                "data_source": "cached_only",
                "promotion_state": "unpromoted",
                "paper_activation": decision == "admitted",
                "execution_authority": False,
                "evaluated_at": evaluated_at,
                "decision_hash": "0" * 64,
            }
        )
        dec_hash = strategy_admission_content_hash(provisional)
        return provisional.model_copy(update={"decision_hash": dec_hash})


__all__ = [
    "AdmissionOutcome",
    "StrategyAdmissionDecider",
    "StrategyAdmissionDecision",
    "strategy_admission_content_hash",
]
