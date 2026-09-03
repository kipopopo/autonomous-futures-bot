"""Empirical challenge tests for Phase 244.

Verifying zero secret leakage, boundary defenses, and single-probe constraints.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from autonomous_futures.staging_preflight import (
    ALLOWED_GEMMA_MODELS,
    validate_encrypted_source_store,
    validate_runtime_credential_delivery,
    validate_staging_environment,
)


def _load_cli_module() -> Any:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "preflight_kainode_staging.py"
    spec = importlib.util.spec_from_file_location("preflight_kainode_staging", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli_mod = _load_cli_module()
cli_main = cli_mod.main


def make_mock_stat(
    mode: int = 0o100600,
    uid: int = 0,
    gid: int = 0,
    size: int = 128,
) -> Callable[[Path], os.stat_result]:
    """Return a mock stat function for deterministic permission testing."""
    res = os.stat_result((mode, 0, 0, 1, uid, gid, size, 0, 0, 0))

    def _stat(_path: Path) -> os.stat_result:
        return res

    return _stat


CANARY_KEY = "AIzaSyDUMMY_CANARY_SECRET_KEY_12345"
BINANCE_KEY_NAME = "BINANCE_LIVE_API_KEY"
BINANCE_SECRET_NAME = "BINANCE_LIVE_SECRET_KEY"
BINANCE_CANARY_KEY_VAL = "binance_live_api_key_val_9876543210"
BINANCE_CANARY_SEC_VAL = "binance_live_secret_key_val_abcdef123456"


# ==============================================================================
# Objective 1: Zero-Secret-Leakage Invariant Empirical Verification
# ==============================================================================


def test_challenger_canary_leakage_in_runtime_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empirically test canary in runtime credential file across all reporting channels."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_data", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "runtime_creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(f"{CANARY_KEY}\n", encoding="utf-8")

    clean_env: dict[str, str] = {"PATH": "/bin"}

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        env=clean_env,
    )

    # 1. Report objects must not contain canary
    assert CANARY_KEY not in repr(report)
    assert CANARY_KEY not in str(report)
    dumped = report.model_dump(mode="json")
    assert CANARY_KEY not in json.dumps(dumped)
    assert CANARY_KEY not in str(report.errors)
    assert CANARY_KEY not in str(report.warnings)
    assert CANARY_KEY not in str(report.metadata)
    assert CANARY_KEY not in repr(report.runtime_credential)

    # 2. CLI execution must not output canary
    monkeypatch.setattr(
        "autonomous_futures.staging_preflight.validate_encrypted_source_store",
        lambda *args, **kwargs: validate_encrypted_source_store(
            source_path, stat_fn=stat_fn, platform="linux"
        ),
    )
    code = cli_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert CANARY_KEY not in captured.out
    assert CANARY_KEY not in captured.err


def test_challenger_canary_leakage_in_error_payloads(
    tmp_path: Path,
) -> None:
    """Empirically test canary in read failure and invalid format error payloads."""
    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    key_file = cred_dir / "google_ai_studio_api_key"

    # Scenario A: Invalid format containing canary with invalid spaces
    key_file.write_text(f"short {CANARY_KEY} bad", encoding="utf-8")
    report, key = validate_runtime_credential_delivery(cred_dir)
    assert key is None
    assert report.validation_error is not None
    assert CANARY_KEY not in report.validation_error
    assert CANARY_KEY not in repr(report)

    # Scenario B: Simulated read exception with canary in exception text
    with patch.object(
        Path, "read_text", side_effect=PermissionError(f"Denied reading {CANARY_KEY}")
    ):
        report_exc, key_exc = validate_runtime_credential_delivery(cred_dir)
        assert key_exc is None
        assert report_exc.validation_error is not None
        assert CANARY_KEY not in report_exc.validation_error
        assert "[REDACTED_API_KEY]" in report_exc.validation_error


def test_challenger_canary_leakage_in_cli_exception_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empirically test that CLI does not dump raw canary in exception traceback on crash."""
    with patch.object(
        cli_mod,
        "validate_staging_environment",
        side_effect=RuntimeError(f"Fatal crash with secret {CANARY_KEY}"),
    ):
        exit_code = cli_main(["--skip-source-check"])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert CANARY_KEY not in captured.out
        assert CANARY_KEY not in captured.err
        assert "[REDACTED_API_KEY]" in captured.out


