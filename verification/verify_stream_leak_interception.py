"""Verification script for Focus 2: Stream leak interception under adversarial injection."""

import hashlib
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path("B:/")
TEST_INTEG_PATH = REPO_ROOT / "tests" / "integration" / "test_run_autonomous_cycle_cli.py"
TEST_UNIT_PATH = REPO_ROOT / "tests" / "unit" / "test_google_ai_studio_cycle_integration.py"

orig_integ_bytes = TEST_INTEG_PATH.read_bytes()
orig_unit_bytes = TEST_UNIT_PATH.read_bytes()

orig_integ_hash = hashlib.sha256(orig_integ_bytes).hexdigest()
orig_unit_hash = hashlib.sha256(orig_unit_bytes).hexdigest()

newline_integ = b"\r\n" if b"\r\n" in orig_integ_bytes else b"\n"
newline_unit = b"\r\n" if b"\r\n" in orig_unit_bytes else b"\n"
nl_i = newline_integ.decode("utf-8")
nl_u = newline_unit.decode("utf-8")

results = {}

def run_test(test_file: str, test_filter: str) -> tuple[int, str]:
    cmd = [
        "uv", "run", "--locked", "pytest",
        test_file,
        "-k", test_filter,
        "-q",
        "--tb=short",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode, proc.stdout + "\n" + proc.stderr

try:
    orig_text = orig_integ_bytes.decode("utf-8")
    target_block = f"    ret = run_cli_main(args){nl_i}    assert ret == 0"

    e2e_func_header = "def test_cli_end_to_end_google_ai_studio_mocked"
    e2e_func_idx = orig_text.find(e2e_func_header)
    assert e2e_func_idx != -1, "test_cli_end_to_end_google_ai_studio_mocked not found"
    e2e_prefix = orig_text[:e2e_func_idx]

    print("--- 2.1 Stdout Bearer leak injection in integration e2e test ---")
    leak_code_out = (
        f"    ret = run_cli_main(args){nl_i}"
        f"    print('LEAK_STDOUT: Bearer ya29.a0AfH6SM_InjectedEmpiricalChallengerStdoutToken12345'){nl_i}"
        f"    assert ret == 0"
    )
    e2e_suffix = orig_text[e2e_func_idx:].replace(target_block, leak_code_out, 1)
    TEST_INTEG_PATH.write_bytes((e2e_prefix + e2e_suffix).encode("utf-8"))

    rc, out = run_test("tests/integration/test_run_autonomous_cycle_cli.py", "test_cli_end_to_end_google_ai_studio_mocked")
    assert rc == 1, f"Expected rc=1, got {rc}\n{out}"
    assert "AssertionError" in out or "assert " in out
    assert "Bearer ya29." in out
    results["2.1_stdout_bearer_leak"] = "CAUGHT_ASSERTION_ERROR"
    print("PASS: 2.1 Stdout Bearer leak failed with AssertionError")

    print("--- 2.2 Stderr AIzaSy key leak injection in integration e2e test ---")
    leak_code_err = (
        f"    ret = run_cli_main(args){nl_i}"
        f"    sys.stderr.write('LEAK_STDERR: AIzaSyInjectedEmpiricalChallengerStderrKey12345\\n'){nl_i}"
        f"    assert ret == 0"
    )
    e2e_suffix_err = orig_text[e2e_func_idx:].replace(target_block, leak_code_err, 1)
    TEST_INTEG_PATH.write_bytes((e2e_prefix + e2e_suffix_err).encode("utf-8"))

    rc, out = run_test("tests/integration/test_run_autonomous_cycle_cli.py", "test_cli_end_to_end_google_ai_studio_mocked")
    assert rc == 1, f"Expected rc=1, got {rc}\n{out}"
    assert "AssertionError" in out or "assert " in out
    assert "AIzaSy" in out
    results["2.2_stderr_aizasy_leak"] = "CAUGHT_ASSERTION_ERROR"
    print("PASS: 2.2 Stderr AIzaSy leak failed with AssertionError")

    print("--- 2.3 Stdout Bearer leak injection in error path test ---")
    err_target_block = f"    ret = run_cli_main(args){nl_i}    assert ret == 3"
    err_leak_code = (
        f"    ret = run_cli_main(args){nl_i}"
        f"    print('LEAK_ERROR_STDOUT: Bearer ya29.a0AfH6SM_ErrorLeakToken12345'){nl_i}"
        f"    assert ret == 3"
    )
    test_func_header = "def test_cli_provider_api_error_exit_code_3"
    func_idx = orig_text.find(test_func_header)
    assert func_idx != -1, "test_cli_provider_api_error_exit_code_3 not found"
    prefix = orig_text[:func_idx]
    suffix = orig_text[func_idx:].replace(err_target_block, err_leak_code, 1)
    TEST_INTEG_PATH.write_bytes((prefix + suffix).encode("utf-8"))

    rc, out = run_test("tests/integration/test_run_autonomous_cycle_cli.py", "test_cli_provider_api_error_exit_code_3")
    assert rc == 1, f"Expected rc=1, got {rc}\n{out}"
    assert "AssertionError" in out or "assert " in out
    assert "Bearer ya29." in out
    results["2.3_error_path_stdout_leak"] = "CAUGHT_ASSERTION_ERROR"
    print("PASS: 2.3 Error path stdout leak failed with AssertionError")

    print("--- 2.4 Stderr AIzaSy leak injection in error path test ---")
    err_leak_code_err = (
        f"    ret = run_cli_main(args){nl_i}"
        f"    sys.stderr.write('LEAK_ERROR_STDERR: AIzaSyErrorStderrKey1234567890\\n'){nl_i}"
        f"    assert ret == 3"
    )
    suffix_err = orig_text[func_idx:].replace(err_target_block, err_leak_code_err, 1)
    TEST_INTEG_PATH.write_bytes((prefix + suffix_err).encode("utf-8"))

    rc, out = run_test("tests/integration/test_run_autonomous_cycle_cli.py", "test_cli_provider_api_error_exit_code_3")
    assert rc == 1, f"Expected rc=1, got {rc}\n{out}"
    assert "AssertionError" in out or "assert " in out
    assert "AIzaSy" in out
    results["2.4_error_path_stderr_leak"] = "CAUGHT_ASSERTION_ERROR"
    print("PASS: 2.4 Error path stderr leak failed with AssertionError")

    # Restore integration test before unit test
    TEST_INTEG_PATH.write_bytes(orig_integ_bytes)

    print("--- 2.5 Unit test stdout Bearer leak injection ---")
    unit_text = orig_unit_bytes.decode("utf-8")
    unit_target = (
        f"    ret = run_cli_main({nl_u}"
        f"        [{nl_u}"
        f"            \"--symbol\",{nl_u}"
        f"            \"BTCUSDT\",{nl_u}"
        f"            \"--provider\",{nl_u}"
        f"            \"google_ai_studio\",{nl_u}"
        f"            \"--feedback-path\",{nl_u}"
        f"            str(fb_path),{nl_u}"
        f"        ]{nl_u}"
        f"    ){nl_u}"
        f"    assert ret == 3"
    )
    unit_leak = (
        f"    ret = run_cli_main({nl_u}"
        f"        [{nl_u}"
        f"            \"--symbol\",{nl_u}"
        f"            \"BTCUSDT\",{nl_u}"
        f"            \"--provider\",{nl_u}"
        f"            \"google_ai_studio\",{nl_u}"
        f"            \"--feedback-path\",{nl_u}"
        f"            str(fb_path),{nl_u}"
        f"        ]{nl_u}"
        f"    ){nl_u}"
        f"    print('UNIT_LEAK_STDOUT: Bearer ya29.unit_leak_token_12345'){nl_u}"
        f"    assert ret == 3"
    )
    assert unit_target in unit_text, "unit_target not found in unit_text"
    mutated_unit = unit_text.replace(unit_target, unit_leak, 1)
    TEST_UNIT_PATH.write_bytes(mutated_unit.encode("utf-8"))

    rc, out = run_test("tests/unit/test_google_ai_studio_cycle_integration.py", "test_cli_main_missing_credentials_exits_code_3_with_clean_json")
    assert rc == 1, f"Expected rc=1, got {rc}\n{out}"
    assert "AssertionError" in out or "assert " in out
    assert "Bearer ya29." in out
    results["2.5_unit_stdout_leak"] = "CAUGHT_ASSERTION_ERROR"
    print("PASS: 2.5 Unit test stdout leak failed with AssertionError")

finally:
    # Always restore original bytes
    TEST_INTEG_PATH.write_bytes(orig_integ_bytes)
    TEST_UNIT_PATH.write_bytes(orig_unit_bytes)

restored_integ_hash = hashlib.sha256(TEST_INTEG_PATH.read_bytes()).hexdigest()
restored_unit_hash = hashlib.sha256(TEST_UNIT_PATH.read_bytes()).hexdigest()

assert restored_integ_hash == orig_integ_hash, "Integration file hash mismatch after restore!"
assert restored_unit_hash == orig_unit_hash, "Unit file hash mismatch after restore!"

print("\n==========================================")
print("ALL 5 STREAM LEAK INJECTIONS CAUGHT WITH ASSERTIONERROR!")
print(f"Integration file restored SHA256 match: {restored_integ_hash == orig_integ_hash}")
print(f"Unit file restored SHA256 match: {restored_unit_hash == orig_unit_hash}")
print("==========================================")
