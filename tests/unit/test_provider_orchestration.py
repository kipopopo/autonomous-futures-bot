"""Unit and integration test suite for supported provider orchestration (R1)."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.autonomy_contracts import (
    FailureMemoryEntry,
    build_failure_memory_entry,
    read_failure_learning_artifact,
    read_research_plan,
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
from autonomous_futures.research_lab.model_policy import (
    LLMRolePolicy,
    ResearchModelPolicy,
    build_research_model_policy,
)
from autonomous_futures.research_lab.research_run_audit_persistence import (
    read_research_run_audit_envelope,
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
