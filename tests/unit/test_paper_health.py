from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedgerEntry
from autonomous_futures.paper.lifecycle import mark_paper_position
from autonomous_futures.paper.observation import PaperObservation

CANDIDATE_ID = "cand-scope-rsi-adx-001"
CANDIDATE_HASH = "a" * 64


def _observations() -> tuple[PaperObservation, ...]:
    first = datetime(2026, 8, 1, tzinfo=UTC)
    return tuple(
        PaperObservation(
            candidate_id=CANDIDATE_ID,
            candidate_artifact_hash=CANDIDATE_HASH,
            observed_at=first + timedelta(hours=6 * index),
            equity=Decimal("100"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            peak_equity=Decimal("100"),
            drawdown_pct=Decimal("0"),
            open_position_count=1,
            quote_exposure=Decimal("11"),
            cumulative_fees=Decimal("0.004"),
            cumulative_slippage=Decimal("0.002"),
            accounting_complete=True,
            reason_codes=("paper_observation_complete",),
        )
        for index in range(28)
    )


def _lifecycle():
    entry = PaperLedgerEntry(
        event="open",
        trade_id="paper-001",
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("100"),
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        entry_fee=Decimal("0.004"),
        slippage_cost=Decimal("0.002"),
    )
    return mark_paper_position(
        entry,
        mark_price=Decimal("110"),
        marked_at=datetime(2026, 8, 8, tzinfo=UTC),
        previous_peak_pnl=Decimal("0"),
        take_profit_price=Decimal("120"),
    )


def test_aggregate_paper_health_reports_mature_healthy_candidate_and_mark_age() -> None:
    from autonomous_futures.paper.health import aggregate_paper_health

    report = aggregate_paper_health(
        _observations(),
        (_lifecycle(),),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, 1, tzinfo=UTC),
        max_mark_age_seconds=7200,
    )

    assert report.health_status == "healthy"
    assert report.maturity_status == "mature"
    assert report.latest_equity == Decimal("100")
    assert report.open_position_count == 1
    assert report.lifecycle[0].trade_id == "paper-001"
    assert report.lifecycle[0].mark_age_seconds == 3600
    assert report.lifecycle[0].stale is False
    assert report.reason_codes == ("paper_health_healthy",)
    assert report.paper_activation is False
    assert report.execution_authority is False
    assert report.exchange_access is False


def test_aggregate_paper_health_reports_attention_for_stale_exit_ready_mark() -> None:
    from autonomous_futures.paper.health import aggregate_paper_health

    mark = _lifecycle().model_copy(update={"lifecycle_status": "exit_ready"})
    report = aggregate_paper_health(
        _observations(),
        (mark,),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, 2, tzinfo=UTC),
        max_mark_age_seconds=3600,
    )

    assert report.health_status == "attention"
    assert report.lifecycle[0].stale is True
    assert report.reason_codes == (
        "paper_lifecycle_mark_stale",
        "paper_lifecycle_exit_ready",
    )


def test_aggregate_paper_health_reports_maturing_without_open_telemetry() -> None:
    from autonomous_futures.paper.health import aggregate_paper_health

    observations = tuple(
        observation.model_copy(update={"open_position_count": 0})
        for observation in _observations()[:5]
    )
    report = aggregate_paper_health(
        observations,
        (),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 2, tzinfo=UTC),
        max_mark_age_seconds=3600,
    )

    assert report.health_status == "maturing"
    assert report.maturity_status == "maturing"
    assert report.reason_codes == ("paper_observation_maturity_in_progress",)


def test_aggregate_paper_health_reports_unavailable_without_observation() -> None:
    from autonomous_futures.paper.health import aggregate_paper_health

    report = aggregate_paper_health(
        (),
        (),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        max_mark_age_seconds=3600,
    )

    assert report.health_status == "unavailable"
    assert report.reason_codes == ("paper_health_observation_unavailable",)


def test_aggregate_paper_health_blocks_incomplete_latest_observation() -> None:
    from autonomous_futures.paper.health import aggregate_paper_health

    observations = _observations()[:-1] + (
        _observations()[-1].model_copy(update={"accounting_complete": False}),
    )
    report = aggregate_paper_health(
        observations,
        (),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        max_mark_age_seconds=3600,
    )

    assert report.health_status == "blocked"
    assert "paper_observation_accounting_incomplete" in report.reason_codes
