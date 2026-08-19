from datetime import UTC, datetime

import pytest

from autonomous_futures.testnet_lifecycle import parse_testnet_order_record
from autonomous_futures.testnet_observation import capture_testnet_observation


def _review():
    from autonomous_futures.testnet_audit import create_testnet_lifecycle_evidence
    from autonomous_futures.testnet_freeze import create_testnet_evidence_review
    from autonomous_futures.testnet_lifecycle import TestnetLifecycleAudit
    from autonomous_futures.testnet_observation import TestnetAccountObservationInput

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
    return create_testnet_evidence_review(
        audit,
        observation,
        review_id="review-testnet-001",
        reviewer_id="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 8, 3, tzinfo=UTC),
        decision="accept_testnet_observation",
        review_notes="Reviewed stable flat evidence.",
    )


def test_frozen_testnet_evidence_blocks_new_actions() -> None:
    from autonomous_futures.testnet_lock import (
        freeze_testnet_evidence,
        require_testnet_action_unlocked,
    )

    lock = freeze_testnet_evidence(_review(), locked_at=datetime(2026, 8, 8, 4, tzinfo=UTC))

    assert lock.new_actions_allowed is False
    assert lock.live_enabled is False
    with pytest.raises(ValueError, match="frozen testnet evidence"):
        require_testnet_action_unlocked(lock, action="new_order")
