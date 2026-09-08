"""Phase 267 review-blocker regressions."""
# ruff: noqa: E501

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from test_phase_267_position_recovery import _state

from autonomous_futures.feed.models import TickerSnapshot
from autonomous_futures.paper.circuit_breakers import HardenedSharedMarginAccount
from autonomous_futures.paper.ledger import PaperRestartRecoveryError
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger


def test_load_rejects_nonfinite_optional_protection_values(tmp_path):
    for key in ("target_price", "trailing_stop_price"):
        ledger = SqlitePaperLedger(tmp_path / f"{key}.sqlite3")
        state = _state()
        state[key] = "NaN"
        with sqlite3.connect(ledger._path) as db:
            db.execute(
                "CREATE TABLE paper_position_state (trade_id TEXT PRIMARY KEY, state_version INTEGER NOT NULL, state_json TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO paper_position_state VALUES (?, ?, ?)",
                (state["trade_id"], 1, json.dumps(state)),
            )
        with pytest.raises(PaperRestartRecoveryError):
            ledger.load_position_states()


def test_load_rejects_missing_state_schema_key(tmp_path):
    ledger = SqlitePaperLedger(tmp_path / "ledger.sqlite3")
    state = _state()
    del state["stop_price"]
    with sqlite3.connect(ledger._path) as db:
        db.execute(
            "CREATE TABLE paper_position_state (trade_id TEXT PRIMARY KEY, state_version INTEGER NOT NULL, state_json TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO paper_position_state VALUES (?, ?, ?)", ("trade-1", 1, json.dumps(state))
        )
    with pytest.raises(PaperRestartRecoveryError, match="corrupt"):
        ledger.load_position_states()


def test_load_rejects_invalid_schema_and_sql_identity(tmp_path):
    ledger = SqlitePaperLedger(tmp_path / "ledger.sqlite3")
    ledger.save_position_state(_state())
    with sqlite3.connect(ledger._path) as db:
        db.execute(
            "UPDATE paper_position_state SET trade_id = ?, state_version = ?", ("tampered", 1)
        )
    with pytest.raises(PaperRestartRecoveryError):
        ledger.load_position_states()


def test_restore_rejects_tampered_ledger_artifact_hash_before_account_mutation(tmp_path):
    from pathlib import Path

    from autonomous_futures.research.creator_artifacts import read_creator_candidate_artifact

    candidate = read_creator_candidate_artifact(
        Path(
            "artifacts/research/phase252/candidates/cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json"
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
        best_ask_price=Decimal("100"),
        best_ask_qty=Decimal("2"),
        transaction_time=datetime(2026, 9, 7, tzinfo=UTC),
        event_time=datetime(2026, 9, 7, tzinfo=UTC),
    )
    # Construct a valid open using the existing engine path.
    first.execute_open("BTCUSDT", 1, Decimal("0.75"), datetime(2026, 9, 7, tzinfo=UTC))
    with sqlite3.connect(paths[0]) as db:
        db.execute("UPDATE paper_ledger_events SET candidate_artifact_hash = ?", ("b" * 64,))
    injected = HardenedSharedMarginAccount()
    injected.cash = Decimal("77")
    with pytest.raises(PaperRestartRecoveryError):
        LivePaperEngine(account=injected, **kwargs)
    assert injected.total_locked_margin() == Decimal("0")


def test_persistence_failure_latches_engine_and_blocks_future_signals(tmp_path, monkeypatch):
    from pathlib import Path

    from autonomous_futures.research.creator_artifacts import read_creator_candidate_artifact

    candidate = read_creator_candidate_artifact(
        Path(
            "artifacts/research/phase252/candidates/cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json"
        )
    )
    paths = [tmp_path / name for name in ("ledger.sqlite3", "lifecycle.sqlite3", "obs.sqlite3")]
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": candidate},
        ledger_db=paths[0],
        lifecycle_db=paths[1],
        observations_db=paths[2],
    )
    monkeypatch.setattr(
        engine.sqlite_ledger,
        "save_position_state",
        lambda state: (_ for _ in ()).throw(OSError("disk full")),
    )
    trade = type(
        "Trade",
        (),
        {
            "trade_id": "t",
            "candidate_id": candidate.candidate_id,
            "candidate_artifact_hash": candidate.artifact_hash,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "quantity": Decimal("1"),
            "base_margin": Decimal("1"),
            "leverage": Decimal("1"),
            "watermark": Decimal("100"),
            "peak_pnl": Decimal("0"),
            "stop_price": Decimal("90"),
            "target_price": Decimal("110"),
            "trailing_atr_multiplier": Decimal("1"),
            "current_atr": Decimal("1"),
            "opened_at": datetime(2026, 9, 7, tzinfo=UTC),
            "trailing_stop_price": Decimal("90"),
        },
    )()
    with pytest.raises(OSError):
        engine._persist_position_state(trade, candidate)
    assert (
        engine.execute_open("BTCUSDT", 1, Decimal("0.75"), datetime(2026, 9, 7, tzinfo=UTC)) is None
    )
    assert engine._persistence_failed is True


