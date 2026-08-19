from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _designation():
    from autonomous_futures.testnet_activation import create_testnet_activation_designation
    from autonomous_futures.testnet_audit import create_testnet_lifecycle_evidence
    from autonomous_futures.testnet_freeze import create_testnet_evidence_review
    from autonomous_futures.testnet_lifecycle import (
        TestnetLifecycleAudit,
        parse_testnet_order_record,
    )
    from autonomous_futures.testnet_observation import (
        TestnetAccountObservationInput,
        capture_testnet_observation,
    )

    open_order = parse_testnet_order_record(
        {
            "orderId": 1,
            "clientOrderId": "afbot-open-1",
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "side": "BUY",
            "type": "MARKET",
            "origQty": "0.0008",
            "executedQty": "0.0008",
            "reduceOnly": False,
            "updateTime": 1,
        }
    )
    close_order = parse_testnet_order_record(
        {
            "orderId": 2,
            "clientOrderId": "afbot-close-2",
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "side": "SELL",
            "type": "MARKET",
            "origQty": "0.0008",
            "executedQty": "0.0008",
            "reduceOnly": True,
            "updateTime": 2,
        }
    )
    audit = create_testnet_lifecycle_evidence(
        open_order,
        close_order,
        pre_open_nonzero_positions=0,
        post_close_nonzero_positions=0,
        audit=TestnetLifecycleAudit(
            status="reconciled",
            open_order_id=1,
            close_order_id=2,
            reason_codes=("testnet_lifecycle_reconciled",),
        ),
        audit_id="audit-testnet-001",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
    )
    observation = capture_testnet_observation(
        audit,
        TestnetAccountObservationInput(asset_count=8, nonzero_position_count=0),
        observation_id="observation-testnet-001",
        observed_at=datetime(2026, 8, 8, 2, tzinfo=UTC),
    )
    review = create_testnet_evidence_review(
        audit,
        observation,
        review_id="review-testnet-001",
        reviewer_id="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 8, 3, tzinfo=UTC),
        decision="accept_testnet_observation",
        review_notes="Reviewed stable flat evidence.",
    )
    return create_testnet_activation_designation(
        review,
        designation_id="designation-testnet-001",
        designated_by="human-reviewer-1",
        designated_at=datetime(2026, 8, 8, 4, tzinfo=UTC),
        expires_at=datetime(2026, 8, 8, 5, tzinfo=UTC),
        symbol="BTCUSDT",
        max_quote_notional=Decimal("100"),
    )


def test_activation_approval_unlocks_exactly_one_bounded_lifecycle() -> None:
    from autonomous_futures.testnet_activation_approval import (
        create_testnet_activation_approval,
    )

    approval = create_testnet_activation_approval(
        _designation(),
        approval_id="approval-testnet-001",
        approved_by="human-reviewer-1",
        approved_at=datetime(2026, 8, 8, 4, 30, tzinfo=UTC),
        expires_at=datetime(2026, 8, 8, 4, 45, tzinfo=UTC),
    )

    assert approval.scope == "one_open_and_reduce_only_close"
    assert approval.symbol == "BTCUSDT"
    assert approval.max_quote_notional == Decimal("100")
    assert approval.new_actions_allowed is True
    assert approval.live_enabled is False
    assert len(approval.approval_hash) == 64


def test_activation_approval_rejects_after_designation_expiry() -> None:
    from autonomous_futures.testnet_activation_approval import (
        create_testnet_activation_approval,
    )

    with pytest.raises(ValueError, match="designation expiry"):
        create_testnet_activation_approval(
            _designation(),
            approval_id="approval-testnet-001",
            approved_by="human-reviewer-1",
            approved_at=datetime(2026, 8, 8, 4, 30, tzinfo=UTC),
            expires_at=datetime(2026, 8, 8, 5, 1, tzinfo=UTC),
        )


def test_sqlite_activation_approval_is_write_once_and_absent_read_pure(tmp_path) -> None:
    from autonomous_futures.testnet_activation_approval import (
        SqliteTestnetActivationApprovals,
        create_testnet_activation_approval,
    )

    approval = create_testnet_activation_approval(
        _designation(),
        approval_id="approval-testnet-001",
        approved_by="human-reviewer-1",
        approved_at=datetime(2026, 8, 8, 4, 30, tzinfo=UTC),
        expires_at=datetime(2026, 8, 8, 4, 45, tzinfo=UTC),
    )
    path = tmp_path / "approvals.sqlite3"
    store = SqliteTestnetActivationApprovals(path)
    store.append(approval)
    store.append(approval)

    assert SqliteTestnetActivationApprovals(path).get("approval-testnet-001") == approval
    assert SqliteTestnetActivationApprovals(path).read() == (approval,)
    with pytest.raises(ValueError, match="conflicting activation approval ID"):
        store.append(approval.model_copy(update={"max_quote_notional": Decimal("200")}))

    absent = tmp_path / "absent.sqlite3"
    assert SqliteTestnetActivationApprovals(absent).read() == ()
    assert not absent.exists()
