"""Phase 261 / Milestone 4: Comprehensive Verification & Adversarial Stress Tests.

Integration test suite for live paper daemon candidate hot-reloading:
1. Scenario A: Hot-reload during active position:
   - Open trade retains Candidate A exit behavior (both strategy exit expressions and
     tick-level ATR trailing stops) while subsequent trade adopts Candidate B.
   - Exact Candidate A / Candidate B attribution preserved in SQLite ledgers.
2. Scenario B: Malformed / tampered manifest resistance:
   - Corrupted JSON, hash mismatches, missing artifacts, tampered artifact contents,
     strategy universe mismatches, and 0-byte/binary garbage fail-closed without crashing.
   - All-or-nothing multi-symbol atomic admission verified.
   - Subsequent valid atomic update recovers cleanly.
3. Scenario C: Continuous daemon stability & shared margin invariants:
   - Zero WebSocket frame loss and zero reconnects across high-volume streaming.
   - Hardened shared margin invariants: account.cash, account.total_locked_margin(),
     engine.current_equity(), and exact decimal reconciliation.
4. Scenario D: Health telemetry verification:
   - Inspects `paper-daemon-health.json` across STARTING, RUNNING, and SHUTDOWN_CLEAN phases.
   - Verifies active_candidates ({symbol: candidate_id}) and last_registry_reload telemetry.
5. Scenario E: Multi-symbol interleaved hot-reload isolation:
   - Independent candidate updates per symbol (BTC, ETH, SOL) with concurrent positions.
6. Scenario F: Adversarial shared margin invariance under churn:
   - Account cash is NEVER reset to starting capital ($100.00) across 20+ reload churn events.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
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
from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot  # noqa: E402
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


# ==============================================================================
# TEST FIXTURES & HELPERS
# ==============================================================================


def _build_test_candidate(
    candidate_id: str,
    symbol: str = "BTCUSDT",
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trail_mult: str = "1.0",
    entry_rule: str = "rsi <= 35",
    exit_rule: str = "rsi >= 55",
) -> CreatorCandidateArtifact:
    """Construct a valid CreatorCandidateArtifact with explicit risk and signal rules."""
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
    """Initialize a LivePaperEngine with real SQLite stores and simulated initial tickers."""
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
    """Seed historical 5m bars to ensure feature evaluators (RSI) have sufficient history.

    The final bar aligns with NOW so that the subsequent bar at NOW + 5m continues
    without triggering gap pruning.
    """
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
    """Mock WebSocket session simulating Binance public wire frames with paced delivery.

    Avoids tight busy-looping while allowing dynamic queue push and graceful close.
    """

    def __init__(self, messages: list[str] | None = None) -> None:
        self._messages: list[str] = list(messages) if messages else []
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str = ""

    def __aiter__(self) -> PacedMockWebSocketSession:
        return self

    async def __anext__(self) -> str:
        if self.closed:
            raise StopAsyncIteration
        if self._messages:
            msg = self._messages.pop(0)
            await asyncio.sleep(0.01)  # Pace delivery to yield slices to event loop tasks
            return msg
        # When messages are exhausted, wait gracefully until closed
        while not self.closed:
            await asyncio.sleep(0.05)
        raise StopAsyncIteration

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class MockConnectContext:
    """Async context manager wrapper for mock WebSocket connection."""

    def __init__(self, ws: PacedMockWebSocketSession) -> None:
        self._ws = ws

    async def __aenter__(self) -> PacedMockWebSocketSession:
        return self._ws

    async def __aexit__(self, exc_type: type | None, exc: Exception | None, tb: object) -> None:
        pass


def make_book_ticker_wire(
    symbol: str = "BTCUSDT",
    bid: str = "50000.00",
    ask: str = "50000.10",
    time_ms: int = 1772700000000,
    update_id: int = 10001,
) -> str:
    """Construct valid multiplexed bookTicker wire payload."""
    return json.dumps(
        {
            "stream": f"{symbol.lower()}@bookTicker",
            "data": {
                "e": "bookTicker",
                "u": update_id,
                "s": symbol.upper(),
                "b": bid,
                "B": "1.0",
                "a": ask,
                "A": "1.0",
                "T": time_ms,
                "E": time_ms + 50,
            },
        }
    )


async def read_health_checkpoint_async(
    health_file: Path,
    timeout: float = 4.0,
    expected_status: str | None = None,
    daemon_task: asyncio.Task[Any] | None = None,
) -> dict[str, Any]:
    """Robust polling reader for paper-daemon-health.json handling Windows NTFS contention."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon_task is not None and daemon_task.done():
            # If daemon crashed, immediately raise its exception
            daemon_task.result()
        if health_file.is_file():
            try:
                content = health_file.read_text(encoding="utf-8")
                if content.strip():
                    raw_data: Any = json.loads(content)
                    if isinstance(raw_data, dict):
                        data: dict[str, Any] = raw_data
                        if expected_status is None or data.get("daemon_status") == expected_status:
                            return data
            except json.JSONDecodeError, OSError, PermissionError:
                pass
        await asyncio.sleep(0.02)
    raise TimeoutError(
        f"Health checkpoint at {health_file} did not meet criteria within {timeout}s"
    )


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================


