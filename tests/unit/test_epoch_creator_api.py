"""Read-only Creator API must not label quarantined epoch evidence verified."""

from pathlib import Path

import pytest

from autonomous_futures.api import create_app
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import (
    build_creator_candidate_registry,
    write_creator_candidate_artifact,
    write_creator_candidate_registry,
)
from autonomous_futures.research.creator_epoch import (
    append_creator_epoch_acceptance,
    create_creator_epoch,
    create_creator_epoch_control,
)
from autonomous_futures.research.creator_proposals import (
    build_candidate_from_proposal,
    parse_creator_proposal,
)
from autonomous_futures.research.qualification_artifacts import (
    build_walk_forward_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from tests.unit.test_creator_api import _request
from tests.unit.test_creator_proposals import BUNDLE_HASH, CREATED_AT, REGISTRY_HASH, _payload
from tests.unit.test_qualification_api import _aggregation, _policy


@pytest.mark.parametrize(
    "mode",
    [
        "accepted",
        "accepted_environment",
        "legacy",
        "unaccepted",
        "control_deleted",
        "journal_deleted",
    ],
)
def test_configured_creator_api_checks_epoch_on_every_read(
    tmp_path: Path, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal, control, pin = (
        tmp_path / name for name in ("journal.sqlite3", "control.sqlite3", "pin.json")
    )
    checkpoint = create_creator_epoch(journal, epoch_id="epoch-api", policy_hash="c" * 64)
    create_creator_epoch_control(control, journal, checkpoint)
    pin.write_text(checkpoint.model_dump_json(), encoding="utf-8")
    payload = _payload()
    assert isinstance(payload["strategy"], dict)
    payload["strategy"]["universe"]["symbols"] = ["BTCUSDT"]
    proposal = parse_creator_proposal(
        payload, epoch_id=None if mode == "legacy" else checkpoint.epoch_id
    )
    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-api-epoch",
        research_seed=1,
        created_at=CREATED_AT,
    )
    if mode not in ("legacy", "unaccepted"):
        outcome = proposal.build_outcome(
            decision="accepted",
            candidate_artifact_hash=candidate.artifact_hash,
            reason_codes=("schema_valid",),
            recorded_at=CREATED_AT,
        )
        append_creator_epoch_acceptance(
            journal, checkpoint, proposal, candidate, outcome, control_path=control
        )
    artifact_path = tmp_path / "candidate.json"
    registry_path = tmp_path / "registry.json"
    write_creator_candidate_artifact(artifact_path, candidate)
    registry = build_creator_candidate_registry(
        ((candidate, "candidate.json"),), created_at=CREATED_AT
    )
    write_creator_candidate_registry(registry_path, registry)
    qualification_root = tmp_path / "qualifications"
    qualification = build_walk_forward_qualification_artifact(
        candidate=candidate,
        aggregation=_aggregation(),
        policy=_policy(),
        evaluator_run_id="epoch-api-qualification",
        evaluator_version="test-only",
        evaluated_at=CREATED_AT,
    )
    write_creator_candidate_qualification_artifact(
        qualification_root / f"{candidate.candidate_id}.json", qualification
    )
    pins = {
        "creator_epoch_journal": journal,
        "creator_epoch_control": control,
        "creator_epoch_checkpoint": pin,
    }
    if mode == "accepted_environment":
        for name, path in pins.items():
            monkeypatch.setenv(f"AFBOT_{name.upper()}", str(path))
        pins = {}
    app = create_app(
        creator_candidate_registry_path=registry_path,
        creator_candidate_artifact_root=tmp_path,
        qualification_artifact_root=qualification_root,
        **pins,
    )
    if mode == "control_deleted":
        control.unlink()
    if mode == "journal_deleted":
        journal.unlink()
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    for route in (
        "/api/v1/creator/registry",
        "/api/v1/creator/qualifications",
        f"/api/v1/creator/qualifications/{candidate.candidate_id}",
    ):
        response = _request(app, "GET", route)
        expected = 200 if mode in ("accepted", "accepted_environment") else 503
        assert response.status_code == expected
        if mode in ("accepted", "accepted_environment"):
            assert response.json()["verified"] is True
            if "/qualifications/" in route:
                assert response.json()["artifact"]["execution_authority"] is False
        else:
            assert response.json() == {
                "detail": "creator candidate registry integrity verification failed"
            }
        assert _request(app, "POST", route).status_code == 405
    assert {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    } == before


def test_creator_api_rejects_partial_epoch_configuration_before_outputs(tmp_path: Path) -> None:
    with pytest.raises(DomainViolation, match="requires journal, control and pinned checkpoint"):
        create_app(creator_epoch_journal=tmp_path / "missing.sqlite3")
    assert not tuple(tmp_path.iterdir())


def test_creator_api_rejects_partial_operator_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AFBOT_CREATOR_EPOCH_JOURNAL", str(tmp_path / "missing.sqlite3"))
    monkeypatch.delenv("AFBOT_CREATOR_EPOCH_CONTROL", raising=False)
    monkeypatch.delenv("AFBOT_CREATOR_EPOCH_CHECKPOINT", raising=False)
    with pytest.raises(DomainViolation, match="requires journal, control and pinned checkpoint"):
        create_app()
    assert not tuple(tmp_path.iterdir())
