import json
from datetime import UTC, datetime
from hashlib import sha256
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


def test_batch_trial_persistence_round_trips_safe_schema_diagnostics(tmp_path: Path) -> None:
    trial = CreatorBatchTrial(
        research_run_id="run-diagnostics",
        decision="rejected",
        reason_codes=("schema_rejected",),
        schema_diagnostics=("strategy.entry:missing",),
    )
    evidence = build_creator_batch_trial_evidence(trial, recorded_at=RECORDED_AT)

    persisted = write_creator_batch_trial_evidence(tmp_path / "diagnostics.json", evidence)

    assert persisted.trial.schema_diagnostics == ("strategy.entry:missing",)
    assert read_creator_batch_trial_evidence(tmp_path / "diagnostics.json").trial == trial


def test_batch_trial_persistence_round_trips_provider_metadata_and_detects_tampering(
    tmp_path: Path,
) -> None:
    trial = CreatorBatchTrial(
        research_run_id="run-provider",
        decision="rejected",
        reason_codes=("provider_payload_invalid",),
        provider_metadata={
            "content_sha256": "c" * 64,
            "finish_reason": "length",
            "status_code": 200,
        },
    )
    path = tmp_path / "provider.json"
    evidence = build_creator_batch_trial_evidence(trial, recorded_at=RECORDED_AT)

    persisted = write_creator_batch_trial_evidence(path, evidence)

    assert persisted.trial.provider_metadata == trial.provider_metadata
    assert read_creator_batch_trial_evidence(path).trial == trial

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["trial"]["provider_metadata"]["status_code"] = 500
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_creator_batch_trial_evidence(path)


def test_legacy_trial_evidence_without_schema_diagnostics_remains_readable(tmp_path: Path) -> None:
    evidence = build_creator_batch_trial_evidence(_trial("run-legacy"), recorded_at=RECORDED_AT)
    payload = evidence.model_dump(mode="json")
    payload["trial"].pop("schema_diagnostics")
    payload["trial"].pop("provider_metadata", None)
    hash_payload = {
        key: value for key, value in payload.items() if key not in {"recorded_at", "evidence_hash"}
    }
    payload["evidence_hash"] = sha256(
        json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_creator_batch_trial_evidence(path) == evidence
