from datetime import UTC, datetime

import pytest

from autonomous_futures.testnet_audit import create_testnet_lifecycle_evidence
from autonomous_futures.testnet_lifecycle import parse_testnet_order_record
from autonomous_futures.testnet_observation import capture_testnet_observation


def _evidence_and_observation():
    from autonomous_futures.testnet_lifecycle import TestnetLifecycleAudit as _TestnetLifecycleAudit
    from autonomous_futures.testnet_observation import (
        TestnetAccountObservationInput as _TestnetAccountObservationInput,
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
    evidence = create_testnet_lifecycle_evidence(
        open_order,
        close_order,
        pre_open_nonzero_positions=0,
        post_close_nonzero_positions=0,
        audit=_TestnetLifecycleAudit(
            status="reconciled",
            open_order_id=1,
            close_order_id=2,
            reason_codes=("testnet_lifecycle_reconciled",),
        ),
        audit_id="audit-testnet-001",
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
    )
    observation = capture_testnet_observation(
        evidence,
        _TestnetAccountObservationInput(asset_count=8, nonzero_position_count=0),
        observation_id="observation-testnet-001",
        observed_at=datetime(2026, 8, 8, 2, tzinfo=UTC),
    )
    return evidence, observation


def test_testnet_evidence_freeze_accepts_only_stable_flat_observation() -> None:
    from autonomous_futures.testnet_freeze import create_testnet_evidence_review

    evidence, observation = _evidence_and_observation()
    review = create_testnet_evidence_review(
        evidence,
        observation,
        review_id="review-testnet-001",
        reviewer_id="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 8, 3, tzinfo=UTC),
        decision="accept_testnet_observation",
        review_notes="Reviewed reconciled lifecycle and stable flat account observation.",
    )

    assert len(review.review_hash) == 64
    assert review.decision == "accept_testnet_observation"
    assert review.paper_activation is False
    assert review.execution_authority is False
    assert review.live_enabled is False


def test_testnet_evidence_freeze_rejects_acceptance_of_drift() -> None:
    from autonomous_futures.testnet_freeze import create_testnet_evidence_review
    from autonomous_futures.testnet_observation import TestnetAccountObservationInput

    evidence, observation = _evidence_and_observation()
    drift = capture_testnet_observation(
        evidence,
        TestnetAccountObservationInput(asset_count=8, nonzero_position_count=1),
        observation_id="observation-testnet-drift",
        observed_at=datetime(2026, 8, 8, 2, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="stable flat"):
        create_testnet_evidence_review(
            evidence,
            drift,
            review_id="review-testnet-001",
            reviewer_id="human-reviewer-1",
            reviewed_at=datetime(2026, 8, 8, 3, tzinfo=UTC),
            decision="accept_testnet_observation",
            review_notes="Not accepted.",
        )


def test_sqlite_testnet_freeze_is_write_once_and_absent_read_pure(tmp_path) -> None:
    from autonomous_futures.testnet_freeze import (
        SqliteTestnetEvidenceReviews,
        create_testnet_evidence_review,
    )

    evidence, observation = _evidence_and_observation()
    review = create_testnet_evidence_review(
        evidence,
        observation,
        review_id="review-testnet-001",
        reviewer_id="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 8, 3, tzinfo=UTC),
        decision="accept_testnet_observation",
        review_notes="Reviewed stable flat testnet evidence.",
    )
    path = tmp_path / "reviews.sqlite3"
    store = SqliteTestnetEvidenceReviews(path)
    store.append(review)
    store.append(review)

    assert SqliteTestnetEvidenceReviews(path).get("review-testnet-001") == review
    assert SqliteTestnetEvidenceReviews(path).read() == (review,)
    with pytest.raises(ValueError, match="conflicting testnet review ID"):
        store.append(review.model_copy(update={"review_notes": "changed"}))

    absent = tmp_path / "absent.sqlite3"
    assert SqliteTestnetEvidenceReviews(absent).read() == ()
    assert not absent.exists()
