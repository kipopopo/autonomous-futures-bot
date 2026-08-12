from datetime import UTC, datetime
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedger, PaperLedgerEntry
from autonomous_futures.paper.observation import observe_paper_ledger


def test_open_observation_uses_durable_entry_costs_as_complete_accounting() -> None:
    open_entry = PaperLedgerEntry(
        event="open",
        trade_id="paper-001",
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("100"),
        occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
        entry_fee=Decimal("0.01"),
        slippage_cost=Decimal("0.02"),
    )

    snapshot = observe_paper_ledger(
        PaperLedger((open_entry,)),
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        starting_equity=Decimal("100"),
        previous_peak_equity=Decimal("100"),
        mark_prices={"BTCUSDT": Decimal("110")},
        observed_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )

    assert snapshot.unrealized_pnl == Decimal("1")
    assert snapshot.equity == Decimal("100.99")
    assert snapshot.cumulative_fees == Decimal("0.01")
    assert snapshot.cumulative_slippage == Decimal("0.02")
    assert snapshot.accounting_complete is True
    assert snapshot.reason_codes == ("paper_observation_complete",)
