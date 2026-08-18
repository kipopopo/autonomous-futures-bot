from datetime import UTC, datetime
from decimal import Decimal

import pytest

from autonomous_futures.paper.ledger import PaperLedgerEntry


def _open() -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="open",
        trade_id="paper-001",
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("100"),
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        entry_fee=Decimal("0.004"),
        slippage_cost=Decimal("0.002"),
    )


def test_lifecycle_mark_calculates_pnl_duration_peak_and_take_profit_readiness() -> None:
    from autonomous_futures.paper.lifecycle import mark_paper_position

    telemetry = mark_paper_position(
        _open(),
        mark_price=Decimal("110"),
        marked_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        previous_peak_pnl=Decimal("0.5"),
        stop_loss_price=Decimal("95"),
        take_profit_price=Decimal("108"),
    )

    assert telemetry.mark_price == Decimal("110")
    assert telemetry.mark_to_market_pnl == Decimal("1.0")
    assert telemetry.pnl_pct == Decimal("0.1")
    assert telemetry.peak_pnl == Decimal("1.0")
    assert telemetry.holding_seconds == 3600
    assert telemetry.stop_loss_hit is False
    assert telemetry.take_profit_hit is True
    assert telemetry.lifecycle_status == "exit_ready"
    assert telemetry.reason_codes == ("take_profit_hit",)
    assert telemetry.paper_activation is False
    assert telemetry.execution_authority is False
    assert telemetry.exchange_access is False


def test_lifecycle_mark_calculates_short_pnl_and_stop_loss_readiness() -> None:
    from autonomous_futures.paper.lifecycle import mark_paper_position

    entry = _open().model_copy(update={"side": "SHORT"})
    telemetry = mark_paper_position(
        entry,
        mark_price=Decimal("105"),
        marked_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        previous_peak_pnl=Decimal("1"),
        stop_loss_price=Decimal("104"),
        take_profit_price=Decimal("90"),
    )

    assert telemetry.mark_to_market_pnl == Decimal("-0.5")
    assert telemetry.pnl_pct == Decimal("-0.05")
    assert telemetry.peak_pnl == Decimal("1")
    assert telemetry.stop_loss_hit is True
    assert telemetry.take_profit_hit is False
    assert telemetry.lifecycle_status == "exit_ready"
    assert telemetry.reason_codes == ("stop_loss_hit",)


def test_lifecycle_mark_without_thresholds_remains_open() -> None:
    from autonomous_futures.paper.lifecycle import mark_paper_position

    telemetry = mark_paper_position(
        _open(),
        mark_price=Decimal("101"),
        marked_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        previous_peak_pnl=Decimal("0"),
    )

    assert telemetry.lifecycle_status == "open"
    assert telemetry.reason_codes == ("lifecycle_open",)


@pytest.mark.parametrize(
    ("side", "stop_loss", "take_profit"),
    (("LONG", Decimal("100"), Decimal("110")), ("SHORT", Decimal("90"), Decimal("95"))),
)
def test_lifecycle_mark_rejects_non_adverse_threshold_contract(
    side: str, stop_loss: Decimal, take_profit: Decimal
) -> None:
    from autonomous_futures.paper.lifecycle import mark_paper_position

    entry = _open().model_copy(update={"side": side})
    with pytest.raises(ValueError, match="stop loss"):
        mark_paper_position(
            entry,
            mark_price=Decimal("101"),
            marked_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
            previous_peak_pnl=Decimal("0"),
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
        )
