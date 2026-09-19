"""Unit tests for Phase 279: Production Canary Live Mainnet Micro-Execution Authorization.

Validates:
- Upstream verification & cryptographic SHA-256 Merkle DAG hash chain ingress.
- Gateway heartbeat freshness monitoring (<= 500 ms) and fail-closed block.
- Micro notional ceiling hard cap (<= 5.00 USDT with ROUND_DOWN precision).
- Margin & reserve allocation ceilings (<= 20% asset, <= 60% portfolio, >= 40% reserve).
- Cumulative daily loss budget interlock (<= 2.00 USDT) and emergency lockout.
- Dual-confirmation client order tagging format (c=canary-p279-{sym}-{ts}-{uuid}).
- Monotonic order lifecycle state transitions and trade ID deduplication.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT).
- Strict fail-closed containment invariants (
  execution_authority: False, orders: 0, api_keys_loaded: 0
).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.canary_activation import (  # noqa: E402
    CANARY_STAGED_SYMBOLS,
    DEFAULT_PHASE276_OUTPUT_DIR,
    OrderSide,
    OrderType,
    TimeInForce,
)
from autonomous_futures.feed.canary_live_gateway import (  # noqa: E402
    DEFAULT_PHASE277_OUTPUT_DIR,
)
from autonomous_futures.feed.canary_probe import (  # noqa: E402
    SafetyInvariantViolation,
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
)
from autonomous_futures.feed.mainnet_authorization import (  # noqa: E402
    DEFAULT_PHASE279_OUTPUT_DIR,
    CanaryMainnetConfig,
    CanaryMainnetRunner,
    CashReserveBreachedError,
    CircuitBreakerAbortError,
    CircuitBreakerState,
    DailyLossBudgetExceededError,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatRecord,
    GatewayHeartbeatStaleError,
    GatewayRateLimitError,
    GatewayServiceUnavailableError,
    HeartbeatStatus,
    InvalidClientOrderIdTagError,
    JsonlCanaryOrderSink,
    MainnetMicroOrderDispatcher,
    MainnetOrderDispatchInterlock,
    MainnetOrderRecord,
    MainnetStreamSequencer,
    MainnetUserDataStreamReconciler,
    MarginAllocationExceededError,
    MockBinanceMainnetGateway,
    NotionalCapExceededError,
    OrderCorrelationError,
    OrderLifecycleState,
    OrderLifecycleTransition,
    PrerequisiteQualificationError,
    SqliteCanaryMainnetTelemetryStore,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_279_hash_chain,
    verify_upstream_phase278_qualification,
)
from autonomous_futures.feed.testnet_deployment import (  # noqa: E402
    DEFAULT_PHASE278_OUTPUT_DIR,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_279_mainnet_authorization import (  # noqa: E402
    execute_phase_279_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def isolated_telemetry(tmp_path: Path):
    db_path = tmp_path / "canary-mainnet-telemetry.sqlite3"
    jsonl_path = tmp_path / "canary-orders.jsonl"
    store = SqliteCanaryMainnetTelemetryStore(db_path)
    sink = JsonlCanaryOrderSink(jsonl_path)
    try:
        yield store, sink, tmp_path
    finally:
        store.checkpoint()
        store.close()


# =====================================================================
# 1. Upstream Verification & Hash Chain Ingress
# =====================================================================


class TestUpstreamPhase278Qualification:
    """Verify upstream Phase 276, Phase 277, and Phase 278 prerequisite qualification."""

    def test_upstream_qualification_nominal(self):
        (
            cert_hash,
            p276_rep_hash,
            p276_sum_hash,
            p277_rep_hash,
            p277_sum_hash,
            p278_rep_hash,
            p278_sum_hash,
            cert,
        ) = verify_upstream_phase278_qualification(
            phase278_dir=DEFAULT_PHASE278_OUTPUT_DIR,
            manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
            phase276_dir=DEFAULT_PHASE276_OUTPUT_DIR,
            phase277_dir=DEFAULT_PHASE277_OUTPUT_DIR,
        )
        assert len(cert_hash) == 64
        assert len(p277_rep_hash) == 64
        assert len(p278_rep_hash) == 64
        assert cert.status == "ACTIVE"

    def test_upstream_qualification_missing_report_fails(self, tmp_path: Path):
        with pytest.raises(PrerequisiteQualificationError, match="Missing Phase 278"):
            verify_upstream_phase278_qualification(
                phase278_dir=tmp_path,
                manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
                phase276_dir=DEFAULT_PHASE276_OUTPUT_DIR,
                phase277_dir=DEFAULT_PHASE277_OUTPUT_DIR,
            )

    def test_upstream_qualification_unverified_status_fails(self, tmp_path: Path):
        # Create summary with failed status
        sum_path = tmp_path / "testnet-summary.json"
        rep_path = tmp_path / "canary-testnet-report.json"
        sum_path.write_text(json.dumps({"testnet_status": "FAILED"}), encoding="utf-8")
        rep_path.write_text(json.dumps({"compliance": {}}), encoding="utf-8")

        with pytest.raises(
            PrerequisiteQualificationError, match="strictly 'TESTNET_DEPLOYMENT_VERIFIED'"
        ):
            verify_upstream_phase278_qualification(
                phase278_dir=tmp_path,
                manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
                phase276_dir=DEFAULT_PHASE276_OUTPUT_DIR,
                phase277_dir=DEFAULT_PHASE277_OUTPUT_DIR,
            )


# =====================================================================
# 2. Gateway Heartbeat Monitoring & Freshness Interlock
# =====================================================================


class TestGatewayHeartbeatMonitor:
    """Verify gateway heartbeat freshness tracking and <= 500 ms ceiling."""

    def test_fresh_heartbeat_passes(self):
        mon = GatewayHeartbeatMonitor(max_age_ms=500.0)
        rec = mon.record_heartbeat(server_time_ms=1000000, local_receive_time_ms=1000045)
        assert rec.latency_ms == 45.0
        assert rec.status == HeartbeatStatus.HEALTHY
        assert mon.is_fresh(now_ms=1000200)
        mon.assert_fresh(now_ms=1000200)

    def test_stale_heartbeat_raises_error(self):
        mon = GatewayHeartbeatMonitor(max_age_ms=500.0)
        mon.record_heartbeat(server_time_ms=1000000, local_receive_time_ms=1000050)
        # 600 ms later: age is 600 ms > 500 ms
        assert not mon.is_fresh(now_ms=1000650)
        with pytest.raises(GatewayHeartbeatStaleError, match="Gateway heartbeat stale"):
            mon.assert_fresh(now_ms=1000650)
        assert mon.stale_count == 1
        assert mon.status == HeartbeatStatus.LATENCY_SPIKE_STALE

    def test_simulated_stale_age_override(self):
        mon = GatewayHeartbeatMonitor(max_age_ms=500.0)
        mon.record_heartbeat(server_time_ms=1000000, local_receive_time_ms=1000050)
        mon.set_simulated_stale_age(750.0)
        assert not mon.is_fresh()
        with pytest.raises(GatewayHeartbeatStaleError):
            mon.assert_fresh()


# =====================================================================
# 3. Dual-Confirmation Client Order Tagging
# =====================================================================


class TestDualConfirmationTagging:
    """Verify deterministic format c=canary-p279-{sym}-{ts}-{uuid}."""

    def test_generate_and_validate_client_order_id(self):
        for sym in CANARY_STAGED_SYMBOLS:
            cid = generate_canary_client_order_id(
                sym, timestamp_ms=1726765000000, uuid_str="abc12345"
            )
            assert cid == f"c=canary-p279-{sym}-1726765000000-abc12345"
            ok, err = validate_canary_client_order_id(cid, expected_symbol=sym)
            assert ok is True
            assert err is None
            assert_valid_canary_client_order_id(cid, expected_symbol=sym)

    def test_tag_symbol_mismatch_fails(self):
        cid = generate_canary_client_order_id(
            "BTCUSDT", timestamp_ms=1726765000000, uuid_str="abc12345"
        )
        ok, err = validate_canary_client_order_id(cid, expected_symbol="ETHUSDT")
        assert ok is False
        assert "does not match expected symbol 'ETHUSDT'" in str(err)
        with pytest.raises(InvalidClientOrderIdTagError):
            assert_valid_canary_client_order_id(cid, expected_symbol="ETHUSDT")

    def test_malformed_tag_fails(self):
        bad_tags = [
            "canary-p279-BTCUSDT-12345",
            "c=canary-p278-BTCUSDT-123-abc",
            "c=canary-p279-INVALID-123-abc",
            "c=canary-p279-BTCUSDT-timestamp-abc",
        ]
        for tag in bad_tags:
            ok, err = validate_canary_client_order_id(tag)
            assert ok is False
            with pytest.raises(InvalidClientOrderIdTagError):
                assert_valid_canary_client_order_id(tag)


# =====================================================================
# 4. Live Order Dispatch Interlocks & Risk Governance
# =====================================================================


class TestLiveOrderDispatchInterlocks:
    """Verify micro notional ceiling, margin & reserve limits, and loss budget gating."""

    def test_micro_notional_cap_enforced(self, isolated_telemetry):
        store, _, _ = isolated_telemetry
        mon = GatewayHeartbeatMonitor()
        mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 20)
        reconciler = MainnetUserDataStreamReconciler("track_1")
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_1",
        )

        cid = generate_canary_client_order_id("BTCUSDT")

        # 4.80 USDT notional <= 5.00 USDT cap -> PASS
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00008"),
            client_order_id=cid,
        )

        # 5.01 USDT notional > 5.00 USDT cap -> REJECT
        with pytest.raises(NotionalCapExceededError, match="exceeds cap of 5.00 USDT"):
            interlock.validate_dispatch(
                symbol="BTCUSDT",
                price=Decimal("60000.00"),
                quantity=Decimal("0.0000835"),  # 5.01 USDT
                client_order_id=cid,
            )

    def test_margin_and_reserve_allocation_ceilings(self, isolated_telemetry):
        store, _, _ = isolated_telemetry
        mon = GatewayHeartbeatMonitor()
        mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 20)
        reconciler = MainnetUserDataStreamReconciler("track_1", starting_equity=Decimal("100.00"))
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_1",
        )

        cid = generate_canary_client_order_id("BTCUSDT")

        # Simulate existing BTCUSDT margin of 18.00 USDT (close to 20% limit)
        reconciler.per_asset_margin["BTCUSDT"] = Decimal("18.00")
        reconciler.allocated_margin = Decimal("18.00")
        reconciler.cash = Decimal("82.00")

        # An order adding 3.00 USDT margin would result in 21.00 USDT (> 20.00% of 100.00)
        with pytest.raises(MarginAllocationExceededError, match="breaches per-asset cap"):
            interlock.validate_dispatch(
                symbol="BTCUSDT",
                price=Decimal("60000.00"),
                quantity=Decimal("0.00005"),  # 3.00 USDT margin
                client_order_id=cid,
            )

    def test_daily_loss_budget_lockout(self, isolated_telemetry):
        store, _, _ = isolated_telemetry
        mon = GatewayHeartbeatMonitor()
        mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 20)
        reconciler = MainnetUserDataStreamReconciler("track_1")
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_1",
            daily_loss_budget_usdt=Decimal("2.00"),
        )

        cid = generate_canary_client_order_id("BTCUSDT")

        # 1.50 USDT realized loss < 2.00 USDT ceiling -> passes
        reconciler.cumulative_realized_loss = Decimal("1.50")
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00005"),
            client_order_id=cid,
        )

        # 2.00 USDT realized loss reached -> triggers lockout
        reconciler.cumulative_realized_loss = Decimal("2.00")
        with pytest.raises(DailyLossBudgetExceededError, match="reached daily budget"):
            interlock.validate_dispatch(
                symbol="BTCUSDT",
                price=Decimal("60000.00"),
                quantity=Decimal("0.00005"),
                client_order_id=cid,
            )
        assert interlock.circuit_state == CircuitBreakerState.DAILY_LOSS_LOCKOUT


# =====================================================================
# 5. Exact Double-Entry Accounting
# =====================================================================


class TestExactDoubleEntryAccounting:
    """Verify zero balance drift (|drift| < 1e-15 USDT) across trading operations."""

    def test_long_open_and_close_reconciliation(self):
        reconciler = MainnetUserDataStreamReconciler(
            "test_track", starting_equity=Decimal("100.00")
        )
        assert reconciler.mathematical_drift == Decimal("0")

        # BUY 0.00008 BTC @ 60,000 (notional = 4.80 USDT, fee = 0.00192 USDT)
        buy_evt = {
            "e": "ORDER_TRADE_UPDATE",
            "T": 1726765100000,
            "o": {
                "s": "BTCUSDT",
                "c": "c=canary-p279-BTCUSDT-1-abc",
                "S": "BUY",
                "x": "TRADE",
                "X": "FILLED",
                "i": 101,
                "t": 201,
                "l": "0.00008",
                "L": "60000.00",
                "n": "0.00192000",
                "N": "USDT",
            },
        }
        mark1 = reconciler.apply_order_trade_update(buy_evt)
        assert mark1 is not None
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
        assert reconciler.allocated_margin == Decimal("4.80000000")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # SELL 0.00008 BTC @ 60,000 to close position
        sell_evt = {
            "e": "ORDER_TRADE_UPDATE",
            "T": 1726765200000,
            "o": {
                "s": "BTCUSDT",
                "c": "c=canary-p279-BTCUSDT-2-def",
                "S": "SELL",
                "x": "TRADE",
                "X": "FILLED",
                "i": 102,
                "t": 202,
                "l": "0.00008",
                "L": "60000.00",
                "n": "0.00192000",
                "N": "USDT",
            },
        }
        mark2 = reconciler.apply_order_trade_update(sell_evt, is_closing=True)
        assert mark2 is not None
        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 6. Stream Sequencer & Monotonic State Transitions
# =====================================================================


class TestStreamSequencerAndMonotonicLifecycle:
    """Verify packet sorting, deduplication, and monotonic lifecycle protection."""

    def test_deduplication_and_out_of_order_packets(self):
        seq = MainnetStreamSequencer()

        pkts = [
            {
                "e": "ORDER_TRADE_UPDATE",
                "E": 1000,
                "T": 1000,
                "_seq": 1,
                "o": {"s": "BTCUSDT", "c": "cid1", "x": "NEW", "X": "NEW", "t": 0},
            },
            {
                "e": "ORDER_TRADE_UPDATE",
                "E": 1200,
                "T": 1200,
                "_seq": 2,
                "o": {"s": "BTCUSDT", "c": "cid1", "x": "TRADE", "X": "FILLED", "t": 501},
            },
        ]

        # Duplicate the trade packet
        dup_pkt = json.loads(json.dumps(pkts[1]))
        pkts.append(dup_pkt)

        # Ingest
        results = seq.ingest_and_sort_packets(pkts)
        assert len(results) == 3
        assert seq.deduplicated_count == 1

    def test_monotonic_lifecycle_prevents_regression(self, isolated_telemetry):
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_4")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_4",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_4",
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            client_order_id=cid,
        )
        assert order.status == OrderLifecycleState.FILLED

        # Late-arriving NEW packet must NOT regress FILLED state
        late_new = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 100,
            "T": 100,
            "_seq": 1,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "x": "NEW",
                "X": "NEW",
                "i": order.order_id,
            },
        }
        gateway.stream_buffer.append(late_new)
        dispatcher.drain_and_reconcile_stream()

        # Verify state remained FILLED
        assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED


# =====================================================================
# 7. End-to-End Simulation Tracks & Full Hash Chain
# =====================================================================


class TestEndToEndSimulationTracks:
    """Verify all 4 deterministic simulation tracks and cryptographic Merkle DAG chain."""

    def test_run_all_tracks_and_verify_hash_chain(self, tmp_path: Path):
        cfg = CanaryMainnetConfig(
            output_dir=tmp_path,
            track="all",
        )
        runner = CanaryMainnetRunner(cfg)
        report = runner.execute_all_tracks()

        assert report.compliance["all_criteria_passed"] is True
        assert report.compliance["zero_balance_drift"] is True
        assert len(report.tracks) == 4

        # Verify cryptographic SHA-256 DAG hash chain
        chain_ok = verify_phase_279_hash_chain(
            output_dir=tmp_path,
            manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
            phase276_dir=DEFAULT_PHASE276_OUTPUT_DIR,
            phase277_dir=DEFAULT_PHASE277_OUTPUT_DIR,
            phase278_dir=DEFAULT_PHASE278_OUTPUT_DIR,
        )
        assert chain_ok is True

    def test_adverse_drift_fails_hash_chain(self, tmp_path: Path):
        cfg = CanaryMainnetConfig(
            output_dir=tmp_path,
            track="track_1",
            simulate_adverse_drift=True,
        )
        runner = CanaryMainnetRunner(cfg)
        report = runner.execute_all_tracks()
        assert report.compliance["zero_balance_drift"] is False

        chain_ok = verify_phase_279_hash_chain(
            output_dir=tmp_path,
            manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
            phase276_dir=DEFAULT_PHASE276_OUTPUT_DIR,
            phase277_dir=DEFAULT_PHASE277_OUTPUT_DIR,
            phase278_dir=DEFAULT_PHASE278_OUTPUT_DIR,
        )
        assert chain_ok is False


# =====================================================================
# 8. Strict Containment & Read-Only Safety Invariants
# =====================================================================


class TestContainmentAndSafetyInvariants:
    """Verify non-negotiable read-only safety invariants."""

    def test_strict_fail_closed_invariants(self):
        inv = verify_strict_fail_closed_invariants(
            orders_submitted=0,
            execution_authority=False,
            exchange_access=False,
            authenticated_endpoints_accessed=False,
        )
        assert inv["orders"] == 0
        assert inv["execution_authority"] is False
        assert inv["api_keys_loaded"] == 0
        assert inv["zero_secret_leakage"] is True

    def test_orders_submitted_violation_fails(self):
        with pytest.raises(SafetyInvariantViolation, match="SAFETY VIOLATION: orders submitted"):
            verify_strict_fail_closed_invariants(orders_submitted=1)

    def test_execution_authority_violation_fails(self):
        with pytest.raises(SafetyInvariantViolation, match="SAFETY VIOLATION: execution_authority"):
            verify_strict_fail_closed_invariants(execution_authority=True)


# =====================================================================
# 9. CLI Runner & Hardening Edge Cases
# =====================================================================


class TestCLIRunnerAndEdgeCases:
    """Verify CLI runner entry points and robustness edge cases."""

    def test_cli_verify_only_passes(self):
        code = execute_phase_279_runner(verify_only=True)
        assert code == 0

    def test_cli_execution_with_json_output(self, tmp_path: Path):
        code = execute_phase_279_runner(
            output_dir=tmp_path,
            track="1",
            json_output=True,
        )
        assert code == 0

    def test_zero_secrets_in_generated_artifacts(self):
        from autonomous_futures.paper.staging import assert_zero_secrets

        for fname in ["canary-mainnet-report.json", "mainnet-summary.json", "paper-summary.json"]:
            p = DEFAULT_PHASE279_OUTPUT_DIR / fname
            if p.is_file():
                assert_zero_secrets(p.read_text(encoding="utf-8"), fname)

    def test_cancel_unknown_order_raises_error(self, isolated_telemetry):
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_1")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_1",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_1",
        )

        from autonomous_futures.feed.mainnet_authorization import OrderCorrelationError

        with pytest.raises(OrderCorrelationError, match="Cannot cancel unknown order"):
            dispatcher.cancel_micro_order("BTCUSDT", "c=canary-p279-BTCUSDT-999-missing")

    def test_unauthorized_symbol_rejected_fail_closed(self, isolated_telemetry):
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_1")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_1",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_1",
        )

        with pytest.raises(SafetyInvariantViolation):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-doge",
                symbol="DOGEUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10.0"),
                price=Decimal("0.10"),
            )


# =====================================================================
# 9. Adversarial Break Attempts & Edge Cases (Reviewer Round 1)
# =====================================================================


class TestPhase279AdversarialHardenings:
    """Adversarial stress-testing of clock drift, hysteresis, race conditions, and concurrency."""

    def test_clock_drift_and_negative_latency_fail_closed(self):
        """Verify clock drift / backward NTP skew triggers stale state fail-closed."""
        mon = GatewayHeartbeatMonitor(max_age_ms=500.0)

        # 1. Backward clock skew: local clock is 1000ms behind server time
        rec = mon.record_heartbeat(
            server_time_ms=1000000,
            local_receive_time_ms=999000,  # -1000ms skew
        )
        assert rec.status == HeartbeatStatus.LATENCY_SPIKE_STALE
        assert not mon.is_fresh()
        with pytest.raises(GatewayHeartbeatStaleError, match="Gateway heartbeat stale"):
            mon.assert_fresh()

        # 2. Negative latency passed explicitly
        mon2 = GatewayHeartbeatMonitor(max_age_ms=500.0)
        rec2 = mon2.record_heartbeat(
            server_time_ms=1000000,
            latency_ms=-50.0,
        )
        assert rec2.status == HeartbeatStatus.LATENCY_SPIKE_STALE
        assert not mon2.is_fresh()

        # 3. Backward clock jump in get_heartbeat_age_ms
        mon3 = GatewayHeartbeatMonitor(max_age_ms=500.0)
        mon3.record_heartbeat(server_time_ms=1000000, local_receive_time_ms=1000010)
        # Clock stepped backward by 5000ms
        age = mon3.get_heartbeat_age_ms(now_ms=995000)
        assert age == float("inf")
        assert not mon3.is_fresh(now_ms=995000)

    def test_gateway_heartbeat_hysteresis_boundary(self):
        """Verify hysteresis prevents chattering when latency oscillates around 500ms."""
        mon = GatewayHeartbeatMonitor(max_age_ms=500.0, recovery_threshold_ms=450.0)

        # 1. Normal healthy state
        rec1 = mon.record_heartbeat(server_time_ms=1000000, latency_ms=400.0)
        assert rec1.status == HeartbeatStatus.HEALTHY

        # 2. Latency spike above 500ms ceiling trips to STALE
        rec2 = mon.record_heartbeat(server_time_ms=1001000, latency_ms=510.0)
        assert rec2.status == HeartbeatStatus.LATENCY_SPIKE_STALE
        assert mon.status == HeartbeatStatus.LATENCY_SPIKE_STALE

        # 3. Latency drops to 480ms (below 500ms ceiling, but above 450ms recovery threshold)
        # Hysteresis must keep status in LATENCY_SPIKE_STALE to prevent rapid toggling
        rec3 = mon.record_heartbeat(server_time_ms=1002000, latency_ms=480.0)
        assert rec3.status == HeartbeatStatus.LATENCY_SPIKE_STALE
        assert mon.status == HeartbeatStatus.LATENCY_SPIKE_STALE

        # 4. Latency drops below recovery threshold (440ms <= 450ms) -> recovers to HEALTHY
        rec4 = mon.record_heartbeat(server_time_ms=1003000, latency_ms=440.0)
        assert rec4.status == HeartbeatStatus.HEALTHY
        assert mon.status == HeartbeatStatus.HEALTHY

    def test_pending_submit_to_filled_direct_jump_and_late_new(self, isolated_telemetry):
        """Verify direct jump PENDING_SUBMIT -> FILLED and immunity to late-arriving NEW."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_4")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_4",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_4",
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        # Create order in PENDING_SUBMIT state
        order_rec = MainnetOrderRecord(
            order_id="100099",
            client_order_id=cid,
            track_id="track_4",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY.value,
            order_type=OrderType.LIMIT.value,
            time_in_force=TimeInForce.GTC.value,
            price="60000.00",
            quantity="0.00008",
            executed_quantity="0",
            notional_usdt="4.80000000",
            status=OrderLifecycleState.PENDING_SUBMIT,
            is_closing=False,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        dispatcher.orders[cid] = order_rec
        store.record_order(order_rec)

        # Inbound WebSocket TRADE / FILLED event arrives first (skipping NEW)
        fill_event = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 2000,
            "T": 2000,
            "_seq": 1,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "o": "LIMIT",
                "f": "GTC",
                "q": "0.00008",
                "p": "60000.00",
                "X": "FILLED",
                "i": "100099",
                "z": "0.00008",
                "t": 600001,
                "l": "0.00008",
                "L": "60000.00",
                "n": "0.00192000",
                "N": "USDT",
                "x": "TRADE",
            },
        }
        gateway.stream_buffer.append(fill_event)
        dispatcher.drain_and_reconcile_stream()

        assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED
        assert dispatcher.orders_filled_count == 1

        # Now late NEW packet arrives; must NOT regress state
        late_new_event = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1000,
            "T": 1000,
            "_seq": 0,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "o": "LIMIT",
                "f": "GTC",
                "q": "0.00008",
                "p": "60000.00",
                "X": "NEW",
                "i": "100099",
                "x": "NEW",
            },
        }
        gateway.stream_buffer.append(late_new_event)
        dispatcher.drain_and_reconcile_stream()

        assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED

    def test_rejected_and_cancelled_orders_do_not_regress(self, isolated_telemetry):
        """Verify REJECTED and CANCELLED orders ignore late NEW events."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_1")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_1",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_1",
        )

        cid_rej = generate_canary_client_order_id("BTCUSDT")
        order_rej = MainnetOrderRecord(
            order_id="rej-001",
            client_order_id=cid_rej,
            track_id="track_1",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY.value,
            order_type=OrderType.LIMIT.value,
            time_in_force=TimeInForce.GTC.value,
            price="60000.00",
            quantity="0.00008",
            executed_quantity="0",
            notional_usdt="4.80000000",
            status=OrderLifecycleState.REJECTED,
            is_closing=False,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        dispatcher.orders[cid_rej] = order_rej

        # Late NEW for rejected order
        late_new = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1000,
            "T": 1000,
            "o": {"s": "BTCUSDT", "c": cid_rej, "X": "NEW", "x": "NEW", "i": "rej-001"},
        }
        gateway.stream_buffer.append(late_new)
        dispatcher.drain_and_reconcile_stream()

        assert dispatcher.orders[cid_rej].status == OrderLifecycleState.REJECTED

    def test_in_flight_fill_absorbed_after_order_cancelled(self, isolated_telemetry):
        """Verify in-flight fill arriving after cancellation request updates ledger and status."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_1")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_1",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_1",
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        # Place order on gateway without immediate fill
        gw_rec = gateway.create_order(
            symbol="BTCUSDT",
            side="BUY",
            type="LIMIT",
            timeInForce="GTC",
            quantity="0.00008",
            price="60000.00",
            newClientOrderId=cid,
        )
        order_rec = MainnetOrderRecord(
            order_id=str(gw_rec["orderId"]),
            client_order_id=cid,
            track_id="track_1",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            price="60000.00",
            quantity="0.00008",
            executed_quantity="0",
            notional_usdt="4.80000000",
            status=OrderLifecycleState.NEW,
            is_closing=False,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        dispatcher.orders[cid] = order_rec
        store.record_order(order_rec)

        # Cancel order locally
        cancelled_rec = dispatcher.cancel_micro_order("BTCUSDT", cid)
        assert cancelled_rec.status == OrderLifecycleState.CANCELLED

        # An in-flight fill that beat the cancel arrives on stream
        fill_event = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 2500,
            "T": 2500,
            "_seq": 10,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "o": "LIMIT",
                "f": "GTC",
                "q": "0.00008",
                "p": "60000.00",
                "X": "FILLED",
                "i": str(gw_rec["orderId"]),
                "z": "0.00008",
                "t": 700001,
                "l": "0.00008",
                "L": "60000.00",
                "n": "0.00192000",
                "N": "USDT",
                "x": "TRADE",
            },
        }
        gateway.stream_buffer.append(fill_event)
        dispatcher.drain_and_reconcile_stream()

        # State updated to FILLED and position absorbed into reconciler
        assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
        assert reconciler.mathematical_drift < Decimal("1e-15")

    def test_emergency_flattening_cancels_active_working_orders(self, isolated_telemetry):
        """Verify execute_emergency_flattening cancels resting orders and zeroes positions."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_3")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_3",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_3",
        )

        # 1. Fill one position
        cid_filled = generate_canary_client_order_id("BTCUSDT")
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            client_order_id=cid_filled,
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")

        # 2. Add an unfilled working order for ETHUSDT
        cid_working = generate_canary_client_order_id("ETHUSDT")
        gw_rec = gateway.create_order(
            symbol="ETHUSDT",
            side="BUY",
            type="LIMIT",
            timeInForce="GTC",
            quantity="0.0010",
            price="3000.00",
            newClientOrderId=cid_working,
        )
        working_rec = MainnetOrderRecord(
            order_id=str(gw_rec["orderId"]),
            client_order_id=cid_working,
            track_id="track_3",
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            price="3000.00",
            quantity="0.0010",
            executed_quantity="0",
            notional_usdt="3.00000000",
            status=OrderLifecycleState.NEW,
            is_closing=False,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        dispatcher.orders[cid_working] = working_rec
        store.record_order(working_rec)

        # 3. Trigger emergency flattening
        dispatcher.execute_emergency_flattening()

        # 4. Verify working order was cancelled
        assert dispatcher.orders[cid_working].status == OrderLifecycleState.CANCELLED
        # 5. Verify all positions and allocated margin are strictly 0
        for sym in CANARY_STAGED_SYMBOLS:
            assert reconciler.positions[sym] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < Decimal("1e-15")

    def test_extreme_price_gapping_and_slippage_double_entry_reconciliation(self):
        """Verify zero balance drift holds under severe price gapping and adverse fills."""
        reconciler = MainnetUserDataStreamReconciler("track_gapping")

        # Open Long: evaluated at 60,000, filled at 65,000 (huge gap up)
        buy_event = {
            "e": "ORDER_TRADE_UPDATE",
            "T": 1000,
            "o": {
                "s": "BTCUSDT",
                "c": "c-gap-buy",
                "S": "BUY",
                "i": "1",
                "t": 101,
                "l": "0.00008",
                "L": "65000.00",
                "n": "0.00208000",
                "N": "USDT",
                "x": "TRADE",
            },
        }
        reconciler.apply_order_trade_update(buy_event)
        assert reconciler.mathematical_drift < Decimal("1e-15")

        # Close Long: filled at 55,000 (10,000 gap down / massive slippage)
        sell_event = {
            "e": "ORDER_TRADE_UPDATE",
            "T": 2000,
            "o": {
                "s": "BTCUSDT",
                "c": "c-gap-sell",
                "S": "SELL",
                "i": "2",
                "t": 102,
                "l": "0.00008",
                "L": "55000.00",
                "n": "0.00176000",
                "N": "USDT",
                "x": "TRADE",
            },
        }
        reconciler.apply_order_trade_update(sell_event, is_closing=True)
        assert reconciler.mathematical_drift < Decimal("1e-15")
        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")

    def test_sqlite_telemetry_store_concurrent_writes(self, tmp_path: Path):
        """Verify SQLite telemetry store handles concurrent multi-threaded writes cleanly."""
        from concurrent.futures import ThreadPoolExecutor

        db_path = tmp_path / "concurrent-telemetry.sqlite3"
        store = SqliteCanaryMainnetTelemetryStore(db_path)

        def write_batch(thread_idx: int) -> None:
            hb = GatewayHeartbeatRecord(
                heartbeat_id=f"hb-t{thread_idx}",
                track_id="track_conc",
                server_time_ms=1000000 + thread_idx,
                local_receive_time_ms=1000040 + thread_idx,
                latency_ms=40.0,
                age_ms=40.0,
                status=HeartbeatStatus.HEALTHY,
                timestamp_utc=datetime.now(UTC).isoformat(),
                details_json="{}",
            )
            store.record_heartbeat(hb)

            order = MainnetOrderRecord(
                order_id=f"ord-t{thread_idx}",
                client_order_id=f"c=canary-p279-BTCUSDT-172676500{thread_idx}-abc{thread_idx}",
                track_id="track_conc",
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                time_in_force="GTC",
                price="60000.00",
                quantity="0.00008",
                executed_quantity="0",
                notional_usdt="4.80000000",
                status=OrderLifecycleState.NEW,
                is_closing=False,
                created_at_utc=datetime.now(UTC).isoformat(),
                updated_at_utc=datetime.now(UTC).isoformat(),
            )
            store.record_order(order)

            trans = OrderLifecycleTransition(
                transition_id=f"tr-t{thread_idx}",
                track_id="track_conc",
                order_id=f"ord-t{thread_idx}",
                client_order_id=order.client_order_id,
                from_state=OrderLifecycleState.PENDING_SUBMIT.value,
                to_state=OrderLifecycleState.NEW.value,
                trigger_reason="ORDER_SUBMITTED",
                timestamp_utc=datetime.now(UTC).isoformat(),
                details_json="{}",
            )
            store.record_transition(trans)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(write_batch, i) for i in range(20)]
            for f in futures:
                f.result()

        heartbeats = store.get_heartbeats(track_id="track_conc")
        assert len(heartbeats) == 20
        orders = store.get_orders(track_id="track_conc")
        assert len(orders) == 20
        transitions = store.get_transitions(track_id="track_conc")
        assert len(transitions) == 20
        store.close()


# =====================================================================
# 11. Round 2 Adversarial Hardenings & Deep Edge-Case Verification
# =====================================================================


class TestPhase279Round2AdversarialHardenings:
    """Round 2 verification: cross-margin, partial fills, 429/503 backoff, hysteresis."""

    def test_resting_and_partially_filled_orders_committed_margin_interlock_blocks(
        self, isolated_telemetry
    ):
        """Verify resting and partial fills commit margin against per-asset and agg caps."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r2_margin")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r2_margin",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r2_margin",
        )

        # 1. Place 4 resting orders for BTC (4 x 4.50 USDT = 18.00 USDT, auto_fill=False)
        resting_cids = []
        for _ in range(3):
            cid_i = generate_canary_client_order_id("BTCUSDT")
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.000075"),
                price=Decimal("60000.00"),
                client_order_id=cid_i,
                auto_fill=False,
            )
            resting_cids.append(cid_i)

        cid_rest = generate_canary_client_order_id("BTCUSDT")
        order_rest = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.000075"),
            price=Decimal("60000.00"),
            client_order_id=cid_rest,
            auto_fill=False,
        )
        resting_cids.append(cid_rest)
        assert order_rest.status == OrderLifecycleState.NEW
        assert interlock.get_working_committed_margin("BTCUSDT") == Decimal("18.00000000")

        # 2. Attempt additional 4.50 USDT: 18.00 + 4.50 = 22.50 > 20.00 USDT per-asset cap!
        cid_blocked = generate_canary_client_order_id("BTCUSDT")
        with pytest.raises(MarginAllocationExceededError, match="per-asset cap"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.000075"),
                price=Decimal("60000.00"),
                client_order_id=cid_blocked,
            )

        # 3. Simulate partial fill of 0.000025 BTC (1.50 USDT) on Order 4
        gateway.fill_order(cid_rest, fill_qty=Decimal("0.000025"))
        dispatcher.drain_and_reconcile_stream()
        assert dispatcher.orders[cid_rest].status == OrderLifecycleState.PARTIALLY_FILLED
        assert reconciler.per_asset_margin["BTCUSDT"] == Decimal("1.50000000")
        # Remaining working on cid_rest: 3.00 USDT; total working: 13.50 + 3.00 = 16.50 USDT
        assert interlock.get_working_committed_margin("BTCUSDT") == Decimal("16.50000000")

        # Combined BTC margin is 1.50 + 16.50 = 18.00 USDT. Another 4.50 USDT is still blocked!
        cid_blocked2 = generate_canary_client_order_id("BTCUSDT")
        with pytest.raises(MarginAllocationExceededError, match="per-asset cap"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.000075"),
                price=Decimal("60000.00"),
                client_order_id=cid_blocked2,
            )

        # 4. Cancel all resting orders except the partially filled position
        for r_cid in resting_cids:
            if dispatcher.orders[r_cid].status in (
                OrderLifecycleState.NEW,
                OrderLifecycleState.PARTIALLY_FILLED,
            ):
                dispatcher.cancel_micro_order("BTCUSDT", r_cid)
        assert interlock.get_working_committed_margin("BTCUSDT") == Decimal("0")
        assert reconciler.per_asset_margin["BTCUSDT"] == Decimal("1.50000000")

        # 5. Now dispatching 4.50 USDT succeeds cleanly: 1.50 + 4.50 = 6.00 <= 20.00 USDT!
        cid_ok = generate_canary_client_order_id("BTCUSDT")
        order_ok = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.000075"),
            price=Decimal("60000.00"),
            client_order_id=cid_ok,
        )
        assert order_ok.status == OrderLifecycleState.FILLED
        assert reconciler.mathematical_drift < Decimal("1e-15")

    def test_multi_symbol_concurrent_dispatch_portfolio_aggregate_ceiling_breach(
        self, isolated_telemetry
    ):
        """Verify multi-symbol concurrent dispatch respects 60% aggregate and 40% reserve."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r2_agg")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r2_agg",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r2_agg",
        )

        # Place 4 resting orders of ~4.75 USDT each on BTC (total ~19.00 USDT, within 20% cap)
        for _ in range(4):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00007916"),
                price=Decimal("60000.00"),
                auto_fill=False,
            )
        # Place 4 resting orders of ~4.75 USDT each on ETH (total ~19.00 USDT, within 20% cap)
        for _ in range(4):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-eth",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00158333"),
                price=Decimal("3000.00"),
                auto_fill=False,
            )
        # Place 4 resting orders of ~4.75 USDT each on SOL (total ~19.00 USDT, within 20% cap)
        for _ in range(4):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-sol",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.03166666"),
                price=Decimal("150.00"),
                auto_fill=False,
            )

        # Aggregate working committed margin: ~19 * 3 = ~57.00 USDT
        assert interlock.get_working_committed_margin() >= Decimal("56.99")

        # Attempt to dispatch 4.50 USDT on SOL: 57 + 4.50 = 61.50 > 60.00 USDT (60% aggregate cap)!
        with pytest.raises((MarginAllocationExceededError, CashReserveBreachedError)):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-sol",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.030"),
                price=Decimal("150.00"),
            )

    def test_mock_gateway_multi_step_partial_fills_and_order_completion(self, isolated_telemetry):
        """Verify mock gateway cumulative partial fills and transitions to FILLED."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r2_part")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r2_part",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r2_part",
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        # Dispatch with auto_fill=False
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            client_order_id=cid,
            auto_fill=False,
        )
        assert dispatcher.orders[cid].status == OrderLifecycleState.NEW

        # Fill 1: 0.00003 BTC
        rec1 = gateway.fill_order(cid, fill_qty=Decimal("0.00003"))
        assert rec1["status"] == "PARTIALLY_FILLED"
        assert rec1["executedQty"] == "0.00003"
        dispatcher.drain_and_reconcile_stream()
        assert dispatcher.orders[cid].status == OrderLifecycleState.PARTIALLY_FILLED
        assert dispatcher.orders[cid].executed_quantity == "0.00003"

        # Fill 2: 0.00005 BTC (completes the order)
        rec2 = gateway.fill_order(cid, fill_qty=Decimal("0.00005"))
        assert rec2["status"] == "FILLED"
        assert rec2["executedQty"] == "0.00008"
        dispatcher.drain_and_reconcile_stream()
        assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED
        assert dispatcher.orders[cid].executed_quantity == "0.00008"
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
        assert reconciler.mathematical_drift < Decimal("1e-15")

    def test_gateway_http_429_rate_limit_rejection_and_reduced_risk(self, isolated_telemetry):
        """Verify HTTP 429 rate limit triggers order rejection and REDUCED_RISK state."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        gateway.inject_rate_limit_429 = True
        reconciler = MainnetUserDataStreamReconciler("track_r2_429")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r2_429",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r2_429",
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        with pytest.raises(GatewayRateLimitError, match="HTTP 429"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                client_order_id=cid,
            )

        assert dispatcher.orders[cid].status == OrderLifecycleState.REJECTED
        assert "HTTP 429" in str(dispatcher.orders[cid].rejection_reason)
        assert interlock.circuit_state == CircuitBreakerState.REDUCED_RISK
        assert dispatcher.orders_rejected_count == 1

    def test_gateway_http_503_service_unavailable_rejection_and_heartbeat_freeze(
        self, isolated_telemetry
    ):
        """Verify HTTP 503 outage triggers order rejection and HEARTBEAT_FREEZE state."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        gateway.inject_service_unavailable_503 = True
        reconciler = MainnetUserDataStreamReconciler("track_r2_503")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r2_503",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r2_503",
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        with pytest.raises(GatewayServiceUnavailableError, match="HTTP 503"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                client_order_id=cid,
            )

        assert dispatcher.orders[cid].status == OrderLifecycleState.REJECTED
        assert "HTTP 503" in str(dispatcher.orders[cid].rejection_reason)
        assert interlock.circuit_state == CircuitBreakerState.HEARTBEAT_FREEZE
        assert dispatcher.orders_rejected_count == 1

        # Subsequent dispatch while frozen is blocked
        cid2 = generate_canary_client_order_id("BTCUSDT")
        with pytest.raises(CircuitBreakerAbortError, match="HEARTBEAT_FREEZE"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                client_order_id=cid2,
            )

        # 3. Gateway recovers, fresh heartbeat arrives after freeze -> thaws back to NORMAL
        gateway.inject_service_unavailable_503 = False
        time.sleep(0.01)
        future_ts = int(time.time() * 1000) + 100
        heartbeat_mon.record_heartbeat(
            server_time_ms=future_ts,
            local_receive_time_ms=future_ts,
            latency_ms=10.0,
        )
        cid3 = generate_canary_client_order_id("BTCUSDT")
        thawed_order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            client_order_id=cid3,
        )
        assert thawed_order.status == OrderLifecycleState.FILLED
        assert interlock.circuit_state == CircuitBreakerState.NORMAL

    def test_heartbeat_timeout_and_disconnected_classification_and_freeze_thaw(
        self, isolated_telemetry
    ):
        """Verify TIMEOUT and DISCONNECTED classifications and freeze thaw upon healthy recovery."""
        mon = GatewayHeartbeatMonitor(max_age_ms=500.0)
        # 1. No heartbeat ever received -> DISCONNECTED
        assert not mon.is_fresh()
        with pytest.raises(GatewayHeartbeatStaleError, match="DISCONNECTED"):
            mon.assert_fresh()
        assert mon.status == HeartbeatStatus.DISCONNECTED

        # 2. Extreme latency spike > 2000ms -> TIMEOUT
        mon.record_heartbeat(server_time_ms=1000000, latency_ms=2500.0)
        assert mon.status == HeartbeatStatus.TIMEOUT
        assert not mon.is_fresh()
        with pytest.raises(GatewayHeartbeatStaleError, match="TIMEOUT"):
            mon.assert_fresh()

        # 3. Fresh heartbeat received -> HEALTHY
        now_ms = int(time.time() * 1000)
        mon.record_heartbeat(server_time_ms=now_ms - 30, latency_ms=30.0)
        assert mon.status == HeartbeatStatus.HEALTHY
        assert mon.is_fresh()

    def test_consecutive_ticks_hysteresis_recovery(self):
        """Verify recovery requires N consecutive healthy frames when configured."""
        mon = GatewayHeartbeatMonitor(
            max_age_ms=500.0,
            recovery_threshold_ms=450.0,
            recovery_hysteresis_ticks=3,
        )
        now_ms = 1000000
        # Frame 1: Stale (600ms)
        mon.record_heartbeat(server_time_ms=now_ms - 600, local_receive_time_ms=now_ms)
        assert mon.status == HeartbeatStatus.LATENCY_SPIKE_STALE
        assert mon.consecutive_healthy_ticks == 0

        # Frame 2: Healthy latency 400ms, tick 1 of 3 -> stays stale
        now_ms += 100
        mon.record_heartbeat(server_time_ms=now_ms - 400, local_receive_time_ms=now_ms)
        assert mon.status == HeartbeatStatus.LATENCY_SPIKE_STALE
        assert mon.consecutive_healthy_ticks == 1

        # Frame 3: Healthy latency 420ms, tick 2 of 3 -> stays stale
        now_ms += 100
        mon.record_heartbeat(server_time_ms=now_ms - 420, local_receive_time_ms=now_ms)
        assert mon.status == HeartbeatStatus.LATENCY_SPIKE_STALE
        assert mon.consecutive_healthy_ticks == 2

        # Frame 4: Healthy latency 390ms, tick 3 of 3 -> RECOVERS!
        now_ms += 100
        mon.record_heartbeat(server_time_ms=now_ms - 390, local_receive_time_ms=now_ms)
        assert mon.status == HeartbeatStatus.HEALTHY
        assert mon.consecutive_healthy_ticks == 3

    def test_stream_synthesized_order_computes_exact_usd_notional(self, isolated_telemetry):
        """Verify synthesized order records from push events compute USD notional (q * p)."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r2_synth")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r2_synth",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r2_synth",
        )

        cid = "c=canary-p279-BTCUSDT-1726765000000-synth001"
        push_event = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1726765000000,
            "T": 1726765000000,
            "_seq": 1,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "o": "LIMIT",
                "f": "GTC",
                "q": "0.00008",
                "p": "60000.00",
                "X": "NEW",
                "i": 999999,
                "z": "0",
                "x": "NEW",
            },
        }
        gateway.stream_buffer.append(push_event)
        dispatcher.drain_and_reconcile_stream()

        assert cid in dispatcher.orders
        order = dispatcher.orders[cid]
        # Notional must be 0.00008 * 60,000 = 4.80 USDT, NOT "0.00008"
        assert order.notional_usdt == "4.80000000"
        assert order.status == OrderLifecycleState.NEW


# =====================================================================
# 11. Phase 279 Round 3 Adversarial Hardenings & Invariant Edge Cases
# =====================================================================


class TestPhase279Round3AdversarialHardenings:
    """Adversarial stress-testing of emergency flattening chunking, cancel symbol matching,
    closing order directional invariants, duplicate event drops, and heartbeat disconnects."""

    def test_emergency_flattening_large_position_chunking(self, isolated_telemetry):
        """Verify positions exceeding 5.00 USDT micro notional cap are chunked <= 5.00 USDT."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r3_chunk")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r3_chunk",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r3_chunk",
        )

        # Build position of 0.00020 BTC @ 60,000 = 12.00 USDT (legal under 20% margin cap)
        # by dispatching 3 legal micro orders of 0.00006, 0.00007, 0.00007 BTC
        for q in [Decimal("0.00006"), Decimal("0.00007"), Decimal("0.00007")]:
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=q,
                price=Decimal("60000.00"),
            )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00020")
        assert reconciler.allocated_margin == Decimal("12.00000000")

        # Execute emergency flattening: MUST slice into orders <= 5.00 USDT each
        flat_orders = dispatcher.execute_emergency_flattening()
        assert len(flat_orders) >= 3
        total_flat_qty = Decimal("0")
        for ord_rec in flat_orders:
            notional = Decimal(ord_rec.notional_usdt)
            assert notional <= Decimal("5.00000000"), f"Chunk {notional} exceeds 5.00 USDT cap"
            assert ord_rec.symbol == "BTCUSDT"
            assert ord_rec.is_closing is True
            assert ord_rec.status == OrderLifecycleState.FILLED
            total_flat_qty += Decimal(ord_rec.quantity)

        assert total_flat_qty == Decimal("0.00020")
        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_order_price_and_quantity_positive_finite_validation(self, isolated_telemetry):
        """Verify non-finite, zero, or negative price/quantity are rejected fail-closed."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r3_val")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r3_val",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r3_val",
        )

        invalid_params = [
            (Decimal("-10.0"), Decimal("0.00008")),
            (Decimal("0.0"), Decimal("0.00008")),
            (Decimal("60000.0"), Decimal("-0.00008")),
            (Decimal("60000.0"), Decimal("0.0")),
            (Decimal("NaN"), Decimal("0.00008")),
            (Decimal("60000.0"), Decimal("Infinity")),
        ]
        for p, q in invalid_params:
            with pytest.raises(DomainViolation):
                dispatcher.dispatch_micro_order(
                    candidate_id="cand-btc",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=q,
                    price=p,
                )

    def test_closing_order_invariants_and_direction_validation(self, isolated_telemetry):
        """Verify closing orders require open position, matching direction, and valid quantity."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r3_closing")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r3_closing",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r3_closing",
        )

        # 1. Closing with zero open position -> fails
        with pytest.raises(OrderCorrelationError, match="no open position exists"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                is_closing=True,
            )

        # Open Long 0.00004 BTC
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00004"),
            price=Decimal("60000.00"),
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00004")

        # 2. Closing quantity exceeds open position -> fails
        with pytest.raises(OrderCorrelationError, match="exceeds open position"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                is_closing=True,
            )

        # 3. Closing side same as position (BUY to close LONG) -> fails
        with pytest.raises(OrderCorrelationError, match="must be SELL to close open position"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00004"),
                price=Decimal("60000.00"),
                is_closing=True,
            )

        # 4. Valid closing order succeeds cleanly
        close_ord = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00004"),
            price=Decimal("60000.00"),
            is_closing=True,
        )
        assert close_ord.status == OrderLifecycleState.FILLED
        assert reconciler.positions["BTCUSDT"] == Decimal("0")

    def test_cancel_order_symbol_mismatch_and_terminal_state(self, isolated_telemetry):
        """Verify cancel order rejects mismatched symbol and terminal state orders."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r3_cancel")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r3_cancel",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r3_cancel",
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            client_order_id=cid,
            auto_fill=False,
        )

        # 1. Symbol mismatch in dispatcher.cancel_micro_order
        with pytest.raises(OrderCorrelationError, match="belongs to symbol BTCUSDT, not ETHUSDT"):
            dispatcher.cancel_micro_order(symbol="ETHUSDT", client_order_id=cid)

        # 2. Symbol mismatch in gateway.cancel_order
        with pytest.raises(OrderCorrelationError, match="belongs to symbol BTCUSDT, not ETHUSDT"):
            gateway.cancel_order(symbol="ETHUSDT", client_order_id=cid)

        # 3. Successful cancel
        canc_ord = dispatcher.cancel_micro_order(symbol="BTCUSDT", client_order_id=cid)
        assert canc_ord.status == OrderLifecycleState.CANCELLED

        # 4. Attempting cancel on already CANCELLED order -> fails
        with pytest.raises(OrderCorrelationError, match="in terminal state"):
            dispatcher.cancel_micro_order(symbol="BTCUSDT", client_order_id=cid)

        # 5. Attempting gateway cancel on EXPIRED order -> fails
        expired_cid = generate_canary_client_order_id("ETHUSDT")
        gateway.create_order(
            symbol="ETHUSDT",
            side="BUY",
            type="LIMIT",
            timeInForce="GTC",
            quantity="0.001",
            price="3000.0",
            newClientOrderId=expired_cid,
        )
        gateway.orders[expired_cid]["status"] = "EXPIRED"
        with pytest.raises(OrderCorrelationError, match="terminal state EXPIRED"):
            gateway.cancel_order(symbol="ETHUSDT", client_order_id=expired_cid)

    def test_stream_duplicate_packet_does_not_mutate_order_or_re_transition(
        self, isolated_telemetry
    ):
        """Verify duplicate WebSocket packets are logged but skipped from order lifecycle."""
        store, sink, _ = isolated_telemetry
        gateway = MockBinanceMainnetGateway()
        reconciler = MainnetUserDataStreamReconciler("track_r3_dedup")
        sequencer = MainnetStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(server_time_ms=int(time.time() * 1000) - 10)
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="track_r3_dedup",
        )
        dispatcher = MainnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="track_r3_dedup",
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            client_order_id=cid,
            auto_fill=False,
        )
        assert order.status == OrderLifecycleState.NEW

        # Partial fill
        gateway.fill_order(
            client_order_id=cid, fill_price=Decimal("60000.00"), fill_qty=Decimal("0.00004")
        )
        dispatcher.drain_and_reconcile_stream()
        assert order.status == OrderLifecycleState.PARTIALLY_FILLED

        # Inject duplicate PARTIALLY_FILLED packet
        dup_event = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1726765000000,
            "T": 1726765000000,
            "_seq": 10,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "o": "LIMIT",
                "f": "GTC",
                "q": "0.00008",
                "p": "60000.00",
                "ap": "60000.00",
                "X": "PARTIALLY_FILLED",
                "i": int(order.order_id),
                "z": "0.00004000",
                "l": "0.00004000",
                "L": "60000.00",
                "n": "0.00096000",
                "N": "USDT",
                "T": 1726765000000,
                "t": 999123,
                "x": "TRADE",
            },
        }
        # Feed first time
        gateway.stream_buffer.append(dup_event)
        dispatcher.drain_and_reconcile_stream()

        # Count transitions recorded after first event ingestion
        with store.conn:
            c1 = store.conn.execute(
                "SELECT COUNT(*) FROM lifecycle_transitions WHERE client_order_id = ?",
                (cid,),
            ).fetchone()[0]

        # Feed duplicate identical event
        gateway.stream_buffer.append(dup_event)
        dispatcher.drain_and_reconcile_stream()

        with store.conn:
            # Transitions count must not increment from the duplicate event
            c2 = store.conn.execute(
                "SELECT COUNT(*) FROM lifecycle_transitions WHERE client_order_id = ?",
                (cid,),
            ).fetchone()[0]
            # Verify push events recorded the duplicate flag
            dup_logged = store.conn.execute(
                "SELECT COUNT(*) FROM websocket_push_events "
                "WHERE client_order_id = ? AND is_duplicate = 1",
                (cid,),
            ).fetchone()[0]

        assert c1 == c2
        assert dup_logged >= 1
        assert sequencer.deduplicated_count >= 1

    def test_gateway_heartbeat_explicit_disconnect_and_assert_fresh(self):
        """Verify mark_disconnected sets DISCONNECTED status and assert_fresh preserves it."""
        mon = GatewayHeartbeatMonitor(max_age_ms=500.0)
        now_ms = int(time.time() * 1000)
        mon.record_heartbeat(server_time_ms=now_ms - 20, latency_ms=20.0)
        assert mon.status == HeartbeatStatus.HEALTHY
        assert mon.is_fresh()

        # Disconnect occurs
        mon.mark_disconnected()
        assert mon.status == HeartbeatStatus.DISCONNECTED
        assert not mon.is_fresh()

        # assert_fresh must preserve DISCONNECTED and not clobber to TIMEOUT
        with pytest.raises(GatewayHeartbeatStaleError, match="DISCONNECTED"):
            mon.assert_fresh(now_ms=now_ms + 5000)
        assert mon.status == HeartbeatStatus.DISCONNECTED

    def test_client_order_id_rejects_negative_timestamp(self):
        """Verify generate_canary_client_order_id rejects negative timestamp."""
        with pytest.raises(DomainViolation, match="strictly positive"):
            generate_canary_client_order_id("BTCUSDT", timestamp_ms=-50)

    def test_sqlite_multi_track_no_clobbering(self, isolated_telemetry):
        """Verify multi-track execution does not clobber order IDs or trade marks in SQLite."""
        store, sink, _ = isolated_telemetry
        manifest, _ = load_and_validate_canary_staging_manifest(
            DEFAULT_CANARY_STAGING_MANIFEST_PATH
        )
        *_, cert = verify_upstream_phase278_qualification(
            phase278_dir=DEFAULT_PHASE278_OUTPUT_DIR,
            manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
            phase276_dir=DEFAULT_PHASE276_OUTPUT_DIR,
            phase277_dir=DEFAULT_PHASE277_OUTPUT_DIR,
        )
        cfg = CanaryMainnetConfig(
            output_dir=Path(isolated_telemetry[2]),
            track="all",
        )
        runner = CanaryMainnetRunner(cfg)
        runner.active_store = store
        runner.active_sink = sink

        # Run Track 1 and Track 2
        res1 = runner._run_track_1(manifest, cert)
        res2 = runner._run_track_2(manifest, cert)
        assert res1.success is True
        assert res2.success is True

        with store.conn:
            tracks_in_orders = [
                row[0]
                for row in store.conn.execute(
                    "SELECT DISTINCT track_id FROM orders ORDER BY track_id"
                ).fetchall()
            ]
            tracks_in_marks = [
                row[0]
                for row in store.conn.execute(
                    "SELECT DISTINCT track_id FROM execution_marks ORDER BY track_id"
                ).fetchall()
            ]
            t1_orders = store.conn.execute(
                "SELECT COUNT(*) FROM orders WHERE track_id = 'track_1'"
            ).fetchone()[0]
            t2_orders = store.conn.execute(
                "SELECT COUNT(*) FROM orders WHERE track_id = 'track_2'"
            ).fetchone()[0]
            t1_marks = store.conn.execute(
                "SELECT COUNT(*) FROM execution_marks WHERE track_id = 'track_1'"
            ).fetchone()[0]
            t2_marks = store.conn.execute(
                "SELECT COUNT(*) FROM execution_marks WHERE track_id = 'track_2'"
            ).fetchone()[0]

        assert "track_1" in tracks_in_orders
        assert "track_2" in tracks_in_orders
        assert "track_1" in tracks_in_marks
        assert "track_2" in tracks_in_marks
        assert t1_orders >= 6
        assert t2_orders >= 2
        assert t1_marks >= 6
        assert t2_marks >= 2
