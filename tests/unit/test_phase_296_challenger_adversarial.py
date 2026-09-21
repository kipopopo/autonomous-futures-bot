"""Empirical Adversarial Stress Test Suite for Phase 296 Autonomous Lifecycle Daemon.

Challenger 1 Adversarial Harness:
1. High-throughput packet ingestion with synthetic burst anomalies:
   - Duplicated depth and trade packets discarded without downstream contamination.
   - Sequence gaps (pu != last_u) detected and persisted in SQLite gap_events.
   - Multi-symbol anomaly isolation.
2. Rapid disconnect/reconnect cycling:
   - Successive rapid disconnects and reconnects without deadlock or state corruption.
   - Immediate purging of resting quotes on disconnect.
   - Preservation of open positions, cash, and allocated margin.
   - Strict quarantine during disconnected state.
3. Supercritical runaway and loss budget lockout:
   - Hawkes supercritical spike (rho >= 1.0) immediate fail-closed lockout.
   - Adverse loss exceeding 7.00 USDT triggers emergency flattening and fail-closed rejection.
   - Sub-cent boundary validation (6.99 vs 7.00 vs 7.01 USDT).
4. Continuous mathematical double-entry balance drift strictly |drift| < 10^-15 USDT.
"""

from __future__ import annotations

import sqlite3
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
from autonomous_futures.feed.paper_risk import (
    CircuitState,
)

# =====================================================================
# Synthetic Generator Helpers
# =====================================================================


def _build_depth(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    update_id: int = 1000,
    prev_id: int | None = None,
    spread: Decimal = Decimal("1.00"),
    ts: datetime | None = None,
) -> OrderBookDepthSnapshot:
    """Construct deterministic top-5 depth snapshot."""
    event_time = ts or datetime.now(UTC)
    half_spread = spread / Decimal("2")
    best_bid = price - half_spread
    best_ask = price + half_spread
    step = spread / Decimal("5")

    bids = tuple(
        OrderBookLevel(price=best_bid - (step * Decimal(i)), quantity=Decimal("2.0") + Decimal(i))
        for i in range(5)
    )
    asks = tuple(
        OrderBookLevel(price=best_ask + (step * Decimal(i)), quantity=Decimal("2.0") + Decimal(i))
        for i in range(5)
    )

    return OrderBookDepthSnapshot(
        symbol=symbol.upper(),
        bids=bids,
        asks=asks,
        last_update_id=update_id,
        prev_last_update_id=prev_id,
        event_time=event_time,
    )


def _build_trade(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    quantity: Decimal = Decimal("0.05"),
    trade_id: int = 5000,
    is_buyer_maker: bool = False,
    ts: datetime | None = None,
) -> AggregateTrade:
    """Construct deterministic AggregateTrade."""
    return AggregateTrade(
        symbol=symbol.upper(),
        aggregate_trade_id=trade_id,
        price=price,
        quantity=quantity,
        first_trade_id=trade_id * 10,
        last_trade_id=trade_id * 10 + 1,
        trade_time=ts or datetime.now(UTC),
        is_buyer_maker=is_buyer_maker,
    )


def _build_mark(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("60000.00"),
    ts: datetime | None = None,
) -> MarkPriceSnapshot:
    """Construct deterministic MarkPriceSnapshot."""
    now = ts or datetime.now(UTC)
    return MarkPriceSnapshot(
        symbol=symbol.upper(),
        mark_price=price,
        index_price=price,
        estimated_settle_price=price,
        funding_rate=Decimal("0.0001"),
        next_funding_time=now + timedelta(hours=8),
        event_time=now,
    )


# =====================================================================
# 1. High-Throughput Packet Ingestion & Deduplication Stress
# =====================================================================


