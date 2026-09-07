"""Phase 265 accounting regression tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedgerEntry
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger


def _entry(event: str, trade_id: str, occurred_at: datetime, **values: str) -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event=event,
        trade_id=trade_id,
        candidate_id="candidate",
        candidate_artifact_hash="a" * 64,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("1"),
        fill_price=Decimal("100"),
        occurred_at=occurred_at,
        approval_id=f"approval-{event}-{trade_id}",
        entry_fee=Decimal(values["entry_fee"]) if "entry_fee" in values else None,
        exit_fee=Decimal(values["exit_fee"]) if "exit_fee" in values else None,
        slippage_cost=Decimal("0") if event == "open" else Decimal("0"),
        gross_pnl=Decimal(values["gross_pnl"]) if "gross_pnl" in values else None,
        net_pnl=Decimal(values["net_pnl"]) if "net_pnl" in values else None,
    )


def test_engine_restores_account_cash_from_persisted_ledger(tmp_path) -> None:
    ledger = SqlitePaperLedger(tmp_path / "paper-ledger.sqlite3")
    opened = datetime(2026, 9, 7, 1, tzinfo=UTC)
    ledger.append(_entry("open", "closed-1", opened, entry_fee="0.04"))
    ledger.append(
        _entry(
            "close",
            "closed-1",
            opened + timedelta(minutes=1),
            entry_fee="0.04",
            exit_fee="0.03",
            gross_pnl="1.50",
            net_pnl="1.43",
        )
    )

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    assert engine.account.cash == Decimal("101.43")
