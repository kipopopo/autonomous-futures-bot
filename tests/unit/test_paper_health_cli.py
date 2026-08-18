from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autonomous_futures.paper.ledger import PaperLedgerEntry
from autonomous_futures.paper.lifecycle import mark_paper_position
from autonomous_futures.paper.observation import PaperObservation
from autonomous_futures.paper.sqlite_lifecycle import SqlitePaperLifecycle
from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations

CANDIDATE_ID = "cand-scope-rsi-adx-001"
CANDIDATE_HASH = "a" * 64


def test_paper_health_cli_reports_healthy_read_only_aggregate(tmp_path, capsys) -> None:
    observation_path = tmp_path / "observations.sqlite3"
    lifecycle_path = tmp_path / "lifecycle.sqlite3"
    first = datetime(2026, 8, 1, tzinfo=UTC)
    observation_store = SqlitePaperObservations(observation_path)
    for index in range(28):
        observation_store.append(
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
        )
    entry = PaperLedgerEntry(
        event="open",
        trade_id="paper-001",
        candidate_id=CANDIDATE_ID,
        candidate_artifact_hash=CANDIDATE_HASH,
        symbol="BTCUSDT",
        side="LONG",
        quantity=Decimal("0.1"),
        fill_price=Decimal("100"),
        occurred_at=first,
        entry_fee=Decimal("0.004"),
        slippage_cost=Decimal("0.002"),
    )
    SqlitePaperLifecycle(lifecycle_path).append(
        mark_paper_position(
            entry,
            mark_price=Decimal("110"),
            marked_at=datetime(2026, 8, 8, tzinfo=UTC),
            previous_peak_pnl=Decimal("0"),
            take_profit_price=Decimal("120"),
        )
    )
    observation_count = len(observation_store.read(CANDIDATE_ID, CANDIDATE_HASH))
    lifecycle_count = len(
        SqlitePaperLifecycle(lifecycle_path).read(
            candidate_id=CANDIDATE_ID,
            candidate_artifact_hash=CANDIDATE_HASH,
            trade_id="paper-001",
        )
    )

    from autonomous_futures.paper.health_cli import main

    exit_code = main(
        [
            "--observation-path",
            str(observation_path),
            "--lifecycle-path",
            str(lifecycle_path),
            "--candidate-id",
            CANDIDATE_ID,
            "--candidate-artifact-hash",
            CANDIDATE_HASH,
            "--as-of",
            "2026-08-08T01:00:00Z",
            "--max-mark-age-seconds",
            "7200",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "healthy"
    assert payload["maturity_status"] == "mature"
    assert payload["lifecycle"][0]["mark_age_seconds"] == 3600
    assert payload["paper_activation"] is False
    assert payload["execution_authority"] is False
    assert payload["exchange_access"] is False
    assert len(observation_store.read(CANDIDATE_ID, CANDIDATE_HASH)) == observation_count
    assert (
        len(
            SqlitePaperLifecycle(lifecycle_path).read(
                candidate_id=CANDIDATE_ID,
                candidate_artifact_hash=CANDIDATE_HASH,
                trade_id="paper-001",
            )
        )
        == lifecycle_count
    )


def test_paper_health_cli_reports_unavailable_without_creating_journals(tmp_path, capsys) -> None:
    from autonomous_futures.paper.health_cli import main

    observation_path = tmp_path / "absent-observations.sqlite3"
    lifecycle_path = tmp_path / "absent-lifecycle.sqlite3"
    exit_code = main(
        [
            "--observation-path",
            str(observation_path),
            "--lifecycle-path",
            str(lifecycle_path),
            "--candidate-id",
            CANDIDATE_ID,
            "--candidate-artifact-hash",
            CANDIDATE_HASH,
            "--as-of",
            "2026-08-08T00:00:00Z",
            "--max-mark-age-seconds",
            "7200",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
    assert not observation_path.exists()
    assert not lifecycle_path.exists()
