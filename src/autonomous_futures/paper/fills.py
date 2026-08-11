"""Paper-only deterministic fill calculations; no network or persistence."""

from decimal import Decimal
from typing import Literal

from pydantic import TypeAdapter, field_validator, model_validator

from ..domain.contracts import (
    DomainModel,
    PaperExecutionRequest,
    StrictNonNegativeDecimal,
    StrictPositiveDecimal,
)


class PaperRoundTripResult(DomainModel):
    candidate_id: str
    candidate_artifact_hash: str
    symbol: str
    side: Literal["LONG", "SHORT"]
    entry_mark_price: StrictPositiveDecimal
    exit_mark_price: StrictPositiveDecimal
    quantity: StrictPositiveDecimal
    entry_fill_price: StrictPositiveDecimal
    exit_fill_price: StrictPositiveDecimal
    entry_fee: StrictNonNegativeDecimal
    exit_fee: StrictNonNegativeDecimal
    total_fees: StrictNonNegativeDecimal
    slippage_cost: StrictNonNegativeDecimal
    gross_pnl: Decimal
    net_pnl: Decimal
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False

    @field_validator("gross_pnl", "net_pnl")
    @classmethod
    def pnl_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("paper P&L must be finite")
        return value

    @model_validator(mode="after")
    def accounting_is_reconciled(self) -> PaperRoundTripResult:
        if self.total_fees != self.entry_fee + self.exit_fee:
            raise ValueError("paper total fees must equal entry plus exit fees")
        if self.net_pnl != self.gross_pnl - self.total_fees:
            raise ValueError("paper net P&L must include both fees")
        return self


def simulate_paper_round_trip(
    request: PaperExecutionRequest, *, exit_mark_price: Decimal
) -> PaperRoundTripResult:
    """Calculate one explicit, non-authoritative paper round trip."""
    exit_mark = TypeAdapter(StrictPositiveDecimal).validate_python(exit_mark_price)
    slippage_rate = request.slippage_bps / Decimal("10000")
    if request.side == "LONG":
        entry_fill = request.mark_price * (Decimal("1") + slippage_rate)
        exit_fill = exit_mark * (Decimal("1") - slippage_rate)
        gross_pnl = (exit_fill - entry_fill) * request.quantity
    else:
        entry_fill = request.mark_price * (Decimal("1") - slippage_rate)
        exit_fill = exit_mark * (Decimal("1") + slippage_rate)
        gross_pnl = (entry_fill - exit_fill) * request.quantity
    entry_fee = entry_fill * request.quantity * request.fee_rate
    exit_fee = exit_fill * request.quantity * request.fee_rate
    total_fees = entry_fee + exit_fee
    slippage_cost = (
        abs(entry_fill - request.mark_price) + abs(exit_fill - exit_mark)
    ) * request.quantity
    return PaperRoundTripResult(
        candidate_id=request.candidate_id,
        candidate_artifact_hash=request.candidate_artifact_hash,
        symbol=request.symbol,
        side=request.side,
        entry_mark_price=request.mark_price,
        exit_mark_price=exit_mark,
        quantity=request.quantity,
        entry_fill_price=entry_fill,
        exit_fill_price=exit_fill,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        total_fees=total_fees,
        slippage_cost=slippage_cost,
        gross_pnl=gross_pnl,
        net_pnl=gross_pnl - total_fees,
    )
