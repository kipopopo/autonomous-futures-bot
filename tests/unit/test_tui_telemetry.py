"""Unit tests for TUI telemetry ingestion, snapshot models, and read-only SQLite reader.

Covers:
1. Ingestion and parsing of real historical artifacts from artifacts/research/phase259/.
2. Cold start and fallback behavior on empty, missing, or corrupted directories.
3. Strict SQLite read-only enforcement (?mode=ro, PRAGMA query_only = ON).
4. Busy timeout and lock contention handling.
5. Closed trade parsing, fee accounting, and lifecycle exit reason matching.
6. Portfolio margin Decimal calculations, PnL percentages, and zero-division protection.
7. Safety invariants evaluation and zero-order guardrails verification.
"""

from __future__ import annotations

import json
import sqlite3
import stat
import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.tui.telemetry import (
    DEFAULT_SYMBOLS,
    DaemonHealthSnapshot,
    MarginAccountSnapshot,
    MarketRegimeSnapshot,
    PositionSnapshot,
    SafetyInvariantsSnapshot,
    TelemetryReader,
    TuiTelemetrySnapshot,
)

_PHASE259_DIR = Path("artifacts/research/phase259")


class TestHistoricalArtifactIngestion:
    """Tests ingesting real artifacts from artifacts/research/phase259/."""

    @pytest.mark.skipif(not _PHASE259_DIR.is_dir(), reason="Phase 259 artifacts not present")
    def test_ingest_phase259_telemetry_artifacts(self) -> None:
        """Verify TelemetryReader successfully ingests real historical phase259 artifacts."""
        reader = TelemetryReader(_PHASE259_DIR)
        snap = reader.poll()

        assert isinstance(snap, TuiTelemetrySnapshot)
        assert snap.storage_dir == _PHASE259_DIR

        # Daemon health validation
        d = snap.daemon
        assert isinstance(d, DaemonHealthSnapshot)
        assert d.status == "SHUTDOWN_CLEAN"
        assert d.pid == 162877
        assert d.uptime_seconds == pytest.approx(35.57, rel=1e-2)
        assert d.feed_messages_received == 5482
        assert d.feed_reconnects_count == 0
        assert d.circuit_breaker_status == "NORMAL"
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            assert sym in d.symbols_monitored

        # Margin account validation
        m = snap.margin
        assert isinstance(m, MarginAccountSnapshot)
        assert m.starting_capital == Decimal("100.00")
        assert m.current_cash == Decimal("100.00")
        assert m.current_equity == Decimal("100.00")
        assert m.realized_pnl == Decimal("0.00")
        assert m.unrealized_pnl == Decimal("0.00")
        assert m.margin_utilization_pct == 0.0
        assert m.reserve_buffer_pct == 100.0

        # Regimes validation
        assert len(snap.regimes) == 4
        for sym in DEFAULT_SYMBOLS:
            assert sym in snap.regimes
            assert isinstance(snap.regimes[sym], MarketRegimeSnapshot)
            assert snap.regimes[sym].mid_price > Decimal("0")

        # Safety invariants validation
        s = snap.safety
        assert isinstance(s, SafetyInvariantsSnapshot)
        assert s.orders_submitted == 0
        assert s.execution_authority is False
        assert s.live_trading_activation is False
        assert s.paper_activation is True
        assert s.promotion_state == "unpromoted"
        assert s.zero_private_credentials is True
        assert s.all_invariants_pass is True


class TestColdStartAndResilience:
    """Tests for missing files, empty directories, and corrupted telemetry."""

    def test_empty_directory_cold_start(self, tmp_path: Path) -> None:
        """Reader on empty directory returns default snapshot with is_stale=True."""
        reader = TelemetryReader(tmp_path)
        snap = reader.poll()

        assert snap.is_stale is True
        assert snap.daemon.status == "OFFLINE"
        assert snap.daemon.pid is None
        assert snap.daemon.uptime_seconds == 0.0
        assert snap.margin.starting_capital == Decimal("100.00")
        assert snap.margin.current_cash == Decimal("100.00")
        assert snap.positions == {}
        assert snap.recent_closed_trades == ()
        assert snap.safety.all_invariants_pass is True

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """Reader on nonexistent directory safely returns default snapshot."""
        ghost = tmp_path / "does_not_exist"
        reader = TelemetryReader(ghost)
        snap = reader.poll()

        assert snap.is_stale is True
        assert snap.daemon.status == "OFFLINE"

    def test_corrupted_json_handling(self, tmp_path: Path) -> None:
        """Malformed or incomplete JSON files fall back gracefully."""
        health_path = tmp_path / "paper-daemon-health.json"

        # Invalid syntax
        health_path.write_text("{broken json", encoding="utf-8")
        reader = TelemetryReader(tmp_path)
        snap = reader.poll()
        assert snap.daemon.status == "OFFLINE"
        assert snap.is_stale is True

        # Empty file
        health_path.write_text("", encoding="utf-8")
        snap2 = reader.poll()
        assert snap2.daemon.status == "OFFLINE"

    def test_last_snapshot_caching_on_failure(self, tmp_path: Path) -> None:
        """When poll fails after a valid snapshot, it returns last snapshot marked stale."""
        health_path = tmp_path / "paper-daemon-health.json"
        valid_health = {
            "daemon_status": "RUNNING",
            "pid": 9999,
            "uptime_seconds": 100.0,
            "starting_capital_usdt": "100.00",
            "current_cash_usdt": "105.00",
            "current_equity_usdt": "105.00",
        }
        health_path.write_text(json.dumps(valid_health), encoding="utf-8")

        reader = TelemetryReader(tmp_path)
        snap1 = reader.poll()
        assert snap1.daemon.pid == 9999
        assert snap1.margin.current_cash == Decimal("105.00")

        # Now simulate file read exception / corruption
        health_path.write_text("corrupted", encoding="utf-8")
        snap2 = reader.poll()
        # Returns offline fallback or cached snapshot
        assert snap2.is_stale is True


