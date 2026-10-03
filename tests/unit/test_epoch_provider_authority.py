"""Synthetic operator permit fixtures; no credentials or network calls."""

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

import autonomous_futures.research.creator_epoch as epoch
import scripts.run_autonomous_cycle as cli
from autonomous_futures.domain.errors import DomainViolation


def _permit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    journal = tmp_path / "journal.sqlite3"
    control = tmp_path / "control.sqlite3"
    pin = tmp_path / "checkpoint.json"
    permit = tmp_path / "permit.json"
    checkpoint = epoch.create_creator_epoch(
        journal, epoch_id="epoch-provider-test", policy_hash="c" * 64
    )
    epoch.create_creator_epoch_control(control, journal, checkpoint)
    pin.write_text(checkpoint.model_dump_json(), encoding="utf-8")
    payload = {
        "cycle_id": "cycle-provider-test",
        "checkpoint": checkpoint.model_dump(mode="json"),
        "journal": str(journal.resolve()),
        "control": str(control.resolve()),
        "checkpoint_file": str(pin.resolve()),
        "ledger_path": str((tmp_path / "ledger.sqlite3").resolve()),
        "lifecycle_path": None,
        "writer_uid": 1000,
        "provider": "google_ai_studio",
        "model": "gemma-4-31b-it",
        "bundle_hash": "a" * 64,
        "dataset_registry_hash": "b" * 64,
        "candidate_artifact_hash": "d" * 64,
        "expires_at": "2099-01-01T00:00:00Z",
        "critic_calls": 1,
        "creator_calls": 1,
    }
    permit.write_text(json.dumps(payload), encoding="utf-8")
    original = Path.lstat

    def protected_metadata(path):
        metadata = original(path)
        values = list(metadata)
        values[0] = (stat.S_IFDIR | 0o755) if path.is_dir() else (stat.S_IFREG | 0o644)
        values[4] = 1000 if path in (journal, control) else 0
        return os.stat_result(values)

    monkeypatch.setattr(Path, "lstat", protected_metadata)
    original_fstat = os.fstat

    def protected_descriptor(descriptor):
        values = list(original_fstat(descriptor))
        values[0] = stat.S_IFREG | 0o644
        values[4] = 0
        return os.stat_result(values)

    monkeypatch.setattr(os, "fstat", protected_descriptor)
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    return journal, control, pin, permit, payload


