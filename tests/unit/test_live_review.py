from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _inputs(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "review_id": "review-live-001",
        "reviewed_by": "human-reviewer-1",
        "reviewed_at": datetime(2026, 8, 20, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 21, tzinfo=UTC),
        "decision": "approve_live_design",
        "candidate_id": "cand-scope-rsi-adx-001",
        "candidate_artifact_hash": "a" * 64,
        "testnet_completion_hash": "b" * 64,
        "legal_review_confirmed": True,
        "venue_account_confirmed": True,
        "capital_risk_confirmed": True,
        "secret_manager_confirmed": True,
        "kill_switch_confirmed": True,
        "reconciliation_clean": True,
        "symbol_approved": True,
        "explicit_live_activation": True,
        "symbol": "BTCUSDT",
        "max_quote_notional_pct": Decimal("50"),
        "max_capital_at_risk_pct": Decimal("1"),
        "max_daily_loss_pct": Decimal("2"),
    }
    payload.update(changes)
    return payload


def test_live_review_is_design_only_even_when_all_gates_are_confirmed() -> None:
    from autonomous_futures.live_review import create_live_activation_review

    review = create_live_activation_review(**_inputs())

    assert review.state == "reviewed_not_activated"
    assert review.live_enabled is False
    assert review.network_allowed is False
    assert len(review.review_hash) == 64


def test_live_review_rejects_approval_with_missing_gate() -> None:
    from autonomous_futures.live_review import create_live_activation_review

    with pytest.raises(ValueError, match="missing live gate"):
        create_live_activation_review(**_inputs(legal_review_confirmed=False))


def test_sqlite_live_review_is_write_once_and_absent_read_pure(tmp_path) -> None:
    from autonomous_futures.live_review import (
        SqliteLiveActivationReviews,
        create_live_activation_review,
    )

    review = create_live_activation_review(**_inputs())
    path = tmp_path / "live-reviews.sqlite3"
    store = SqliteLiveActivationReviews(path)
    store.append(review)
    store.append(review)

    assert SqliteLiveActivationReviews(path).get("review-live-001") == review
    assert SqliteLiveActivationReviews(path).read() == (review,)
    with pytest.raises(ValueError, match="conflicting live review ID"):
        store.append(review.model_copy(update={"symbol": "ETHUSDT"}))

    absent = tmp_path / "absent.sqlite3"
    assert SqliteLiveActivationReviews(absent).read() == ()
    assert not absent.exists()
