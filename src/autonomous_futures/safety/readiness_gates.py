"""Readiness gates, fail-closed boundaries, and completion status matrix (R6).

Enforces strict fail-closed safety isolation:
- Default execution, live trading, paper resume, and paid provider network calls
  remain strictly disabled (fail-closed).
- Explicit preflight and manual trigger mechanisms are strictly required to enable
  any execution mode.
- System completion status matrix tracks requirements R1-R6 with verified statuses:
  IMPLEMENTED, OFFLINE-VERIFIED, PROVIDER-VERIFIED, DEPLOYED, RUNTIME-PROVEN, BLOCKED.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import Field, field_validator

from autonomous_futures.domain.contracts import DomainModel


class ExecutionGateStatus(StrEnum):
    """Component execution status conforming to ANTIGRAVITY_HANDOFF specification."""

    IMPLEMENTED = "IMPLEMENTED"
    OFFLINE_VERIFIED = "OFFLINE-VERIFIED"
    PROVIDER_VERIFIED = "PROVIDER-VERIFIED"
    DEPLOYED = "DEPLOYED"
    RUNTIME_PROVEN = "RUNTIME-PROVEN"
    BLOCKED = "BLOCKED"


class ExecutionTarget(StrEnum):
    """Target execution boundaries requiring fail-closed gate evaluation."""

    LIVE_TRADING = "live_trading"
    TESTNET_ORDERS = "testnet_orders"
    PAPER_RESUME = "paper_resume"
    PAID_PROVIDER_CALLS = "paid_provider_calls"
    VPS_RESTART = "vps_restart"
    OFFLINE_SIMULATION = "offline_simulation"
    PAPER_OBSERVATION = "paper_observation"


class SafetyGateResult(DomainModel):
    """Result of evaluating a safety readiness gate."""

    target: ExecutionTarget | str
    status: ExecutionGateStatus
    is_allowed: bool
    fail_closed: bool = True
    reason_codes: tuple[str, ...] = Field(min_length=1)
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() != timedelta(0):
            raise ValueError("evaluated_at must be timezone-aware UTC")
        return v.astimezone(UTC)


def evaluate_safety_gate(
    target: ExecutionTarget | str,
    *,
    explicit_preflight_passed: bool = False,
    operator_signed_approval: bool = False,
    budget_configured: bool = False,
) -> SafetyGateResult:
    """Evaluate whether an execution target is permitted under fail-closed safety policies.

    Rules:
    1. LIVE_TRADING: Strictly BLOCKED in all conditions. Live execution is forbidden.
    2. TESTNET_ORDERS: BLOCKED unless explicit signed operator approval exists.
    3. PAPER_RESUME: BLOCKED unless explicit preflight passed and operator signed approval.
    4. PAID_PROVIDER_CALLS: BLOCKED unless explicit credential preflight and budget configured.
    5. VPS_RESTART: BLOCKED unless signed operator approval exists.
    6. OFFLINE_SIMULATION / PAPER_OBSERVATION: OFFLINE-VERIFIED and permitted.
    """
    now = datetime.now(UTC)

    # 1. LIVE_TRADING is permanently fail-closed and blocked
    if target == ExecutionTarget.LIVE_TRADING:
        return SafetyGateResult(
            target=target,
            status=ExecutionGateStatus.BLOCKED,
            is_allowed=False,
            fail_closed=True,
            reason_codes=("live_trading_permanently_disabled_fail_closed",),
            evaluated_at=now,
        )

    # 2. TESTNET_ORDERS requires explicit operator signed approval
    if target == ExecutionTarget.TESTNET_ORDERS:
        if not operator_signed_approval:
            return SafetyGateResult(
                target=target,
                status=ExecutionGateStatus.BLOCKED,
                is_allowed=False,
                fail_closed=True,
                reason_codes=("testnet_orders_missing_signed_operator_approval",),
                evaluated_at=now,
            )
        return SafetyGateResult(
            target=target,
            status=ExecutionGateStatus.OFFLINE_VERIFIED,
            is_allowed=False,  # Order submission still disabled without active hardware token
            fail_closed=True,
            reason_codes=("testnet_active_order_submission_disabled",),
            evaluated_at=now,
        )

    # 3. PAPER_RESUME requires explicit preflight AND signed approval
    if target == ExecutionTarget.PAPER_RESUME:
        reasons: list[str] = []
        if not explicit_preflight_passed:
            reasons.append("paper_resume_preflight_not_passed")
        if not operator_signed_approval:
            reasons.append("paper_resume_missing_signed_approval")
        if reasons:
            return SafetyGateResult(
                target=target,
                status=ExecutionGateStatus.BLOCKED,
                is_allowed=False,
                fail_closed=True,
                reason_codes=tuple(reasons),
                evaluated_at=now,
            )
        return SafetyGateResult(
            target=target,
            status=ExecutionGateStatus.OFFLINE_VERIFIED,
            is_allowed=True,
            fail_closed=True,
            reason_codes=("paper_resume_authorized_with_clean_preflight",),
            evaluated_at=now,
        )

    # 4. PAID_PROVIDER_CALLS requires explicit preflight AND budget configured
    if target == ExecutionTarget.PAID_PROVIDER_CALLS:
        reasons = []
        if not explicit_preflight_passed:
            reasons.append("provider_credentials_not_preflighted")
        if not budget_configured:
            reasons.append("request_budget_not_configured")
        if reasons:
            return SafetyGateResult(
                target=target,
                status=ExecutionGateStatus.BLOCKED,
                is_allowed=False,
                fail_closed=True,
                reason_codes=tuple(reasons),
                evaluated_at=now,
            )
        return SafetyGateResult(
            target=target,
            status=ExecutionGateStatus.PROVIDER_VERIFIED,
            is_allowed=True,
            fail_closed=True,
            reason_codes=("provider_preflight_and_budget_verified",),
            evaluated_at=now,
        )

    # 5. VPS_RESTART requires operator approval
    if target == ExecutionTarget.VPS_RESTART:
        if not operator_signed_approval:
            return SafetyGateResult(
                target=target,
                status=ExecutionGateStatus.BLOCKED,
                is_allowed=False,
                fail_closed=True,
                reason_codes=("vps_restart_missing_signed_approval",),
                evaluated_at=now,
            )
        return SafetyGateResult(
            target=target,
            status=ExecutionGateStatus.OFFLINE_VERIFIED,
            is_allowed=True,
            fail_closed=True,
            reason_codes=("vps_restart_authorized",),
            evaluated_at=now,
        )

    # 6. OFFLINE_SIMULATION / PAPER_OBSERVATION
    if target in (ExecutionTarget.OFFLINE_SIMULATION, ExecutionTarget.PAPER_OBSERVATION):
        return SafetyGateResult(
            target=target,
            status=ExecutionGateStatus.OFFLINE_VERIFIED,
            is_allowed=True,
            fail_closed=True,
            reason_codes=("offline_deterministic_execution_allowed",),
            evaluated_at=now,
        )

    # Any unknown or unhandled target is strictly BLOCKED (fail-closed)
    return SafetyGateResult(
        target=target,
        status=ExecutionGateStatus.BLOCKED,
        is_allowed=False,
        fail_closed=True,
        reason_codes=("unrecognized_target_fail_closed_blocked",),
        evaluated_at=now,
    )


class CompletionMatrixEntry(DomainModel):
    """Tracking entry for system completion status matrix."""

    requirement: str
    component: str
    producer_entrypoint: str
    consumer_entrypoint: str
    canonical_tests: tuple[str, ...]
    evidence_path: str
    runtime_status: ExecutionGateStatus
    remaining_gate: str


def get_system_completion_matrix() -> tuple[CompletionMatrixEntry, ...]:
    """Return the authoritative completion status matrix across requirements R1 through R6."""
    return (
        CompletionMatrixEntry(
            requirement="R1",
            component="Durable Provider-to-Research Integration",
            producer_entrypoint="scripts/run_autonomy_provider.py",
            consumer_entrypoint="src/autonomous_futures/research/provider_orchestration.py",
            canonical_tests=("tests/unit/test_provider_orchestration.py",),
            evidence_path="data/research/llm-runs",
            runtime_status=ExecutionGateStatus.OFFLINE_VERIFIED,
            remaining_gate=(
                "Paid live provider API calls require explicit GEMINI_API_KEY preflight "
                "and request budget"
            ),
        ),
        CompletionMatrixEntry(
            requirement="R2",
            component="Autonomous Learning & Strategy-Creation Loop",
            producer_entrypoint="scripts/run_autonomous_base.py",
            consumer_entrypoint="src/autonomous_futures/pipeline/autonomous_base.py",
            canonical_tests=(
                "tests/unit/test_autonomous_research_base.py",
                "tests/unit/test_autonomous_research_loop.py",
            ),
            evidence_path="data/autonomous-base",
            runtime_status=ExecutionGateStatus.OFFLINE_VERIFIED,
            remaining_gate="Multi-cycle live paper deployment requires operator admission review",
        ),
        CompletionMatrixEntry(
            requirement="R3",
            component="Deterministic Evaluation & Admission Engine",
            producer_entrypoint="src/autonomous_futures/research/evaluation.py",
            consumer_entrypoint="src/autonomous_futures/paper/candidate_registry.py",
            canonical_tests=("tests/unit/test_deterministic_evaluation_admission.py",),
            evidence_path="data/research/candidates",
            runtime_status=ExecutionGateStatus.OFFLINE_VERIFIED,
            remaining_gate="Fixed qualification gates enforce zero discretionary bypass",
        ),
        CompletionMatrixEntry(
            requirement="R4",
            component="Paper Execution & Feedback Closure",
            producer_entrypoint="src/autonomous_futures/paper/engine.py",
            consumer_entrypoint="src/autonomous_futures/paper/feedback_extractor.py",
            canonical_tests=("tests/unit/test_paper_execution_feedback_closure.py",),
            evidence_path="data/paper/ledger.db",
            runtime_status=ExecutionGateStatus.OFFLINE_VERIFIED,
            remaining_gate="HALTED ledger resume requires signed operator receipt",
        ),
        CompletionMatrixEntry(
            requirement="R5",
            component="Operational Tooling & Observability",
            producer_entrypoint="scripts/run_autonomous_scheduler.py",
            consumer_entrypoint="src/autonomous_futures/notify/telegram.py",
            canonical_tests=("tests/unit/test_operational_tooling.py",),
            evidence_path="data/scheduler-health.json",
            runtime_status=ExecutionGateStatus.OFFLINE_VERIFIED,
            remaining_gate="Telegram credentials require systemd/environment secret provision",
        ),
        CompletionMatrixEntry(
            requirement="R6",
            component="Fail-Closed Boundaries & Safety Gate Isolation",
            producer_entrypoint="src/autonomous_futures/safety/readiness_gates.py",
            consumer_entrypoint="src/autonomous_futures/live_boundary.py",
            canonical_tests=("tests/unit/test_safety_readiness_gates.py",),
            evidence_path="data/safety",
            runtime_status=ExecutionGateStatus.BLOCKED,
            remaining_gate=(
                "Live trading permanently BLOCKED; Testnet order execution disabled without "
                "hardware clearance"
            ),
        ),
    )
