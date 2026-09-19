"""Unit tests for Phase 277: Live Exchange Gateway Synchronization Runner
& Shadow Order Dispatch Harness.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.canary_activation import (  # noqa: E402
    CANARY_STAGED_SYMBOLS,
    DAILY_LOSS_BUDGET_USDT,
    DEFAULT_AGGREGATE_MARGIN_CAP,
    DEFAULT_PER_ASSET_MARGIN_CAP,
    HARD_NOTIONAL_CAP_USDT,
    STARTING_EQUITY_USDT,
    CanaryActivationCertificate,
    CanaryOrderDispatchInterlockGateway,
    CertificateExpiredError,
    CertificateInvalidatedError,
    CertificateStatus,
    ExchangeApiKeyPermissions,
    OrderNotionalCapBreachError,
    OrderSide,
    OrderType,
    RateLimitThrottleExceededError,
    SecureExchangeKeyVault,
    UnauthorizedSymbolError,
    compute_certificate_signature,
)
from autonomous_futures.feed.canary_live_gateway import (  # noqa: E402
    BalanceDesyncError,
    CanaryGatewayConfig,
    CanaryLiveGatewayClient,
    CanaryLiveGatewayError,
    CanaryLiveGatewayRunner,
    CanaryLiveOrderDispatcher,
    GatewayBalanceSnapshot,
    GatewayErrorRecord,
    GatewayLockoutError,
    GatewaySyncEvent,
    GatewaySyncStatus,
    JsonlCanaryOrderSink,
    LiveGatewayAccountReconciler,
    MockBinanceFuturesGateway,
    OrderLifecycleState,
    PrerequisiteQualificationError,
    SqliteCanaryLiveGatewayTelemetryStore,
    verify_phase_277_hash_chain,
    verify_upstream_phase276_qualification,
)
from autonomous_futures.feed.circuit_breaker_drill import (  # noqa: E402
    CanaryCircuitBreakerRecoveryStateMachine,
)
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
)
from scripts.run_phase_277_canary_live_gateway import (  # noqa: E402
    execute_phase_277_runner,
    format_summary_table,
)
from scripts.run_phase_277_canary_live_gateway import (  # noqa: E402
    main as cli_main,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def safe_key_vault() -> SecureExchangeKeyVault:
    """Provide an isolated safe key vault for testing."""
    vault = SecureExchangeKeyVault()
    vault.load_credentials(
        api_key="unit_test_p277_key",
        api_secret="unit_test_p277_secret",
        permissions=ExchangeApiKeyPermissions(
            enable_reading=True,
            enable_futures_trading=True,
            enable_withdrawals=False,
        ),
    )
    return vault


@pytest.fixture
def sample_certificate() -> CanaryActivationCertificate:
    """Provide a valid test canary activation certificate."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "certificate_id": "cert-test-p277-001",
        "version": "1.0",
        "phase": "phase_276",
        "manifest_version": 2,
        "staged_manifest_hash": "a" * 64,
        "upstream_phase275_readiness_hash": "b" * 64,
        "upstream_phase275_summary_hash": "c" * 64,
        "operator_id": "operator-test-001",
        "authorized_symbols": list(CANARY_STAGED_SYMBOLS),
        "max_allocated_margin_caps": {
            "BTCUSDT": str(DEFAULT_PER_ASSET_MARGIN_CAP),
            "ETHUSDT": str(DEFAULT_PER_ASSET_MARGIN_CAP),
            "SOLUSDT": str(DEFAULT_PER_ASSET_MARGIN_CAP),
        },
        "max_aggregate_margin_usdt": str(DEFAULT_AGGREGATE_MARGIN_CAP),
        "max_micro_order_notional_usdt": str(HARD_NOTIONAL_CAP_USDT),
        "daily_loss_budget_usdt": str(DAILY_LOSS_BUDGET_USDT),
        "max_duration_hours": 24.0,
        "issued_at_utc": now.isoformat(),
        "expires_at_utc": (now + timedelta(hours=24)).isoformat(),
        "status": CertificateStatus.ACTIVE,
        "operator_rationale": "Unit test authorization",
    }
    sig = compute_certificate_signature(payload)
    payload["cryptographic_signature"] = sig
    return CanaryActivationCertificate.model_validate(payload)


@pytest.fixture
def mock_gateway(safe_key_vault: SecureExchangeKeyVault) -> MockBinanceFuturesGateway:
    """Provide an isolated mock Binance Futures exchange gateway."""
    return MockBinanceFuturesGateway(
        initial_balance_usdt=STARTING_EQUITY_USDT,
        key_vault=safe_key_vault,
    )


