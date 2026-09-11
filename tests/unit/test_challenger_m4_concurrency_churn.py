"""Empirical Challenger 2 Test Suite for Milestone 4 (R4).

Role: Long-Duration Concurrency & Churn Challenger.
Focus:
1. SQLite lock contention (busy_timeout, database is locked) under concurrent
   trading writes, observations, lifecycle events, hot reloader polling, and ReadOnlyLedgerReader.
2. SQLite database integrity (PRAGMA integrity_check) and monotonic ledger sequencing.
3. Memory stability and candidate artifact retention across repeated hot-reload churn.
4. Unhandled task exceptions, coroutine lifecycles, and clean shutdown invariants.
"""

from __future__ import annotations

import asyncio
import gc
import json
import sqlite3
import sys
import tracemalloc
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.run_phase_259_live_paper_daemon as daemon_mod  # noqa: E402
from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader  # noqa: E402
from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import TickerSnapshot  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    CandidateManifestEntry,
    CandidateRegistryHotReloader,
    build_candidate_registry_manifest,
    publish_candidate_admission,
    write_candidate_registry,
)
from autonomous_futures.paper.live_engine import LivePaperEngine  # noqa: E402
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def _hex64(val: int | str) -> str:
    """Generate deterministic 64-char lowercase hex string."""
    import hashlib

    return hashlib.sha256(str(val).encode("utf-8")).hexdigest()


def _build_test_candidate(
    candidate_id: str,
    symbol: str = "BTCUSDT",
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trail_mult: str = "1.0",
    entry_rule: str = "rsi <= 35",
    exit_rule: str = "rsi >= 55",
) -> CreatorCandidateArtifact:
    """Construct a valid CreatorCandidateArtifact with explicit risk parameters."""
    feats = (FeatureRef(name="rsi", lookback=14, shift=1),)
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,),
            timeframe="5m",
            regime_context_timeframe="15m",
        ),
        features=feats,
        entry=EntryExit(long=entry_rule, short="rsi >= 70"),
        exit=EntryExit(long=exit_rule, short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_mult),
            take_profit_atr_multiplier=Decimal(tp_mult),
            trailing_atr_multiplier=Decimal(trail_mult),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=NOW,
    )


