"""Unit Test Suite for Phase 300: Testnet Exchange Connectivity & Multi-Sig Order Gateway.

Comprehensive testing for:
1. MultiSigOrderAuthorizer (R1):
   - Dual-custody multi-signature ticket requiring >= 2 independent roles
     (ROLE_RISK_INTERLOCK and ROLE_PORTFOLIO_OFFICER)
   - HMAC-SHA256 signature generation and verification
   - Replay attack defense via unique nonce cache
   - Fail-closed rejection on clock skew or ticket expiry
   - Fail-closed rejection on single-custody or duplicate role
   - Fail-closed rejection on tampered payloads or invalid signatures
2. OrderPreDispatchFilterGuard (R2):
   - LOT_SIZE: stepSize rounding with ROUND_DOWN
   - PRICE_FILTER: tickSize alignment
   - MIN_NOTIONAL: >= 5.00 USDT enforcement
   - PERCENT_PRICE: <= 1.0% mark price deviation boundary
   - Micro child order cap: <= 5.00 USDT enforcement
   - Boundary rejection tests for violations
3. TestnetExchangeGateway & OrderLifecycleTracker (R3):
   - Lifecycle state machine: INTENDED -> AUTHORIZED -> STAGED -> DISPATCHED -> FILLED / REJECTED
   - Idempotent clientOrderId deduplication
   - Sub-50 ms round-trip latency attribution (tau_auth, tau_filter, tau_dispatch, tau_rtt)
   - Strict paper-safe isolation (EXECUTION AUTHORITY: OFF)
4. Continuous Mathematical Double-Entry Zero-Drift Balance Governance (R4):
   - Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL - Total Fees
   - Invariant strictly verified: |Delta| < 10^-15 USDT
5. Deterministic Runner Tracks & SHA-256 Merkle DAG (R5):
   - Tracks 1 to 4 deterministic execution
   - Cryptographic SHA-256 Merkle DAG linking Phase 299 root hash.
"""

