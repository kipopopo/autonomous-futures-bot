from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _review():
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
    return create_testnet_evidence_review(
        audit,
        observation,
        review_id="review-testnet-001",
        reviewer_id="human-reviewer-1",
        reviewed_at=datetime(2026, 8, 8, 3, tzinfo=UTC),
        decision="accept_testnet_observation",
        review_notes="Reviewed stable flat evidence.",
    )


def test_activation_designation_is_scoped_but_does_not_unlock_actions() -> None:
    from autonomous_futures.testnet_activation import create_testnet_activation_designation

    designation = create_testnet_activation_designation(
        _review(),
        designation_id="designation-testnet-001",
        designated_by="human-reviewer-1",
        designated_at=datetime(2026, 8, 8, 4, tzinfo=UTC),
        expires_at=datetime(2026, 8, 8, 5, tzinfo=UTC),
        symbol="BTCUSDT",
        max_quote_notional=Decimal("100"),
    )

    assert designation.state == "designated_not_activated"
    assert designation.new_actions_allowed is False
    assert designation.max_open_positions == 1
    assert designation.live_enabled is False
    assert len(designation.designation_hash) == 64


def test_activation_designation_rejects_expired_or_unready_review() -> None:
    from autonomous_futures.testnet_activation import create_testnet_activation_designation

    with pytest.raises(ValueError, match="expires_at"):
        create_testnet_activation_designation(
            _review(),
            designation_id="designation-testnet-001",
            designated_by="human-reviewer-1",
            designated_at=datetime(2026, 8, 8, 5, tzinfo=UTC),
            expires_at=datetime(2026, 8, 8, 5, tzinfo=UTC),
            symbol="BTCUSDT",
            max_quote_notional=Decimal("100"),
        )


def test_sqlite_activation_designation_is_write_once_and_absent_read_pure(tmp_path) -> None:
    from autonomous_futures.testnet_activation import (
        SqliteTestnetActivationDesignations,
        create_testnet_activation_designation,
    )

    designation = create_testnet_activation_designation(
        _review(),
        designation_id="designation-testnet-001",
        designated_by="human-reviewer-1",
        designated_at=datetime(2026, 8, 8, 4, tzinfo=UTC),
        expires_at=datetime(2026, 8, 8, 5, tzinfo=UTC),
        symbol="BTCUSDT",
        max_quote_notional=Decimal("100"),
    )
    path = tmp_path / "designations.sqlite3"
    store = SqliteTestnetActivationDesignations(path)
    store.append(designation)
    store.append(designation)

    assert SqliteTestnetActivationDesignations(path).get("designation-testnet-001") == designation
    assert SqliteTestnetActivationDesignations(path).read() == (designation,)
    with pytest.raises(ValueError, match="conflicting designation ID"):
        store.append(designation.model_copy(update={"max_quote_notional": Decimal("200")}))

    absent = tmp_path / "absent.sqlite3"
    assert SqliteTestnetActivationDesignations(absent).read() == ()
    assert not absent.exists()
