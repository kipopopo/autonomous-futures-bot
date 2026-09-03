"""Unit tests for bounded Creator staging diagnostic probe (Phase 249)."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from autonomous_futures.creator_staging_probe import (
    DEFAULT_PINNED_MODEL_ID,
    assert_offline_safety_invariants,
    execute_creator_staging_probe,
    resolve_staging_credential,
    validate_probe_parameters,
)
from autonomous_futures.research.creator_batch_persistence import (
    read_creator_batch_trial_evidence,
)
from autonomous_futures.research.creator_generator import (
    CreatorGenerationRequest,
)
from autonomous_futures.research.google_ai_studio_provider import (
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    ProviderJsonPayload,
    ProviderTransportError,
)


def _load_script_module(name: str) -> Any:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


preflight_mod = _load_script_module("preflight_kainode_staging")
probe_mod = _load_script_module("probe_creator_staging")
preflight_main: Callable[[list[str] | None], int] = preflight_mod.main
probe_main: Callable[[list[str] | None], int] = probe_mod.main


def _valid_proposal_payload(
    run_id: str = "run-doge-google-gemma-20260903-phase249",
) -> dict[str, Any]:
    return {
        "proposal_id": "proposal-phase249-001",
        "research_run_id": run_id,
        "hypothesis": "Mean reversion after RSI extreme oversold state",
        "expected_regime": "range",
        "novelty_reason": "Single-probe test hypothesis",
        "strategy": {
            "dsl_version": 1,
            "strategy_id": "cand-placeholder-will-be-overwritten",
            "family": "range_mean_reversion",
            "universe": {
                "symbols": ["DOGEUSDT"],
                "timeframe": "5m",
                "regime_context_timeframe": "15m",
            },
            "features": [{"name": "rsi", "lookback": 14, "shift": 1}],
            "entry": {"long": "rsi <= 30", "short": "rsi >= 70"},
            "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
            "vetoes": ["funding_adverse"],
        },
    }


def test_resolve_staging_credential_from_directory(tmp_path: Path) -> None:
    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    cred_file = cred_dir / "google_ai_studio_api_key"
    test_key = "AIzaSyFakeGoogleAIStudioKey12345678"
    cred_file.write_text(test_key, encoding="utf-8")

    resolved = resolve_staging_credential(credential_dir=cred_dir)
    assert resolved == test_key


def test_resolve_staging_credential_from_credentials_directory_env(tmp_path: Path) -> None:
    cred_dir = tmp_path / "systemd_creds"
    cred_dir.mkdir()
    cred_file = cred_dir / "google_ai_studio_api_key"
    test_key = "AIzaSyFakeGoogleAIStudioKey98765432"
    cred_file.write_text(test_key, encoding="utf-8")

    env = {"CREDENTIALS_DIRECTORY": str(cred_dir)}
    resolved = resolve_staging_credential(credential_dir=None, env=env)
    assert resolved == test_key


def test_resolve_staging_credential_from_env_vars() -> None:
    test_key = "AIzaSyEnvVarGoogleStudioKey11223344"
    env = {"GOOGLE_AI_STUDIO_API_KEY": test_key}
    resolved = resolve_staging_credential(credential_dir=None, env=env)
    assert resolved == test_key


def test_resolve_staging_credential_explicit_key() -> None:
    test_key = "AIzaSyExplicitKeyValidLength55667788"
    resolved = resolve_staging_credential(explicit_key=test_key)
    assert resolved == test_key


def test_resolve_staging_credential_symlink_rejected(tmp_path: Path) -> None:
    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    real_file = tmp_path / "real_key"
    real_file.write_text("AIzaSyRealKeyContent12345678", encoding="utf-8")
    symlink_file = cred_dir / "google_ai_studio_api_key"
    try:
        symlink_file.symlink_to(real_file)
    except OSError:
        pytest.skip("Symlinks not supported on this platform/privilege")

    with pytest.raises(RuntimeError, match="No valid Google AI Studio credential"):
        resolve_staging_credential(credential_dir=cred_dir, env={})


def test_resolve_staging_credential_invalid_format(tmp_path: Path) -> None:
    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    cred_file = cred_dir / "google_ai_studio_api_key"
    # Too short
    cred_file.write_text("short_key", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid format"):
        resolve_staging_credential(credential_dir=cred_dir)

    # Empty
    cred_file.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        resolve_staging_credential(credential_dir=cred_dir)


def test_resolve_staging_credential_missing_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="No valid Google AI Studio credential"):
        resolve_staging_credential(credential_dir=None, env={})


def test_validate_probe_parameters_strict() -> None:
    # Valid default passes
    validate_probe_parameters(
        base_url=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        model_id=DEFAULT_PINNED_MODEL_ID,
        max_retries=0,
        fallback_provider=False,
    )

    # max_retries > 0 rejected
    with pytest.raises(ValueError, match="max_retries must be 0"):
        validate_probe_parameters(max_retries=1)

    # fallback_provider True rejected
    with pytest.raises(ValueError, match="fallback_provider must be False"):
        validate_probe_parameters(fallback_provider=True)

    # bad base_url rejected
    with pytest.raises(ValueError, match="base_url must be"):
        validate_probe_parameters(base_url="https://api.openai.com/v1")

    # unknown model rejected
    with pytest.raises(ValueError, match="model_id must be in"):
        validate_probe_parameters(model_id="gpt-4o")


def test_assert_offline_safety_invariants(tmp_path: Path) -> None:
    # Clean env passes
    assert_offline_safety_invariants(credential_dir=tmp_path, env={"PATH": "/usr/bin"})

    # Contaminated env rejected
    with pytest.raises(RuntimeError, match="Offline safety violation"):
        assert_offline_safety_invariants(
            credential_dir=tmp_path,
            env={"BINANCE_API_KEY": "hostile_binance_key"},
        )

    # Contaminated directory rejected
    bad_dir = tmp_path / "bad_creds"
    bad_dir.mkdir()
    (bad_dir / "binance_secret_key").write_text("secret", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Offline safety violation"):
        assert_offline_safety_invariants(credential_dir=bad_dir, env={})


def test_execute_creator_staging_probe_accepted(tmp_path: Path) -> None:
    evidence_root = tmp_path / "phase249_evidence"
    run_id = "run-doge-google-gemma-20260903-phase249"
    payload = _valid_proposal_payload(run_id=run_id)

    def mock_transport(req: CreatorGenerationRequest) -> ProviderJsonPayload:
        return ProviderJsonPayload(payload, metadata={"finish_reason": "stop"})

    summary = execute_creator_staging_probe(
        api_key="AIzaSyMockKeyForTesting12345678",
        evidence_root=evidence_root,
        run_id=run_id,
        transport_override=mock_transport,
        env={"PATH": "/usr/bin"},
    )

    assert summary["decision"] == "accepted"
    assert summary["reason_codes"] == ["candidate_accepted_for_testing"]
    assert summary["candidate_id"] is not None
    assert summary["candidate_id"].startswith("cand-")
    assert summary["candidate_artifact_hash"] is not None
    assert len(summary["candidate_artifact_hash"]) == 64
    assert summary["safety_state"]["orders"] == 0
    assert summary["safety_state"]["exchange_access"] is False
    assert summary["safety_state"]["execution_authority"] is False
    assert summary["safety_state"]["promotion_state"] == "unpromoted"

    # Verify trial file exists on disk and is readable
    trial_file = evidence_root / "trials" / f"trial-0000-{run_id}.json"
    assert trial_file.is_file()
    evidence = read_creator_batch_trial_evidence(trial_file)
    assert evidence.trial.decision == "accepted"
    assert evidence.trial.candidate_id == summary["candidate_id"]

    # Verify campaign summary exists on disk
    summary_file = evidence_root / "campaign-summary.json"
    assert summary_file.is_file()


def test_execute_creator_staging_probe_rejected_provider_http_error(tmp_path: Path) -> None:
    evidence_root = tmp_path / "phase249_rejected"
    run_id = "run-doge-google-gemma-20260903-phase249"

    def mock_failing_transport(req: CreatorGenerationRequest) -> ProviderJsonPayload:
        raise ProviderTransportError(
            code="provider_http_error",
            status_code=401,
            error_code="http_401",
            error_status="UNAUTHENTICATED",
            error_reason="http_401_unauthenticated",
            metadata={
                "status_code": 401,
                "error_code": "http_401",
                "error_status": "UNAUTHENTICATED",
                "error_reason": "http_401_unauthenticated",
                "content_kind": "json",
                "content_length": 150,
                "content_sha256": "0" * 64,
                "response_keys": ["error"],
            },
        )

    summary = execute_creator_staging_probe(
        api_key="AIzaSyMockKeyForTesting12345678",
        evidence_root=evidence_root,
        run_id=run_id,
        transport_override=mock_failing_transport,
        env={"PATH": "/usr/bin"},
    )

    assert summary["decision"] == "rejected"
    assert "provider_http_error" in summary["reason_codes"]
    assert summary["candidate_id"] is None
    assert summary["provider_metadata"]["status_code"] == 401
    assert summary["provider_metadata"]["error_code"] == "http_401"
    assert summary["safety_state"]["orders"] == 0
    assert summary["safety_state"]["exchange_access"] is False

    trial_file = evidence_root / "trials" / f"trial-0000-{run_id}.json"
    assert trial_file.is_file()
    evidence = read_creator_batch_trial_evidence(trial_file)
    assert evidence.trial.decision == "rejected"


def test_execute_creator_staging_probe_schema_rejected(tmp_path: Path) -> None:
    evidence_root = tmp_path / "phase249_schema_rejected"
    run_id = "run-doge-google-gemma-20260903-phase249"

    # Malformed proposal missing 'strategy'
    bad_payload = {"proposal_id": "proposal-bad", "research_run_id": run_id}

    def mock_bad_schema_transport(req: CreatorGenerationRequest) -> ProviderJsonPayload:
        return ProviderJsonPayload(bad_payload, metadata={"finish_reason": "stop"})

    summary = execute_creator_staging_probe(
        api_key="AIzaSyMockKeyForTesting12345678",
        evidence_root=evidence_root,
        run_id=run_id,
        transport_override=mock_bad_schema_transport,
        env={"PATH": "/usr/bin"},
    )

    assert summary["decision"] == "rejected"
    assert summary["reason_codes"] == ["schema_rejected"]
    assert len(summary["schema_diagnostics"]) > 0


def test_preflight_cli_with_execute_probe_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    cred_file = cred_dir / "google_ai_studio_api_key"
    cred_file.write_text("AIzaSyMockKeyForCliTesting123456", encoding="utf-8")

    evidence_dir = tmp_path / "evidence_out"

    # Mock validate_encrypted_source_store
    monkeypatch.setattr(
        "autonomous_futures.staging_preflight.validate_encrypted_source_store",
        lambda *args, **kwargs: None,
    )
    # Mock validate_staging_environment to return ready
    from autonomous_futures.staging_preflight import StagingPreflightReport

    monkeypatch.setattr(
        preflight_mod,
        "validate_staging_environment",
        lambda **kwargs: StagingPreflightReport(
            ready=True,
            status="ready_for_staging_probe",
            errors=(),
            warnings=(),
            source_store={
                "path": str(kwargs.get("source_credential_path")),
                "exists": True,
                "is_regular_file": True,
                "size_bytes": 128,
                "mode_octal": "0o600",
                "mode_valid": True,
                "owner_uid": 0,
                "owner_name": "root",
                "owner_valid": True,
            },
            runtime_credential={  # type: ignore[arg-type]
                "credential_name": "google_ai_studio_api_key",
                "exists": True,
                "is_regular_file": True,
                "non_empty": True,
            },
            offline_safety={  # type: ignore[arg-type]
                "binance_keys_forbidden": True,
                "binance_keys_detected": (),
                "exchange_access": False,
                "execution_authority": False,
                "orders": 0,
                "promotion_state": "unpromoted",
                "paper_activation": False,
            },
            probe_constraints={  # type: ignore[arg-type]
                "base_url": GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
                "model_id": "gemma-4-31b-it",
                "max_retries": 0,
                "fallback_provider": False,
                "provider": "google_ai_studio",
            },
            metadata={"platform": "linux", "python_version": "3.14.7"},
        ),
    )

    # Mock execute_creator_staging_probe
    monkeypatch.setattr(
        preflight_mod,
        "execute_creator_staging_probe",
        lambda **kwargs: {
            "campaign_id": kwargs["campaign_id"],
            "decision": "accepted",
            "candidate_id": "cand-test-identity",
            "request_count": 1,
            "max_retries": 0,
            "fallback_provider": False,
            "safety_state": {
                "orders": 0,
                "exchange_access": False,
                "execution_authority": False,
                "promotion_state": "unpromoted",
            },
        },
    )

    code = preflight_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
            "--execute-probe",
            "--evidence-dir",
            str(evidence_dir),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    assert len(lines) > 0


def test_probe_creator_staging_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    cred_file = cred_dir / "google_ai_studio_api_key"
    cred_file.write_text("AIzaSyMockKeyForCliTesting123456", encoding="utf-8")
    evidence_dir = tmp_path / "evidence_out"

    monkeypatch.setattr(
        probe_mod,
        "execute_creator_staging_probe",
        lambda **kwargs: {
            "campaign_id": kwargs["campaign_id"],
            "decision": "accepted",
            "candidate_id": "cand-cli-probe",
            "request_count": 1,
            "max_retries": 0,
            "fallback_provider": False,
            "safety_state": {
                "orders": 0,
                "exchange_access": False,
                "execution_authority": False,
                "promotion_state": "unpromoted",
            },
        },
    )

    code = probe_main(
        [
            "--credential-dir",
            str(cred_dir),
            "--evidence-dir",
            str(evidence_dir),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["decision"] == "accepted"
    assert data["candidate_id"] == "cand-cli-probe"
