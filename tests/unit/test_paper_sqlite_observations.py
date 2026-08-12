from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from autonomous_futures.paper.observation import PaperObservation
from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations

CANDIDATE_ID = "cand-scope-rsi-adx-001"
CANDIDATE_HASH = "a" * 64


def _snapshot(*, observed_at: datetime, complete: bool) -> PaperObservation:
    return PaperObservation(
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        observed_at=observed_at,
        equity=Decimal("100.97"),
        realized_pnl=Decimal("0.97"),
        unrealized_pnl=Decimal("0"),
        peak_equity=Decimal("100.97"),
        drawdown_pct=Decimal("0"),
        open_position_count=0,
        quote_exposure=Decimal("0"),
        cumulative_fees=Decimal("0.03"),
        cumulative_slippage=Decimal("0.02"),
        accounting_complete=complete,
        reason_codes=(
            ("paper_observation_complete",)
            if complete
            else ("open_position_entry_accounting_unavailable",)
        ),
    )


def test_sqlite_paper_observations_append_and_reload_complete_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "paper-observations.sqlite3"
    snapshot = _snapshot(observed_at=datetime(2026, 8, 11, tzinfo=UTC), complete=True)
    store = SqlitePaperObservations(path)

    store.append(snapshot)

    assert SqlitePaperObservations(path).read(CANDIDATE_ID, CANDIDATE_HASH) == (snapshot,)


def test_sqlite_paper_observations_preserve_incomplete_snapshot_as_diagnostic_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "paper-observations.sqlite3"
    incomplete = _snapshot(observed_at=datetime(2026, 8, 11, tzinfo=UTC), complete=False)
    complete = _snapshot(observed_at=datetime(2026, 8, 11, 1, tzinfo=UTC), complete=True)
    store = SqlitePaperObservations(path)

    store.append(incomplete)
    store.append(complete)

    assert SqlitePaperObservations(path).read(CANDIDATE_ID, CANDIDATE_HASH) == (
        incomplete,
        complete,
    )
