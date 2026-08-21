from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _token_and_evidence():
    from autonomous_futures.live_activation import issue_live_activation_token
    from autonomous_futures.live_evidence import capture_live_readonly_evidence
    from autonomous_futures.live_review import create_live_activation_review

    review = create_live_activation_review(
        review_id="review-live-003",
        reviewed_by="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 21, tzinfo=UTC),
        expires_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        decision="approve_live_design",
        candidate_id="cand-scope-rsi-adx-001",
        candidate_artifact_hash="a" * 64,
        testnet_completion_hash="b" * 64,
        legal_review_confirmed=True,
        venue_account_confirmed=True,
        capital_risk_confirmed=True,
        secret_manager_confirmed=True,
        kill_switch_confirmed=True,
        reconciliation_clean=True,
        symbol_approved=True,
        explicit_live_activation=True,
        symbol="BTCUSDT",
        max_quote_notional_pct=Decimal("50"),
        max_capital_at_risk_pct=Decimal("1"),
        max_daily_loss_pct=Decimal("2"),
    )
    token = issue_live_activation_token(
        review,
        token_id="token-live-002",
        issued_at=datetime(2026, 8, 21, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 21, 2, tzinfo=UTC),
    )
    evidence = capture_live_readonly_evidence(
        token,
        evidence_id="evidence-live-001",
        observed_at=datetime(2026, 8, 21, 1, 30, tzinfo=UTC),
        asset_count=11,
        nonzero_position_count=0,
        status="reconciled",
        reason_codes=("live_account_reconciled",),
        network_request_count=1,
    )
    return token, evidence


def test_final_order_review_is_bound_but_not_enabled() -> None:
    from autonomous_futures.live_order_review import create_live_order_activation_review

    token, evidence = _token_and_evidence()
    review = create_live_order_activation_review(
        token,
        evidence,
        review_id="review-order-live-001",
        reviewed_at=datetime(2026, 8, 21, 1, 40, tzinfo=UTC),
        expires_at=datetime(2026, 8, 21, 1, 50, tzinfo=UTC),
        reviewed_by="human-reviewer-1",
        decision="approve_one_live_lifecycle",
    )

    assert review.token_id == token.token_id
    assert review.evidence_id == evidence.evidence_id
    assert review.symbol == "BTCUSDT"
    assert review.max_quote_notional_pct == Decimal("50")
    assert review.max_capital_at_risk_pct == Decimal("1")
    assert review.max_daily_loss_pct == Decimal("2")
    assert review.max_leverage == Decimal("1")
    assert review.max_open_positions == 1
    assert review.state == "reviewed_not_enabled"
    assert review.live_order_enabled is False
    assert review.network_allowed is False
    assert len(review.review_hash) == 64


def test_final_order_review_rejects_drifted_evidence() -> None:
    from autonomous_futures.live_order_review import create_live_order_activation_review

    token, evidence = _token_and_evidence()
    drifted = evidence.model_copy(update={"nonzero_position_count": 1})

    with pytest.raises(ValueError, match="evidence is not reconciled"):
        create_live_order_activation_review(
            token,
            drifted,
            review_id="review-order-live-002",
            reviewed_at=datetime(2026, 8, 21, 1, 40, tzinfo=UTC),
            expires_at=datetime(2026, 8, 21, 1, 50, tzinfo=UTC),
            reviewed_by="human-reviewer-1",
            decision="approve_one_live_lifecycle",
        )


def test_final_order_review_journal_is_write_once(tmp_path) -> None:
    from autonomous_futures.live_order_review import (
        SqliteLiveOrderActivationReviews,
        create_live_order_activation_review,
    )

    token, evidence = _token_and_evidence()
    review = create_live_order_activation_review(
        token,
        evidence,
        review_id="review-order-live-003",
        reviewed_at=datetime(2026, 8, 21, 1, 40, tzinfo=UTC),
        expires_at=datetime(2026, 8, 21, 1, 50, tzinfo=UTC),
        reviewed_by="human-reviewer-1",
        decision="approve_one_live_lifecycle",
    )
    store = SqliteLiveOrderActivationReviews(tmp_path / "reviews.sqlite3")
    store.append(review)
    store.append(review)

    assert store.get(review.review_id) == review
    with pytest.raises(ValueError, match="conflicting live order review ID"):
        store.append(review.model_copy(update={"symbol": "ETHUSDT"}))
