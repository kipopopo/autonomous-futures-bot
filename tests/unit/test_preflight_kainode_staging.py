"""Comprehensive unit tests for Kainode staging preflight logic and CLI."""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from autonomous_futures.research.google_ai_studio_provider import (
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
)
from autonomous_futures.staging_preflight import (
    validate_encrypted_source_store,
    validate_staging_environment,
)


def _load_cli_main() -> Callable[[list[str] | None], int]:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "preflight_kainode_staging.py"
    spec = importlib.util.spec_from_file_location("preflight_kainode_staging", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main  # type: ignore[no-any-return]


cli_main = _load_cli_main()


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


def test_preflight_valid_credentials_clean_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_path = tmp_path / "google_ai_studio_api_key_source"
    source_path.write_text("encrypted_blob_data", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "credentials"
    cred_dir.mkdir()
    runtime_key_file = cred_dir / "google_ai_studio_api_key"
    runtime_key_file.write_text("valid_opaque_token_string_12345", encoding="utf-8")

    clean_env: dict[str, str] = {"PATH": "/usr/bin"}

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        base_url=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        model_id="gemma-4-31b-it",
        max_retries=0,
        fallback_provider=False,
        stat_fn=stat_fn,
        env=clean_env,
    )

    assert report.ready is True
    assert report.status == "ready_for_staging_probe"
    assert report.errors == ()
    assert report.offline_safety.exchange_access is False
    assert report.runtime_credential.non_empty is True

    # Test CLI invocation returns 0
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
            "--base-url",
            GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
            "--model-id",
            "gemma-4-31b-it",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "ready_for_staging_probe"


def test_preflight_missing_encrypted_store(tmp_path: Path) -> None:
    missing_source = tmp_path / "non_existent_source_key"
    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=missing_source,
        credential_dir=cred_dir,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("credential_store_missing" in err for err in report.errors)


def test_preflight_loose_permissions_mode_644(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100644, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        platform="linux",
    )
    assert report.ready is False
    assert any("credential_store_insecure_permissions" in err for err in report.errors)


def test_preflight_loose_permissions_mode_777(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100777, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        platform="linux",
    )
    assert report.ready is False
    assert any("credential_store_insecure_permissions" in err for err in report.errors)


def test_preflight_loose_permissions_mode_660(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100660, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        platform="linux",
    )
    assert report.ready is False
    assert any("credential_store_insecure_permissions" in err for err in report.errors)


def test_preflight_accepted_permissions_mode_400(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100400, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        platform="linux",
        env={},
    )
    assert report.ready is True
    assert not any("credential_store_insecure_permissions" in err for err in report.errors)


def test_preflight_wrong_owner_uid(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    # UID 9999 is neither root (0) nor afbot (1000)
    stat_fn = make_mock_stat(mode=0o100600, uid=9999, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        platform="linux",
    )
    assert report.ready is False
    assert any("credential_store_invalid_owner" in err for err in report.errors)


def test_preflight_empty_encrypted_store(tmp_path: Path) -> None:
    source_path = tmp_path / "empty_source_key"
    source_path.write_text("", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=0)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        platform="linux",
    )
    assert report.ready is False
    assert any("credential_store_empty" in err for err in report.errors)


def test_preflight_missing_credentials_directory(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=None,
        stat_fn=stat_fn,
    )
    assert report.ready is False
    assert any("credentials_directory_missing" in err for err in report.errors)


def test_preflight_missing_runtime_key_file(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "empty_creds"
    cred_dir.mkdir()

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
    )
    assert report.ready is False
    assert any("runtime_credential_missing" in err for err in report.errors)


def test_preflight_empty_runtime_key_file(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text("   \n", encoding="utf-8")

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
    )
    assert report.ready is False
    assert any("runtime_credential_empty" in err for err in report.errors)


def test_preflight_invalid_runtime_key_format(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    # Too short (< 20 chars)
    (cred_dir / "google_ai_studio_api_key").write_text("short_key", encoding="utf-8")

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
    )
    assert report.ready is False
    assert any("runtime_credential_invalid_format" in err for err in report.errors)


def test_preflight_contamination_with_binance_env_keys(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    contaminated_env = {"BINANCE_LIVE_API_KEY": "canary_secret_val"}

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        env=contaminated_env,
    )
    assert report.ready is False
    assert any("exchange_credential_contamination" in err for err in report.errors)
    assert "env:BINANCE_LIVE_API_KEY" in report.offline_safety.binance_keys_detected


def test_preflight_contamination_with_binance_files(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )
    (cred_dir / "binance_live_api_key").write_text("secret", encoding="utf-8")

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        env={},
    )
    assert report.ready is False
    assert any("exchange_credential_contamination" in err for err in report.errors)
    assert "file:binance_live_api_key" in report.offline_safety.binance_keys_detected