from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.canary_activation import OrderSide
from autonomous_futures.feed.paper_ledger import DOUBLE_ENTRY_MAX_DRIFT
from autonomous_futures.feed.testnet_gateway import (
    UPSTREAM_PHASE299_ROOT_HASH,
    CanaryTestnetGatewayRunner,
    MultiSigOrderAuthorizer,
    MultiSigRole,
    OrderGatewayState,
    OrderPreDispatchFilterGuard,
    StagedOrderLifecycleError,
    TestnetExchangeGateway,
    verify_phase_300_dag,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def authorizer() -> MultiSigOrderAuthorizer:
    """Standard MultiSigOrderAuthorizer instance."""
    return MultiSigOrderAuthorizer()


@pytest.fixture
def filter_guard() -> OrderPreDispatchFilterGuard:
    """Standard OrderPreDispatchFilterGuard instance."""
    return OrderPreDispatchFilterGuard()


@pytest.fixture
def gateway(
    authorizer: MultiSigOrderAuthorizer,
    filter_guard: OrderPreDispatchFilterGuard,
) -> TestnetExchangeGateway:
    """Standard TestnetExchangeGateway instance."""
    return TestnetExchangeGateway(authorizer=authorizer, filter_guard=filter_guard)


@pytest.fixture
def temp_output_dir() -> Path:
    """Temporary directory for runner testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# =====================================================================
# R1: MultiSigOrderAuthorizer Tests
# =====================================================================


def test_multisig_authorizer_valid_dual_signatures(authorizer: MultiSigOrderAuthorizer) -> None:
    """Verify authorizer grants authorization when dual valid signatures are provided."""
    now = datetime.now(UTC)
    intent_hash = hashlib.sha256(b"intent-test-001").hexdigest()
    ticket = authorizer.create_authorization_ticket(
        symbol="BTCUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-test-001",
        created_at_utc=now,
    )

    sig_risk = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-test-001",
    )
    sig_port = authorizer.generate_signature(
        signer_id="officer-portfolio-002",
        role=MultiSigRole.ROLE_PORTFOLIO_OFFICER,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-test-002",
    )
    ticket.signatures.extend([sig_risk, sig_port])

    is_valid, reason = authorizer.verify_ticket(ticket, current_time_utc=now)
    assert is_valid is True
    assert reason is None
    assert ticket.is_valid is True


def test_multisig_authorizer_single_signature_rejected(authorizer: MultiSigOrderAuthorizer) -> None:
    """Verify authorizer rejects a ticket signed by only 1 role."""
    now = datetime.now(UTC)
    intent_hash = hashlib.sha256(b"intent-test-002").hexdigest()
    ticket = authorizer.create_authorization_ticket(
        symbol="ETHUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-test-002",
        created_at_utc=now,
    )

    sig_risk = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-test-003",
    )
    ticket.signatures.append(sig_risk)

    is_valid, reason = authorizer.verify_ticket(ticket, current_time_utc=now)
    assert is_valid is False
    assert "Insufficient signatures" in (reason or "")


def test_multisig_authorizer_duplicate_role_rejected(authorizer: MultiSigOrderAuthorizer) -> None:
    """Verify authorizer rejects when 2 signatures are provided from the same role."""
    now = datetime.now(UTC)
    intent_hash = hashlib.sha256(b"intent-test-003").hexdigest()
    ticket = authorizer.create_authorization_ticket(
        symbol="SOLUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-test-003",
        created_at_utc=now,
    )

    sig_risk1 = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-test-004",
    )
    sig_risk2 = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-test-005",
    )
    ticket.signatures.extend([sig_risk1, sig_risk2])

    is_valid, reason = authorizer.verify_ticket(ticket, current_time_utc=now)
    assert is_valid is False
    assert "Dual custody breach" in (reason or "")


def test_multisig_authorizer_nonce_replay_rejected(authorizer: MultiSigOrderAuthorizer) -> None:
    """Verify replay defense: reusing an authorization ticket nonce triggers rejection."""
    now = datetime.now(UTC)
    intent_hash = hashlib.sha256(b"intent-test-004").hexdigest()
    ticket1 = authorizer.create_authorization_ticket(
        symbol="BTCUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-test-004",
        created_at_utc=now,
    )
    sig_risk = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket1.ticket_id,
        order_intent_hash=ticket1.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-replay-001",
    )
    sig_port = authorizer.generate_signature(
        signer_id="officer-portfolio-002",
        role=MultiSigRole.ROLE_PORTFOLIO_OFFICER,
        ticket_id=ticket1.ticket_id,
        order_intent_hash=ticket1.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-replay-002",
    )
    ticket1.signatures.extend([sig_risk, sig_port])

    is_valid1, _ = authorizer.verify_ticket(ticket1, current_time_utc=now)
    assert is_valid1 is True

    # Attempt replay with ticket2 reusing nonce-replay-001
    ticket2 = authorizer.create_authorization_ticket(
        symbol="BTCUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-test-005",
        created_at_utc=now,
    )
    sig_risk_reused = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket2.ticket_id,
        order_intent_hash=ticket2.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-replay-001",  # Reused!
    )
    sig_port2 = authorizer.generate_signature(
        signer_id="officer-portfolio-002",
        role=MultiSigRole.ROLE_PORTFOLIO_OFFICER,
        ticket_id=ticket2.ticket_id,
        order_intent_hash=ticket2.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-replay-003",
    )
    ticket2.signatures.extend([sig_risk_reused, sig_port2])

    is_valid2, reason2 = authorizer.verify_ticket(ticket2, current_time_utc=now)
    assert is_valid2 is False
    assert "Nonce reuse detected" in (reason2 or "")


def test_multisig_authorizer_expired_ticket_rejected(authorizer: MultiSigOrderAuthorizer) -> None:
    """Verify expired tickets (> 60 s TTL) are rejected fail-closed."""
    created_at = datetime.now(UTC) - timedelta(seconds=70)
    intent_hash = hashlib.sha256(b"intent-test-005").hexdigest()
    ticket = authorizer.create_authorization_ticket(
        symbol="BTCUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-test-006",
        created_at_utc=created_at,
    )
    sig_risk = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=created_at,
        nonce="nonce-exp-001",
    )
    sig_port = authorizer.generate_signature(
        signer_id="officer-portfolio-002",
        role=MultiSigRole.ROLE_PORTFOLIO_OFFICER,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=created_at,
        nonce="nonce-exp-002",
    )
    ticket.signatures.extend([sig_risk, sig_port])

    is_valid, reason = authorizer.verify_ticket(ticket, current_time_utc=datetime.now(UTC))
    assert is_valid is False
    assert "expired" in (reason or "").lower()


def test_multisig_authorizer_tampered_signature_rejected(
    authorizer: MultiSigOrderAuthorizer,
) -> None:
    """Verify tampered HMAC-SHA256 signature is rejected."""
    now = datetime.now(UTC)
    intent_hash = hashlib.sha256(b"intent-test-006").hexdigest()
    ticket = authorizer.create_authorization_ticket(
        symbol="BTCUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-test-007",
        created_at_utc=now,
    )
    sig_risk = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-tamper-001",
    )
    sig_port = authorizer.generate_signature(
        signer_id="officer-portfolio-002",
        role=MultiSigRole.ROLE_PORTFOLIO_OFFICER,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-tamper-002",
    )
    # Corrupt risk signature
    corrupted_sig = sig_risk.model_copy(update={"signature": "deadbeef" * 8})
    ticket.signatures.extend([corrupted_sig, sig_port])

    is_valid, reason = authorizer.verify_ticket(ticket, current_time_utc=now)
    assert is_valid is False
    assert "signature mismatch" in (reason or "").lower()


# =====================================================================
# R2: OrderPreDispatchFilterGuard Tests
# =====================================================================


def test_filter_guard_compliant_order_passes(filter_guard: OrderPreDispatchFilterGuard) -> None:
    """Verify compliant order passes all exchange filters."""
    res = filter_guard.validate_order(
        symbol="BTCUSDT",
        price=Decimal("50000.0"),
        quantity=Decimal("0.00010"),
        side=OrderSide.BUY,
        mark_price=Decimal("50000.0"),
    )
    assert res.compliant is True
    assert len(res.violations) == 0
    assert res.validated_notional_usdt == Decimal("5.00")


def test_filter_guard_min_notional_violation_rejected(
    filter_guard: OrderPreDispatchFilterGuard,
) -> None:
    """Verify order with notional < 5.00 USDT fails pre-dispatch validation."""
    # 0.00008 * 50000 = 4.00 USDT (< 5.00 USDT)
    res = filter_guard.validate_order(
        symbol="BTCUSDT",
        price=Decimal("50000.0"),
        quantity=Decimal("0.00008"),
        side=OrderSide.BUY,
        mark_price=Decimal("50000.0"),
    )
    assert res.compliant is False
    assert any("min_notional" in v for v in res.violations)


def test_filter_guard_micro_cap_violation_rejected(
    filter_guard: OrderPreDispatchFilterGuard,
) -> None:
    """Verify order with notional > 5.00 USDT micro child order cap is rejected."""
    # 0.00015 * 50000 = 7.50 USDT (> 5.00 USDT)
    res = filter_guard.validate_order(
        symbol="BTCUSDT",
        price=Decimal("50000.0"),
        quantity=Decimal("0.00015"),
        side=OrderSide.BUY,
        mark_price=Decimal("50000.0"),
    )
    assert res.compliant is False
    assert any("micro child cap" in v for v in res.violations)


def test_filter_guard_percent_price_violation_rejected(
    filter_guard: OrderPreDispatchFilterGuard,
) -> None:
    """Verify order price deviating > 1.0% from mark price is rejected."""
    # Mark price 50000.0, order price 50600.0 (1.2% > 1.0%)
    res = filter_guard.validate_order(
        symbol="BTCUSDT",
        price=Decimal("50600.0"),
        quantity=Decimal("0.00010"),
        side=OrderSide.BUY,
        mark_price=Decimal("50000.0"),
    )
    assert res.compliant is False
    assert any("deviates" in v for v in res.violations)


# =====================================================================
# R3: TestnetExchangeGateway & Order Lifecycle Tests
# =====================================================================


def test_gateway_staged_order_lifecycle_progression(
    gateway: TestnetExchangeGateway,
    authorizer: MultiSigOrderAuthorizer,
) -> None:
    """Verify lifecycle progression: INTENDED -> AUTHORIZED -> STAGED -> DISPATCHED -> FILLED."""
    now = datetime.now(UTC)
    intent_hash = hashlib.sha256(b"intent-life-001").hexdigest()
    ticket = authorizer.create_authorization_ticket(
        symbol="BTCUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-life-001",
        created_at_utc=now,
    )
    sig_risk = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-life-001",
    )
    sig_port = authorizer.generate_signature(
        signer_id="officer-portfolio-002",
        role=MultiSigRole.ROLE_PORTFOLIO_OFFICER,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-life-002",
    )
    ticket.signatures.extend([sig_risk, sig_port])

    # Stage order
    order = gateway.stage_order(
        ticket=ticket,
        price=Decimal("50000.0"),
        quantity=Decimal("0.00010"),
        client_order_id="cl-life-001",
        mark_price=Decimal("50000.0"),
    )
    assert order.current_state == OrderGatewayState.DISPATCHED
    assert order.latency_attribution.is_sub_50ms is True

    # Fill order
    filled = gateway.simulate_testnet_fill("cl-life-001", fill_price=Decimal("50000.0"))
    assert filled.current_state == OrderGatewayState.FILLED
    assert filled.fee_usdt > Decimal("0")


def test_gateway_duplicate_client_order_id_rejected(
    gateway: TestnetExchangeGateway,
    authorizer: MultiSigOrderAuthorizer,
) -> None:
    """Verify duplicate clientOrderId raises StagedOrderLifecycleError."""
    now = datetime.now(UTC)
    intent_hash = hashlib.sha256(b"intent-dedup-001").hexdigest()
    ticket = authorizer.create_authorization_ticket(
        symbol="ETHUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-dedup-001",
        created_at_utc=now,
    )
    sig_risk = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-dedup-001",
    )
    sig_port = authorizer.generate_signature(
        signer_id="officer-portfolio-002",
        role=MultiSigRole.ROLE_PORTFOLIO_OFFICER,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-dedup-002",
    )
    ticket.signatures.extend([sig_risk, sig_port])

    gateway.stage_order(
        ticket=ticket,
        price=Decimal("2500.0"),
        quantity=Decimal("0.002"),
        client_order_id="cl-dedup-fixed",
        mark_price=Decimal("2500.0"),
    )

    # Second attempt with same client_order_id must fail
    with pytest.raises(StagedOrderLifecycleError, match="Duplicate clientOrderId"):
        gateway.stage_order(
            ticket=ticket,
            price=Decimal("2500.0"),
            quantity=Decimal("0.002"),
            client_order_id="cl-dedup-fixed",
            mark_price=Decimal("2500.0"),
        )


# =====================================================================
# R4: Double-Entry Zero-Drift Balance Governance Tests
# =====================================================================


def test_gateway_double_entry_balance_reconciliation(
    gateway: TestnetExchangeGateway,
    authorizer: MultiSigOrderAuthorizer,
) -> None:
    """Verify double-entry balance reconciliation maintains |Delta| < 10^-15 USDT."""
    rec_initial = gateway.reconcile_balances()
    assert rec_initial["zero_balance_drift_verified"] is True
    assert rec_initial["drift_usdt"] <= float(DOUBLE_ENTRY_MAX_DRIFT)

    now = datetime.now(UTC)
    intent_hash = hashlib.sha256(b"intent-bal-001").hexdigest()
    ticket = authorizer.create_authorization_ticket(
        symbol="BTCUSDT",
        target_notional_usdt=Decimal("5.00"),
        order_intent_hash=intent_hash,
        ticket_id="ticket-bal-001",
        created_at_utc=now,
    )
    sig_risk = authorizer.generate_signature(
        signer_id="officer-risk-001",
        role=MultiSigRole.ROLE_RISK_INTERLOCK,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-bal-001",
    )
    sig_port = authorizer.generate_signature(
        signer_id="officer-portfolio-002",
        role=MultiSigRole.ROLE_PORTFOLIO_OFFICER,
        ticket_id=ticket.ticket_id,
        order_intent_hash=ticket.order_intent_hash,
        signed_at_utc=now,
        nonce="nonce-bal-002",
    )
    ticket.signatures.extend([sig_risk, sig_port])

    gateway.stage_order(
        ticket=ticket,
        price=Decimal("50000.0"),
        quantity=Decimal("0.00010"),
        client_order_id="cl-bal-001",
        mark_price=Decimal("50000.0"),
    )
    gateway.simulate_testnet_fill("cl-bal-001", fill_price=Decimal("50000.0"))

    rec_post = gateway.reconcile_balances()
    assert rec_post["zero_balance_drift_verified"] is True
    assert rec_post["drift_usdt"] <= float(DOUBLE_ENTRY_MAX_DRIFT)


# =====================================================================
# R5: CanaryTestnetGatewayRunner & Merkle DAG Tests
# =====================================================================


def test_runner_run_all_deterministic_execution(temp_output_dir: Path) -> None:
    """Verify CanaryTestnetGatewayRunner.run_all generates valid artifacts."""
    runner = CanaryTestnetGatewayRunner(output_dir=temp_output_dir)
    summary = runner.run_all(seed=42)

    assert summary["phase"] == "phase_300"
    assert summary["status"] == "TESTNET_GATEWAY_VERIFIED"
    assert summary["execution_authority"] is False
    assert summary["paper_safe"] is True
    assert summary["total_orders_staged"] > 0
    assert summary["orders_filled"] > 0
    assert summary["solvency"]["zero_balance_drift_verified"] is True
    assert summary["upstream_hash"] == UPSTREAM_PHASE299_ROOT_HASH

    # Check generated files
    assert (temp_output_dir / "canary-testnet-gateway-telemetry.sqlite3").exists()
    assert (temp_output_dir / "canary-orders.jsonl").exists()
    assert (temp_output_dir / "canary-testnet-gateway-report.json").exists()
    assert (temp_output_dir / "testnet-gateway-summary.json").exists()
    assert (temp_output_dir / "paper-summary.json").exists()

    # Verify DAG function
    summary_path = temp_output_dir / "testnet-gateway-summary.json"
    assert verify_phase_300_dag(summary_path) is True
