"""Unit Test Suite for Phase 296 Autonomous Lifecycle Daemon & Multi-Session Longevity Runner.

Covers:
1. Daemon Initialization & Strict Paper-Safe Confinement (EXECUTION AUTHORITY: OFF, zero keys)
2. Multi-Session Longevity & State Continuity across Disjoint Sessions
3. Auto-Recovery & Disconnection Drills (disconnect, reconnect, quote cancellation)
4. Sequence Gap Detection & Packet Deduplication via PublicMarketStreamSequencer
5. Bounded Memory Management & Ring Buffers (maxlen guarantees)
6. Continuous Fail-Closed Risk Interlocks (Freshness, Clock drift, Hawkes rho, Loss budget)
7. Continuous Mathematical Double-Entry Zero-Drift Balance Governance (|drift| < 10^-15 USDT)
8. Research Artifact Persistence & SHA-256 Merkle DAG Hash Chain Linkage
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.autonomous_lifecycle import (
    DEFAULT_PHASE295_DIR,
    DOUBLE_ENTRY_MAX_DRIFT,
    AutonomousLifecycleDaemon,
    SessionStatus,
    persist_phase296_artifacts,
    verify_phase296_artifacts,
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

# =====================================================================
# Fixtures & Helper Functions
# =====================================================================


def make_depth(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    update_id: int = 1000,
    prev_id: int | None = None,
    ts: datetime | None = None,
) -> OrderBookDepthSnapshot:
    """Create test orderbook depth snapshot."""
    spread = Decimal("1.00")
    best_bid = price - spread / Decimal("2")
    best_ask = price + spread / Decimal("2")
    return OrderBookDepthSnapshot(
        symbol=symbol.upper(),
        bids=(
            OrderBookLevel(price=best_bid, quantity=Decimal("2.0")),
            OrderBookLevel(price=best_bid - Decimal("0.50"), quantity=Decimal("3.0")),
        ),
        asks=(
            OrderBookLevel(price=best_ask, quantity=Decimal("2.0")),
            OrderBookLevel(price=best_ask + Decimal("0.50"), quantity=Decimal("3.0")),
        ),
        last_update_id=update_id,
        prev_last_update_id=prev_id,
        event_time=ts or datetime.now(UTC),
    )


def make_trade(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    qty: Decimal = Decimal("0.05"),
    trade_id: int = 5000,
    is_buyer_maker: bool = False,
    ts: datetime | None = None,
) -> AggregateTrade:
    """Create test AggregateTrade."""
    return AggregateTrade(
        symbol=symbol.upper(),
        aggregate_trade_id=trade_id,
        price=price,
        quantity=qty,
        first_trade_id=trade_id * 10,
        last_trade_id=trade_id * 10 + 1,
        trade_time=ts or datetime.now(UTC),
        is_buyer_maker=is_buyer_maker,
    )


def make_mark(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    ts: datetime | None = None,
) -> MarkPriceSnapshot:
    """Create test MarkPriceSnapshot."""
    return MarkPriceSnapshot(
        symbol=symbol.upper(),
        mark_price=price,
        index_price=price,
        estimated_settle_price=price,
        funding_rate=Decimal("0.0001"),
        next_funding_time=(ts or datetime.now(UTC)) + timedelta(hours=8),
        event_time=ts or datetime.now(UTC),
    )


# =====================================================================
# 1. Daemon Bootstrap & Strict Paper-Safe Confinement
# =====================================================================


class TestAutonomousLifecycleDaemonBootstrap:
    """Test daemon initialization, candidate loading, and credential rejection."""

    def test_daemon_paper_safe_initialization(self) -> None:
        """Verify strict paper-safe defaults and execution authority off."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        assert daemon.paper_safe is True
        assert daemon.execution_authority is False
        assert daemon.starting_capital == Decimal("100.00")
        assert daemon.ledger.starting_equity == Decimal("100.00")
        assert daemon.ledger.cash == Decimal("100.00")
        assert daemon.ledger.allocated_margin == Decimal("0")
        assert daemon.ledger.realized_pnl == Decimal("0")
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_rejection_of_exchange_credentials(self) -> None:
        """Verify passing live API credentials immediately raises ValueError."""
        with pytest.raises(ValueError, match="strictly forbidden"):
            AutonomousLifecycleDaemon(api_key="live_secret_key_12345")

        with pytest.raises(ValueError, match="strictly forbidden"):
            AutonomousLifecycleDaemon(api_secret="live_api_secret_67890")

        with pytest.raises(ValueError, match="strictly forbidden"):
            AutonomousLifecycleDaemon(private_key="0xdeadbeef")

    def test_candidate_evaluation_and_promotion(self) -> None:
        """Verify candidates from Candidate Registry Manifest v2 are loaded and evaluated."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        assert len(daemon.bundles) == 3
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            assert sym in daemon.bundles
            assert sym in daemon.gate_records
            assert daemon.gate_records[sym].qualified is True
            assert daemon.state_machines[sym].is_executable is True


# =====================================================================
# 2. Multi-Session Longevity & State Continuity
# =====================================================================


class TestMultiSessionLongevityAndContinuity:
    """Test multi-session state preservation without equity resets or balance leakage."""

    def test_multi_session_state_preservation(self) -> None:
        """Verify equity, positions, and cash carry forward seamlessly across 3 sessions."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))

        # Session 1: open position and execute fill
        daemon.start_session("sess_001")
        d1 = make_depth("BTCUSDT", Decimal("60000.00"), 100)
        daemon.on_depth(d1)
        daemon.on_mark_price(make_mark("BTCUSDT", Decimal("60000.00")))

        orders, _ = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        assert len(orders) > 0
        fill_price = orders[0].price
        # Send fill with quantity exceeding queue_ahead to trigger execution
        daemon.on_trade(make_trade("BTCUSDT", fill_price, Decimal("5.0"), 200, is_buyer_maker=True))

        s1_cash = daemon.ledger.cash
        s1_margin = daemon.ledger.allocated_margin
        assert s1_margin > Decimal("0")
        daemon.end_session()

        # Session 2: State continuity check
        daemon.start_session("sess_002")
        assert daemon.ledger.cash == s1_cash
        assert daemon.ledger.allocated_margin == s1_margin
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True

        # Ingest ticks in Session 2
        d2 = make_depth("BTCUSDT", Decimal("60050.00"), 101, prev_id=100)
        daemon.on_depth(d2)
        daemon.on_mark_price(make_mark("BTCUSDT", Decimal("60050.00")))
        daemon.end_session()

        # Session 3: State continuity check
        daemon.start_session("sess_003")
        assert daemon.ledger.allocated_margin == s1_margin
        assert daemon.ledger.drift < DOUBLE_ENTRY_MAX_DRIFT
        daemon.end_session()

        assert len(daemon._sessions_history) == 3
        for s in daemon._sessions_history:
            assert s.zero_balance_drift is True
            assert Decimal(s.drift_usdt) < DOUBLE_ENTRY_MAX_DRIFT

    def test_session_audit_record_generation(self) -> None:
        """Verify each finalized session generates an immutable SessionRecord."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("audit_sess_1")
        daemon.on_depth(make_depth("BTCUSDT", Decimal("60000.00"), 10))
        rec = daemon.end_session()

        assert rec.session_id == "audit_sess_1"
        assert rec.ticks_processed >= 1
        assert rec.status == SessionStatus.COMPLETED.value
        assert rec.zero_balance_drift is True


# =====================================================================
# 3. Auto-Recovery & Disconnection Drills
# =====================================================================


class TestAutoRecoveryAndDisconnectionDrills:
    """Test simulated transport drops, keepalive resets, and auto-reconnection."""

    def test_simulate_disconnect_cancels_resting_orders(self) -> None:
        """Verify disconnect transitions state to DISCONNECTED and cancels active orders."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("disc_sess")
        daemon.on_depth(make_depth("BTCUSDT", Decimal("60000.00"), 10))

        # Place passive limit order without filling it
        orders, fills = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        assert len(orders) > 0
        assert len(daemon.matching_engine.get_active_orders()) > 0

        # Simulate disconnect
        daemon.simulate_disconnect(reason="tcp_reset")
        assert daemon._status == SessionStatus.DISCONNECTED
        assert daemon._disconnect_count == 1
        assert len(daemon.matching_engine.get_active_orders()) == 0

        # Events during disconnect are dropped
        accepted = daemon.on_depth(make_depth("BTCUSDT", Decimal("60010.00"), 11, prev_id=10))
        assert accepted is False

    def test_recover_connection_resumes_clean_event_loop(self) -> None:
        """Verify clean auto-recovery restores ACTIVE state and verifies zero-drift."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("rec_sess")
        daemon.simulate_disconnect(reason="network_timeout")
        daemon.recover_connection(reason="reconnected_ws")

        assert daemon._status == SessionStatus.ACTIVE
        assert daemon._reconnect_count == 1
        assert daemon._gateway_healthy is True

        # Now depth is accepted again
        accepted = daemon.on_depth(make_depth("BTCUSDT", Decimal("60000.00"), 20))
        assert accepted is True
        daemon.end_session()


# =====================================================================
# 4. Sequence Gap Detection & Packet Deduplication
# =====================================================================


class TestSequenceGapDetectionAndPacketDeduplication:
    """Test PublicMarketStreamSequencer integration, gap detection, and dedup filtering."""

    def test_depth_packet_deduplication(self) -> None:
        """Verify u <= last_u packets are dropped idempotently and logged."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("dedup_sess")

        d1 = make_depth("BTCUSDT", Decimal("60000.00"), update_id=500)
        assert daemon.on_depth(d1) is True

        # Duplicate depth packet (same update_id)
        d_dup = make_depth("BTCUSDT", Decimal("60000.00"), update_id=500, prev_id=499)
        assert daemon.on_depth(d_dup) is False
        assert daemon.sequencer.duplicate_count == 1
        assert len(daemon._dedup_event_records) == 1

        # Older depth packet (u < last_u)
        d_old = make_depth("BTCUSDT", Decimal("60000.00"), update_id=499)
        assert daemon.on_depth(d_old) is False
        assert daemon.sequencer.duplicate_count == 2
        daemon.end_session()

    def test_trade_packet_deduplication(self) -> None:
        """Verify a <= last_a trade packets are discarded without producing fills."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("trade_dedup_sess")

        t1 = make_trade("BTCUSDT", Decimal("60000.00"), Decimal("0.10"), trade_id=1000)
        daemon.on_trade(t1)

        # Duplicate trade
        t_dup = make_trade("BTCUSDT", Decimal("60000.00"), Decimal("0.10"), trade_id=1000)
        fills = daemon.on_trade(t_dup)
        assert len(fills) == 0
        assert daemon.sequencer.duplicate_count == 1
        daemon.end_session()

    def test_sequence_gap_detection(self) -> None:
        """Verify pu != last_u triggers sequence gap event and logging."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("gap_sess")

        d1 = make_depth("BTCUSDT", Decimal("60000.00"), update_id=100)
        daemon.on_depth(d1)

        # Ingest depth with gap (expected pu=100, received pu=110)
        d_gap = make_depth("BTCUSDT", Decimal("60000.00"), update_id=120, prev_id=110)
        accepted = daemon.on_depth(d_gap)
        assert accepted is True  # still processed, but gap recorded
        assert daemon.sequencer.sequence_gap_count == 1
        assert len(daemon._gap_event_records) == 1
        assert daemon._gap_event_records[0]["gap_size"] == 10
        daemon.end_session()