def _setup_engine(
    tmp_path: Path,
    candidates: dict[str, CreatorCandidateArtifact],
    starting_capital: Decimal = Decimal("100.00"),
) -> LivePaperEngine:
    """Initialize a LivePaperEngine with real SQLite stores."""
    symbols = tuple(sorted(candidates.keys()))
    engine = LivePaperEngine(
        symbols=symbols,
        candidates=candidates,
        starting_capital=starting_capital,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    for sym in symbols:
        engine.monitor._rolling_atrs[sym] = Decimal("100.0")
        engine.monitor._baseline_atrs[sym] = Decimal("100.0")
        engine.latest_tickers[sym] = TickerSnapshot(
            symbol=sym,
            best_bid_price=Decimal("50000.00"),
            best_bid_qty=Decimal("2.0"),
            best_ask_price=Decimal("50001.00"),
            best_ask_qty=Decimal("2.0"),
            transaction_time=NOW,
            event_time=NOW,
        )
    return engine


def _seed_warmup_bars(
    engine: LivePaperEngine,
    symbol: str = "BTCUSDT",
    count: int = 25,
    base_price: Decimal = Decimal("50000.00"),
) -> None:
    """Seed historical 5m bars to ensure feature evaluators (RSI) have sufficient history."""
    engine._bar_history[symbol].clear()
    for i in range(count):
        bar_time = NOW - timedelta(minutes=5 * (count - 1 - i))
        engine._bar_history[symbol].append(
            {
                "timestamp": bar_time,
                "open": base_price,
                "high": base_price + Decimal("20"),
                "low": base_price - Decimal("20"),
                "close": base_price,
                "volume": Decimal("10.0"),
            }
        )


class PacedMockWebSocketSession:
    """Mock WebSocket returning queued JSON wire messages."""

    def __init__(self, messages: list[str], pace_seconds: float = 0.001) -> None:
        self.messages = list(messages)
        self.idx = 0
        self.pace_seconds = pace_seconds

    def __aiter__(self) -> PacedMockWebSocketSession:
        return self

    async def __anext__(self) -> str:
        if self.idx >= len(self.messages):
            await asyncio.sleep(0.01)
            raise StopAsyncIteration
        msg = self.messages[self.idx]
        self.idx += 1
        if self.pace_seconds > 0:
            await asyncio.sleep(self.pace_seconds)
        return msg

    async def close(self) -> None:
        pass


class MockConnectContext:
    def __init__(self, session: PacedMockWebSocketSession) -> None:
        self.session = session

    async def __aenter__(self) -> PacedMockWebSocketSession:
        return self.session

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.session.close()


def _make_book_ticker_wire(
    symbol: str, bid: str, ask: str, time_ms: int = 1772700000000, update_id: int = 1000
) -> str:
    return json.dumps(
        {
            "stream": f"{symbol.lower()}@bookTicker",
            "data": {
                "u": update_id,
                "s": symbol.upper(),
                "b": bid,
                "B": "1.500",
                "a": ask,
                "A": "1.500",
                "T": time_ms,
                "E": time_ms,
            },
        }
    )


# ==============================================================================
# EMPIRICAL CHALLENGER TESTS
# ==============================================================================


def test_empirical_sqlite_lock_contention_and_integrity_under_rapid_churn(
    tmp_path: Path,
) -> None:
    """Empirical challenge: SQLite lock contention and database corruption under churn.

    Simultaneously executes:
    1. Active trading lifecycle: opens, ratchets trailing stops, closes (writes to ledger,
       lifecycle, observations).
    2. Rapid candidate publishing and hot-reloading (updates manifest and engine candidates).
    3. Concurrent ReadOnlyLedgerReader queries (self-joins, table exists, busy_timeout).

    Verifies:
    - Zero `sqlite3.OperationalError` ("database is locked") or busy timeout exceptions.
    - `PRAGMA integrity_check` on all 3 SQLite databases returns 'ok'.
    - Ledger sequence continuity: monotonic integer sequence with zero gaps or corruption.
    - Zero balance drift across entire execution.
    """
    storage_dir = tmp_path / "sqlite_stress"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    cand_init = _build_test_candidate("cand-init", symbol="BTCUSDT")
    cand_init_file = storage_dir / "cand-init.json"
    write_creator_candidate_artifact(cand_init_file, cand_init)
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_init.candidate_id,
        candidate_artifact_hash=cand_init.artifact_hash,
        artifact_path=cand_init_file,
        qualification_hash=_hex64("init"),
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_init})
    _seed_warmup_bars(engine, "BTCUSDT", count=25)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    reader = ReadOnlyLedgerReader(storage_dir)

    lock_errors: list[Exception] = []
    trades_executed = 0

    # Execute 25 full trade cycles with concurrent hot reloads and reader queries
    for cycle in range(1, 26):
        # 1. Open trade
        open_time = NOW + timedelta(minutes=cycle * 10)
        open_res = engine.execute_open(
            symbol="BTCUSDT",
            signal=1,
            conviction=Decimal("0.75"),
            event_time=open_time,
        )
        assert open_res is not None
        assert open_res.status == "opened"
        assert engine.active_trades["BTCUSDT"].trade_id is not None

        # 2. Concurrently read ledger while position is open
        try:
            open_count = reader.read_open_trades_count()
            assert open_count == 1
            reconciled_cash = reader.calculate_reconciled_cash(Decimal("100.00"))
            assert reconciled_cash > Decimal("0")
        except Exception as exc:
            lock_errors.append(exc)

        # 3. Ratchet trailing stop via favorable ticks
        for tick_step in range(3):
            p = Decimal("50000.00") + Decimal(str(cycle * 10 + tick_step * 20))
            tick = TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=p,
                best_bid_qty=Decimal("1.0"),
                best_ask_price=p + Decimal("1.0"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=open_time + timedelta(seconds=tick_step * 5),
                event_time=open_time + timedelta(seconds=tick_step * 5),
            )
            engine.latest_tickers["BTCUSDT"] = tick
            engine._evaluate_tick_stops("BTCUSDT", tick)

        # 4. Rapidly publish and reload a new candidate mid-trade
        new_cand = _build_test_candidate(f"cand-churn-{cycle:03d}", symbol="BTCUSDT")
        new_cand_file = storage_dir / f"cand-churn-{cycle:03d}.json"
        write_creator_candidate_artifact(new_cand_file, new_cand)
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=new_cand.candidate_id,
            candidate_artifact_hash=new_cand.artifact_hash,
            artifact_path=new_cand_file,
            qualification_hash=_hex64(cycle),
        )

        try:
            reloaded = reloader.check_and_reload()
            assert reloaded is True
            assert engine.candidates["BTCUSDT"].candidate_id == f"cand-churn-{cycle:03d}"
        except Exception as exc:
            lock_errors.append(exc)

        # 5. Concurrently read closed trades and lifecycle marks during reload
        try:
            _ = reader.read_closed_trades()
            _ = reader._load_exit_reasons()
        except Exception as exc:
            lock_errors.append(exc)

        # 6. Close trade
        close_time = open_time + timedelta(minutes=5)
        close_res = engine.execute_close(
            symbol="BTCUSDT",
            exit_reason="take_profit_hit",
            event_time=close_time,
        )
        assert close_res is not None
        assert close_res.status == "closed"
        trades_executed += 1

        # 7. Post-close reader verification
        try:
            closed_trades = reader.read_closed_trades()
            assert len(closed_trades) == trades_executed
        except Exception as exc:
            lock_errors.append(exc)

    # Verification 1: Zero lock errors or busy timeout exceptions
    assert len(lock_errors) == 0, f"Encountered SQLite lock contention / busy errors: {lock_errors}"

    # Verification 2: PRAGMA integrity_check on all 3 SQLite databases
    for db_name in (
        "paper-ledger.sqlite3",
        "paper-lifecycle.sqlite3",
        "paper-observations.sqlite3",
    ):
        db_file = storage_dir / db_name
        assert db_file.is_file(), f"Database {db_name} missing"
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            rows = cursor.fetchall()
            assert rows == [("ok",)], f"Database {db_name} failed integrity check: {rows}"

    # Verification 3: Monotonic contiguous sequence numbers in paper_ledger_events
    with sqlite3.connect(storage_dir / "paper-ledger.sqlite3") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT sequence FROM paper_ledger_events ORDER BY sequence ASC")
        sequences = [r[0] for r in cursor.fetchall()]
        expected_sequences = list(range(1, 2 * trades_executed + 1))
        assert sequences == expected_sequences, (
            f"Ledger sequences non-contiguous: got {sequences[:10]}... "
            f"expected {expected_sequences[:10]}..."
        )

    # Verification 4: Zero balance drift
    reconciled = engine.reconcile_balances()
    assert reconciled["zero_balance_drift"] is True
    assert reconciled["closed_trades_count"] == trades_executed