@pytest.mark.anyio
async def test_scenario_a_hot_reload_during_active_position_immutability(
    tmp_path: Path,
) -> None:
    """Scenario A: Open trade retains Candidate A exit rules while Candidate B is admitted.

    Subsequent trade on the same symbol strictly adopts Candidate B rules.
    Verifies Open-Trade Immutability Invariant across engine memory, strategy evaluation,
    and durable SQLite ledger event records.
    """
    storage_dir = tmp_path / "paper_live_scenario_a"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    # 1. Candidate A: tight trail (1.0x ATR), exit when rsi >= 55, entry when rsi <= 35
    cand_a = _build_test_candidate(
        "cand-btc-alpha",
        symbol="BTCUSDT",
        stop_mult="1.5",
        tp_mult="5.0",
        trail_mult="1.0",
        entry_rule="rsi <= 35",
        exit_rule="rsi >= 55",
    )
    cand_a_file = storage_dir / "cand-btc-alpha.json"
    write_creator_candidate_artifact(cand_a_file, cand_a)

    # 2. Candidate B: wide trail (3.5x ATR), exit when rsi >= 85, entry when rsi <= 40
    cand_b = _build_test_candidate(
        "cand-btc-beta",
        symbol="BTCUSDT",
        stop_mult="3.0",
        tp_mult="10.0",
        trail_mult="3.5",
        entry_rule="rsi <= 40",
        exit_rule="rsi >= 85",
    )
    cand_b_file = storage_dir / "cand-btc-beta.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    # 3. Publish Candidate A initially
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_hash=cand_a.artifact_hash,
        artifact_path=cand_a_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_a})
    _seed_warmup_bars(engine, "BTCUSDT", count=25)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id

    # 4. Open Trade 1 under Candidate A
    opened_1 = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW)
    assert opened_1 is not None
    trade_1 = engine.active_trades["BTCUSDT"]
    assert trade_1.candidate_id == cand_a.candidate_id
    assert trade_1.candidate is not None
    assert trade_1.candidate.candidate_id == cand_a.candidate_id
    assert trade_1.trailing_atr_multiplier == Decimal("1.0")

    # 5. Hot-reload Candidate B while Trade 1 is actively OPEN
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="2" * 64,
        admitted_at=NOW + timedelta(seconds=10),
    )
    reloaded = reloader.check_and_reload()
    assert reloaded is True
    assert reloader.last_reload_status == "RELOADED"

    # Open-Trade Immutability Invariant Verification:
    # Engine pool now has Candidate B, but Trade 1 strictly retains Candidate A
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id
    retained_trade = engine.active_trades["BTCUSDT"]
    assert retained_trade.candidate_id == cand_a.candidate_id
    assert retained_trade.candidate is not None
    assert retained_trade.candidate.candidate_id == cand_a.candidate_id
    assert retained_trade.trailing_atr_multiplier == Decimal("1.0")

    # 6. Feed bar that triggers Candidate A's exit rule (rsi >= 55),
    # but NOT Candidate B's (rsi >= 85)
    with patch(
        "autonomous_futures.paper.live_engine.evaluate_strategy_exit",
        side_effect=lambda row, side, long_exit_expr, short_exit_expr: (
            long_exit_expr == cand_a.strategy.exit.long
        ),
    ):
        exit_bar = CanonicalBar(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=NOW + timedelta(minutes=5),
            close_time=NOW + timedelta(minutes=5),
            open=Decimal("50000"),
            high=Decimal("50200"),
            low=Decimal("49900"),
            close=Decimal("50150"),
            volume=Decimal("15"),
            quote_volume=Decimal("752250"),
            trades=150,
            taker_buy_base=Decimal("8"),
            taker_buy_quote=Decimal("401200"),
            is_closed=True,
        )
        engine._process_closed_bar(exit_bar)

    # Trade 1 closed cleanly under Candidate A rules
    assert "BTCUSDT" not in engine.active_trades
    assert engine.total_closed_trades == 1

    # Verify SQLite ledger events for Trade 1 permanently record Candidate A
    with sqlite3.connect(storage_dir / "paper-ledger.sqlite3") as conn:
        rows = conn.execute(
            "SELECT sequence, event, trade_id, candidate_id, symbol "
            "FROM paper_ledger_events ORDER BY sequence ASC"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "open"
    assert rows[0][3] == cand_a.candidate_id
    assert rows[1][1] == "close"
    assert rows[1][3] == cand_a.candidate_id

    # 7. Open subsequent Trade 2: Must adopt Candidate B
    opened_2 = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=NOW + timedelta(minutes=10)
    )
    assert opened_2 is not None
    trade_2 = engine.active_trades["BTCUSDT"]
    assert trade_2.candidate_id == cand_b.candidate_id
    assert trade_2.candidate is not None
    assert trade_2.candidate.candidate_id == cand_b.candidate_id
    assert trade_2.trailing_atr_multiplier == Decimal("3.5")

    # Ledger event for Trade 2 open reflects Candidate B
    with sqlite3.connect(storage_dir / "paper-ledger.sqlite3") as conn:
        rows_2 = conn.execute(
            "SELECT sequence, event, trade_id, candidate_id, symbol "
            "FROM paper_ledger_events ORDER BY sequence ASC"
        ).fetchall()
    assert len(rows_2) == 3
    assert rows_2[2][1] == "open"
    assert rows_2[2][3] == cand_b.candidate_id

    # Balance reconciliation verified
    rec = engine.reconcile_balances()
    assert rec["zero_balance_drift"] is True


