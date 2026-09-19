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
from decimal import Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.canary_activation import (  # noqa: E402
    CANARY_STAGED_SYMBOLS,
    DEFAULT_PHASE276_OUTPUT_DIR,
    OrderSide,
    OrderType,
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
    CircuitBreakerState,
    DailyLossBudgetExceededError,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    HeartbeatStatus,
    InvalidClientOrderIdTagError,
    JsonlCanaryOrderSink,
    MainnetMicroOrderDispatcher,
    MainnetOrderDispatchInterlock,
    MainnetStreamSequencer,
    MainnetUserDataStreamReconciler,
    MarginAllocationExceededError,
    MockBinanceMainnetGateway,
    NotionalCapExceededError,
    OrderLifecycleState,
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
