from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.paper.ledger import PaperLedgerEntry, PaperLedgerError
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger


def _open(*, trade_id: str = "paper-001") -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="open",
        trade_id=trade_id,
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("100"),
        occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


def _close() -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="close",
        trade_id="paper-001",
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("110"),
        occurred_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
        entry_fee=Decimal("0.01"),
        exit_fee=Decimal("0.02"),
        slippage_cost=Decimal("0.02"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("0.97"),
    )


def test_sqlite_paper_ledger_persists_and_rehydrates_open_position(tmp_path: Path) -> None:
    path = tmp_path / "paper-ledger.sqlite3"
    storage = SqlitePaperLedger(path)
    storage.append(_open())

    rehydrated = SqlitePaperLedger(path).load()

    assert rehydrated.entries == (_open(),)
    assert rehydrated.open_positions() == (_open(),)


def test_sqlite_paper_ledger_preserves_close_history_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "paper-ledger.sqlite3"
    storage = SqlitePaperLedger(path)
    storage.append(_open())
    storage.append(_close())

    rehydrated = SqlitePaperLedger(path).load()

    assert rehydrated.entries == (_open(), _close())
    assert rehydrated.open_positions() == ()


def test_sqlite_paper_ledger_rejects_invalid_duplicate_open_without_persisting_it(
    tmp_path: Path,
) -> None:
    storage = SqlitePaperLedger(tmp_path / "paper-ledger.sqlite3")
    storage.append(_open())

    with pytest.raises(PaperLedgerError, match="duplicate open"):
        storage.append(_open(trade_id="paper-002"))

    assert storage.load().entries == (_open(),)