@pytest.mark.anyio
async def test_scenario_a_tick_level_atr_trailing_stop_immutability(
    tmp_path: Path,
) -> None:
    """Scenario A2: Tick-level ATR trailing stop immutability invariant.

    Active trade retains tight trailing ATR stop multiplier (1.0x) bound at entry.
    When price advances and pulls back, Trade 1 exits on trailing stop hit under Candidate A's
    multiplier, whereas Candidate B's wider multiplier (3.5x) would have remained open.
    Subsequent Trade 2 opens and adopts the wider 3.5x multiplier.
    """
    storage_dir = tmp_path / "paper_live_scenario_a_tick"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    cand_a = _build_test_candidate("cand-a-tick", trail_mult="1.0")
    cand_b = _build_test_candidate("cand-b-tick", trail_mult="3.5")
    cand_a_file = storage_dir / "cand-a-tick.json"
    cand_b_file = storage_dir / "cand-b-tick.json"
    write_creator_candidate_artifact(cand_a_file, cand_a)
    write_creator_candidate_artifact(cand_b_file, cand_b)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_a.candidate_id,
        candidate_artifact_hash=cand_a.artifact_hash,
        artifact_path=cand_a_file,
        qualification_hash="a" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_a})
    _seed_warmup_bars(engine, "BTCUSDT", count=25)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()

    # Open Trade 1: fills at ask ($50,001.00), ATR = 100.00
    opened = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW)
    assert opened is not None
    trade_1 = engine.active_trades["BTCUSDT"]
    assert trade_1.trailing_atr_multiplier == Decimal("1.0")

    # Hot-reload Candidate B (3.5x trail multiplier)
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="b" * 64,
        admitted_at=NOW + timedelta(seconds=1),
    )
    assert reloader.check_and_reload()
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id
    assert trade_1.trailing_atr_multiplier == Decimal("1.0")

    # Step 1: Price rallies to $50,200.00 (ratchets trailing stop)
    tick_up = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50200.00"),
        best_bid_qty=Decimal("1.0"),
        best_ask_price=Decimal("50201.00"),
        best_ask_qty=Decimal("1.0"),
        transaction_time=NOW + timedelta(seconds=10),
        event_time=NOW + timedelta(seconds=10),
    )
    engine.latest_tickers["BTCUSDT"] = tick_up
    engine._evaluate_tick_stops("BTCUSDT", tick_up)

    # Under Candidate A (1.0x ATR), trailing stop is 50,200 - 100 = $50,100.00
    # (Under Candidate B, trailing stop would be 50,200 - 350 = $49,850.00)
    assert trade_1.trailing_stop_price == Decimal("50100.00")

    # Step 2: Price pulls back to $50,050.00 (hits Candidate A's stop of $50,100.00!)
    tick_down = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50050.00"),
        best_bid_qty=Decimal("1.0"),
        best_ask_price=Decimal("50051.00"),
        best_ask_qty=Decimal("1.0"),
        transaction_time=NOW + timedelta(seconds=20),
        event_time=NOW + timedelta(seconds=20),
    )
    engine.latest_tickers["BTCUSDT"] = tick_down
    engine._evaluate_tick_stops("BTCUSDT", tick_down)

    # Trade 1 must be closed via trailing_stop_hit
    assert "BTCUSDT" not in engine.active_trades
    assert engine.total_closed_trades == 1

    # Step 3: Open subsequent Trade 2: Must adopt Candidate B with 3.5x trail multiplier
    opened_2 = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW + timedelta(seconds=30)
    )
    assert opened_2 is not None
    trade_2 = engine.active_trades["BTCUSDT"]
    assert trade_2.candidate_id == cand_b.candidate_id
    assert trade_2.trailing_atr_multiplier == Decimal("3.5")
    assert engine.reconcile_balances()["zero_balance_drift"] is True


