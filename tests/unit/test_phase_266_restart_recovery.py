"""Phase 266 bounded restart-recovery regressions."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from autonomous_futures.paper.ledger import PaperLedgerEntry, PaperLedgerError
from autonomous_futures.paper.live_engine import LivePaperEngine, PaperRestartRecoveryError
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger


def _open_entry(*, trade_id: str = "open-1", symbol: str = "BTCUSDT") -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="open",
        trade_id=trade_id,
        candidate_id="candidate",
        candidate_artifact_hash="a" * 64,
        symbol=symbol,
        side="LONG",
        quantity=Decimal("1"),
        fill_price=Decimal("100"),
        occurred_at=datetime(2026, 9, 7, 1, tzinfo=UTC),
        approval_id=f"approval-{trade_id}",
        entry_fee=Decimal("0.04"),
        slippage_cost=Decimal("0.02"),
    )


def test_restart_with_open_ledger_position_fails_closed_before_signals(tmp_path) -> None:
    path = tmp_path / "paper-ledger.sqlite3"
    ledger = SqlitePaperLedger(path)
    ledger.append(_open_entry())

    with pytest.raises(PaperRestartRecoveryError, match="protective state"):
        LivePaperEngine(
            symbols=("BTCUSDT",),
            ledger_db=path,
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )

    restored = ledger.load()
    assert len(restored.open_positions()) == 1
    assert restored.open_positions()[0].trade_id == "open-1"


def test_same_symbol_duplicate_open_remains_rejected(tmp_path) -> None:
    ledger = SqlitePaperLedger(tmp_path / "paper-ledger.sqlite3")
    ledger.append(_open_entry(trade_id="open-1"))

    with pytest.raises(PaperLedgerError, match="duplicate open"):
        ledger.append(_open_entry(trade_id="open-2"))


def test_restart_recovery_does_not_recreate_entry_fee_or_margin_state(tmp_path) -> None:
    path = tmp_path / "paper-ledger.sqlite3"
    ledger = SqlitePaperLedger(path)
    ledger.append(_open_entry())

    with pytest.raises(PaperRestartRecoveryError):
        LivePaperEngine(
            symbols=("BTCUSDT",),
            ledger_db=path,
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )

    restored = ledger.load().open_positions()[0]
    assert restored.entry_fee == Decimal("0.04")
    assert restored.slippage_cost == Decimal("0.02")
    assert len(ledger.load().entries) == 1
