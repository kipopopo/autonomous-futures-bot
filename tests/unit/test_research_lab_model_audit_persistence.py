from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.model_audit import (
    ModelCallAudit,
    read_model_call_audit,
    write_model_call_audit,
)


def _audit() -> ModelCallAudit:
    return ModelCallAudit.build(
        research_run_id="research-run-0001",
        call_id="model-call-0001",
        role="hypothesis_generator",
        policy_id="research-model-policy-v1",
        policy_hash="a" * 64,
        provider="opencode",
        model_id="x-preview-f-free",
        prompt_template_hash="b" * 64,
        system_policy_version="research-system-policy-v1",
        input_evidence_refs=("dataset-manifest:abc", "prior-failure:def"),
        output_schema_id="hypothesis-v1",
        outcome="succeeded",
        output_hash="c" * 64,
        input_tokens=100,
        output_tokens=200,
        declared_price_tier="free",
        rate_limit_delay_ms=0,
        retry_count=0,
        error_code=None,
        observed_at=datetime(2026, 8, 9, tzinfo=UTC),
    )


def test_model_call_audit_persistence_round_trips_verified_evidence(tmp_path: Path) -> None:
    audit = _audit()
    path = tmp_path / "audits" / "model-call-0001.json"

    assert write_model_call_audit(path, audit) == audit
    assert read_model_call_audit(path) == audit


def test_model_call_audit_persistence_is_idempotent_and_write_once(tmp_path: Path) -> None:
    audit = _audit()
    path = tmp_path / "model-call-0001.json"

    assert write_model_call_audit(path, audit) == audit
    assert write_model_call_audit(path, audit) == audit

    changed_observed_at = audit.model_copy(
        update={"observed_at": audit.observed_at + timedelta(hours=1)}
    )
    assert changed_observed_at.audit_hash == audit.audit_hash
    with pytest.raises(DomainViolation, match="immutable"):
        write_model_call_audit(path, changed_observed_at)


def test_model_call_audit_reader_rejects_tampered_hash_as_integrity_failure(
    tmp_path: Path,
) -> None:
    audit = _audit()
    path = tmp_path / "model-call-0001.json"
    write_model_call_audit(path, audit)
    path.write_text(
        path.read_text(encoding="utf-8").replace(audit.audit_hash, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_model_call_audit(path)


def test_model_call_audit_reader_fails_closed_for_malformed_and_missing_artifacts(
    tmp_path: Path,
) -> None:
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(DataQualityError, match="invalid persisted"):
        read_model_call_audit(malformed_path)
    with pytest.raises(FileNotFoundError):
        read_model_call_audit(tmp_path / "missing.json")


def test_model_call_audit_writer_rejects_hash_mismatch_before_filesystem_work(
    tmp_path: Path,
) -> None:
    audit = _audit()
    path = tmp_path / "new" / "model-call-0001.json"
    invalid = audit.model_copy(update={"audit_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="hash mismatch"):
        write_model_call_audit(path, invalid)
    assert not path.parent.exists()


def test_model_call_audit_writer_cleans_temp_file_on_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _audit()
    path = tmp_path / "model-call-0001.json"

    def fail_link(source: Path, destination: Path) -> None:
        raise OSError("link failed")

    monkeypatch.setattr("autonomous_futures.research_lab.model_audit.os.link", fail_link)

    with pytest.raises(OSError, match="link failed"):
        write_model_call_audit(path, audit)
    assert not path.exists()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))
