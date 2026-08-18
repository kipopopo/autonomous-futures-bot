from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autonomous_futures.paper.observation import PaperObservation

CANDIDATE_ID = "cand-scope-rsi-adx-001"
CANDIDATE_HASH = "a" * 64


def _observation(observed_at: datetime, *, accounting_complete: bool = True) -> PaperObservation:
    return PaperObservation(
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        observed_at=observed_at,
        equity=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        peak_equity=Decimal("100"),
        drawdown_pct=Decimal("0"),
        open_position_count=0,
        quote_exposure=Decimal("0"),
        cumulative_fees=Decimal("0"),
        cumulative_slippage=Decimal("0"),
        accounting_complete=accounting_complete,
        reason_codes=("paper_observation_complete",),
    )


def test_maturity_evaluator_reports_complete_seven_day_coverage() -> None:
    from autonomous_futures.paper.maturity import evaluate_paper_maturity

    first = datetime(2026, 8, 1, tzinfo=UTC)
    observations = tuple(_observation(first + timedelta(hours=6 * index)) for index in range(28))

    report = evaluate_paper_maturity(
        observations,
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert report.status == "mature"
    assert report.required_slots == 28
    assert report.observed_slots == 28
    assert report.first_slot == first
    assert report.maturity_end == datetime(2026, 8, 8, tzinfo=UTC)
    assert report.next_slot is None
    assert report.reason_codes == ("paper_observation_maturity_complete",)
    assert report.paper_activation is False
    assert report.execution_authority is False
    assert report.exchange_access is False


def test_maturity_evaluator_reports_in_progress_without_shortening_seven_day_gate() -> None:
    from autonomous_futures.paper.maturity import evaluate_paper_maturity

    first = datetime(2026, 8, 1, tzinfo=UTC)
    observations = tuple(_observation(first + timedelta(hours=6 * index)) for index in range(5))

    report = evaluate_paper_maturity(
        observations,
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert report.status == "maturing"
    assert report.observed_slots == 5
    assert report.maturity_end == datetime(2026, 8, 8, tzinfo=UTC)
    assert report.next_slot == datetime(2026, 8, 2, 6, tzinfo=UTC)


def test_maturity_evaluator_blocks_missing_completed_slot() -> None:
    from autonomous_futures.paper.maturity import evaluate_paper_maturity

    first = datetime(2026, 8, 1, tzinfo=UTC)
    observations = tuple(
        _observation(first + timedelta(hours=6 * index)) for index in range(28) if index != 3
    )

    report = evaluate_paper_maturity(
        observations,
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert report.status == "blocked"
    assert report.next_slot == datetime(2026, 8, 1, 18, tzinfo=UTC)
    assert report.reason_codes == ("paper_observation_slot_missing",)


def test_maturity_evaluator_blocks_incomplete_accounting() -> None:
    from autonomous_futures.paper.maturity import evaluate_paper_maturity

    first = datetime(2026, 8, 1, tzinfo=UTC)
    observations = tuple(
        _observation(
            first + timedelta(hours=6 * index),
            accounting_complete=index != 4,
        )
        for index in range(28)
    )

    report = evaluate_paper_maturity(
        observations,
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert report.status == "blocked"
    assert report.accounting_complete is False
    assert report.reason_codes == ("paper_observation_accounting_incomplete",)


def test_maturity_evaluator_blocks_duplicate_fixed_slot() -> None:
    from autonomous_futures.paper.maturity import evaluate_paper_maturity

    first = datetime(2026, 8, 1, tzinfo=UTC)
    observations = tuple(_observation(first + timedelta(hours=6 * index)) for index in range(28))
    observations += (_observation(first + timedelta(hours=6 * 4, minutes=30)),)

    report = evaluate_paper_maturity(
        observations,
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert report.status == "blocked"
    assert report.reason_codes == ("paper_observation_duplicate_slot",)


def test_maturity_evaluator_reports_unavailable_without_observations() -> None:
    from autonomous_futures.paper.maturity import evaluate_paper_maturity

    report = evaluate_paper_maturity(
        (),
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert report.status == "unavailable"
    assert report.reason_codes == ("paper_observation_evidence_unavailable",)
