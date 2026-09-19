"""Unit tests for Phase 276: Operator Canary Authorization
& Live Order Dispatch Interlock Harness.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.canary_activation import (  # noqa: E402
    CANARY_STAGED_SYMBOLS,
    DAILY_LOSS_BUDGET_USDT,
    DEFAULT_AGGREGATE_MARGIN_CAP,
    DEFAULT_PER_ASSET_MARGIN_CAP,
    DEFAULT_PHASE276_OUTPUT_DIR,
    HARD_NOTIONAL_CAP_USDT,
    STARTING_EQUITY_USDT,
    AccountingDriftError,
    CanaryActivationCertificate,
    CanaryActivationConfig,
    CanaryActivationError,
    CanaryActivationReport,
    CanaryActivationRunner,
    CanaryActivationSimulator,
    CanaryActivationTrackResult,
    CanaryOrderDispatchInterlockGateway,
    CertificateExpiredError,
    CertificateInvalidatedError,
    CertificateStatus,
    CircuitBreakerInterlockError,
    DailyLossBudgetLockoutError,
    ExchangeApiKeyPermissions,
    JsonlCanaryOrderSink,
    LiquidityRole,
    MarginCapBreachError,
    MarketDepthTick,
    MicroCanaryFill,
    MicroCanaryOrder,
    MissingRequiredPermissionError,
    OrderNotionalCapBreachError,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    PositionStatus,
    RateLimitThrottleExceededError,
    SecretToken,
    SecureExchangeKeyVault,
    SqliteCanaryActivationTelemetryStore,
    StaleHeartbeatInterlockError,
    TimestampDriftWindowExceededError,
    UnauthorizedSymbolError,
    UnpermittedPermissionError,
    UpstreamPrerequisiteNotMetError,
    WithdrawalPermissionDetectedError,
    compute_certificate_signature,
    verify_phase_276_hash_chain,
    verify_upstream_phase275_qualification,
)
from autonomous_futures.feed.circuit_breaker_drill import (  # noqa: E402
    CanaryCircuitBreakerRecoveryStateMachine,
)
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    CircuitBreakerState,
)
from autonomous_futures.paper.staging import (  # noqa: E402
    assert_zero_secrets,
)
from scripts.run_phase_276_canary_activation import (  # noqa: E402
    build_arg_parser,
    format_summary_table,
)
from scripts.run_phase_276_canary_activation import (  # noqa: E402
    main as cli_main,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def fresh_sm() -> CanaryCircuitBreakerRecoveryStateMachine:
    """Provide a fresh circuit breaker recovery state machine."""
    return CanaryCircuitBreakerRecoveryStateMachine(recovery_hysteresis_ticks=5)


@pytest.fixture
def sample_certificate() -> CanaryActivationCertificate:
    """Provide a valid test canary activation certificate."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "certificate_id": "cert-test-001",
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
def safe_key_vault() -> SecureExchangeKeyVault:
    """Provide a key vault configured with safe trading-only credentials."""
    vault = SecureExchangeKeyVault()
    vault.load_credentials(
        api_key="unit_test_safe_key_001",
        api_secret="unit_test_safe_secret_001",
        permissions=ExchangeApiKeyPermissions(
            enable_reading=True,
            enable_futures_trading=True,
            enable_withdrawals=False,
            permits_universal_transfer=False,
            enable_internal_transfer=False,
            enable_sub_account_transfer=False,
        ),
    )
    return vault


# =====================================================================
# 1. Upstream Phase 275 Prerequisite Verification Tests
# =====================================================================


class TestUpstreamPhase275Verification:
    """Validate strict pre-condition checks on upstream Phase 275 certification."""

    def test_verify_upstream_success(self) -> None:
        """Verify that existing Phase 275 artifacts pass verification."""
        rep_hash, sum_hash = verify_upstream_phase275_qualification()
        assert len(rep_hash) == 64
        assert len(sum_hash) == 64

    def test_verify_upstream_missing_directory(self, tmp_path: Path) -> None:
        """Verify fail-closed rejection when Phase 275 directory does not exist."""
        empty_dir = tmp_path / "nonexistent"
        with pytest.raises(UpstreamPrerequisiteNotMetError, match="Missing Phase 275 artifacts"):
            verify_upstream_phase275_qualification(empty_dir)

    def test_verify_upstream_uncertified_state(self, tmp_path: Path) -> None:
        """Verify fail-closed rejection when promotion state is not certified."""
        p275_dir = tmp_path / "phase275"
        p275_dir.mkdir(parents=True)
        report_data = {
            "promotion_assessment": {"promotion_state": "PROMOTION_REJECTED"},
            "compliance": {"all_criteria_passed": False},
        }
        summary_data = {"phase": "phase_275", "promotion_authorized": False}
        (p275_dir / "canary-live-readiness-report.json").write_text(json.dumps(report_data))
        (p275_dir / "rehearsal-summary.json").write_text(json.dumps(summary_data))

        with pytest.raises(UpstreamPrerequisiteNotMetError, match="Upstream promotion_state"):
            verify_upstream_phase275_qualification(p275_dir)

    def test_verify_upstream_criteria_failed(self, tmp_path: Path) -> None:
        """Verify fail-closed rejection when all_criteria_passed is False."""
        p275_dir = tmp_path / "phase275"
        p275_dir.mkdir(parents=True)
        report_data = {
            "promotion_assessment": {"promotion_state": "CERTIFIED_FOR_PRODUCTION_CANARY"},
            "compliance": {"all_criteria_passed": False},
        }
        summary_data = {"phase": "phase_275", "promotion_authorized": True}
        (p275_dir / "canary-live-readiness-report.json").write_text(json.dumps(report_data))
        (p275_dir / "rehearsal-summary.json").write_text(json.dumps(summary_data))

        with pytest.raises(
            UpstreamPrerequisiteNotMetError, match="all_criteria_passed is not True"
        ):
            verify_upstream_phase275_qualification(p275_dir)


# =====================================================================
# 2. Canary Activation Certificate Governance Tests
# =====================================================================


