"""Unit and integration test suite for supported provider orchestration (R1)."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.autonomy_contracts import (
    FailureLearningArtifact,
    FailureMemoryEntry,
    build_failure_memory_entry,
    read_failure_learning_artifact,
    read_research_plan,
    write_failure_memory_entry,
)
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.google_ai_studio_provider import (
    ProviderTransportError,
)
from autonomous_futures.research.provider_orchestration import (
    ProviderOrchestrationConfig,
    execute_provider_orchestration,
)
from autonomous_futures.research.qualification_artifacts import QualificationGateResult
from autonomous_futures.research_lab.model_audit import ModelCallAudit
from autonomous_futures.research_lab.model_policy import (
    LLMRolePolicy,
    ResearchModelPolicy,
    build_research_model_policy,
)
from autonomous_futures.research_lab.research_run_audit import (
    build_research_run_audit_envelope,
)
from autonomous_futures.research_lab.research_run_audit_persistence import (
    read_research_run_audit_envelope,
    write_research_run_audit_envelope,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_autonomy_provider import main as cli_main  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


def _policy(role: str = "failure_analyst") -> ResearchModelPolicy:
    return build_research_model_policy(
        policy_id="policy-orch-test-001",
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="failure_analyst",
                provider="google_ai_studio",
                model_id="gemma-4-26b-a4b-it",
                temperature=Decimal("0.20"),
                max_output_tokens=2048,
                max_requests_per_batch=1,
                max_retries=0,
            ),
            LLMRolePolicy(
                role="hypothesis_generator",
                provider="google_ai_studio",
                model_id="gemma-4-31b-it",
                temperature=Decimal("0.10"),
                max_output_tokens=2048,
                max_requests_per_batch=1,
                max_retries=0,
            ),
        ),
    )


def _feedback() -> CreatorQualificationFailureFeedback:
    return CreatorQualificationFailureFeedback(
        candidate_id="cand-orch-seed-001",
        candidate_artifact_hash=HASH_A,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_hash=HASH_C,
        qualification_policy_id="policy-orch-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.75"),
                threshold=Decimal("1.05"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )


def _memory() -> FailureMemoryEntry:
    return build_failure_memory_entry(
        base_run_id="base-orch-001",
        source_type="seed_feedback",
        source_id="seed-feedback-orch-001",
        sequence=0,
        feedback=_feedback(),
        cycle_id=None,
        cycle_hash=None,
        recorded_at=NOW,
    )


def test_learner_accepted_produces_durable_artifact_and_audit_readback_verified(
    tmp_path: Path,
) -> None:
    called = 0

    def mock_transport(_req: object) -> Mapping[str, object]:
        nonlocal called
        called += 1
        return {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic", "feature_set"],
        }

    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-learner-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    result = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=mock_transport,
        now=NOW,
    )

    assert result.status == "succeeded"
    assert result.decision == "accepted"
    assert result.readback_verified is True
    assert result.requests_consumed == 1
    assert called == 1
    assert result.learning_artifact is not None

    # Verify physical file existence and readback integrity
    artifact_path = (
        tmp_path / "evidence" / "learning" / f"{result.learning_artifact.learning_id}.json"
    )
    assert artifact_path.is_file()
    disk_artifact = read_failure_learning_artifact(artifact_path)
    assert disk_artifact == result.learning_artifact

    # Verify audit envelope existence and readback integrity
    assert result.audit_envelope is not None
    envelope_path = (
        tmp_path / "evidence" / "audits" / f"envelope-{result.audit_envelope.envelope_hash}.json"
    )
    assert envelope_path.is_file()
    disk_envelope = read_research_run_audit_envelope(envelope_path)
    assert disk_envelope == result.audit_envelope
    assert disk_envelope.audits[0].outcome == "succeeded"


def test_planner_accepted_produces_durable_artifact_and_audit_readback_verified(
    tmp_path: Path,
) -> None:
    called = 0

    def mock_transport(_req: object) -> Mapping[str, object]:
        nonlocal called
        called += 1
        return {
            "hypothesis": "Apply volume confirmation and volatility breakout on trend regime.",
            "expected_regime": "volatile_trend",
            "strategy_family": "volume_confirmed_momentum",
            "novelty_dimensions": ["entry_logic"],
            "falsification_criteria": ["reject when OOS profit factor drops below 1.05"],
        }

    # First produce a valid learning artifact
    learner_config = ProviderOrchestrationConfig(
        research_run_id="run-orch-learner-prep-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    learner_result = execute_provider_orchestration(
        config=learner_config,
        failure_memory=(_memory(),),
        transport=lambda _r: {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic"],
        },
        now=NOW,
    )
    assert learner_result.learning_artifact is not None

    planner_config = ProviderOrchestrationConfig(
        research_run_id="run-orch-planner-001",
        base_run_id="base-orch-001",
        role="hypothesis_generator",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
        cycle_id="cycle-btcusdt-001",
    )
    result = execute_provider_orchestration(
        config=planner_config,
        failure_memory=(_memory(),),
        learning_artifact=learner_result.learning_artifact,
        transport=mock_transport,
        now=NOW,
    )

    assert result.status == "succeeded"
    assert result.decision == "accepted"
    assert result.readback_verified is True
    assert result.research_plan is not None
    assert called == 1

    plan_path = tmp_path / "evidence" / "plans" / f"{result.research_plan.plan_id}.json"
    assert plan_path.is_file()
    disk_plan = read_research_plan(plan_path)
    assert disk_plan == result.research_plan


def test_learner_rejected_preserves_schema_diagnostics_honestly_without_schema_relaxation(
    tmp_path: Path,
) -> None:
    def invalid_transport(_req: object) -> Mapping[str, object]:
        return {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": [],  # too short: min_length=1
            "recommended_novelty_dimensions": ["entry_logic"],
        }

    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-rejected-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    result = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=invalid_transport,
        now=NOW,
    )

    assert result.status == "rejected"
    assert result.decision == "rejected"
    assert result.learning_artifact is None
    assert "learned_constraints:too_short" in result.schema_diagnostics

    # Durable audit envelope must still be persisted with schema_rejected outcome
    assert result.audit_envelope is not None
    envelope_path = (
        tmp_path / "evidence" / "audits" / f"envelope-{result.audit_envelope.envelope_hash}.json"
    )
    assert envelope_path.is_file()
    disk_envelope = read_research_run_audit_envelope(envelope_path)
    assert disk_envelope.audits[0].outcome == "schema_rejected"


def test_provider_failure_persists_sanitized_audit_without_leaking_secret(tmp_path: Path) -> None:
    secret_text = "AIzaSySecretTokenMustNotAppearInAuditRecord12345"

    def failing_transport(_req: object) -> Mapping[str, object]:
        raise ProviderTransportError(
            "http_503_service_unavailable",
            status_code=503,
            error_reason=f"bad: {secret_text}",
        )

    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-error-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    result = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=failing_transport,
        now=NOW,
    )

    assert result.status == "rejected"
    assert result.decision == "rejected"
    assert result.audit_envelope is not None
    assert result.audit_envelope.audits[0].outcome == "provider_error"
    assert result.audit_envelope.audits[0].error_code == "provider_error"
    envelope_str = result.audit_envelope.model_dump_json()
    assert secret_text not in envelope_str


def test_restart_reuse_idempotency_without_network_call(tmp_path: Path) -> None:
    called = 0

    def mock_transport(_req: object) -> Mapping[str, object]:
        nonlocal called
        called += 1
        return {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic"],
        }

    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-reuse-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    first = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=mock_transport,
        now=NOW,
    )
    assert first.status == "succeeded"
    assert first.reused_existing is False
    assert called == 1

    # Second execution must detect existing valid checkpoint and reuse without calling transport
    second = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=mock_transport,
        now=NOW,
    )
    assert second.status == "reused_checkpoint"
    assert second.reused_existing is True
    assert second.requests_consumed == 0
    assert called == 1  # transport was NOT called again


def test_tampered_checkpoint_prior_to_network_call_rejects(tmp_path: Path) -> None:
    called = 0

    def mock_transport(_req: object) -> Mapping[str, object]:
        nonlocal called
        called += 1
        return {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic"],
        }

    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-tampered-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    first = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=mock_transport,
        now=NOW,
    )
    assert first.status == "succeeded"
    assert first.learning_artifact is not None

    # Tamper with the persisted learning artifact on disk
    artifact_path = (
        tmp_path / "evidence" / "learning" / f"{first.learning_artifact.learning_id}.json"
    )
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    data["learning_hash"] = "0" * 64
    artifact_path.write_text(json.dumps(data), encoding="utf-8")

    # Second run must reject prior to calling network
    with pytest.raises(DomainViolation, match="tampered or corrupted"):
        execute_provider_orchestration(
            config=config,
            failure_memory=(_memory(),),
            transport=mock_transport,
            now=NOW,
        )
    assert called == 1  # transport was NOT called on tampered check


def test_budget_exhaustion_rejects_prior_to_network_call(tmp_path: Path) -> None:
    called = 0

    def mock_transport(_req: object) -> Mapping[str, object]:
        nonlocal called
        called += 1
        return {}

    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-budget-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=0,  # exhausted
        execute=True,
    )
    result = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=mock_transport,
        now=NOW,
    )

    assert result.status == "budget_exhausted"
    assert result.decision == "rejected"
    assert called == 0  # transport was never called
    assert result.audit_envelope is not None
    assert result.audit_envelope.audits[0].outcome == "budget_rejected"


def test_zero_network_preflight_dry_run(tmp_path: Path) -> None:
    called = 0

    def mock_transport(_req: object) -> Mapping[str, object]:
        nonlocal called
        called += 1
        return {}

    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-dryrun-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=False,  # dry-run
    )
    result = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=mock_transport,
        now=NOW,
    )

    assert result.status == "prepared"
    assert result.decision == "prepared"
    assert called == 0


def test_missing_credentials_preflight_fails_closed_safely(tmp_path: Path) -> None:
    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-missing-creds-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    # With empty env and missing repo env file
    result = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=None,  # triggers real credential resolution
        env={},
        repo_env_path=tmp_path / "non_existent.env",
        now=NOW,
    )

    assert result.status == "blocked"
    assert result.decision == "rejected"
    assert "missing_credentials" in result.reason_codes
    assert result.audit_envelope is not None
    assert result.audit_envelope.audits[0].outcome == "provider_error"
    assert result.audit_envelope.audits[0].error_code == "missing_credentials"


def test_cli_forbidden_credential_flag_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_main(["--api-key", "secret123", "--role", "failure_analyst"])
    assert code == 2
    err = capsys.readouterr().err
    assert "forbidden" in err.lower()


def test_cli_preflight_dry_run_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(_policy().model_dump_json(), encoding="utf-8")

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(_memory().model_dump_json(), encoding="utf-8")

    evidence_root = tmp_path / "evidence"

    code = cli_main(
        [
            "--policy-file",
            str(policy_path),
            "--role",
            "failure_analyst",
            "--research-run-id",
            "run-cli-test-001",
            "--symbol",
            "BTCUSDT",
            "--evidence-root",
            str(evidence_root),
            "--failure-memory-file",
            str(memory_path),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["status"] == "prepared"
    assert result["decision"] == "prepared"


def test_orphan_artifact_without_audit_envelope_rejects(tmp_path: Path) -> None:
    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-orphan-art-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    # Execute valid run to produce durable artifact and audit
    first = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=lambda _req: {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic"],
        },
        now=NOW,
    )
    assert first.status == "succeeded"

    # Remove the audit envelope file to create an orphan artifact
    assert first.audit_envelope is not None
    envelope_file = (
        tmp_path / "evidence" / "audits" / f"envelope-{first.audit_envelope.envelope_hash}.json"
    )
    envelope_file.unlink()

    # Next call must detect the orphan artifact and reject prior to network call
    with pytest.raises(DomainViolation, match="partial or orphan checkpoint"):
        execute_provider_orchestration(
            config=config,
            failure_memory=(_memory(),),
            transport=lambda _req: {},
            now=NOW,
        )


def test_orphan_audit_envelope_without_artifact_rejects(tmp_path: Path) -> None:
    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-orphan-env-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    audits_dir = tmp_path / "evidence" / "audits"
    audits_dir.mkdir(parents=True, exist_ok=True)
    audit = ModelCallAudit.build(
        research_run_id=config.research_run_id,
        call_id="call-orphan-001",
        role=config.role,
        policy_id=config.policy.policy_id,
        policy_hash=config.policy.policy_hash,
        provider="google_ai_studio",
        model_id="gemma-4-26b-a4b-it",
        prompt_template_hash="d" * 64,
        system_policy_version="autonomous-research-base-v1",
        input_evidence_refs=(f"failure/{_memory().memory_hash}",),
        output_schema_id="failure-learning-v1",
        outcome="succeeded",
        output_hash="e" * 64,
        input_tokens=None,
        output_tokens=None,
        declared_price_tier="unspecified",
        rate_limit_delay_ms=0,
        retry_count=0,
        error_code=None,
        observed_at=NOW,
    )
    envelope = build_research_run_audit_envelope(
        research_run_id=config.research_run_id,
        policy=config.policy,
        audits=(audit,),
        prepared_at=NOW,
    )
    write_research_run_audit_envelope(
        audits_dir / f"envelope-{envelope.envelope_hash}.json", envelope
    )

    with pytest.raises(DomainViolation, match="partial or orphan checkpoint"):
        execute_provider_orchestration(
            config=config,
            failure_memory=(_memory(),),
            transport=lambda _req: {},
            now=NOW,
        )


def test_replayed_terminal_checkpoint_rejects(tmp_path: Path) -> None:
    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-replay-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    audits_dir = tmp_path / "evidence" / "audits"
    audits_dir.mkdir(parents=True, exist_ok=True)
    audit = ModelCallAudit.build(
        research_run_id=config.research_run_id,
        call_id="call-replay-001",
        role=config.role,
        policy_id=config.policy.policy_id,
        policy_hash=config.policy.policy_hash,
        provider="google_ai_studio",
        model_id="gemma-4-26b-a4b-it",
        prompt_template_hash="d" * 64,
        system_policy_version="autonomous-research-base-v1",
        input_evidence_refs=(f"failure/{_memory().memory_hash}",),
        output_schema_id="failure-learning-v1",
        outcome="schema_rejected",
        output_hash=None,
        input_tokens=None,
        output_tokens=None,
        declared_price_tier="unspecified",
        rate_limit_delay_ms=0,
        retry_count=0,
        error_code="schema_rejected",
        observed_at=NOW,
    )
    envelope = build_research_run_audit_envelope(
        research_run_id=config.research_run_id,
        policy=config.policy,
        audits=(audit,),
        prepared_at=NOW,
    )
    write_research_run_audit_envelope(
        audits_dir / f"envelope-{envelope.envelope_hash}.json", envelope
    )

    with pytest.raises(DomainViolation, match="replayed checkpoint"):
        execute_provider_orchestration(
            config=config,
            failure_memory=(_memory(),),
            transport=lambda _req: {},
            now=NOW,
        )


def test_tampered_checkpoint_filename_mismatch_rejects(tmp_path: Path) -> None:
    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-filename-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    # Execute valid run to produce durable artifact
    first = execute_provider_orchestration(
        config=config,
        failure_memory=(_memory(),),
        transport=lambda _req: {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic"],
        },
        now=NOW,
    )
    assert first.status == "succeeded"
    assert first.learning_artifact is not None

    # Rename the artifact file to a mismatched filename
    learning_dir = tmp_path / "evidence" / "learning"
    real_file = learning_dir / f"{first.learning_artifact.learning_id}.json"
    mismatched_file = learning_dir / "learn-forgedfilenamemismatch001.json"
    real_file.rename(mismatched_file)

    with pytest.raises(DomainViolation, match="tampered checkpoint filename mismatch"):
        execute_provider_orchestration(
            config=config,
            failure_memory=(_memory(),),
            transport=lambda _req: {},
            now=NOW,
        )


def test_storage_failure_during_artifact_or_audit_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import autonomous_futures.research.provider_orchestration as po_mod

    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-storage-fail-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )

    def failing_read_artifact(path: Path) -> FailureLearningArtifact:
        real_artifact = read_failure_learning_artifact(path)
        return real_artifact.model_copy(update={"symbol": "FORGED"})

    monkeypatch.setattr(po_mod, "read_failure_learning_artifact", failing_read_artifact)

    with pytest.raises(DomainViolation, match="storage failure"):
        execute_provider_orchestration(
            config=config,
            failure_memory=(_memory(),),
            transport=lambda _req: {
                "failure_patterns": ["oos_profit_factor_below_threshold"],
                "learned_constraints": ["preserve_all_qualification_gates"],
                "recommended_novelty_dimensions": ["entry_logic"],
            },
            now=NOW,
        )


def test_budget_exhaustion_hypothesis_generator_requires_learning_artifact(tmp_path: Path) -> None:
    """Verify budget exhaustion on hypothesis_generator validates causal inputs first."""
    config = ProviderOrchestrationConfig(
        research_run_id="run-orch-budget-hypo-001",
        base_run_id="base-orch-001",
        role="hypothesis_generator",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=0,
        cycle_id="cycle-btcusdt-001",
        execute=True,
    )
    with pytest.raises(
        DataQualityError, match="hypothesis_generator role requires learning_artifact"
    ):
        execute_provider_orchestration(
            config=config,
            failure_memory=(_memory(),),
            learning_artifact=None,
            now=NOW,
        )


def test_budget_exhaustion_hypothesis_generator_binds_complete_evidence(tmp_path: Path) -> None:
    """Verify hypothesis_generator budget exhaustion binds complete causal evidence refs."""
    # First generate a real learning artifact
    learner_config = ProviderOrchestrationConfig(
        research_run_id="run-orch-learner-for-budget-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    learner_result = execute_provider_orchestration(
        config=learner_config,
        failure_memory=(_memory(),),
        transport=lambda _r: {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic"],
        },
        now=NOW,
    )
    assert learner_result.learning_artifact is not None

    planner_config = ProviderOrchestrationConfig(
        research_run_id="run-orch-planner-budget-001",
        base_run_id="base-orch-001",
        role="hypothesis_generator",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=tmp_path / "evidence",
        policy=_policy(),
        request_budget=0,  # exhausted
        cycle_id="cycle-btcusdt-001",
        execute=True,
    )
    result = execute_provider_orchestration(
        config=planner_config,
        failure_memory=(_memory(),),
        learning_artifact=learner_result.learning_artifact,
        now=NOW,
    )

    assert result.status == "budget_exhausted"
    assert result.decision == "rejected"
    assert result.readback_verified is True
    assert result.audit_envelope is not None
    audit = result.audit_envelope.audits[0]
    assert audit.outcome == "budget_rejected"
    assert audit.output_schema_id == "research-plan-v1"
    # Bound causal inputs must include the learning artifact hash
    assert f"learning/{learner_result.learning_artifact.learning_hash}" in audit.input_evidence_refs


def test_cross_role_checkpoint_collision_rejects(tmp_path: Path) -> None:
    """Verify existing artifact for research_run_id belonging to a different role rejects."""
    evidence_root = tmp_path / "evidence"
    # Create a learning artifact for run-orch-cross-001
    learner_config = ProviderOrchestrationConfig(
        research_run_id="run-orch-cross-001",
        base_run_id="base-orch-001",
        role="failure_analyst",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=evidence_root,
        policy=_policy(),
        request_budget=1,
        execute=True,
    )
    res = execute_provider_orchestration(
        config=learner_config,
        failure_memory=(_memory(),),
        transport=lambda _r: {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic"],
        },
        now=NOW,
    )
    # Remove audit envelope to simulate artifact existing without envelope
    for envelope_file in (evidence_root / "audits").glob("envelope-*.json"):
        envelope_file.unlink()

    # Now attempt to run hypothesis_generator with the SAME research_run_id
    planner_config = ProviderOrchestrationConfig(
        research_run_id="run-orch-cross-001",
        base_run_id="base-orch-001",
        role="hypothesis_generator",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        evidence_root=evidence_root,
        policy=_policy(),
        request_budget=1,
        cycle_id="cycle-btcusdt-001",
        execute=True,
    )
    with pytest.raises(DomainViolation, match="cross-role artifact conflict"):
        execute_provider_orchestration(
            config=planner_config,
            failure_memory=(_memory(),),
            learning_artifact=res.learning_artifact,
            now=NOW,
        )


def test_autonomy_contracts_write_readback_mismatch_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify write_* functions in autonomy_contracts fail-closed on readback mismatch."""
    import autonomous_futures.research.autonomy_contracts as ac_mod

    entry = _memory()
    entry_path = tmp_path / "failure-test.json"

    def corrupted_read_memory(path: Path) -> FailureMemoryEntry:
        real_entry = FailureMemoryEntry.model_validate_json(path.read_text(encoding="utf-8"))
        return real_entry.model_copy(update={"source_id": "CORRUPTED_ID"})

    monkeypatch.setattr(ac_mod, "read_failure_memory_entry", corrupted_read_memory)
    with pytest.raises(DomainViolation, match="failure memory path is immutable"):
        write_failure_memory_entry(entry_path, entry)


def test_cli_runner_rejects_extended_forbidden_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify run_autonomy_provider rejects --secret, --bearer, --binance-api-key, etc."""
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(_policy().model_dump_json(), encoding="utf-8")

    for flag in ("--secret", "--bearer", "--binance-api-key", "--password", "--secret-key"):
        exit_code = cli_main(
            [
                flag,
                "secret_val",
                "--policy-file",
                str(policy_path),
                "--role",
                "failure_analyst",
                "--research-run-id",
                "run-orch-cli-001",
                "--symbol",
                "BTCUSDT",
                "--evidence-root",
                str(tmp_path / "evidence"),
                "--failure-memory-file",
                str(tmp_path / "mem.json"),
            ]
        )
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "forbidden_cli_argument" in captured.err
