"""Prepare-only provider smoke contract tests."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.provider_smoke import (
    ProviderSmokePreparation,
    build_provider_smoke_preparation,
    read_provider_smoke_preparation,
    write_provider_smoke_preparation,
)
from autonomous_futures.research_lab.model_policy import (
    LLMRolePolicy,
    build_research_model_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.prepare_autonomy_provider_smoke import main  # noqa: E402

HASH_A = "a" * 64
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _policy(role: str = "failure_analyst"):
    return build_research_model_policy(
        policy_id="policy-smoke-contract-001",
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role=role,
                provider="google_ai_studio",
                model_id="gemma-4-26b-a4b-it",
                temperature=Decimal("0.20"),
                max_output_tokens=1024,
                max_requests_per_batch=1,
                max_retries=0,
            ),
        ),
    )


def test_build_provider_smoke_preparation_is_non_authorizing() -> None:
    preparation = build_provider_smoke_preparation(
        research_run_id="run-smoke-contract-001",
        role="failure_analyst",
        policy=_policy(),
        input_evidence_refs=(f"failure/{HASH_A}",),
        prepared_at=NOW,
    )

    assert preparation.preparation_id == f"smoke-prep-{preparation.preparation_hash}"
    assert preparation.provider == "google_ai_studio"
    assert preparation.model_id == "gemma-4-26b-a4b-it"
    assert preparation.output_schema_id == "failure-learning-v1"
    assert preparation.request_count == 1
    assert preparation.max_retries == 0
    assert preparation.fallback_provider is False
    assert preparation.network_call_allowed is False
    assert preparation.runtime_mutation is False
    assert preparation.paper_activation is False
    assert preparation.execution_authority is False
    assert preparation.exchange_access is False
    assert preparation.promotion_state == "unpromoted"


def test_planner_preparation_uses_planner_schema() -> None:
    preparation = build_provider_smoke_preparation(
        research_run_id="run-smoke-contract-002",
        role="hypothesis_generator",
        policy=_policy("hypothesis_generator"),
        input_evidence_refs=(f"learning/{HASH_A}",),
        prepared_at=NOW,
    )

    assert preparation.output_schema_id == "research-plan-v1"
    assert preparation.role == "hypothesis_generator"


def test_preparation_rejects_tampered_policy_before_build() -> None:
    tampered_policy = _policy().model_copy(update={"policy_hash": "f" * 64})

    with pytest.raises(DomainViolation, match="policy hash"):
        build_provider_smoke_preparation(
            research_run_id="run-smoke-contract-003",
            role="failure_analyst",
            policy=tampered_policy,
            input_evidence_refs=(f"failure/{HASH_A}",),
            prepared_at=NOW,
        )


def test_preparation_write_read_is_write_once_and_hash_verified(tmp_path) -> None:
    preparation = build_provider_smoke_preparation(
        research_run_id="run-smoke-contract-004",
        role="failure_analyst",
        policy=_policy(),
        input_evidence_refs=(f"failure/{HASH_A}",),
        prepared_at=NOW,
    )
    path = tmp_path / "smoke-preparation.json"

    first = write_provider_smoke_preparation(path, preparation)
    second = write_provider_smoke_preparation(path, preparation)

    assert first == preparation
    assert second == preparation
    assert read_provider_smoke_preparation(path) == preparation

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["preparation_hash"] = "f" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DomainViolation, match="preparation hash"):
        read_provider_smoke_preparation(path)


def test_preparation_model_cannot_enable_network_or_runtime() -> None:
    with pytest.raises(ValueError):
        ProviderSmokePreparation(
            preparation_id="smoke-prep-" + "0" * 64,
            research_run_id="run-smoke-contract-005",
            role="failure_analyst",
            policy_id="policy-smoke-contract-001",
            policy_hash=HASH_A,
            provider="google_ai_studio",
            model_id="gemma-4-26b-a4b-it",
            input_evidence_refs=("failure/ref",),
            output_schema_id="failure-learning-v1",
            network_call_allowed=True,
            prepared_at=NOW,
            preparation_hash="0" * 64,
        )


def test_cli_prepares_non_authorizing_artifact(tmp_path, capsys) -> None:
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "preparation.json"
    policy_path.write_text(_policy().model_dump_json(), encoding="utf-8")

    assert (
        main(
            [
                "--policy-file",
                str(policy_path),
                "--role",
                "failure_analyst",
                "--research-run-id",
                "run-smoke-cli-001",
                "--input-evidence-ref",
                f"failure/{HASH_A}",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    preparation = read_provider_smoke_preparation(output_path)
    assert result["status"] == "prepared"
    assert preparation.network_call_allowed is False
    assert preparation.runtime_mutation is False


def test_cli_blocks_policy_with_extra_credential_field(tmp_path, capsys) -> None:
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "preparation.json"
    payload = json.loads(_policy().model_dump_json())
    payload["api_key"] = "not-real"
    policy_path.write_text(json.dumps(payload), encoding="utf-8")

    assert (
        main(
            [
                "--policy-file",
                str(policy_path),
                "--role",
                "failure_analyst",
                "--research-run-id",
                "run-smoke-cli-002",
                "--input-evidence-ref",
                f"failure/{HASH_A}",
                "--output",
                str(output_path),
            ]
        )
        == 2
    )

    assert json.loads(capsys.readouterr().out) == {
        "error_code": "invalid_preparation_input",
        "status": "blocked",
    }
    assert not output_path.exists()
