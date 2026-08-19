from datetime import UTC, datetime

import pytest

from autonomous_futures.testnet_lifecycle import parse_testnet_order_record


def _evidence():
    from autonomous_futures.testnet_audit import create_testnet_lifecycle_evidence
    from autonomous_futures.testnet_lifecycle import TestnetLifecycleAudit

    return create_testnet_lifecycle_evidence(
        parse_testnet_order_record(
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
        ),
        parse_testnet_order_record(
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
        ),
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


def test_testnet_lifecycle_evidence_is_hash_bound_and_authority_free() -> None:
    evidence = _evidence()

    assert len(evidence.evidence_hash) == 64
    assert evidence.open_order.order_id == 1
    assert evidence.close_order.reduce_only is True
    assert evidence.pre_open_nonzero_positions == 0
    assert evidence.post_close_nonzero_positions == 0
    assert evidence.live_enabled is False
    assert evidence.paper_activation is False
    assert evidence.execution_authority is False


def test_sqlite_testnet_evidence_is_write_once_and_restart_safe(tmp_path) -> None:
    from autonomous_futures.testnet_audit import SqliteTestnetLifecycleEvidence

    path = tmp_path / "testnet-audits.sqlite3"
    store = SqliteTestnetLifecycleEvidence(path)
    evidence = _evidence()
    store.append(evidence)
    store.append(evidence)

    reopened = SqliteTestnetLifecycleEvidence(path)
    assert reopened.get("audit-testnet-001") == evidence
    assert reopened.read() == (evidence,)

    with pytest.raises(ValueError, match="conflicting audit ID"):
        store.append(evidence.model_copy(update={"post_close_nonzero_positions": 1}))


def test_sqlite_testnet_evidence_absent_read_does_not_create_database(tmp_path) -> None:
    from autonomous_futures.testnet_audit import SqliteTestnetLifecycleEvidence

    path = tmp_path / "absent.sqlite3"
    assert SqliteTestnetLifecycleEvidence(path).get("audit-testnet-001") is None
    assert SqliteTestnetLifecycleEvidence(path).read() == ()
    assert not path.exists()