@pytest.fixture
def gateway_client(
    safe_key_vault: SecureExchangeKeyVault,
    mock_gateway: MockBinanceFuturesGateway,
) -> CanaryLiveGatewayClient:
    """Provide an authenticated live gateway client."""
    client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
    client.sync_server_time()
    return client


# =====================================================================
# 1. Upstream Phase 276 Prerequisite Qualification Tests
# =====================================================================


class TestUpstreamPhase276Verification:
    """Validate strict prerequisite qualification on Phase 276 artifacts."""

    def test_verify_upstream_phase276_success(self) -> None:
        """Verify that existing Phase 276 artifacts pass qualification."""
        cert_hash, rep_hash, sum_hash, cert = verify_upstream_phase276_qualification()
        assert len(cert_hash) == 64
        assert len(rep_hash) == 64
        assert len(sum_hash) == 64
        assert cert.status == CertificateStatus.ACTIVE
        assert not cert.is_expired()

    def test_verify_upstream_missing_certificate(self, tmp_path: Path) -> None:
        """Verify fail-closed error when Phase 276 certificate is missing."""
        empty_dir = tmp_path / "nonexistent"
        with pytest.raises(
            PrerequisiteQualificationError, match="Missing Phase 276 activation certificate"
        ):
            verify_upstream_phase276_qualification(phase276_dir=empty_dir)

    def test_verify_upstream_invalid_status(self, tmp_path: Path) -> None:
        """Verify fail-closed error when certificate status is not ACTIVE."""
        p276_dir = tmp_path / "phase276"
        p276_dir.mkdir(parents=True)
        now = datetime.now(UTC)
        cert_data: dict[str, Any] = {
            "certificate_id": "cert-test-revoked",
            "version": "1.0",
            "phase": "phase_276",
            "manifest_version": 2,
            "staged_manifest_hash": "a" * 64,
            "upstream_phase275_readiness_hash": "b" * 64,
            "upstream_phase275_summary_hash": "c" * 64,
            "operator_id": "operator-test",
            "status": "REVOKED_OPERATOR",
            "issued_at_utc": now.isoformat(),
            "expires_at_utc": (now + timedelta(hours=24)).isoformat(),
            "operator_rationale": "Revoked",
        }
        cert_data["cryptographic_signature"] = compute_certificate_signature(cert_data)
        (p276_dir / "canary-activation-certificate.json").write_text(json.dumps(cert_data))

        with pytest.raises(CertificateInvalidatedError, match="strictly ACTIVE required"):
            verify_upstream_phase276_qualification(phase276_dir=p276_dir)

    def test_verify_upstream_signature_tampered(self, tmp_path: Path) -> None:
        """Verify fail-closed error when cryptographic signature does not match payload."""
        p276_dir = tmp_path / "phase276"
        p276_dir.mkdir(parents=True)
        now = datetime.now(UTC)
        cert_data: dict[str, Any] = {
            "certificate_id": "cert-test-tampered",
            "version": "1.0",
            "phase": "phase_276",
            "manifest_version": 2,
            "staged_manifest_hash": "a" * 64,
            "upstream_phase275_readiness_hash": "b" * 64,
            "upstream_phase275_summary_hash": "c" * 64,
            "operator_id": "operator-test",
            "status": "ACTIVE",
            "issued_at_utc": now.isoformat(),
            "expires_at_utc": (now + timedelta(hours=24)).isoformat(),
            "operator_rationale": "Tampered",
            "cryptographic_signature": "0" * 64,  # Invalid signature
        }
        (p276_dir / "canary-activation-certificate.json").write_text(json.dumps(cert_data))

        with pytest.raises(PrerequisiteQualificationError, match="signature mismatch"):
            verify_upstream_phase276_qualification(phase276_dir=p276_dir)

    def test_verify_upstream_certificate_expired(self, tmp_path: Path) -> None:
        """Verify fail-closed error when certificate expiration timestamp has passed."""
        past_time = datetime.now(UTC) - timedelta(hours=2)
        p276_dir = tmp_path / "phase276"
        p276_dir.mkdir(parents=True)
        cert_data: dict[str, Any] = {
            "certificate_id": "cert-test-expired",
            "version": "1.0",
            "phase": "phase_276",
            "manifest_version": 2,
            "staged_manifest_hash": "a" * 64,
            "upstream_phase275_readiness_hash": "b" * 64,
            "upstream_phase275_summary_hash": "c" * 64,
            "operator_id": "operator-test",
            "status": "ACTIVE",
            "issued_at_utc": (past_time - timedelta(hours=24)).isoformat(),
            "expires_at_utc": past_time.isoformat(),
            "operator_rationale": "Expired",
        }
        cert_data["cryptographic_signature"] = compute_certificate_signature(cert_data)
        (p276_dir / "canary-activation-certificate.json").write_text(json.dumps(cert_data))

        with pytest.raises(CertificateExpiredError, match="Phase 276 certificate expired"):
            verify_upstream_phase276_qualification(phase276_dir=p276_dir)


