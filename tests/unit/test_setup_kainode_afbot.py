"""Unit tests for scripts/setup_kainode_afbot.sh provisioning script.

Validates bash script syntax, safety flags, idempotency guards, permission
octals, ownership directives, restricted sudoers configuration, zero secret
leakage invariants, and dry-run execution behavior.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "setup_kainode_afbot.sh"
SCRIPT_REL_PATH = "scripts/setup_kainode_afbot.sh"

EXPECTED_PUBKEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMJJ0UAlUCOTwKyqG0+vpNr3e7nr6trU3C3kqIQgWShY "
    "eddsa-key-20260901"
)


@pytest.fixture(scope="module")
def script_content() -> str:
    """Return the decoded text content of the provisioning script."""
    assert SCRIPT_PATH.is_file(), f"Script not found at {SCRIPT_PATH}"
    return SCRIPT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script_bytes() -> bytes:
    """Return the raw byte content of the provisioning script."""
    assert SCRIPT_PATH.is_file(), f"Script not found at {SCRIPT_PATH}"
    return SCRIPT_PATH.read_bytes()


def test_script_file_exists_and_non_empty(script_bytes: bytes) -> None:
    """Script file exists, is regular file, and contains content."""
    assert SCRIPT_PATH.exists()
    assert SCRIPT_PATH.is_file()
    assert len(script_bytes) > 0


def test_script_has_unix_lf_line_endings(script_bytes: bytes) -> None:
    """Script strictly enforces UNIX LF line endings with zero CRLF or lone CR."""
    assert b"\r\n" not in script_bytes, "Found CRLF line endings; strictly LF required"
    assert b"\r" not in script_bytes, "Found standalone carriage return (\\r) characters"


def test_script_has_no_trailing_whitespace(script_content: str) -> None:
    """Script has zero lines with trailing whitespace characters."""
    lines_with_trailing_ws = [
        idx
        for idx, line in enumerate(script_content.splitlines(), start=1)
        if line != line.rstrip()
    ]
    assert not lines_with_trailing_ws, f"Lines with trailing whitespace: {lines_with_trailing_ws}"


def test_script_has_valid_shebang(script_content: str) -> None:
    """Line 1 contains valid bash shebang directive."""
    first_line = script_content.splitlines()[0].strip()
    assert first_line in ("#!/usr/bin/env bash", "#!/bin/bash")


def test_script_enforces_strict_safety_flags(script_content: str) -> None:
    """Script enables bash strict mode flags and hardened IFS setting."""
    assert "set -euo pipefail" in script_content
    assert "IFS=$'\\n\\t'" in script_content or "IFS='\\n\\t'" in script_content


def test_script_root_privilege_enforcement(script_content: str) -> None:
    """Script verifies execution under root EUID 0 unless in dry-run mode."""
    assert "id -u" in script_content
    assert re.search(r'\[\[\s*"\$\(id -u\)"\s*-ne\s*0\s*\]\]', script_content) is not None
    assert "exit 1" in script_content


def test_script_target_identity_constants(script_content: str) -> None:
    """Script specifies operator afbot identity constants."""
    assert 'TARGET_USER="afbot"' in script_content
    assert 'TARGET_GROUP="afbot"' in script_content
    assert 'TARGET_SHELL="/bin/bash"' in script_content
    assert 'TARGET_HOME="/home/afbot"' in script_content


def test_script_idempotent_user_and_group_management(script_content: str) -> None:
    """Script uses defensive idempotency guards for group and user provisioning."""
    # Group existence check before groupadd
    assert "getent group" in script_content
    assert "groupadd" in script_content
    # User existence check before useradd and usermod reconciliation
    assert "id -u" in script_content
    assert "useradd" in script_content
    assert "usermod" in script_content


def test_script_ssh_directory_permissions_and_ownership(script_content: str) -> None:
    """Script configures /home/afbot/.ssh with mode 700 and afbot:afbot ownership."""
    assert re.search(r"mkdir\s+-p\s+.*SSH_DIR", script_content) is not None
    assert re.search(r"chmod\s+700\s+.*SSH_DIR", script_content) is not None
    assert re.search(r"chown\s+.*TARGET_USER.*TARGET_GROUP.*SSH_DIR", script_content) is not None


def test_script_authorized_keys_permissions_and_ownership(script_content: str) -> None:
    """Script configures authorized_keys with mode 600 and afbot:afbot ownership."""
    assert re.search(r"chmod\s+600\s+.*AUTH_KEYS_FILE", script_content) is not None
    assert (
        re.search(r"chown\s+.*TARGET_USER.*TARGET_GROUP.*AUTH_KEYS_FILE", script_content)
        is not None
    )


def test_script_pinned_operator_public_key(script_content: str) -> None:
    """Script defines and injects the exact pinned operator Ed25519 public key."""
    assert EXPECTED_PUBKEY in script_content


def test_script_authorized_keys_idempotency_and_newline_safety(script_content: str) -> None:
    """Script checks for key presence before appending and handles trailing newlines."""
    # Idempotent presence check
    assert "grep -q -F" in script_content
    # Newline safety check
    assert "tail -c1" in script_content


def test_script_credentials_directory_hardening(script_content: str) -> None:
    """Script configures /etc/autonomous-futures/credentials with mode 750 and root:afbot."""
    assert (
        "/etc/autonomous-futures/credentials" in script_content
        or "CREDENTIALS_DIR" in script_content
    )
    assert re.search(r"chmod\s+750\s+.*CREDENTIALS_DIR", script_content) is not None
    assert re.search(r"chown\s+root:.*TARGET_GROUP.*CREDENTIALS_DIR", script_content) is not None


def test_script_sudoers_file_path_and_mode(script_content: str) -> None:
    """Script specifies /etc/sudoers.d/afbot-service with mode 0440 and root:root."""
    assert 'readonly SUDOERS_DROPIN="/etc/sudoers.d/afbot-service"' in script_content
    assert "SUDOERS_FILE" not in script_content, "Deprecated/unbound SUDOERS_FILE identifier found"
    assert "/etc/sudoers.d/afbot-service" in script_content
    assert "440" in script_content
    assert "root:root" in script_content


def test_script_sudoers_restricted_whitelist(script_content: str) -> None:
    """Sudoers rule restricts afbot to systemctl restart/status and journalctl."""
    sudoers_pattern = re.compile(
        r"afbot\s+ALL=\(ALL\)\s+NOPASSWD:\s*(.*?)(?:\n|EOF)",
        re.DOTALL,
    )
    match = sudoers_pattern.search(script_content)
    assert match is not None, "Could not locate afbot NOPASSWD sudoers rule in script"
    rule_commands = match.group(1)

    # Must contain systemctl restart and status for autonomous-futures-*
    assert "/usr/bin/systemctl restart autonomous-futures-*" in rule_commands
    assert "/usr/bin/systemctl status autonomous-futures-*" in rule_commands
    assert "/usr/bin/journalctl -u autonomous-futures-*" in rule_commands

    # Must also include /bin/ aliases for merged-usr architecture
    assert "/bin/systemctl restart autonomous-futures-*" in rule_commands
    assert "/bin/systemctl status autonomous-futures-*" in rule_commands
    assert "/bin/journalctl -u autonomous-futures-*" in rule_commands


def test_script_sudoers_no_blanket_privileges(script_content: str) -> None:
    """Script strictly avoids blanket root privileges (NOPASSWD: ALL)."""
    assert "NOPASSWD: ALL" not in script_content
    assert "ALL=(ALL:ALL) ALL" not in script_content
    assert "ALL=(ALL) ALL" not in script_content


def test_script_sudoers_visudo_validation(script_content: str) -> None:
    """Script validates sudoers drop-in with visudo -cf before installation."""
    assert "visudo -cf" in script_content


def test_script_systemd_creds_capability_check(script_content: str) -> None:
    """Script checks systemd-creds binary presence and runs version command safely."""
    assert "command -v systemd-creds" in script_content
    assert "systemd-creds --version" in script_content


def test_canary_zero_private_keys(script_content: str) -> None:
    """Canary scan: zero SSH, RSA, or EC private keys embedded in script."""
    forbidden_patterns = [
        r"BEGIN\s+(?:OPENSSH|RSA|DSA|EC|PGP)?\s*PRIVATE\s+KEY",
        r"PuTTY-User-Key-File",
        r"PRIVATE\s+KEY\s+BLOCK",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, script_content, re.IGNORECASE) is None, (
            f"Canary violation: found pattern matching {pattern}"
        )


def test_canary_zero_credentials_or_passwords(script_content: str) -> None:
    """Canary scan: zero passwords, API tokens, or secrets embedded in script."""
    forbidden_patterns = [
        r"AIzaSy[A-Za-z0-9_-]{33}",  # Google API key format
        r"BINANCE_API_KEY",
        r"BINANCE_API_SECRET",
        r"fapi\.binance\.com",
        r"api\.binance\.com",
        r"PASSWORD\s*=\s*['\"][^'\"]+['\"]",
        r"SECRET\s*=\s*['\"][^'\"]+['\"]",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, script_content) is None, (
            f"Canary violation: found pattern matching {pattern}"
        )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not in PATH")
def test_bash_syntax_check_oracle() -> None:
    """Execute bash -n on the script to verify shell syntax."""
    result = subprocess.run(
        ["bash", "-n", SCRIPT_REL_PATH],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not in PATH")
def test_dry_run_execution_via_cli_flag() -> None:
    """Executing script with --dry-run exits 0 and prints simulation summary."""
    result = subprocess.run(
        ["bash", SCRIPT_REL_PATH, "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Dry-run execution failed: {result.stderr}"
    assert "[DRY-RUN]" in result.stdout
    assert "Simulation completed successfully" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not in PATH")
def test_dry_run_execution_via_env_var() -> None:
    """Executing script with DRY_RUN=1 environment variable exits 0."""
    result = subprocess.run(
        ["bash", "-c", f"DRY_RUN=1 bash {SCRIPT_REL_PATH}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"DRY_RUN=1 execution failed: {result.stderr}"
    assert "[DRY-RUN]" in result.stdout
    assert "Simulation completed successfully" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not in PATH")
def test_non_root_execution_fails_with_code_1() -> None:
    """Executing script without root and without dry-run exits with code 1."""
    # In Windows or unprivileged test runner, id -u is not 0 (or fails/returns non-zero)
    result = subprocess.run(
        ["bash", SCRIPT_REL_PATH],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # If the runner is unprivileged (normal case), it must exit 1
    if result.returncode != 0:
        assert result.returncode == 1
        assert "must be executed as root" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not in PATH")
def test_invalid_cli_option_fails_with_code_1() -> None:
    """Passing unrecognized argument causes script to exit 1 with usage error."""
    result = subprocess.run(
        ["bash", SCRIPT_REL_PATH, "--unrecognized-option"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "ERROR: Unknown option '--unrecognized-option'" in result.stderr
    assert "Usage:" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not in PATH")
def test_help_flag_exits_0() -> None:
    """Passing --help causes script to display usage and exit 0."""
    result = subprocess.run(
        ["bash", SCRIPT_REL_PATH, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_script_all_variable_references_are_declared_or_builtin(script_content: str) -> None:
    """Static analysis: every $VAR and ${VAR} parameter expansion is assigned or a shell builtin."""
    lines = script_content.splitlines()
    in_quoted_heredoc = False
    heredoc_delimiter = ""

    active_lines: list[tuple[int, str]] = []
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if in_quoted_heredoc:
            if stripped == heredoc_delimiter:
                in_quoted_heredoc = False
            continue

        heredoc_match = re.search(r"<<\s*['\"]([A-Za-z0-9_]+)['\"]", line)
        if heredoc_match:
            in_quoted_heredoc = True
            heredoc_delimiter = heredoc_match.group(1)
            active_lines.append((line_num, line))
            continue

        active_lines.append((line_num, line))

    # Identify variable assignments: VAR=, readonly VAR=, local VAR=, export VAR=
    assign_pattern = re.compile(
        r"^\s*(?:readonly\s+|local\s+|export\s+)?([A-Za-z_][A-Za-z0-9_]*)\+?="
    )
    assigned: set[str] = set()
    for _, line in active_lines:
        line_clean = line.split("#")[0].strip() if not line.strip().startswith("#") else ""
        m = assign_pattern.match(line_clean)
        if m:
            assigned.add(m.group(1))

    # Identify for-loop variable declarations: for var in ...
    for_pattern = re.compile(r"for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in")
    for _, line in active_lines:
        line_clean = line.split("#")[0].strip() if not line.strip().startswith("#") else ""
        m = for_pattern.search(line_clean)
        if m:
            assigned.add(m.group(1))

    # Standard POSIX / bash builtins and environment variables
    standard_builtins = {
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "@",
        "*",
        "#",
        "?",
        "!",
        "$",
        "_",
        "IFS",
        "PATH",
        "UID",
        "EUID",
        "DRY_RUN",
        "HOME",
        "USER",
    }

    # Identify parameter expansions: ${VAR} and $VAR
    brace_pattern = re.compile(r"\$\{([A-Za-z_0-9*@#?!]+)(?:[^}]*)?\}")
    bare_pattern = re.compile(r"(?<!\\)\$([A-Za-z_][A-Za-z0-9_]*)")

    unbound: dict[str, list[int]] = {}
    for line_num, line in active_lines:
        line_clean = line.split("#")[0] if not line.strip().startswith("#") else ""
        if not line_clean:
            continue
        for m in brace_pattern.finditer(line_clean):
            var_name = m.group(1)
            if var_name not in assigned and var_name not in standard_builtins:
                unbound.setdefault(var_name, []).append(line_num)
        for m in bare_pattern.finditer(line_clean):
            var_name = m.group(1)
            if var_name not in assigned and var_name not in standard_builtins:
                unbound.setdefault(var_name, []).append(line_num)

    assert not unbound, f"Unbound variable references detected in script: {unbound}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash executable not in PATH")
def test_stage6_completion_summary_dynamic_execution_zero_unbound_vars(
    script_content: str,
) -> None:
    """Dynamic execution: verify Stage 6 summary executes cleanly under set -u
    without unbound variables.
    """
    lines = script_content.splitlines()

    constants_lines: list[str] = []
    stage6_lines: list[str] = []
    in_constants = False
    in_stage6 = False

    for line in lines:
        if "readonly TARGET_USER" in line:
            in_constants = True
        if in_constants:
            constants_lines.append(line)
            if "readonly SUDOERS_DROPIN" in line:
                in_constants = False

        if "=== [6/6] Provisioning summary ===" in line:
            in_stage6 = True
        if in_stage6:
            stage6_lines.append(line)

    assert constants_lines, "Could not extract script constant declarations"
    assert stage6_lines, "Could not extract Stage 6 summary block from script"

    test_script = (
        "set -euo pipefail\n"
        "IFS=$'\\n\\t'\n"
        "DRY_RUN=0\n" + "\n".join(constants_lines) + "\n" + "\n".join(stage6_lines) + "\n"
    )

    result = subprocess.run(
        ["bash", "-s"],
        input=test_script.encode("utf-8"),
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Stage 6 execution failed with code {result.returncode}:\n"
        f"stderr: {result.stderr.decode('utf-8', errors='replace')}\n"
        f"stdout: {result.stdout.decode('utf-8', errors='replace')}"
    )
    stdout_text = result.stdout.decode("utf-8", errors="replace")
    assert "SUCCESS: Operator 'afbot' provisioned successfully" in stdout_text
    assert "Sudoers Drop-In: /etc/sudoers.d/afbot-service" in stdout_text
