"""Unit tests for safety readiness gates, fail-closed boundaries, and completion matrix (R6).

Verifies:
1. Default execution, live trading, paper resume, and paid provider network calls remain
   strictly disabled (fail-closed).
2. Explicit preflight or manual trigger mechanisms are strictly required to enable any execution.
3. System completion status matrix correctly tracks components across all six states:
   IMPLEMENTED, OFFLINE-VERIFIED, PROVIDER-VERIFIED, DEPLOYED, RUNTIME-PROVEN, BLOCKED.
4. Timezone-aware UTC timestamp validation on safety decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonomous_futures.safety.readiness_gates import (
    ExecutionGateStatus,
    ExecutionTarget,
    SafetyGateResult,
    evaluate_safety_gate,
    get_system_completion_matrix,
)


def test_live_trading_permanently_blocked() -> None:
    """Verify live trading is unconditionally BLOCKED and disallowed."""
    # Even if flags are passed as True, live trading must remain blocked
    result = evaluate_safety_gate(
        ExecutionTarget.LIVE_TRADING,
        explicit_preflight_passed=True,
        operator_signed_approval=True,
        budget_configured=True,
    )
    assert result.status == ExecutionGateStatus.BLOCKED
    assert result.is_allowed is False
    assert result.fail_closed is True
    assert "live_trading_permanently_disabled_fail_closed" in result.reason_codes


def test_testnet_orders_fail_closed_by_default() -> None:
    """Verify testnet orders are BLOCKED by default without operator approval."""
    default_result = evaluate_safety_gate(ExecutionTarget.TESTNET_ORDERS)
    assert default_result.status == ExecutionGateStatus.BLOCKED
    assert default_result.is_allowed is False
    assert "testnet_orders_missing_signed_operator_approval" in default_result.reason_codes

    # With operator approval, order submission remains disabled in this environment
    approved_result = evaluate_safety_gate(
        ExecutionTarget.TESTNET_ORDERS, operator_signed_approval=True
    )
    assert approved_result.is_allowed is False
    assert "testnet_active_order_submission_disabled" in approved_result.reason_codes


def test_paper_resume_requires_both_preflight_and_approval() -> None:
    """Verify paper resume is BLOCKED unless BOTH clean preflight AND signed approval exist."""
    # Default: blocked
    res_default = evaluate_safety_gate(ExecutionTarget.PAPER_RESUME)
    assert res_default.status == ExecutionGateStatus.BLOCKED
    assert res_default.is_allowed is False
    assert "paper_resume_preflight_not_passed" in res_default.reason_codes
    assert "paper_resume_missing_signed_approval" in res_default.reason_codes

    # Preflight only: still blocked
    res_preflight_only = evaluate_safety_gate(
        ExecutionTarget.PAPER_RESUME, explicit_preflight_passed=True
    )
    assert res_preflight_only.status == ExecutionGateStatus.BLOCKED
    assert res_preflight_only.is_allowed is False
    assert "paper_resume_missing_signed_approval" in res_preflight_only.reason_codes

    # Approval only: still blocked
    res_approval_only = evaluate_safety_gate(
        ExecutionTarget.PAPER_RESUME, operator_signed_approval=True
    )
    assert res_approval_only.status == ExecutionGateStatus.BLOCKED
    assert res_approval_only.is_allowed is False
    assert "paper_resume_preflight_not_passed" in res_approval_only.reason_codes

    # Both present: permitted
    res_authorized = evaluate_safety_gate(
        ExecutionTarget.PAPER_RESUME,
        explicit_preflight_passed=True,
        operator_signed_approval=True,
    )
    assert res_authorized.status == ExecutionGateStatus.OFFLINE_VERIFIED
    assert res_authorized.is_allowed is True


def test_paid_provider_calls_require_preflight_and_budget() -> None:
    """Verify paid provider calls are BLOCKED unless preflight passed and budget configured."""
    # Default: blocked
    res_default = evaluate_safety_gate(ExecutionTarget.PAID_PROVIDER_CALLS)
    assert res_default.status == ExecutionGateStatus.BLOCKED
    assert res_default.is_allowed is False
    assert "provider_credentials_not_preflighted" in res_default.reason_codes
    assert "request_budget_not_configured" in res_default.reason_codes

    # Preflight only without budget: blocked
    res_no_budget = evaluate_safety_gate(
        ExecutionTarget.PAID_PROVIDER_CALLS, explicit_preflight_passed=True
    )
    assert res_no_budget.status == ExecutionGateStatus.BLOCKED
    assert res_no_budget.is_allowed is False
    assert "request_budget_not_configured" in res_no_budget.reason_codes

    # Preflight and budget: permitted
    res_allowed = evaluate_safety_gate(
        ExecutionTarget.PAID_PROVIDER_CALLS,
        explicit_preflight_passed=True,
        budget_configured=True,
    )
    assert res_allowed.status == ExecutionGateStatus.PROVIDER_VERIFIED
    assert res_allowed.is_allowed is True


def test_vps_restart_requires_signed_operator_approval() -> None:
    """Verify VPS restart is BLOCKED by default and only authorized with operator approval."""
    res_default = evaluate_safety_gate(ExecutionTarget.VPS_RESTART)
    assert res_default.status == ExecutionGateStatus.BLOCKED
    assert res_default.is_allowed is False

    res_approved = evaluate_safety_gate(ExecutionTarget.VPS_RESTART, operator_signed_approval=True)
    assert res_approved.status == ExecutionGateStatus.OFFLINE_VERIFIED
    assert res_approved.is_allowed is True


def test_offline_simulation_permitted() -> None:
    """Verify offline deterministic simulation is permitted without external network calls."""
    res = evaluate_safety_gate(ExecutionTarget.OFFLINE_SIMULATION)
    assert res.status == ExecutionGateStatus.OFFLINE_VERIFIED
    assert res.is_allowed is True


def test_safety_gate_result_enforces_utc() -> None:
    """Verify SafetyGateResult rejects naive and non-UTC datetimes."""
    now_utc = datetime.now(UTC)

    # Valid UTC
    gate = SafetyGateResult(
        target=ExecutionTarget.LIVE_TRADING,
        status=ExecutionGateStatus.BLOCKED,
        is_allowed=False,
        reason_codes=("blocked",),
        evaluated_at=now_utc,
    )
    assert gate.evaluated_at.tzinfo == UTC

    # Naive datetime must fail
    naive_now = datetime.now()
    with pytest.raises(ValidationError):
        SafetyGateResult(
            target=ExecutionTarget.LIVE_TRADING,
            status=ExecutionGateStatus.BLOCKED,
            is_allowed=False,
            reason_codes=("blocked",),
            evaluated_at=naive_now,
        )

    # Non-UTC timezone must fail
    myt = timezone(timedelta(hours=8))
    non_utc_now = datetime.now(myt)
    with pytest.raises(ValidationError):
        SafetyGateResult(
            target=ExecutionTarget.LIVE_TRADING,
            status=ExecutionGateStatus.BLOCKED,
            is_allowed=False,
            reason_codes=("blocked",),
            evaluated_at=non_utc_now,
        )


def test_system_completion_matrix_integrity() -> None:
    """Verify completion matrix covers R1-R6 with complete producer/consumer/test bindings."""
    matrix = get_system_completion_matrix()
    assert len(matrix) == 6

    reqs = [entry.requirement for entry in matrix]
    assert reqs == ["R1", "R2", "R3", "R4", "R5", "R6"]

    # All canonical test files must actually exist in repo
    repo_root = Path(__file__).resolve().parents[2]
    for entry in matrix:
        assert entry.component
        assert entry.producer_entrypoint
        assert entry.consumer_entrypoint
        assert entry.canonical_tests
        assert entry.evidence_path
        assert entry.runtime_status in (
            ExecutionGateStatus.OFFLINE_VERIFIED,
            ExecutionGateStatus.BLOCKED,
        )
        assert entry.remaining_gate

        for test_file in entry.canonical_tests:
            full_path = repo_root / test_file
            assert full_path.is_file(), f"Canonical test file {test_file} does not exist!"


def test_unrecognized_target_fails_closed() -> None:
    """Verify any unrecognized or unhandled execution target is strictly BLOCKED (fail-closed)."""
    # Test completely invalid target value
    res = evaluate_safety_gate("unrecognized_future_target")
    assert res.status == ExecutionGateStatus.BLOCKED
    assert res.is_allowed is False
    assert res.fail_closed is True
    assert "unrecognized_target_fail_closed_blocked" in res.reason_codes