class TestCanaryActivationCertificate:
    """Validate cryptographic certificate issuance, expiry, and invalidation semantics."""

    def test_certificate_signature_deterministic(
        self, sample_certificate: CanaryActivationCertificate
    ) -> None:
        """Verify SHA-256 signature is deterministic and tamper-evident."""
        data = sample_certificate.model_dump()
        sig = compute_certificate_signature(data)
        assert sig == sample_certificate.cryptographic_signature

        # Tampering with operator ID changes signature
        tampered_data = dict(data)
        tampered_data["operator_id"] = "malicious_operator"
        tampered_sig = compute_certificate_signature(tampered_data)
        assert tampered_sig != sig

    def test_certificate_expiration_check(
        self, sample_certificate: CanaryActivationCertificate
    ) -> None:
        """Verify expiration detection logic against simulated timestamps."""
        assert not sample_certificate.is_expired()

        # Future time past 24h
        future_time = datetime.now(UTC) + timedelta(hours=25)
        assert sample_certificate.is_expired(as_of=future_time)

    def test_certificate_invalidation(
        self, sample_certificate: CanaryActivationCertificate
    ) -> None:
        """Verify certificate invalidation transitions status to permanent invalidation."""
        assert sample_certificate.status.value == CertificateStatus.ACTIVE.value
        sample_certificate.invalidate("Security test trigger")
        assert (
            sample_certificate.status.value
            == CertificateStatus.INVALIDATED_WITHDRAWAL_PERMISSION_DETECTED.value
        )


# =====================================================================
# 3. Secure Exchange Key Vault & Permission Boundary Tests
# =====================================================================


class TestSecureExchangeKeyVault:
    """Validate key vault security, zero leakage, canonicalization, and permission boundaries."""

    def test_secret_token_redaction(self) -> None:
        """Verify SecretToken masks raw secret strings in repr and str."""
        token = SecretToken("super_secret_production_key_12345")
        assert "super_secret_production_key_12345" not in repr(token)
        assert "super_secret_production_key_12345" not in str(token)
        assert token.reveal() == "super_secret_production_key_12345"
        assert_zero_secrets(
            {"token_repr": repr(token), "token_str": str(token)}, "token_redaction_test"
        )

    def test_vault_repr_does_not_leak_secrets(self, safe_key_vault: SecureExchangeKeyVault) -> None:
        """Verify key vault string representations do not reveal secrets."""
        vault_repr = repr(safe_key_vault)
        assert "unit_test_safe_secret_001" not in vault_repr
        assert_zero_secrets({"vault_repr": vault_repr}, "vault_repr_test")

    def test_query_canonicalization(self) -> None:
        """Verify deterministic RFC 3986 parameter sorting and encoding."""
        params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.0001",
            "timestamp": "1700000000",
        }
        canonical = SecureExchangeKeyVault.canonicalize_query_string(params)
        # Expected keys sorted alphabetically: quantity, side, symbol, timestamp
        expected = "quantity=0.0001&side=BUY&symbol=BTCUSDT&timestamp=1700000000"
        assert canonical == expected

    def test_hmac_sha256_signature_and_verification(
        self, safe_key_vault: SecureExchangeKeyVault
    ) -> None:
        """Verify HMAC-SHA256 signature generation and constant-time verification."""
        params = {"symbol": "ETHUSDT", "side": "BUY", "timestamp": "1700000000"}
        query = safe_key_vault.canonicalize_query_string(params)
        sig = safe_key_vault.generate_signature(query)
        assert len(sig) == 64
        assert safe_key_vault.verify_signature(query, sig) is True

        # Tampered parameter causes signature verification failure
        tampered_params = dict(params)
        tampered_params["side"] = "SELL"
        tampered_query = safe_key_vault.canonicalize_query_string(tampered_params)
        assert safe_key_vault.verify_signature(tampered_query, sig) is False

    def test_timestamp_drift_window_enforcement(self) -> None:
        """Verify request timestamp drift within +/- 1000ms passes, outside fails."""
        now_ms = int(time.time() * 1000)

        # 500ms drift -> pass
        assert SecureExchangeKeyVault.validate_timestamp_window(now_ms - 500, now_ms) is True
        assert SecureExchangeKeyVault.validate_timestamp_window(now_ms + 500, now_ms) is True

        # 1001ms drift -> raises TimestampDriftWindowExceededError
        with pytest.raises(TimestampDriftWindowExceededError, match="Request timestamp drift"):
            SecureExchangeKeyVault.validate_timestamp_window(now_ms - 1001, now_ms)

        with pytest.raises(TimestampDriftWindowExceededError, match="Request timestamp drift"):
            SecureExchangeKeyVault.validate_timestamp_window(now_ms + 1001, now_ms)

    @pytest.mark.parametrize(
        "prohibited_field",
        [
            "enable_withdrawals",
            "permits_universal_transfer",
            "enable_internal_transfer",
            "enable_sub_account_transfer",
        ],
    )
    def test_prohibited_permissions_rejected(self, prohibited_field: str) -> None:
        """Verify that any key with transfer/withdrawal permissions is strictly rejected."""
        perms_kwargs: dict[str, bool] = {
            "enable_reading": True,
            "enable_futures_trading": True,
            "enable_withdrawals": False,
            "permits_universal_transfer": False,
            "enable_internal_transfer": False,
            "enable_sub_account_transfer": False,
        }
        perms_kwargs[prohibited_field] = True
        perms = ExchangeApiKeyPermissions(**perms_kwargs)

        vault = SecureExchangeKeyVault()
        with pytest.raises(WithdrawalPermissionDetectedError, match="Security violation"):
            vault.load_credentials(
                api_key="bad_key",
                api_secret="bad_secret",
                permissions=perms,
            )

    def test_missing_required_permissions_rejected(self) -> None:
        """Verify keys lacking reading or futures trading rights are rejected."""
        vault = SecureExchangeKeyVault()

        # Missing futures trading
        with pytest.raises(MissingRequiredPermissionError, match="Futures Trading"):
            vault.load_credentials(
                api_key="k1",
                api_secret="s1",
                permissions=ExchangeApiKeyPermissions(
                    enable_reading=True, enable_futures_trading=False
                ),
            )

        # Missing reading
        with pytest.raises(MissingRequiredPermissionError, match="Read permissions"):
            vault.load_credentials(
                api_key="k2",
                api_secret="s2",
                permissions=ExchangeApiKeyPermissions(
                    enable_reading=False, enable_futures_trading=True
                ),
            )


# =====================================================================
# 4. Fail-Closed Live Order Dispatch Interlock Gateway Tests
# =====================================================================


