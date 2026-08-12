from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autonomous_futures.paper.ledger import PaperLedgerEntry


def test_paper_close_event_requires_complete_accounting() -> None:
    with pytest.raises(ValidationError, match="paper close requires complete accounting"):
        PaperLedgerEntry(
            event="close",
            trade_id="paper-001",
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("0.1"),
            fill_price=Decimal("110"),
            occurred_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
        )


def test_paper_close_event_requires_net_pnl_reconciled_to_gross_fees() -> None:
    with pytest.raises(ValidationError, match="paper net P&L must include all fees"):
        PaperLedgerEntry(
            event="close",
            trade_id="paper-001",
            candidate_id="cand-scope-rsi-adx-001",
            candidate_artifact_hash="a" * 64,
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("0.1"),
            fill_price=Decimal("110"),
            occurred_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
            entry_fee=Decimal("0.01"),
            exit_fee=Decimal("0.02"),
            slippage_cost=Decimal("0.02"),
            gross_pnl=Decimal("1"),
            net_pnl=Decimal("1"),
        )
