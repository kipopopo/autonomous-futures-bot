"""Unit tests for Phase 277: Live Exchange Gateway Synchronization Runner
& Shadow Order Dispatch Harness.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Mapping
from contextlib import closing
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
    MarginCapBreachError,
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
    ExchangeRateLimitError,
    GatewayBalanceSnapshot,
    GatewayErrorRecord,
    GatewayLockoutError,
    GatewaySyncEvent,
    GatewaySyncStatus,
    JsonlCanaryOrderSink,
    LiveGatewayAccountReconciler,
    MockBinanceFuturesGateway,
    NetworkTimeoutError,
    OrderLifecycleState,
    PrerequisiteQualificationError,
    SqliteCanaryLiveGatewayTelemetryStore,
    TimestampDriftError,
    UnknownOrderStatusError,
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

    def test_mark_price_fluctuation_reconciliation_zero_drift(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify exchange mark price changes update local PnL without false desync."""
        db_path = tmp_path / "telemetry_mark_fluct.sqlite3"
        jsonl_path = tmp_path / "orders_mark_fluct.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_mark_fluct",
            starting_equity=Decimal("100.00"),
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_mark_fluct",
        )
        # Open 0.00008 BTC @ 60,000.00 (4.80 USDT margin)
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        # Move exchange mark price by +$1000
        mock_exchange.set_mark_price("BTCUSDT", Decimal("61000.00"))

        # Reconcile must not trip desync and must update local unrealized PnL
        evt = reconciler.reconcile_with_exchange()
        assert evt.status == GatewaySyncStatus.SYNCHRONIZED
        assert reconciler.locked_out is False
        assert reconciler.unrealized_pnl == Decimal("0.08000000")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()

    def test_position_discrepancy_triggers_desync_lockout(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
    ) -> None:
        """Verify position divergence between remote exchange and local ledger trips lockout."""
        db_path = tmp_path / "telemetry_pos_desync.sqlite3"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_pos_desync",
            starting_equity=Decimal("100.00"),
        )
        # Inject phantom remote position on BTCUSDT
        mock_exchange.positions["BTCUSDT"]["positionAmt"] = "0.00010"

        with pytest.raises(BalanceDesyncError, match="Position discrepancy on BTCUSDT"):
            reconciler.reconcile_with_exchange()

        assert reconciler.locked_out is True
        store.close()

    def test_unauthorized_symbol_triggers_desync_lockout(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
    ) -> None:
        """Verify rogue position on non-staged symbol triggers immediate fail-closed lockout."""
        db_path = tmp_path / "telemetry_unauth_sym.sqlite3"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        # Add unauthorized symbol to mock exchange
        mock_exchange.positions["DOGEUSDT"] = {
            "symbol": "DOGEUSDT",
            "positionAmt": "1000.0",
            "entryPrice": "0.10",
            "markPrice": "0.10",
            "unRealizedProfit": "0.00000000",
            "initialMargin": "100.00000000",
            "positionInitialMargin": "100.00000000",
            "maintMargin": "0.00000000",
            "openOrderInitialMargin": "0.00000000",
            "leverage": "1",
            "isolated": False,
            "positionSide": "BOTH",
        }
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_unauth_sym",
            starting_equity=Decimal("100.00"),
        )
        with pytest.raises(
            BalanceDesyncError,
            match="Unauthorized position detected on non-canary symbol DOGEUSDT",
        ):
            reconciler.reconcile_with_exchange()

        assert reconciler.locked_out is True
        store.close()

    def test_cross_endpoint_balance_divergence_triggers_lockout(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
    ) -> None:
        """Verify inconsistency between /fapi/v2/account and /fapi/v2/balance triggers lockout."""
        db_path = tmp_path / "telemetry_endpoint_desync.sqlite3"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_endpoint_desync",
            starting_equity=Decimal("100.00"),
        )
        # Invalidate /fapi/v2/balance relative to /fapi/v2/account
        orig_get_balance = mock_exchange.get_balance

        def tampered_balance(params: Any, sig: Any) -> list[dict[str, Any]]:
            bals = orig_get_balance(params, sig)
            bals[0]["balance"] = "80.00000000"  # Diverges by 20 USDT
            return bals

        mock_exchange.get_balance = tampered_balance  # type: ignore[assignment]

        with pytest.raises(BalanceDesyncError, match="Exchange balance discrepancy"):
            reconciler.reconcile_with_exchange()

        assert reconciler.locked_out is True
        store.close()

    def test_short_position_lifecycle_and_double_entry(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify opening and closing short positions satisfies exact double-entry accounting."""
        db_path = tmp_path / "telemetry_short.sqlite3"
        jsonl_path = tmp_path / "orders_short.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_short",
            starting_equity=Decimal("100.00"),
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_short",
        )
        # 1. Open SHORT: SELL 0.032 SOLUSDT @ 150.00 (notional = 4.80 USDT)
        short_order = dispatcher.dispatch_micro_order(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
            is_closing=False,
        )
        assert short_order.status == OrderLifecycleState.FILLED
        assert reconciler.positions["SOLUSDT"] == Decimal("-0.032")
        assert reconciler.allocated_margin == Decimal("4.80")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Intermediate Reconcile
        evt1 = reconciler.reconcile_with_exchange()
        assert evt1.status == GatewaySyncStatus.SYNCHRONIZED

        # 2. Close SHORT: BUY 0.032 SOLUSDT @ 150.00 (is_closing=True)
        dispatcher.advance_time(65.0, update_heartbeat=True)
        close_short = dispatcher.dispatch_micro_order(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
            is_closing=True,
        )
        assert close_short.status == OrderLifecycleState.FILLED
        assert reconciler.positions["SOLUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Final Reconcile
        evt2 = reconciler.reconcile_with_exchange()
        assert evt2.status == GatewaySyncStatus.SYNCHRONIZED
        store.close()

    def test_short_position_invalid_closing_rejected(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify invalid attempts to close a short position fail closed."""
        db_path = tmp_path / "telemetry_short_inv.sqlite3"
        jsonl_path = tmp_path / "orders_short_inv.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_short_inv",
            starting_equity=Decimal("100.00"),
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_short_inv",
        )
        # Open SHORT
        dispatcher.dispatch_micro_order(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
            is_closing=False,
        )
        # Attempt to close short with SELL side
        dispatcher.advance_time(65.0, update_heartbeat=True)
        with pytest.raises(CanaryLiveGatewayError, match="expected BUY"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-sol",
                symbol="SOLUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.032"),
                price=Decimal("150.00"),
                is_closing=True,
            )
        # Attempt to close short with quantity exceeding active short position
        with pytest.raises(CanaryLiveGatewayError, match="exceeds active short position"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-sol",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.040"),
                price=Decimal("150.00"),
                is_closing=True,
            )
        store.close()

    def test_unknown_order_blocks_subsequent_order_dispatch(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify that an unresolved UNKNOWN order strictly blocks new order routing per R2."""
        db_path = tmp_path / "telemetry_unknown_block.sqlite3"
        jsonl_path = tmp_path / "orders_unknown_block.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_unknown",
            starting_equity=Decimal("100.00"),
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_unknown",
        )

        # Tamper query_order to fail persistently, leaving order in UNKNOWN state
        def failing_query(params: Any, sig: Any) -> dict[str, Any]:
            raise CanaryLiveGatewayError("Network partition: cannot connect to host")

        mock_exchange.query_order = failing_query  # type: ignore[assignment]
        mock_exchange.inject_network_timeout = True

        with pytest.raises(UnknownOrderStatusError, match="remains UNKNOWN"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )

        # Attempt to dispatch subsequent order: must be blocked with UnknownOrderStatusError
        with pytest.raises(UnknownOrderStatusError, match="existing order is in UNKNOWN state"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-eth",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.0019"),
                price=Decimal("2500.00"),
            )
        store.close()

    def test_network_timeout_ingress_drop_handled_as_rejected(
        self,
        tmp_path: Path,
        safe_key_vault: SecureExchangeKeyVault,
        sample_certificate: CanaryActivationCertificate,
    ) -> None:
        """Verify order dropped before matching engine is recovered cleanly as REJECTED."""
        db_path = tmp_path / "telemetry_ingress_drop.sqlite3"
        jsonl_path = tmp_path / "orders_ingress_drop.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_exchange = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_exchange)
        client.sync_server_time()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="track_ingress_drop",
            starting_equity=Decimal("100.00"),
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="track_ingress_drop",
        )

        def ingress_drop_place(params: Any, sig: Any) -> dict[str, Any]:
            mock_exchange._verify_auth(params, sig)
            raise NetworkTimeoutError("Socket closed during TCP transmission")

        mock_exchange.place_order = ingress_drop_place  # type: ignore[assignment]

        order = dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        # Order should have been queried via fallback, found non-existent, and marked REJECTED
        assert order.status == OrderLifecycleState.REJECTED
        assert "not found" in (order.rejection_reason or "").lower()
        assert dispatcher.orders_rejected_count == 1
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()

    def test_rate_limit_backoff_freeze_and_safe_resumption(
        self,
        safe_key_vault: SecureExchangeKeyVault,
    ) -> None:
        """Verify client rejects dispatch during rate-limit freeze and resumes after backoff."""
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        now_time = 1000.0
        client = CanaryLiveGatewayClient(
            key_vault=safe_key_vault,
            gateway=mock_gateway,
            clock_fn=lambda: now_time,
        )
        # Set active rate-limit freeze for 2.0 seconds
        client.rate_limit_backoff_until_epoch = now_time + 2.0

        order_params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.00008",
            "price": "60000.00",
            "newClientOrderId": "cid-freeze-test",
        }
        # While now_time < freeze_until, dispatch must be frozen
        with pytest.raises(
            ExchangeRateLimitError,
            match="Order dispatch frozen due to rate-limit backoff",
        ):
            client.dispatch_order(order_params)

        # Advance clock past freeze
        now_time += 2.5
        resp = client.dispatch_order(order_params)
        assert resp["status"] == "FILLED"

    def test_mock_gateway_terminal_cancellation_rejected(
        self,
        safe_key_vault: SecureExchangeKeyVault,
        gateway_client: CanaryLiveGatewayClient,
        mock_gateway: MockBinanceFuturesGateway,
    ) -> None:
        """Verify MockBinanceFuturesGateway rejects cancelling an already FILLED order."""
        order_params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.00008",
            "price": "60000.00",
            "newClientOrderId": "cid-filled-cancel-test",
        }
        resp = gateway_client.dispatch_order(order_params)
        assert resp["status"] == "FILLED"

        with pytest.raises(CanaryLiveGatewayError, match="terminal state"):
            gateway_client.cancel_order("BTCUSDT", "cid-filled-cancel-test")

    def test_telemetry_store_and_sink_string_path_initialization(
        self,
        tmp_path: Path,
    ) -> None:
        """Verify SqliteCanaryLiveGatewayTelemetryStore and JsonlCanaryOrderSink
        accept str paths.
        """
        str_db = str(tmp_path / "subdir" / "test_str.sqlite3")
        str_jsonl = str(tmp_path / "subdir" / "test_str.jsonl")

        store = SqliteCanaryLiveGatewayTelemetryStore(str_db)
        sink = JsonlCanaryOrderSink(str_jsonl)

        assert store.verify_unlocked() is True
        assert sink.file_path.name == "test_str.jsonl"
        store.close()

    def test_opposing_order_without_closing_flag_rejected(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify opening orders opposing active position direction without
        is_closing=True are rejected fail-closed.
        """
        db_path = tmp_path / "telemetry_oppose.sqlite3"
        jsonl_path = tmp_path / "orders_oppose.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="test_oppose",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_oppose",
        )
        # Open LONG on BTCUSDT
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            is_closing=False,
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")

        # Attempt to dispatch SELL order without is_closing=True -> must be rejected
        with pytest.raises(
            CanaryLiveGatewayError,
            match="Cannot open SELL/SHORT order on BTCUSDT with active LONG position",
        ):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                is_closing=False,
            )

        # Close long properly
        dispatcher.advance_time(10.0, update_heartbeat=True)
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            is_closing=True,
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0")

        # Open SHORT on SOLUSDT
        dispatcher.advance_time(10.0, update_heartbeat=True)
        dispatcher.dispatch_micro_order(
            candidate_id="cand-solusdt-rgb-001",
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
            is_closing=False,
        )
        assert reconciler.positions["SOLUSDT"] == Decimal("-0.032")

        # Attempt to dispatch BUY order without is_closing=True -> must be rejected
        with pytest.raises(
            CanaryLiveGatewayError,
            match="Cannot open BUY/LONG order on SOLUSDT with active SHORT position",
        ):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.032"),
                price=Decimal("150.00"),
                is_closing=False,
            )

        # Close short properly
        dispatcher.advance_time(10.0, update_heartbeat=True)
        dispatcher.dispatch_micro_order(
            candidate_id="cand-solusdt-rgb-001",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
            is_closing=True,
        )
        assert reconciler.positions["SOLUSDT"] == Decimal("0")
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()

    def test_closing_order_auto_calculates_realized_pnl_when_missing_from_exchange_resp(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify closing orders auto-compute realized PnL from entry price when
        the exchange order response omits realizedPnl.
        """
        db_path = tmp_path / "telemetry_pnl.sqlite3"
        jsonl_path = tmp_path / "orders_pnl.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="test_pnl",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_pnl",
        )
        # Open LONG on BTCUSDT at 60000
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        mock_gateway.set_mark_price("BTCUSDT", Decimal("61000.00"))

        orig_dispatch = client.dispatch_order

        def stripped_dispatch(order_params: dict[str, Any]) -> dict[str, Any]:
            resp = orig_dispatch(order_params)
            resp_copy = dict(resp)
            resp_copy.pop("realizedPnl", None)
            return resp_copy

        client.dispatch_order = stripped_dispatch  # type: ignore[method-assign]

        dispatcher.advance_time(10.0, update_heartbeat=True)
        # Close at 61000 with stripped realizedPnl
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("61000.00"),
            is_closing=True,
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.realized_pnl > Decimal("0")
        sync_evt = reconciler.reconcile_with_exchange()
        assert sync_evt.status == GatewaySyncStatus.SYNCHRONIZED
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()

    def test_mock_gateway_position_initial_margin_uses_entry_price(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify MockBinanceFuturesGateway calculates positionInitialMargin using
        entryPrice on partial closes, matching local reconciler exactly.
        """
        db_path = tmp_path / "telemetry_pos_margin.sqlite3"
        jsonl_path = tmp_path / "orders_pos_margin.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="test_margin",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_margin",
        )
        # Open short on SOLUSDT of 0.032 at 150.00
        dispatcher.dispatch_micro_order(
            candidate_id="cand-solusdt-rgb-001",
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
        )
        assert mock_gateway.positions["SOLUSDT"]["positionInitialMargin"] == "4.80000000"

        # Partially close 0.016 at 140.00 (lower price than entry)
        dispatcher.advance_time(10.0, update_heartbeat=True)
        dispatcher.dispatch_micro_order(
            candidate_id="cand-solusdt-rgb-001",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.016"),
            price=Decimal("140.00"),
            is_closing=True,
        )
        # Remaining amount is 0.016, entry price is 150.00 -> margin must be 0.016 * 150 = 2.40
        assert mock_gateway.positions["SOLUSDT"]["positionInitialMargin"] == "2.40000000"
        assert reconciler.allocated_margin == Decimal("2.40")

        sync_evt = reconciler.reconcile_with_exchange()
        assert sync_evt.status == GatewaySyncStatus.SYNCHRONIZED
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()

    def test_mock_gateway_simulate_fill_updates_cum_quote_and_avg_price(
        self,
        safe_key_vault: SecureExchangeKeyVault,
        gateway_client: CanaryLiveGatewayClient,
        mock_gateway: MockBinanceFuturesGateway,
    ) -> None:
        """Verify MockBinanceFuturesGateway.simulate_fill updates cumQuote and
        avgPrice correctly across sequential partial fills.
        """
        mock_gateway.inject_order_initial_status = "NEW"
        order_params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.00008",
            "price": "60000.00",
            "newClientOrderId": "cid-sim-fill-test",
        }
        resp = gateway_client.dispatch_order(order_params)
        assert resp["status"] == "NEW"
        assert resp["avgPrice"] == "0.00000000"

        # Partial fill 1: 0.00004 at 60000.00
        fill_1 = mock_gateway.simulate_fill(
            "cid-sim-fill-test",
            Decimal("0.00004"),
            fill_price=Decimal("60000.00"),
        )
        assert fill_1["status"] == "PARTIALLY_FILLED"
        assert fill_1["avgPrice"] == "60000.00000000"
        order = mock_gateway.orders["cid-sim-fill-test"]
        assert order["cumQuote"] == "2.40000000"
        assert order["avgPrice"] == "60000.00000000"

        # Partial fill 2: 0.00004 at 61000.00
        fill_2 = mock_gateway.simulate_fill(
            "cid-sim-fill-test",
            Decimal("0.00004"),
            fill_price=Decimal("61000.00"),
        )
        assert fill_2["status"] == "FILLED"
        assert fill_2["avgPrice"] == "60500.00000000"
        assert order["cumQuote"] == "4.84000000"
        assert order["avgPrice"] == "60500.00000000"

    def test_recover_unknown_order_after_network_restoration(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify recover_unknown_order re-queries exchange after network restoration,
        resolves UNKNOWN order, and unblocks new order routing.
        """
        db_path = tmp_path / "telemetry_rec.sqlite3"
        jsonl_path = tmp_path / "orders_rec.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="test_rec",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_rec",
        )
        orig_query = mock_gateway.query_order

        def failing_query(p: Mapping[str, Any], s: str | None) -> dict[str, Any]:
            raise CanaryLiveGatewayError("Persistent network outage: endpoint unreachable")

        mock_gateway.query_order = failing_query  # type: ignore[method-assign]
        mock_gateway.inject_network_timeout = True

        with pytest.raises(UnknownOrderStatusError, match="remains UNKNOWN"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )

        unknown_order = next(iter(dispatcher.orders.values()))
        assert unknown_order.status == OrderLifecycleState.UNKNOWN

        # Subsequent order must be blocked by UNKNOWN gate
        with pytest.raises(UnknownOrderStatusError, match="existing order is in UNKNOWN state"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-ethusdt-dcb-003",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.0019"),
                price=Decimal("2500.00"),
            )

        # Restore network connectivity
        mock_gateway.query_order = orig_query  # type: ignore[method-assign]

        # Call recover_unknown_order
        recovered = dispatcher.recover_unknown_order(unknown_order.client_order_id)
        assert recovered.status == OrderLifecycleState.FILLED

        # Now subsequent order can be placed freely
        dispatcher.advance_time(10.0, update_heartbeat=True)
        eth_order = dispatcher.dispatch_micro_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
        )
        assert eth_order.status == OrderLifecycleState.FILLED
        store.close()

    def test_reconcile_with_exchange_locks_out_on_can_trade_false_or_can_withdraw_true(
        self,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify reconcile_with_exchange triggers lockout if canTrade=False
        or canWithdraw=True.
        """
        db_path = tmp_path / "telemetry_sec.sqlite3"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="test_sec",
        )
        orig_get_account = mock_gateway.get_account

        def disabled_trade_account(p: Mapping[str, Any], s: str | None) -> dict[str, Any]:
            acc = orig_get_account(p, s)
            acc["canTrade"] = False
            return acc

        mock_gateway.get_account = disabled_trade_account  # type: ignore[method-assign]
        with pytest.raises(BalanceDesyncError, match="canTrade=False"):
            reconciler.reconcile_with_exchange()
        assert reconciler.locked_out is True

        # Reset and test canWithdraw=True
        mock_gateway.get_account = orig_get_account  # type: ignore[method-assign]
        reconciler.locked_out = False

        def withdrawal_enabled_account(p: Mapping[str, Any], s: str | None) -> dict[str, Any]:
            acc = orig_get_account(p, s)
            acc["canWithdraw"] = True
            return acc

        mock_gateway.get_account = withdrawal_enabled_account  # type: ignore[method-assign]
        with pytest.raises(BalanceDesyncError, match="canWithdraw=True"):
            reconciler.reconcile_with_exchange()
        assert reconciler.locked_out is True
        store.close()

    def test_update_mark_price_rejects_non_finite_or_non_positive(
        self,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify update_mark_price and set_mark_price strictly reject non-finite
        and non-positive values.
        """
        store = SqliteCanaryLiveGatewayTelemetryStore(tmp_path / "telemetry_mp.sqlite3")
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="test_mp",
        )
        for invalid_val in [
            Decimal("0"),
            Decimal("-1.0"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
        ]:
            with pytest.raises(DomainViolation, match="strictly positive and finite"):
                reconciler.update_mark_price("BTCUSDT", invalid_val)
            with pytest.raises(DomainViolation, match="strictly positive and finite"):
                mock_gateway.set_mark_price("BTCUSDT", invalid_val)
        store.close()

    def test_multi_attempt_timestamp_drift_recovery(
        self,
        safe_key_vault: SecureExchangeKeyVault,
    ) -> None:
        """Verify client succeeds when 2 consecutive requests experience timestamp
        drift and resync.
        """
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
        attempts = 0
        orig_get_balance = mock_gateway.get_balance

        def drifting_get_balance(p: Mapping[str, Any], s: str | None) -> list[dict[str, Any]]:
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise TimestampDriftError("Timestamp ahead/behind server clock")
            return orig_get_balance(p, s)

        mock_gateway.get_balance = drifting_get_balance  # type: ignore[method-assign]
        bal = client.fetch_balances()
        assert len(bal) == 1
        assert attempts == 3

    def test_asynchronous_multi_order_partial_fill_sequence_with_fees_and_aggregate_margin_cap(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        tmp_path: Path,
    ) -> None:
        """Verify multi-order partial fill sequence with fees, aggregate margin
        cap enforcement, and exact zero drift.
        """
        db_path = tmp_path / "telemetry_multi_partial.sqlite3"
        jsonl_path = tmp_path / "orders_multi_partial.jsonl"
        store = SqliteCanaryLiveGatewayTelemetryStore(db_path)
        sink = JsonlCanaryOrderSink(jsonl_path)
        mock_gateway = MockBinanceFuturesGateway(
            initial_balance_usdt=Decimal("100.00"),
            key_vault=safe_key_vault,
        )
        client = CanaryLiveGatewayClient(key_vault=safe_key_vault, gateway=mock_gateway)
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        interlock = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=sm,
        )
        reconciler = LiveGatewayAccountReconciler(
            client=client,
            telemetry_store=store,
            track_id="test_multi_part",
        )
        dispatcher = CanaryLiveOrderDispatcher(
            interlock_gateway=interlock,
            client=client,
            reconciler=reconciler,
            telemetry_store=store,
            jsonl_sink=sink,
            track_id="test_multi_part",
        )
        # Order 1: BTCUSDT partial fill 0.00004 at 60000 (margin = 2.40)
        mock_gateway.inject_partial_fill_qty = Decimal("0.00004")
        o1 = dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert o1.status == OrderLifecycleState.PARTIALLY_FILLED
        assert reconciler.allocated_margin == Decimal("2.40")

        # Order 2: ETHUSDT partial fill 0.0010 at 2500 (margin = 2.50)
        dispatcher.advance_time(10.0, update_heartbeat=True)
        mock_gateway.inject_partial_fill_qty = Decimal("0.0010")
        o2 = dispatcher.dispatch_micro_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
        )
        assert o2.status == OrderLifecycleState.PARTIALLY_FILLED
        assert reconciler.allocated_margin == Decimal("4.90")

        # Complete Order 1 via mock_gateway.simulate_fill and process_fill_event
        mock_gateway.simulate_fill(
            o1.client_order_id,
            Decimal("0.00004"),
            fill_price=Decimal("60000.00"),
            fee=Decimal("0.0010"),
        )
        dispatcher.process_fill_event(
            client_order_id=o1.client_order_id,
            fill_qty=Decimal("0.00004"),
            fill_price=Decimal("60000.00"),
            fee=Decimal("0.0010"),
        )
        assert o1.status == OrderLifecycleState.FILLED
        assert reconciler.allocated_margin == Decimal("7.30")

        # Complete Order 2 via mock_gateway.simulate_fill and process_fill_event
        mock_gateway.simulate_fill(
            o2.client_order_id,
            Decimal("0.0009"),
            fill_price=Decimal("2500.00"),
            fee=Decimal("0.0010"),
        )
        dispatcher.process_fill_event(
            client_order_id=o2.client_order_id,
            fill_qty=Decimal("0.0009"),
            fill_price=Decimal("2500.00"),
            fee=Decimal("0.0010"),
        )
        assert o2.status == OrderLifecycleState.FILLED
        assert reconciler.allocated_margin == Decimal("9.55")

        # Attempt order that would breach aggregate margin cap
        sample_certificate.max_aggregate_margin_usdt = "10.00"
        with pytest.raises(MarginCapBreachError, match="would breach aggregate margin cap"):
            dispatcher.dispatch_micro_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.032"),
                price=Decimal("150.00"),
            )
        sample_certificate.max_aggregate_margin_usdt = str(DEFAULT_AGGREGATE_MARGIN_CAP)

        # Reconcile mid-flight
        sync_mid = reconciler.reconcile_with_exchange()
        assert sync_mid.status == GatewaySyncStatus.SYNCHRONIZED
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Close Order 1
        dispatcher.advance_time(65.0, update_heartbeat=True)
        c1 = dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            is_closing=True,
        )
        assert c1.status == OrderLifecycleState.FILLED

        # Close Order 2
        dispatcher.advance_time(65.0, update_heartbeat=True)
        c2 = dispatcher.dispatch_micro_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
            is_closing=True,
        )
        assert c2.status == OrderLifecycleState.FILLED

        assert reconciler.allocated_margin == Decimal("0")
        sync_final = reconciler.reconcile_with_exchange()
        assert sync_final.status == GatewaySyncStatus.SYNCHRONIZED
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
        store.close()