class TestAdversarialBurstIngestionAndDeduplication:
    """Stress-test deduplication, sequence gap detection, and downstream isolation."""

    def test_adversarial_depth_duplicate_burst(self) -> None:
        """Verify 500 depth packets with 250 duplicate anomalies are dropped cleanly."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("adv_depth_dedup_sess")
        sym = "BTCUSDT"
        base_p = Decimal("60000.00")

        accepted_count = 0
        rejected_count = 0
        seq = 1000

        for _ in range(250):
            seq += 1
            nominal_depth = _build_depth(sym, base_p, update_id=seq, prev_id=seq - 1)
            accepted = daemon.on_depth(nominal_depth)
            if accepted:
                accepted_count += 1

            # Inject duplicate (same update_id)
            dup_depth = _build_depth(sym, base_p, update_id=seq, prev_id=seq - 1)
            dup_accepted = daemon.on_depth(dup_depth)
            if not dup_accepted:
                rejected_count += 1

        assert accepted_count == 250
        assert rejected_count == 250
        assert daemon.sequencer.duplicate_count == 250
        assert len(daemon._dedup_event_records) == 250

        # Verify internal history queue contains only unique accepted packets
        assert len(daemon._depth_history[sym]) <= 100  # bounded deque maxlen 100

        # Verify zero drift after burst ingestion
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        daemon.end_session()

    def test_adversarial_trade_duplicate_burst_no_phantom_fills(self) -> None:
        """Verify duplicate trade packets do not produce phantom fills or corrupt ledger."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("adv_trade_dedup_sess")
        sym = "BTCUSDT"
        base_p = Decimal("60000.00")

        # Ingest depth and place order
        d = _build_depth(sym, base_p, update_id=100)
        daemon.on_depth(d)
        daemon.on_mark_price(_build_mark(sym, base_p))

        orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders) > 0
        fill_price = orders[0].price

        # First trade triggers real fill
        t_valid = _build_trade(sym, fill_price, Decimal("10.0"), trade_id=5000, is_buyer_maker=True)
        fills_1 = daemon.on_trade(t_valid)
        assert len(fills_1) == len(orders)
        initial_allocated_margin = daemon.ledger.allocated_margin
        assert initial_allocated_margin > Decimal("0")

        # Inject 20 duplicates and stale trades
        for i in range(20):
            tid = 5000 if i % 2 == 0 else 4990 - i
            t_dup = _build_trade(
                sym, fill_price, Decimal("10.0"), trade_id=tid, is_buyer_maker=True
            )
            dup_fills = daemon.on_trade(t_dup)
            assert len(dup_fills) == 0, f"Duplicate trade {tid} produced phantom fill!"

        # Assert no phantom fills in ledger
        assert len(daemon._execution_marks) == len(fills_1)
        assert daemon.ledger.allocated_margin == initial_allocated_margin
        assert daemon.sequencer.duplicate_count == 20

        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        daemon.end_session()

    def test_adversarial_sequence_gap_detection_and_sqlite_recording(self, tmp_path: Path) -> None:
        """Verify sequence gaps (pu != last_u) increment gap counters and persist to SQLite."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("adv_gap_sess")
        sym = "BTCUSDT"
        base_p = Decimal("60000.00")

        # Depth 1: nominal
        daemon.on_depth(_build_depth(sym, base_p, update_id=100))

        # Ingest 3 distinct sequence gaps
        # Gap 1: expected 100, received pu=140
        daemon.on_depth(_build_depth(sym, base_p, update_id=150, prev_id=140))

        # Gap 2: expected 150, received pu=200
        daemon.on_depth(_build_depth(sym, base_p, update_id=210, prev_id=200))

        # Gap 3: expected 210, received pu=300
        daemon.on_depth(_build_depth(sym, base_p, update_id=310, prev_id=300))

        assert daemon.sequencer.sequence_gap_count == 3
        assert len(daemon._gap_event_records) == 3
        assert daemon._gap_event_records[0]["gap_size"] == 10  # 150 - 140
        assert daemon._gap_event_records[1]["gap_size"] == 10  # 210 - 200
        assert daemon._gap_event_records[2]["gap_size"] == 10  # 310 - 300

        # End session and persist artifacts to verify SQLite table creation
        daemon.end_session()
        out_dir = tmp_path / "artifacts" / "phase296_adv"
        persist_phase296_artifacts(
            output_dir=out_dir,
            daemon=daemon,
            upstream_dir=DEFAULT_PHASE295_DIR,
        )

        db_path = out_dir / "canary-lifecycle-telemetry.sqlite3"
        assert db_path.exists()

        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Verify gap_events table
        cur.execute("SELECT COUNT(*) FROM gap_events WHERE symbol = 'BTCUSDT'")
        gap_count = cur.fetchone()[0]
        assert gap_count == 3

        # Verify feed_packets has is_gap == 1 rows
        cur.execute("SELECT COUNT(*) FROM feed_packets WHERE is_gap = 1")
        feed_gap_count = cur.fetchone()[0]
        assert feed_gap_count == 3

        conn.close()

        # Verify Merkle DAG chain remains mathematically intact
        assert verify_phase296_artifacts(phase296_dir=out_dir, phase295_dir=DEFAULT_PHASE295_DIR)

    def test_adversarial_multi_symbol_anomaly_isolation(self) -> None:
        """Verify anomalies injected on one symbol do not pollute other symbols."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("adv_symbol_iso_sess")

        # Inject 30 duplicates and 5 sequence gaps on BTCUSDT
        daemon.on_depth(_build_depth("BTCUSDT", Decimal("60000.00"), update_id=100))
        for _ in range(30):
            daemon.on_depth(_build_depth("BTCUSDT", Decimal("60000.00"), update_id=100))

        for i in range(1, 6):
            daemon.on_depth(
                _build_depth(
                    "BTCUSDT",
                    Decimal("60000.00"),
                    update_id=100 + i * 20,
                    prev_id=100 + i * 20 - 5,
                )
            )

        # Ingest pure nominal packets on ETHUSDT and SOLUSDT
        daemon.on_depth(_build_depth("ETHUSDT", Decimal("3000.00"), update_id=500))
        daemon.on_depth(_build_depth("ETHUSDT", Decimal("3000.00"), update_id=501, prev_id=500))

        daemon.on_depth(_build_depth("SOLUSDT", Decimal("150.00"), update_id=800))
        daemon.on_depth(_build_depth("SOLUSDT", Decimal("150.00"), update_id=801, prev_id=800))

        # Check symbol isolation
        assert daemon.sequencer.duplicates_by_symbol.get("BTCUSDT", 0) == 30
        assert daemon.sequencer.duplicates_by_symbol.get("ETHUSDT", 0) == 0
        assert daemon.sequencer.duplicates_by_symbol.get("SOLUSDT", 0) == 0

        assert daemon.sequencer.gaps_by_symbol.get("BTCUSDT", 0) == 5
        assert daemon.sequencer.gaps_by_symbol.get("ETHUSDT", 0) == 0
        assert daemon.sequencer.gaps_by_symbol.get("SOLUSDT", 0) == 0

        daemon.end_session()