@pytest.mark.anyio
async def test_scenario_b_malformed_and_tampered_manifest_resistance(
    tmp_path: Path,
) -> None:
    """Scenario B: Daemon rejects corrupt JSON, hash mismatches, missing files,

    content tampering, universe mismatches, and 0-byte/binary garbage fail-closed.
    Verifies all-or-nothing multi-symbol atomic admission and clean subsequent recovery.
    """
    storage_dir = tmp_path / "paper_live_scenario_b"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    cand_valid = _build_test_candidate("cand-valid-001", symbol="BTCUSDT")
    cand_valid_file = storage_dir / "cand-valid-001.json"
    write_creator_candidate_artifact(cand_valid_file, cand_valid)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_valid.candidate_id,
        candidate_artifact_hash=cand_valid.artifact_hash,
        artifact_path=cand_valid_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )

    engine = _setup_engine(storage_dir, {"BTCUSDT": cand_valid})
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-valid-001"

    # Vector 1: Corrupted JSON syntax (truncated JSON string)
    manifest_path.write_text('{"registry_version": 1, "symbols": {', encoding="utf-8")
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_CORRUPT"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-valid-001"

    # Vector 2: Cryptographic SHA-256 Hash Mismatch (tampered manifest payload)
    manifest = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id="cand-valid-001",
                candidate_artifact_hash=cand_valid.artifact_hash,
                artifact_path=str(cand_valid_file),
                qualification_hash="1" * 64,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    tampered = manifest.model_copy(update={"registry_hash": "e" * 64})
    manifest_path.write_text(json.dumps(tampered.model_dump(mode="json")), encoding="utf-8")
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_HASH_MISMATCH"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-valid-001"

    # Vector 3: Missing Candidate Artifact File on disk
    manifest_missing = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id="cand-ghost",
                candidate_artifact_hash="8" * 64,
                artifact_path=str(storage_dir / "ghost_file.json"),
                qualification_hash="8" * 64,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    write_candidate_registry(manifest_path, manifest_missing)
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_ARTIFACT_MISSING"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-valid-001"

    # Vector 4: Tampered Candidate Artifact (inner content modified so _artifact_content_hash fails)
    cand_tampered = _build_test_candidate("cand-tampered-001", symbol="BTCUSDT")
    cand_tampered_file = storage_dir / "cand-tampered-001.json"
    write_creator_candidate_artifact(cand_tampered_file, cand_tampered)
    manifest_bad_art_hash = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id=cand_tampered.candidate_id,
                candidate_artifact_hash="f" * 64,  # Intentionally wrong
                artifact_path=str(cand_tampered_file),
                qualification_hash="7" * 64,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    write_candidate_registry(manifest_path, manifest_bad_art_hash)
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_ARTIFACT_HASH_MISMATCH"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-valid-001"

    # Vector 5: Strategy Universe Mismatch (ETH strategy assigned to BTC symbol)
    cand_eth = _build_test_candidate("cand-eth-only", symbol="ETHUSDT")
    cand_eth_file = storage_dir / "cand-eth-only.json"
    write_creator_candidate_artifact(cand_eth_file, cand_eth)
    manifest_mismatch = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id=cand_eth.candidate_id,
                candidate_artifact_hash=cand_eth.artifact_hash,
                artifact_path=str(cand_eth_file),
                qualification_hash="6" * 64,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    write_candidate_registry(manifest_path, manifest_mismatch)
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_UNIVERSE_MISMATCH"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-valid-001"

    # Vector 6: 0-byte file and raw pseudo-random binary garbage
    manifest_path.write_bytes(b"")
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_CORRUPT"

    manifest_path.write_bytes(b"\x00\xff\x00\xff" * 64)
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_CORRUPT"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-valid-001"

    # Vector 7: All-or-nothing multi-symbol atomic admission
    # Manifest contains BTC (valid) and ETH (missing artifact) -> NEITHER should be admitted!
    cand_btc_batch = _build_test_candidate("cand-btc-batch", symbol="BTCUSDT")
    cand_btc_batch_file = storage_dir / "cand-btc-batch.json"
    write_creator_candidate_artifact(cand_btc_batch_file, cand_btc_batch)
    manifest_batch = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id=cand_btc_batch.candidate_id,
                candidate_artifact_hash=cand_btc_batch.artifact_hash,
                artifact_path=str(cand_btc_batch_file),
                qualification_hash="b" * 64,
                admitted_at=NOW.isoformat(),
            ),
            "ETHUSDT": CandidateManifestEntry(
                candidate_id="cand-eth-ghost",
                candidate_artifact_hash="e" * 64,
                artifact_path=str(storage_dir / "ghost_eth.json"),
                qualification_hash="e" * 64,
                admitted_at=NOW.isoformat(),
            ),
        },
        updated_at=NOW.isoformat(),
    )
    write_candidate_registry(manifest_path, manifest_batch)
    assert not reloader.check_and_reload()
    assert reloader.last_reload_status == "FAILED_ARTIFACT_MISSING"
    # Verify BTC was NOT partially admitted:
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-valid-001"
    assert "ETHUSDT" not in engine.candidates

    # Vector 8: Clean recovery on legitimate update
    cand_recovered = _build_test_candidate("cand-recovered-001", symbol="BTCUSDT")
    cand_recovered_file = storage_dir / "cand-recovered-001.json"
    write_creator_candidate_artifact(cand_recovered_file, cand_recovered)
    manifest_recovered = build_candidate_registry_manifest(
        symbols={
            "BTCUSDT": CandidateManifestEntry(
                candidate_id=cand_recovered.candidate_id,
                candidate_artifact_hash=cand_recovered.artifact_hash,
                artifact_path=str(cand_recovered_file),
                qualification_hash="5" * 64,
                admitted_at=NOW.isoformat(),
            )
        },
        updated_at=NOW.isoformat(),
    )
    write_candidate_registry(manifest_path, manifest_recovered)
    assert reloader.check_and_reload()
    assert reloader.last_reload_status == "RELOADED"
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-recovered-001"


