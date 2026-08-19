from datetime import UTC, datetime

import pytest

from autonomous_futures.testnet_audit import TestnetLifecycleEvidence as _TestnetLifecycleEvidence
from autonomous_futures.testnet_lifecycle import parse_testnet_order_record


def _evidence() -> _TestnetLifecycleEvidence:
    from autonomous_futures.testnet_audit import create_testnet_lifecycle_evidence
    from autonomous_futures.testnet_lifecycle import TestnetLifecycleAudit as _TestnetLifecycleAudit

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
    return create_testnet_lifecycle_evidence(
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


def test_testnet_observation_captures_stable_flat_account_bound_to_audit() -> None:
    from autonomous_futures.testnet_observation import (
        TestnetAccountObservationInput,
        capture_testnet_observation,
    )

    observation = capture_testnet_observation(
        _evidence(),
        TestnetAccountObservationInput(asset_count=8, nonzero_position_count=0),
        observation_id="observation-testnet-001",
        observed_at=datetime(2026, 8, 8, 2, tzinfo=UTC),
    )

    assert observation.status == "stable"
    assert observation.audit_id == "audit-testnet-001"
    assert observation.audit_hash == _evidence().evidence_hash
    assert observation.asset_count == 8
    assert observation.nonzero_position_count == 0
    assert observation.paper_activation is False
    assert observation.execution_authority is False
    assert observation.live_enabled is False


def test_testnet_observation_marks_drift_for_nonzero_position() -> None:
    from autonomous_futures.testnet_observation import (
        TestnetAccountObservationInput,
        capture_testnet_observation,
    )

    observation = capture_testnet_observation(
        _evidence(),
        TestnetAccountObservationInput(asset_count=8, nonzero_position_count=1),
        observation_id="observation-testnet-001",
        observed_at=datetime(2026, 8, 8, 2, tzinfo=UTC),
    )

    assert observation.status == "drift"
    assert observation.reason_codes == ("nonzero_position_detected",)


def test_sqlite_testnet_observation_is_write_once_and_absent_read_pure(tmp_path) -> None:
    from autonomous_futures.testnet_observation import (
        SqliteTestnetObservations,
        TestnetAccountObservationInput,
        capture_testnet_observation,
    )

    path = tmp_path / "observations.sqlite3"
    observation = capture_testnet_observation(
        _evidence(),
        TestnetAccountObservationInput(asset_count=8, nonzero_position_count=0),
        observation_id="observation-testnet-001",
        observed_at=datetime(2026, 8, 8, 2, tzinfo=UTC),
    )
    store = SqliteTestnetObservations(path)
    store.append(observation)
    store.append(observation)

    assert SqliteTestnetObservations(path).get("observation-testnet-001") == observation
    assert SqliteTestnetObservations(path).read() == (observation,)
    with pytest.raises(ValueError, match="conflicting observation ID"):
        store.append(observation.model_copy(update={"asset_count": 9}))

    absent = tmp_path / "absent.sqlite3"
    assert SqliteTestnetObservations(absent).read() == ()
    assert not absent.exists()