# =====================================================================
# 2. Rapid Disconnect / Reconnect Cycling Stress
# =====================================================================


class TestAdversarialRapidDisconnectReconnectCycling:
    """Stress-test transport drop auto-recovery, quote purging, and state preservation."""

    def test_rapid_cycling_state_transitions_no_deadlock(self) -> None:
        """Verify 20 rapid disconnect/reconnect cycles without thread lock or state crash."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("rapid_cycling_sess")

        for cycle in range(1, 21):
            daemon.simulate_disconnect(reason=f"rapid_drop_{cycle}")
            assert daemon.get_status() == SessionStatus.DISCONNECTED

            daemon.recover_connection(reason=f"rapid_recovery_{cycle}")
            assert daemon.get_status() == SessionStatus.ACTIVE

        assert daemon._disconnect_count == 20
        assert daemon._reconnect_count == 20
        assert len(daemon._recovery_events) == 40

        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        daemon.end_session()

    def test_resting_quotes_purged_on_disconnect(self) -> None:
        """Verify resting limit orders in matching simulator are purged upon disconnect."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("purge_quotes_sess")

        # Ingest depth and place resting quotes
        daemon.on_depth(_build_depth("BTCUSDT", Decimal("60000.00"), update_id=100))
        daemon.on_depth(_build_depth("ETHUSDT", Decimal("3000.00"), update_id=100))

        orders_btc, _ = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
        orders_eth, _ = daemon.evaluate_strategy(symbol="ETHUSDT", force_side=OrderSide.BUY)

        assert len(orders_btc) > 0
        assert len(orders_eth) > 0
        assert len(daemon.matching_engine.get_active_orders()) > 0

        # Simulate disconnect
        daemon.simulate_disconnect(reason="test_quote_purge")

        # Verify all active resting orders are purged immediately
        assert len(daemon.matching_engine.get_active_orders()) == 0

        # Ingest trade that would match the cancelled quote: verify 0 fills
        trade = _build_trade(
            "BTCUSDT", orders_btc[0].price, Decimal("10.0"), trade_id=9000, is_buyer_maker=True
        )
        fills = daemon.on_trade(trade)
        assert len(fills) == 0

        daemon.end_session()

    def test_open_position_and_balance_preservation_across_disconnect_storm(self) -> None:
        """Verify open positions and balance are preserved across a storm of disconnects."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("position_preservation_sess")
        sym = "BTCUSDT"
        base_p = Decimal("60000.00")

        daemon.on_depth(_build_depth(sym, base_p, update_id=100))
        daemon.on_mark_price(_build_mark(sym, base_p))

        # Place order and execute fill to establish position
        orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        fill_p = orders[0].price
        trade = _build_trade(sym, fill_p, Decimal("10.0"), trade_id=2000, is_buyer_maker=True)
        fills = daemon.on_trade(trade)
        assert len(fills) >= 1

        cash_before = daemon.ledger.cash
        margin_before = daemon.ledger.allocated_margin
        qty_before = daemon.ledger.positions[sym].quantity
        assert margin_before > Decimal("0")

        # Storm of 10 disconnect/reconnect cycles with price fluctuations
        for i in range(1, 11):
            daemon.simulate_disconnect(reason=f"storm_drop_{i}")
            daemon.recover_connection(reason=f"storm_rec_{i}")

            # Mark price movement
            new_p = base_p + Decimal(i * 10)
            daemon.on_mark_price(_build_mark(sym, new_p))
            daemon.on_depth(_build_depth(sym, new_p, update_id=100 + i, prev_id=100 + i - 1))

            # Verify balance invariant after every cycle
            is_valid, drift = daemon.verify_zero_drift()
            assert is_valid is True
            assert drift < DOUBLE_ENTRY_MAX_DRIFT

        # Final assertions
        assert daemon.ledger.cash == cash_before
        assert daemon.ledger.allocated_margin == margin_before
        assert daemon.ledger.positions[sym].quantity == qty_before
        daemon.end_session()

    def test_ingress_quarantine_during_disconnected_state(self) -> None:
        """Verify ingress calls return false/empty and do not mutate state while disconnected."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("quarantine_sess")
        sym = "BTCUSDT"

        daemon.simulate_disconnect(reason="transport_failure")
        assert daemon.status == SessionStatus.DISCONNECTED

        # Depth rejected
        assert daemon.on_depth(_build_depth(sym, Decimal("60000.00"), 10)) is False

        # Trade rejected
        assert daemon.on_trade(_build_trade(sym, Decimal("60000.00"), Decimal("1.0"), 1)) == []

        # Mark price does not mutate marks
        daemon.on_mark_price(_build_mark(sym, Decimal("65000.00")))
        assert daemon.ledger.positions.get(sym) is None

        # Strategy evaluation blocked
        child_orders, fills = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(child_orders) == 0
        assert len(fills) == 0

        # Recover and verify nominal operation resumes
        daemon.recover_connection(reason="quarantine_exit")
        assert daemon.on_depth(_build_depth(sym, Decimal("60000.00"), 11)) is True
        daemon.end_session()