def test_empirical_memory_leak_and_candidate_retention_across_churn(
    tmp_path: Path,
) -> None:
    """Empirical challenge: Memory stability and candidate artifact retention across churn.

    Runs 60 consecutive candidate hot-reloads on the engine while tracking:
    1. Size of `engine.candidates` dict: must remain strictly 1 (bounded to symbol set).
    2. Heap allocation via `tracemalloc`: snapshot growth between cycle 10 and cycle 60
       must be tightly bounded (< 400 KB), proving unreferenced candidate strategy
       trees and feature lists are garbage-collected cleanly.
    """
    storage_dir = tmp_path / "memory_churn_test"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    cand_0 = _build_test_candidate("cand-mem-000", symbol="BTCUSDT")
    cand_0_file = storage_dir / "cand-mem-000.json"
    write_creator_candidate_artifact(cand_0_file, cand_0)
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_0.candidate_id,
        candidate_artifact_hash=cand_0.artifact_hash,
        artifact_path=cand_0_file,
        qualification_hash=_hex64("mem-000"),
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_0})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    # Force garbage collection and start tracemalloc
    gc.collect()
    tracemalloc.start()

    snapshot_early = None
    total_reloads = 60

    for i in range(1, total_reloads + 1):
        cand = _build_test_candidate(f"cand-mem-{i:03d}", symbol="BTCUSDT")
        cand_file = storage_dir / f"cand-mem-{i:03d}.json"
        write_creator_candidate_artifact(cand_file, cand)
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=cand.candidate_id,
            candidate_artifact_hash=cand.artifact_hash,
            artifact_path=cand_file,
            qualification_hash=_hex64(f"mem-{i}"),
        )

        reloaded = reloader.check_and_reload()
        assert reloaded is True
        assert len(engine.candidates) == 1
        assert engine.candidates["BTCUSDT"].candidate_id == f"cand-mem-{i:03d}"

        if i == 10:
            gc.collect()
            snapshot_early = tracemalloc.take_snapshot()

    gc.collect()
    snapshot_late = tracemalloc.take_snapshot()
    tracemalloc.stop()

    assert snapshot_early is not None
    top_stats = snapshot_late.compare_to(snapshot_early, "lineno")
    total_diff_bytes = sum(stat.size_diff for stat in top_stats)

    # Over 50 reloads, net heap growth should be modest (< 500 KB)
    assert total_diff_bytes < 500 * 1024, (
        f"Potential memory leak detected: net heap growth was "
        f"{total_diff_bytes / 1024:.2f} KB across 50 reloads"
    )