def test_challenger_canary_leakage_in_environment_variables(
    tmp_path: Path,
) -> None:
    """Empirically test canary in arbitrary environment variable."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_data", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_for_testing_12345", encoding="utf-8"
    )

    env_with_canary = {
        "GOOGLE_AI_STUDIO_API_KEY": CANARY_KEY,
        "CUSTOM_SECRET_ENV": CANARY_KEY,
        "PATH": "/usr/bin",
    }

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        env=env_with_canary,
    )

    assert CANARY_KEY not in repr(report)
    assert CANARY_KEY not in json.dumps(report.model_dump(mode="json"))


# ==============================================================================
# Objective 2: Exchange Boundary Contamination Empirical Verification
# ==============================================================================


def test_challenger_exchange_credential_in_env_halts_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empirically verify BINANCE_LIVE_API_KEY / SECRET in env blocks preflight."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )

    contaminated_env = {
        BINANCE_KEY_NAME: BINANCE_CANARY_KEY_VAL,
        BINANCE_SECRET_NAME: BINANCE_CANARY_SEC_VAL,
    }

    # Test Python validation halts
    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        env=contaminated_env,
    )

    assert report.ready is False
    assert report.status == "blocked"
    assert report.offline_safety.exchange_access is False
    assert report.offline_safety.execution_authority is False
    assert report.offline_safety.orders == 0
    assert report.offline_safety.promotion_state == "unpromoted"
    assert report.offline_safety.validation_error is not None
    assert "exchange_credential_contamination" in report.offline_safety.validation_error
    assert f"env:{BINANCE_KEY_NAME}" in report.offline_safety.binance_keys_detected
    assert f"env:{BINANCE_SECRET_NAME}" in report.offline_safety.binance_keys_detected

    # Zero leakage of secret values
    assert BINANCE_CANARY_KEY_VAL not in repr(report)
    assert BINANCE_CANARY_SEC_VAL not in repr(report)
    assert BINANCE_CANARY_KEY_VAL not in json.dumps(report.model_dump(mode="json"))
    assert BINANCE_CANARY_SEC_VAL not in json.dumps(report.model_dump(mode="json"))

    # Test CLI halts with exit code 3
    monkeypatch.setattr(
        "autonomous_futures.staging_preflight.validate_encrypted_source_store",
        lambda *args, **kwargs: validate_encrypted_source_store(
            source_path, stat_fn=stat_fn, platform="linux"
        ),
    )
    for k, v in contaminated_env.items():
        monkeypatch.setenv(k, v)

    code = cli_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
        ]
    )
    assert code == 3
    captured = capsys.readouterr()
    assert BINANCE_CANARY_KEY_VAL not in captured.out
    assert BINANCE_CANARY_SEC_VAL not in captured.out
    cli_json = json.loads(captured.out)
    assert cli_json["status"] == "blocked"
    assert cli_json["ready"] is False
    assert any("exchange_credential_contamination" in e for e in cli_json["errors"])


def test_challenger_exchange_credential_in_directory_halts_preflight(
    tmp_path: Path,
) -> None:
    """Empirically verify BINANCE credential files in credential_dir blocks preflight."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds_with_binance"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )
    # Contaminating files in the directory
    (cred_dir / "binance_live_api_key").write_text(BINANCE_CANARY_KEY_VAL, encoding="utf-8")
    (cred_dir / "BINANCE_LIVE_SECRET_KEY").write_text(BINANCE_CANARY_SEC_VAL, encoding="utf-8")

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        env={},
    )

    assert report.ready is False
    assert report.status == "blocked"
    assert report.offline_safety.validation_error is not None
    assert "exchange_credential_contamination" in report.offline_safety.validation_error
    assert "file:binance_live_api_key" in report.offline_safety.binance_keys_detected
    assert "file:BINANCE_LIVE_SECRET_KEY" in report.offline_safety.binance_keys_detected

    # Zero leakage of file contents
    assert BINANCE_CANARY_KEY_VAL not in repr(report)
    assert BINANCE_CANARY_SEC_VAL not in repr(report)