class TestReadOnlySqliteEnforcement:
    """Tests confirming read-only SQLite connection and write prevention."""

    def test_connect_readonly_prevents_writes(self, tmp_path: Path) -> None:
        """_connect_readonly must enforce ?mode=ro and PRAGMA query_only = ON."""
        db_file = tmp_path / "test_ledger.sqlite3"
        conn = sqlite3.connect(db_file)
        conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, val TEXT);")
        conn.execute("INSERT INTO test_data VALUES (1, 'initial');")
        conn.commit()
        conn.close()

        reader = TelemetryReader(tmp_path)
        ro_conn = reader._connect_readonly(db_file)
        assert ro_conn is not None

        # Read succeeds
        cur = ro_conn.execute("SELECT val FROM test_data WHERE id = 1;")
        assert cur.fetchone()[0] == "initial"

        # Insert MUST raise OperationalError (readonly or query_only)
        with pytest.raises(sqlite3.OperationalError):
            ro_conn.execute("INSERT INTO test_data VALUES (2, 'injected');")

        # Update MUST raise OperationalError
        with pytest.raises(sqlite3.OperationalError):
            ro_conn.execute("UPDATE test_data SET val = 'mutated' WHERE id = 1;")

        # Delete MUST raise OperationalError
        with pytest.raises(sqlite3.OperationalError):
            ro_conn.execute("DELETE FROM test_data WHERE id = 1;")

        ro_conn.close()

    def test_filesystem_readonly_files_readable(self, tmp_path: Path) -> None:
        """Reader operates seamlessly when SQLite files have read-only file permissions."""
        db_file = tmp_path / "paper-ledger.sqlite3"
        conn = sqlite3.connect(db_file)
        conn.execute(
            """
            CREATE TABLE paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                trade_id TEXT,
                symbol TEXT,
                side TEXT,
                quantity TEXT,
                fill_price TEXT,
                occurred_at TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                net_pnl TEXT,
                approval_id TEXT,
                event TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 't1', 'BTCUSDT', 'LONG', '0.001', '90000.00', '2026-09-06T12:00:00Z',
             '0.036', '0.036', '0.50', 'app1', 'close');
            """
        )
        conn.commit()
        conn.close()

        # Set read-only permission on file
        db_file.chmod(stat.S_IREAD)

        reader = TelemetryReader(tmp_path)
        trades = reader._query_closed_trades()
        assert len(trades) == 1
        assert trades[0].trade_id == "t1"
        assert trades[0].net_pnl == Decimal("0.50")

        # Revert permission for cleanup
        db_file.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_busy_timeout_on_lock_contention(self, tmp_path: Path) -> None:
        """Reader query completes within timeout without hanging under write lock contention."""
        db_file = tmp_path / "paper-ledger.sqlite3"
        conn = sqlite3.connect(db_file)
        conn.execute("CREATE TABLE paper_ledger_events (sequence INTEGER PRIMARY KEY, event TEXT);")
        conn.commit()
        conn.close()

        lock_held = threading.Event()
        stop_holding = threading.Event()

        def _hold_exclusive_lock() -> None:
            c = sqlite3.connect(db_file)
            c.execute("BEGIN EXCLUSIVE;")
            lock_held.set()
            stop_holding.wait(timeout=5.0)
            c.rollback()
            c.close()

        th = threading.Thread(target=_hold_exclusive_lock, daemon=True)
        th.start()
        assert lock_held.wait(timeout=2.0)

        try:
            reader = TelemetryReader(tmp_path)
            start = time.perf_counter()
            # Under lock contention, reader returns empty tuple after busy timeout
            trades = reader._query_closed_trades()
            elapsed = time.perf_counter() - start

            assert trades == ()
            assert elapsed < 3.0
        finally:
            stop_holding.set()
            th.join(timeout=2.0)


