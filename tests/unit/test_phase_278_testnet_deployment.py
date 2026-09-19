"""Unit tests for Phase 278: Production Canary Testnet Deployment Runner
& Real-Time WebSocket User Data Stream Reconciler.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.canary_activation import (  # noqa: E402
    CANARY_STAGED_SYMBOLS,
    HARD_NOTIONAL_CAP_USDT,
    STARTING_EQUITY_USDT,
    CanaryActivationCertificate,
    CertificateExpiredError,
    CertificateStatus,
    OrderSide,
    OrderType,
    compute_certificate_signature,
)
from autonomous_futures.feed.circuit_breaker_drill import (  # noqa: E402
    CanaryCircuitBreakerRecoveryStateMachine,
)
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
    CircuitBreakerState,
)
from autonomous_futures.feed.testnet_deployment import (  # noqa: E402
    CanaryTestnetConfig,
    CanaryTestnetRunner,
    CircuitBreakerAbortError,
    JsonlCanaryOrderSink,
    ListenKeyExpiredError,
    ListenKeyLifecycleError,
    MockBinanceTestnetGateway,
    OrderLifecycleState,
    PrerequisiteQualificationError,
    SqliteCanaryTestnetTelemetryStore,
    StreamDisconnectError,
    TestnetListenKeyManager,
    TestnetMicroOrderDispatcher,
    TestnetStreamSequencer,
    TestnetUserDataStreamReconciler,
    verify_phase_278_hash_chain,
    verify_upstream_phase277_qualification,
)
from autonomous_futures.paper.staging import (  # noqa: E402
    assert_zero_secrets,
)
from scripts.run_phase_278_testnet_deployment import (  # noqa: E402
    execute_phase_278_runner,
    format_summary_table,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def sample_certificate() -> CanaryActivationCertificate:
    """Provide a valid test canary activation certificate."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "certificate_id": "cert-test-p278-001",
        "version": "1.0",
        "phase": "phase_276",
        "manifest_version": 2,
        "staged_manifest_hash": "a" * 64,
        "upstream_phase275_readiness_hash": "b" * 64,
        "upstream_phase275_summary_hash": "c" * 64,
        "operator_id": "operator-test-001",
        "authorized_symbols": list(CANARY_STAGED_SYMBOLS),
        "hard_notional_cap_usdt": str(HARD_NOTIONAL_CAP_USDT),
        "daily_loss_budget_usdt": "2.00",
        "status": CertificateStatus.ACTIVE.value,
        "issued_at_utc": now.isoformat(),
        "expires_at_utc": (now + timedelta(days=7)).isoformat(),
        "key_permissions": {
            "enable_reading": True,
            "enable_futures_trading": True,
            "enable_withdrawals": False,
        },
    }
    payload["cryptographic_signature"] = compute_certificate_signature(payload)
    return CanaryActivationCertificate.model_validate(payload)


@pytest.fixture
def isolated_telemetry(
    tmp_path: Path,
) -> tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink]:
    """Provide isolated SQLite store and JSONL sink in temp directory."""
    db_path = tmp_path / "test-canary-testnet-telemetry.sqlite3"
    jsonl_path = tmp_path / "test-canary-orders.jsonl"
    store = SqliteCanaryTestnetTelemetryStore(db_path)
    sink = JsonlCanaryOrderSink(jsonl_path)
    return store, sink


# =====================================================================
# 1. Upstream Qualification & Certificate Verification Tests
# =====================================================================


