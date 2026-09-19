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
    DEFAULT_MAKER_FEE_RATE,
    CanaryTestnetConfig,
    CanaryTestnetRunner,
    CircuitBreakerAbortError,
    JsonlCanaryOrderSink,
    ListenKeyExpiredError,
    ListenKeyLifecycleError,
    MockBinanceTestnetGateway,
    OrderCorrelationError,
    OrderLifecycleState,
    PrerequisiteQualificationError,
    SafetyInvariantViolation,
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


# =====================================================================
# 9. Hardened Micro-Execution, Partial Fills & Adversarial Edge Cases
# =====================================================================


class TestHardenedCanaryExecutionAndEdgeCases:
    """Validate partial fills, opposing order validation, position flips, and cancellation."""

    def test_partial_fill_lifecycle_and_executed_quantity(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify partial fill updates executed_quantity, followed by complete fill."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_partial", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_partial")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_partial",
        )

        # 1. Place order with partial_fill_qty=0.00004
        cid = "cid-partial-001"
        order_rec = dispatcher.orders[cid] = dispatcher.orders.get(
            cid,
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            ),
        )
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Simulate a partial fill event directly on dispatcher
        partial_evt = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 2000,
            "T": 2000,
            "_seq": 50,
            "o": {
                "s": "BTCUSDT",
                "c": order_rec.client_order_id,
                "S": "BUY",
                "o": "LIMIT",
                "x": "TRADE",
                "X": "PARTIALLY_FILLED",
                "i": 999,
                "l": "0.00004000",
                "z": "0.00004000",
                "L": "60000.00",
                "N": "USDT",
                "n": "0.00096000",
                "t": 101,
            },
        }
        gateway.stream_event_queue.append(partial_evt)
        dispatcher.process_inbound_stream_events()

        assert order_rec.status == OrderLifecycleState.PARTIALLY_FILLED
        assert order_rec.executed_quantity == Decimal("0.00004000")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_partial_fill_then_cancel_lifecycle(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify partially filled order can be cancelled and tracks cancelled counts."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_p_cancel", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_p_cancel")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_p_cancel",
        )

        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert order.status == OrderLifecycleState.FILLED

        # Create a new order with auto_fill=False and cancel it
        params = {
            "symbol": "ETHUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.0010",
            "price": "2500.00",
            "newClientOrderId": "cid-cancel-test-01",
            "auto_fill": False,
        }
        gateway.place_order(params)
        # We manually register in dispatcher to simulate active order
        from autonomous_futures.feed.testnet_deployment import TestnetOrderRecord

        rec = TestnetOrderRecord(
            order_id="ord-cancel-01",
            client_order_id="cid-cancel-test-01",
            track_id="track_p_cancel",
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("2500.00"),
            quantity=Decimal("0.0010"),
            notional_usdt=Decimal("2.50"),
            status=OrderLifecycleState.NEW,
        )
        dispatcher.orders["cid-cancel-test-01"] = rec
        dispatcher.process_inbound_stream_events()
        assert rec.status == OrderLifecycleState.NEW

        # Cancel on gateway
        gateway.cancel_order("ETHUSDT", "cid-cancel-test-01")
        dispatcher.process_inbound_stream_events()
        assert rec.status == OrderLifecycleState.CANCELED
        assert dispatcher.orders_cancelled_count == 1
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_cancel_terminal_order_raises(self) -> None:
        """Verify cancelling an already FILLED order raises DomainViolation."""
        gateway = MockBinanceTestnetGateway()
        params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.00008",
            "price": "60000.00",
            "newClientOrderId": "cid-filled-term",
        }
        gateway.place_order(params)
        with pytest.raises(DomainViolation, match="terminal state"):
            gateway.cancel_order("BTCUSDT", "cid-filled-term")

    def test_position_flip_accounting_maintains_zero_drift(self) -> None:
        """Verify flipping from LONG to SHORT and vice-versa maintains exact zero drift."""
        reconciler = TestnetUserDataStreamReconciler("track_flip", Decimal("100.00"))
        # 1. Open Long BTCUSDT: 0.00008 @ 60000 = 4.80 USDT margin
        evt1 = {
            "o": {
                "x": "TRADE",
                "s": "BTCUSDT",
                "S": "BUY",
                "i": 1,
                "c": "c-flip-1",
                "t": 1,
                "l": "0.00008",
                "L": "60000.00",
                "n": "0.00192",
            },
            "T": 1000,
        }
        reconciler.apply_order_trade_update(evt1)
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
        assert reconciler.allocated_margin == Decimal("4.80")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # 2. Sell 0.00010 @ 61000: closes 0.00008 Long, opens 0.00002 Short @ 61000
        evt2 = {
            "o": {
                "x": "TRADE",
                "s": "BTCUSDT",
                "S": "SELL",
                "i": 2,
                "c": "c-flip-2",
                "t": 2,
                "l": "0.00010",
                "L": "61000.00",
                "n": "0.00244",
            },
            "T": 2000,
        }
        reconciler.apply_order_trade_update(evt2)
        assert reconciler.positions["BTCUSDT"] == Decimal("-0.00002")
        assert reconciler.entry_prices["BTCUSDT"] == Decimal("61000.00")
        assert reconciler.allocated_margin == Decimal("0.00002") * Decimal("61000.00")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # 3. Buy 0.00004 @ 60500: closes 0.00002 Short, opens 0.00002 Long @ 60500
        evt3 = {
            "o": {
                "x": "TRADE",
                "s": "BTCUSDT",
                "S": "BUY",
                "i": 3,
                "c": "c-flip-3",
                "t": 3,
                "l": "0.00004",
                "L": "60500.00",
                "n": "0.000968",
            },
            "T": 3000,
        }
        reconciler.apply_order_trade_update(evt3)
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00002")
        assert reconciler.entry_prices["BTCUSDT"] == Decimal("60500.00")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_opposing_order_without_is_closing_rejected(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify opening order opposing an active position without is_closing is rejected."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_opp", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_opp")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_opp",
        )

        # Open Long BTC
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")

        # Attempt to open opposing SELL without is_closing=True
        with pytest.raises(DomainViolation, match="Cannot open SELL/SHORT order"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                is_closing=False,
            )

    def test_closing_order_validations(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify closing order validation guards on no position, wrong side, and excess size."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_close_val", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_close_val")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_close_val",
        )

        # 1. is_closing=True with no position
        with pytest.raises(DomainViolation, match="no active position"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                is_closing=True,
            )

        # Open Long position (0.00004 @ 60000 = 2.40 USDT)
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00004"),
            price=Decimal("60000.00"),
        )

        # 2. is_closing=True with wrong side (BUY to close LONG)
        with pytest.raises(DomainViolation, match="Invalid closing side"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00004"),
                price=Decimal("60000.00"),
                is_closing=True,
            )

        # 3. is_closing=True with excess size (0.00006 > 0.00004, notional 3.60 <= 5.00 cap)
        with pytest.raises(DomainViolation, match="exceeds active position"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00006"),
                price=Decimal("60000.00"),
                is_closing=True,
            )

    def test_unrecognized_client_order_id_raises_order_correlation_error(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify unmapped clientOrderId raises OrderCorrelationError on inbound push."""
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_rogue", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_rogue",
        )

        # Inject rogue push event into gateway stream
        rogue_evt = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1000,
            "T": 1000,
            "_seq": 1,
            "o": {
                "s": "BTCUSDT",
                "c": "cid-rogue-unmapped-999",
                "S": "BUY",
                "o": "LIMIT",
                "x": "TRADE",
                "X": "FILLED",
                "i": 777,
                "l": "0.00008",
                "L": "60000.00",
                "n": "0.00192",
                "t": 1,
            },
        }
        gateway.stream_event_queue.append(rogue_evt)

        with pytest.raises(OrderCorrelationError, match="not correlated"):
            dispatcher.process_inbound_stream_events()

    def test_unauthorized_symbol_raises_safety_invariant_violation(self) -> None:
        """Verify push event with unauthorized symbol raises SafetyInvariantViolation."""
        reconciler = TestnetUserDataStreamReconciler("track_sym", STARTING_EQUITY_USDT)
        rogue_evt = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "DOGEUSDT",
                "S": "BUY",
                "x": "TRADE",
                "X": "FILLED",
                "i": 1,
                "c": "c1",
                "t": 1,
                "l": "100.0",
                "L": "0.10",
                "n": "0.004",
            },
        }
        with pytest.raises(SafetyInvariantViolation, match="Unauthorized symbol"):
            reconciler.apply_order_trade_update(rogue_evt)

    def test_event_sequencer_tie_breaker_same_millisecond(self) -> None:
        """Verify sequencer breaks ties with NEW -> TRADE -> ACCOUNT_UPDATE for identical times."""
        sequencer = TestnetStreamSequencer()
        acc_pkt = {
            "e": "ACCOUNT_UPDATE",
            "E": 1000,
            "T": 1000,
            "_seq": 0,
            "a": {"m": "ORDER", "B": [{"a": "USDT", "wb": "99.99"}]},
        }
        trade_pkt = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1000,
            "T": 1000,
            "_seq": 0,
            "o": {"s": "BTCUSDT", "c": "c1", "x": "TRADE", "X": "FILLED", "t": 1},
        }
        new_pkt = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1000,
            "T": 1000,
            "_seq": 0,
            "o": {"s": "BTCUSDT", "c": "c1", "x": "NEW", "X": "NEW", "t": 0},
        }

        # Ingest in reversed order
        sorted_batch = sequencer.ingest_and_sort_packets([acc_pkt, trade_pkt, new_pkt])
        assert len(sorted_batch) == 3
        # 1. NEW
        assert sorted_batch[0][0]["o"]["x"] == "NEW"
        # 2. TRADE
        assert sorted_batch[1][0]["o"]["x"] == "TRADE"
        # 3. ACCOUNT_UPDATE
        assert sorted_batch[2][0]["e"] == "ACCOUNT_UPDATE"

    def test_maker_fee_commission_rate(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify order with maker fee computes fee at DEFAULT_MAKER_FEE_RATE with zero drift."""
        gateway = MockBinanceTestnetGateway()
        res = gateway.place_order(
            {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "quantity": "0.00008",
                "price": "60000.00",
                "is_maker": True,
            }
        )
        expected_fee = (Decimal("0.00008") * Decimal("60000.00") * DEFAULT_MAKER_FEE_RATE).quantize(
            Decimal("0.00000001")
        )
        assert Decimal(res["fee"]) == expected_fee

    def test_sqlite_telemetry_store_context_manager_and_verify_unlocked(
        self,
        tmp_path: Path,
    ) -> None:
        """Verify SqliteCanaryTestnetTelemetryStore supports verify_unlocked and context manager."""
        db_path = tmp_path / "test_store_ctx.sqlite3"
        with SqliteCanaryTestnetTelemetryStore(db_path) as store:
            assert store.verify_unlocked() is True


# =====================================================================
# 11. Reviewer Adversarial Hardening & Edge Cases (Phase 278 Round 2)
# =====================================================================


class TestReviewerHardeningAndEdgeCases:
    """Adversarial validation covering emergency liquidation chunking, symbol validation,
    multi-stage partial fills, REST order synchronization, and reconnect loops.
    """

    def test_emergency_flattening_large_accumulated_position_chunking(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify positions accumulated > 5.00 USDT are chunked into micro orders
        during emergency flattening.
        """
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_chunk", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_chunk")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_chunk",
            key_mgr=key_mgr,
        )

        # Open 2 micro orders: 0.00008 @ 60000 (4.80 USDT) each -> total 0.00016 BTC = 9.60 USDT
        o1 = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert o1.status == OrderLifecycleState.FILLED

        o2 = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert o2.status == OrderLifecycleState.FILLED

        assert reconciler.positions["BTCUSDT"] == Decimal("0.00016")
        assert reconciler.allocated_margin == Decimal("9.60")

        # Trigger Tier 2 Hard-Abort Emergency Incident
        sm.process_tick(
            rtt_ms=0.0,
            drift_ms=0.0,
            is_catastrophic=True,
            anomaly_reason="Emergency test: large position liquidation chunking",
        )
        assert sm.current_state == CircuitBreakerState.TIER_2_HARD_ABORT

        # Emergency flattening must chunk the 9.60 USDT position into <= 5.00 USDT micro orders
        flattening_orders = dispatcher.execute_emergency_flattening()
        assert len(flattening_orders) >= 2
        for fo in flattening_orders:
            assert fo.notional_usdt <= HARD_NOTIONAL_CAP_USDT
            assert fo.status == OrderLifecycleState.FILLED

        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_cancel_order_symbol_mismatch_raises_order_correlation_error(self) -> None:
        """Verify cancel_order raises OrderCorrelationError when symbol does not match
        order record.
        """
        gateway = MockBinanceTestnetGateway()
        res = gateway.place_order(
            {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "quantity": "0.00008",
                "price": "60000.00",
                "newClientOrderId": "cid-btc-sym-test",
                "auto_fill": False,
            }
        )
        assert res["status"] == "NEW"

        with pytest.raises(OrderCorrelationError, match="belongs to symbol BTCUSDT, not ETHUSDT"):
            gateway.cancel_order("ETHUSDT", "cid-btc-sym-test")

    def test_cancel_micro_order_via_dispatcher_writes_jsonl_and_transitions(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify cancel_micro_order on dispatcher transitions to CANCELED and writes
        ORDER_CANCELED to JSONL.
        """
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_cancel", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_cancel",
        )

        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            auto_fill=False,
        )
        assert order.status == OrderLifecycleState.NEW

        cancelled_rec = dispatcher.cancel_micro_order("BTCUSDT", order.client_order_id)
        assert cancelled_rec.status == OrderLifecycleState.CANCELED
        assert dispatcher.orders_cancelled_count == 1

        # Check JSONL file contents
        jsonl_lines = [
            json.loads(line)
            for line in sink.file_path.read_text(encoding="utf-8").strip().split("\n")
            if line
        ]
        cancel_entries = [e for e in jsonl_lines if e.get("event") == "ORDER_CANCELED"]
        assert len(cancel_entries) == 1
        assert cancel_entries[0]["client_order_id"] == order.client_order_id

    def test_gateway_fill_order_multi_stage_partial_and_full(self) -> None:
        """Verify gateway fill_order executes multi-stage partial and complete fills
        on open orders.
        """
        gateway = MockBinanceTestnetGateway()
        res = gateway.place_order(
            {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "quantity": "0.00008",
                "price": "60000.00",
                "newClientOrderId": "cid-multi-fill",
                "auto_fill": False,
            }
        )
        cid = res["clientOrderId"]
        assert gateway.orders[cid]["status"] == "NEW"

        # Stage 1: Partial fill of 0.00003 BTC
        part_res = gateway.fill_order(cid, fill_qty=Decimal("0.00003"))
        assert part_res["status"] == "PARTIALLY_FILLED"
        assert part_res["executedQty"] == "0.00003000"
        assert Decimal(gateway.positions["BTCUSDT"]["positionAmt"]) == Decimal("0.00003")

        # Stage 2: Full fill of remaining 0.00005 BTC
        full_res = gateway.fill_order(cid)
        assert full_res["status"] == "FILLED"
        assert full_res["executedQty"] == "0.00008000"
        assert Decimal(gateway.positions["BTCUSDT"]["positionAmt"]) == Decimal("0.00008")

        # Stage 3: Further fill on terminal order raises DomainViolation
        with pytest.raises(DomainViolation, match="terminal state"):
            gateway.fill_order(cid)

    def test_gateway_get_open_orders_and_get_order(self) -> None:
        """Verify get_open_orders and get_order endpoints return accurate records."""
        gateway = MockBinanceTestnetGateway()
        gateway.place_order(
            {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "quantity": "0.00008",
                "price": "60000.00",
                "newClientOrderId": "cid-oo-btc",
                "auto_fill": False,
            }
        )
        gateway.place_order(
            {
                "symbol": "ETHUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "quantity": "0.0019",
                "price": "2500.00",
                "newClientOrderId": "cid-oo-eth",
                "auto_fill": False,
            }
        )

        all_open = gateway.get_open_orders()
        assert len(all_open) == 2

        btc_open = gateway.get_open_orders("BTCUSDT")
        assert len(btc_open) == 1
        assert btc_open[0]["clientOrderId"] == "cid-oo-btc"

        rec = gateway.get_order("BTCUSDT", "cid-oo-btc")
        assert rec["clientOrderId"] == "cid-oo-btc"
        assert rec["symbol"] == "BTCUSDT"

        with pytest.raises(OrderCorrelationError):
            gateway.get_order("ETHUSDT", "cid-oo-btc")

        with pytest.raises(OrderCorrelationError):
            gateway.get_order("BTCUSDT", "nonexistent-cid")

    def test_sync_orders_via_rest_after_stream_drop(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify sync_orders_via_rest updates in-flight order states after WebSocket
        packet loss.
        """
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_sync", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_sync",
        )

        # 1. Place order with auto_fill=False
        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            auto_fill=False,
        )
        assert order.status == OrderLifecycleState.NEW

        # 2. Simulate stream disconnect
        gateway.is_stream_connected = False

        # 3. Order is filled on the exchange while disconnected
        gateway.fill_order(order.client_order_id)
        assert gateway.orders[order.client_order_id]["status"] == "FILLED"

        # 4. Stream reconnects
        gateway.is_stream_connected = True

        # 5. REST sync updates in-flight order status in dispatcher
        synced = dispatcher.sync_orders_via_rest()
        assert len(synced) == 1
        assert order.status == OrderLifecycleState.FILLED
        assert order.executed_quantity == Decimal("0.00008")
        assert dispatcher.orders_filled_count == 1

    def test_listen_key_refresh_or_reconnect_automated_hysteresis(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify refresh_or_reconnect refreshes when valid and reconnects when expired."""
        store, _ = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_refresh_rec")

        # Initial acquire
        key1 = key_mgr.acquire_key()

        # Normal refresh
        active_key, was_reconnected = key_mgr.refresh_or_reconnect()
        assert active_key == key1
        assert was_reconnected is False
        assert key_mgr.refresh_count == 1

        # Simulate expiration
        gateway.inject_listen_key_expired = True
        key2, was_reconnected2 = key_mgr.refresh_or_reconnect()
        assert was_reconnected2 is True
        assert key2 != key1
        assert key_mgr.reconnect_count == 1

    def test_websocket_listen_key_expired_event_triggers_reconnect(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify WebSocket push event listenKeyExpired automatically reconnects stream
        in dispatcher.
        """
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_ws_exp", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_ws_exp")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_ws_exp",
            key_mgr=key_mgr,
        )

        assert key_mgr.reconnect_count == 0
        gateway.emit_listen_key_expired()

        dispatcher.process_inbound_stream_events()
        assert key_mgr.reconnect_count == 1

    def test_update_mark_price_unauthorized_symbol_raises_safety_invariant_violation(self) -> None:
        """Verify reconciler update_mark_price rejects unauthorized symbols."""
        reconciler = TestnetUserDataStreamReconciler("track_unauth", STARTING_EQUITY_USDT)
        with pytest.raises(SafetyInvariantViolation, match="Unauthorized symbol"):
            reconciler.update_mark_price("ADAUSDT", Decimal("0.35"))

    def test_rapid_reconnect_loop_with_inflight_partially_filled_multi_symbol(
        self,
        isolated_telemetry: tuple[SqliteCanaryTestnetTelemetryStore, JsonlCanaryOrderSink],
    ) -> None:
        """Verify rapid reconnect loop with in-flight partially filled orders across multiple
        symbols preserves zero drift.
        """
        store, sink = isolated_telemetry
        gateway = MockBinanceTestnetGateway()
        reconciler = TestnetUserDataStreamReconciler("track_loop", STARTING_EQUITY_USDT)
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(gateway, store, "track_loop")
        key_mgr.acquire_key()
        sm = CanaryCircuitBreakerRecoveryStateMachine()

        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            circuit_breaker=sm,
            track_id="track_loop",
            key_mgr=key_mgr,
        )

        # Place 3 orders across BTCUSDT, ETHUSDT, SOLUSDT with auto_fill=False
        o_btc = dispatcher.dispatch_micro_order(
            candidate_id="c-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            auto_fill=False,
        )
        o_eth = dispatcher.dispatch_micro_order(
            candidate_id="c-eth",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
            auto_fill=False,
        )
        o_sol = dispatcher.dispatch_micro_order(
            candidate_id="c-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
            auto_fill=False,
        )

        # Execute partial fills on all 3 on the exchange
        gateway.fill_order(o_btc.client_order_id, fill_qty=Decimal("0.00004"))
        gateway.fill_order(o_eth.client_order_id, fill_qty=Decimal("0.0010"))
        gateway.fill_order(o_sol.client_order_id, fill_qty=Decimal("0.016"))

        # Rapid reconnection loop: 3 expirations and renewals
        for _ in range(3):
            key_mgr.reconnect_stream()

        assert key_mgr.reconnect_count == 3

        # Process queued stream events after reconnection
        dispatcher.process_inbound_stream_events()

        assert o_btc.status == OrderLifecycleState.PARTIALLY_FILLED
        assert o_eth.status == OrderLifecycleState.PARTIALLY_FILLED
        assert o_sol.status == OrderLifecycleState.PARTIALLY_FILLED
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Fill remaining quantities
        gateway.fill_order(o_btc.client_order_id)
        gateway.fill_order(o_eth.client_order_id)
        gateway.fill_order(o_sol.client_order_id)

        dispatcher.process_inbound_stream_events()

        assert o_btc.status == OrderLifecycleState.FILLED
        assert o_eth.status == OrderLifecycleState.FILLED
        assert o_sol.status == OrderLifecycleState.FILLED
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Emergency flattening to verify clean liquidation of all multi-symbol positions
        flattening_orders = dispatcher.execute_emergency_flattening()
        assert len(flattening_orders) == 3

        for sym in CANARY_STAGED_SYMBOLS:
            assert reconciler.positions[sym] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
