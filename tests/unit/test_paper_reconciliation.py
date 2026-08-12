from datetime import UTC, datetime
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedger, PaperLedgerEntry
from autonomous_futures.paper.reconciliation import reconcile_paper_positions


def _open(trade_id: str) -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="open",
        trade_id=trade_id,
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        symbol="BTCUSDT" if trade_id == "paper-001" else "ETHUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("100"),
        occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


def test_reconciliation_accepts_identical_runtime_and_ledger_open_trade_ids() -> None:
    result = reconcile_paper_positions(PaperLedger((_open("paper-001"),)), ("paper-001",))

    assert result.reconciled is True
    assert result.runtime_only_trade_ids == ()
    assert result.ledger_only_trade_ids == ()


def test_reconciliation_reports_runtime_and_ledger_drift_without_mutating_ledger() -> None:
    ledger = PaperLedger((_open("paper-001"),))

    result = reconcile_paper_positions(ledger, ("paper-002",))

    assert result.reconciled is False
    assert result.runtime_only_trade_ids == ("paper-002",)
    assert result.ledger_only_trade_ids == ("paper-001",)
    assert ledger.open_positions() == (_open("paper-001"),)


def test_reconciliation_rejects_duplicate_runtime_trade_ids() -> None:
    result = reconcile_paper_positions(
        PaperLedger((_open("paper-001"),)), ("paper-001", "paper-001")
    )

    assert result.reconciled is False
    assert result.runtime_only_trade_ids == ()
    assert result.ledger_only_trade_ids == ()
    assert result.reason_codes == ("runtime_duplicate_trade_id",)
