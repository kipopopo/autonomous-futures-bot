"""Read-only fixed-slot maturity evidence for paper observations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator

from ..domain.contracts import DomainModel
from .observation import PaperObservation, PaperObservationBinding

_SLOT = timedelta(hours=6)


class PaperMaturityReport(DomainModel):
    candidate_id: str
    candidate_artifact_hash: str
    status: Literal["unavailable", "maturing", "blocked", "mature"]
    as_of: datetime
    required_days: int = Field(gt=0, strict=True)
    required_slots: int = Field(gt=0, strict=True)
    observed_slots: int = Field(ge=0, strict=True)
    first_slot: datetime | None = None
    last_slot: datetime | None = None
    maturity_end: datetime | None = None
    next_slot: datetime | None = None
    accounting_complete: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("as_of", "first_slot", "last_slot", "maturity_end", "next_slot")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("paper maturity timestamp must be timezone-aware UTC")
        return value.astimezone(UTC) if value is not None else None


def _slot_start(value: datetime) -> datetime:
    return value.replace(hour=(value.hour // 6) * 6, minute=0, second=0, microsecond=0)


def _report(
    *,
    binding: PaperObservationBinding,
    status: Literal["unavailable", "maturing", "blocked", "mature"],
    as_of: datetime,
    required_days: int,
    observed_slots: int,
    first_slot: datetime | None,
    last_slot: datetime | None,
    maturity_end: datetime | None,
    next_slot: datetime | None,
    accounting_complete: bool,
    reason_codes: tuple[str, ...],
) -> PaperMaturityReport:
    return PaperMaturityReport(
        candidate_id=binding.candidate_id,
        candidate_artifact_hash=binding.candidate_artifact_hash,
        status=status,
        as_of=as_of,
        required_days=required_days,
        required_slots=required_days * 4,
        observed_slots=observed_slots,
        first_slot=first_slot,
        last_slot=last_slot,
        maturity_end=maturity_end,
        next_slot=next_slot,
        accounting_complete=accounting_complete,
        reason_codes=reason_codes,
    )


def evaluate_paper_maturity(
    observations: Sequence[PaperObservation],
    *,
    candidate_id: str,
    candidate_artifact_hash: str,
    as_of: datetime,
    required_days: int = 7,
) -> PaperMaturityReport:
    """Evaluate fixed six-hour paper evidence without mutation or current-time lookup."""
    binding = PaperObservationBinding(
        candidate_id=candidate_id,
        candidate_artifact_hash=candidate_artifact_hash,
    )
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ValueError("as_of must be timezone-aware UTC")
    if required_days <= 0:
        raise ValueError("required_days must be positive")
    observed_at = as_of.astimezone(UTC)
    required_slots = required_days * 4
    if not observations:
        return _report(
            binding=binding,
            status="unavailable",
            as_of=observed_at,
            required_days=required_days,
            observed_slots=0,
            first_slot=None,
            last_slot=None,
            maturity_end=None,
            next_slot=None,
            accounting_complete=False,
            reason_codes=("paper_observation_evidence_unavailable",),
        )

    slots: list[datetime] = []
    for observation in observations:
        if (
            observation.candidate_id != binding.candidate_id
            or observation.candidate_artifact_hash != binding.candidate_artifact_hash
        ):
            return _report(
                binding=binding,
                status="blocked",
                as_of=observed_at,
                required_days=required_days,
                observed_slots=0,
                first_slot=None,
                last_slot=None,
                maturity_end=None,
                next_slot=None,
                accounting_complete=False,
                reason_codes=("paper_observation_binding_mismatch",),
            )
        if observation.observed_at > observed_at:
            return _report(
                binding=binding,
                status="blocked",
                as_of=observed_at,
                required_days=required_days,
                observed_slots=0,
                first_slot=None,
                last_slot=None,
                maturity_end=None,
                next_slot=None,
                accounting_complete=False,
                reason_codes=("paper_observation_future_timestamp",),
            )
        slots.append(_slot_start(observation.observed_at))

    unique_slots = set(slots)
    first_slot = min(unique_slots)
    maturity_end = first_slot + timedelta(days=required_days)
    expected_slots = tuple(first_slot + index * _SLOT for index in range(required_slots))
    expected_set = set(expected_slots)
    window_observations = tuple(
        observation
        for observation in observations
        if _slot_start(observation.observed_at) in expected_set
    )
    observed_expected = unique_slots & expected_set
    last_slot = max(observed_expected) if observed_expected else None
    missing_slots = tuple(slot for slot in expected_slots if slot not in observed_expected)
    due_missing = tuple(slot for slot in missing_slots if slot + _SLOT <= observed_at)
    if len(unique_slots) != len(slots):
        return _report(
            binding=binding,
            status="blocked",
            as_of=observed_at,
            required_days=required_days,
            observed_slots=len(observed_expected),
            first_slot=first_slot,
            last_slot=last_slot,
            maturity_end=maturity_end,
            next_slot=missing_slots[0] if missing_slots else None,
            accounting_complete=False,
            reason_codes=("paper_observation_duplicate_slot",),
        )
    if any(not observation.accounting_complete for observation in window_observations):
        return _report(
            binding=binding,
            status="blocked",
            as_of=observed_at,
            required_days=required_days,
            observed_slots=len(observed_expected),
            first_slot=first_slot,
            last_slot=last_slot,
            maturity_end=maturity_end,
            next_slot=due_missing[0] if due_missing else None,
            accounting_complete=False,
            reason_codes=("paper_observation_accounting_incomplete",),
        )
    if due_missing:
        return _report(
            binding=binding,
            status="blocked",
            as_of=observed_at,
            required_days=required_days,
            observed_slots=len(observed_expected),
            first_slot=first_slot,
            last_slot=last_slot,
            maturity_end=maturity_end,
            next_slot=due_missing[0],
            accounting_complete=True,
            reason_codes=("paper_observation_slot_missing",),
        )
    if observed_at < maturity_end:
        next_slot = next(
            (slot for slot in expected_slots if slot not in observed_expected), maturity_end
        )
        return _report(
            binding=binding,
            status="maturing",
            as_of=observed_at,
            required_days=required_days,
            observed_slots=len(observed_expected),
            first_slot=first_slot,
            last_slot=last_slot,
            maturity_end=maturity_end,
            next_slot=next_slot,
            accounting_complete=True,
            reason_codes=("paper_observation_maturity_in_progress",),
        )
    return _report(
        binding=binding,
        status="mature",
        as_of=observed_at,
        required_days=required_days,
        observed_slots=len(observed_expected),
        first_slot=first_slot,
        last_slot=last_slot,
        maturity_end=maturity_end,
        next_slot=None,
        accounting_complete=True,
        reason_codes=("paper_observation_maturity_complete",),
    )