class TestUpstreamPhase277Qualification:
    """Validate ingestion and integrity checks for upstream Phase 276 & 277."""

    def test_valid_upstream_qualification(self) -> None:
        """Verify that default production Phase 276 & 277 artifacts qualify cleanly."""
        (
            cert_hash,
            p276_rep_hash,
            p276_sum_hash,
            p277_rep_hash,
            p277_sum_hash,
            cert,
        ) = verify_upstream_phase277_qualification()
        assert len(cert_hash) == 64
        assert len(p276_rep_hash) == 64
        assert len(p276_sum_hash) == 64
        assert len(p277_rep_hash) == 64
        assert len(p277_sum_hash) == 64
        assert cert.status == CertificateStatus.ACTIVE

    def test_missing_phase277_dir_raises(self, tmp_path: Path) -> None:
        """Verify error raised when Phase 277 directory is absent."""
        with pytest.raises(PrerequisiteQualificationError, match="Missing Phase 277"):
            verify_upstream_phase277_qualification(phase277_dir=tmp_path / "nonexistent")

    def test_missing_phase277_report_raises(self, tmp_path: Path) -> None:
        """Verify error raised when canary-gateway-report.json is missing."""
        (tmp_path / "gateway-summary.json").write_text("{}", encoding="utf-8")
        with pytest.raises(
            PrerequisiteQualificationError, match="Missing Phase 277 canary gateway report"
        ):
            verify_upstream_phase277_qualification(phase277_dir=tmp_path)

    def test_missing_phase277_summary_raises(self, tmp_path: Path) -> None:
        """Verify error raised when gateway-summary.json is missing."""
        (tmp_path / "canary-gateway-report.json").write_text("{}", encoding="utf-8")
        with pytest.raises(
            PrerequisiteQualificationError, match="Missing Phase 277 gateway summary"
        ):
            verify_upstream_phase277_qualification(phase277_dir=tmp_path)

    def test_expired_phase276_certificate_raises(self) -> None:
        """Verify error raised when Phase 276 certificate has expired."""
        past = datetime.now(UTC) + timedelta(days=365)
        with pytest.raises(CertificateExpiredError, match="expired"):
            verify_upstream_phase277_qualification(as_of=past)


# =====================================================================
# 2. ListenKey Lifecycle Management Tests
# =====================================================================


