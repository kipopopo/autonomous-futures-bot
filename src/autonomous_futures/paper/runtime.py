"""Caller-driven local paper actions with one-shot human approvals."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, TypeAdapter

from ..domain.contracts import (
    DomainModel,
    PaperExecutionRequest,
    StrictNonNegativeDecimal,
    StrictPositiveDecimal,
)
from .ledger import PaperLedgerEntry
from .safety import (
    PaperActionApproval,
    PaperSafetyEvidence,
    evaluate_paper_action_permission,
)
from .sqlite_ledger import SqlitePaperLedger


class PaperRuntimeResult(DomainModel):
    status: Literal["opened", "closed", "blocked"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    trade_id: str
    fill_price: StrictPositiveDecimal | None = None
    entry_fee: StrictNonNegativeDecimal | None = None
    exit_fee: StrictNonNegativeDecimal | None = None
    slippage_cost: StrictNonNegativeDecimal | None = None
    gross_pnl: Decimal | None = None
    net_pnl: Decimal | None = None
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False


class PaperRuntime:
    """Append explicit locally simulated opens; it has no autonomous inputs."""

    def __init__(self, ledger: SqlitePaperLedger) -> None:
        self.ledger = ledger

    def open(
        self,
        request: PaperExecutionRequest,
        evidence: PaperSafetyEvidence,
        approval: PaperActionApproval,
        *,
        trade_id: str,
        occurred_at: datetime,
    ) -> PaperRuntimeResult:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() != UTC.utcoffset(occurred_at):
            raise ValueError("timezone-aware UTC timestamp required")
        occurred = occurred_at.astimezone(UTC)
        permission = evaluate_paper_action_permission(
            request,
            evidence,
            approval,
            trade_id=trade_id,
            action="open",
            occurred_at=occurred,
        )
        if not permission.permitted:
            return PaperRuntimeResult(
                status="blocked",
                trade_id=trade_id,
                reason_codes=permission.reason_codes,
            )
        slippage_rate = request.slippage_bps / Decimal("10000")
        fill_price = request.mark_price * (
            Decimal("1") + slippage_rate if request.side == "LONG" else Decimal("1") - slippage_rate
        )
        entry_fee = fill_price * request.quantity * request.fee_rate
        slippage_cost = abs(fill_price - request.mark_price) * request.quantity
        self.ledger.append(
            PaperLedgerEntry(
                event="open",
                trade_id=trade_id,
                candidate_id=request.candidate_id,
                candidate_artifact_hash=request.candidate_artifact_hash,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                fill_price=fill_price,
                occurred_at=occurred,
                approval_id=approval.approval_id,
                entry_fee=entry_fee,
                slippage_cost=slippage_cost,
            )
        )
        return PaperRuntimeResult(
            status="opened",
            trade_id=trade_id,
            reason_codes=("local_paper_open_recorded",),
            fill_price=fill_price,
            entry_fee=entry_fee,
            slippage_cost=slippage_cost,
        )

    def close(
        self,
        request: PaperExecutionRequest,
        evidence: PaperSafetyEvidence,
        approval: PaperActionApproval,
        *,
        trade_id: str,
        exit_mark_price: Decimal,
        occurred_at: datetime,
    ) -> PaperRuntimeResult:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() != UTC.utcoffset(occurred_at):
            raise ValueError("timezone-aware UTC timestamp required")
        occurred = occurred_at.astimezone(UTC)
        permission = evaluate_paper_action_permission(
            request,
            evidence,
            approval,
            trade_id=trade_id,
            action="close",
            occurred_at=occurred,
        )
        if not permission.permitted:
            return PaperRuntimeResult(
                status="blocked",
                trade_id=trade_id,
                reason_codes=permission.reason_codes,
            )
        open_entry = next(
            (entry for entry in self.ledger.load().open_positions() if entry.trade_id == trade_id),
            None,
        )
        if open_entry is None:
            return PaperRuntimeResult(
                status="blocked",
                trade_id=trade_id,
                reason_codes=("durable_open_position_missing",),
            )
        exit_mark = TypeAdapter(StrictPositiveDecimal).validate_python(exit_mark_price)
        slippage_rate = request.slippage_bps / Decimal("10000")
        exit_fill = exit_mark * (
            Decimal("1") - slippage_rate if request.side == "LONG" else Decimal("1") + slippage_rate
        )
        gross_pnl = (
            (exit_fill - open_entry.fill_price) * request.quantity
            if request.side == "LONG"
            else (open_entry.fill_price - exit_fill) * request.quantity
        )
        entry_fee = open_entry.entry_fee
        entry_slippage = open_entry.slippage_cost
        if entry_fee is None or entry_slippage is None:
            return PaperRuntimeResult(
                status="blocked",
                trade_id=trade_id,
                reason_codes=("durable_open_entry_accounting_missing",),
            )
        exit_fee = exit_fill * request.quantity * request.fee_rate
        slippage_cost = entry_slippage + abs(exit_fill - exit_mark) * request.quantity
        net_pnl = gross_pnl - entry_fee - exit_fee
        self.ledger.append(
            PaperLedgerEntry(
                event="close",
                trade_id=trade_id,
                candidate_id=request.candidate_id,
                candidate_artifact_hash=request.candidate_artifact_hash,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                fill_price=exit_fill,
                occurred_at=occurred,
                approval_id=approval.approval_id,
                entry_fee=entry_fee,
                exit_fee=exit_fee,
                slippage_cost=slippage_cost,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
            )
        )
        return PaperRuntimeResult(
            status="closed",
            trade_id=trade_id,
            reason_codes=("local_paper_close_recorded",),
            fill_price=exit_fill,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            slippage_cost=slippage_cost,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
        )
