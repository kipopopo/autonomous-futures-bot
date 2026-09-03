"""Empirical adversarial challenge and stress tests for Kainode staging preflight and service.

Authored by challenger_1 for Phase 244 empirical challenge.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from autonomous_futures.research.google_ai_studio_provider import (
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
)
from autonomous_futures.staging_preflight import (
    EncryptedSourceStoreReport,
    OfflineSafetyInvariants,
    RuntimeCredentialReport,
    SingleProbeConstraints,
    StagingPreflightReport,
    validate_encrypted_source_store,
    validate_runtime_credential_delivery,
    validate_single_probe_constraints,
    validate_staging_environment,
)

# Load CLI entrypoint dynamically
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "preflight_kainode_staging.py"
_SPEC = importlib.util.spec_from_file_location("preflight_kainode_staging", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_CLI_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI_MOD)
cli_main: Callable[[list[str] | None], int] = _CLI_MOD.main

SERVICE_UNIT_PATH = (
    Path(__file__).resolve().parents[2] / "deploy" / "autonomous-futures-creator-staging.service"
)


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


# ==============================================================================
# SUITE A: CLI Argument Parsing and Exit Code 2 Oracle
# ==============================================================================


@pytest.mark.parametrize(
    "invalid_args",
    [
        ["--nonexistent-option-xyz"],
        ["--foo", "--bar"],
        ["--source-credential-path"],  # missing value
        ["--credential-dir"],  # missing value
        ["--model-id"],  # missing value
        ["--model-id", "gpt-4o"],  # not in choices
        ["--model-id", "claude-3-opus"],  # not in choices
        ["--model-id", "gemini-1.5-pro"],  # not in choices
        ["--max-retries"],  # missing value
        ["--max-retries", "not_a_number"],  # invalid int
        ["--max-retries", "3.14"],  # invalid int
    ],
)
def test_cli_invalid_arguments_return_exit_code_2(
    invalid_args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Argparse syntax errors and invalid option choices must return exit code 2."""
    code = cli_main(invalid_args)
    assert code == 2