# =====================================================================
# 3. Supercritical Runaway & Loss Budget Lockout Stress
# =====================================================================


class TestAdversarialSupercriticalAndLossBudgetLockout:
    """Stress-test Hawkes supercritical lockout and intra-phase loss emergency flattening."""

    @pytest.mark.parametrize(
        "rho_val", [Decimal("1.0"), Decimal("1.25"), Decimal("2.50"), Decimal("10.0")]
    )
    def test_supercritical_hawkes_instant_lockout(self, rho_val: Decimal) -> None:
        """Verify any spectral radius rho >= 1.0 triggers immediate fail-closed order lockout."""
        daemon = AutonomousLifecycleDaemon(
            starting_capital=Decimal("100.00"),
            simulate_supercritical_hawkes=True,
        )
        daemon.start_session(f"supercritical_rho_{rho_val}")
        sym = "BTCUSDT"

        daemon.on_depth(_build_depth(sym, Decimal("60000.00"), 10))
        daemon.on_mark_price(_build_mark(sym, Decimal("60000.00")))

        # Attempt strategy evaluation under supercritical conditions
        orders, fills = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)

        assert len(orders) == 0
        assert len(fills) == 0
        assert daemon.risk.circuit_state == CircuitState.SUPERCRITICAL_CASCADE_LOCKOUT

        # Verify veto event recorded
        assert any(
            "Hawkes supercritical" in str(it.reason)
            or "supercritical" in str(getattr(it, "code", getattr(it, "veto_code", ""))).lower()
            for it in daemon._interlock_events
        )

        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        daemon.end_session()

    def test_adverse_loss_breach_triggers_emergency_flattening(self) -> None:
        """Verify cumulative loss exceeding 7.00 USDT triggers immediate emergency flattening."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("loss_flatten_sess")
        sym = "BTCUSDT"
        base_p = Decimal("60000.00")

        daemon.on_depth(_build_depth(sym, base_p, 10))
        daemon.on_mark_price(_build_mark(sym, base_p))

        # Open position
        orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders) > 0
        fill_p = orders[0].price
        trade = _build_trade(sym, fill_p, Decimal("10.0"), trade_id=1001, is_buyer_maker=True)
        fills = daemon.on_trade(trade)
        assert len(fills) >= 1
        assert daemon.ledger.allocated_margin > Decimal("0")
        assert daemon.ledger.positions[sym].quantity > Decimal("0")

        # Remediation Verification:
        # Inject cumulative loss breach (7.50 USDT > 7.00 USDT ceiling)
        daemon.risk.cumulative_loss = Decimal("7.50")
        daemon.risk._circuit_state = CircuitState.NORMAL

        # evaluate_strategy() must trigger emergency flattening and preserve zero drift
        orders, flatten_fills = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders) == 0, "All new orders must be blocked fail-closed under loss breach"
        assert len(flatten_fills) >= 1, "Open positions must be cleanly flattened"
        assert daemon.ledger.allocated_margin == Decimal("0.00")
        assert sym not in daemon.ledger.positions or daemon.ledger.positions[
            sym
        ].quantity == Decimal("0")
        assert daemon.risk.circuit_state == CircuitState.INTRA_PHASE_LOSS_LOCKOUT

        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT

        daemon.end_session()

    def test_flatten_portfolio_emergency_supports_position_track(self) -> None:
        """Verify flatten_portfolio_emergency supports PositionTrack objects without error."""
        from autonomous_futures.feed.paper_ledger import PositionTrack
        from autonomous_futures.feed.paper_risk import flatten_portfolio_emergency

        positions = {
            "BTCUSDT": PositionTrack(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.00010"),
                entry_price=Decimal("60000.00"),
                allocated_margin=Decimal("6.00"),
                mark_price=Decimal("60000.00"),
            ),
            "ETHUSDT": PositionTrack(
                symbol="ETHUSDT",
                side=OrderSide.SELL,
                quantity=Decimal("0.0020"),
                entry_price=Decimal("3000.00"),
                allocated_margin=Decimal("6.00"),
                mark_price=Decimal("3000.00"),
            ),
        }
        prices = {"BTCUSDT": Decimal("60000.00"), "ETHUSDT": Decimal("3000.00")}
        closing_orders = flatten_portfolio_emergency(positions=positions, prices=prices)
        assert len(closing_orders) >= 2
        for order in closing_orders:
            assert order.notional_usdt <= Decimal("5.00")
            if order.symbol == "BTCUSDT":
                assert order.side == OrderSide.SELL
            elif order.symbol == "ETHUSDT":
                assert order.side == OrderSide.BUY

    def test_direct_daemon_emergency_flattening_fallback(self) -> None:
        """Verify that direct daemon.trigger_emergency_flattening() cleanly flattens."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("direct_flatten_sess")
        sym = "BTCUSDT"
        base_p = Decimal("60000.00")

        daemon.on_depth(_build_depth(sym, base_p, 10))
        daemon.on_mark_price(_build_mark(sym, base_p))

        # Open position
        orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders) > 0
        fill_p = orders[0].price
        trade = _build_trade(sym, fill_p, Decimal("10.0"), trade_id=1001, is_buyer_maker=True)
        daemon.on_trade(trade)
        assert daemon.ledger.allocated_margin > Decimal("0")

        # Direct emergency flattening
        flatten_fills = daemon.trigger_emergency_flattening(reason="direct_test_flatten")
        assert len(flatten_fills) >= 1
        assert daemon.ledger.allocated_margin == Decimal("0.00")
        assert sym not in daemon.ledger.positions or daemon.ledger.positions[
            sym
        ].quantity == Decimal("0")

        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        daemon.end_session()

    def test_fail_closed_permanent_rejection_after_loss_lockout(self) -> None:
        """Verify that after loss lockout, all subsequent orders are rejected fail-closed."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("permanent_lockout_sess")

        # Seed data
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            daemon.on_depth(_build_depth(sym, Decimal("1000.00"), 10))

        # Trip loss budget ceiling
        daemon.risk.cumulative_loss = Decimal("7.01")
        daemon.risk._circuit_state = CircuitState.INTRA_PHASE_LOSS_LOCKOUT

        # Attempt 30 order evaluations across all symbols
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            for _ in range(10):
                orders, fills = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
                assert len(orders) == 0
                assert len(fills) == 0

        assert len(daemon._child_orders) == 0
        assert daemon.ledger.allocated_margin == Decimal("0")
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        daemon.end_session()

    def test_sub_cent_boundary_condition_loss_lockout(self) -> None:
        """Verify exact boundary condition: 6.99 allows orders, 7.00 triggers lockout."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("boundary_lockout_sess")
        sym = "BTCUSDT"
        daemon.on_depth(_build_depth(sym, Decimal("60000.00"), 10))

        # 1. Below threshold: 6.99 USDT loss
        daemon.risk.cumulative_loss = Decimal("6.99")
        daemon.risk._circuit_state = CircuitState.NORMAL
        orders_sub, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders_sub) > 0, "6.99 USDT should not be locked out"

        # Clear orders
        daemon.matching_engine.cancel_all_orders()

        # 2. At exact threshold: 7.00 USDT loss
        daemon.risk.cumulative_loss = Decimal("7.00")
        orders_exact, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders_exact) == 0, "7.00 USDT must trigger lockout"

        # 3. Above threshold: 7.01 USDT loss
        daemon.risk.cumulative_loss = Decimal("7.01")
        orders_above, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders_above) == 0, "7.01 USDT must trigger lockout"

        daemon.end_session()