def test_epoch_provider_requires_independent_protected_permit(tmp_path, monkeypatch):
    journal, control, pin, permit, payload = _permit(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    authority = epoch.read_creator_epoch_provider_permit(
        permit,
        journal=journal,
        control=control,
        checkpoint_file=pin,
        cycle_id=payload["cycle_id"],
        provider=payload["provider"],
        model=payload["model"],
        bundle_hash=payload["bundle_hash"],
        dataset_registry_hash=payload["dataset_registry_hash"],
        now=datetime(2026, 10, 3, tzinfo=UTC),
        ledger_path=Path(payload["ledger_path"]),
    )
    assert authority.checkpoint == epoch.read_creator_epoch_configuration(journal, control, pin)
    assert authority.candidate_artifact_hash == payload["candidate_artifact_hash"]
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    with pytest.raises(DomainViolation):
        epoch.read_creator_epoch_provider_permit(
            permit,
            journal=journal,
            control=control,
            checkpoint_file=pin,
            cycle_id="cycle-other",
            provider=payload["provider"],
            model=payload["model"],
            bundle_hash=payload["bundle_hash"],
            dataset_registry_hash=payload["dataset_registry_hash"],
            now=datetime(2026, 10, 3, tzinfo=UTC),
            ledger_path=Path(payload["ledger_path"]),
        )


def test_epoch_provider_reservation_revalidates_the_protected_grant(tmp_path, monkeypatch):
    journal, control, pin, permit_file, payload = _permit(tmp_path, monkeypatch)
    constructed = epoch.CreatorEpochProviderPermit.model_validate_json(json.dumps(payload))
    permit_file.unlink()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(DomainViolation):
        epoch.reserve_creator_epoch_provider_permit(constructed, permit_path=permit_file)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_epoch_provider_budget_is_consumed_once_before_credentials(tmp_path, monkeypatch):
    journal, control, pin, permit_file, payload = _permit(tmp_path, monkeypatch)
    permit = epoch.read_creator_epoch_provider_permit(
        permit_file,
        journal=journal,
        control=control,
        checkpoint_file=pin,
        cycle_id=payload["cycle_id"],
        provider=payload["provider"],
        model=payload["model"],
        bundle_hash=payload["bundle_hash"],
        dataset_registry_hash=payload["dataset_registry_hash"],
        ledger_path=Path(payload["ledger_path"]),
    )
    if os.name == "nt":
        # Windows cannot open directory fsync descriptors; Linux CI uses the real directory.
        original_open = os.open

        def open_with_directory_descriptor(path, flags, *args, **kwargs):
            if Path(path).is_dir():
                return original_open(journal, os.O_RDWR)
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", open_with_directory_descriptor)
    epoch.reserve_creator_epoch_provider_permit(permit, permit_path=permit_file)
    files = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    record = json.loads(files[f".provider-{permit.cycle_id}.reserved"])
    assert record["status"] == "reserved_before_credentials"
    with pytest.raises(DomainViolation, match="already reserved"):
        epoch.reserve_creator_epoch_provider_permit(permit, permit_path=permit_file)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == files


@pytest.mark.parametrize("fault", ["descriptor", "naive_time"])
def test_epoch_provider_rejects_unprotected_open_descriptor(tmp_path, monkeypatch, fault):
    journal, control, pin, permit_file, payload = _permit(tmp_path, monkeypatch)
    original_fstat = os.fstat

    def replaced_descriptor(descriptor):
        values = list(original_fstat(descriptor))
        values[4] = 1001
        return os.stat_result(values)

    if fault == "descriptor":
        monkeypatch.setattr(os, "fstat", replaced_descriptor)
    with pytest.raises(DomainViolation):
        epoch.read_creator_epoch_provider_permit(
            permit_file,
            journal=journal,
            control=control,
            checkpoint_file=pin,
            cycle_id=payload["cycle_id"],
            provider=payload["provider"],
            model=payload["model"],
            bundle_hash=payload["bundle_hash"],
            dataset_registry_hash=payload["dataset_registry_hash"],
            now=datetime(2026, 10, 3) if fault == "naive_time" else None,
            ledger_path=Path(payload["ledger_path"]),
        )


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "control_after_critic",
        "permit_after_critic",
        "permit_after_creator",
        "seed_hash",
        "ledger_scope",
        "expired",
        "writer",
        "writable_parent",
        "partial",
        "acceptance_failure",
        "credential_failure",
    ],
)
def test_epoch_google_cli_reserves_before_persistence_without_legacy_bypass(
    tmp_path, monkeypatch, fault
):
    from autonomous_futures.pipeline import autonomous_cycle as pipeline
    from autonomous_futures.research.creator_artifacts import (
        read_creator_candidate_artifact,
        write_creator_candidate_artifact,
    )
    from tests.integration.test_run_autonomous_cycle_cli import _init_test_ledger
    from tests.unit.test_autonomous_cycle import _build_test_candidate, _make_cached_window

    journal, control, pin, permit_file, payload = _permit(tmp_path, monkeypatch)
    candidate = _build_test_candidate("cand-provider-seed")
    candidate_file = tmp_path / "seed.json"
    write_creator_candidate_artifact(candidate_file, candidate)
    payload["candidate_artifact_hash"] = candidate.artifact_hash
    if fault == "seed_hash":
        payload["candidate_artifact_hash"] = "e" * 64
    if fault == "ledger_scope":
        payload["ledger_path"] = str((tmp_path / "different-ledger.sqlite3").resolve())
    if fault == "expired":
        payload["expires_at"] = "2020-01-01T00:00:00Z"
    permit_file.write_text(json.dumps(payload), encoding="utf-8")
    ledger = tmp_path / "ledger.sqlite3"
    _init_test_ledger(ledger, candidate)
    calls = []
    marker = journal.parent / f".provider-{payload['cycle_id']}.reserved"

    def credential(**kwargs):
        assert marker.is_file()
        calls.append("credential")
        if fault == "credential_failure":
            raise cli.MissingCredentialsError("Synthetic missing credential")
        return "fixture-only-not-a-real-key"

    monkeypatch.setattr(cli, "resolve_credential", credential)
    monkeypatch.setattr(cli, "load_and_slice_windows", lambda *a, **kw: (_make_cached_window(),))
    feedback = cli.extract_paper_feedback(
        ledger_path=ledger,
        symbol="BTCUSDT",
        candidate_artifact_path=candidate_file,
        policy=cli.PaperQualificationPolicy(policy_id="paper-policy-cli-001"),
        bundle_hash=payload["bundle_hash"],
        dataset_registry_hash=payload["dataset_registry_hash"],
    )
    assert feedback is not None

    def handler(request):
        assert marker.is_file()
        if calls == ["credential"]:
            calls.append("critic")
            response = {
                "review_id": "review-provider-test",
                "research_run_id": f"run-critic-{payload['cycle_id']}",
                "candidate_id": candidate.candidate_id,
                "decision": "revise",
                "failure_reason_codes": list(feedback.failure_reason_codes),
                "revision_actions": ["adjust_stop_multiplier"],
            }
            if fault == "control_after_critic":
                control.unlink()
            if fault == "permit_after_critic":
                permit_file.unlink()
        else:
            assert calls == ["credential", "critic"]
            calls.append("creator")
            response = {
                "proposal_id": "proposal-provider-test",
                "research_run_id": f"run-creator-{payload['cycle_id']}",
                "hypothesis": "Synthetic permit integration",
                "expected_regime": "test",
                "novelty_reason": "Synthetic revised stop",
                "strategy": _build_test_candidate("cand-revised", "2.0").strategy.model_dump(
                    mode="json"
                ),
            }
            response["strategy"]["risk"] = {
                key: float(value) for key, value in response["strategy"]["risk"].items()
            }
            if fault == "permit_after_creator":
                permit_file.unlink()
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response)}}]
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        cli.httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler))
    )
    original_write = pipeline.write_creator_candidate_artifact

    def accepted_before_write(path, artifact):
        current = epoch.read_creator_epoch_control(
            control, journal, epoch.CreatorEpochCheckpoint.model_validate(payload["checkpoint"])
        )
        assert current.sequence == 1
        epoch.require_creator_epoch_candidate(journal, current, artifact)
        assert not path.exists()
        calls.append("persist")
        return original_write(path, artifact)

    monkeypatch.setattr(pipeline, "write_creator_candidate_artifact", accepted_before_write)
    if fault == "writer":
        monkeypatch.setattr(os, "geteuid", lambda: 1001)
    if fault == "writable_parent":
        original_lstat = Path.lstat

        def writable_parent(path):
            values = list(original_lstat(path))
            if path == tmp_path:
                values[0] |= stat.S_IWGRP
            return os.stat_result(values)

        monkeypatch.setattr(Path, "lstat", writable_parent)
    if fault == "acceptance_failure":
        import sqlite3

        with sqlite3.connect(control) as conn:
            conn.execute(
                "CREATE TRIGGER reject_head BEFORE UPDATE ON epoch_control "
                "BEGIN SELECT RAISE(ABORT, 'synthetic rejection'); END"
            )
    if os.name == "nt":
        original_open = os.open
        monkeypatch.setattr(
            os,
            "open",
            lambda p, flags, *a, **kw: (
                original_open(journal, os.O_RDWR)
                if Path(p).is_dir()
                else original_open(p, flags, *a, **kw)
            ),
        )
    output = tmp_path / "output"
    argv = [
        "--symbol",
        "BTCUSDT",
        "--provider",
        "google_ai_studio",
        "--model",
        payload["model"],
        "--cycle-id",
        payload["cycle_id"],
        "--ledger-db",
        str(ledger),
        "--candidate-path",
        str(candidate_file),
        "--bundle-hash",
        payload["bundle_hash"],
        "--dataset-registry-hash",
        payload["dataset_registry_hash"],
        "--output-dir",
        str(output),
        "--creator-epoch-journal",
        str(journal),
        "--creator-epoch-control",
        str(control),
        "--creator-epoch-checkpoint",
        str(pin),
        "--creator-epoch-provider-permit",
        str(permit_file),
    ]
    if fault == "partial":
        index = argv.index("--creator-epoch-control")
        del argv[index : index + 2]
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    exit_code = cli.main(argv)
    if fault in ("seed_hash", "ledger_scope", "expired", "writer", "writable_parent", "partial"):
        assert exit_code == 3
        assert calls == []
        assert not output.exists()
        assert not marker.exists()
        assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before
        return
    if fault in ("credential_failure", "acceptance_failure", "permit_after_creator"):
        assert exit_code == 3
        assert calls == (
            ["credential"] if fault == "credential_failure" else ["credential", "critic", "creator"]
        )
        assert marker.exists()
        assert not (output / "candidates").exists()
        assert not (output / "evidence" / "creator").exists()
        assert (
            epoch.read_creator_epoch_control(
                control, journal, epoch.CreatorEpochCheckpoint.model_validate(payload["checkpoint"])
            ).sequence
            == 0
        )
        assert cli.main(argv) == 3
        return
    if fault in ("control_after_critic", "permit_after_critic"):
        assert exit_code == 3
        assert calls == ["credential", "critic"]
        assert not (output / "candidates").exists()
        assert not (output / "evidence" / "creator").exists()
        return
    assert exit_code == 0
    result = json.loads((output / "autonomous-cycle-result.json").read_text())
    assert result["cycle_status"] == "completed_unadmitted"
    assert result["admission_decision"] is None
    assert result["stop_reasons"] == ["paper_admission_not_authorized"]
    assert not (tmp_path / "candidate_registry.json").exists()
    assert calls == ["credential", "critic", "creator", "persist"]
    artifacts = list((output / "candidates").glob("*.json"))
    assert len(artifacts) == 1
    artifact = read_creator_candidate_artifact(artifacts[0])
    current = epoch.read_creator_epoch_control(
        control, journal, epoch.CreatorEpochCheckpoint.model_validate(payload["checkpoint"])
    )
    epoch.require_creator_epoch_candidate(journal, current, artifact)
    # The same grant cannot spend again after acceptance or a failed downstream step.
    assert cli.main(argv) == 3
    assert calls == ["credential", "critic", "creator", "persist"]
