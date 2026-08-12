from datetime import UTC, datetime
from decimal import Decimal

import pytest

from autonomous_futures.paper.ledger import PaperLedger, PaperLedgerEntry, PaperLedgerError


def _open(*, trade_id: str = "paper-001") -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="open",
        trade_id=trade_id,
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("100.10"),
        occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


def _close(*, trade_id: str = "paper-001") -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="close",
        trade_id=trade_id,
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("110"),
        occurred_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )


def test_paper_ledger_rehydrates_open_position_from_injected_history() -> None:
    ledger = PaperLedger((_open(),))

    assert ledger.entries == (_open(),)
    assert ledger.open_positions() == (_open(),)


def test_paper_ledger_rejects_duplicate_open_for_candidate_and_symbol() -> None:
    ledger = PaperLedger((_open(),))

    with pytest.raises(PaperLedgerError, match="duplicate open"):
        ledger.append(_open(trade_id="paper-002"))


def test_paper_ledger_close_removes_rehydrated_open_position_without_rewriting_history() -> None:
    open_event = _open()
    close_event = _close()
    ledger = PaperLedger((open_event,))

    ledger.append(close_event)

    assert ledger.entries == (open_event, close_event)
    assert ledger.open_positions() == ()


def test_paper_ledger_rejects_close_without_matching_open() -> None:
    with pytest.raises(PaperLedgerError, match="missing open"):
        PaperLedger((_close(),))