def test_cli_empty_string_arguments_handled_gracefully(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empty string passed to source-credential-path or base-url must not crash unexpectedly."""
    # Empty source path -> invalid input or blocked, never code 0
    code = cli_main(["--source-credential-path", "", "--skip-source-check"])
    # Either code 2 (OSError/ValueError) or code 3 (blocked)
    assert code in (2, 3)


# ==============================================================================
# SUITE B: Exit Code 3 Security & Configuration Blocking Conditions
# ==============================================================================


def test_cli_nonexistent_paths_return_exit_code_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nonexistent source path or credential dir must result in exit code 3."""
    code = cli_main(
        [
            "--source-credential-path",
            str(tmp_path / "does_not_exist_source"),
            "--credential-dir",
            str(tmp_path / "does_not_exist_cred_dir"),
        ]
    )
    assert code == 3
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "blocked"
    assert data["ready"] is False
    assert any("credential_store_missing" in err for err in data["errors"])
    assert any("credentials_directory_missing" in err for err in data["errors"])


def test_cli_directory_traversal_paths_properly_evaluated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Directory traversal sequences (e.g. ../../../etc/shadow) must not bypass validation."""
    traversal_path = tmp_path / "sub" / ".." / "nonexistent_secret"
    code = cli_main(
        [
            "--source-credential-path",
            str(traversal_path),
            "--credential-dir",
            str(tmp_path),
        ]
    )
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "blocked"


def test_cli_source_store_as_directory_returns_exit_code_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If source_credential_path points to a directory instead of a regular file, must return 3."""
    dir_path = tmp_path / "store_is_a_dir"
    dir_path.mkdir()
    code = cli_main(
        [
            "--source-credential-path",
            str(dir_path),
            "--credential-dir",
            str(tmp_path),
        ]
    )
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "blocked"
    assert any("credential_store_not_a_regular_file" in err for err in data["errors"])


def test_cli_credential_dir_as_file_returns_exit_code_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If credential_dir points to a regular file instead of a directory, must return 3."""
    file_as_dir = tmp_path / "cred_dir_is_actually_a_file"
    file_as_dir.write_text("dummy", encoding="utf-8")
    code = cli_main(
        [
            "--source-credential-path",
            str(tmp_path / "source"),
            "--credential-dir",
            str(file_as_dir),
        ]
    )
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "blocked"
    assert any("credentials_directory_missing" in err for err in data["errors"])


def test_cli_binary_corrupted_runtime_credential_returns_exit_code_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If runtime credential contains invalid non-UTF-8 bytes, must handle cleanly and return 3."""
    source_file = tmp_path / "source_key"
    source_file.write_text("encrypted_blob", encoding="utf-8")

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    runtime_file = cred_dir / "google_ai_studio_api_key"
    # Write invalid UTF-8 byte sequence
    runtime_file.write_bytes(b"\x80\x81\x82\xfe\xff\x00corrupted")

    code = cli_main(
        [
            "--source-credential-path",
            str(source_file),
            "--credential-dir",
            str(cred_dir),
            "--skip-source-check",
        ]
    )
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "blocked"
    assert any("runtime_credential_read_failure" in err for err in data["errors"])


def test_cli_whitespace_contaminated_runtime_key_returns_exit_code_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keys with internal spaces, tabs, or newlines must be rejected with exit code 3."""
    source_file = tmp_path / "source_key"
    source_file.write_text("encrypted_blob", encoding="utf-8")

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    runtime_file = cred_dir / "google_ai_studio_api_key"
    # Key length >= 20, but contains an internal space
    runtime_file.write_text("AIzaSy123456789 123456789", encoding="utf-8")

    code = cli_main(
        [
            "--source-credential-path",
            str(source_file),
            "--credential-dir",
            str(cred_dir),
            "--skip-source-check",
        ]
    )
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "blocked"
    assert any("runtime_credential_invalid_format" in err for err in data["errors"])


# ==============================================================================
# SUITE C: Symlink Attacks & Adversarial Scenarios
# ==============================================================================


def test_symlink_source_credential_rejected(tmp_path: Path) -> None:
    """A symbolic link passed as source credential must be rejected."""
    real_file = tmp_path / "real_file"
    real_file.write_text("secret_blob", encoding="utf-8")

    symlink_file = tmp_path / "symlink_source"
    try:
        symlink_file.symlink_to(real_file)
    except OSError, NotImplementedError:
        pytest.skip("Symlink creation not permitted on this platform without admin")

    report = validate_encrypted_source_store(symlink_file)
    assert report.is_regular_file is False
    assert report.mode_valid is False
    assert "credential_store_not_a_regular_file" in (report.validation_error or "")


def test_symlink_runtime_credential_rejected(tmp_path: Path) -> None:
    """A symbolic link passed as runtime credential in CREDENTIALS_DIRECTORY must be rejected."""
    real_file = tmp_path / "target_key"
    real_file.write_text("AIzaSyValidLengthTokenString12345678", encoding="utf-8")

    cred_dir = tmp_path / "cred_dir"
    cred_dir.mkdir()
    symlink_file = cred_dir / "google_ai_studio_api_key"
    try:
        symlink_file.symlink_to(real_file)
    except OSError, NotImplementedError:
        pytest.skip("Symlink creation not permitted on this platform without admin")

    runtime_report, raw_key = validate_runtime_credential_delivery(cred_dir)
    assert raw_key is None
    assert runtime_report.is_regular_file is False
    assert "runtime_credential_not_a_regular_file" in (runtime_report.validation_error or "")


# ==============================================================================
# SUITE D: Readiness Oracle & Exhaustive Mutation Testing
# ==============================================================================


def test_oracle_single_mutation_invalidation_matrix(tmp_path: Path) -> None:
    """Verify that every single violation deterministically invalidates readiness."""
    # Base valid fixtures
    source_file = tmp_path / "source_key"
    source_file.write_text("valid_encrypted_blob", encoding="utf-8")
    stat_valid = make_mock_stat(mode=0o100600, uid=0, size=128)

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    runtime_file = cred_dir / "google_ai_studio_api_key"
    runtime_file.write_text("valid_opaque_key_string_1234567890", encoding="utf-8")

    clean_env: dict[str, str] = {"PATH": "/usr/bin"}

    # Base valid check must succeed
    base_report = validate_staging_environment(
        source_credential_path=source_file,
        credential_dir=cred_dir,
        base_url=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        model_id="gemma-4-31b-it",
        max_retries=0,
        fallback_provider=False,
        stat_fn=stat_valid,
        env=clean_env,
    )
    assert base_report.ready is True
    assert base_report.status == "ready_for_staging_probe"

    # Mutations matrix: (kwarg_overrides, expected_error_substring)
    mutations: list[tuple[dict[str, Any], str]] = [
        # 1. Nonexistent source
        (
            {"source_credential_path": tmp_path / "missing_source"},
            "credential_store_missing",
        ),
        # 2. Insecure mode (0o664)
        (
            {"stat_fn": make_mock_stat(mode=0o100664, uid=0, size=128)},
            "credential_store_insecure_permissions",
        ),
        # 3. Invalid owner (UID 500)
        (
            {"stat_fn": make_mock_stat(mode=0o100600, uid=500, size=128)},
            "credential_store_invalid_owner",
        ),
        # 4. Missing cred_dir
        ({"credential_dir": None}, "credentials_directory_missing"),
        # 5. Missing runtime file
        (
            {"credential_dir": tmp_path / "empty_dir"},
            "credentials_directory_missing",
        ),
        # 6. Retry violation
        ({"max_retries": 1}, "single_probe_retry_violation"),
        ({"max_retries": 5}, "single_probe_retry_violation"),
        # 7. Fallback provider violation
        ({"fallback_provider": True}, "single_probe_fallback_violation"),
        # 8. Altered base_url
        (
            {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/v2"},
            "invalid_base_url",
        ),
        (
            {"base_url": "http://generativelanguage.googleapis.com/v1beta/openai"},
            "invalid_base_url",
        ),
        (
            {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai?probe=1"},
            "invalid_base_url",
        ),
        (
            {"base_url": "https://evil.com/v1beta/openai"},
            "invalid_base_url",
        ),
        # 9. Altered model
        (
            {"model_id": "gemma-4-unsupported-variant"},
            "invalid_model_id",
        ),
        # 10. Binance env contamination
        (
            {"env": {"BINANCE_KEY": "123"}},
            "exchange_credential_contamination",
        ),
        (
            {"env": {"binance_secret_token": "abc"}},
            "exchange_credential_contamination",
        ),
    ]

    for overrides, expected_err in mutations:
        kwargs: dict[str, Any] = {
            "source_credential_path": source_file,
            "credential_dir": cred_dir,
            "base_url": GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
            "model_id": "gemma-4-31b-it",
            "max_retries": 0,
            "fallback_provider": False,
            "stat_fn": stat_valid,
            "env": clean_env,
            "platform": "linux",
        }
        kwargs.update(overrides)
        report = validate_staging_environment(**kwargs)
        assert report.ready is False, (
            f"Failed to block invalid mutation: {overrides}. Report: {report}"
        )
        assert report.status == "blocked"
        assert len(report.errors) > 0
        assert any(expected_err in err for err in report.errors), (
            f"Expected '{expected_err}' in {report.errors} for {overrides}"
        )


# ==============================================================================
# SUITE E: Systemd Service Hardening & Sandboxing Invariants
# ==============================================================================


def test_service_unit_file_security_properties() -> None:
    """Adversarial audit of deploy/autonomous-futures-creator-staging.service."""
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith(("#", ";"))
    ]
    directives: dict[str, list[str]] = {}
    current_sec = ""
    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            current_sec = line[1:-1]
        elif "=" in line:
            k, v = line.split("=", 1)
            directives.setdefault(f"{current_sec}.{k.strip()}", []).append(v.strip())

    # 1. Enforce Non-Root Execution
    assert directives.get("Service.User") == ["afbot"]
    assert directives.get("Service.Group") == ["afbot"]

    # 2. Strict Filesystem Sandboxing
    assert directives.get("Service.ProtectSystem") == ["strict"]
    assert directives.get("Service.ProtectHome") == ["read-only"]
    assert directives.get("Service.PrivateTmp") == ["yes"]
    assert directives.get("Service.NoNewPrivileges") == ["yes"]

    # 3. Network Isolation / Address Families
    assert directives.get("Service.RestrictAddressFamilies") == ["AF_INET AF_INET6 AF_UNIX"]

    # 4. Dangerous Directives Forbidden
    forbidden_keys = [
        "Service.CapabilityBoundingSet",
        "Service.AmbientCapabilities",
        "Service.ReadWritePaths",
        "Service.ReadWriteDirectories",
        "Service.SupplementaryGroups",
    ]
    for key in forbidden_keys:
        assert key not in directives, f"Dangerous directive {key} present in staging service unit!"

    # 5. Resource Envelope
    assert directives.get("Service.CPUQuota") == ["500%"]
    assert directives.get("Service.MemoryMax") == ["10G"]
    assert directives.get("Service.TimeoutStartSec") == ["120"]
    assert directives.get("Service.Restart") == ["no"]
    assert directives.get("Service.Type") == ["oneshot"]

    # 6. Exchange Isolation
    full_text_lower = content.lower()
    for forbidden_word in ("binance", "fapi", "trade", "exchange", "order"):
        assert forbidden_word not in full_text_lower, (
            f"Forbidden exchange keyword '{forbidden_word}' leaked into service file!"
        )

    # 7. Exact Encrypted Credential Target
    assert directives.get("Service.LoadCredentialEncrypted") == [
        "google_ai_studio_api_key:/etc/autonomous-futures/credentials/google_ai_studio_api_key"
    ]


# ==============================================================================
# SUITE F: Zero Secret Leakage & Scrubbing
# ==============================================================================


def test_canary_secrets_never_leak_in_exceptions_or_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Canary secrets must never appear in reports, json dumps, reprs, or outputs."""
    google_canary = "AIzaSySuperSecretCanaryToken999888777"
    binance_canary = "BinanceSuperSecretCanaryKey111222333"

    cred_dir = tmp_path / "creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(google_canary, encoding="utf-8")

    source_path = tmp_path / "source_key"
    source_path.write_text("encrypted_blob", encoding="utf-8")

    monkeypatch.setenv("BINANCE_API_KEY", binance_canary)

    report = validate_staging_environment(
        source_credential_path=source_path,
        credential_dir=cred_dir,
        skip_source_check=True,
    )

    # 1. Report string representations
    assert google_canary not in str(report)
    assert google_canary not in repr(report)
    assert binance_canary not in str(report)
    assert binance_canary not in repr(report)

    # 2. JSON serialization
    serialized = json.dumps(report.model_dump(mode="json"))
    assert google_canary not in serialized
    assert binance_canary not in serialized

    # 3. CLI execution output
    code = cli_main(
        [
            "--source-credential-path",
            str(source_path),
            "--credential-dir",
            str(cred_dir),
            "--skip-source-check",
        ]
    )
    # Blocked due to Binance key in env
    assert code == 3
    captured = capsys.readouterr()
    assert google_canary not in captured.out
    assert google_canary not in captured.err
    assert binance_canary not in captured.out
    assert binance_canary not in captured.err


# ==============================================================================
# SUITE G: Direct OS Subprocess CLI Invocation
# ==============================================================================


def test_cli_subprocess_invocation_exit_codes(tmp_path: Path) -> None:
    """Execute the CLI as a real OS subprocess to verify true exit codes."""
    script_path = str(_SCRIPT_PATH)

    # 1. Unknown flag -> exit code 2
    res = subprocess.run(
        [sys.executable, script_path, "--definitely-invalid-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 2

    # 2. Missing paths on clean invocation -> exit code 3
    res = subprocess.run(
        [
            sys.executable,
            script_path,
            "--source-credential-path",
            str(tmp_path / "absent_source"),
            "--credential-dir",
            str(tmp_path / "absent_creds"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 3
    data = json.loads(res.stdout)
    assert data["status"] == "blocked"
    assert data["ready"] is False

    # 3. Successful preflight under valid mock environment -> exit code 0
    cred_dir = tmp_path / "valid_creds"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(
        "AIzaSyValidToken123456789012345", encoding="utf-8"
    )
    res = subprocess.run(
        [
            sys.executable,
            script_path,
            "--credential-dir",
            str(cred_dir),
            "--skip-source-check",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ.get("PATH", "")},
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["status"] == "ready_for_staging_probe"
    assert data["ready"] is True


# ==============================================================================
# SUITE H: Boundary Conditions & Character Stress Testing
# ==============================================================================


@pytest.mark.parametrize(
    ("key_text", "should_pass", "err_type"),
    [
        ("1234567890123456789", False, "runtime_credential_invalid_format"),  # 19 chars (boundary)
        ("12345678901234567890", True, None),  # 20 chars (boundary minimum)
        ("123456789012345678901234567890", True, None),  # 30 chars
        ("1234567890 1234567890", False, "runtime_credential_invalid_format"),  # space
        ("1234567890\t1234567890", False, "runtime_credential_invalid_format"),  # tab
        ("1234567890\n1234567890", False, "runtime_credential_invalid_format"),  # newline
        ("1234567890\r1234567890", False, "runtime_credential_invalid_format"),  # CR
        ("1234567890\u00a01234567890", False, "runtime_credential_invalid_format"),  # NBSP
        ("1234567890\u20031234567890", False, "runtime_credential_invalid_format"),  # Em space
    ],
)
def test_runtime_credential_boundary_and_whitespace(
    tmp_path: Path, key_text: str, should_pass: bool, err_type: str | None
) -> None:
    """Assert strict length and whitespace boundary enforcement."""
    cred_dir = tmp_path / f"creds_{abs(hash(key_text))}"
    cred_dir.mkdir()
    (cred_dir / "google_ai_studio_api_key").write_text(key_text, encoding="utf-8")

    report, raw_key = validate_runtime_credential_delivery(cred_dir)
    if should_pass:
        assert raw_key == key_text
        assert report.non_empty is True
        assert report.validation_error is None
    else:
        assert raw_key is None
        assert report.non_empty is False
        assert err_type in (report.validation_error or "")


# ==============================================================================
# SUITE I: Model Validator Consistency & URL Security Assertions
# ==============================================================================


def test_staging_preflight_report_model_consistency_rules() -> None:
    """StagingPreflightReport must enforce internal consistency via Pydantic model validator."""
    dummy_source = EncryptedSourceStoreReport(
        path="/etc/test", exists=True, is_regular_file=True, mode_valid=True, owner_valid=True
    )
    dummy_runtime = RuntimeCredentialReport(
        directory="/run/creds", exists=True, is_regular_file=True, non_empty=True
    )
    dummy_safety = OfflineSafetyInvariants()
    dummy_probe = SingleProbeConstraints(
        base_url=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        model_id="gemma-4-31b-it",
    )

    # 1. ready=True with status="blocked" must fail
    with pytest.raises(ValueError, match="ready report must have status 'ready_for_staging_probe'"):
        StagingPreflightReport(
            ready=True,
            status="blocked",
            source_store=dummy_source,
            runtime_credential=dummy_runtime,
            offline_safety=dummy_safety,
            probe_constraints=dummy_probe,
        )

    # 2. ready=True with errors must fail
    with pytest.raises(ValueError, match="ready report cannot have errors"):
        StagingPreflightReport(
            ready=True,
            status="ready_for_staging_probe",
            errors=("some_error",),
            source_store=dummy_source,
            runtime_credential=dummy_runtime,
            offline_safety=dummy_safety,
            probe_constraints=dummy_probe,
        )

    # 3. ready=False with status="ready_for_staging_probe" must fail
    with pytest.raises(ValueError, match="unready report must have status 'blocked'"):
        StagingPreflightReport(
            ready=False,
            status="ready_for_staging_probe",
            source_store=dummy_source,
            runtime_credential=dummy_runtime,
            offline_safety=dummy_safety,
            probe_constraints=dummy_probe,
        )


@pytest.mark.parametrize(
    "host_variant",
    [
        "https://generativelanguage.googleapis.com:443/v1beta/openai",  # explicit port
        "https://generativelanguage.googleapis.com:8443/v1beta/openai",  # alternate port
        "https://user:pass@generativelanguage.googleapis.com/v1beta/openai",  # userinfo
        "https://generativelanguage.googleapis.com.evil.com/v1beta/openai",  # subdomain affix
        "https://attacker.com/generativelanguage.googleapis.com/v1beta/openai",  # path prepend
        "https://generativelanguage.googleapis.com/v1beta/openai/extra",  # path append
        "https://generativelanguage.googleapis.com/v1",  # shortened path
    ],
)
def test_url_injection_variants_rejected(host_variant: str) -> None:
    """Strict URL validation must reject all port, userinfo, and affix variations."""
    res = validate_single_probe_constraints(
        base_url=host_variant,
        model_id="gemma-4-31b-it",
        max_retries=0,
        fallback_provider=False,
    )
    assert res.validation_error is not None
    assert "invalid_base_url" in res.validation_error
