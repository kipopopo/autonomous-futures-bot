"""Unit Test Suite for Phase 297 Stress Fault Injection, Circuit Breakers & Auto-Flattening.

Covers:
1. MarketFaultInjector shock vector lifecycle & stream transformations (Flash Crash, Evaporation)
2. OnlineStressEvaluationEngine sub-millisecond anomaly detection (< 1 ms latency)
3. Fail-Closed Risk Interlocks (SPREAD_SHOCK_VETO, Hawkes supercritical lockout, Telemetry freeze)
4. Emergency Auto-Flattening (micro-chunking <= 5.00 USDT, quote purging, HALTED transition)
5. Continuous Mathematical Double-Entry Zero-Drift Balance Governance (|drift| < 10^-15 USDT)
6. Cryptographic Merkle DAG Hash Chain Linkage & Tamper Detection (chained to Phase 296 parent hash)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.autonomous_lifecycle import (
    DOUBLE_ENTRY_MAX_DRIFT,
    AutonomousLifecycleDaemon,
    SessionStatus,
)
from autonomous_futures.feed.models import (
    AggregateTrade,
    MarkPriceSnapshot,
    OrderBookDepthSnapshot,
    OrderBookLevel,
)
from autonomous_futures.feed.paper_execution import (
    OrderSide,
)
from autonomous_futures.feed.paper_ledger import (
    DoubleEntryDriftError,
)
from autonomous_futures.feed.paper_risk import (
    SPREAD_SHOCK_THRESHOLD_PCT,
    CircuitState,
    InterlockCode,
    LivePaperRiskInterlock,
)
from autonomous_futures.feed.stress_fault_injection import (
    PHASE296_PARENT_HASH_EXPECTED,
    SUB_MS_LATENCY_CEILING_US,
    MarketFaultInjector,
    OnlineStressEvaluationEngine,
    ShockConfiguration,
    ShockVectorType,
    StressCircuitState,
    init_phase297_sqlite_telemetry,
    persist_phase297_artifacts,
    verify_phase297_artifacts,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# =====================================================================
# Fixtures & Helpers
# =====================================================================


def _make_depth(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    update_id: int = 1000,
    prev_id: int | None = None,
    spread: Decimal = Decimal("1.00"),
    ts: datetime | None = None,
) -> OrderBookDepthSnapshot:
    best_bid = price - spread / Decimal("2")
    best_ask = price + spread / Decimal("2")
    bids = tuple(
        OrderBookLevel(price=best_bid - Decimal(i * 10), quantity=Decimal("0.5000"))
        for i in range(5)
    )
    asks = tuple(
        OrderBookLevel(price=best_ask + Decimal(i * 10), quantity=Decimal("0.5000"))
        for i in range(5)
    )
    return OrderBookDepthSnapshot(
        symbol=symbol.upper(),
        bids=bids,
        asks=asks,
        last_update_id=update_id,
        prev_last_update_id=prev_id,
        event_time=ts or datetime.now(UTC),
    )


def _make_mark(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    ts: datetime | None = None,
) -> MarkPriceSnapshot:
    t_now = ts or datetime.now(UTC)
    return MarkPriceSnapshot(
        symbol=symbol.upper(),
        mark_price=price,
        index_price=price,
        estimated_settle_price=price,
        funding_rate=Decimal("0.0001"),
        next_funding_time=t_now + timedelta(hours=8),
        event_time=t_now,
    )


def _make_trade(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    qty: Decimal = Decimal("0.05"),
    trade_id: int = 1,
    is_buyer_maker: bool = True,
    ts: datetime | None = None,
) -> AggregateTrade:
    t_now = ts or datetime.now(UTC)
    return AggregateTrade(
        symbol=symbol.upper(),
        aggregate_trade_id=trade_id,
        price=price,
        quantity=qty,
        first_trade_id=trade_id,
        last_trade_id=trade_id,
        trade_time=t_now,
        is_buyer_maker=is_buyer_maker,
    )


@pytest.fixture
def temp_daemon(tmp_path: Path) -> AutonomousLifecycleDaemon:
    return AutonomousLifecycleDaemon(
        starting_capital=Decimal("100.00"),
        registry_path=tmp_path / "registry.json",
        repo_root=_REPO_ROOT,
    )


@pytest.fixture
def temp_engine(temp_daemon: AutonomousLifecycleDaemon) -> OnlineStressEvaluationEngine:
    injector = MarketFaultInjector(symbols=tuple(temp_daemon.symbols))
    return OnlineStressEvaluationEngine(
        daemon=temp_daemon,
        injector=injector,
        loss_budget_usdt=Decimal("7.00"),
    )


# =====================================================================
# 1. MarketFaultInjector Tests
# =====================================================================


class TestMarketFaultInjector:
    """Test suite for MarketFaultInjector shock lifecycle and feed mutations."""

    def test_injector_initialization_paper_safe(self) -> None:
        injector = MarketFaultInjector(symbols=("BTCUSDT", "ETHUSDT"))
        assert injector.paper_safe is True
        assert injector.execution_authority is False
        assert len(injector.active_shocks) == 0

    def test_reject_credentials(self) -> None:
        with pytest.raises(ValueError, match="forbidden"):
            MarketFaultInjector(
                symbols=("BTCUSDT",),
                api_key="leaked_key_123",  # type: ignore[call-arg]
            )

    def test_arm_and_disarm_shocks(self) -> None:
        injector = MarketFaultInjector(symbols=("BTCUSDT", "ETHUSDT"))
        cfg1 = ShockConfiguration(
            shock_type=ShockVectorType.FLASH_CRASH,
            target_symbols=("BTCUSDT",),
            price_drop_pct=Decimal("0.20"),
        )
        injector.arm_shock(cfg1)
        assert injector.is_shock_active(ShockVectorType.FLASH_CRASH, "BTCUSDT")
        assert not injector.is_shock_active(ShockVectorType.FLASH_CRASH, "ETHUSDT")

        injector.disarm_shock(ShockVectorType.FLASH_CRASH)
        assert not injector.is_shock_active(ShockVectorType.FLASH_CRASH, "BTCUSDT")

    def test_disarm_all(self) -> None:
        injector = MarketFaultInjector(symbols=("BTCUSDT", "ETHUSDT"))
        injector.arm_shock(
            ShockConfiguration(
                shock_type=ShockVectorType.LIQUIDITY_EVAPORATION,
                target_symbols=("BTCUSDT",),
            )
        )
        injector.arm_shock(
            ShockConfiguration(
                shock_type=ShockVectorType.TELEMETRY_DEGRADATION,
                target_symbols=("ETHUSDT",),
            )
        )
        assert len(injector.active_shocks) == 2
        injector.disarm_all()
        assert len(injector.active_shocks) == 0

    def test_transform_depth_flash_crash(self) -> None:
        injector = MarketFaultInjector(symbols=("BTCUSDT",))
        injector.arm_shock(
            ShockConfiguration(
                shock_type=ShockVectorType.FLASH_CRASH,
                target_symbols=("BTCUSDT",),
                price_drop_pct=Decimal("0.20"),  # -20%
            )
        )
        depth = _make_depth("BTCUSDT", price=Decimal("60000.00"))
        mutated, was_mut = injector.transform_depth(depth)
        assert was_mut is True
        assert mutated.best_bid_price is not None
        assert mutated.best_ask_price is not None
        # Original mid was 60000, 20% drop -> ~48000
        assert mutated.best_bid_price < Decimal("49000.00")
        assert mutated.best_bid_price < mutated.best_ask_price

    def test_transform_depth_liquidity_evaporation(self) -> None:
        injector = MarketFaultInjector(symbols=("BTCUSDT",))
        injector.arm_shock(
            ShockConfiguration(
                shock_type=ShockVectorType.LIQUIDITY_EVAPORATION,
                target_symbols=("BTCUSDT",),
                spread_pct=Decimal("0.10"),  # 10.0% wide spread
                depth_depletion_pct=Decimal("0.95"),  # 95% depleted
            )
        )
        depth = _make_depth("BTCUSDT", price=Decimal("60000.00"))
        mutated, was_mut = injector.transform_depth(depth)
        assert was_mut is True
        assert mutated.best_bid_price is not None
        assert mutated.best_ask_price is not None
        spread_pct = (
            (mutated.best_ask_price - mutated.best_bid_price) / mutated.best_bid_price
        ) * Decimal("100")
        assert spread_pct >= Decimal("9.50")
        # Depth quantity should be depleted
        assert mutated.bids[0].quantity < depth.bids[0].quantity

    def test_transform_depth_phantom_asymmetry(self) -> None:
        injector = MarketFaultInjector(symbols=("BTCUSDT",))
        injector.arm_shock(
            ShockConfiguration(
                shock_type=ShockVectorType.PHANTOM_DEPTH_SPOOFING,
                target_symbols=("BTCUSDT",),
                asymmetry_ratio=Decimal("0.98"),
            )
        )
        depth = _make_depth("BTCUSDT", price=Decimal("60000.00"))
        mutated, was_mut = injector.transform_depth(depth)
        assert was_mut is True
        tot_bid = sum(lvl.quantity for lvl in mutated.bids)
        tot_ask = sum(lvl.quantity for lvl in mutated.asks)
        i_depth = abs(tot_bid - tot_ask) / (tot_bid + tot_ask)
        assert i_depth > Decimal("0.95")

    def test_transform_telemetry(self) -> None:
        injector = MarketFaultInjector(symbols=("BTCUSDT",))
        injector.arm_shock(
            ShockConfiguration(
                shock_type=ShockVectorType.TELEMETRY_DEGRADATION,
                clock_skew_ms=750.0,
                silence_duration_ms=800,
            )
        )
        age, skew, was_mut = injector.transform_telemetry(10.0, 5.0)
        assert was_mut is True
        assert age >= 800.0
        assert skew >= 750.0


# =====================================================================
# 2. OnlineStressEvaluationEngine Tests
# =====================================================================


class TestOnlineStressEvaluationEngine:
    """Test suite for OnlineStressEvaluationEngine and sub-ms breaker evaluation."""

    def test_sub_millisecond_latency_compliance(
        self, temp_engine: OnlineStressEvaluationEngine
    ) -> None:
        sym = "BTCUSDT"
        depth = _make_depth(sym, price=Decimal("60000.00"))
        trade = _make_trade(sym, price=Decimal("60000.00"))
        mark = _make_mark(sym, price=Decimal("60000.00"))

        latencies: list[float] = []
        for _ in range(50):
            tripped, reason, lat_us = temp_engine.evaluate_microstructure_tick(
                symbol=sym, depth=depth, trade=trade, mark=mark, hawkes_rho=Decimal("0.35")
            )
            assert not tripped
            latencies.append(lat_us)
            assert lat_us < SUB_MS_LATENCY_CEILING_US, (
                f"Latency {lat_us:.2f} us breached 1 ms ceiling"
            )

        mean_us = sum(latencies) / len(latencies)
        assert mean_us < 500.0, f"Average latency {mean_us:.2f} us exceeded 500 us"

    def test_telemetry_heartbeat_stale_trip(
        self, temp_engine: OnlineStressEvaluationEngine
    ) -> None:
        tripped, reason, lat_us = temp_engine.evaluate_microstructure_tick(
            symbol="BTCUSDT",
            heartbeat_age_ms=650.0,  # > 500 ms
        )
        assert tripped is True
        assert "heartbeat age" in reason
        assert temp_engine.circuit_state == StressCircuitState.HALTED
        assert lat_us < SUB_MS_LATENCY_CEILING_US

    def test_telemetry_clock_skew_trip(self, temp_engine: OnlineStressEvaluationEngine) -> None:
        tripped, reason, lat_us = temp_engine.evaluate_microstructure_tick(
            symbol="BTCUSDT",
            clock_skew_ms=550.0,  # > 500 ms
        )
        assert tripped is True
        assert "Clock skew" in reason
        assert temp_engine.circuit_state == StressCircuitState.CLOCK_SKEW_FREEZE
        assert lat_us < SUB_MS_LATENCY_CEILING_US

    def test_hawkes_supercritical_cascade_lockout(
        self, temp_engine: OnlineStressEvaluationEngine
    ) -> None:
        tripped, reason, lat_us = temp_engine.evaluate_microstructure_tick(
            symbol="BTCUSDT",
            hawkes_rho=Decimal("1.15"),  # >= 1.0
        )
        assert tripped is True
        assert "Hawkes supercritical" in reason
        assert temp_engine.circuit_state == StressCircuitState.SUPERCRITICAL_CASCADE_LOCKOUT
        assert lat_us < SUB_MS_LATENCY_CEILING_US

    def test_relative_spread_shock_trip(self, temp_engine: OnlineStressEvaluationEngine) -> None:
        # Create wide depth with spread > 1.0% (100 bps)
        wide_depth = _make_depth(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            spread=Decimal("1200.00"),  # 2.0%
        )
        tripped, reason, lat_us = temp_engine.evaluate_microstructure_tick(
            symbol="BTCUSDT",
            depth=wide_depth,
        )
        assert tripped is True
        assert "Relative spread" in reason
        assert temp_engine.circuit_state == StressCircuitState.ELEVATED_CONTROLS
        assert lat_us < SUB_MS_LATENCY_CEILING_US

    def test_phantom_depth_extreme_asymmetry_trip(
        self, temp_engine: OnlineStressEvaluationEngine
    ) -> None:
        # Construct highly asymmetric depth
        bids = tuple(
            OrderBookLevel(price=Decimal("59990.00") - Decimal(i * 10), quantity=Decimal("100.0"))
            for i in range(5)
        )
        asks = tuple(
            OrderBookLevel(price=Decimal("60010.00") + Decimal(i * 10), quantity=Decimal("0.01"))
            for i in range(5)
        )
        asym_depth = OrderBookDepthSnapshot(
            symbol="BTCUSDT",
            bids=bids,
            asks=asks,
            last_update_id=1200,
            event_time=datetime.now(UTC),
        )
        tripped, reason, lat_us = temp_engine.evaluate_microstructure_tick(
            symbol="BTCUSDT",
            depth=asym_depth,
        )
        assert tripped is True
        assert "Extreme orderbook asymmetry" in reason
        assert temp_engine.circuit_state == StressCircuitState.ELEVATED_CONTROLS

    def test_flash_crash_sub_ms_auto_flattening(
        self,
        temp_daemon: AutonomousLifecycleDaemon,
        temp_engine: OnlineStressEvaluationEngine,
    ) -> None:
        sym = "BTCUSDT"
        base_price = Decimal("60000.00")
        t0 = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

        temp_daemon.start_session("unit_flash_crash_001")
        temp_daemon.on_depth(_make_depth(sym, base_price, update_id=100, ts=t0))
        temp_daemon.on_mark_price(_make_mark(sym, base_price, ts=t0))

        # Open a long position
        orders, _ = temp_daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders) > 0
        fill_price = orders[0].price
        trade_fill = _make_trade(
            sym, fill_price, Decimal("5.0"), trade_id=5000, is_buyer_maker=True, ts=t0
        )
        temp_daemon.on_trade(trade_fill)
        assert temp_daemon.ledger.allocated_margin > Decimal("0")

        # Arm and inject Flash Crash Shock (-20%)
        temp_engine.injector.arm_shock(
            ShockConfiguration(
                shock_type=ShockVectorType.FLASH_CRASH,
                target_symbols=(sym,),
                price_drop_pct=Decimal("0.20"),
            )
        )
        crashed_depth, _ = temp_engine.injector.transform_depth(
            _make_depth(sym, base_price, update_id=101, prev_id=100, ts=t0)
        )
        crashed_mark, _ = temp_engine.injector.transform_mark_price(
            _make_mark(sym, base_price, ts=t0)
        )
        crashed_trade, _ = temp_engine.injector.transform_trade(trade_fill)

        temp_daemon.on_depth(crashed_depth)
        temp_daemon.on_mark_price(crashed_mark)
        temp_daemon.on_trade(crashed_trade)

        # Microstructure evaluation trips and auto-flattens
        tripped, reason, lat_us = temp_engine.evaluate_microstructure_tick(
            symbol=sym,
            depth=crashed_depth,
            trade=crashed_trade,
            mark=crashed_mark,
        )

        assert tripped is True
        assert lat_us < SUB_MS_LATENCY_CEILING_US
        # Open position must be flattened
        assert temp_daemon.ledger.allocated_margin == Decimal("0")
        assert temp_daemon.risk.circuit_state == CircuitState.HALTED
        assert temp_daemon.get_status() == SessionStatus.HALTED
        assert temp_engine.circuit_state == StressCircuitState.HALTED

        # Intra-phase loss capped within 7.00 USDT budget
        pnl = temp_daemon.ledger.realized_pnl
        loss = abs(pnl) if pnl < Decimal("0") else Decimal("0")
        assert loss <= Decimal("7.00")
        assert temp_daemon.ledger.total_equity > Decimal("0")

        # Zero balance drift preserved
        is_valid, drift = temp_engine.assert_double_entry_zero_drift()
        assert is_valid
        assert drift == Decimal("0")

        temp_daemon.end_session()

    def test_latencies_summary_metrics(self, temp_engine: OnlineStressEvaluationEngine) -> None:
        sym = "BTCUSDT"
        for _ in range(5):
            temp_engine.evaluate_microstructure_tick(symbol=sym, heartbeat_age_ms=600.0)

        summary = temp_engine.get_reaction_latencies_summary()
        assert summary["count"] == 5
        assert summary["sub_millisecond_compliant"] is True
        assert summary["max_us"] < SUB_MS_LATENCY_CEILING_US


# =====================================================================
# 3. Risk Interlock SPREAD_SHOCK_VETO Tests
# =====================================================================


class TestRiskInterlockSpreadShockVeto:
    """Test suite for SPREAD_SHOCK_VETO interlock behavior."""

    def test_spread_shock_threshold_constant(self) -> None:
        assert SPREAD_SHOCK_THRESHOLD_PCT == Decimal("1.00")

    def test_spread_shock_veto_blocks_proposed_order(self) -> None:
        risk = LivePaperRiskInterlock(starting_equity=Decimal("100.00"))
        # Spread is 2.50% (> 1.00%)
        decision = risk.validate_pre_trade_interlocks(
            symbol="BTCUSDT",
            proposed_notional=Decimal("4.50"),
            bid_ask_spread_pct=Decimal("2.50"),
        )
        assert decision.allowed is False
        assert decision.code == InterlockCode.SPREAD_SHOCK_VETO
        assert "Relative spread" in str(decision.reason)

    def test_normal_spread_allows_order(self) -> None:
        risk = LivePaperRiskInterlock(starting_equity=Decimal("100.00"))
        # Spread is 0.05% (< 1.00%)
        decision = risk.validate_pre_trade_interlocks(
            symbol="BTCUSDT",
            proposed_notional=Decimal("4.50"),
            bid_ask_spread_pct=Decimal("0.05"),
        )
        assert decision.allowed is True
        assert decision.code == InterlockCode.NORMAL


# =====================================================================
# 4. Continuous Double-Entry Balance Governance Tests
# =====================================================================


class TestContinuousDoubleEntryZeroDrift:
    """Test suite for continuous mathematical zero-drift balance validation."""

    def test_zero_drift_across_lifecycle_events(
        self, temp_daemon: AutonomousLifecycleDaemon
    ) -> None:
        sym = "BTCUSDT"
        t0 = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
        temp_daemon.start_session("unit_drift_session_001")

        for i in range(15):
            t_now = t0 + timedelta(seconds=i)
            bp = Decimal("60000.00") + Decimal(i * 5)
            temp_daemon.on_mark_price(_make_mark(sym, bp, ts=t_now))
            temp_daemon.on_depth(_make_depth(sym, bp, update_id=200 + i, ts=t_now))
            temp_daemon.on_trade(_make_trade(sym, bp, Decimal("0.05"), trade_id=300 + i, ts=t_now))

        is_valid, drift = temp_daemon.verify_zero_drift()
        assert is_valid
        assert abs(drift) < Decimal(DOUBLE_ENTRY_MAX_DRIFT)

        temp_daemon.end_session()

    def test_corrupted_balance_triggers_drift_error(
        self, temp_daemon: AutonomousLifecycleDaemon
    ) -> None:
        temp_daemon.start_session("unit_drift_corrupt")
        # Artificially corrupt cash balance
        temp_daemon.ledger.cash += Decimal("0.50")
        with pytest.raises(DoubleEntryDriftError):
            temp_daemon.ledger.verify_zero_drift()
        # Restore balance so end_session does not raise
        temp_daemon.ledger.cash -= Decimal("0.50")
        temp_daemon.end_session()


# =====================================================================
# 5. Cryptographic Merkle DAG Persistence & Integrity Tests
# =====================================================================


class TestMerkleDAGPersistenceAndIntegrity:
    """Test suite for Phase 297 artifact persistence and Merkle DAG verification."""

    def test_telemetry_sqlite_initialization(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test-stress-telemetry.sqlite3"
        init_phase297_sqlite_telemetry(db_path)
        assert db_path.exists()
        assert db_path.stat().st_size > 0

    def test_persist_and_verify_artifacts(
        self, tmp_path: Path, temp_daemon: AutonomousLifecycleDaemon
    ) -> None:
        output_dir = tmp_path / "artifacts" / "phase297"
        output_dir.mkdir(parents=True, exist_ok=True)

        engine = OnlineStressEvaluationEngine(daemon=temp_daemon)

        # Record a test reaction record
        engine.evaluate_microstructure_tick(symbol="BTCUSDT", heartbeat_age_ms=600.0)

        # Persist artifacts chained to Phase 296 parent hash
        artifact_hashes = persist_phase297_artifacts(
            engine=engine,
            output_dir=output_dir,
            upstream_dir=tmp_path / "non_existent",
            manifest_version=2,
        )

        assert "canary-stress-telemetry.sqlite3" in artifact_hashes
        assert "stress-summary.json" in artifact_hashes
        assert "paper-summary.json" in artifact_hashes

        summary_file = output_dir / "stress-summary.json"
        assert summary_file.exists()
        data = json.loads(summary_file.read_text(encoding="utf-8"))
        assert data["phase"] == "phase_297"
        assert data["upstream_merkle_dag"]["phase296_summary_hash"] == PHASE296_PARENT_HASH_EXPECTED

        # Verify integrity
        is_valid = verify_phase297_artifacts(
            phase297_dir=output_dir,
            phase296_dir=tmp_path / "non_existent",
        )
        assert is_valid is True

    def test_tamper_detection_fails_verification(
        self, tmp_path: Path, temp_daemon: AutonomousLifecycleDaemon
    ) -> None:
        output_dir = tmp_path / "artifacts" / "phase297_tamper"
        output_dir.mkdir(parents=True, exist_ok=True)

        engine = OnlineStressEvaluationEngine(daemon=temp_daemon)
        persist_phase297_artifacts(
            engine=engine,
            output_dir=output_dir,
            upstream_dir=tmp_path / "non_existent",
            manifest_version=2,
        )

        # Tamper with an artifact by appending corrupted data
        orders_file = output_dir / "canary-orders.jsonl"
        with open(orders_file, "a", encoding="utf-8") as f:
            f.write('{"tampered": true}\n')

        # Verify must fail
        is_valid = verify_phase297_artifacts(
            phase297_dir=output_dir,
            phase296_dir=tmp_path / "non_existent",
        )
        assert is_valid is False
