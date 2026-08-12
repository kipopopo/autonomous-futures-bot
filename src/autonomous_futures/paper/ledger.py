"""Injected append-only paper ledger; persistence belongs to a later caller-owned adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

from ..domain.contracts import DomainModel, StrictPositiveDecimal


class PaperLedgerError(ValueError):
    """Raised when injected paper history has an invalid lifecycle transition."""


class PaperLedgerEntry(DomainModel):
    event: Literal["open", "close"]
    trade_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    candidate_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    side: Literal["LONG", "SHORT"]
    quantity: StrictPositiveDecimal
    fill_price: StrictPositiveDecimal
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("paper ledger timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)


class PaperLedger:
    """Rebuildable paper lifecycle state from caller-injected append-only events."""

    def __init__(self, entries: tuple[PaperLedgerEntry, ...] = ()) -> None:
        self._entries: list[PaperLedgerEntry] = []
        self._open_by_trade_id: dict[str, PaperLedgerEntry] = {}
        self._open_by_candidate_symbol: dict[tuple[str, str], PaperLedgerEntry] = {}
        for entry in entries:
            self.append(entry)

    @property
    def entries(self) -> tuple[PaperLedgerEntry, ...]:
        return tuple(self._entries)

    def open_positions(self) -> tuple[PaperLedgerEntry, ...]:
        return tuple(self._open_by_trade_id.values())

    def append(self, entry: PaperLedgerEntry) -> None:
        key = (entry.candidate_id, entry.symbol)
        if entry.event == "open":
            if key in self._open_by_candidate_symbol:
                raise PaperLedgerError("duplicate open paper position")
            if entry.trade_id in self._open_by_trade_id:
                raise PaperLedgerError("duplicate open trade ID")
            self._open_by_trade_id[entry.trade_id] = entry
            self._open_by_candidate_symbol[key] = entry
        else:
            open_entry = self._open_by_trade_id.get(entry.trade_id)
            if open_entry is None:
                raise PaperLedgerError("missing open paper position")
            if (
                entry.candidate_id,
                entry.candidate_artifact_hash,
                entry.symbol,
                entry.side,
                entry.quantity,
            ) != (
                open_entry.candidate_id,
                open_entry.candidate_artifact_hash,
                open_entry.symbol,
                open_entry.side,
                open_entry.quantity,
            ):
                raise PaperLedgerError("close does not match open paper position")
            if entry.occurred_at < open_entry.occurred_at:
                raise PaperLedgerError("paper close precedes open")
            del self._open_by_trade_id[entry.trade_id]
            del self._open_by_candidate_symbol[key]
        self._entries.append(entry)
