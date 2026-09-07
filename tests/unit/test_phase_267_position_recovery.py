"""Phase 267 durable active-position recovery contract."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from autonomous_futures.feed.models import TickerSnapshot
from autonomous_futures.paper.circuit_breakers import HardenedSharedMarginAccount
from autonomous_futures.paper.live_engine import LivePaperEngine, PaperRestartRecoveryError
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.research.creator_artifacts import read_creator_candidate_artifact


def _state() -> dict[str, object]:
    return {
        "trade_id": "trade-1",
        "candidate_id": "cand-abc",
        "candidate_artifact_hash": "a" * 64,
        "symbol": "BTCUSDT",
        "side": "LONG",
        "quantity": "0.1",
        "base_margin": "10",
        "leverage": "2",
        "watermark": "100",
        "peak_pnl": "0",
        "stop_price": "90",
        "target_price": "120",
        "trailing_atr_multiplier": "1",
        "current_atr": "5",
        "opened_at": datetime(2026, 9, 7, tzinfo=UTC).isoformat(),
        "trailing_stop_price": "90",
        "strategy_json": '{"strategy_id":"cand-abc"}',
    }


def test_position_state_round_trips_as_versioned_decimal_evidence(tmp_path) -> None:
    ledger = SqlitePaperLedger(tmp_path / "ledger.sqlite3")
    ledger.save_position_state(_state())

    restored = ledger.load_position_states()
    assert restored[0]["leverage"] == Decimal("2")
    assert restored[0]["stop_price"] == Decimal("90")
    assert restored[0]["state_version"] == 1


def test_position_state_missing_for_open_is_fail_closed(tmp_path) -> None:
    ledger = SqlitePaperLedger(tmp_path / "ledger.sqlite3")
    with pytest.raises(PaperRestartRecoveryError):
        ledger.require_recoverable_position_states(open_trade_ids={"trade-1"}, candidate_by_id={})


def test_position_state_orphan_is_fail_closed(tmp_path) -> None:
    ledger = SqlitePaperLedger(tmp_path / "ledger.sqlite3")
    ledger.save_position_state(_state())
    with pytest.raises(PaperRestartRecoveryError, match="orphan"):
        ledger.require_recoverable_position_states(open_trade_ids=set(), candidate_by_id={})


def test_open_update_restart_protective_close_and_second_restart(tmp_path) -> None:
    candidate = read_creator_candidate_artifact(
        __import__("pathlib").Path(
            "artifacts/research/phase252/candidates/"
            "cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json"
        )
    )
    paths = [tmp_path / name for name in ("ledger.sqlite3", "lifecycle.sqlite3", "obs.sqlite3")]
    kwargs = {
        "symbols": ("BTCUSDT",),
        "candidates": {"BTCUSDT": candidate},
        "ledger_db": paths[0],
        "lifecycle_db": paths[1],
        "observations_db": paths[2],
    }
    first = LivePaperEngine(**kwargs)
    first.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("100"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("100.1"),
        best_ask_qty=Decimal("2"),
        transaction_time=datetime(2026, 9, 7, tzinfo=UTC),
        event_time=datetime(2026, 9, 7, tzinfo=UTC),
    )
    opened = first.execute_open("BTCUSDT", 1, Decimal("0.75"), datetime(2026, 9, 7, tzinfo=UTC))
    assert opened is not None and opened.status == "opened"
    trade_id = next(iter(first.active_trades))
    first.active_trades[trade_id].watermark += Decimal("1")
    first._persist_position_state(first.active_trades[trade_id], candidate)

    injected_account = HardenedSharedMarginAccount()
    injected_account.cash = Decimal("77")
    injected = LivePaperEngine(account=injected_account, **kwargs)
    assert injected.account.cash == Decimal("77")
    assert injected.account.total_locked_margin() == first.active_trades[trade_id].base_margin

    second = LivePaperEngine(**kwargs)
    assert trade_id in second.active_trades
    assert second.account.total_locked_margin() == first.active_trades[trade_id].base_margin
    second.latest_tickers["BTCUSDT"] = first.latest_tickers["BTCUSDT"]
    closed = second.execute_close("BTCUSDT", "test", datetime(2026, 9, 7, 0, 0, 1, tzinfo=UTC))
    assert closed is not None and closed.status == "closed"

    third = LivePaperEngine(**kwargs)
    assert not third.active_trades
    assert len(third.runtime.ledger.load().entries) == 2