# =====================================================================
# 2. Binance Futures Authentication & Parameter Canonicalization Tests
# =====================================================================


class TestBinanceFuturesAuthentication:
    """Validate RFC 3986 parameter canonicalization and HMAC-SHA256 signing."""

    def test_canonicalize_query_string(self) -> None:
        """Verify RFC 3986 deterministic key sorting and URL encoding."""
        params = {
            "symbol": "BTCUSDT",
            "quantity": "0.00008",
            "price": "60000.00",
            "side": "BUY",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "timestamp": 1600000000000,
        }
        canonical = SecureExchangeKeyVault.canonicalize_query_string(params)
        expected_order = [
            "price=60000.00",
            "quantity=0.00008",
            "side=BUY",
            "symbol=BTCUSDT",
            "timeInForce=GTC",
            "timestamp=1600000000000",
            "type=LIMIT",
        ]
        assert canonical == "&".join(expected_order)

    def test_hmac_signature_generation_and_verification(
        self, safe_key_vault: SecureExchangeKeyVault
    ) -> None:
        """Verify HMAC-SHA256 signature calculation and tamper resistance."""
        query = "price=60000.00&quantity=0.00008&symbol=BTCUSDT&timestamp=1600000000000"
        sig = safe_key_vault.generate_signature(query)
        assert len(sig) == 64
        assert safe_key_vault.verify_signature(query, sig) is True

        # Tampered query
        tampered = query + "1"
        assert safe_key_vault.verify_signature(tampered, sig) is False

    def test_timestamp_drift_validation(self) -> None:
        """Verify timestamp drift validation window (<= 1000ms)."""
        now = int(time.time() * 1000)
        assert SecureExchangeKeyVault.validate_timestamp_window(now, now + 500) is True
        assert SecureExchangeKeyVault.validate_timestamp_window(now, now - 500) is True

        # Over 1000ms drift
        with pytest.raises(Exception, match="exceeds allowed window"):
            SecureExchangeKeyVault.validate_timestamp_window(now, now + 1500)


# =====================================================================
# 3. Authenticated Endpoints & Error Recovery Tests
# =====================================================================