class TestOrderDispatchInterlockGateway:
    """Validate that all 8 fail-closed interlock gates block invalid dispatch attempts."""

    @pytest.fixture
    def gateway(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> CanaryOrderDispatchInterlockGateway:
        """Provide a configured interlock gateway."""
        return CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=DAILY_LOSS_BUDGET_USDT,
        )

    def test_gate1_permanent_lockout_check(
        self, gateway: CanaryOrderDispatchInterlockGateway
    ) -> None:
        """Gate 1: Pre-existing lockout blocks all dispatch attempts fail-closed."""
        gateway.locked_out = True
        gateway.lockout_reason = "Manual emergency halt"

        now = time.time()
        with pytest.raises(DailyLossBudgetLockoutError, match="permanently locked out"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_gate1",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

    def test_gate2_certificate_invalidation_and_expiration(
        self, gateway: CanaryOrderDispatchInterlockGateway
    ) -> None:
        """Gate 2: Inactive or expired certificates fail-closed."""
        now = time.time()

        # Invalidate certificate
        gateway.certificate.status = CertificateStatus.REVOKED_OPERATOR
        with pytest.raises(CertificateInvalidatedError, match="REVOKED_OPERATOR"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_gate2",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

        # Expired certificate
        gateway.certificate.status = CertificateStatus.ACTIVE
        gateway.certificate.expires_at_utc = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        with pytest.raises(CertificateExpiredError, match="expiration timestamp"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_gate2",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

    def test_gate3_symbol_whitelist(self, gateway: CanaryOrderDispatchInterlockGateway) -> None:
        """Gate 3: Unauthorized symbol rejected."""
        now = time.time()
        with pytest.raises(UnauthorizedSymbolError, match="DOGEUSDT not in authorized"):
            gateway.check_order_dispatch_interlocks(
                symbol="DOGEUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_gate3",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

    def test_gate4_hard_notional_cap_breach(
        self, gateway: CanaryOrderDispatchInterlockGateway
    ) -> None:
        """Gate 4: Order notional > 5.00 USDT rejected."""
        now = time.time()
        with pytest.raises(OrderNotionalCapBreachError, match="exceeds hard ceiling of 5.00 USDT"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("5.01"),
                track_id="test_gate4",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

    def test_gate5_stale_heartbeat_block(
        self, gateway: CanaryOrderDispatchInterlockGateway
    ) -> None:
        """Gate 5: Stream heartbeat age > 1000ms rejected."""
        now = time.time()
        # 1500ms old heartbeat
        last_heartbeat = now - 1.5
        with pytest.raises(StaleHeartbeatInterlockError, match="exceeds 1000.0ms"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_gate5",
                current_time_epoch=now,
                last_heartbeat_epoch=last_heartbeat,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

    def test_gate6_circuit_breaker_freeze_block(
        self, gateway: CanaryOrderDispatchInterlockGateway
    ) -> None:
        """Gate 6: Circuit breaker state != NORMAL rejected."""
        gateway.circuit_breaker.process_tick(rtt_ms=450.0, drift_ms=10.0, anomaly_reason="Spike")
        assert gateway.circuit_breaker.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE

        now = time.time()
        with pytest.raises(CircuitBreakerInterlockError, match="must be NORMAL"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_gate6",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

    def test_gate7_rate_limit_throttle(self, gateway: CanaryOrderDispatchInterlockGateway) -> None:
        """Gate 7: Multiple orders within 60s window on same symbol rejected."""
        now = time.time()
        gateway.last_order_timestamp_by_symbol["BTCUSDT"] = now - 30.0  # 30s ago (< 60s)

        with pytest.raises(RateLimitThrottleExceededError, match="elapsed 30.00s < 60.0s"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_gate7",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

        # After 61s -> passes
        gateway.last_order_timestamp_by_symbol["BTCUSDT"] = now - 61.0
        gateway.check_order_dispatch_interlocks(
            symbol="BTCUSDT",
            notional_usdt=Decimal("4.00"),
            track_id="test_gate7",
            current_time_epoch=now,
            last_heartbeat_epoch=now,
            cumulative_drawdown_usdt=Decimal("0.0"),
        )

    def test_gate8_daily_loss_budget_lockout(
        self, gateway: CanaryOrderDispatchInterlockGateway
    ) -> None:
        """Gate 8: Cumulative drawdown >= 2.00 USDT engages lockout."""
        now = time.time()
        with pytest.raises(DailyLossBudgetLockoutError, match="Daily loss budget breach"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_gate8",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("2.05"),
            )
        assert gateway.locked_out is True


# =====================================================================
# 5. SQLite Telemetry & Double-Entry Accounting Tests
# =====================================================================


class TestSqliteTelemetryAndAccounting:
    """Validate 9-table SQLite telemetry store, WAL journal, and zero balance drift."""

    def test_sqlite_tables_created(self, tmp_path: Path) -> None:
        """Verify all 9 relational telemetry tables are created with proper schema."""
        db_path = tmp_path / "test_telemetry.sqlite3"
        store = SqliteCanaryActivationTelemetryStore(db_path)

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            "activation_certificates",
            "interlock_events",
            "orders",
            "fills",
            "positions",
            "circuit_breaker_events",
            "portfolio_snapshots",
            "execution_marks",
            "activation_tracks",
        }
        for tbl in expected_tables:
            assert tbl in tables, f"Missing table: {tbl}"

        store.close()

    def test_order_and_fill_recording(self, tmp_path: Path) -> None:
        """Verify recording of orders and fills in SQLite store."""
        db_path = tmp_path / "test_rec.sqlite3"
        store = SqliteCanaryActivationTelemetryStore(db_path)

        order = MicroCanaryOrder(
            order_id="ord-test-01",
            client_order_id="cid-01",
            track_id="unit_track",
            candidate_id="cand-01",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("60000.00"),
            quantity=Decimal("0.00008"),
            notional_usdt=Decimal("4.80"),
        )
        store.record_order(order)

        fill = MicroCanaryFill(
            fill_id="fill-test-01",
            order_id="ord-test-01",
            client_order_id="cid-01",
            track_id="unit_track",
            candidate_id="cand-01",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            liquidity_role=LiquidityRole.MAKER,
            fill_price=Decimal("60000.00"),
            fill_quantity=Decimal("0.00008"),
            notional_usdt=Decimal("4.80"),
            fee_usdt=Decimal("0.00096"),
            fee_rate=Decimal("0.0002"),
            slippage_usdt=Decimal("0.0"),
            slippage_bps=Decimal("0.0"),
            realized_pnl_usdt=Decimal("-0.00096"),
        )
        store.record_fill(fill)

        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM orders WHERE order_id = 'ord-test-01'")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT count(*) FROM fills WHERE fill_id = 'fill-test-01'")
            assert cursor.fetchone()[0] == 1

        store.close()

    def test_jsonl_sink_zero_secrets(self, tmp_path: Path) -> None:
        """Verify JsonlCanaryOrderSink asserts zero secrets on every written line."""
        sink_path = tmp_path / "test-orders.jsonl"
        sink = JsonlCanaryOrderSink(sink_path)

        order = MicroCanaryOrder(
            order_id="ord-jsonl-01",
            client_order_id="cid-jsonl-01",
            track_id="track_1",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("60000.00"),
            quantity=Decimal("0.00008"),
            notional_usdt=Decimal("4.80"),
        )
        sink.record_order(order)

        content = sink_path.read_text(encoding="utf-8")
        assert "ord-jsonl-01" in content
        assert_zero_secrets({"content": content}, "jsonl_sink_test")


# =====================================================================
# 6. Full Simulation Tracks & Runner Execution Tests
# =====================================================================


class TestCanaryActivationRunner:
    """Validate execution of all 4 simulation tracks and report generation."""

    def test_execute_all_tracks(self, tmp_path: Path) -> None:
        """Verify runner completes all 4 tracks, verifies zero drift and produces all artifacts."""
        output_dir = tmp_path / "phase276_test"
        config = CanaryActivationConfig(
            output_dir=output_dir,
            operator_id="test-operator-lead",
            daily_loss_budget_usdt=Decimal("2.00"),
            authorize_canary=True,
        )
        runner = CanaryActivationRunner(config)
        report = runner.execute_all_tracks()

        assert report.compliance["all_criteria_passed"] is True
        assert report.compliance["zero_balance_drift"] is True
        assert report.compliance["zero_secret_leakage"] is True
        assert len(report.tracks) == 4

        # Verify all 6 artifacts exist
        assert (output_dir / "canary-activation-certificate.json").exists()
        assert (output_dir / "canary-orders.jsonl").exists()
        assert (output_dir / "canary-activation-telemetry.sqlite3").exists()
        assert (output_dir / "canary-activation-report.json").exists()
        assert (output_dir / "activation-summary.json").exists()
        assert (output_dir / "paper-summary.json").exists()

        # Verify hash chain on generated artifacts
        assert verify_phase_276_hash_chain(output_dir) is True

    def test_adverse_drift_injection_detection(self, tmp_path: Path) -> None:
        """Verify that simulated adverse drift triggers AccountingDriftError."""
        output_dir = tmp_path / "phase276_drift_test"
        config = CanaryActivationConfig(
            output_dir=output_dir,
            authorize_canary=True,
            simulate_adverse_drift=True,
        )
        runner = CanaryActivationRunner(config)
        with pytest.raises(AccountingDriftError, match="Double-entry drift"):
            runner.execute_all_tracks()


# =====================================================================
# 7. Cryptographic Hash Chain Verification Tests
# =====================================================================


class TestHashChainVerification:
    """Validate SHA-256 DAG hash chain across artifacts and tamper detection."""

    def test_verify_authentic_phase276_artifacts(self) -> None:
        """Verify that generated Phase 276 artifacts pass cryptographic DAG verification."""
        assert verify_phase_276_hash_chain() is True

    def test_tampered_artifact_rejected(self, tmp_path: Path) -> None:
        """Verify that tampering with an artifact invalidates hash chain verification."""
        # Copy genuine artifacts to tmp_path
        p276_dir = DEFAULT_PHASE276_OUTPUT_DIR
        for p in p276_dir.iterdir():
            if p.is_file():
                (tmp_path / p.name).write_bytes(p.read_bytes())

        # Verify authentic copy passes
        assert verify_phase_276_hash_chain(tmp_path) is True

        # Tamper with canary-orders.jsonl
        orders_file = tmp_path / "canary-orders.jsonl"
        orders_file.write_text(orders_file.read_text() + "\n// tampered")

        # Now verification must fail
        assert verify_phase_276_hash_chain(tmp_path) is False


# =====================================================================
# 8. CLI Runner & Argument Parser Tests
# =====================================================================


class TestCliRunner:
    """Validate command-line interface, argument parsing, and output formatting."""

    def test_parser_defaults(self) -> None:
        """Verify CLI argument defaults."""
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.track == "all"
        assert args.operator_id == "operator-lead-001"
        assert args.daily_loss_budget_usdt == 2.0
        assert args.max_duration_hours == 24.0
        assert args.authorize_canary is False
        assert args.verify_only is False

    def test_cli_verify_only_succeeds(self) -> None:
        """Verify --verify-only returns 0 on authentic Phase 276 artifacts."""
        ret = cli_main(["--verify-only"])
        assert ret == 0

    def test_cli_summary_table_formatting(self) -> None:
        """Verify summary table string format contains expected headers."""
        sample_report = CanaryActivationReport(
            timestamp_utc=datetime.now(UTC).isoformat(),
            manifest_version=2,
            staged_manifest_hash="a" * 64,
            certificate_info={
                "certificate_id": "cert-test-01",
                "operator_id": "op-01",
                "expires_at_utc": "2026-09-20T00:00:00Z",
                "daily_loss_budget_usdt": "2.0",
                "max_micro_order_notional_usdt": "5.00",
            },
            tracks=[
                CanaryActivationTrackResult(
                    track_id="track_1",
                    track_name="Nominal",
                    status="SUCCESS",
                    starting_equity_usdt="100.00",
                    final_cash_usdt="100.10",
                    allocated_margin_usdt="0.00",
                    unrealized_pnl_usdt="0.00",
                    realized_pnl_usdt="0.10",
                    total_fees_usdt="0.001",
                    total_slippage_usdt="0.0005",
                    drift_usdt="0.00",
                    zero_balance_drift=True,
                    orders_placed_count=2,
                    orders_filled_count=2,
                    orders_cancelled_count=0,
                    orders_rejected_count=0,
                    interlock_blocks_count=0,
                    final_circuit_state="NORMAL",
                    success=True,
                )
            ],
            order_stats={
                "total_orders_placed": 2,
                "total_orders_filled": 2,
                "total_orders_rejected": 0,
            },
            interlock_stats={
                "total_interlock_blocks": 0,
                "daily_loss_lockouts": 0,
                "key_permission_rejections": 0,
            },
            compliance={
                "zero_balance_drift": True,
                "zero_secret_leakage": True,
                "all_criteria_passed": True,
            },
            tracks_executed=["track_1"],
            artifact_hashes={
                "canary-activation-certificate.json": "0" * 64,
                "canary-orders.jsonl": "0" * 64,
                "canary-activation-telemetry.sqlite3": "0" * 64,
            },
        )
        table = format_summary_table(sample_report)
        assert "PHASE 276: OPERATOR PRODUCTION CANARY AUTHORIZATION" in table
        assert "track_1" in table
        assert "All Criteria Passed : True" in table


# =====================================================================
# 9. Adversarial Reviewer Probes & Edge Case Regression Tests
# =====================================================================


class TestAdversarialReviewerProbe:
    """Adversarial edge-case probes introduced by reviewer audit."""

    def test_gate2_simulated_expiration(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> None:
        """Verify Gate 2 catches expiration under simulated/replay time past 24h."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        now = time.time()
        future_epoch = now + (25 * 3600)  # 25 hours in future (past 24h expiry)

        with pytest.raises(CertificateExpiredError, match="expiration timestamp"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="test_sim_exp",
                current_time_epoch=future_epoch,
                last_heartbeat_epoch=future_epoch,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )
        assert gateway.certificate.status == CertificateStatus.EXPIRED

    def test_match_maker_fill_closing_position(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify match_maker_fill properly closes position, releases margin, and updates cash."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_telemetry.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_orders.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_maker_close")

        # 1. Open long position via maker fill
        buy_order = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        sim.match_maker_fill(buy_order.order_id, fill_price=Decimal("60000.00"))
        assert "BTCUSDT" in sim.active_positions
        assert sim.active_positions["BTCUSDT"].side == PositionSide.LONG
        assert sim.allocated_margin == Decimal("4.8000")

        # 2. Advance time past rate-limit window
        sim.advance_time(65.0, update_heartbeat=True)

        # 3. Close long position via maker sell fill with profit
        sell_order = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60500.00"),
        )
        close_fill = sim.match_maker_fill(sell_order.order_id, fill_price=Decimal("60500.00"))

        assert "BTCUSDT" not in sim.active_positions
        assert len(sim.closed_positions) == 1
        assert sim.allocated_margin == Decimal("0")
        assert sim.current_drift < Decimal("1e-15")
        assert close_fill.realized_pnl_usdt > Decimal("0")

        store.close()

    def test_close_all_positions_emergency_during_lockout(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify close_all_positions_emergency flattens positions even when locked out."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_emg.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_emg.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_emg_close")

        # Open position
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )
        assert len(sim.active_positions) == 1

        # Engage lockout
        gateway.locked_out = True
        gateway.lockout_reason = "Daily loss budget breach lockout"

        # Emergency flatten must succeed and clear active positions
        sim.close_all_positions_emergency()
        assert len(sim.active_positions) == 0
        assert sim.allocated_margin == Decimal("0")
        assert sim.current_drift < Decimal("1e-15")

        store.close()

    def test_non_positive_timestamps_rejected(self) -> None:
        """Verify non-positive timestamps are rejected fail-closed."""
        with pytest.raises(TimestampDriftWindowExceededError, match="must be positive integers"):
            SecureExchangeKeyVault.validate_timestamp_window(-500, -200)

        with pytest.raises(TimestampDriftWindowExceededError, match="must be positive integers"):
            SecureExchangeKeyVault.validate_timestamp_window(0, 1000)

        with pytest.raises(TimestampDriftWindowExceededError, match="must be non-negative"):
            SecureExchangeKeyVault.validate_timestamp_window(1000, 1000, max_drift_ms=-1)

    def test_empty_or_whitespace_credentials_rejected(self) -> None:
        """Verify empty or whitespace API keys and secrets are rejected."""
        vault = SecureExchangeKeyVault()
        perms = ExchangeApiKeyPermissions(enable_reading=True, enable_futures_trading=True)

        with pytest.raises(CanaryActivationError, match="must be a non-empty string"):
            vault.load_credentials("", "secret", perms)

        with pytest.raises(CanaryActivationError, match="must be a non-empty string"):
            vault.load_credentials("key", "   ", perms)

    def test_unpermitted_margin_permissions_rejected(self) -> None:
        """Verify keys with margin or spot trading enabled are rejected fail-closed."""
        vault = SecureExchangeKeyVault()

        with pytest.raises(MissingRequiredPermissionError, match="unpermitted Margin or Spot"):
            vault.load_credentials(
                "key",
                "secret",
                ExchangeApiKeyPermissions(
                    enable_reading=True,
                    enable_futures_trading=True,
                    enable_margin=True,
                ),
            )

        with pytest.raises(MissingRequiredPermissionError, match="unpermitted Margin or Spot"):
            vault.load_credentials(
                "key",
                "secret",
                ExchangeApiKeyPermissions(
                    enable_reading=True,
                    enable_futures_trading=True,
                    enable_spot_and_margin_trading=True,
                ),
            )

    def test_rfc3986_percent_encoding(self) -> None:
        """Verify RFC 3986 percent encoding for spaces and special characters and None omission."""
        params = {
            "symbol": "BTC USDT",
            "clientOrderId": "order#1+2",
            "filter": None,
            "timestamp": "1700000000",
        }
        canonical = SecureExchangeKeyVault.canonicalize_query_string(params)
        assert "filter" not in canonical
        assert "clientOrderId=order%231%2B2" in canonical
        assert "symbol=BTC%20USDT" in canonical

    def test_non_positive_price_quantity_notional_rejected(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> None:
        """Verify non-positive price, quantity, or notional are rejected fail-closed."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        now = time.time()
        with pytest.raises(
            (OrderNotionalCapBreachError, ValidationError), match="must be strictly positive"
        ):
            MicroCanaryOrder(
                track_id="t",
                candidate_id="c",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("-10.0"),
                quantity=Decimal("0.0001"),
                notional_usdt=Decimal("0.0"),
            )

        with pytest.raises(OrderNotionalCapBreachError, match="must be strictly positive"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("0.0"),
                track_id="t",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

    def test_config_invariants_validation(self) -> None:
        """Verify CanaryActivationConfig validates positive parameters and non-empty operator."""
        with pytest.raises(ValidationError, match="operator_id must be a non-empty"):
            CanaryActivationConfig(operator_id="")

        with pytest.raises(ValidationError, match="daily_loss_budget_usdt .* must be positive"):
            CanaryActivationConfig(daily_loss_budget_usdt=Decimal("0"))

        with pytest.raises(ValidationError, match="max_duration_hours .* must be positive"):
            CanaryActivationConfig(max_duration_hours=0.0)

    def test_load_and_verify_key_vault_invalidates_certificate(
        self, sample_certificate: CanaryActivationCertificate
    ) -> None:
        """Verify load_and_verify_key_vault detects prohibited rights and invalidates cert."""
        vault = SecureExchangeKeyVault()
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=vault,
            circuit_breaker=sm,
        )
        assert sample_certificate.status == CertificateStatus.ACTIVE

        bad_perms = ExchangeApiKeyPermissions(
            enable_reading=True,
            enable_futures_trading=True,
            enable_withdrawals=True,
        )

        with pytest.raises(WithdrawalPermissionDetectedError):
            gateway.load_and_verify_key_vault(
                api_key="bad_k",
                api_secret="bad_s",
                permissions=bad_perms,
                track_id="adv_test",
            )

        assert (
            sample_certificate.status
            == CertificateStatus.INVALIDATED_WITHDRAWAL_PERMISSION_DETECTED
        )

    def test_emergency_close_expired_certificate(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify emergency close flattens positions even after certificate has expired."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_exp_emg.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_exp_emg.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_exp_emg")

        # Open a position
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )
        assert len(sim.active_positions) == 1

        # Expire the certificate
        future_epoch = time.time() + (30 * 3600)
        sim.simulated_clock_epoch = future_epoch

        # Emergency close must still succeed
        sim.close_all_positions_emergency()
        assert len(sim.active_positions) == 0
        assert sim.allocated_margin == Decimal("0")
        assert sim.current_drift < Decimal("1e-15")
        store.close()

    def test_close_appreciated_position_above_hard_cap(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify closing a position whose notional grew above 5.00 USDT succeeds."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_apprec.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_apprec.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_apprec")

        # Open long at 4.80 USDT (0.00008 @ 60,000)
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )
        assert len(sim.active_positions) == 1

        # Advance past rate limit and price rallies:
        # notional = 0.00008 * 65,000 = 5.20 USDT > 5.00 USDT
        sim.advance_time(70.0, update_heartbeat=True)
        sim.on_market_tick(
            MarketDepthTick(
                track_id="t_apprec",
                symbol="BTCUSDT",
                bid_price=Decimal("65000.00"),
                bid_quantity=Decimal("1.0"),
                ask_price=Decimal("65002.00"),
                ask_quantity=Decimal("1.0"),
                mark_price=Decimal("65001.00"),
            )
        )

        # Closing order notional is 5.20 USDT > 5.00 USDT cap, but must succeed as risk reduction
        exit_order, fill = sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("65001.00"),
        )
        assert exit_order.status == OrderStatus.FILLED
        assert len(sim.active_positions) == 0
        assert sim.allocated_margin == Decimal("0")
        assert sim.current_drift < Decimal("1e-15")
        store.close()

    def test_partial_maker_and_taker_closing(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify partial closing releases margin proportionally and retains zero drift."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_partial.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_partial.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_partial")

        # Open 0.00008 BTC position with 4.80 USDT margin
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )
        assert sim.active_positions["BTCUSDT"].quantity == Decimal("0.00008")
        assert sim.active_positions["BTCUSDT"].allocated_margin_usdt == Decimal("4.8010")

        # Advance past rate limit and partially close half (0.00004 BTC) via maker fill
        sim.advance_time(70.0, update_heartbeat=True)
        sell_maker = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00004"),
            price=Decimal("60500.00"),
        )
        sim.match_maker_fill(sell_maker.order_id, fill_price=Decimal("60500.00"))

        # Position should remain active with half quantity and half margin
        pos = sim.active_positions["BTCUSDT"]
        assert pos.quantity == Decimal("0.00004")
        assert pos.status == PositionStatus.OPEN
        assert sim.current_drift < Decimal("1e-15")

        # Advance and close remaining half via taker order
        sim.advance_time(70.0, update_heartbeat=True)
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00004"),
            mark_price=Decimal("61000.00"),
        )
        assert len(sim.active_positions) == 0
        assert sim.allocated_margin == Decimal("0")
        assert sim.current_drift < Decimal("1e-15")
        store.close()

    def test_overclose_rejected_fail_closed(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify closing more than active position quantity is rejected fail-closed."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
            hard_notional_cap_usdt=Decimal("10.00"),
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_overclose.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_overclose.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_overclose")

        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00004"),
            mark_price=Decimal("60000.00"),
        )

        sim.advance_time(70.0, update_heartbeat=True)
        with pytest.raises(CanaryActivationError, match="exceeds active position quantity"):
            sim.execute_taker_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00008"),  # greater than 0.00004 open position
                mark_price=Decimal("60000.00"),
            )

        # Active position remains intact and balance uncorrupted
        assert sim.active_positions["BTCUSDT"].quantity == Decimal("0.00004")
        assert sim.current_drift < Decimal("1e-15")
        store.close()

    def test_scale_in_position(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify adding to an active position updates weighted average entry price and margin."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_scale.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_scale.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_scale")

        # Initial buy 0.00002 @ 60,000
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00002"),
            mark_price=Decimal("60000.00"),
        )
        assert sim.active_positions["BTCUSDT"].quantity == Decimal("0.00002")

        # Scale in: second buy 0.00002 @ 62,000
        sim.advance_time(70.0, update_heartbeat=True)
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00002"),
            mark_price=Decimal("62000.00"),
        )

        pos = sim.active_positions["BTCUSDT"]
        assert pos.quantity == Decimal("0.00004")
        assert sim.current_drift < Decimal("1e-15")
        store.close()

    def test_per_asset_and_aggregate_margin_cap_enforcement(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> None:
        """Verify Gate 4b rejects orders breaching per-asset or aggregate margin caps."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
            hard_notional_cap_usdt=Decimal("25.00"),
        )
        now = time.time()

        # 1. Per-asset cap breach (BTCUSDT cap is 20.00 USDT)
        with pytest.raises(MarginCapBreachError, match="would breach BTCUSDT margin cap"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("5.00"),
                track_id="t_cap",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
                current_asset_margin_usdt=Decimal("18.00"),  # 18 + 5 = 23 > 20
                current_aggregate_margin_usdt=Decimal("18.00"),
            )

        # 2. Aggregate cap breach (aggregate cap is 60.00 USDT)
        with pytest.raises(MarginCapBreachError, match="would breach aggregate margin cap"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="t_cap",
                current_time_epoch=now,
                last_heartbeat_epoch=now,
                cumulative_drawdown_usdt=Decimal("0.0"),
                current_asset_margin_usdt=Decimal("10.00"),
                current_aggregate_margin_usdt=Decimal("58.00"),  # 58 + 4 = 62 > 60
            )

    def test_timestamp_window_boolean_and_non_numeric_rejection(self) -> None:
        """Verify boolean and non-numeric types are rejected in timestamp validation."""
        with pytest.raises(TimestampDriftWindowExceededError, match="cannot be boolean"):
            SecureExchangeKeyVault.validate_timestamp_window(True, 1000)

        with pytest.raises(TimestampDriftWindowExceededError, match="cannot be boolean"):
            SecureExchangeKeyVault.validate_timestamp_window(1000, False)

        with pytest.raises(TimestampDriftWindowExceededError, match="must be numeric"):
            SecureExchangeKeyVault.validate_timestamp_window("1000", 1000)  # type: ignore[arg-type]

    def test_hmac_signature_case_insensitivity(
        self, safe_key_vault: SecureExchangeKeyVault
    ) -> None:
        """Verify HMAC signature comparison is case-insensitive and handles None safely."""
        qs = "symbol=BTCUSDT&timestamp=1700000000"
        sig = safe_key_vault.generate_signature(qs)

        # Upper case signature must verify
        assert safe_key_vault.verify_signature(qs, sig.upper()) is True
        # Lower case signature must verify
        assert safe_key_vault.verify_signature(qs, sig.lower()) is True
        # None and empty must return False safely without raising
        assert safe_key_vault.verify_signature(qs, None) is False  # type: ignore[arg-type]
        assert safe_key_vault.verify_signature(qs, "") is False

    def test_unpermitted_permissions_rejected(
        self,
        safe_key_vault: SecureExchangeKeyVault,
    ) -> None:
        """Verify unpermitted spot/margin trading permissions trigger UnpermittedPermissionError."""
        bad_perms = ExchangeApiKeyPermissions(
            enable_reading=True,
            enable_futures_trading=True,
            enable_spot_and_margin_trading=True,
        )
        with pytest.raises(UnpermittedPermissionError, match="unpermitted Margin or Spot"):
            safe_key_vault.verify_permissions(bad_perms)

        bad_perms2 = ExchangeApiKeyPermissions(
            enable_reading=True,
            enable_futures_trading=True,
            enable_margin=True,
        )
        with pytest.raises(UnpermittedPermissionError, match="unpermitted Margin or Spot"):
            safe_key_vault.verify_permissions(bad_perms2)

    def test_cli_verify_hash_chain_without_authorize_canary(self) -> None:
        """Verify CLI --verify-hash-chain works without --authorize-canary."""
        exit_code = cli_main(["--verify-hash-chain"])
        assert exit_code == 0

    def test_fake_is_closing_rejected_without_opposing_position(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify passing is_closing=True without an active opposing position is rejected."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_fake_close.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_fake_close.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_fake_close")

        # 1. No position open at all
        with pytest.raises(CanaryActivationError, match="no active opposing position exists"):
            sim.place_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
                is_closing=True,
            )

        # 2. Position is LONG, but order is BUY (same side, not opposing)
        ord1 = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00004"),
            price=Decimal("60000.00"),
        )
        sim.match_maker_fill(ord1.order_id, fill_price=Decimal("60000.00"))

        with pytest.raises(CanaryActivationError, match="no active opposing position exists"):
            sim.place_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00004"),
                price=Decimal("60000.00"),
                is_closing=True,
            )
        store.close()

    def test_overclosing_order_rejected_at_placement(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify closing order quantity exceeding active position is rejected in place_order."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
            hard_notional_cap_usdt=Decimal("20.00"),
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_overclose_upfront.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_overclose_upfront.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_overclose_upfront")

        # Open 0.00004 BTC position
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00004"),
            mark_price=Decimal("60000.00"),
        )

        sim.advance_time(70.0, update_heartbeat=True)
        # Attempt to place order with quantity 0.00008 > 0.00004
        with pytest.raises(CanaryActivationError, match="exceeds active position quantity"):
            sim.place_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )

        # Must not have left any open orders in simulator
        open_orders = [o for o in sim.orders.values() if o.status == OrderStatus.OPEN]
        assert len(open_orders) == 0
        store.close()

    def test_closing_order_permitted_during_loss_budget_lockout(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify closing orders are permitted through Gate 1 and Gate 8 when in loss lockout."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_lockout_close.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_lockout_close.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_lockout_close")

        # Open position
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )

        # Trigger lockout
        gateway.trigger_daily_loss_lockout(Decimal("2.50"), "t_lockout_close", "BTCUSDT")
        assert gateway.locked_out is True

        # Opening a new order must be blocked
        with pytest.raises(DailyLossBudgetLockoutError):
            sim.place_order(
                candidate_id="cand-eth",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.001"),
                price=Decimal("2500.00"),
            )

        # But closing the existing position MUST be permitted to de-risk
        sim.advance_time(70.0, update_heartbeat=True)
        close_order = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert close_order.status == OrderStatus.OPEN
        sim.match_maker_fill(close_order.order_id, fill_price=Decimal("60000.00"))
        assert len(sim.active_positions) == 0
        assert sim.current_drift < Decimal("1e-15")
        store.close()

    def test_closing_order_permitted_after_certificate_expiry(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify closing orders are permitted through Gate 2 when certificate has expired."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_exp_close.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_exp_close.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_exp_close")

        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )

        # Advance time 30 hours (> 24 hours certificate validity)
        sim.advance_time(30 * 3600.0, update_heartbeat=True)

        # New opening order must be blocked due to expiration
        with pytest.raises(CertificateExpiredError):
            sim.place_order(
                candidate_id="cand-eth",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.001"),
                price=Decimal("2500.00"),
            )

        # Closing order MUST be permitted to exit position
        close_order = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert close_order.status == OrderStatus.OPEN
        sim.match_maker_fill(close_order.order_id, fill_price=Decimal("60000.00"))
        assert len(sim.active_positions) == 0
        assert sim.current_drift < Decimal("1e-15")
        store.close()

    def test_closing_order_permitted_during_rate_limit_throttle(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify closing orders are permitted through Gate 7 within the 60s rate limit window."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_rate_close.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_rate_close.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_rate_close")

        # Open position
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )

        # Immediately advance only 5 seconds (< 60s limit)
        sim.advance_time(5.0, update_heartbeat=True)

        # Closing order MUST NOT be blocked by rate limit
        close_order = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert close_order.status == OrderStatus.OPEN
        sim.match_maker_fill(close_order.order_id, fill_price=Decimal("60000.00"))
        assert len(sim.active_positions) == 0
        store.close()

    def test_closing_order_permitted_during_circuit_breaker_soft_freeze(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify closing orders are permitted through Gate 6 in soft freeze."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_cb_close.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_cb_close.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_cb_close")

        # Open position
        sim.execute_taker_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )

        # Trigger soft freeze
        fresh_sm.process_tick(rtt_ms=450.0, drift_ms=10.0, anomaly_reason="Test latency anomaly")
        assert fresh_sm.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE

        # New opening order must be blocked
        sim.advance_time(70.0, update_heartbeat=True)
        with pytest.raises(CircuitBreakerInterlockError):
            sim.place_order(
                candidate_id="cand-eth",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.001"),
                price=Decimal("2500.00"),
            )

        # Closing order MUST be permitted to exit position
        close_order = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert close_order.status == OrderStatus.OPEN
        sim.match_maker_fill(close_order.order_id, fill_price=Decimal("60000.00"))
        assert len(sim.active_positions) == 0
        store.close()

    def test_timestamp_window_nan_inf_and_boolean_max_drift_rejection(self) -> None:
        """Verify NaN, Inf, and boolean max_drift are rejected in timestamp validation."""
        with pytest.raises(TimestampDriftWindowExceededError, match="cannot be boolean"):
            SecureExchangeKeyVault.validate_timestamp_window(1000, 1000, max_drift_ms=True)  # type: ignore[arg-type]

        with pytest.raises(TimestampDriftWindowExceededError, match="must be finite"):
            SecureExchangeKeyVault.validate_timestamp_window(float("nan"), 1000)

        with pytest.raises(TimestampDriftWindowExceededError, match="must be finite"):
            SecureExchangeKeyVault.validate_timestamp_window(1000, float("nan"))

        with pytest.raises(TimestampDriftWindowExceededError, match="must be finite"):
            SecureExchangeKeyVault.validate_timestamp_window(1000, 1000, max_drift_ms=float("nan"))  # type: ignore[arg-type]

        with pytest.raises(TimestampDriftWindowExceededError, match="must be finite"):
            SecureExchangeKeyVault.validate_timestamp_window(float("inf"), 1000)

    def test_stale_heartbeat_nan_and_inf_rejection(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> None:
        """Verify Gate 5 blocks dispatch when heartbeat timestamps are NaN or Inf."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )

        with pytest.raises(StaleHeartbeatInterlockError, match="invalid or non-finite"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="t_hb",
                current_time_epoch=float("nan"),
                last_heartbeat_epoch=1000.0,
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

        with pytest.raises(StaleHeartbeatInterlockError, match="invalid or non-finite"):
            gateway.check_order_dispatch_interlocks(
                symbol="BTCUSDT",
                notional_usdt=Decimal("4.00"),
                track_id="t_hb",
                current_time_epoch=1000.0,
                last_heartbeat_epoch=float("nan"),
                cumulative_drawdown_usdt=Decimal("0.0"),
            )

    def test_cancel_order_and_cancel_all_open_orders(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify order cancellation updates status and telemetric counters properly."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_cancel.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_cancel.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_cancel")

        ord1 = sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert ord1.status == OrderStatus.OPEN

        # Cancel single order
        cancelled = sim.cancel_order(ord1.order_id, reason="Operator cancellation test")
        assert cancelled.status == OrderStatus.CANCELLED
        assert cancelled.rejection_reason == "Operator cancellation test"
        assert sim.orders_cancelled_count == 1

        # Place two more orders
        sim.advance_time(70.0, update_heartbeat=True)
        sim.place_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("59000.00"),
        )
        sim.place_order(
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.001"),
            price=Decimal("2400.00"),
        )

        # Cancel all remaining open orders
        all_cancelled = sim.cancel_all_open_orders(reason="Global cancel")
        assert len(all_cancelled) == 2
        assert sim.orders_cancelled_count == 3
        assert all(o.status == OrderStatus.CANCELLED for o in all_cancelled)
        store.close()

    def test_rejected_order_with_invalid_price_or_quantity_persists(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify rejected orders with non-positive price/qty are safely recorded to telemetry."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_rej_order.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_rej_order.jsonl")
        sim = CanaryActivationSimulator(gateway, store, sink, "t_rej_order")

        with pytest.raises(OrderNotionalCapBreachError, match="must be strictly positive"):
            sim.place_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("-100.00"),
            )
        assert sim.orders_rejected_count == 1

        with pytest.raises(OrderNotionalCapBreachError, match="must be strictly positive"):
            sim.place_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.0"),
                price=Decimal("60000.00"),
            )
        assert sim.orders_rejected_count == 2
        store.close()

    def test_insufficient_cash_opening_order_rejected(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify attempting to open an order with notional exceeding cash is rejected."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_cash.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_cash.jsonl")
        sim = CanaryActivationSimulator(
            gateway, store, sink, "t_cash", starting_equity=Decimal("2.00")
        )

        # 4.80 USDT order with only 2.00 USDT cash
        with pytest.raises(CanaryActivationError, match="Insufficient free cash"):
            sim.place_order(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
        store.close()

    def test_simulate_adverse_drift_fails_closed(
        self,
        sample_certificate: CanaryActivationCertificate,
        safe_key_vault: SecureExchangeKeyVault,
        fresh_sm: CanaryCircuitBreakerRecoveryStateMachine,
        tmp_path: Path,
    ) -> None:
        """Verify simulate_adverse_drift triggers fail-closed AccountingDriftError."""
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=sample_certificate,
            key_vault=safe_key_vault,
            circuit_breaker=fresh_sm,
        )
        store = SqliteCanaryActivationTelemetryStore(tmp_path / "test_drift.sqlite3")
        sink = JsonlCanaryOrderSink(tmp_path / "test_drift.jsonl")

        with pytest.raises(AccountingDriftError, match="Double-entry drift"):
            CanaryActivationSimulator(gateway, store, sink, "t_drift", simulate_adverse_drift=True)
        store.close()

    def test_dynamic_interlock_stats_on_single_track(
        self,
        tmp_path: Path,
    ) -> None:
        """Verify running a single track produces truthful dynamic interlock_stats."""
        cfg = CanaryActivationConfig(
            output_dir=tmp_path / "track1_run",
            track="track_1",
            authorize_canary=True,
        )
        runner = CanaryActivationRunner(cfg)
        report = runner.execute_all_tracks()
        stats = report.interlock_stats
        assert stats["total_interlock_blocks"] == 0
        assert stats["heartbeat_stale_blocks"] == 0
        assert stats["circuit_breaker_blocks"] == 0
        assert stats["notional_cap_blocks"] == 0
        assert stats["rate_limit_blocks"] == 0
        assert stats["daily_loss_lockouts"] == 0
        assert stats["key_permission_rejections"] == 0
