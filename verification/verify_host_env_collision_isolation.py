"""Verification script for Focus 3: Host .env collision isolation."""

import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path("B:/")
HOST_ENV_PATH = REPO_ROOT / ".env"

had_env_originally = HOST_ENV_PATH.exists()
orig_env_bytes = HOST_ENV_PATH.read_bytes() if had_env_originally else None

results = {}

active_env_content = (
    "# Active host credentials that must NEVER pollute or leak into isolated tests\n"
    "GOOGLE_API_KEY=AIzaSyActiveHostEnvKeyThatMustNotPollute12345\n"
    "GEMINI_API_KEY=AIzaSyActiveHostGeminiKeyThatMustNotPollute12345\n"
    "GOOGLE_AI_STUDIO_API_KEY=AIzaSyActiveStudioKeyThatMustNotPollute12345\n"
)

try:
    print("Writing active .env file to disk at B:\\.env...")
    HOST_ENV_PATH.write_text(active_env_content, encoding="utf-8")
    assert HOST_ENV_PATH.exists(), "Failed to create .env on disk"

    print("Running unit missing credentials tests with active .env on disk...")
    cmd_unit = [
        "uv", "run", "--locked", "pytest",
        "tests/unit/test_google_ai_studio_cycle_integration.py",
        "-k", "missing_credentials",
        "-v",
    ]
    proc_u = subprocess.run(
        cmd_unit,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print(f"Unit missing credentials returncode: {proc_u.returncode}")
    print(proc_u.stdout)
    assert proc_u.returncode == 0, f"Unit missing credentials failed with active .env:\n{proc_u.stdout}\n{proc_u.stderr}"
    assert "test_resolve_credential_raises_missing_credentials_error PASSED" in proc_u.stdout
    assert "test_cli_main_missing_credentials_exits_code_3_with_clean_json PASSED" in proc_u.stdout
    results["unit_missing_credentials_with_active_env"] = "PASSED"

    print("Running integration missing credentials tests with active .env on disk...")
    cmd_integ = [
        "uv", "run", "--locked", "pytest",
        "tests/integration/test_run_autonomous_cycle_cli.py",
        "-k", "missing_credentials",
        "-v",
    ]
    proc_i = subprocess.run(
        cmd_integ,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print(f"Integration missing credentials returncode: {proc_i.returncode}")
    print(proc_i.stdout)
    assert proc_i.returncode == 0, f"Integration missing credentials failed with active .env:\n{proc_i.stdout}\n{proc_i.stderr}"
    assert "test_cli_missing_credentials_exit_code_3 PASSED" in proc_i.stdout
    results["integration_missing_credentials_with_active_env"] = "PASSED"

finally:
    if had_env_originally:
        HOST_ENV_PATH.write_bytes(orig_env_bytes)
    elif HOST_ENV_PATH.exists():
        HOST_ENV_PATH.unlink()

assert not HOST_ENV_PATH.exists(), "Failed to clean up host .env file!"
print("\n==========================================")
print("PASS: Focus 3 Host .env collision isolation fully verified!")
print("Host .env cleanly created, tested, and unlinked.")
print("==========================================")