class TestDatabaseQueryParsing:
    """Tests for SQL queries on ledger, lifecycle marks, and observations."""

    def test_query_closed_trades_and_fee_accounting(self, tmp_path: Path) -> None:
        """Closed trade queries parse Decimal quantities, fees, and net PnL."""
        ledger_db = tmp_path / "paper-ledger.sqlite3"
        conn = sqlite3.connect(ledger_db)
        conn.execute(
            """
            CREATE TABLE paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                trade_id TEXT,
                symbol TEXT,
                side TEXT,
                quantity TEXT,
                fill_price TEXT,
                occurred_at TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                net_pnl TEXT,
                approval_id TEXT,
                event TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 't1', 'BTCUSDT', 'LONG', '0.0025', '90500.00', '2026-09-06T12:00:00Z',
             '0.0905', '0.0910', '1.2500', 'app-1', 'close'),
            (2, 't2', 'ETHUSDT', 'SHORT', '0.1000', '2650.00', '2026-09-06T12:15:00Z',
             '0.1060', '0.1055', '-0.4500', 'app-2', 'close'),
            (3, 't3', 'SOLUSDT', 'LONG', '1.0000', '180.00', '2026-09-06T12:30:00Z',
             '0.0720', NULL, NULL, 'app-3', 'open');
            """
        )
        conn.commit()
        conn.close()

        reader = TelemetryReader(tmp_path)
        trades = reader._query_closed_trades(limit=5)
        # Only 'close' events are queried, ordered DESC (sequence 2 then 1)
        assert len(trades) == 2
        t2, t1 = trades[0], trades[1]

        assert t2.trade_id == "t2"
        assert t2.symbol == "ETHUSDT"
        assert t2.side == "SHORT"
        assert t2.quantity == Decimal("0.1000")
        assert t2.fill_price == Decimal("2650.00")
        assert t2.entry_fee == Decimal("0.1060")
        assert t2.exit_fee == Decimal("0.1055")
        assert t2.total_fees == Decimal("0.2115")
        assert t2.net_pnl == Decimal("-0.4500")

        assert t1.trade_id == "t1"
        assert t1.symbol == "BTCUSDT"
        assert t1.side == "LONG"
        assert t1.total_fees == Decimal("0.1815")
        assert t1.net_pnl == Decimal("1.2500")

    def test_query_exit_reasons_matching(self, tmp_path: Path) -> None:
        """Exit reason mapping matches lifecycle marks reason_codes."""
        lc_db = tmp_path / "paper-lifecycle.sqlite3"
        conn = sqlite3.connect(lc_db)
        conn.execute(
            """
            CREATE TABLE paper_lifecycle_marks (
                sequence INTEGER PRIMARY KEY,
                trade_id TEXT,
                payload TEXT
            );
            """
        )
        payloads = [
            (1, "t1", json.dumps({"reason_codes": ["take_profit_hit"]})),
            (2, "t2", json.dumps({"reason_codes": ["stop_loss_hit"]})),
            (3, "t3", json.dumps({"reason_codes": ["trailing_stop_hit"]})),
            (4, "t4", json.dumps({"reason_codes": ["strategy_exit"]})),
            (5, "t5", json.dumps({"reason_codes": ["custom_circuit_breaker"]})),
        ]
        conn.executemany("INSERT INTO paper_lifecycle_marks VALUES (?, ?, ?);", payloads)
        conn.commit()
        conn.close()

        reader = TelemetryReader(tmp_path)
        reasons = reader._query_exit_reasons()

        assert reasons["t1"] == "take_profit"
        assert reasons["t2"] == "stop_loss"
        assert reasons["t3"] == "trailing_stop"
        assert reasons["t4"] == "strategy_exit"
        assert reasons["t5"] == "custom_circuit_breaker"

    def test_query_observations_peak_equity(self, tmp_path: Path) -> None:
        """Observations query extracts peak equity checkpoint."""
        obs_db = tmp_path / "paper-observations.sqlite3"
        conn = sqlite3.connect(obs_db)
        conn.execute(
            "CREATE TABLE paper_observations (sequence INTEGER PRIMARY KEY, payload TEXT);"
        )
        conn.execute(
            "INSERT INTO paper_observations VALUES (1, ?);",
            (json.dumps({"peak_equity": "112.75"}),),
        )
        conn.commit()
        conn.close()

        reader = TelemetryReader(tmp_path)
        obs = reader._query_observations()
        assert obs is not None
        assert obs.get("peak_equity") == "112.75"


