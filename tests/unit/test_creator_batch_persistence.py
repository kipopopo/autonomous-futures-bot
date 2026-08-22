from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_batch import CreatorBatchResult, CreatorBatchTrial
from autonomous_futures.research.creator_batch_persistence import (
    build_creator_batch_trial_evidence,
    persist_creator_batch_trials,
    read_creator_batch_trial_evidence,
    write_creator_batch_trial_evidence,
)

RECORDED_AT = datetime(2026, 8, 22, tzinfo=UTC)


def _trial(run_id: str, decision: str = "rejected") -> CreatorBatchTrial:
    return CreatorBatchTrial(
        research_run_id=run_id,
        decision=decision,
        reason_codes=("schema_rejected",),
    )


def test_trial_evidence_round_trips_and_conflicting_write_is_rejected(tmp_path: Path) -> None:
    evidence = build_creator_batch_trial_evidence(_trial("run-one"), recorded_at=RECORDED_AT)
    path = tmp_path / "run-one.json"

    assert write_creator_batch_trial_evidence(path, evidence) == evidence
    assert read_creator_batch_trial_evidence(path) == evidence
    assert write_creator_batch_trial_evidence(path, evidence) == evidence

    changed = build_creator_batch_trial_evidence(
        CreatorBatchTrial(
            research_run_id="run-one",
            decision="rejected",
            reason_codes=("provider_error",),
        ),
        recorded_at=RECORDED_AT,
    )
    with pytest.raises(DomainViolation, match="immutable"):
        write_creator_batch_trial_evidence(path, changed)


def test_batch_trial_persistence_keeps_order_and_writes_all_trials(tmp_path: Path) -> None:
    result = CreatorBatchResult(trials=(_trial("run-one"), _trial("run-two")))

    persisted = persist_creator_batch_trials(result, root=tmp_path, recorded_at=RECORDED_AT)

    assert len(persisted) == 2
    assert [item.trial.research_run_id for item in persisted] == ["run-one", "run-two"]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "trial-0000-run-one.json",
        "trial-0001-run-two.json",
    ]
