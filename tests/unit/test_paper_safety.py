from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autonomous_futures.domain.contracts import PaperExecutionRequest
from autonomous_futures.paper.safety import (
    PaperActionApproval,
    PaperSafetyEvidence,
    evaluate_paper_action_permission,
    evaluate_paper_safety,
)


def _request() -> PaperExecutionRequest:
    return PaperExecutionRequest.model_validate(
        {
            "candidate_id": "cand-scope-rsi-adx-001",
            "candidate_artifact_hash": "a" * 64,
            "qualified_symbols": ("BTCUSDT",),
            "symbol": "BTCUSDT",
            "side": "LONG",
            "mark_price": Decimal("100"),
            "quantity": Decimal("0.1"),
            "fee_rate": Decimal("0.0004"),
            "slippage_bps": Decimal("2"),
        }
    )


def _evidence(**changes: object) -> PaperSafetyEvidence:
    payload: dict[str, object] = {
        "candidate_id": "cand-scope-rsi-adx-001",
        "candidate_artifact_hash": "a" * 64,
        "qualification_hash": "b" * 64,
        "qualification_decision": "qualified",
        "zero_oos_liquidations": True,
    }
    payload.update(changes)
    return PaperSafetyEvidence.model_validate(payload)


def test_paper_safety_gate_keeps_fully_bound_evidence_blocked_pending_human_authorization() -> None:
    decision = evaluate_paper_safety(_request(), _evidence())

    assert decision.allowed is False
    assert decision.paper_activation is False
    assert decision.execution_authority is False
    assert decision.exchange_access is False
    assert decision.reason_codes == ("paper_activation_not_authorized",)


def test_paper_safety_gate_blocks_unqualified_or_liquidated_evidence() -> None:
    decision = evaluate_paper_safety(
        _request(), _evidence(qualification_decision="rejected", zero_oos_liquidations=False)
    )

    assert decision.allowed is False
    assert decision.reason_codes == (
        "oos_liquidations_present",
        "paper_activation_not_authorized",
        "qualification_not_qualified",
    )


def test_paper_safety_gate_blocks_evidence_for_another_candidate() -> None:
    decision = evaluate_paper_safety(_request(), _evidence(candidate_artifact_hash="c" * 64))

    assert decision.allowed is False
    assert decision.reason_codes == (
        "candidate_evidence_mismatch",
        "paper_activation_not_authorized",
    )


def test_one_shot_approval_permits_only_the_bound_local_open_action() -> None:
    approval = PaperActionApproval(
        approval_id="approval-open-001",
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        trade_id="paper-001",
        action="open",
        approved_at=datetime(2026, 8, 13, tzinfo=UTC),
        expires_at=datetime(2026, 8, 13, tzinfo=UTC) + timedelta(minutes=1),
    )

    decision = evaluate_paper_action_permission(
        _request(),
        _evidence(),
        approval,
        trade_id="paper-001",
        action="open",
        occurred_at=approval.approved_at,
    )

    assert decision.permitted is True
    assert decision.paper_activation is False
    assert decision.execution_authority is False
    assert decision.exchange_access is False


def test_one_shot_approval_blocks_expired_or_mismatched_local_action() -> None:
    approval = PaperActionApproval(
        approval_id="approval-open-001",
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        trade_id="paper-001",
        action="open",
        approved_at=datetime(2026, 8, 13, tzinfo=UTC),
        expires_at=datetime(2026, 8, 13, tzinfo=UTC) + timedelta(minutes=1),
    )

    decision = evaluate_paper_action_permission(
        _request(),
        _evidence(),
        approval,
        trade_id="paper-002",
        action="close",
        occurred_at=approval.expires_at,
    )

    assert decision.permitted is False
    assert decision.reason_codes == (
        "approval_action_mismatch",
        "approval_expired",
        "approval_trade_mismatch",
    )


def test_one_shot_approval_blocks_action_before_approval_time() -> None:
    approval = PaperActionApproval(
        approval_id="approval-open-001",
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        trade_id="paper-001",
        action="open",
        approved_at=datetime(2026, 8, 13, tzinfo=UTC),
        expires_at=datetime(2026, 8, 13, tzinfo=UTC) + timedelta(minutes=1),
    )

    decision = evaluate_paper_action_permission(
        _request(),
        _evidence(),
        approval,
        trade_id="paper-001",
        action="open",
        occurred_at=approval.approved_at - timedelta(microseconds=1),
    )

    assert decision.permitted is False
    assert decision.reason_codes == ("approval_not_yet_valid",)