def test_preflight_single_probe_retry_violation(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        max_retries=3,
        env={},
    )
    assert report.ready is False
    assert any("single_probe_retry_violation" in err for err in report.errors)


def test_preflight_single_probe_fallback_provider_violation(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        fallback_provider=True,
        env={},
    )
    assert report.ready is False
    assert any("single_probe_fallback_violation" in err for err in report.errors)


def test_preflight_invalid_base_url(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        base_url="https://api.openai.com/v1",
        env={},
    )
    assert report.ready is False
    assert any("invalid_base_url" in err for err in report.errors)


def test_preflight_invalid_model_id(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "valid_opaque_key_string_12345", encoding="utf-8"
    )

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        model_id="gpt-4o-mini",
        env={},
    )
    assert report.ready is False
    assert any("invalid_model_id" in err for err in report.errors)


def test_preflight_zero_secret_leakage_comprehensive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    canary_google_key = "AIzaSyCanary999888777666555444"
    canary_binance_secret = "binance_canary_secret_value_112233"

    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(canary_google_key, encoding="utf-8")

    env_with_secret = {"BINANCE_LIVE_API_KEY": canary_binance_secret}
    monkeypatch.setenv("BINANCE_LIVE_API_KEY", canary_binance_secret)

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        env=env_with_secret,
    )

    # 1. Inspect Python report objects
    report_repr = repr(report)
    assert canary_google_key not in report_repr
    assert canary_binance_secret not in report_repr

    dumped = report.model_dump(mode="json")
    dumped_str = json.dumps(dumped)
    assert canary_google_key not in dumped_str
    assert canary_binance_secret not in dumped_str

    for err in report.errors:
        assert canary_google_key not in err
        assert canary_binance_secret not in err

    # 2. Inspect CLI execution output
    code = cli_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
        ]
    )
    # Blocked due to binance key in env
    assert code == 3
    captured = capsys.readouterr()
    assert canary_google_key not in captured.out
    assert canary_binance_secret not in captured.out
    assert canary_google_key not in captured.err
    assert canary_binance_secret not in captured.err


def test_preflight_cli_argument_parsing_and_exit_code_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli_main(["--unrecognized-argument-xyz"])
    assert code == 2


def test_preflight_multiple_simultaneous_violations(tmp_path: Path) -> None:
    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")
    stat_fn = make_mock_stat(mode=0o100777, uid=9999, size=128)

    cred_dir = tmp_path / "empty_dir"
    cred_dir.mkdir()

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        stat_fn=stat_fn,
        platform="linux",
        base_url="https://api.openai.com/v1",
        model_id="invalid-model",
        max_retries=2,
        fallback_provider=True,
        env={"BINANCE_API_KEY": "test"},
    )

    assert report.ready is False
    assert report.status == "blocked"
    # Multiple distinct violation categories are all captured
    error_text = " ".join(report.errors)
    assert "credential_store_insecure_permissions" in error_text
    assert "runtime_credential_missing" in error_text
    assert "exchange_credential_contamination" in error_text
    assert "invalid_base_url" in error_text
    assert "invalid_model_id" in error_text
    assert "single_probe_retry_violation" in error_text
    assert "single_probe_fallback_violation" in error_text
