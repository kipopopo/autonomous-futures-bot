"""Autonomous Futures Bot - Phase 317 Milestone 4 Iteration 2 Adversarial Challenge Suite.

File: tests/unit/test_phase_317_m4_it2_adversarial_challenge.py
Author: challenger_m4_it2_2

Empirically probes:
1. Concurrency Safety:
   - Stress-test concurrent queue access: 10 concurrent threads (5 enqueuers, 5 drainers)
     enqueuing 500 autopsies and calling drain_pending_autopsies simultaneously.
     Verifies 0 deadlocks, 0 race conditions, and exact accounting of all 500 records in SQLite.
   - Multi-thread connection sharing: 8 concurrent threads executing drain_pending_autopsies
     over the cached SQLite connection in WAL mode with 0 threading exceptions.
2. Error Resilience & FIFO Recovery:
   - Synthetic SQLite operational error injection (e.g. disk I/O error, locked database).
     Verifies failed batch is restored to _pending_autopsies in exact FIFO order
     without loss or duplicates.
   - Cascading multi-round SQLite failure recovery preserving strict chronological ordering.
   - Read-only filesystem operational error recovery.
3. Solvency Ledger & SQLite Table Consistency:
   - Double-entry solvency balance invariant (|drift| < 10^-15 USDT) across trade lifecycles.
   - 1:1 record count verification between drained autopsies, ict_trade_autopsies,
     and ict_candidate_registry.
   - Repeated autopsies for identical candidate updating health tier without duplicating entries.
4. Trader Cycle Timeout Budget Enforcement:
   - Disk I/O stall simulation verifying adaptive 5.0ms timeout bounds cycle latency < 15.0ms.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.continuous_trader import ContinuousSelfDrivingTrader
from autonomous_futures.execution.self_driving import SelfDrivingTradingEngine
from autonomous_futures.feed.auto_evolution import IctAutopsyMetrics
from autonomous_futures.feed.kline_sequencer import (
    ACTIVE_PAIRS,
    ACTIVE_TIMEFRAMES,
)
from autonomous_futures.strategy.ict_mmxm import Candle
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle as MacroCandle,
)

# =============================================================================
# Helper Fixtures & Data Generators
# =============================================================================


def make_autopsy_payload(
    trade_id: str,
    symbol: str = "SOLUSDT",
    candidate_id: str | None = None,
    side: str = "BUY",
    entry_price: float = 100.0,
    exit_price: float = 102.5,
    fill_qty: float = 0.05,
    timestamp_ms: int = 1700000000000,
) -> dict[str, Any]:
    """Generates a raw autopsy dictionary matching SelfDrivingTradingEngine ingress."""
    return {
        "trade_id": trade_id,
        "candidate_id": candidate_id or f"cand-{symbol.lower()}-ict-001",
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "fill_qty": fill_qty,
        "optimal_price": entry_price,
        "fvg_boundary_price": entry_price,
        "lowest_price_during_trade": min(entry_price, exit_price) - 0.5,
        "highest_price_during_trade": max(entry_price, exit_price) + 0.5,
        "timestamp_ms": timestamp_ms,
    }


# =============================================================================
# Challenge 1: Concurrency Safety & Multi-Thread Queue Access
# =============================================================================


class TestConcurrentAutopsyQueueSafety:
    """Stress-tests thread safety, lock disjointness, and race-free queue operations."""

    def test_concurrent_enqueue_and_drain_stress_zero_deadlocks(self, tmp_path: Path) -> None:
        """Runs 10 concurrent threads (5 enqueuers, 5 drainers) executing 500 autopsies.

        Verifies:
        1. 0 deadlocks: all threads finish cleanly within strict timeout.
        2. 0 race conditions: total items drained across all drain calls equals exactly 500.
        3. Exact accounting: SQLite table `ict_trade_autopsies` contains all 500 distinct records.
        """
        engine = SelfDrivingTradingEngine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        total_enqueuers = 5
        items_per_enqueuer = 100
        expected_total = total_enqueuers * items_per_enqueuer

        all_enqueued_ids: set[str] = set()
        enqueued_lock = threading.Lock()

        drain_results: list[IctAutopsyMetrics] = []
        drain_lock = threading.Lock()

        stop_drainers = threading.Event()
        barrier = threading.Barrier(total_enqueuers + 5)

        def enqueuer_worker(worker_idx: int) -> None:
            barrier.wait()
            for i in range(items_per_enqueuer):
                trade_id = f"trd-conc-{worker_idx}-{i:04d}"
                sym = ACTIVE_PAIRS[(worker_idx * items_per_enqueuer + i) % len(ACTIVE_PAIRS)]
                payload = make_autopsy_payload(
                    trade_id=trade_id,
                    symbol=sym,
                    timestamp_ms=1700000000000 + (worker_idx * 1000) + i,
                )
                with enqueued_lock:
                    all_enqueued_ids.add(trade_id)
                engine.enqueue_ict_autopsy(payload)
                # Jitter to encourage thread interleaving
                if i % 10 == 0:
                    time.sleep(0.0001)

        def drainer_worker() -> None:
            barrier.wait()
            while not stop_drainers.is_set():
                drained = engine.drain_pending_autopsies()
                if drained:
                    with drain_lock:
                        drain_results.extend(drained)
                time.sleep(0.0002)
            # Final drain pass for this worker
            drained = engine.drain_pending_autopsies()
            if drained:
                with drain_lock:
                    drain_results.extend(drained)

        threads: list[threading.Thread] = []
        for w_idx in range(total_enqueuers):
            t = threading.Thread(target=enqueuer_worker, args=(w_idx,))
            threads.append(t)
            t.start()

        for _ in range(5):
            t = threading.Thread(target=drainer_worker)
            threads.append(t)
            t.start()

        # Wait for all enqueuers to complete (max 10s budget)
        for t in threads[:total_enqueuers]:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Enqueuer thread deadlocked!"

        # Allow drainers to finish remaining queue
        stop_drainers.set()
        for t in threads[total_enqueuers:]:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Drainer thread deadlocked!"

        # Final cleanup drain
        final_drained = engine.drain_pending_autopsies()
        with drain_lock:
            drain_results.extend(final_drained)

        # 1. Verify queue is fully drained
        assert not engine.has_pending_autopsies()
        with engine._autopsy_lock:
            assert len(engine._pending_autopsies) == 0

        # 2. Verify drained count equals expected count
        drained_ids = {m.trade_id for m in drain_results}
        assert len(drain_results) == expected_total, (
            f"Expected {expected_total} drained items, but got {len(drain_results)}"
        )
        assert len(drained_ids) == expected_total, "Duplicate trade_ids drained!"
        assert drained_ids == all_enqueued_ids, "Mismatch between enqueued and drained trade_ids!"

        # 3. Verify SQLite persistence exact accounting
        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        count = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT trade_id FROM ict_trade_autopsies")
        db_trade_ids = {row[0] for row in cur.fetchall()}
        conn.close()

        assert count == expected_total, (
            f"Expected {expected_total} records in ict_trade_autopsies, found {count}"
        )
        assert db_trade_ids == all_enqueued_ids, "SQLite records do not match enqueued set!"

        engine.close_telemetry_db()

    def test_concurrent_multi_thread_db_connection_sharing(self, tmp_path: Path) -> None:
        """Verifies that 8 concurrent threads executing drain_pending_autopsies over

        the cached SQLite connection in WAL mode execute with 0 threading exceptions.
        """
        engine = SelfDrivingTradingEngine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        # Pre-enqueue 80 autopsies
        for i in range(80):
            sym = ACTIVE_PAIRS[i % len(ACTIVE_PAIRS)]
            engine.enqueue_ict_autopsy(
                make_autopsy_payload(
                    trade_id=f"trd-share-{i:03d}",
                    symbol=sym,
                    timestamp_ms=1700000000000 + i,
                )
            )

        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def worker(idx: int) -> None:
            try:
                barrier.wait()
                for _ in range(10):
                    engine.drain_pending_autopsies()
                    time.sleep(0.0005)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Threading errors occurred: {errors}"

        # Verify all 80 records exist in SQLite
        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 80

        engine.close_telemetry_db()


# =============================================================================
# Challenge 2: Error Resilience & FIFO Queue Recovery
# =============================================================================


class TestErrorResilienceAndFifoRecovery:
    """Stress-tests fail-safe recovery when SQLite persistence operations fail."""

    def test_synthetic_sqlite_failure_restores_exact_fifo_order(self, tmp_path: Path) -> None:
        """Injects synthetic SQLite OperationalError during drain and verifies:

        1. Non-fatal handling: no unhandled exceptions crash the caller.
        2. The failed batch is restored to `_pending_autopsies` in exact FIFO order.
        3. When new items arrive while failed batch is queued, the failed batch precedes
           the new items (exact chronological preservation).
        4. Once SQLite is restored, all records persist cleanly in correct order.
        """
        engine = SelfDrivingTradingEngine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        # Enqueue Batch 1: 5 items
        batch_1_ids = [f"trd-b1-{i:03d}" for i in range(5)]
        for tid in batch_1_ids:
            engine.enqueue_ict_autopsy(make_autopsy_payload(trade_id=tid))

        # Monkeypatch SQLite cursor.executemany to simulate disk I/O / lock failure
        class FailingCursor:
            def executemany(self, *args: Any, **kwargs: Any) -> Any:
                raise sqlite3.OperationalError("synthetic disk I/O error: disk full")

            def execute(self, *args: Any, **kwargs: Any) -> Any:
                raise sqlite3.OperationalError("synthetic disk I/O error: disk full")

            def close(self) -> None:
                pass

        class FailingConnection:
            def cursor(self) -> FailingCursor:
                return FailingCursor()

            def commit(self) -> None:
                pass

        # Trigger drain with failure injection
        with patch.object(engine, "_get_telemetry_db_conn", return_value=FailingConnection()):
            # Drain must not raise unhandled exception
            engine.drain_pending_autopsies()

        # 1. Assert failed items restored to _pending_autopsies
        assert engine.has_pending_autopsies()
        with engine._autopsy_lock:
            current_queue_ids = [
                item["trade_id"] if isinstance(item, dict) else item.trade_id
                for item in engine._pending_autopsies
            ]
        assert current_queue_ids == batch_1_ids, (
            f"FIFO order violated upon failure restoration! "
            f"Expected {batch_1_ids}, got {current_queue_ids}"
        )

        # Enqueue Batch 2: 3 items while Batch 1 is still in queue
        batch_2_ids = [f"trd-b2-{i:03d}" for i in range(3)]
        for tid in batch_2_ids:
            engine.enqueue_ict_autopsy(make_autopsy_payload(trade_id=tid))

        # Verify combined queue order is strictly Batch 1 followed by Batch 2
        expected_combined_ids = batch_1_ids + batch_2_ids
        with engine._autopsy_lock:
            combined_queue_ids = [
                item["trade_id"] if isinstance(item, dict) else item.trade_id
                for item in engine._pending_autopsies
            ]
        assert combined_queue_ids == expected_combined_ids, (
            f"FIFO sequencing violated! Expected {expected_combined_ids}, got {combined_queue_ids}"
        )

        # Restore normal DB operations and drain
        drained_final = engine.drain_pending_autopsies()
        assert len(drained_final) == len(expected_combined_ids)
        assert [m.trade_id for m in drained_final] == expected_combined_ids

        # Verify SQLite has exactly 8 records
        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        count = cur.fetchone()[0]
        cur.execute("SELECT trade_id FROM ict_trade_autopsies ORDER BY timestamp_ms ASC")
        persisted_ids = [r[0] for r in cur.fetchall()]
        conn.close()

        assert count == 8
        assert set(persisted_ids) == set(expected_combined_ids)
        assert not engine.has_pending_autopsies()

        engine.close_telemetry_db()

    def test_multi_round_cascading_sqlite_failures_preserves_strict_fifo(
        self, tmp_path: Path
    ) -> None:
        """Simulates 3 consecutive failed drain cycles with interleaved enqueues,

        verifying that recursive extendleft(reversed(...)) never corrupts order
        or duplicates records.
        """
        engine = SelfDrivingTradingEngine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        class FailingCursor:
            def executemany(self, *args: Any, **kwargs: Any) -> Any:
                raise sqlite3.OperationalError("database is locked")

            def execute(self, *args: Any, **kwargs: Any) -> Any:
                raise sqlite3.OperationalError("database is locked")

            def close(self) -> None:
                pass

        class FailingConnection:
            def cursor(self) -> FailingCursor:
                return FailingCursor()

            def commit(self) -> None:
                pass

        all_expected_ids: list[str] = []

        # Round 1: Enqueue [R1-0, R1-1], fail drain
        r1 = ["trd-r1-0", "trd-r1-1"]
        all_expected_ids.extend(r1)
        for tid in r1:
            engine.enqueue_ict_autopsy(make_autopsy_payload(trade_id=tid))

        with patch.object(engine, "_get_telemetry_db_conn", return_value=FailingConnection()):
            engine.drain_pending_autopsies()

        # Round 2: Enqueue [R2-0, R2-1], fail drain
        r2 = ["trd-r2-0", "trd-r2-1"]
        all_expected_ids.extend(r2)
        for tid in r2:
            engine.enqueue_ict_autopsy(make_autopsy_payload(trade_id=tid))

        with patch.object(engine, "_get_telemetry_db_conn", return_value=FailingConnection()):
            engine.drain_pending_autopsies()

        # Round 3: Enqueue [R3-0, R3-1], fail drain
        r3 = ["trd-r3-0", "trd-r3-1"]
        all_expected_ids.extend(r3)
        for tid in r3:
            engine.enqueue_ict_autopsy(make_autopsy_payload(trade_id=tid))

        with patch.object(engine, "_get_telemetry_db_conn", return_value=FailingConnection()):
            engine.drain_pending_autopsies()

        # Check queue has all 6 items in exact order
        with engine._autopsy_lock:
            current_ids = [
                item["trade_id"] if isinstance(item, dict) else item.trade_id
                for item in engine._pending_autopsies
            ]
        assert current_ids == all_expected_ids, (
            f"Multi-round FIFO recovery failed! Expected {all_expected_ids}, got {current_ids}"
        )

        # Heal DB and drain all
        drained = engine.drain_pending_autopsies()
        assert len(drained) == len(all_expected_ids)
        assert [m.trade_id for m in drained] == all_expected_ids

        # Verify SQLite has all 6
        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 6

        engine.close_telemetry_db()

    def test_read_only_filesystem_operational_error_recovery(self, tmp_path: Path) -> None:
        """Simulates read-only database error and verifies graceful catch,

        FIFO restoration, and subsequent write upon permission restoration.
        """
        engine = SelfDrivingTradingEngine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        # Close existing cached handle
        engine.close_telemetry_db()

        # Make database file read-only
        db_file = engine.db_path
        os.chmod(db_file, stat.S_IREAD)

        # Enqueue 3 items
        for i in range(3):
            engine.enqueue_ict_autopsy(make_autopsy_payload(trade_id=f"trd-ro-{i}"))

        # Trigger drain — read-only filesystem should raise OperationalError internally
        engine.drain_pending_autopsies()

        # Verify items were restored to queue
        assert engine.has_pending_autopsies()
        with engine._autopsy_lock:
            assert len(engine._pending_autopsies) == 3

        # Restore write permissions and cached handle
        engine.close_telemetry_db()
        os.chmod(db_file, stat.S_IWRITE | stat.S_IREAD)

        # Drain should now succeed
        drained = engine.drain_pending_autopsies()
        assert len(drained) == 3

        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 3

        engine.close_telemetry_db()


# =============================================================================
# Challenge 3: Double-Entry Solvency Ledger & Record Count Consistency
# =============================================================================


class TestSolvencyLedgerAndRecordCountConsistency:
    """Verifies 1:1 record count consistency and strict mathematical zero balance drift."""

    def test_solvency_ledger_zero_drift_invariant_across_lifecycles(self, tmp_path: Path) -> None:
        """Validates that Cash + Allocated Margin + Unrealized PnL == Starting Equity + Realized PnL

        strictly preserves |drift| < 10^-15 USDT across simulated fills, mark-to-market updates,
        and position closures.
        """
        engine = SelfDrivingTradingEngine(
            storage_dir=tmp_path,
            starting_capital_usdt=Decimal("100.00"),
        )
        engine.perform_preflight_checks()

        # Initial baseline check
        snap0 = engine.ledger.get_snapshot()
        assert snap0.zero_balance_drift
        assert abs(snap0.drift) < 1e-15
        assert snap0.cash == 100.0
        assert snap0.total_equity == 100.0

        # 1. Simulate entry fill on SOLUSDT (BUY 0.05 SOL @ 100.00 = 5.00 notional)
        cand = engine.candidates["SOLUSDT"]
        cand.position_qty = Decimal("0.05")
        cand.entry_price = Decimal("100.00")
        cand.allocated_exposure_usdt = Decimal("5.00")

        engine.ledger.record_fill(
            symbol="SOLUSDT",
            side="BUY",
            qty=0.05,
            price=100.00,
            fee=0.001,  # 0.02% maker fee on 5 USDT = 0.001 USDT
            realized_pnl=0.0,
        )

        snap1 = engine.ledger.get_snapshot()
        assert snap1.zero_balance_drift, f"Drift violated on entry fill: {snap1.drift}"
        assert abs(snap1.drift) < 1e-15
        assert snap1.allocated_margin == 5.00
        assert snap1.cash == pytest.approx(94.999, rel=1e-9)

        # 2. Mark-to-market price appreciation: SOL price moves to 102.50 (+0.125 USDT UPnL)
        engine.ledger.unrealized_pnl = Decimal("0.125")
        snap2 = engine.ledger.get_snapshot()
        assert snap2.zero_balance_drift, f"Drift violated on mark-to-market: {snap2.drift}"
        assert abs(snap2.drift) < 1e-15
        assert snap2.total_equity == pytest.approx(100.124, rel=1e-9)

        # 3. Exit position at Take Profit (102.50)
        engine.ledger.unrealized_pnl = Decimal("0.0")
        engine.ledger.record_fill(
            symbol="SOLUSDT",
            side="SELL",
            qty=0.05,
            price=102.50,
            fee=0.001,
            realized_pnl=0.125,
        )
        cand.position_qty = Decimal("0.0")
        cand.allocated_exposure_usdt = Decimal("0.0")

        snap3 = engine.ledger.get_snapshot()
        assert snap3.zero_balance_drift, f"Drift violated on exit fill: {snap3.drift}"
        assert abs(snap3.drift) < 1e-15
        assert snap3.allocated_margin == 0.0
        # 0.125 gross PnL - 0.002 total fees = 0.123 net realized PnL
        assert snap3.realized_pnl == pytest.approx(0.123, rel=1e-9)
        assert snap3.total_equity == pytest.approx(100.123, rel=1e-9)

        # 4. Record snapshot in SQLite and verify stored record
        now_ms = 1700000000000
        engine._record_solvency_snapshot(now_ms)

        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()
        cur.execute("SELECT drift, total_equity, cash, allocated_margin FROM solvency_snapshots")
        row = cur.fetchone()
        conn.close()

        assert row is not None
        assert abs(row[0]) < 1e-15
        assert row[1] == pytest.approx(100.123, rel=1e-9)

        engine.close_telemetry_db()

    def test_autopsy_drain_record_count_matches_tables_1_to_1(self, tmp_path: Path) -> None:
        """Verifies that draining autopsies across all active pairs creates 1:1 records."""
        engine = SelfDrivingTradingEngine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        for idx, sym in enumerate(ACTIVE_PAIRS):
            engine.enqueue_ict_autopsy(
                make_autopsy_payload(
                    trade_id=f"trd-p317-{sym.lower()}-001",
                    symbol=sym,
                    candidate_id=f"cand-{sym.lower()}-ict-001",
                    entry_price=100.0,
                    exit_price=102.5 if idx % 2 == 0 else 98.0,
                    timestamp_ms=1700000000000 + idx * 1000,
                )
            )

        drained = engine.drain_pending_autopsies()
        assert len(drained) == len(ACTIVE_PAIRS)

        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()

        # Verify ict_trade_autopsies record count
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        autopsy_count = cur.fetchone()[0]
        assert autopsy_count == len(ACTIVE_PAIRS), (
            f"Expected {len(ACTIVE_PAIRS)} autopsies, got {autopsy_count}"
        )

        # Verify ict_candidate_registry record count
        cur.execute("SELECT COUNT(*) FROM ict_candidate_registry")
        candidate_count = cur.fetchone()[0]
        assert candidate_count == len(ACTIVE_PAIRS), (
            f"Expected {len(ACTIVE_PAIRS)} candidates in registry, got {candidate_count}"
        )

        # Verify all 8 candidate IDs are enrolled
        cur.execute("SELECT candidate_id, symbol, health_tier FROM ict_candidate_registry")
        registry_rows = cur.fetchall()
        conn.close()

        enrolled_cand_ids = {r[0] for r in registry_rows}
        expected_cand_ids = {f"cand-{s.lower()}-ict-001" for s in ACTIVE_PAIRS}
        assert enrolled_cand_ids == expected_cand_ids

        # Verify health tiers match net PnL (even index: BUY exit 102.5 > 100 = HEALTHY)
        for cand_id, sym, tier in registry_rows:
            idx = ACTIVE_PAIRS.index(sym)
            expected_tier = "HEALTHY" if idx % 2 == 0 else "DEGRADED"
            assert tier == expected_tier, (
                f"Candidate {cand_id} health tier mismatch: {tier} != {expected_tier}"
            )

        engine.close_telemetry_db()

    def test_repeated_autopsies_for_same_candidate_updates_health_without_duplication(
        self, tmp_path: Path
    ) -> None:
        """Verifies that 10 autopsies for the SAME candidate produce:

        - 10 distinct records in `ict_trade_autopsies`
        - Exactly 1 record in `ict_candidate_registry` (updated in-place via INSERT OR REPLACE).
        """
        engine = SelfDrivingTradingEngine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        for i in range(10):
            # Alternating winners and losers
            pnl_delta = 2.0 if i % 2 == 0 else -2.0
            engine.enqueue_ict_autopsy(
                make_autopsy_payload(
                    trade_id=f"trd-rep-{i:03d}",
                    symbol="SOLUSDT",
                    candidate_id="cand-solusdt-ict-001",
                    entry_price=100.0,
                    exit_price=100.0 + pnl_delta,
                    timestamp_ms=1700000000000 + i * 1000,
                )
            )

        drained = engine.drain_pending_autopsies()
        assert len(drained) == 10

        conn = sqlite3.connect(engine.db_path)
        cur = conn.cursor()

        # 10 records in ict_trade_autopsies
        cur.execute(
            "SELECT COUNT(*) FROM ict_trade_autopsies WHERE candidate_id = 'cand-solusdt-ict-001'"
        )
        assert cur.fetchone()[0] == 10

        # Exactly 1 record in ict_candidate_registry
        cur.execute(
            "SELECT COUNT(*) FROM ict_candidate_registry "
            "WHERE candidate_id = 'cand-solusdt-ict-001'"
        )
        assert cur.fetchone()[0] == 1

        # Check timestamp reflects latest autopsy (i=9 => 1700000000000 + 9000)
        cur.execute(
            "SELECT updated_at_ms, health_tier FROM ict_candidate_registry "
            "WHERE candidate_id = 'cand-solusdt-ict-001'"
        )
        updated_ts, tier = cur.fetchone()
        conn.close()

        assert updated_ts == 1700000000000 + 9000
        # i=9 was loser (-2.0) -> DEGRADED
        assert tier == "DEGRADED"

        engine.close_telemetry_db()


# =============================================================================
# Challenge 4: Trader Loop Timeout Budget Enforcement
# =============================================================================


class TestTraderLoopTimeoutBudgetEnforcement:
    """Verifies that disk I/O stalls never breach the 15.0ms trader cycle budget."""

    @pytest.mark.anyio
    async def test_simulated_disk_io_stall_does_not_block_trader_cycle(
        self, tmp_path: Path
    ) -> None:
        """Simulates a 50.0ms disk I/O stall in drain_pending_autopsies.

        Verifies that:
        1. asyncio.wait_for(..., timeout=0.005) times out after ~5ms.
        2. run_single_cycle() continues without raising an unhandled exception.
        3. Total cycle execution latency remains strictly < 15.0 ms.
        """
        mock_gateway = AsyncMock(spec=BinanceFuturesGateway)
        mock_gateway.get_position_risk.return_value = []
        mock_gateway.get_klines.return_value = []
        mock_gateway.testnet = True

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gateway,
            telegram_enabled=False,
        )
        trader.engine.perform_preflight_checks()

        now = time.time()
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = trader.sequencer.buffers[(sym, tf)]
                for i in range(50):
                    buf.append(
                        Candle(
                            timestamp_ms=1700000000000 + i * 60000,
                            open=Decimal("100.0"),
                            high=Decimal("101.0"),
                            low=Decimal("99.0"),
                            close=Decimal("100.5"),
                            volume=Decimal("1000.0"),
                        )
                    )
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        trader.btc_1h_history = [
            MacroCandle(
                timestamp_ms=1700000000000 + i * 3600000,
                open=Decimal("82600.0"),
                high=Decimal("82700.0"),
                low=Decimal("82500.0"),
                close=Decimal("82650.0"),
                volume=Decimal("500.0"),
            )
            for i in range(210)
        ]
        trader.last_candle_fetch_ts = now
        trader.last_export_ts = now

        # Enqueue autopsy
        trader.engine.enqueue_ict_autopsy(make_autopsy_payload(trade_id="trd-stall-001"))
        assert trader.engine.has_pending_autopsies()

        # Mock drain_pending_autopsies with a deliberate 50ms blocking sleep
        def stalled_drain(*args: Any, **kwargs: Any) -> list[IctAutopsyMetrics]:
            time.sleep(0.050)
            return []

        # On Windows, elevate timer resolution to 1ms (standard on Linux)
        is_windows = os.name == "nt"
        if is_windows:
            import ctypes

            ctypes.windll.winmm.timeBeginPeriod(1)

        try:
            with patch.object(trader.engine, "drain_pending_autopsies", side_effect=stalled_drain):
                t0 = time.perf_counter()
                await trader.run_single_cycle()
                cycle_ms = (time.perf_counter() - t0) * 1000.0
        finally:
            if is_windows:
                import ctypes

                ctypes.windll.winmm.timeEndPeriod(1)

        # Cycle latency must be bound by the ~5ms timeout, staying strictly < 15.0 ms
        assert cycle_ms < 15.0, (
            f"Cycle latency under stalled disk I/O took {cycle_ms:.2f}ms, exceeding 15.0ms budget!"
        )

        trader.engine.close_telemetry_db()
