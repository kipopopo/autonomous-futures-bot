from datetime import UTC, datetime
from decimal import Decimal, localcontext

import pytest

from autonomous_futures.paper.ledger import PaperLedger, PaperLedgerEntry
from autonomous_futures.paper.observation import observe_paper_ledger

CANDIDATE_ID = "cand-scope-rsi-adx-001"
CANDIDATE_HASH = "a" * 64


def _open() -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="open",
        trade_id="paper-001",
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("100"),
        occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


def _close() -> PaperLedgerEntry:
    return PaperLedgerEntry(
        event="close",
        trade_id="paper-001",
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("110"),
        occurred_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
        entry_fee=Decimal("0.01"),
        exit_fee=Decimal("0.02"),
        slippage_cost=Decimal("0.02"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("0.97"),
    )


def test_closed_paper_observation_derives_complete_realized_accounting_and_peak() -> None:
    snapshot = observe_paper_ledger(
        PaperLedger((_open(), _close())),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        starting_equity=Decimal("100"),
        previous_peak_equity=Decimal("100"),
        mark_prices={},
        observed_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
    )

    assert snapshot.realized_pnl == Decimal("0.97")
    assert snapshot.unrealized_pnl == Decimal("0")
    assert snapshot.equity == Decimal("100.97")
    assert snapshot.peak_equity == Decimal("100.97")
    assert snapshot.drawdown_pct == Decimal("0")
    assert snapshot.open_position_count == 0
    assert snapshot.quote_exposure == Decimal("0")
    assert snapshot.cumulative_fees == Decimal("0.03")
    assert snapshot.cumulative_slippage == Decimal("0.02")
    assert snapshot.accounting_complete is True
    assert snapshot.reason_codes == ("paper_observation_complete",)


def test_open_paper_observation_uses_explicit_mark_and_blocks_accounting_completeness() -> None:
    snapshot = observe_paper_ledger(
        PaperLedger((_open(),)),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        starting_equity=Decimal("100"),
        previous_peak_equity=Decimal("105"),
        mark_prices={"BTCUSDT": Decimal("110")},
        observed_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
    )

    assert snapshot.realized_pnl == Decimal("0")
    assert snapshot.unrealized_pnl == Decimal("1")
    assert snapshot.equity == Decimal("101")
    assert snapshot.peak_equity == Decimal("105")
    with localcontext() as context:
        context.prec = 80
        assert snapshot.drawdown_pct == (Decimal("101") - Decimal("105")) / Decimal("105")
    assert snapshot.open_position_count == 1
    assert snapshot.quote_exposure == Decimal("11")
    assert snapshot.accounting_complete is False
    assert snapshot.reason_codes == ("open_position_entry_accounting_unavailable",)


def test_open_paper_observation_rejects_missing_explicit_mark() -> None:
    with pytest.raises(ValueError, match="missing explicit mark"):
        observe_paper_ledger(
            PaperLedger((_open(),)),
            candidate_id=CANDIDATE_ID,
            candidate_artifact_hash=CANDIDATE_HASH,
            starting_equity=Decimal("100"),
            previous_peak_equity=Decimal("100"),
            mark_prices={},
            observed_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
        )
