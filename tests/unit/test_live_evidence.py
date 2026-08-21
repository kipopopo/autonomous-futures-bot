from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _token():
    from autonomous_futures.live_activation import issue_live_activation_token
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
    return issue_live_activation_token(
        review,
        token_id="token-live-002",
        issued_at=datetime(2026, 8, 21, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 21, 2, tzinfo=UTC),
    )


def test_live_readonly_evidence_binds_token_and_safe_aggregates() -> None:
    from autonomous_futures.live_evidence import capture_live_readonly_evidence

    evidence = capture_live_readonly_evidence(
        _token(),
        evidence_id="evidence-live-001",
        observed_at=datetime(2026, 8, 21, 1, 30, tzinfo=UTC),
        asset_count=11,
        nonzero_position_count=0,
        status="reconciled",
        reason_codes=("live_account_reconciled",),
        network_request_count=1,
    )

    assert evidence.token_id == "token-live-002"
    assert evidence.asset_count == 11
    assert evidence.nonzero_position_count == 0
    assert evidence.network_request_count == 1
    assert evidence.live_enabled is False
    assert evidence.order_capability is False
    assert len(evidence.evidence_hash) == 64


def test_live_readonly_evidence_rejects_multiple_requests() -> None:
    from autonomous_futures.live_evidence import capture_live_readonly_evidence

    with pytest.raises(ValueError, match="exactly one"):
        capture_live_readonly_evidence(
            _token(),
            evidence_id="evidence-live-002",
            observed_at=datetime(2026, 8, 21, 1, 30, tzinfo=UTC),
            asset_count=11,
            nonzero_position_count=0,
            status="reconciled",
            reason_codes=("live_account_reconciled",),
            network_request_count=2,
        )


def test_live_readonly_evidence_journal_is_write_once_and_absent_read_pure(tmp_path) -> None:
    from autonomous_futures.live_evidence import (
        SqliteLiveReadOnlyEvidence,
        capture_live_readonly_evidence,
    )

    evidence = capture_live_readonly_evidence(
        _token(),
        evidence_id="evidence-live-003",
        observed_at=datetime(2026, 8, 21, 1, 30, tzinfo=UTC),
        asset_count=11,
        nonzero_position_count=0,
        status="reconciled",
        reason_codes=("live_account_reconciled",),
        network_request_count=1,
    )
    path = tmp_path / "live-evidence.sqlite3"
    store = SqliteLiveReadOnlyEvidence(path)
    store.append(evidence)
    store.append(evidence)

    assert store.get(evidence.evidence_id) == evidence
    assert store.read() == (evidence,)
    with pytest.raises(ValueError, match="conflicting live evidence ID"):
        store.append(evidence.model_copy(update={"asset_count": 12}))

    absent = tmp_path / "absent.sqlite3"
    assert SqliteLiveReadOnlyEvidence(absent).read() == ()
    assert not absent.exists()