class TestAuthenticatedEndpointsAndRecovery:
    """Validate authenticated endpoint responses and fail-closed error recovery."""

    def test_account_endpoints_ingestion(self, gateway_client: CanaryLiveGatewayClient) -> None:
        """Verify /fapi/v2/account, /fapi/v2/balance, and /fapi/v2/positionRisk responses."""
        account = gateway_client.fetch_account_info()
        assert account["canTrade"] is True
        assert Decimal(account["totalWalletBalance"]) == STARTING_EQUITY_USDT
        assert len(account["positions"]) == 3

        balances = gateway_client.fetch_balances()
        assert len(balances) >= 1
        assert balances[0]["asset"] == "USDT"
        assert Decimal(balances[0]["balance"]) == STARTING_EQUITY_USDT

        positions = gateway_client.fetch_position_risk()
        assert len(positions) == 3
        symbols = {p["symbol"] for p in positions}
        assert symbols == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    def test_timestamp_drift_auto_recovery(
        self,
        mock_gateway: MockBinanceFuturesGateway,
        gateway_client: CanaryLiveGatewayClient,
    ) -> None:
        """Verify automatic timestamp offset resync and retry on code -1021."""
        mock_gateway.inject_timestamp_drift_error = True

        order_params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.00008",
            "price": "60000.00",
            "newClientOrderId": "cid-drift-test",
        }
        # Client should catch -1021, resync server time, and retry successfully
        resp = gateway_client.dispatch_order(order_params)
        assert resp["status"] == "FILLED"
        assert resp["clientOrderId"] == "cid-drift-test"

    def test_rate_limit_backoff_recovery(
        self,
        mock_gateway: MockBinanceFuturesGateway,
        gateway_client: CanaryLiveGatewayClient,
    ) -> None:
        """Verify exponential jittered backoff and retry on HTTP 429."""
        mock_gateway.inject_rate_limit_error = True

        order_params = {
            "symbol": "ETHUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.0019",
            "price": "2500.00",
            "newClientOrderId": "cid-rate-test",
        }
        # Client should catch HTTP 429, apply backoff, and retry successfully
        resp = gateway_client.dispatch_order(order_params)
        assert resp["status"] == "FILLED"
        assert resp["clientOrderId"] == "cid-rate-test"

    def test_network_timeout_and_rest_fallback(
        self,
        mock_gateway: MockBinanceFuturesGateway,
        gateway_client: CanaryLiveGatewayClient,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify network timeout triggers UNKNOWN state and recovers via REST fallback."""
        store = SqliteCanaryLiveGatewayTelemetryStore(tmp_path / "test-telemetry.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test-orders.jsonl")
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=gateway_client,
            telemetry_store=store,
            track_id="test_timeout",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=gateway_client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_timeout",
        )

        mock_gateway.inject_network_timeout = True
        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        # Verify order was recovered cleanly to FILLED via REST fallback
        assert order.status == OrderLifecycleState.FILLED
        assert reconciler.allocated_margin == Decimal("0.00008") * Decimal("60000.00")
        store.close()


# =====================================================================
# 4. Account Ledger Reconciler & Desync Detection Tests
# =====================================================================


class TestAccountLedgerReconciler:
    """Validate remote vs local balance reconciliation and fail-closed desync lockout."""

    def test_nominal_reconciliation_zero_drift(
        self,
        gateway_client: CanaryLiveGatewayClient,
        tmp_path: Path,
    ) -> None:
        """Verify nominal reconciliation confirms zero drift (< 1e-15 USDT)."""
        store = SqliteCanaryLiveGatewayTelemetryStore(tmp_path / "test-telemetry.sqlite3")
        reconciler = LiveGatewayAccountReconciler(
            client=gateway_client,
            telemetry_store=store,
            track_id="test_nominal",
        )
        evt = reconciler.reconcile_with_exchange()
        assert evt.status == GatewaySyncStatus.SYNCHRONIZED
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()

    def test_balance_desync_triggers_hard_abort_lockout(
        self,
        mock_gateway: MockBinanceFuturesGateway,
        gateway_client: CanaryLiveGatewayClient,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify remote balance divergence triggers immediate Tier 2 Hard-Abort and lockout."""
        store = SqliteCanaryLiveGatewayTelemetryStore(tmp_path / "test-telemetry.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test-orders.jsonl")
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=gateway_client,
            telemetry_store=store,
            track_id="test_desync",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=gateway_client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_desync",
        )

        # Initial clean sync
        reconciler.reconcile_with_exchange()

        # Inject 0.50 USDT desync
        mock_gateway.inject_balance_desync_delta = Decimal("0.50")

        with pytest.raises(BalanceDesyncError, match="Balance desync detected"):
            reconciler.reconcile_with_exchange()

        assert reconciler.locked_out is True

        # Subsequent order must be strictly blocked fail-closed
        with pytest.raises(GatewayLockoutError, match="Gateway locked out"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btcusdt-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
        store.close()


# =====================================================================
# 5. Order Dispatch Interlock Tests
# =====================================================================


class TestOrderDispatchInterlocks:
    """Validate micro notional cap, daily loss, rate limit, and symbol interlocks."""

    def test_hard_notional_cap_interlock(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        gateway_client: CanaryLiveGatewayClient,
        tmp_path: Path,
    ) -> None:
        """Verify order with notional > 5.00 USDT is blocked fail-closed."""
        store = SqliteCanaryLiveGatewayTelemetryStore(tmp_path / "test-telemetry.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test-orders.jsonl")
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=gateway_client,
            telemetry_store=store,
            track_id="test_interlock",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=gateway_client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_interlock",
        )

        # Attempt order with notional = 0.001 BTC * 60000 = 60.00 USDT (> 5.00 USDT)
        with pytest.raises(OrderNotionalCapBreachError, match="exceeds hard ceiling"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btcusdt-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.001"),
                price=Decimal("60000.00"),
            )
        store.close()

    def test_unauthorized_symbol_interlock(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        gateway_client: CanaryLiveGatewayClient,
        tmp_path: Path,
    ) -> None:
        """Verify order on unauthorized symbol (e.g. DOGEUSDT) is blocked fail-closed."""
        store = SqliteCanaryLiveGatewayTelemetryStore(tmp_path / "test-telemetry.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test-orders.jsonl")
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=gateway_client,
            telemetry_store=store,
            track_id="test_symbol",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=gateway_client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_symbol",
        )

        with pytest.raises(UnauthorizedSymbolError, match="not in authorized whitelist"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-doge-001",
                symbol="DOGEUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                price=Decimal("0.10"),
            )
        store.close()

    def test_rate_limit_throttle_interlock(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        gateway_client: CanaryLiveGatewayClient,
        tmp_path: Path,
    ) -> None:
        """Verify orders on same symbol submitted < 60s apart are blocked by rate throttle."""
        store = SqliteCanaryLiveGatewayTelemetryStore(tmp_path / "test-telemetry.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test-orders.jsonl")
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=gateway_client,
            telemetry_store=store,
            track_id="test_throttle",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=gateway_client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_throttle",
        )

        # First order on BTCUSDT
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )

        # Advance only 10 seconds (must be >= 60s)
        dispatcher.advance_time(10.0, update_heartbeat=True)

        with pytest.raises(RateLimitThrottleExceededError, match="Order frequency throttle"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btcusdt-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
        store.close()


# =====================================================================
# 6. Full Deterministic Multi-Track Runner & Hash Chain Tests
# =====================================================================


class TestFullMultiTrackRunner:
    """Validate deterministic execution across all 4 simulation tracks."""

    def test_run_track_1_individually(self, tmp_path: Path) -> None:
        """Verify individual execution of Track 1."""
        cfg = CanaryGatewayConfig(
            output_dir=tmp_path / "phase277_t1",
            track="track_1",
        )
        runner = CanaryLiveGatewayRunner(cfg)
        report = runner.execute_all_tracks()
        assert len(report.tracks) == 1
        assert report.tracks[0].track_id == "track_1"
        assert report.tracks[0].success is True
        assert report.tracks[0].zero_balance_drift is True

    def test_run_track_2_individually(self, tmp_path: Path) -> None:
        """Verify individual execution of Track 2."""
        cfg = CanaryGatewayConfig(
            output_dir=tmp_path / "phase277_t2",
            track="track_2",
        )
        runner = CanaryLiveGatewayRunner(cfg)
        report = runner.execute_all_tracks()
        assert len(report.tracks) == 1
        assert report.tracks[0].track_id == "track_2"
        assert report.tracks[0].success is True
        assert report.tracks[0].zero_balance_drift is True

    def test_run_track_3_individually(self, tmp_path: Path) -> None:
        """Verify individual execution of Track 3."""
        cfg = CanaryGatewayConfig(
            output_dir=tmp_path / "phase277_t3",
            track="track_3",
        )
        runner = CanaryLiveGatewayRunner(cfg)
        report = runner.execute_all_tracks()
        assert len(report.tracks) == 1
        assert report.tracks[0].track_id == "track_3"
        assert report.tracks[0].success is True
        assert report.tracks[0].status == "LOCKED_OUT_BALANCE_DESYNC_DETECTED"

    def test_run_track_4_individually(self, tmp_path: Path) -> None:
        """Verify individual execution of Track 4."""
        cfg = CanaryGatewayConfig(
            output_dir=tmp_path / "phase277_t4",
            track="track_4",
        )
        runner = CanaryLiveGatewayRunner(cfg)
        report = runner.execute_all_tracks()
        assert len(report.tracks) == 1
        assert report.tracks[0].track_id == "track_4"
        assert report.tracks[0].success is True

    def test_run_all_tracks_and_verify_hash_chain(self, tmp_path: Path) -> None:
        """Verify execution of all 4 tracks, report generation, and SHA-256 DAG hash chain."""
        out_dir = tmp_path / "phase277_full"
        cfg = CanaryGatewayConfig(
            output_dir=out_dir,
            track="all",
        )
        runner = CanaryLiveGatewayRunner(cfg)
        report = runner.execute_all_tracks()

        assert len(report.tracks) == 4
        assert report.compliance["all_criteria_passed"] is True
        assert report.compliance["zero_balance_drift"] is True
        assert report.compliance["zero_secret_leakage"] is True

        # Verify cryptographic SHA-256 DAG hash chain
        assert verify_phase_277_hash_chain(output_dir=out_dir) is True

    def test_cli_runner_execution_and_verify_only(self, tmp_path: Path) -> None:
        """Verify CLI execution and --verify-only flag."""
        out_dir = tmp_path / "phase277_cli"
        code = execute_phase_277_runner(
            output_dir=out_dir,
            track="all",
            verify_hash_chain=True,
        )
        assert code == 0

        # Run verify-only on same directory
        verify_code = execute_phase_277_runner(
            output_dir=out_dir,
            verify_only=True,
        )
        assert verify_code == 0

    def test_format_summary_table(self, tmp_path: Path) -> None:
        """Verify ASCII summary table formatter."""
        out_dir = tmp_path / "phase277_table"
        cfg = CanaryGatewayConfig(output_dir=out_dir, track="all")
        runner = CanaryLiveGatewayRunner(cfg)
        report = runner.execute_all_tracks()
        table_str = format_summary_table(report)
        assert "PHASE 277: LIVE EXCHANGE GATEWAY SYNCHRONIZATION" in table_str
        assert "track_1" in table_str
        assert "track_2" in table_str
        assert "track_3" in table_str
        assert "track_4" in table_str

    def test_sqlite_telemetry_schema_and_records(self, tmp_path: Path) -> None:
        """Verify SQLite telemetry database schema and persistence of all tables."""
        db_path = tmp_path / "telemetry_schema_test.sqlite3"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)

        # Inspect table creation
        with closing(sqlite3.connect(str(db_path))) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
        expected_tables = {
            "gateway_sync_events",
            "orders",
            "lifecycle_transitions",
            "gateway_errors",
            "interlock_events",
            "balance_snapshots",
            "gateway_tracks",
        }
        assert expected_tables.issubset(tables)

        # Verify record persistence
        sync_evt = GatewaySyncEvent(
            track_id="track_1",
            server_time_ms=1600000000000,
            local_time_ms=1600000000000,
            drift_ms=0,
            remote_wallet_balance_usdt=Decimal("100.00"),
            remote_unrealized_pnl_usdt=Decimal("0.00"),
            remote_allocated_margin_usdt=Decimal("0.00"),
            local_cash_usdt=Decimal("100.00"),
            local_unrealized_pnl_usdt=Decimal("0.00"),
            local_allocated_margin_usdt=Decimal("0.00"),
            desync_drift_usdt=Decimal("0.00"),
            status=GatewaySyncStatus.SYNCHRONIZED,
        )
        store.record_sync_event(sync_evt)

        err_rec = GatewayErrorRecord(
            track_id="track_2",
            endpoint="/fapi/v1/order",
            error_code=-1021,
            error_message="Timestamp drift",
            recovery_action="Resync server time",
            resolved=True,
        )
        store.record_error(err_rec)
        store.checkpoint()
        store.close()

        with closing(sqlite3.connect(str(db_path))) as conn:
            sync_count = conn.execute("SELECT COUNT(*) FROM gateway_sync_events;").fetchone()[0]
            err_count = conn.execute("SELECT COUNT(*) FROM gateway_errors;").fetchone()[0]
        assert sync_count == 1
        assert err_count == 1

    def test_adverse_drift_simulation_fails_closed(self, tmp_path: Path) -> None:
        """Verify that synthetic adverse accounting drift triggers fail-closed rejection."""
        out_dir = tmp_path / "phase277_adverse"
        cfg = CanaryGatewayConfig(
            output_dir=out_dir,
            track="track_1",
            simulate_adverse_drift=True,
        )
        runner = CanaryLiveGatewayRunner(cfg)
        report = runner.execute_all_tracks()

        assert report.compliance["zero_balance_drift"] is False
        assert report.compliance["all_criteria_passed"] is False
        assert report.tracks[0].zero_balance_drift is False
        assert report.tracks[0].success is False

        # Hash chain must fail verification due to balance drift breach
        assert verify_phase_277_hash_chain(output_dir=out_dir) is False

    def test_hash_chain_tampering_detection(self, tmp_path: Path) -> None:
        """Verify that tampering with artifact files causes hash chain failure."""
        out_dir = tmp_path / "phase277_tamper"
        cfg = CanaryGatewayConfig(output_dir=out_dir, track="all")
        runner = CanaryLiveGatewayRunner(cfg)
        runner.execute_all_tracks()

        assert verify_phase_277_hash_chain(output_dir=out_dir) is True

        # Tamper with gateway-summary.json
        summary_path = out_dir / "gateway-summary.json"
        content = json.loads(summary_path.read_text(encoding="utf-8"))
        content["gateway_status"] = "TAMPERED_STATUS"
        summary_path.write_text(json.dumps(content))

        # Verification must now fail
        assert verify_phase_277_hash_chain(output_dir=out_dir) is False

    def test_cli_main_entry_point(self, tmp_path: Path) -> None:
        """Verify CLI main entry point with JSON argument parsing."""
        out_dir = tmp_path / "phase277_cli_main"
        argv = [
            "--output-dir",
            str(out_dir),
            "--track",
            "1",
            "--json",
            "--verify-hash-chain",
        ]
        ret = cli_main(argv)
        assert ret == 0
        assert (out_dir / "paper-summary.json").is_file()