class TestListenKeyLifecycle:
    """Validate acquisition, keep-alive, expiration, and termination of listenKey."""

    def test_listenkey_acquisition(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify clean listenKey acquisition on testnet gateway."""
        store, _ = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        mgr = TestnetListenKeyManager(gateway, store, "track_1")

        key = mgr.acquire_key()
        assert key.startswith("testnet_lk_")
        assert gateway.is_key_valid(key)
        assert mgr.current_listen_key == key

    def test_listenkey_keepalive_refresh(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify 30-minute keepalive refresh extends expiry."""
        store, _ = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        mgr = TestnetListenKeyManager(gateway, store, "track_1")

        key = mgr.acquire_key()
        initial_expiry = mgr.expiry_epoch

        gateway.advance_server_time(1800.0)  # 30m
        mgr.refresh_key()
        assert mgr.refresh_count == 1
        assert mgr.expiry_epoch > initial_expiry
        assert gateway.is_key_valid(key)

    def test_listenkey_clean_termination(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify clean termination invalidates key."""
        store, _ = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        mgr = TestnetListenKeyManager(gateway, store, "track_1")

        key = mgr.acquire_key()
        mgr.terminate_key()
        assert mgr.current_listen_key is None
        assert not gateway.is_key_valid(key)

    def test_listenkey_expiration_detection_and_reconnect(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify expired listenKey triggers exception and reconnect hysteresis."""
        store, _ = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        mgr = TestnetListenKeyManager(gateway, store, "track_2")

        key1 = mgr.acquire_key()
        gateway.inject_listen_key_expired = True

        with pytest.raises(ListenKeyExpiredError):
            mgr.refresh_key()

        key2 = mgr.reconnect_stream()
        assert key2 != key1
        assert mgr.reconnect_count == 1
        assert gateway.is_key_valid(key2)

    def test_refresh_without_active_key_raises(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify error raised when refresh called without active key."""
        store, _ = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        mgr = TestnetListenKeyManager(gateway, store, "track_1")
        with pytest.raises(ListenKeyLifecycleError, match="no active listenKey"):
            mgr.refresh_key()


# =====================================================================
# 3. WebSocket Event Ingress, Sequencer & Deduplication Tests
# =====================================================================


class TestWebSocketIngressAndSequencer:
    """Validate packet sequencing, deduplication, and chronological ordering."""

    def test_deduplication_suppresses_duplicate_packets(self) -> None:
        """Verify duplicate packets are identified and suppressed without double ledger effects."""
        sequencer = TestnetStreamSequencer()

        pkt = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1000,
            "T": 1000,
            "_seq": 1,
            "o": {
                "s": "BTCUSDT",
                "c": "cid-001",
                "S": "BUY",
                "o": "LIMIT",
                "x": "TRADE",
                "X": "FILLED",
                "t": 1,
                "l": "0.00008",
                "L": "60000.00",
                "n": "0.00192",
                "rp": "0",
            },
        }

        # First delivery
        res1 = sequencer.ingest_and_sort_packets([pkt])
        assert len(res1) == 1
        assert res1[0][1] is False  # is_duplicate = False

        # Duplicate delivery
        res2 = sequencer.ingest_and_sort_packets([dict(pkt)])
        assert len(res2) == 1
        assert res2[0][1] is True  # is_duplicate = True
        assert sequencer.deduplicated_count == 1

    def test_out_of_order_packets_reordered_chronologically(self) -> None:
        """Verify packets arriving out-of-order are sorted chronologically by transaction time."""
        sequencer = TestnetStreamSequencer()

        pkt_early = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1000,
            "T": 1000,
            "_seq": 1,
            "o": {"s": "BTCUSDT", "c": "cid-001", "x": "NEW", "X": "NEW", "t": 0},
        }
        pkt_late = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1001,
            "T": 1001,
            "_seq": 2,
            "o": {"s": "BTCUSDT", "c": "cid-001", "x": "TRADE", "X": "FILLED", "t": 1},
        }

        # Arrive in reverse order: late first, early second
        sorted_batch = sequencer.ingest_and_sort_packets([pkt_late, pkt_early])
        assert len(sorted_batch) == 2
        # First sorted packet should be early (T=1000)
        assert sorted_batch[0][0]["T"] == 1000
        # Second sorted packet should be late (T=1001)
        assert sorted_batch[1][0]["T"] == 1001
        assert sequencer.out_of_order_count >= 1

    def test_stream_disconnect_error_handling(self) -> None:
        """Verify stream disconnection raises StreamDisconnectError."""
        gateway = MockBinanceTestnetGateway()
        gateway.create_listen_key()
        gateway.inject_stream_disconnect = True

        with pytest.raises(StreamDisconnectError, match="network partition"):
            gateway.poll_stream_events()


# =====================================================================
# 4. Asynchronous Order Lifecycle & Governance Tests
# =====================================================================


class TestAsynchronousOrderLifecycle:
    """Validate micro-order dispatch, correlation, and cap enforcement."""

    def test_nominal_micro_order_fill(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify outbound order correlates with inbound push and transitions to FILLED."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_1", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_1")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_1",
        )

        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )

        assert order.status == OrderLifecycleState.FILLED
        assert order.executed_quantity == Decimal("0.00008")
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
        assert reconciler.allocated_margin == Decimal("4.80")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_hard_notional_cap_breach_rejection(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify order with notional > 5.00 USDT is rejected."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_1", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_1",
        )

        with pytest.raises(DomainViolation, match="exceeds hard cap"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.0001"),  # 6.00 USDT > 5.00
                price=Decimal("60000.00"),
            )
        assert dispatcher.orders_rejected_count == 1

    def test_per_asset_margin_cap_breach_rejection(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify per-asset margin cap breach (attempting > 20% on one asset) is rejected."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_1", STARTING_EQUITY_USDT)
        # Pre-allocate 19 USDT on BTCUSDT
        reconciler.per_asset_margin["BTCUSDT"] = Decimal("19.00")
        reconciler.allocated_margin = Decimal("19.00")
        reconciler.cash = Decimal("81.00")

        sequencer = TestnetStreamSequencer()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_1",
        )

        with pytest.raises(DomainViolation, match="Per-asset margin cap breach"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),  # 4.80 USDT + 19 = 23.80 > 20.00
                price=Decimal("60000.00"),
            )

    def test_reserve_buffer_breach_rejection(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify reserve buffer breach (< 40% free cash remaining) is rejected."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_1", STARTING_EQUITY_USDT)
        reconciler.cash = Decimal("42.00")  # Free cash 42 USDT, order 4.80 -> 37.20 < 40 floor

        sequencer = TestnetStreamSequencer()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_1",
        )

        with pytest.raises(DomainViolation, match="Reserve buffer breach"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),  # 4.80 USDT
                price=Decimal("60000.00"),
            )

    def test_circuit_breaker_tier_2_blocks_orders(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify circuit breaker in TIER_2_HARD_ABORT strictly blocks new orders fail-closed."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_3", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        sm.process_tick(rtt_ms=0.0, drift_ms=0.0, is_catastrophic=True, anomaly_reason="Test abort")
        assert sm.current_state == CircuitBreakerState.TIER_2_HARD_ABORT

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_3",
        )

        with pytest.raises(CircuitBreakerAbortError, match="locked out in TIER_2_HARD_ABORT"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )


# =====================================================================
# 5. Exact Double-Entry Accounting & Reconciliation Tests
# =====================================================================


class TestExactDoubleEntryAccounting:
    """Validate mathematical balance reconciliation and REST fallback backfill."""

    def test_zero_drift_complete_trade_lifecycle(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify zero drift across open, partial fill, mark update, and close."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_1", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_1")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_1",
        )

        # 1. Open Long BTCUSDT
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # 2. Mark price changes
        reconciler.update_mark_price("BTCUSDT", Decimal("60500.00"))
        assert reconciler.unrealized_pnl == Decimal("0.00008") * Decimal("500.00")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # 3. Close Long BTCUSDT
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc-001",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            is_closing=True,
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.unrealized_pnl == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_rest_state_backfill_matches_gateway(self) -> None:
        """Verify REST state backfill synchronizes cleanly with remote exchange state."""
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_2", STARTING_EQUITY_USDT)
        # Clean backfill with initial balance
        reconciler.backfill_via_rest(gateway)
        assert not reconciler.locked_out

    def test_rest_backfill_detects_balance_desync(self) -> None:
        """Verify REST backfill detects divergence and raises DomainViolation."""
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_2", STARTING_EQUITY_USDT)
        # Inject artificial desync on gateway balance
        gateway.wallet_balance += Decimal("1.00")

        with pytest.raises(DomainViolation, match="REST backfill desync"):
            reconciler.backfill_via_rest(gateway)
        assert reconciler.locked_out is True


# =====================================================================
# 6. Emergency Circuit Breaker & Flattening Incident Response Tests
# =====================================================================


class TestEmergencyFlatteningIncidentResponse:
    """Validate emergency liquidation flattening and fail-closed containment."""

    def test_emergency_flattening_closes_all_open_positions(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify emergency flattening closes active positions and zeroes allocated margin."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_3", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_3")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_3",
        )

        # Open BTC position
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")

        # Emergency Flattening
        orders = dispatcher.execute_emergency_flattening()
        assert len(orders) == 1
        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 7. End-to-End Simulation Tracks & Artifact Hash Chain Tests
# =====================================================================


class TestEndToEndSimulationTracks:
    """Validate full multi-track execution, report generation, and hash chaining."""

    def test_execute_all_tracks_and_verify_hash_chain(self, tmp_path: Path) -> None:
        """Verify all 4 deterministic simulation tracks execute with zero drift and valid DAG."""
        cfg = CanaryTestnetConfig(output_dir=tmp_path)
        runner = CanaryTestnetRunner(cfg)
        report = runner.execute_all_tracks()

        assert len(report.tracks) == 4
        assert all(t.success for t in report.tracks)
        assert all(t.zero_balance_drift for t in report.tracks)
        assert report.compliance["all_criteria_passed"] is True
        assert report.compliance["zero_balance_drift"] is True
        assert report.compliance["listenkey_lifecycle_verified"] is True
        assert report.compliance["websocket_stream_ingress_verified"] is True
        assert report.compliance["asynchronous_order_lifecycle_verified"] is True

        # Verify cryptographic SHA-256 DAG hash chain
        assert verify_phase_278_hash_chain(output_dir=tmp_path) is True

    def test_verify_phase_278_hash_chain_fails_on_tampered_artifact(self, tmp_path: Path) -> None:
        """Verify hash chain detects tamper in generated telemetry SQLite database."""
        cfg = CanaryTestnetConfig(output_dir=tmp_path)
        runner = CanaryTestnetRunner(cfg)
        runner.execute_all_tracks()

        # Tamper with sqlite database
        db_path = tmp_path / "canary-testnet-telemetry.sqlite3"
        with db_path.open("ab") as f:
            f.write(b"tampered_corrupted_bytes")

        assert verify_phase_278_hash_chain(output_dir=tmp_path) is False

    def test_cli_runner_verify_only(self, tmp_path: Path) -> None:
        """Verify CLI runner --verify-only flag."""
        cfg = CanaryTestnetConfig(output_dir=tmp_path)
        runner = CanaryTestnetRunner(cfg)
        runner.execute_all_tracks()

        rc = execute_phase_278_runner(output_dir=tmp_path, verify_only=True)
        assert rc == 0

    def test_cli_runner_single_track(self, tmp_path: Path) -> None:
        """Verify CLI runner can execute a single track (track 1)."""
        rc = execute_phase_278_runner(output_dir=tmp_path, track="1")
        assert rc == 0

    def test_cli_runner_adverse_drift_fails_closed(self, tmp_path: Path) -> None:
        """Verify synthetic adverse drift triggers fail-closed return code 1."""
        rc = execute_phase_278_runner(output_dir=tmp_path, simulate_adverse_drift=True)
        assert rc == 1

    def test_format_summary_table(self, tmp_path: Path) -> None:
        """Verify human-readable table formatting function."""
        cfg = CanaryTestnetConfig(output_dir=tmp_path, track="1")
        runner = CanaryTestnetRunner(cfg)
        report = runner.execute_all_tracks()
        table_str = format_summary_table(report)
        assert "PHASE 278: PRODUCTION CANARY TESTNET DEPLOYMENT" in table_str
        assert "track_1" in table_str


# =====================================================================
# 8. Containment, Safety Invariants & Secret Scanning Tests
# =====================================================================


class TestContainmentAndSafetyInvariants:
    """Validate strict read-only containment, zero mainnet capital, and zero secret leakage."""

    def test_strict_safety_invariants_in_paper_summary(self, tmp_path: Path) -> None:
        """Verify paper-summary.json contains strict zero execution containment flags."""
        cfg = CanaryTestnetConfig(output_dir=tmp_path)
        runner = CanaryTestnetRunner(cfg)
        runner.execute_all_tracks()

        paper_path = tmp_path / "paper-summary.json"
        data = json.loads(paper_path.read_text(encoding="utf-8"))

        safety = data.get("safety_invariants", {})
        assert safety.get("api_keys_loaded") == 0
        assert safety.get("execution_authority") is False
        assert safety.get("orders") == 0
        assert safety.get("canary_activation") is False
        assert safety.get("paper_activation") is False
        assert safety.get("zero_secret_leakage") is True

    def test_zero_secret_leakage_across_all_artifacts(self, tmp_path: Path) -> None:
        """Verify no API keys or secret patterns are leaked across any generated files."""
        cfg = CanaryTestnetConfig(output_dir=tmp_path)
        runner = CanaryTestnetRunner(cfg)
        runner.execute_all_tracks()

        for filename in [
            "canary-testnet-report.json",
            "testnet-summary.json",
            "paper-summary.json",
            "canary-orders.jsonl",
        ]:
            file_path = tmp_path / filename
            content = file_path.read_text(encoding="utf-8")
            assert_zero_secrets(content, filename)