@pytest.mark.anyio
async def test_scenario_c_continuous_daemon_stability_and_shared_margin_invariants(
    tmp_path: Path,
) -> None:
    """Scenario C: Zero WebSocket frame loss, zero reconnects, and exact margin invariants.

    Streams 80 high-volume multiplexed wire frames while concurrently updating manifests
    in background tasks. Confirms zero message loss, zero reconnects, and exact Decimal
    balance reconciliation (zero_balance_drift is True).
    """
    storage_dir = tmp_path / "paper_live_scenario_c"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    cand_init = _build_test_candidate("cand-init-001", symbol="BTCUSDT")
    cand_init_file = storage_dir / "cand-init-001.json"
    write_creator_candidate_artifact(cand_init_file, cand_init)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_init.candidate_id,
        candidate_artifact_hash=cand_init.artifact_hash,
        artifact_path=cand_init_file,
        qualification_hash="0" * 64,
        admitted_at=NOW,
    )

    # Build 80 mock WebSocket wire frames
    messages: list[str] = []
    for i in range(80):
        p = 50000.0 + (i % 25) * 0.5
        messages.append(
            make_book_ticker_wire(
                symbol="BTCUSDT",
                bid=f"{p:.2f}",
                ask=f"{(p + 0.10):.2f}",
                time_ms=1772700000000 + i * 50,
                update_id=20000000 + i,
            )
        )

    mock_ws = PacedMockWebSocketSession(messages)
    args = daemon_mod.parse_cli_args(
        [
            "--storage-dir",
            str(storage_dir),
            "--duration",
            "1.5",
            "--checkpoint-interval",
            "0.1",
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

    async def _concurrent_publisher_task() -> None:
        """Concurrently publish multiple manifest updates while WebSocket messages stream."""
        await asyncio.sleep(0.05)
        for step in range(1, 4):
            c = _build_test_candidate(f"cand-stream-{step:03d}", symbol="BTCUSDT")
            c_file = storage_dir / f"cand-stream-{step:03d}.json"
            write_creator_candidate_artifact(c_file, c)
            publish_candidate_admission(
                manifest_path=manifest_path,
                symbol="BTCUSDT",
                candidate_id=c.candidate_id,
                candidate_artifact_hash=c.artifact_hash,
                artifact_path=c_file,
                qualification_hash=f"{step}" * 64,
                admitted_at=NOW + timedelta(seconds=step),
            )
            await asyncio.sleep(0.12)

    with patch("websockets.connect", return_value=MockConnectContext(mock_ws)):
        pub_task = asyncio.create_task(_concurrent_publisher_task())
        summary = await daemon_mod.run_live_paper_daemon(args)
        await pub_task

    # 1. Message Delivery & Reconnect Invariants
    assert summary is not None
    health_file = storage_dir / "paper-daemon-health.json"
    assert health_file.is_file()
    health = json.loads(health_file.read_text(encoding="utf-8"))
    assert health["daemon_status"] == "SHUTDOWN_CLEAN"
    assert health["feed_messages_received"] == 80
    assert health["feed_reconnects_count"] == 0

    # 2. Hardened Shared Margin Invariants
    assert summary["shared_portfolio_margin"]["zero_balance_drift"] is True
    assert summary["shared_portfolio_margin"]["starting_capital"] == "100.00"
    assert summary["shared_portfolio_margin"]["final_cash"] == "100.00"
    assert summary["safety_invariants"]["orders_submitted"] == 0

    # 3. Reload Telemetry Invariants
    assert health["last_registry_reload"]["reload_count"] >= 1
    assert health["last_registry_reload"]["reload_status"] == "RELOADED"


@pytest.mark.anyio
async def test_scenario_d_health_telemetry_across_daemon_lifecycle(
    tmp_path: Path,
) -> None:
    """Scenario D: Health telemetry verification across STARTING, RUNNING, and SHUTDOWN_CLEAN.

    Validates schema conformity, active_candidates mappings, monotonic reload_count,
    and fail-closed preservation of active_candidates during corrupted manifest injection.
    """
    storage_dir = tmp_path / "paper_live_scenario_d"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"
    health_file = storage_dir / "paper-daemon-health.json"

    # Pre-stage Candidate 1
    cand_1 = _build_test_candidate("cand-telemetry-001", symbol="BTCUSDT")
    cand_1_file = storage_dir / "cand-telemetry-001.json"
    write_creator_candidate_artifact(cand_1_file, cand_1)

    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_1.candidate_id,
        candidate_artifact_hash=cand_1.artifact_hash,
        artifact_path=cand_1_file,
        qualification_hash="1" * 64,
        admitted_at=NOW,
    )

    mock_ws = PacedMockWebSocketSession([make_book_ticker_wire(symbol="BTCUSDT")])
    args = daemon_mod.parse_cli_args(
        [
            "--storage-dir",
            str(storage_dir),
            "--candidate-registry-path",
            str(manifest_path),
            "--duration",
            "2.5",
            "--checkpoint-interval",
            "0.05",
            "--starting-capital",
            "100.00",
            "--symbols",
            "BTCUSDT",
            "--offline-warmup",
            "--warmup-bars",
            "25",
        ]
    )

    with patch("websockets.connect", return_value=MockConnectContext(mock_ws)):
        daemon_task = asyncio.create_task(daemon_mod.run_live_paper_daemon(args))

        # 1. Checkpoint Verification: Initial boot reflects Candidate 1
        cp_init = await read_health_checkpoint_async(
            health_file, timeout=4.0, daemon_task=daemon_task
        )
        assert cp_init["daemon_status"] in ("STARTING", "RUNNING")
        assert cp_init["active_candidates"]["BTCUSDT"] == "cand-telemetry-001"
        assert cp_init["last_registry_reload"]["reload_count"] >= 1

        # 2. Dynamic Hot-Reload: Admit Candidate 2 while running
        cand_2 = _build_test_candidate("cand-telemetry-002", symbol="BTCUSDT")
        cand_2_file = storage_dir / "cand-telemetry-002.json"
        write_creator_candidate_artifact(cand_2_file, cand_2)
        publish_candidate_admission(
            manifest_path=manifest_path,
            symbol="BTCUSDT",
            candidate_id=cand_2.candidate_id,
            candidate_artifact_hash=cand_2.artifact_hash,
            artifact_path=cand_2_file,
            qualification_hash="2" * 64,
            admitted_at=datetime.now(UTC),
        )

        # Wait for heartbeat loop to detect Candidate 2
        deadline = time.monotonic() + 1.2
        reloaded = False
        while time.monotonic() < deadline:
            cp = await read_health_checkpoint_async(health_file, timeout=0.5)
            if cp.get("active_candidates", {}).get("BTCUSDT") == "cand-telemetry-002":
                assert cp["last_registry_reload"]["reload_status"] == "RELOADED"
                assert cp["last_registry_reload"]["reload_count"] >= 2
                assert cp["last_registry_reload"]["registry_hash"] is not None
                assert cp["last_registry_reload"]["reloaded_at"] is not None
                reloaded = True
                break
            await asyncio.sleep(0.03)
        assert reloaded, "Candidate 2 was not reflected in health checkpoint"

        # 3. Dynamic Corruption: Inject corrupted JSON
        manifest_path.write_text("{corrupt json", encoding="utf-8")
        corrupted_observed = False
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            cp = await read_health_checkpoint_async(health_file, timeout=0.5)
            if cp.get("last_registry_reload", {}).get("reload_status") == "FAILED_CORRUPT":
                # Crucial invariant: Candidate 2 remains active despite corruption!
                assert cp["active_candidates"]["BTCUSDT"] == "cand-telemetry-002"
                corrupted_observed = True
                break
            await asyncio.sleep(0.03)
        assert corrupted_observed, "Corrupt manifest status was not reflected in health checkpoint"

        summary = await daemon_task

    # 4. Clean Shutdown Phase
    assert summary is not None
    final_health = json.loads(health_file.read_text(encoding="utf-8"))
    assert final_health["daemon_status"] == "SHUTDOWN_CLEAN"
    assert final_health["active_candidates"]["BTCUSDT"] == "cand-telemetry-002"


@pytest.mark.anyio
async def test_scenario_e_multi_symbol_interleaved_hot_reload_isolation(
    tmp_path: Path,
) -> None:
    """Scenario E: Multi-symbol interleaved hot-reload isolation (BTC, ETH, SOL).

    Verifies independent candidate updates across multiple symbols without cross-talk:
    - BTC position is open and ratcheting trailing stops.
    - ETH and SOL candidates are dynamically reloaded.
    - BTC open trade remains untouched and bound to Candidate BTC 1.
    - Subsequent ETH and SOL trades adopt newly admitted candidates.
    - Shared margin accounting is maintained across all 3 concurrent allocations.
    """
    storage_dir = tmp_path / "paper_live_scenario_e"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    cand_btc_1 = _build_test_candidate("cand-btc-1", symbol="BTCUSDT", trail_mult="1.0")
    cand_eth_1 = _build_test_candidate("cand-eth-1", symbol="ETHUSDT", trail_mult="1.5")
    cand_sol_1 = _build_test_candidate("cand-sol-1", symbol="SOLUSDT", trail_mult="1.2")

    cand_btc_2 = _build_test_candidate("cand-btc-2", symbol="BTCUSDT", trail_mult="2.0")
    cand_eth_2 = _build_test_candidate("cand-eth-2", symbol="ETHUSDT", trail_mult="3.0")
    cand_sol_2 = _build_test_candidate("cand-sol-2", symbol="SOLUSDT", trail_mult="2.5")

    for c in (cand_btc_1, cand_eth_1, cand_sol_1, cand_btc_2, cand_eth_2, cand_sol_2):
        write_creator_candidate_artifact(storage_dir / f"{c.candidate_id}.json", c)

    # Initial 3-symbol manifest
    publish_candidate_admission(
        manifest_path,
        "BTCUSDT",
        cand_btc_1.candidate_id,
        cand_btc_1.artifact_hash,
        storage_dir / f"{cand_btc_1.candidate_id}.json",
        "a" * 64,
        NOW,
    )
    publish_candidate_admission(
        manifest_path,
        "ETHUSDT",
        cand_eth_1.candidate_id,
        cand_eth_1.artifact_hash,
        storage_dir / f"{cand_eth_1.candidate_id}.json",
        "b" * 64,
        NOW,
    )
    publish_candidate_admission(
        manifest_path,
        "SOLUSDT",
        cand_sol_1.candidate_id,
        cand_sol_1.artifact_hash,
        storage_dir / f"{cand_sol_1.candidate_id}.json",
        "c" * 64,
        NOW,
    )

    engine = _setup_engine(
        storage_dir,
        {"BTCUSDT": cand_btc_1, "ETHUSDT": cand_eth_1, "SOLUSDT": cand_sol_1},
        starting_capital=Decimal("100.00"),
    )
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        _seed_warmup_bars(engine, s, count=25)

    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()

    # Step 1: Open position on BTCUSDT ($20 margin)
    opened_btc = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW
    )
    assert opened_btc is not None
    btc_trade = engine.active_trades["BTCUSDT"]
    assert btc_trade.candidate_id == cand_btc_1.candidate_id
    assert btc_trade.trailing_atr_multiplier == Decimal("1.0")

    # Step 2: Concurrently hot-reload ETHUSDT and SOLUSDT candidates
    publish_candidate_admission(
        manifest_path,
        "ETHUSDT",
        cand_eth_2.candidate_id,
        cand_eth_2.artifact_hash,
        storage_dir / f"{cand_eth_2.candidate_id}.json",
        "d" * 64,
        NOW + timedelta(seconds=1),
    )
    publish_candidate_admission(
        manifest_path,
        "SOLUSDT",
        cand_sol_2.candidate_id,
        cand_sol_2.artifact_hash,
        storage_dir / f"{cand_sol_2.candidate_id}.json",
        "e" * 64,
        NOW + timedelta(seconds=2),
    )
    assert reloader.check_and_reload()

    # Verify BTC candidate and active trade are completely unaffected
    assert engine.candidates["BTCUSDT"].candidate_id == cand_btc_1.candidate_id
    assert btc_trade.candidate_id == cand_btc_1.candidate_id
    assert btc_trade.trailing_atr_multiplier == Decimal("1.0")

    # Verify ETH and SOL candidates updated
    assert engine.candidates["ETHUSDT"].candidate_id == cand_eth_2.candidate_id
    assert engine.candidates["SOLUSDT"].candidate_id == cand_sol_2.candidate_id

    # Step 3: Open positions on ETHUSDT and SOLUSDT
    opened_eth = engine.execute_open(
        "ETHUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW + timedelta(seconds=3)
    )
    opened_sol = engine.execute_open(
        "SOLUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW + timedelta(seconds=4)
    )
    assert opened_eth is not None
    assert opened_sol is not None

    eth_trade = engine.active_trades["ETHUSDT"]
    sol_trade = engine.active_trades["SOLUSDT"]
    assert eth_trade.candidate_id == cand_eth_2.candidate_id
    assert eth_trade.trailing_atr_multiplier == Decimal("3.0")
    assert sol_trade.candidate_id == cand_sol_2.candidate_id
    assert sol_trade.trailing_atr_multiplier == Decimal("2.5")

    # Step 4: Shared Margin Accounting across all 3 open positions
    total_locked = engine.account.total_locked_margin()
    expected_sum = btc_trade.base_margin + eth_trade.base_margin + sol_trade.base_margin
    assert total_locked == expected_sum
    cur_eq = engine.current_equity()
    assert engine.account.margin_utilization(cur_eq) <= Decimal("0.80")
    assert engine.account.unencumbered_reserve_buffer(cur_eq) >= Decimal("0.20")

    # Step 5: Close BTC trade under Candidate BTC 1 rules
    engine.execute_close(
        "BTCUSDT", exit_reason="take_profit_hit", event_time=NOW + timedelta(seconds=10)
    )
    assert "BTCUSDT" not in engine.active_trades

    # Hot-reload BTCUSDT candidate to Candidate BTC 2
    publish_candidate_admission(
        manifest_path,
        "BTCUSDT",
        cand_btc_2.candidate_id,
        cand_btc_2.artifact_hash,
        storage_dir / f"{cand_btc_2.candidate_id}.json",
        "f" * 64,
        NOW + timedelta(seconds=15),
    )
    assert reloader.check_and_reload()
    assert engine.candidates["BTCUSDT"].candidate_id == cand_btc_2.candidate_id

    # Subsequent BTC trade adopts Candidate BTC 2 with trail_mult=2.0
    opened_btc_2 = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW + timedelta(seconds=20)
    )
    assert opened_btc_2 is not None
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_btc_2.candidate_id
    assert engine.active_trades["BTCUSDT"].trailing_atr_multiplier == Decimal("2.0")

    # Close remaining trades
    engine.execute_close("BTCUSDT", "signal_exit", event_time=NOW + timedelta(seconds=30))
    engine.execute_close("ETHUSDT", "take_profit_hit", event_time=NOW + timedelta(seconds=31))
    engine.execute_close("SOLUSDT", "stop_loss_hit", event_time=NOW + timedelta(seconds=32))

    assert len(engine.active_trades) == 0
    assert engine.account.total_locked_margin() == Decimal("0.00")
    assert engine.reconcile_balances()["zero_balance_drift"] is True