class TestHardenedGatewayVerification:
    """Adversarial verification of double-entry drift, partial fills, cancellation."""

    def test_active_position_double_entry_zero_drift(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify drift is strictly < 1e-15 during active open position and after closure."""
        db_path = tmp_path / "telemetry.sqlite3"
        jsonl_path = tmp_path / "orders.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)

        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()

        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=DAILY_LOSS_BUDGET_USDT,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_1",
            starting_equity=STARTING_EQUITY_USDT,
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_1",
        )

        reconciler.reconcile_with_exchange()
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Open BTC position: 0.00008 @ 60000 = 4.80 USDT
        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert order.status == OrderLifecycleState.FILLED

        # CRITICAL TEST: Double-entry integrity WHILE position is active
        assert reconciler.allocated_margin == Decimal("4.80")
        assert reconciler.cash < STARTING_EQUITY_USDT - Decimal("4.80")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Close position
        dispatcher.advance_time(65.0, update_heartbeat=True)
        close_order = dispatcher.dispatch_micro_order(
            candidate_id="cand-001",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            is_closing=True,
        )
        assert close_order.status == OrderLifecycleState.FILLED
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        store.checkpoint()
        store.close()

        # Check all snapshots in SQLite
        chk_store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        passed, max_drift = chk_store.verify_double_entry_integrity(require_records=True)
        assert passed is True
        assert max_drift < DOUBLE_ENTRY_MAX_DRIFT
        chk_store.close()

    def test_sqlite_verify_double_entry_integrity_detects_drift(self, tmp_path: Path) -> None:
        """Verify that SqliteCanaryLiveGatewayTelemetryStore detects drift >= 1e-15."""
        db_path = tmp_path / "drift_test.sqlite3"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        snap = GatewayBalanceSnapshot(
            track_id="track_1",
            cash_usdt=Decimal("95.00"),
            allocated_margin_usdt=Decimal("0"),
            unrealized_pnl_usdt=Decimal("0"),
            realized_pnl_usdt=Decimal("0"),
            equity_usdt=Decimal("95.00"),
            drift_usdt=Decimal("5.00000000"),
        )
        store.record_balance_snapshot(snap)
        store.checkpoint()

        passed, max_drift = store.verify_double_entry_integrity(require_records=True)
        assert passed is False
        assert max_drift == Decimal("5.00000000")
        assert store.verify_unlocked() is True
        store.close()

    def test_partial_fill_lifecycle_and_accounting(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify NEW -> PARTIALLY_FILLED -> FILLED lifecycle transitions and accounting."""
        db_path = tmp_path / "telemetry_pf.sqlite3"
        jsonl_path = tmp_path / "orders_pf.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)

        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            key_vault=safe_key_vault,
        )
        mock_exchange.inject_order_initial_status = "NEW"

        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=DAILY_LOSS_BUDGET_USDT,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_1",
            starting_equity=STARTING_EQUITY_USDT,
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_1",
        )

        reconciler.reconcile_with_exchange()

        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert order.status == OrderLifecycleState.NEW
        assert order.executed_quantity == Decimal("0")
        assert dispatcher.orders_placed_count == 1
        assert dispatcher.orders_filled_count == 0
        assert reconciler.allocated_margin == Decimal("0")

        # Process first partial fill (half: 0.00004 @ 60000 = 2.40 USDT)
        dispatcher.process_fill_event(
            client_order_id=order.client_order_id,
            fill_qty=Decimal("0.00004"),
            fill_price=Decimal("60000.00"),
        )
        assert order.status == OrderLifecycleState.PARTIALLY_FILLED
        assert order.executed_quantity == Decimal("0.00004")
        assert reconciler.allocated_margin == Decimal("2.40")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        assert dispatcher.orders_filled_count == 0

        # Process second fill to complete order
        dispatcher.process_fill_event(
            client_order_id=order.client_order_id,
            fill_qty=Decimal("0.00004"),
            fill_price=Decimal("60000.00"),
        )
        assert order.status == OrderLifecycleState.FILLED
        assert order.executed_quantity == Decimal("0.00008")
        assert reconciler.allocated_margin == Decimal("4.80")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        assert dispatcher.orders_filled_count == 1
        store.close()

    def test_order_cancellation_lifecycle(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify order cancellation transitions to CANCELED and prevents invalid cancellation."""
        db_path = tmp_path / "telemetry_cancel.sqlite3"
        jsonl_path = tmp_path / "orders_cancel.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)

        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            key_vault=safe_key_vault,
        )
        mock_exchange.inject_order_initial_status = "NEW"

        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=DAILY_LOSS_BUDGET_USDT,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_1",
            starting_equity=STARTING_EQUITY_USDT,
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_1",
        )

        reconciler.reconcile_with_exchange()
        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert order.status == OrderLifecycleState.NEW

        # Cancel order
        canceled = dispatcher.cancel_order(order.symbol, order.client_order_id)
        assert canceled.status == OrderLifecycleState.CANCELED
        assert dispatcher.orders_cancelled_count == 1

        # Attempting to cancel already canceled order raises error
        with pytest.raises(CanaryLiveGatewayError, match="Cannot cancel order"):
            dispatcher.cancel_order(order.symbol, order.client_order_id)

        # Attempting to cancel non-existent order raises error
        with pytest.raises(CanaryLiveGatewayError, match="Unknown client_order_id"):
            dispatcher.cancel_order("BTCUSDT", "non-existent-id")
        store.close()

    def test_network_timeout_recovery_partial_fill(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify network timeout on dispatch recovers PARTIALLY_FILLED state via REST fallback."""
        db_path = tmp_path / "telemetry_timeout_pf.sqlite3"
        jsonl_path = tmp_path / "orders_timeout_pf.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)

        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            key_vault=safe_key_vault,
        )
        mock_exchange.inject_network_timeout = True
        mock_exchange.inject_order_initial_status = "PARTIALLY_FILLED"
        mock_exchange.inject_partial_fill_qty = Decimal("0.00004")

        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=DAILY_LOSS_BUDGET_USDT,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_4",
            starting_equity=STARTING_EQUITY_USDT,
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_4",
        )

        reconciler.reconcile_with_exchange()
        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert order.status == OrderLifecycleState.PARTIALLY_FILLED
        assert order.executed_quantity == Decimal("0.00004")
        assert reconciler.allocated_margin == Decimal("2.40")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()

    def test_dispatcher_input_guards_and_invariants(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify invalid price, quantity, non-existent close, and overdraft are rejected."""
        db_path = tmp_path / "telemetry_guards.sqlite3"
        jsonl_path = tmp_path / "orders_guards.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)

        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=DAILY_LOSS_BUDGET_USDT,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_1",
            starting_equity=STARTING_EQUITY_USDT,
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_1",
        )
        reconciler.reconcile_with_exchange()

        # Non-positive price
        with pytest.raises(OrderNotionalCapBreachError, match="strictly positive"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("0"),
            )

        # Non-positive quantity
        with pytest.raises(OrderNotionalCapBreachError, match="strictly positive"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("-0.001"),
                price=Decimal("60000.00"),
            )

        # Closing non-existent position
        with pytest.raises(CanaryLiveGatewayError, match="no active position exists"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-001",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                is_closing=True,
            )

        # Insufficient free cash
        reconciler.cash = Decimal("2.00")
        with pytest.raises(CanaryLiveGatewayError, match="Insufficient free cash"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-001",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
        store.close()

    def test_three_endpoint_reconciliation_and_cross_asset_margin(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
    ) -> None:
        """Verify reconciler queries all 3 endpoints and computes cross-asset margin."""
        db_path = tmp_path / "telemetry_endpoints.sqlite3"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("200.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_1",
            starting_equity=Decimal("200.00"),
        )
        evt = reconciler.reconcile_with_exchange()
        assert evt.status == GatewaySyncStatus.SYNCHRONIZED
        assert "/fapi/v2/account" in evt.details["endpoints_queried"]
        assert "/fapi/v2/balance" in evt.details["endpoints_queried"]
        assert "/fapi/v2/positionRisk" in evt.details["endpoints_queried"]
        assert "cross_asset_margin_utilization" in evt.details
        assert "per_asset_margin" in evt.details
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()
