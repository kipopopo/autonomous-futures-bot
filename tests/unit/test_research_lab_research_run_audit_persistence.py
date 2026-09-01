from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research_lab.model_audit import ModelCallAudit
from autonomous_futures.research_lab.model_policy import (
    LLMRolePolicy,
    ResearchModelPolicy,
    build_research_model_policy,
)
from autonomous_futures.research_lab.research_run_audit import (
    ResearchRunAuditEnvelope,
    build_research_run_audit_envelope,
)
from autonomous_futures.research_lab.research_run_audit_persistence import (
    read_research_run_audit_envelope,
    write_research_run_audit_envelope,
)


def _policy() -> ResearchModelPolicy:
    return build_research_model_policy(
        policy_id="research-model-policy-v1",
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="hypothesis_generator",
                provider="google_ai_studio",
                model_id="gemma-4-26b-a4b-it",
                temperature=Decimal("0.20"),
                max_output_tokens=800,
                max_requests_per_batch=4,
                max_retries=0,
            ),
        ),
    )


def _envelope() -> ResearchRunAuditEnvelope:
    policy = _policy()
    audit = ModelCallAudit.build(
        research_run_id="research-run-0001",
        call_id="model-call-0001",
        role="hypothesis_generator",
        policy_id=policy.policy_id,
        policy_hash=policy.policy_hash,
        provider="google_ai_studio",
        model_id="gemma-4-26b-a4b-it",
        prompt_template_hash="b" * 64,
        system_policy_version="research-system-policy-v1",
        input_evidence_refs=("dataset-manifest:abc",),
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
    return build_research_run_audit_envelope(
        research_run_id="research-run-0001",
        policy=policy,
        audits=(audit,),
        prepared_at=datetime(2026, 8, 9, tzinfo=UTC),
    )


def test_research_run_audit_persistence_round_trips_verified_envelope(tmp_path: Path) -> None:
    envelope = _envelope()
    path = tmp_path / "research-runs" / "research-run-0001.json"

    assert write_research_run_audit_envelope(path, envelope) == envelope
    assert read_research_run_audit_envelope(path) == envelope


def test_research_run_audit_persistence_is_idempotent_and_write_once(tmp_path: Path) -> None:
    envelope = _envelope()
    path = tmp_path / "research-run-0001.json"

    assert write_research_run_audit_envelope(path, envelope) == envelope
    assert write_research_run_audit_envelope(path, envelope) == envelope

    changed = envelope.model_copy(update={"prepared_at": datetime(2026, 8, 9, 1, tzinfo=UTC)})
    assert changed.envelope_hash == envelope.envelope_hash
    with pytest.raises(DomainViolation, match="immutable"):
        write_research_run_audit_envelope(path, changed)


def test_research_run_audit_reader_rejects_tampered_malformed_and_missing_artifacts(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    path = tmp_path / "research-run-0001.json"
    write_research_run_audit_envelope(path, envelope)
    path.write_text(
        path.read_text(encoding="utf-8").replace(envelope.envelope_hash, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_research_run_audit_envelope(path)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DataQualityError, match="invalid persisted"):
        read_research_run_audit_envelope(malformed)
    with pytest.raises(FileNotFoundError):
        read_research_run_audit_envelope(tmp_path / "missing.json")


def test_research_run_audit_writer_rejects_hash_mismatch_before_filesystem_work(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    path = tmp_path / "new" / "research-run-0001.json"
    invalid = envelope.model_copy(update={"envelope_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="hash mismatch"):
        write_research_run_audit_envelope(path, invalid)
    assert not path.parent.exists()


def test_research_run_audit_writer_cleans_temp_file_on_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = _envelope()
    path = tmp_path / "research-run-0001.json"

    def fail_link(source: Path, destination: Path) -> None:
        raise OSError("link failed")

    monkeypatch.setattr(
        "autonomous_futures.research_lab.research_run_audit_persistence.os.link", fail_link
    )

    with pytest.raises(OSError, match="link failed"):
        write_research_run_audit_envelope(path, envelope)
    assert not path.exists()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))