@pytest.mark.anyio
async def test_scenario_f_adversarial_shared_margin_invariance_under_churn(
    tmp_path: Path,
) -> None:
    """Scenario F: Shared margin accounting is NEVER reset or corrupted across 20+ reload events.

    Proves that account.cash, account.total_locked_margin(), and engine.current_equity()
    strictly maintain their real balances through rapid valid and corrupt reload churn,
    both during active positions and after realized profits.
    """
    storage_dir = tmp_path / "paper_live_scenario_f"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "candidate_registry.json"

    cand_btc = _build_test_candidate("cand-btc-base", symbol="BTCUSDT")
    cand_eth = _build_test_candidate("cand-eth-base", symbol="ETHUSDT")
    write_creator_candidate_artifact(storage_dir / "cand-btc-base.json", cand_btc)
    write_creator_candidate_artifact(storage_dir / "cand-eth-base.json", cand_eth)

    publish_candidate_admission(
        manifest_path,
        "BTCUSDT",
        cand_btc.candidate_id,
        cand_btc.artifact_hash,
        storage_dir / "cand-btc-base.json",
        "1" * 64,
        NOW,
    )
    publish_candidate_admission(
        manifest_path,
        "ETHUSDT",
        cand_eth.candidate_id,
        cand_eth.artifact_hash,
        storage_dir / "cand-eth-base.json",
        "2" * 64,
        NOW,
    )

    engine = _setup_engine(
        storage_dir,
        {"BTCUSDT": cand_btc, "ETHUSDT": cand_eth},
        starting_capital=Decimal("100.00"),
    )
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload()

    # Step 1: Open Trade on BTCUSDT ($20 margin, entry fee paid)
    opened = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW)
    assert opened is not None
    entry_fee = opened.entry_fee
    assert entry_fee is not None
    expected_cash_open = Decimal("100.00") - entry_fee
    assert engine.account.cash == expected_cash_open
    assert engine.account.total_locked_margin() == Decimal("20.00")

    # Step 2: Perform 5 sequential valid hot-reloads of ETH candidate while BTC trade is open
    for i in range(1, 6):
        c = _build_test_candidate(f"cand-eth-churn-{i}", symbol="ETHUSDT")
        c_file = storage_dir / f"cand-eth-churn-{i}.json"
        write_creator_candidate_artifact(c_file, c)
        publish_candidate_admission(
            manifest_path,
            "ETHUSDT",
            c.candidate_id,
            c.artifact_hash,
            c_file,
            f"{i}" * 64,
            NOW + timedelta(seconds=i),
        )
        assert reloader.check_and_reload()
        # Non-negotiable invariant: cash is NEVER reset to $100.00!
        assert engine.account.cash == expected_cash_open
        assert engine.account.total_locked_margin() == Decimal("20.00")
        assert engine.reconcile_balances()["zero_balance_drift"] is True

    # Step 3: Advance price to generate positive unrealized PnL
    tick_profit = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50500.00"),
        best_bid_qty=Decimal("1.0"),
        best_ask_price=Decimal("50501.00"),
        best_ask_qty=Decimal("1.0"),
        transaction_time=NOW + timedelta(minutes=1),
        event_time=NOW + timedelta(minutes=1),
    )
    engine.latest_tickers["BTCUSDT"] = tick_profit
    assert engine.current_equity() > engine.account.cash

    # Step 4: Perform 5 corrupted reloads (bad hash, corrupt JSON) while trade is in profit
    for j in range(1, 6):
        manifest_path.write_text(f'{{"registry_version": {j}, "corrupt": true', encoding="utf-8")
        assert not reloader.check_and_reload()
        assert reloader.last_reload_status == "FAILED_CORRUPT"
        assert engine.account.cash == expected_cash_open
        assert engine.account.total_locked_margin() == Decimal("20.00")
        assert engine.reconcile_balances()["zero_balance_drift"] is True

    # Step 5: Close BTC trade with realized profit
    closed = engine.execute_close(
        "BTCUSDT", exit_reason="take_profit_hit", event_time=NOW + timedelta(minutes=2)
    )
    assert closed is not None
    assert closed.status == "closed"
    # Net realized cash must be strictly greater than starting capital $100.00
    realized_cash = engine.account.cash
    assert realized_cash > Decimal("100.00")
    assert engine.account.total_locked_margin() == Decimal("0.00")

    # Restore valid manifest base so publish_candidate_admission can read prior manifest
    write_candidate_registry(
        manifest_path,
        build_candidate_registry_manifest(
            symbols={
                "BTCUSDT": CandidateManifestEntry(
                    candidate_id=cand_btc.candidate_id,
                    candidate_artifact_hash=cand_btc.artifact_hash,
                    artifact_path=str(storage_dir / "cand-btc-base.json"),
                    qualification_hash="1" * 64,
                    admitted_at=NOW.isoformat(),
                )
            },
            updated_at=NOW.isoformat(),
        ),
    )

    # Step 6: Perform 10 more reloads while flat
    for k in range(1, 11):
        c = _build_test_candidate(f"cand-btc-flat-{k}", symbol="BTCUSDT")
        c_file = storage_dir / f"cand-btc-flat-{k}.json"
        write_creator_candidate_artifact(c_file, c)
        publish_candidate_admission(
            manifest_path,
            "BTCUSDT",
            c.candidate_id,
            c.artifact_hash,
            c_file,
            f"{k:02d}" * 32,
            NOW + timedelta(minutes=3, seconds=k),
        )
        assert reloader.check_and_reload()
        # Invariant: realized cash remains exactly realized_cash and is NEVER restored to 100.00!
        assert engine.account.cash == realized_cash
        assert engine.account.total_locked_margin() == Decimal("0.00")
        assert engine.reconcile_balances()["zero_balance_drift"] is True

    # Step 7: Open Trade 2: Base margin calculated off new equity (> $100.00)
    opened_2 = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=NOW + timedelta(minutes=4)
    )
    assert opened_2 is not None
    assert engine.account.total_locked_margin() > Decimal("20.00")
    rec_final = engine.reconcile_balances()
    assert rec_final["zero_balance_drift"] is True
