"""Milestone 5 Adversarial Challenger Verification Suite.

Empirically challenges:
1. Focus 1: Offline network isolation (socket blocking across tests; confirm 0 socket connects).
2. Focus 2: Stream leak interception (stdout/stderr leak injection fails test with AssertionError).
3. Focus 3: Host .env collision isolation (missing credentials tests pass with active .env file on disk).
4. Static Quality Gates & Exit Cost Audit: ruff check, ruff format, mypy, exit cost baseline.
5. Issues explicit verdict: APPROVE or REQUEST_CHANGES.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import time

REPO_ROOT = pathlib.Path("B:/")
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_autonomous_cycle.py"
PROVIDER_PATH = REPO_ROOT / "src" / "autonomous_futures" / "research" / "google_ai_studio_provider.py"
TEST_UNIT_PATH = REPO_ROOT / "tests" / "unit" / "test_google_ai_studio_cycle_integration.py"
TEST_INTEG_PATH = REPO_ROOT / "tests" / "integration" / "test_run_autonomous_cycle_cli.py"

results = {
    "offline_network_isolation": {},
    "stream_leak_interception": {},
    "host_env_collision_isolation": {},
    "quality_gates": {},
    "defects_found": [],
    "overall_verdict": "PENDING",
}


def clean_pycache() -> None:
    for p in REPO_ROOT.glob("**/__pycache__"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def run_cmd(cmd, check_rc=None):
    start = time.perf_counter()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - start
    if check_rc is not None:
        assert proc.returncode == check_rc, (
            f"Expected rc={check_rc}, got {proc.returncode}.\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.returncode, elapsed, proc.stdout, proc.stderr


def run_pytest(args, check_rc=None):
    return run_cmd(["uv", "run", "--locked", "pytest"] + args, check_rc=check_rc)


print("=" * 70)
print("STARTING EMPIRICAL CHALLENGER VERIFICATION: MILESTONE 5")
print("=" * 70)

clean_pycache()

# ==============================================================================
# 1. OFFLINE NETWORK ISOLATION RE-VERIFICATION
# ==============================================================================
print("\n--- [1/4] Re-verifying Offline Network Isolation (Socket Interception) ---")

socket_runner_script = REPO_ROOT / "verification" / "_socket_intercept_runner.py"
socket_runner_code = '''
import sys
import socket
import pytest

socket_attempts = []
orig_connect = socket.socket.connect
orig_connect_ex = socket.socket.connect_ex
orig_create_connection = socket.create_connection
orig_getaddrinfo = socket.getaddrinfo

def blocked_connect(self, address):
    socket_attempts.append(("connect", address))
    raise RuntimeError(f"BLOCKED_NETWORK_SOCKET_CONNECT: {address}")

def blocked_connect_ex(self, address):
    socket_attempts.append(("connect_ex", address))
    return 111  # ECONNREFUSED

def blocked_create_connection(address, *args, **kwargs):
    socket_attempts.append(("create_connection", address))
    raise RuntimeError(f"BLOCKED_NETWORK_CREATE_CONNECTION: {address}")

def blocked_getaddrinfo(host, port, *args, **kwargs):
    socket_attempts.append(("getaddrinfo", (host, port)))
    raise RuntimeError(f"BLOCKED_NETWORK_GETADDRINFO: {host}:{port}")

# Oracle self-check: verify interceptor actually catches connections
if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
    socket.socket.connect = blocked_connect
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("8.8.8.8", 53))
    except RuntimeError as e:
        assert "BLOCKED_NETWORK_SOCKET_CONNECT" in str(e)
        assert len(socket_attempts) == 1
        print("ORACLE_SELF_TEST_PASSED")
        sys.exit(0)
    print("ORACLE_SELF_TEST_FAILED")
    sys.exit(1)

# Apply interception
socket.socket.connect = blocked_connect
socket.socket.connect_ex = blocked_connect_ex
socket.create_connection = blocked_create_connection
socket.getaddrinfo = blocked_getaddrinfo

exit_code = pytest.main([
    "-o", "testpaths=tests",
    "tests/unit/test_google_ai_studio_cycle_integration.py",
    "tests/integration/test_run_autonomous_cycle_cli.py",
    "-q",
    "--tb=short"
])

print(f"\\n__SOCKET_ATTEMPTS_COUNT__:{len(socket_attempts)}")
for kind, target in socket_attempts:
    print(f"__SOCKET_ATTEMPT__:{kind}:{target}")

sys.exit(exit_code)
'''

socket_runner_script.write_text(socket_runner_code, encoding="utf-8")

try:
    rc_oracle, el_oracle, out_oracle, err_oracle = run_cmd(
        ["uv", "run", "python", str(socket_runner_script), "--self-test"],
        check_rc=0,
    )
    assert "ORACLE_SELF_TEST_PASSED" in out_oracle
    print("PASS: Socket interceptor oracle self-test verified (interception works).")

    rc_sock, el_sock, out_sock, err_sock = run_cmd(
        ["uv", "run", "python", str(socket_runner_script)]
    )
    print(f"Socket isolation test executed in {el_sock:.2f}s with rc={rc_sock}")

    match_count = re.search(r"__SOCKET_ATTEMPTS_COUNT__:(\d+)", out_sock)
    attempts_count = int(match_count.group(1)) if match_count else -1

    print(f"Captured socket connection attempts: {attempts_count}")
    has_0_attempts = (attempts_count == 0)

    results["offline_network_isolation"] = {
        "status": "PASS" if has_0_attempts else "FAIL",
        "socket_connects_attempted": attempts_count,
        "oracle_verified": True,
        "pytest_rc": rc_sock,
        "duration_s": el_sock,
    }

    if has_0_attempts:
        print("PASS: Focus 1 Offline Network Isolation Verified: 0 socket connects attempted.")
    else:
        print(f"FAIL: Focus 1 Offline Network Isolation: {attempts_count} socket connects detected!")
        results["defects_found"].append(f"Offline network isolation breach: {attempts_count} socket connects attempted.")

    if rc_sock != 0:
        print(f"NOTE: Pytest exited with rc={rc_sock} under socket interception.")
        # Check why pytest failed
        if "FAILED" in out_sock:
            lines = [l for l in out_sock.splitlines() if "FAILED" in l]
            for l in lines:
                print(f"  FAILED TEST: {l}")
                results["defects_found"].append(f"Target test suite failure: {l.strip()}")
finally:
    if socket_runner_script.exists():
        socket_runner_script.unlink()

# ==============================================================================
# 2. STREAM LEAK INTERCEPTION RE-VERIFICATION
# ==============================================================================
print("\n--- [2/4] Re-verifying Stream Leak Interception (AssertionError on Injected Leaks) ---")

orig_integ_content = TEST_INTEG_PATH.read_text(encoding="utf-8")
orig_unit_content = TEST_UNIT_PATH.read_text(encoding="utf-8")

# 2.1 Stdout Bearer Token Leak Injection in test_cli_end_to_end_google_ai_studio_mocked
try:
    old_target = "    ret = run_cli_main(args)\n    assert ret == 0"
    new_target = (
        "    ret = run_cli_main(args)\n"
        "    print('LEAK_STDOUT: Bearer ya29.a0AfH6SM_InjectedEmpiricalChallengerStdoutToken12345')\n"
        "    assert ret == 0"
    )
    assert old_target in orig_integ_content, "Target block for stdout leak not found in integration test!"
    mutated = orig_integ_content.replace(old_target, new_target)
    TEST_INTEG_PATH.write_text(mutated, encoding="utf-8")
    clean_pycache()

    rc, elapsed, stdout, stderr = run_pytest([
        "tests/integration/test_run_autonomous_cycle_cli.py",
        "-k", "test_cli_end_to_end_google_ai_studio_mocked",
        "-q",
    ])
    caught = (rc == 1 and "FAILED" in stdout and ("AssertionError" in stdout or "assert" in stdout))
    print(f"2.1 Stdout Bearer leak injection: caught={caught} (rc={rc}, elapsed={elapsed:.2f}s)")
    results["stream_leak_interception"]["stdout_bearer_leak"] = {
        "caught": caught,
        "rc": rc,
        "failure_type": "AssertionError" if caught else "NONE",
    }
finally:
    TEST_INTEG_PATH.write_text(orig_integ_content, encoding="utf-8")
    clean_pycache()

# 2.2 Stderr AIzaSy Key Leak Injection in test_cli_end_to_end_google_ai_studio_mocked
try:
    old_target = "    ret = run_cli_main(args)\n    assert ret == 0"
    new_target = (
        "    ret = run_cli_main(args)\n"
        "    sys.stderr.write('LEAK_STDERR: AIzaSyInjectedEmpiricalChallengerStderrKey12345\\n')\n"
        "    assert ret == 0"
    )
    assert old_target in orig_integ_content, "Target block for stderr leak not found in integration test!"
    mutated = orig_integ_content.replace(old_target, new_target)
    TEST_INTEG_PATH.write_text(mutated, encoding="utf-8")
    clean_pycache()

    rc, elapsed, stdout, stderr = run_pytest([
        "tests/integration/test_run_autonomous_cycle_cli.py",
        "-k", "test_cli_end_to_end_google_ai_studio_mocked",
        "-q",
    ])
    caught = (rc == 1 and "FAILED" in stdout and ("AssertionError" in stdout or "assert" in stdout))
    print(f"2.2 Stderr AIzaSy leak injection: caught={caught} (rc={rc}, elapsed={elapsed:.2f}s)")
    results["stream_leak_interception"]["stderr_aizasy_leak"] = {
        "caught": caught,
        "rc": rc,
        "failure_type": "AssertionError" if caught else "NONE",
    }
finally:
    TEST_INTEG_PATH.write_text(orig_integ_content, encoding="utf-8")
    clean_pycache()

# 2.3 Stdout Leak Injection in Provider API Error Path (test_cli_provider_api_error_exit_code_3)
try:
    old_target = "    ret = run_cli_main(args)\n    assert ret == 3"
    new_target = (
        "    ret = run_cli_main(args)\n"
        "    print('LEAK_ERROR_STDOUT: Bearer ya29.a0AfH6SM_ErrorLeakToken12345')\n"
        "    assert ret == 3"
    )
    assert old_target in orig_integ_content, "Target block for error stdout leak not found in integration test!"
    mutated = orig_integ_content.replace(old_target, new_target)
    TEST_INTEG_PATH.write_text(mutated, encoding="utf-8")
    clean_pycache()

    rc, elapsed, stdout, stderr = run_pytest([
        "tests/integration/test_run_autonomous_cycle_cli.py",
        "-k", "test_cli_provider_api_error_exit_code_3",
        "-q",
    ])
    caught = (rc == 1 and "FAILED" in stdout and ("AssertionError" in stdout or "assert" in stdout))
    print(f"2.3 Error path stdout leak injection: caught={caught} (rc={rc}, elapsed={elapsed:.2f}s)")
    results["stream_leak_interception"]["error_path_stdout_leak"] = {
        "caught": caught,
        "rc": rc,
        "failure_type": "AssertionError" if caught else "NONE",
    }
finally:
    TEST_INTEG_PATH.write_text(orig_integ_content, encoding="utf-8")
    clean_pycache()

# 2.4 Stderr Leak Injection in Provider API Error Path (test_cli_provider_api_error_exit_code_3)
try:
    old_target = "    ret = run_cli_main(args)\n    assert ret == 3"
    new_target = (
        "    ret = run_cli_main(args)\n"
        "    sys.stderr.write('LEAK_ERROR_STDERR: AIzaSyErrorStderrKey1234567890\\n')\n"
        "    assert ret == 3"
    )
    assert old_target in orig_integ_content, "Target block for error stderr leak not found in integration test!"
    mutated = orig_integ_content.replace(old_target, new_target)
    TEST_INTEG_PATH.write_text(mutated, encoding="utf-8")
    clean_pycache()

    rc, elapsed, stdout, stderr = run_pytest([
        "tests/integration/test_run_autonomous_cycle_cli.py",
        "-k", "test_cli_provider_api_error_exit_code_3",
        "-q",
    ])
    caught = (rc == 1 and "FAILED" in stdout and ("AssertionError" in stdout or "assert" in stdout))
    print(f"2.4 Error path stderr leak injection: caught={caught} (rc={rc}, elapsed={elapsed:.2f}s)")
    results["stream_leak_interception"]["error_path_stderr_leak"] = {
        "caught": caught,
        "rc": rc,
        "failure_type": "AssertionError" if caught else "NONE",
    }
finally:
    TEST_INTEG_PATH.write_text(orig_integ_content, encoding="utf-8")
    clean_pycache()

# 2.5 Unit Test Stream Leak Injection in test_cli_main_missing_credentials_exits_code_3_with_clean_json
try:
    old_target = "    ret = run_cli_main(\n        [\n            \"--symbol\",\n            \"BTCUSDT\",\n            \"--provider\",\n            \"google_ai_studio\",\n            \"--feedback-path\",\n            str(fb_path),\n        ]\n    )\n    assert ret == 3"
    new_target = (
        "    ret = run_cli_main(\n"
        "        [\n"
        "            \"--symbol\",\n"
        "            \"BTCUSDT\",\n"
        "            \"--provider\",\n"
        "            \"google_ai_studio\",\n"
        "            \"--feedback-path\",\n"
        "            str(fb_path),\n"
        "        ]\n"
        "    )\n"
        "    print('UNIT_LEAK_STDOUT: Bearer ya29.unit_leak_token_12345')\n"
        "    assert ret == 3"
    )
    assert old_target in orig_unit_content, "Target block for unit stdout leak not found!"
    mutated = orig_unit_content.replace(old_target, new_target)
    TEST_UNIT_PATH.write_text(mutated, encoding="utf-8")
    clean_pycache()

    rc, elapsed, stdout, stderr = run_pytest([
        "tests/unit/test_google_ai_studio_cycle_integration.py",
        "-k", "test_cli_main_missing_credentials_exits_code_3_with_clean_json",
        "-q",
    ])
    caught = (rc == 1 and "FAILED" in stdout and ("AssertionError" in stdout or "assert" in stdout))
    print(f"2.5 Unit test stdout leak injection: caught={caught} (rc={rc}, elapsed={elapsed:.2f}s)")
    results["stream_leak_interception"]["unit_stdout_leak"] = {
        "caught": caught,
        "rc": rc,
        "failure_type": "AssertionError" if caught else "NONE",
    }
finally:
    TEST_UNIT_PATH.write_text(orig_unit_content, encoding="utf-8")
    clean_pycache()

all_leaks_caught = all(s.get("caught", False) for s in results["stream_leak_interception"].values())
if all_leaks_caught:
    print("PASS: Focus 2 Stream Leak Interception Verified: All 5 injected secret leaks trigger AssertionError.")
else:
    print("FAIL: Focus 2 Stream Leak Interception: At least one leak injection was not caught!")
    results["defects_found"].append("Stream leak interception failed to catch one or more injected secrets.")

# ==============================================================================
# 3. HOST .ENV COLLISION ISOLATION RE-VERIFICATION
# ==============================================================================
print("\n--- [3/4] Re-verifying Host .env Collision Isolation ---")

env_path = REPO_ROOT / ".env"
had_env_initially = env_path.exists()
initial_env_content = env_path.read_text(encoding="utf-8") if had_env_initially else None

try:
    env_content = (
        "# Active host credentials that must NEVER pollute or leak into tests\n"
        "GOOGLE_API_KEY=AIzaSyActiveHostEnvKeyThatMustNotPollute12345\n"
        "GEMINI_API_KEY=AIzaSyActiveHostGeminiKeyThatMustNotPollute12345\n"
        "GOOGLE_AI_STUDIO_API_KEY=AIzaSyActiveStudioKeyThatMustNotPollute12345\n"
    )
    env_path.write_text(env_content, encoding="utf-8")
    assert env_path.exists(), "Failed to create active .env on disk!"
    clean_pycache()

    rc_u, el_u, out_u, err_u = run_pytest([
        "tests/unit/test_google_ai_studio_cycle_integration.py",
        "-k", "missing_credentials",
        "-v",
    ], check_rc=0)
    u_passed = ("test_resolve_credential_raises_missing_credentials_error PASSED" in out_u and
                "test_cli_main_missing_credentials_exits_code_3_with_clean_json PASSED" in out_u)
    print(f"Unit missing credentials tests with active .env: passed={u_passed} ({el_u:.2f}s)")

    rc_i, el_i, out_i, err_i = run_pytest([
        "tests/integration/test_run_autonomous_cycle_cli.py",
        "-k", "missing_credentials",
        "-v",
    ], check_rc=0)
    i_passed = "test_cli_missing_credentials_exit_code_3 PASSED" in out_i
    print(f"Integration missing credentials tests with active .env: passed={i_passed} ({el_i:.2f}s)")

    env_isolated = u_passed and i_passed
    results["host_env_collision_isolation"] = {
        "status": "PASS" if env_isolated else "FAIL",
        "active_env_created": True,
        "unit_missing_creds_passed": u_passed,
        "integration_missing_creds_passed": i_passed,
    }
    if env_isolated:
        print("PASS: Focus 3 Host .env Collision Isolation Verified: tests pass cleanly with active .env on disk.")
    else:
        print("FAIL: Focus 3 Host .env Collision Isolation: tests failed or picked up ambient .env!")
        results["defects_found"].append("Host .env collision isolation failure.")
finally:
    if had_env_initially:
        env_path.write_text(initial_env_content, encoding="utf-8")
    elif env_path.exists():
        env_path.unlink()
    clean_pycache()

assert not env_path.exists(), "Failed to clean up .env file after test!"

# ==============================================================================
# 4. STATIC QUALITY GATES & EXIT COST AUDIT
# ==============================================================================
print("\n--- [4/4] Static Quality Gates & Exit Cost Audit ---")

# 4.1 Ruff Check
rc_ruff, _, out_ruff, _ = run_cmd(["uv", "run", "--locked", "ruff", "check", "src", "tests", "scripts"])
ruff_ok = (rc_ruff == 0 and "All checks passed!" in out_ruff)
print(f"Ruff check: rc={rc_ruff}, ok={ruff_ok}")
if not ruff_ok:
    print(f"  Ruff check output:\n{out_ruff}")
    results["defects_found"].append(f"Ruff linter error: {out_ruff.strip()}")

# 4.2 Ruff Format Check
rc_fmt, _, out_fmt, _ = run_cmd(["uv", "run", "--locked", "ruff", "format", "--check", "src", "tests", "scripts"])
fmt_ok = (rc_fmt == 0)
print(f"Ruff format: rc={rc_fmt}, ok={fmt_ok}")
if not fmt_ok:
    results["defects_found"].append("Ruff formatting check failed.")

# 4.3 Mypy
rc_mypy, _, out_mypy, _ = run_cmd([
    "uv", "run", "--locked", "mypy",
    "src", "scripts",
    "tests/unit/test_google_ai_studio_cycle_integration.py",
    "tests/integration/test_run_autonomous_cycle_cli.py"
])
mypy_ok = (rc_mypy == 0 and "Success: no issues found" in out_mypy)
print(f"Mypy check: rc={rc_mypy}, ok={mypy_ok}")
if not mypy_ok:
    results["defects_found"].append(f"Mypy type check failure: {out_mypy.strip()}")

# 4.4 Exit Cost Audit
rc_audit, _, out_audit, _ = run_cmd(["uv", "run", "python", "verification/reproduce_exit_cost_audit.py"])
audit_ok = False
if rc_audit == 0:
    try:
        audit_data = json.loads(out_audit)
        expected_hash = "85f1f0e6c705fa0418042fb224931960a11a641b1e79d38e2a1dc256f09b731e"
        audit_ok = (
            audit_data.get("snapshot_sha256") == expected_hash
            and audit_data.get("closed_count") == 4
            and audit_data.get("net") == "-0.44487942568588285440"
        )
        print(f"Exit cost audit: rc={rc_audit}, hash_match={audit_ok}")
    except Exception as e:
        print(f"Exit cost audit parse error: {e}")
if not audit_ok:
    results["defects_found"].append("Exit cost audit reproduction mismatch or failure.")

results["quality_gates"] = {
    "ruff_check": "PASS" if ruff_ok else "FAIL",
    "ruff_format": "PASS" if fmt_ok else "FAIL",
    "mypy": "PASS" if mypy_ok else "FAIL",
    "exit_cost_audit": "PASS" if audit_ok else "FAIL",
}

# ==============================================================================
# 5. OVERALL VERDICT DETERMINATION
# ==============================================================================
has_defects = len(results["defects_found"]) > 0

if has_defects:
    results["overall_verdict"] = "REQUEST_CHANGES"
else:
    results["overall_verdict"] = "APPROVE"

out_json_path = REPO_ROOT / "verification" / "milestone5_challenger2_results.json"
out_json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

print("\n" + "=" * 70)
print(f"FINAL CHALLENGER VERDICT: {results['overall_verdict']}")
print(f"Defects found ({len(results['defects_found'])}):")
for d in results["defects_found"]:
    print(f"  - {d}")
print("=" * 70)