# ==============================================================================
# Objective 3: Single-Probe Constraints Empirical Verification
# ==============================================================================


@pytest.mark.parametrize("invalid_retries", [1, 2, 5, 10, -1])
def test_challenger_single_probe_retry_constraint(tmp_path: Path, invalid_retries: int) -> None:
    """Empirically test that max_retries != 0 is strictly blocked."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        max_retries=invalid_retries,
        env={},
    )

    assert report.ready is False
    assert report.status == "blocked"
    assert any("single_probe_retry_violation" in err for err in report.errors)


def test_challenger_single_probe_fallback_provider_constraint(
    tmp_path: Path,
) -> None:
    """Empirically test that fallback_provider=True is strictly blocked."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        fallback_provider=True,
        env={},
    )

    assert report.ready is False
    assert report.status == "blocked"
    assert any("single_probe_fallback_violation" in err for err in report.errors)


@pytest.mark.parametrize(
    "invalid_model",
    [
        "gpt-4o",
        "claude-3-5-sonnet",
        "gemini-1.5-pro",
        "gemma-2-9b",
        "gemma-4-unknown",
        "gemma-4-31b-it; rm -rf /",
    ],
)
def test_challenger_single_probe_model_whitelist(tmp_path: Path, invalid_model: str) -> None:
    """Empirically test that non-whitelisted models are strictly blocked."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        model_id=invalid_model,
        env={},
    )

    assert report.ready is False
    assert report.status == "blocked"
    assert any("invalid_model_id" in err for err in report.errors)


@pytest.mark.parametrize("valid_model", ALLOWED_GEMMA_MODELS)
def test_challenger_single_probe_whitelisted_models_pass(tmp_path: Path, valid_model: str) -> None:
    """Empirically verify that all models in ALLOWED_GEMMA_MODELS pass validation."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        model_id=valid_model,
        env={},
    )

    assert report.ready is True
    assert report.status == "ready_for_staging_probe"
    assert report.probe_constraints.model_id == valid_model


def test_challenger_cli_single_probe_fallback_provider_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empirically verify CLI halts with exit code 3 when --fallback-provider is supplied."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )

    monkeypatch.setattr(
        "autonomous_futures.staging_preflight.validate_encrypted_source_store",
        lambda *args, **kwargs: validate_encrypted_source_store(
            source_path, stat_fn=stat_fn, platform="linux"
        ),
    )

    code = cli_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
            "--fallback-provider",
        ]
    )
    assert code == 3
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "blocked"
    assert any("single_probe_fallback_violation" in e for e in data["errors"])


def test_challenger_cli_single_probe_max_retries_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empirically verify CLI halts with exit code 3 when --max-retries > 0 is supplied."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )

    monkeypatch.setattr(
        "autonomous_futures.staging_preflight.validate_encrypted_source_store",
        lambda *args, **kwargs: validate_encrypted_source_store(
            source_path, stat_fn=stat_fn, platform="linux"
        ),
    )

    code = cli_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
            "--max-retries",
            "3",
        ]
    )
    assert code == 3
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "blocked"
    assert any("single_probe_retry_violation" in e for e in data["errors"])


def test_challenger_cli_single_probe_invalid_model_choice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Empirically verify CLI parser rejects invalid model ID with exit code 2."""
    code = cli_main(["--model-id", "unsupported-model-v1"])
    assert code == 2


@pytest.mark.parametrize(
    "env_key",
    [
        "binance_live_api_key",
        "BINANCE_FUTURES_TESTNET_KEY",
        "PREFIX_BINANCE_SECRET",
        "MY_binance_KEY_VAL",
    ],
)
def test_challenger_exchange_credential_casing_and_patterns(tmp_path: Path, env_key: str) -> None:
    """Empirically verify case-insensitive matching for BINANCE tokens in env."""
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_key_string_1234567890", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        env={env_key: "secret_value"},
    )

    assert report.ready is False
    assert report.status == "blocked"
    assert report.offline_safety.validation_error is not None
    assert f"env:{env_key}" in report.offline_safety.binance_keys_detected