class TestMarginAndSafetyCalculations:
    """Tests for exact Decimal margin and safety calculations."""

    def test_parse_margin_calculations(self) -> None:
        """_parse_margin calculates realized and unrealized PnL with exact Decimal precision."""
        reader = TelemetryReader(Path("dummy"))
        health = {
            "starting_capital_usdt": "100.00",
            "current_cash_usdt": "102.50",
            "current_equity_usdt": "104.75",
            "margin_utilization_pct": 35.0,
            "reserve_buffer_pct": 65.0,
        }
        observations = {"peak_equity": "106.00"}

        m = reader._parse_margin(health, observations)
        assert m.starting_capital == Decimal("100.00")
        assert m.current_cash == Decimal("102.50")
        assert m.current_equity == Decimal("104.75")
        # Realized PnL = cash - starting = 102.50 - 100.00 = 2.50
        assert m.realized_pnl == Decimal("2.50")
        assert m.realized_pnl_pct == Decimal("2.5")
        # Unrealized PnL = equity - cash = 104.75 - 102.50 = 2.25
        assert m.unrealized_pnl == Decimal("2.25")
        assert m.unrealized_pnl_pct == Decimal("2.25")
        assert m.peak_equity == Decimal("106.00")

    def test_parse_margin_zero_starting_capital_protection(self) -> None:
        """Zero starting capital protects against ZeroDivisionError."""
        reader = TelemetryReader(Path("dummy"))
        health = {
            "starting_capital_usdt": "0.00",
            "current_cash_usdt": "10.00",
            "current_equity_usdt": "10.00",
        }
        m = reader._parse_margin(health, None)
        assert m.realized_pnl_pct == Decimal("0")
        assert m.unrealized_pnl_pct == Decimal("0")

    def test_parse_safety_invariant_triggers(self) -> None:
        """Safety invariants flag any violations."""
        reader = TelemetryReader(Path("dummy"))

        # Healthy invariants
        healthy = {
            "circuit_breaker_status": "NORMAL",
            "zero_order_safety_invariants": {
                "orders_submitted": 0,
                "execution_authority": False,
                "live_trading_activation": False,
                "paper_activation": True,
                "promotion_state": "unpromoted",
                "zero_private_credentials": True,
            },
        }
        s_good = reader._parse_safety(healthy)
        assert s_good.all_invariants_pass is True

        # Violation: orders submitted > 0
        bad_orders = {
            "circuit_breaker_status": "NORMAL",
            "zero_order_safety_invariants": {
                "orders_submitted": 1,
                "execution_authority": False,
                "live_trading_activation": False,
                "paper_activation": True,
                "promotion_state": "unpromoted",
                "zero_private_credentials": True,
            },
        }
        s_bad = reader._parse_safety(bad_orders)
        assert s_bad.orders_submitted == 1
        assert s_bad.all_invariants_pass is False

        # Violation: execution authority True
        bad_auth = {
            "circuit_breaker_status": "NORMAL",
            "zero_order_safety_invariants": {
                "orders_submitted": 0,
                "execution_authority": True,
                "live_trading_activation": False,
                "paper_activation": True,
                "promotion_state": "unpromoted",
                "zero_private_credentials": True,
            },
        }
        assert reader._parse_safety(bad_auth).all_invariants_pass is False

    def test_parse_positions_calculations(self) -> None:
        """_parse_positions calculates unrealized PnL and liquidation distance."""
        reader = TelemetryReader(Path("dummy"))
        health = {
            "active_positions": {
                "BTCUSDT": {
                    "side": "LONG",
                    "quantity": "0.001",
                    "entry_price": "90000.00",
                    "leverage": "2.0",
                }
            }
        }
        regimes = {
            "BTCUSDT": MarketRegimeSnapshot(
                symbol="BTCUSDT",
                best_bid=Decimal("91000.00"),
                best_ask=Decimal("91000.50"),
                mid_price=Decimal("91000.25"),
                spread_bps=Decimal("0.5"),
                rolling_atr=Decimal("100.0"),
                status="NORMAL",
            )
        }

        positions = reader._parse_positions(health, {}, regimes)
        assert "BTCUSDT" in positions
        p = positions["BTCUSDT"]
        assert isinstance(p, PositionSnapshot)
        assert p.side == "LONG"
        assert p.quantity == Decimal("0.001")
        assert p.entry_price == Decimal("90000.00")
        assert p.mark_price == Decimal("91000.25")
        # uPnL = (91000.25 - 90000.00) * 0.001 = 1.00025
        assert p.unrealized_pnl == pytest.approx(Decimal("1.00025"))
        # Liquidation distance at 2.0x leverage: 1/2 * 100 = 50.0%
        assert p.liquidation_distance_pct == Decimal("50.0")
