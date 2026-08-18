from datetime import UTC, datetime
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedgerEntry
from autonomous_futures.paper.lifecycle import mark_paper_position
from autonomous_futures.paper.sqlite_lifecycle import SqlitePaperLifecycle


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


def _telemetry(mark: str):
    return mark_paper_position(
        _open(),
        mark_price=Decimal(mark),
        marked_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        previous_peak_pnl=Decimal("0"),
        take_profit_price=Decimal("120"),
    )


def test_sqlite_lifecycle_journal_rehydrates_marks_and_latest(tmp_path) -> None:
    path = tmp_path / "lifecycle.sqlite3"
    store = SqlitePaperLifecycle(path)
    first = _telemetry("101")
    second = _telemetry("102")
    store.append(first)
    store.append(second)

    reopened = SqlitePaperLifecycle(path)
    rows = reopened.read(
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        trade_id="paper-001",
    )

    assert rows == (first, second)
    assert (
        reopened.latest(
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            trade_id="paper-001",
        )
        == second
    )


def test_sqlite_lifecycle_absent_read_does_not_create_database(tmp_path) -> None:
    path = tmp_path / "absent.sqlite3"

    assert (
        SqlitePaperLifecycle(path).read(
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            trade_id="paper-001",
        )
        == ()
    )
    assert not path.exists()
