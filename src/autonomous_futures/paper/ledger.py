"""Injected append-only paper ledger; persistence belongs to a later caller-owned adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel, StrictNonNegativeDecimal, StrictPositiveDecimal


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
    entry_fee: StrictNonNegativeDecimal | None = None
    exit_fee: StrictNonNegativeDecimal | None = None
    slippage_cost: StrictNonNegativeDecimal | None = None
    gross_pnl: Decimal | None = None
    net_pnl: Decimal | None = None

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("paper ledger timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def accounting_is_complete(self) -> PaperLedgerEntry:
        accounting = (
            self.entry_fee,
            self.exit_fee,
            self.slippage_cost,
            self.gross_pnl,
            self.net_pnl,
        )
        if self.event == "open":
            if any(value is not None for value in (self.exit_fee, self.gross_pnl, self.net_pnl)):
                raise ValueError("paper open must not include close accounting")
            if (self.entry_fee is None) != (self.slippage_cost is None):
                raise ValueError("paper open requires complete entry accounting")
        if self.event == "close":
            if any(value is None for value in accounting):
                raise ValueError("paper close requires complete accounting")
            assert self.entry_fee is not None
            assert self.exit_fee is not None
            assert self.slippage_cost is not None
            assert self.gross_pnl is not None
            assert self.net_pnl is not None
            if not self.gross_pnl.is_finite() or not self.net_pnl.is_finite():
                raise ValueError("paper P&L must be finite")
            if self.net_pnl != self.gross_pnl - self.entry_fee - self.exit_fee:
                raise ValueError("paper net P&L must include all fees")
        return self


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
