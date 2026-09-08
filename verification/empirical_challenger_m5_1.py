"""verification/empirical_challenger_m5_1.py

Empirical Challenger verification suite for Milestone 5:
1. Targeted regression test suite pass count verification (50/50).
2. Financial exit cost audit reproduction & cryptographic integrity check.
3. Deterministic replay in demo mode with fixed --now (bit-for-bit SHA-256 identity).
4. Provider & Governance security invariant verification.
5. Static analysis and repository hygiene verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path("B:/")
PARQUET_PATH = REPO_ROOT / "research" / "immutable-data" / "5m" / "canonical" / "BTCUSDT-5m.parquet"
EXIT_AUDIT_SCRIPT = REPO_ROOT / "verification" / "reproduce_exit_cost_audit.py"
CLI_SCRIPT = REPO_ROOT / "scripts" / "run_autonomous_cycle.py"

TARGET_HASH = "85f1f0e6c705fa0418042fb224931960a11a641b1e79d38e2a1dc256f09b731e"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_regression_suite_pass_count() -> dict[str, object]:
    """Task 1: Verify regression test suite pass count (50/50 passed)."""
    print("\n" + "=" * 70)
    print("CHALLENGE 1: Regression Test Suite Pass Count (50/50)")
    print("=" * 70)

    cmd = [
        "uv",
        "run",
        "--locked",
        "pytest",
        "tests/unit/test_google_ai_studio_cycle_integration.py",
        "tests/integration/test_run_autonomous_cycle_cli.py",
        "-v",
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - t0
    print(f"Executed in {elapsed:.2f}s, returncode={proc.returncode}")

    passed_50 = "50 passed" in proc.stdout
    assert proc.returncode == 0, f"pytest failed with code {proc.returncode}:\n{proc.stdout}\n{proc.stderr}"
    assert passed_50, f"Expected '50 passed' in output, got:\n{proc.stdout}"

    print(f"CONFIRMED: Exactly 50/50 tests passed in {elapsed:.2f}s.")
    return {
        "passed": True,
        "returncode": proc.returncode,
        "tests_passed": 50,
        "elapsed_s": round(elapsed, 2),
    }


def test_exit_cost_audit_reproduction() -> dict[str, object]:
    """Task 2: Verify financial exit cost audit reproduction."""
    print("\n" + "=" * 70)
    print("CHALLENGE 2: Financial Exit Cost Audit Reproduction")
    print("=" * 70)

    cmd = ["uv", "run", "python", str(EXIT_AUDIT_SCRIPT)]
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - t0
    assert proc.returncode == 0, f"Audit reproduction failed with code {proc.returncode}:\n{proc.stderr}"

    data = json.loads(proc.stdout)
    assert data["snapshot_sha256"] == TARGET_HASH, (
        f"Hash mismatch: expected {TARGET_HASH}, got {data['snapshot_sha256']}"
    )
    assert data["closed_count"] == 4
    assert data["excluded_open_count"] == 2
    assert data["net"] == "-0.44487942568588285440"
    assert data["fees"] == "0.14851486592677885440"
    assert data["gross"] == "-0.2963645597591040"

    print(f"CONFIRMED: Snapshot SHA256 matches exact target: {TARGET_HASH}")
    print(f"Closed count: {data['closed_count']}, Excluded open count: {data['excluded_open_count']}")
    print(f"Gross PnL: {data['gross']}, Fees: {data['fees']}, Net PnL: {data['net']}")
    return {
        "passed": True,
        "snapshot_sha256": data["snapshot_sha256"],
        "target_sha256": TARGET_HASH,
        "exact_match": True,
        "elapsed_s": round(elapsed, 2),
        "data": data,
    }


def _create_deterministic_test_fixtures(temp_dir: Path) -> tuple[Path, Path]:
    """Create test ledger and candidate file for deterministic CLI replay."""
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from tests.integration.test_run_autonomous_cycle_cli import (
        _build_candidate,
        _init_test_ledger,
        write_creator_candidate_artifact,
    )

    cand = _build_candidate("cand-replay-challenger-001", stop_atr="0.5")
    cand_path = temp_dir / "cand-replay-challenger-001.json"
    write_creator_candidate_artifact(cand_path, cand)

    ledger_db = temp_dir / "ledger.sqlite3"
    _init_test_ledger(ledger_db, cand)

    return cand_path, ledger_db


def test_deterministic_replay_demo_mode() -> dict[str, object]:
    """Task 3: Verify deterministic replay in demo mode with fixed --now."""
    print("\n" + "=" * 70)
    print("CHALLENGE 3: Deterministic Replay in Demo Mode with Fixed --now")
    print("=" * 70)

    fixed_now = "2026-08-06T06:00:00Z"
    cycle_id = "cycle-challenger-det-001"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_root_str:
        temp_root = Path(temp_root_str)
        cand_path, ledger_db = _create_deterministic_test_fixtures(temp_root)

        dir_run1 = temp_root / "run1"
        dir_run2 = temp_root / "run2"
        dir_run3 = temp_root / "run3"

        base_args = [
            "uv",
            "run",
            "python",
            str(CLI_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(ledger_db),
            "--parquet-path",
            str(PARQUET_PATH),
            "--candidate-path",
            str(cand_path),
            "--cycle-id",
            cycle_id,
            "--windows-count",
            "1",
            "--min-windows",
            "1",
            "--min-profit-factor",
            "0.10",
            "--min-trades",
            "10",
            "--max-drawdown-pct",
            "50.0",
            "--min-average-return-pct",
            "-10.0",
            "--now",
            fixed_now,
            "--provider",
            "demo",
        ]

        # 3.1: Execute Run 1 into dir_run1
        cmd1 = base_args + ["--output-dir", str(dir_run1)]
        res1 = subprocess.run(cmd1, cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res1.returncode == 0, f"Run 1 failed with code {res1.returncode}:\n{res1.stderr}\n{res1.stdout}"

        # 3.2: Execute Run 2 into dir_run2 (separate clean dir)
        cmd2 = base_args + ["--output-dir", str(dir_run2)]
        res2 = subprocess.run(cmd2, cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res2.returncode == 0, f"Run 2 failed with code {res2.returncode}:\n{res2.stderr}\n{res2.stdout}"

        # 3.3: Compare Run 1 vs Run 2 byte-for-byte
        audit_file_1 = dir_run1 / "cycle-audit.json"
        audit_file_2 = dir_run2 / "cycle-audit.json"
        result_file_1 = dir_run1 / "autonomous-cycle-result.json"
        result_file_2 = dir_run2 / "autonomous-cycle-result.json"

        assert audit_file_1.exists() and audit_file_2.exists()
        assert result_file_1.exists() and result_file_2.exists()

        audit_bytes_1 = audit_file_1.read_bytes()
        audit_bytes_2 = audit_file_2.read_bytes()
        result_bytes_1 = result_file_1.read_bytes()
        result_bytes_2 = result_file_2.read_bytes()

        audit_sha_1 = hashlib.sha256(audit_bytes_1).hexdigest()
        audit_sha_2 = hashlib.sha256(audit_bytes_2).hexdigest()
        result_sha_1 = hashlib.sha256(result_bytes_1).hexdigest()
        result_sha_2 = hashlib.sha256(result_bytes_2).hexdigest()

        print(f"Run 1 cycle-audit.json SHA256:       {audit_sha_1}")
        print(f"Run 2 cycle-audit.json SHA256:       {audit_sha_2}")
        print(f"Run 1 cycle-result.json SHA256:      {result_sha_1}")
        print(f"Run 2 cycle-result.json SHA256:      {result_sha_2}")

        assert audit_bytes_1 == audit_bytes_2, "cycle-audit.json bytes differ between runs!"
        assert result_bytes_1 == result_bytes_2, "autonomous-cycle-result.json bytes differ between runs!"

        # Inspect internal json structures
        audit_data_1 = json.loads(audit_bytes_1.decode("utf-8"))
        audit_data_2 = json.loads(audit_bytes_2.decode("utf-8"))
        result_data_1 = json.loads(result_bytes_1.decode("utf-8"))
        result_data_2 = json.loads(result_bytes_2.decode("utf-8"))

        assert audit_data_1["audit_hash"] == audit_data_2["audit_hash"]
        assert audit_data_1["cycle_hash"] == audit_data_2["cycle_hash"]
        assert result_data_1["cycle_hash"] == result_data_2["cycle_hash"]

        # Invariants in demo mode with fixed --now
        assert audit_data_1["telemetry"]["provider"] == "demo"
        assert audit_data_1["telemetry"]["model"] == "deterministic-heuristic"
        assert audit_data_1["telemetry"]["latency_ms"] == 0.0, (
            f"Expected latency_ms == 0.0 in demo mode with fixed --now, got {audit_data_1['telemetry']['latency_ms']}"
        )
        assert result_data_1["latency_ms"] == 0.0
        assert result_data_1["provider"] == "demo"
        assert result_data_1["cycle_status"] == "completed_admitted"

        # 3.4: Re-execution into existing directory (idempotency check)
        cmd_rerun = base_args + ["--output-dir", str(dir_run1)]
        res_rerun = subprocess.run(cmd_rerun, cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res_rerun.returncode == 0
        rerun_audit_sha = hashlib.sha256(audit_file_1.read_bytes()).hexdigest()
        rerun_result_sha = hashlib.sha256(result_file_1.read_bytes()).hexdigest()
        assert rerun_audit_sha == audit_sha_1, "In-place rerun changed cycle-audit.json!"
        assert rerun_result_sha == result_sha_1, "In-place rerun changed autonomous-cycle-result.json!"
        print("In-place idempotent rerun verified: hashes remained bit-for-bit identical.")

        # 3.5: Counter-check: without --now, timestamps and latency must vary (non-deterministic time)
        cmd_dyn = [
            "uv",
            "run",
            "python",
            str(CLI_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(ledger_db),
            "--parquet-path",
            str(PARQUET_PATH),
            "--candidate-path",
            str(cand_path),
            "--cycle-id",
            "cycle-dyn-001",
            "--windows-count",
            "1",
            "--min-windows",
            "1",
            "--min-profit-factor",
            "0.10",
            "--min-trades",
            "10",
            "--max-drawdown-pct",
            "50.0",
            "--min-average-return-pct",
            "-10.0",
            "--provider",
            "demo",
            "--output-dir",
            str(dir_run3),
        ]
        res3 = subprocess.run(cmd_dyn, cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res3.returncode == 0
        audit_dyn = json.loads((dir_run3 / "cycle-audit.json").read_text(encoding="utf-8"))
        print(f"Dynamic run (without --now): completed_at={audit_dyn['completed_at']}")
        assert audit_dyn["completed_at"] != fixed_now, "Dynamic run should not have fixed --now timestamp!"

        print("CONFIRMED: Bit-for-bit deterministic replay verified across isolated and in-place runs.")
        return {
            "passed": True,
            "audit_file_sha256": audit_sha_1,
            "result_file_sha256": result_sha_1,
            "audit_hash": audit_data_1["audit_hash"],
            "cycle_hash": audit_data_1["cycle_hash"],
            "latency_ms": audit_data_1["telemetry"]["latency_ms"],
            "provider": audit_data_1["telemetry"]["provider"],
            "model": audit_data_1["telemetry"]["model"],
            "bit_for_bit_identical": True,
            "idempotent_identical": True,
        }


def test_provider_security_invariants() -> dict[str, object]:
    """Task 4: Verify provider forbidden flags and credential safety invariants."""
    print("\n" + "=" * 70)
    print("CHALLENGE 4: Provider & Governance Security Invariants")
    print("=" * 70)

    # 4.1 Forbidden CLI flag rejection (exit code 2)
    forbidden_flags = ["--api-key", "--api_key", "--key", "-k", "--token", "--google-ai-studio-api-key"]
    for flag in forbidden_flags:
        proc = subprocess.run(
            ["uv", "run", "python", str(CLI_SCRIPT), flag, "secret123"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2, f"Flag {flag} was not rejected with exit code 2! rc={proc.returncode}"
        assert "forbidden" in proc.stderr.lower() or "forbidden" in proc.stdout.lower()

    print(f"CONFIRMED: All forbidden flags {forbidden_flags} correctly rejected with exit code 2.")

    # 4.2 Missing credentials when --provider google_ai_studio (exit code 3, clean JSON, no traceback)
    clean_env = {k: v for k, v in os.environ.items() if not any(x in k.upper() for x in ["GOOGLE", "GEMINI"])}
    clean_env["PATH"] = os.environ.get("PATH", "")
    clean_env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_missing_dir:
        cand_p, ledg_p = _create_deterministic_test_fixtures(Path(temp_missing_dir))
        out_p = Path(temp_missing_dir) / "missing_out"
        proc_missing = subprocess.run(
            [
                "uv",
                "run",
                "python",
                str(CLI_SCRIPT),
                "--symbol",
                "BTCUSDT",
                "--ledger-db",
                str(ledg_p),
                "--candidate-path",
                str(cand_p),
                "--parquet-path",
                str(PARQUET_PATH),
                "--output-dir",
                str(out_p),
                "--provider",
                "google_ai_studio",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=clean_env,
        )
        assert proc_missing.returncode == 3, f"Expected rc=3 for missing credentials, got rc={proc_missing.returncode}"
        assert "Traceback" not in proc_missing.stderr
        assert "Traceback" not in proc_missing.stdout
        parsed = json.loads(proc_missing.stdout.strip())
        assert parsed["error_code"] == "missing_credentials"
        assert "No Google AI Studio / Gemini credential found" in parsed["message"]
        print("CONFIRMED: Missing credentials cleanly handled with exit code 3 and sanitized JSON.")

    return {"passed": True, "forbidden_flags_tested": len(forbidden_flags), "missing_credentials_rc": 3}


def test_static_analysis_and_hygiene() -> dict[str, object]:
    """Task 5: Verify ruff and mypy quality gates."""
    print("\n" + "=" * 70)
    print("CHALLENGE 5: Static Analysis & Repository Hygiene")
    print("=" * 70)

    # Ruff check
    rc_check = subprocess.run(
        ["uv", "run", "--locked", "ruff", "check", "src", "tests", "scripts"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert rc_check.returncode == 0, f"ruff check failed:\n{rc_check.stdout}\n{rc_check.stderr}"
    print("CONFIRMED: ruff check reports 0 errors.")

    # Ruff format
    rc_fmt = subprocess.run(
        ["uv", "run", "--locked", "ruff", "format", "--check", "src", "tests", "scripts"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert rc_fmt.returncode == 0, f"ruff format --check failed:\n{rc_fmt.stdout}\n{rc_fmt.stderr}"
    print("CONFIRMED: ruff format --check reports 0 formatting deviations.")

    # Mypy type check
    rc_mypy = subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "mypy",
            "src",
            "scripts",
            "tests/unit/test_google_ai_studio_cycle_integration.py",
            "tests/integration/test_run_autonomous_cycle_cli.py",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert rc_mypy.returncode == 0, f"mypy failed:\n{rc_mypy.stdout}\n{rc_mypy.stderr}"
    print("CONFIRMED: mypy static type analysis passed with 0 issues.")

    return {
        "passed": True,
        "ruff_check": "0 errors",
        "ruff_format": "0 changes",
        "mypy": "0 issues",
    }


def main():
    print("STARTING EMPIRICAL CHALLENGER VERIFICATION FOR MILESTONE 5")
    results = {}
    failures = []

    for name, fn in [
        ("challenge_1_regression_suite", test_regression_suite_pass_count),
        ("challenge_2_exit_cost_audit", test_exit_cost_audit_reproduction),
        ("challenge_3_deterministic_replay", test_deterministic_replay_demo_mode),
        ("challenge_4_security_invariants", test_provider_security_invariants),
        ("challenge_5_static_hygiene", test_static_analysis_and_hygiene),
    ]:
        try:
            results[name] = fn()
        except Exception as exc:
            print(f"\n[FAIL] {name}: {exc}")
            results[name] = {"passed": False, "error": str(exc)}
            failures.append((name, str(exc)))

    results["failures"] = failures
    results["overall_verdict"] = "APPROVE" if not failures else "REQUEST_CHANGES"

    summary_file = REPO_ROOT / "verification" / "milestone5_challenger1_results.json"
    summary_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nResults successfully written to {summary_file}")
    print("\n" + "=" * 70)
    print(f"FINAL CHALLENGER VERDICT: {results['overall_verdict']}")
    print("=" * 70)


if __name__ == "__main__":
    main()