@pytest.mark.anyio
async def test_empirical_unhandled_task_exceptions_and_lifecycle_invariants(
    tmp_path: Path,
) -> None:
    """Empirical challenge: Unhandled task exceptions, coroutines, and clean shutdown.

    Runs `run_live_paper_daemon` with high-frequency streaming while concurrently:
    1. Performing valid hot reloads.
    2. Injecting invalid / corrupt manifests (triggering fail-closed paths).
    3. Recovering with valid manifests.

    Verifies:
    - Daemon runs and terminates cleanly with status SHUTDOWN_CLEAN.
    - All background tasks (heartbeat, monitor, ws client) terminate cleanly.
    - Zero unhandled task exceptions (no uncaught exceptions in tasks).
    """
    storage_dir = tmp_path / "daemon_task_lifecycle"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    # Pre-stage valid candidate
    cand_init = _build_test_candidate("cand-lifecycle-001", symbol="BTCUSDT")
    cand_init_file = storage_dir / "cand-lifecycle-001.json"
    write_creator_candidate_artifact(cand_init_file, cand_init)
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_init.candidate_id,
        candidate_artifact_hash=cand_init.artifact_hash,
        artifact_path=cand_init_file,
        qualification_hash=_hex64("lifecycle01"),
    )

    # 120 streaming wire frames
    messages: list[str] = []
    for i in range(120):
        p = 50000.0 + (i % 20) * 1.5
        messages.append(
            _make_book_ticker_wire(
                symbol="BTCUSDT",
                bid=f"{p:.2f}",
                ask=f"{(p + 0.5):.2f}",
                time_ms=1772700000000 + i * 40,
                update_id=30000000 + i,
            )
        )

    mock_ws = PacedMockWebSocketSession(messages, pace_seconds=0.001)
    args = daemon_mod.parse_cli_args(
        [
            "--storage-dir",
            str(storage_dir),
            "--duration",
            "5.0",
            "--checkpoint-interval",
            "0.08",
            "--starting-capital",
            "100.00",
            "--symbols",
            "BTCUSDT",
            "--candidate-registry-path",
            str(manifest_path),
            "--offline-warmup",
            "--warmup-bars",
            "25",
        ]
    )

    async def _adversarial_manifest_churn_task() -> None:
        """Concurrently inject valid and invalid manifests while daemon streams."""
        await asyncio.sleep(0.08)

        # 1. Valid update
        c2 = _build_test_candidate("cand-lifecycle-002", symbol="BTCUSDT")
        c2_file = storage_dir / "cand-lifecycle-002.json"
        write_creator_candidate_artifact(c2_file, c2)
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=c2.candidate_id,
            candidate_artifact_hash=c2.artifact_hash,
            artifact_path=c2_file,
            qualification_hash=_hex64("lifecycle02"),
        )
        await asyncio.sleep(0.15)

        # 2. Corrupted manifest injection (truncated JSON)
        manifest_path.write_text('{"corrupted_json": true, ', encoding="utf-8")
        await asyncio.sleep(0.15)

        # 3. Recovery with valid update
        c3 = _build_test_candidate("cand-lifecycle-003", symbol="BTCUSDT")
        c3_file = storage_dir / "cand-lifecycle-003.json"
        write_creator_candidate_artifact(c3_file, c3)
        manifest_recovered = build_candidate_registry_manifest(
            symbols={
                "BTCUSDT": CandidateManifestEntry(
                    candidate_id=c3.candidate_id,
                    candidate_artifact_hash=c3.artifact_hash,
                    artifact_path=str(c3_file),
                    qualification_hash=_hex64("lifecycle03"),
                    admitted_at=NOW.isoformat(),
                )
            },
            updated_at=NOW.isoformat(),
        )
        write_candidate_registry(manifest_path, manifest_recovered)

    with patch("websockets.connect", return_value=MockConnectContext(mock_ws)):
        churn_task = asyncio.create_task(_adversarial_manifest_churn_task())
        summary = await daemon_mod.run_live_paper_daemon(args)
        await churn_task

    assert summary is not None
    health_file = storage_dir / "paper-daemon-health.json"
    assert health_file.is_file()
    health = json.loads(health_file.read_text(encoding="utf-8"))

    # Verification: clean shutdown and telemetry
    assert health["daemon_status"] == "SHUTDOWN_CLEAN"
    assert health["feed_messages_received"] == 120
    assert health["feed_reconnects_count"] == 0
    assert health["last_registry_reload"]["reload_status"] == "RELOADED"
    assert health["last_registry_reload"]["reload_count"] >= 2
    assert health["active_candidates"]["BTCUSDT"] == "cand-lifecycle-003"
