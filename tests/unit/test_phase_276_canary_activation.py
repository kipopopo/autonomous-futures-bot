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
    CanaryActivationReport,
    CanaryActivationRunner,
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
    MicroCanaryFill,
    MicroCanaryOrder,
    MissingRequiredPermissionError,
    OrderNotionalCapBreachError,
    OrderSide,
    OrderType,
    RateLimitThrottleExceededError,
    SecretToken,
    SecureExchangeKeyVault,
    SqliteCanaryActivationTelemetryStore,
    StaleHeartbeatInterlockError,
    TimestampDriftWindowExceededError,
    UnauthorizedSymbolError,
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
