from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autonomous_futures.paper.observation import PaperObservation


def test_paper_observation_rejects_any_authority_flag() -> None:
    with pytest.raises(ValidationError):
        PaperObservation(
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            observed_at=datetime(2026, 8, 11, tzinfo=UTC),
            equity=Decimal("100"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            peak_equity=Decimal("100"),
            drawdown_pct=Decimal("0"),
            open_position_count=0,
            quote_exposure=Decimal("0"),
            cumulative_fees=Decimal("0"),
            cumulative_slippage=Decimal("0"),
            accounting_complete=True,
            paper_activation=True,
            reason_codes=("paper_observation_complete",),
        )
