from datetime import UTC, datetime


def _evidence_chain():
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
    return (audit,), (observation,), (review,)


def test_completion_summary_reports_frozen_complete_evidence_and_locked_actions() -> None:
    from autonomous_futures.testnet_completion import summarize_testnet_completion

    audits, observations, reviews = _evidence_chain()
    summary = summarize_testnet_completion(audits, observations, reviews)

    assert summary.status == "complete"
    assert summary.audit_count == 1
    assert summary.reconciled_audit_count == 1
    assert summary.observation_count == 1
    assert summary.stable_observation_count == 1
    assert summary.accepted_review_count == 1
    assert summary.new_actions_allowed is False
    assert summary.reason_codes == ("testnet_evidence_complete_and_frozen",)


def test_completion_summary_blocks_hash_binding_drift() -> None:
    from autonomous_futures.testnet_completion import summarize_testnet_completion

    audits, observations, reviews = _evidence_chain()
    drifted = observations[0].model_copy(update={"audit_hash": "b" * 64})
    summary = summarize_testnet_completion(audits, (drifted,), reviews)

    assert summary.status == "blocked"
    assert summary.reason_codes == ("testnet_evidence_binding_drift",)