# =====================================================================
# 4. Continuous Double-Entry Balance Drift Conservation Stress
# =====================================================================


class TestAdversarialDoubleEntryBalanceDriftConservation:
    """Stress-test mathematical balance equation |drift| < 10^-15 USDT under extreme scenarios."""

    def test_continuous_zero_drift_under_chaotic_interleaved_stresses(self) -> None:
        """Verify |drift| < 10^-15 USDT under 100 chaotic interleaved market & lifecycle events."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("chaotic_stress_sess")
        sym = "BTCUSDT"
        base_p = Decimal("60000.00")
        seq = 1000

        for step in range(1, 101):
            price_offset = Decimal((step % 13) * 50 - 300)
            cur_price = base_p + price_offset
            seq += 1

            # 1. Ingest mark price
            daemon.on_mark_price(_build_mark(sym, cur_price))

            # 2. Ingest depth
            daemon.on_depth(_build_depth(sym, cur_price, update_id=seq, prev_id=seq - 1))

            # 3. Interleaved order placement
            if step % 5 == 0:
                side = OrderSide.BUY if (step // 5) % 2 == 0 else OrderSide.SELL
                orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=side)
                if orders:
                    fill_trade = _build_trade(
                        sym,
                        orders[0].price,
                        Decimal("5.0"),
                        trade_id=seq + 1000,
                        is_buyer_maker=True,
                    )
                    daemon.on_trade(fill_trade)

            # 4. Interleaved duplicates
            if step % 7 == 0:
                daemon.on_depth(_build_depth(sym, cur_price, update_id=seq, prev_id=seq - 1))

            # 5. Interleaved sequence gaps
            if step % 11 == 0:
                seq += 5
                daemon.on_depth(_build_depth(sym, cur_price, update_id=seq, prev_id=seq - 3))

            # 6. Interleaved disconnect/reconnect
            if step % 25 == 0:
                daemon.simulate_disconnect(reason=f"step_{step}_disconnect")
                daemon.recover_connection(reason=f"step_{step}_reconnect")

            # Verify balance invariant after EVERY single step
            is_valid, drift = daemon.verify_zero_drift()
            assert is_valid is True, f"Zero-drift failed at step {step}: drift={drift}"
            assert drift < DOUBLE_ENTRY_MAX_DRIFT, f"Drift {drift} >= 1e-15 at step {step}"

        daemon.end_session()

    def test_extreme_price_crash_double_entry_preservation(self) -> None:
        """Verify balance equation holds when mark price crashes 90% and surges 100%."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("price_crash_sess")
        sym = "BTCUSDT"
        entry_p = Decimal("60000.00")

        t_base = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

        daemon.on_depth(_build_depth(sym, entry_p, 10, ts=t_base))
        daemon.on_mark_price(_build_mark(sym, entry_p, ts=t_base))

        # Open long position
        orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
        assert len(orders) > 0
        fill_trade = _build_trade(
            sym,
            orders[0].price,
            Decimal("10.0"),
            200,
            is_buyer_maker=True,
            ts=t_base + timedelta(seconds=1),
        )
        daemon.on_trade(fill_trade)

        # 1. 90% Price Crash: 60,000 -> 6,000 USDT
        crash_p = Decimal("6000.00")
        daemon.on_mark_price(_build_mark(sym, crash_p, ts=t_base + timedelta(seconds=2)))
        assert daemon.ledger.unrealized_pnl < Decimal("0")
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT

        # 2. 100% Price Surge from entry: 60,000 -> 120,000 USDT
        surge_p = Decimal("120000.00")
        daemon.on_mark_price(_build_mark(sym, surge_p, ts=t_base + timedelta(seconds=3)))
        assert daemon.ledger.unrealized_pnl > Decimal("0")
        is_valid, drift = daemon.verify_zero_drift()
        assert is_valid is True
        assert drift < DOUBLE_ENTRY_MAX_DRIFT

        daemon.end_session()

    def test_synthetic_floating_point_precision_drift_detector(self) -> None:
        """Verify that any drift >= 1e-15 USDT is detected and raises DoubleEntryDriftError."""
        daemon = AutonomousLifecycleDaemon(starting_capital=Decimal("100.00"))
        daemon.start_session("corrupt_drift_test")

        # Nominal passes
        assert daemon.verify_zero_drift()[0] is True

        # Inject microscopic drift of 1e-14 USDT (above 1e-15 threshold)
        daemon.ledger.cash += Decimal("0.00000000000001")
        with pytest.raises(DoubleEntryDriftError, match="exceeds tolerance"):
            daemon.verify_zero_drift()