def test_failed_state_update_invalidates_stale_state_before_restart(tmp_path, monkeypatch):
    from pathlib import Path

    from autonomous_futures.feed.models import TickerSnapshot
    from autonomous_futures.research.creator_artifacts import read_creator_candidate_artifact

    candidate = read_creator_candidate_artifact(
        Path(
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
    engine = LivePaperEngine(**kwargs)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("100"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("100"),
        best_ask_qty=Decimal("2"),
        transaction_time=datetime(2026, 9, 7, tzinfo=UTC),
        event_time=datetime(2026, 9, 7, tzinfo=UTC),
    )
    opened = engine.execute_open("BTCUSDT", 1, Decimal("0.75"), datetime(2026, 9, 7, tzinfo=UTC))
    assert opened is not None and opened.status == "opened"
    trade = engine.active_trades["BTCUSDT"]
    original = engine.sqlite_ledger.save_position_state
    monkeypatch.setattr(
        engine.sqlite_ledger,
        "save_position_state",
        lambda state: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        engine._persist_position_state(trade, candidate)
    monkeypatch.setattr(engine.sqlite_ledger, "save_position_state", original)
    with pytest.raises(PaperRestartRecoveryError, match="dirty|protective state"):
        LivePaperEngine(**kwargs)


def test_restore_validates_every_state_before_mutating_injected_account(tmp_path):
    ledger = SqlitePaperLedger(tmp_path / "ledger.sqlite3")
    first, second = _state(), _state()
    second["trade_id"] = "trade-2"
    ledger.save_position_state(first)
    ledger.save_position_state(second)
    account = HardenedSharedMarginAccount()
    with pytest.raises(PaperRestartRecoveryError):
        ledger.require_recoverable_position_states({"trade-1", "trade-2"}, {})
    assert account.total_locked_margin() == Decimal("0")


def test_marker_write_failure_precedes_open_account_mutation(tmp_path, monkeypatch):
    candidate = __import__("pathlib").Path(
        "artifacts/research/phase252/candidates/"
        "cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json"
    )
    artifact = __import__(
        "autonomous_futures.research.creator_artifacts",
        fromlist=["read_creator_candidate_artifact"],
    ).read_creator_candidate_artifact(candidate)
    paths = [tmp_path / name for name in ("ledger.sqlite3", "lifecycle.sqlite3", "obs.sqlite3")]
    kwargs = {
        "symbols": ("BTCUSDT",),
        "candidates": {"BTCUSDT": artifact},
        "ledger_db": paths[0],
        "lifecycle_db": paths[1],
        "observations_db": paths[2],
    }
    engine = LivePaperEngine(**kwargs)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("100"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("100"),
        best_ask_qty=Decimal("2"),
        transaction_time=datetime(2026, 9, 7, tzinfo=UTC),
        event_time=datetime(2026, 9, 7, tzinfo=UTC),
    )
    monkeypatch.setattr(
        engine.sqlite_ledger,
        "begin_position_update",
        lambda trade_id, intent="mutable_state": (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        engine.execute_open("BTCUSDT", 1, Decimal("0.75"), datetime(2026, 9, 7, tzinfo=UTC))
    assert engine.account.total_locked_margin() == Decimal("0")
    assert not engine.active_trades
    assert engine._persistence_failed is True
    monkeypatch.setattr(engine.sqlite_ledger, "begin_position_update", lambda *args: None)
    assert (
        engine.execute_open("BTCUSDT", 1, Decimal("0.75"), datetime(2026, 9, 7, tzinfo=UTC)) is None
    )


def test_committed_dirty_marker_blocks_restart_after_update_failure(tmp_path, monkeypatch):
    candidate = __import__("pathlib").Path(
        "artifacts/research/phase252/candidates/"
        "cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json"
    )
    artifact = __import__(
        "autonomous_futures.research.creator_artifacts",
        fromlist=["read_creator_candidate_artifact"],
    ).read_creator_candidate_artifact(candidate)
    paths = [tmp_path / name for name in ("ledger.sqlite3", "lifecycle.sqlite3", "obs.sqlite3")]
    kwargs = {
        "symbols": ("BTCUSDT",),
        "candidates": {"BTCUSDT": artifact},
        "ledger_db": paths[0],
        "lifecycle_db": paths[1],
        "observations_db": paths[2],
    }
    engine = LivePaperEngine(**kwargs)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("100"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("100"),
        best_ask_qty=Decimal("2"),
        transaction_time=datetime(2026, 9, 7, tzinfo=UTC),
        event_time=datetime(2026, 9, 7, tzinfo=UTC),
    )
    assert (
        engine.execute_open("BTCUSDT", 1, Decimal("0.75"), datetime(2026, 9, 7, tzinfo=UTC)).status
        == "opened"
    )
    trade = engine.active_trades["BTCUSDT"]
    monkeypatch.setattr(
        engine.sqlite_ledger,
        "save_position_state",
        lambda state: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        engine._persist_position_state(trade, artifact)
    with pytest.raises(PaperRestartRecoveryError, match="dirty"):
        LivePaperEngine(**kwargs)


def test_marker_clear_failure_blocks_restart_after_complete_state_write(tmp_path, monkeypatch):
    candidate = __import__("pathlib").Path(
        "artifacts/research/phase252/candidates/"
        "cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json"
    )
    artifact = __import__(
        "autonomous_futures.research.creator_artifacts",
        fromlist=["read_creator_candidate_artifact"],
    ).read_creator_candidate_artifact(candidate)
    paths = [tmp_path / name for name in ("ledger.sqlite3", "lifecycle.sqlite3", "obs.sqlite3")]
    kwargs = {
        "symbols": ("BTCUSDT",),
        "candidates": {"BTCUSDT": artifact},
        "ledger_db": paths[0],
        "lifecycle_db": paths[1],
        "observations_db": paths[2],
    }
    engine = LivePaperEngine(**kwargs)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("100"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("100"),
        best_ask_qty=Decimal("2"),
        transaction_time=datetime(2026, 9, 7, tzinfo=UTC),
        event_time=datetime(2026, 9, 7, tzinfo=UTC),
    )
    assert (
        engine.execute_open("BTCUSDT", 1, Decimal("0.75"), datetime(2026, 9, 7, tzinfo=UTC)).status
        == "opened"
    )
    monkeypatch.setattr(
        engine.sqlite_ledger,
        "clear_position_update",
        lambda trade_id: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        engine._persist_position_state(engine.active_trades["BTCUSDT"], artifact)
    with pytest.raises(PaperRestartRecoveryError, match="dirty"):
        LivePaperEngine(**kwargs)
