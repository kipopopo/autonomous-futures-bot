from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from autonomous_futures.paper.safety import PaperActionApproval


def test_paper_action_approval_rejects_expiry_at_or_before_approval_time() -> None:
    with pytest.raises(ValidationError, match="after approved_at"):
        PaperActionApproval(
            approval_id="approval-open-001",
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            trade_id="paper-001",
            action="open",
            approved_at=datetime(2026, 8, 13, tzinfo=UTC),
            expires_at=datetime(2026, 8, 13, tzinfo=UTC),
        )


def test_paper_action_approval_requires_utc_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        PaperActionApproval(
            approval_id="approval-open-001",
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            trade_id="paper-001",
            action="open",
            approved_at=datetime(2026, 8, 13),
            expires_at=datetime(2026, 8, 13, tzinfo=UTC) + timedelta(minutes=1),
        )