# =====================================================================
# 5. Bounded Memory Management & Ring Buffers
# =====================================================================


class TestBoundedMemoryManagementAndRingBuffers:
    """Test memory boundedness guarantees under high event throughput."""

    def test_bounded_deques_under_high_throughput(self) -> None:
        """Verify queue lengths never exceed their maxlen under thousands of ticks."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("memory_sess")

        # Ingest 1,500 ticks
        sym = "BTCUSDT"
        base_p = Decimal("60000.00")
        t0 = datetime.now(UTC)

        for i in range(1500):
            t_tick = t0 + timedelta(milliseconds=i * 10)
            daemon.on_mark_price(make_mark(sym, base_p + Decimal(i % 10), ts=t_tick))
            daemon.on_depth(make_depth(sym, base_p, update_id=1000 + i, prev_id=999 + i, ts=t_tick))
            daemon.on_trade(make_trade(sym, base_p, Decimal("0.01"), trade_id=5000 + i, ts=t_tick))

        assert len(daemon._trade_history[sym]) <= 500
        assert len(daemon._depth_history[sym]) <= 100
        assert len(daemon._mark_history[sym]) <= 100
        assert len(daemon._feed_packet_records) <= 2000
        assert len(daemon._gap_event_records) <= 500
        assert len(daemon._dedup_event_records) <= 500
        daemon.end_session()


# =====================================================================
# 6. Continuous Fail-Closed Risk Interlocks
# =====================================================================


class TestContinuousFailClosedRiskInterlocks:
    """Test prioritized fail-closed risk circuit breakers."""

    def test_hawkes_supercritical_lockout(self) -> None:
        """Verify spectral radius rho >= 1.0 halts order placement fail-closed."""
        daemon = AutonomousLifecycleDaemon(simulate_supercritical_hawkes=True)
        daemon.start_session("hawkes_lockout_sess")
        daemon.on_depth(make_depth("BTCUSDT", Decimal("60000.00"), 10))

        orders, fills = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        assert len(orders) == 0
        assert len(fills) == 0
        assert any("Hawkes supercritical" in str(it.reason) for it in daemon._interlock_events)
        daemon.end_session()

    def test_stale_gateway_heartbeat_veto(self) -> None:
        """Verify heartbeat age > 500 ms blocks order generation."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("stale_hb_sess")
        daemon.on_depth(make_depth("BTCUSDT", Decimal("60000.00"), 10))

        # Inject stale heartbeat age
        daemon._last_heartbeat_age_ms = 600.0
        orders, fills = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        assert len(orders) == 0
        assert any("Gateway heartbeat age" in str(it.reason) for it in daemon._interlock_events)
        daemon.end_session()

    def test_clock_skew_breach_veto(self) -> None:
        """Verify clock skew > 250 ms blocks order generation."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("clock_skew_sess")
        daemon.on_depth(make_depth("BTCUSDT", Decimal("60000.00"), 10))

        # Inject clock drift
        daemon._server_clock_drift_ms = 350.0
        orders, fills = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        assert len(orders) == 0
        assert any("Clock skew" in str(it.reason) for it in daemon._interlock_events)
        daemon.end_session()

    def test_emergency_flattening_on_loss_breach(self) -> None:
        """Verify intra-phase cumulative loss >= 7 USDT triggers emergency flattening."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("loss_breach_sess")
        d = make_depth("BTCUSDT", Decimal("60000.00"), 10)
        daemon.on_depth(d)

        # Open a position
        orders, _ = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        fill_price = orders[0].price
        daemon.on_trade(make_trade("BTCUSDT", fill_price, Decimal("5.0"), 200, is_buyer_maker=True))
        assert daemon.ledger.allocated_margin > Decimal("0")

        # Simulate intra-phase loss breach
        daemon.risk.cumulative_loss = Decimal("7.50")
        daemon.risk.circuit_state = "INTRA_PHASE_LOSS_LOCKOUT"

        flatten_fills = daemon.trigger_emergency_flattening(reason="unit_test_loss_breach")
        assert len(flatten_fills) > 0
        assert daemon.ledger.allocated_margin == Decimal("0")
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        daemon.end_session()

    def test_evaluate_strategy_emergency_flattening_on_loss_lockout(self) -> None:
        """Verify evaluate_strategy() automatically executes emergency flattening on loss breach."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("loss_lockout_eval_sess")
        d = make_depth("BTCUSDT", Decimal("60000.00"), 10)
        daemon.on_depth(d)

        # Open a position
        orders, _ = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        fill_price = orders[0].price
        daemon.on_trade(make_trade("BTCUSDT", fill_price, Decimal("5.0"), 200, is_buyer_maker=True))
        assert daemon.ledger.allocated_margin > Decimal("0")

        # Simulate intra-phase loss breach
        daemon.risk.cumulative_loss = Decimal("7.50")

        # Next evaluate_strategy must flatten existing positions and return zero new orders
        new_orders, flatten_fills = daemon.evaluate_strategy(
            symbol="BTCUSDT", force_side=OrderSide.BUY
        )
        assert len(new_orders) == 0
        assert len(flatten_fills) > 0
        assert daemon.ledger.allocated_margin == Decimal("0")
        assert "BTCUSDT" not in daemon.ledger.positions or daemon.ledger.positions[
            "BTCUSDT"
        ].quantity == Decimal("0")
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        daemon.end_session()


# =====================================================================
# 7. Continuous Double-Entry Zero-Drift Balance Governance
# =====================================================================


class TestContinuousDoubleEntryZeroDriftLedger:
    """Test exact mathematical balance invariant: Cash + Margin + Unrealized = Equity + Realized."""

    def test_zero_drift_across_multiple_fills_and_marks(self) -> None:
        """Verify absolute drift |drift| < 10^-15 USDT holds across fills, fees, and mark prices."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("drift_check_sess")
        sym = "BTCUSDT"

        d = make_depth(sym, Decimal("60000.00"), 10)
        daemon.on_depth(d)
        daemon.on_mark_price(make_mark(sym, Decimal("60000.00")))

        # Order placement & fill
        orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        fill_p = orders[0].price
        daemon.on_trade(make_trade(sym, fill_p, Decimal("10.0"), 20, is_buyer_maker=True))

        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT

        # Mark price move (creates unrealized PnL)
        daemon.on_mark_price(make_mark(sym, Decimal("61000.00")))
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT

        daemon.end_session()

    def test_synthetic_drift_raises_double_entry_drift_error(self) -> None:
        """Verify synthetic drift corruption immediately raises DoubleEntryDriftError."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("corrupt_sess")

        # Synthetically corrupt cash
        daemon.ledger.cash += Decimal("0.05")
        with pytest.raises(DoubleEntryDriftError, match="exceeds tolerance"):
            daemon.verify_zero_drift()


# =====================================================================
# 8. Research Artifact Persistence & Merkle DAG Linkage
# =====================================================================


class TestArtifactPersistenceAndMerkleDAG:
    """Test SQLite schema creation, JSONL serialization, and SHA-256 Merkle DAG hash chaining."""

    def test_persist_and_verify_phase296_artifacts(self, tmp_path: Path) -> None:
        """Verify all 5 artifacts are persisted and verified via SHA-256 Merkle DAG."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("persist_sess")

        d = make_depth("BTCUSDT", Decimal("60000.00"), 100)
        daemon.on_depth(d)
        daemon.on_mark_price(make_mark("BTCUSDT", Decimal("60000.00")))

        orders, _ = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        if orders:
            daemon.on_trade(
                make_trade("BTCUSDT", orders[0].price, Decimal("5.0"), 200, is_buyer_maker=True)
            )

        daemon.end_session()

        out_dir = tmp_path / "artifacts" / "phase296"
        hashes = persist_phase296_artifacts(
            output_dir=out_dir,
            daemon=daemon,
            upstream_dir=DEFAULT_PHASE295_DIR,
        )

        assert "canary-lifecycle-telemetry.sqlite3" in hashes
        assert "canary-orders.jsonl" in hashes
        assert "canary-lifecycle-report.json" in hashes
        assert "lifecycle-summary.json" in hashes
        assert "paper-summary.json" in hashes

        # Verify all 5 files exist on disk
        for fname in hashes:
            assert (out_dir / fname).exists()

        # Verify Merkle DAG chain
        verified = verify_phase296_artifacts(
            phase296_dir=out_dir, phase295_dir=DEFAULT_PHASE295_DIR
        )
        assert verified is True

    def test_tampered_artifact_fails_verification(self, tmp_path: Path) -> None:
        """Verify tampering with a persisted artifact invalidates the Merkle DAG hash chain."""
        daemon = AutonomousLifecycleDaemon()
        daemon.start_session("tamper_sess")
        daemon.on_depth(make_depth("BTCUSDT", Decimal("60000.00"), 10))
        daemon.end_session()

        out_dir = tmp_path / "artifacts" / "phase296"
        persist_phase296_artifacts(
            output_dir=out_dir,
            daemon=daemon,
            upstream_dir=DEFAULT_PHASE295_DIR,
        )

        # Tamper with canary-orders.jsonl
        orders_file = out_dir / "canary-orders.jsonl"
        orders_file.write_text("tampered_content\n", encoding="utf-8")

        verified = verify_phase296_artifacts(
            phase296_dir=out_dir, phase295_dir=DEFAULT_PHASE295_DIR
        )
        assert verified is False
