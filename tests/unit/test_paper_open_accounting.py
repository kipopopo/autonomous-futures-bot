from datetime import UTC, datetime
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedgerEntry


def test_paper_open_accepts_complete_entry_cost_accounting() -> None:
    entry = PaperLedgerEntry(
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

    assert entry.entry_fee == Decimal("0.01")
    assert entry.slippage_cost == Decimal("0.02")
