from decimal import Decimal

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.contracts import PaperExecutionRequest
from autonomous_futures.paper.fills import simulate_paper_round_trip


def _request(**changes: object) -> PaperExecutionRequest:
    payload: dict[str, object] = {
        "candidate_id": "cand-scope-rsi-adx-001",
        "candidate_artifact_hash": "a" * 64,
        "qualified_symbols": ("BTCUSDT",),
        "symbol": "BTCUSDT",
        "side": "LONG",
        "mark_price": Decimal("100"),
        "quantity": Decimal("1"),
        "fee_rate": Decimal("0.001"),
        "slippage_bps": Decimal("10"),
    }
    payload.update(changes)
    return PaperExecutionRequest.model_validate(payload)


def test_paper_long_round_trip_uses_adverse_fills_and_both_fees() -> None:
    result = simulate_paper_round_trip(_request(), exit_mark_price=Decimal("110"))

    assert result.entry_fill_price == Decimal("100.100")
    assert result.exit_fill_price == Decimal("109.890")
    assert result.gross_pnl == Decimal("9.790")
    assert result.entry_fee == Decimal("0.100100")
    assert result.exit_fee == Decimal("0.109890")
    assert result.total_fees == Decimal("0.209990")
    assert result.slippage_cost == Decimal("0.210")
    assert result.net_pnl == Decimal("9.580010")
    assert result.paper_activation is False
    assert result.execution_authority is False
    assert result.exchange_access is False


def test_paper_short_round_trip_uses_adverse_fills_and_both_fees() -> None:
    result = simulate_paper_round_trip(_request(side="SHORT"), exit_mark_price=Decimal("90"))

    assert result.entry_fill_price == Decimal("99.900")
    assert result.exit_fill_price == Decimal("90.090")
    assert result.gross_pnl == Decimal("9.810")
    assert result.total_fees == Decimal("0.189990")
    assert result.slippage_cost == Decimal("0.190")
    assert result.net_pnl == Decimal("9.620010")


def test_paper_round_trip_rejects_non_positive_exit_mark_price() -> None:
    with pytest.raises(ValidationError):
        simulate_paper_round_trip(_request(), exit_mark_price=Decimal("0"))
