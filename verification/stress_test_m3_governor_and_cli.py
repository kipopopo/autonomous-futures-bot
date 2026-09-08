# Stress test suite for Milestone 3: Hard Budget Governor, CLI Flags, Secret Flags, Idempotency
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_autonomous_cycle import (
    BoundedTransportCallGovernor,
    build_parser,
    main as run_cli_main,
)
from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

CANONICAL_BTC_PARQUET = (
    PROJECT_ROOT / "research" / "immutable-data" / "5m" / "canonical" / "BTCUSDT-5m.parquet"
)
BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"

passed_tests = 0
failed_tests = 0
test_results: list[dict[str, Any]] = []


def record_result(name: str, passed: bool, details: str) -> None:
    global passed_tests, failed_tests
    if passed:
        passed_tests += 1
        test_results.append({"name": name, "status": "PASS", "details": details})
        print(f"[PASS] {name}: {details}")
    else:
        failed_tests += 1
        test_results.append({"name": name, "status": "FAIL", "details": details})
        print(f"[FAIL] {name}: {details}")


# =========================================================================
# SECTION 1: HARD BUDGET GOVERNOR EMPIRICAL STRESS TESTS
# =========================================================================

def test_governor_single_call_success():
    call_log = []
    def dummy_transport(req):
        call_log.append(req)
        return {"status": "ok", "req": req}

    gov = BoundedTransportCallGovernor(dummy_transport, max_calls=1, name="test_transport")
    assert gov.call_count == 0
    res = gov({"action": "generate"})
    assert res["status"] == "ok"
    assert gov.call_count == 1
    assert len(call_log) == 1
    record_result("Governor: Single call success", True, "Transport called once, call_count == 1")


def test_governor_blocks_second_and_third_call():
    call_log = []
    def dummy_transport(req):
        call_log.append(req)
        return {"status": "ok"}

    gov = BoundedTransportCallGovernor(dummy_transport, max_calls=1, name="creator_transport")
    gov({"action": "first"})
    assert gov.call_count == 1

    # Attempt 2: Must be blocked
    blocked_2 = False
    try:
        gov({"action": "second"})
    except RuntimeError as e:
        blocked_2 = "Budget ceiling breach" in str(e) and "exceeded limit of 1" in str(e)

    # Attempt 3: Must be blocked
    blocked_3 = False
    try:
        gov({"action": "third"})
    except RuntimeError as e:
        blocked_3 = "Budget ceiling breach" in str(e) and "exceeded limit of 1" in str(e)

    passed = blocked_2 and blocked_3 and len(call_log) == 1 and gov.call_count == 1
    record_result(
        "Governor: Strictly blocks calls > 1",
        passed,
        f"Second call blocked={blocked_2}, third call blocked={blocked_3}, underlying calls={len(call_log)}",
    )


def test_governor_non_bypassable_on_error():
    """Verify that if the first call throws an exception, subsequent retries are still blocked."""
    call_log = []
    def failing_transport(req):
        call_log.append(req)
        raise ConnectionResetError("Network failure simulation")

    gov = BoundedTransportCallGovernor(failing_transport, max_calls=1, name="failing_critic")
    
    # Call 1: fails with transport error
    threw_first = False
    try:
        gov({"action": "call_1"})
    except ConnectionResetError:
        threw_first = True

    # Call 2: Caller catches error and tries to retry -> governor MUST BLOCK IT
    threw_budget_breach = False
    try:
        gov({"action": "call_2_retry"})
    except RuntimeError as e:
        threw_budget_breach = "Budget ceiling breach" in str(e)

    passed = threw_first and threw_budget_breach and len(call_log) == 1
    record_result(
        "Governor: Non-bypassable on transport failure (retry block)",
        passed,
        f"First call threw ConnectionResetError={threw_first}, retry threw Budget ceiling breach={threw_budget_breach}",
    )


def test_governor_in_multi_attempt_loop():
    """Simulate an external loop attempting to query the transport multiple times."""
    call_count = 0
    def transport(req):
        nonlocal call_count
        call_count += 1
        return {"decision": "rejected", "reason_codes": ["schema_rejected"]}

    gov = BoundedTransportCallGovernor(transport, max_calls=1, name="learner_critic")
    
    attempts_allowed = 0
    attempts_blocked = 0
    for i in range(5):
        try:
            gov({"attempt": i})
            attempts_allowed += 1
        except RuntimeError:
            attempts_blocked += 1

    passed = (attempts_allowed == 1) and (attempts_blocked == 4) and (call_count == 1)
    record_result(
        "Governor: Loop stress test (5 attempts)",
        passed,
        f"Allowed={attempts_allowed}, Blocked={attempts_blocked}, Underlying calls={call_count}",
    )


# =========================================================================
# SECTION 2: CLI FLAGS & BOUNDARIES
# =========================================================================

def test_cli_invalid_model_names():
    invalid_models = [
        "gemini-1.5-pro",
        "gemma-2-9b",
        "gpt-4o",
        "gemma-4-31b",
        "claude-3-5-sonnet",
        "",
    ]
    all_rejected = True
    details_list = []
    for model in invalid_models:
        proc = subprocess.run(
            [sys.executable, "scripts/run_autonomous_cycle.py", "--model", model],
            capture_output=True,
            text=True,
        )
        rejected = proc.returncode == 2 and "invalid choice" in proc.stderr
        if not rejected:
            all_rejected = False
        details_list.append(f"{model}: code={proc.returncode}")

    record_result(
        "CLI Flags: Invalid model names rejected with exit code 2",
        all_rejected,
        "; ".join(details_list),
    )


def test_cli_valid_model_names():
    valid_models = ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]
    all_accepted = True
    parser = build_parser()
    for model in valid_models:
        args = parser.parse_args(["--symbol", "BTCUSDT", "--model", model])
        if args.model != model:
            all_accepted = False

    record_result(
        "CLI Flags: Valid model names accepted by parser",
        all_accepted,
        f"Models tested: {valid_models}",
    )


def test_cli_invalid_provider_names():
    invalid_providers = [
        "openai",
        "anthropic",
        "google",
        "azure",
        "",
    ]
    all_rejected = True
    details_list = []
    for prov in invalid_providers:
        proc = subprocess.run(
            [sys.executable, "scripts/run_autonomous_cycle.py", "--provider", prov],
            capture_output=True,
            text=True,
        )
        rejected = proc.returncode == 2 and "invalid choice" in proc.stderr
        if not rejected:
            all_rejected = False
        details_list.append(f"{prov}: code={proc.returncode}")

    record_result(
        "CLI Flags: Invalid provider names rejected with exit code 2",
        all_rejected,
        "; ".join(details_list),
    )


def test_cli_valid_provider_names():
    valid_providers = ["demo", "google_ai_studio"]
    all_accepted = True
    parser = build_parser()
    for prov in valid_providers:
        args = parser.parse_args(["--symbol", "BTCUSDT", "--provider", prov])
        if args.provider != prov:
            all_accepted = False

    record_result(
        "CLI Flags: Valid provider names accepted by parser",
        all_accepted,
        f"Providers tested: {valid_providers}",
    )


def test_cli_temperature_boundaries():
    """Test temperature flag: non-float values, negative, out-of-range, NaN, Inf."""
    # Non-float value test
    proc_abc = subprocess.run(
        [sys.executable, "scripts/run_autonomous_cycle.py", "--temperature", "abc"],
        capture_output=True,
        text=True,
    )
    non_float_rejected = proc_abc.returncode == 2 and "invalid float value" in proc_abc.stderr

    # Boundaries: negative, > 2.0, nan, inf
    parser = build_parser()
    boundary_cases = ["-0.5", "2.5", "nan", "inf", "10.0"]
    unbounded_accepted = []
    for val in boundary_cases:
        try:
            args = parser.parse_args(["--symbol", "BTCUSDT", "--temperature", val])
            parsed_val = args.temperature
            unbounded_accepted.append((val, parsed_val))
        except SystemExit:
            pass

    # Invariant: Does the CLI strictly reject temperature outside [0.0, 2.0] or non-finite?
    # If unbounded_accepted is non-empty, temperature boundaries are NOT strictly enforced.
    strictly_bounded = len(unbounded_accepted) == 0 and non_float_rejected
    details = (
        f"Non-float rejected={non_float_rejected}. "
        f"Unbounded values erroneously accepted: {unbounded_accepted}"
    )
    record_result(
        "CLI Flags: Temperature boundaries strictly enforced in [0.0, 2.0]",
        strictly_bounded,
        details,
    )


# =========================================================================
# SECTION 3: SECRET FLAGS & LEAKAGE PREVENTION
# =========================================================================

def test_secret_flags_exit_code_2_and_no_leakage():
    secret_tests = [
        (["--api-key", "secret_token_123"], "secret_token_123"),
        (["--key=super_secret_value"], "super_secret_value"),
        (["-k", "short_flag_secret"], "short_flag_secret"),
        (["--google-api-key", "AIzaSyFakeKey1234567890"], "AIzaSyFakeKey1234567890"),
        (["--api_key=underscore_secret"], "underscore_secret"),
        (["-key", "dash_key_secret"], "dash_key_secret"),
        (["--gemini-api-key=gem_secret"], "gem_secret"),
        (["--token", "bearer_token_xyz"], "bearer_token_xyz"),
        (["--api-token=api_token_abc"], "api_token_abc"),
    ]

    all_passed = True
    failure_details = []
    for flags, secret in secret_tests:
        cmd = [sys.executable, "scripts/run_autonomous_cycle.py"] + flags
        proc = subprocess.run(cmd, capture_output=True, text=True)
        
        exit_code_ok = proc.returncode == 2
        no_leak_stdout = secret not in proc.stdout
        no_leak_stderr = secret not in proc.stderr
        
        # Verify stderr JSON shape
        valid_stderr_json = False
        try:
            err_obj = json.loads(proc.stderr)
            valid_stderr_json = (err_obj.get("error_code") == "forbidden_cli_argument")
        except Exception:
            valid_stderr_json = False

        test_ok = exit_code_ok and no_leak_stdout and no_leak_stderr and valid_stderr_json
        if not test_ok:
            all_passed = False
            failure_details.append(
                f"{flags}: code={proc.returncode}, leak_out={not no_leak_stdout}, leak_err={not no_leak_stderr}, valid_json={valid_stderr_json}"
            )

    record_result(
        "Secret Flags: Immediate exit code 2, valid JSON on stderr, zero secret leakage",
        all_passed,
        "All 9 secret flag patterns verified with zero token leakage" if all_passed else "; ".join(failure_details),
    )


# =========================================================================
# SECTION 4: IDEMPOTENCY & HASH DETERMINISM
# =========================================================================

def _setup_test_ledger(db_path: Path, cand: CreatorCandidateArtifact, symbol: str, now: datetime) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                approval_id TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                slippage_cost TEXT,
                gross_pnl TEXT,
                net_pnl TEXT
            );
        """)
        conn.execute("""
            INSERT INTO paper_ledger_events VALUES (
                1, 'open', 'trade-fail-001', ?, ?, ?, 'LONG', '0.002', '50000.0',
                ?, 'app-01', '0.05', NULL, '0.01', NULL, NULL
            );
        """, (cand.candidate_id, cand.artifact_hash, symbol, (now - timedelta(hours=1)).isoformat()))
        conn.execute("""
            INSERT INTO paper_ledger_events VALUES (
                2, 'close', 'trade-fail-001', ?, ?, ?, 'LONG', '0.002', '45000.0',
                ?, 'app-02', '0.05', '0.05', '0.01', '-10.0', '-10.1'
            );
        """, (cand.candidate_id, cand.artifact_hash, symbol, now.isoformat()))


def test_cli_idempotency_and_determinism():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)
        now_dt = datetime(2026, 8, 6, 6, 0, tzinfo=UTC)
        symbol = "BTCUSDT"
        cand_id = "cand-challenger-m3-001"
        strategy = StrategySpec(
            dsl_version=2,
            strategy_id=cand_id,
            family="experimental",
            universe=StrategyUniverse(symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"),
            features=(FeatureRef(name="returns", lookback=3, shift=1),),
            entry=EntryExit(long="returns > 0.001", short="returns < -0.001"),
            exit=EntryExit(long="returns < 0.0", short="returns > 0.0"),
            vetoes=("testing_only_no_promotion",),
            risk=CandidateSimulationRisk(
                position_fraction=Decimal("0.1"),
                stop_atr_multiplier=Decimal("0.5"),
                take_profit_atr_multiplier=Decimal("2.0"),
                trailing_atr_multiplier=Decimal("1.0"),
            ),
        )
        cand = build_creator_candidate_artifact(
            candidate_id=cand_id,
            strategy=strategy,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=REGISTRY_HASH,
            creator_run_id="run-challenger-001",
            research_seed=42,
            created_at=now_dt - timedelta(days=1),
        )
        cand_path = tmp_path / "cand.json"
        write_creator_candidate_artifact(cand_path, cand)

        ledger_db = tmp_path / "ledger.sqlite3"
        _setup_test_ledger(ledger_db, cand, symbol, now_dt)

        output_dir = tmp_path / "cycle_output"
        args = [
            sys.executable,
            "scripts/run_autonomous_cycle.py",
            "--symbol", symbol,
            "--ledger-db", str(ledger_db),
            "--parquet-path", str(CANONICAL_BTC_PARQUET),
            "--output-dir", str(output_dir),
            "--candidate-path", str(cand_path),
            "--cycle-id", "cycle-m3-challenger-001",
            "--windows-count", "1",
            "--min-windows", "1",
            "--min-profit-factor", "0.10",
            "--min-trades", "10",
            "--max-drawdown-pct", "50.0",
            "--min-average-return-pct", "-10.0",
            "--now", "2026-08-06T06:00:00Z",
        ]

        # Execution 1
        p1 = subprocess.run(args, capture_output=True, text=True)
        assert p1.returncode == 0, f"Run 1 failed: {p1.stderr}"
        audit1 = json.loads((output_dir / "cycle-audit.json").read_text(encoding="utf-8"))
        res1 = json.loads((output_dir / "autonomous-cycle-result.json").read_text(encoding="utf-8"))

        # Execution 2
        p2 = subprocess.run(args, capture_output=True, text=True)
        assert p2.returncode == 0, f"Run 2 failed: {p2.stderr}"
        audit2 = json.loads((output_dir / "cycle-audit.json").read_text(encoding="utf-8"))
        res2 = json.loads((output_dir / "autonomous-cycle-result.json").read_text(encoding="utf-8"))

        audit_hash_equal = audit1["audit_hash"] == audit2["audit_hash"]
        cycle_hash_equal = audit1["cycle_hash"] == audit2["cycle_hash"]
        res_cycle_hash_equal = res1["cycle_hash"] == res2["cycle_hash"]
        latency_zero = audit1["telemetry"]["latency_ms"] == 0.0 and audit2["telemetry"]["latency_ms"] == 0.0
        provider_demo = audit1["telemetry"]["provider"] == "demo"
        model_heuristic = audit1["telemetry"]["model"] == "deterministic-heuristic"

        passed = (
            audit_hash_equal
            and cycle_hash_equal
            and res_cycle_hash_equal
            and latency_zero
            and provider_demo
            and model_heuristic
        )
        details = (
            f"audit_hash={audit1['audit_hash']}, "
            f"cycle_hash={audit1['cycle_hash']}, "
            f"latency_ms={audit1['telemetry']['latency_ms']}, "
            f"provider={audit1['telemetry']['provider']}, "
            f"model={audit1['telemetry']['model']}"
        )
        record_result("Idempotency & Hash Determinism: --now fixed re-execution exact match", passed, details)



def test_missing_credentials_exit_code_3():
    """Verify that running with --provider google_ai_studio without credentials exits with code 3 cleanly."""
    env = dict(os.environ)
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_AI_STUDIO_API_KEY", None)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp_path = Path(tmpdir)
        now_dt = datetime(2026, 8, 6, 6, 0, tzinfo=UTC)
        symbol = "BTCUSDT"
        cand_id = "cand-cli-init-001"
        strategy = StrategySpec(
            dsl_version=2,
            strategy_id=cand_id,
            family="experimental",
            universe=StrategyUniverse(symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"),
            features=(FeatureRef(name="returns", lookback=3, shift=1),),
            entry=EntryExit(long="returns > 0.001", short="returns < -0.001"),
            exit=EntryExit(long="returns < 0.0", short="returns > 0.0"),
            vetoes=("testing_only_no_promotion",),
            risk=CandidateSimulationRisk(
                position_fraction=Decimal("0.1"),
                stop_atr_multiplier=Decimal("0.5"),
                take_profit_atr_multiplier=Decimal("2.0"),
                trailing_atr_multiplier=Decimal("1.0"),
            ),
        )
        cand = build_creator_candidate_artifact(
            candidate_id=cand_id,
            strategy=strategy,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=REGISTRY_HASH,
            creator_run_id="run-cli-001",
            research_seed=42,
            created_at=now_dt - timedelta(days=1),
        )
        cand_path = tmp_path / "cand.json"
        write_creator_candidate_artifact(cand_path, cand)

        ledger_db = tmp_path / "ledger.sqlite3"
        _setup_test_ledger(ledger_db, cand, symbol, now_dt)

        cli_path = PROJECT_ROOT / "scripts" / "run_autonomous_cycle.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "--symbol", symbol,
                "--provider", "google_ai_studio",
                "--ledger-db", str(ledger_db),
                "--parquet-path", str(CANONICAL_BTC_PARQUET),
                "--candidate-path", str(cand_path),
                "--output-dir", str(tmp_path / "out"),
                "--now", "2026-08-06T06:00:00Z",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmpdir,
        )

        code_ok = proc.returncode == 3
        no_traceback = "Traceback" not in proc.stderr and "Traceback" not in proc.stdout
        stdout_json_ok = False
        try:
            data = json.loads(proc.stdout)
            stdout_json_ok = data.get("error_code") == "missing_credentials"
        except Exception:
            stdout_json_ok = False

        passed = code_ok and no_traceback and stdout_json_ok
        details = f"exit_code={proc.returncode}, no_traceback={no_traceback}, stdout_json_ok={stdout_json_ok}"
        record_result("Missing Credentials: Clean exit code 3 with JSON error and no traceback", passed, details)

# =========================================================================
# MAIN EXECUTION
# =========================================================================

def main():
    print("=" * 75)
    print("Milestone 3 Empirical Challenger Stress Test Suite")
    print("=" * 75)

    print("\n--- [1] Hard Budget Governor Tests ---")
    test_governor_single_call_success()
    test_governor_blocks_second_and_third_call()
    test_governor_non_bypassable_on_error()
    test_governor_in_multi_attempt_loop()

    print("\n--- [2] CLI Flags & Boundaries Tests ---")
    test_cli_invalid_model_names()
    test_cli_valid_model_names()
    test_cli_invalid_provider_names()
    test_cli_valid_provider_names()
    test_cli_temperature_boundaries()

    print("\n--- [3] Secret Flags & Leakage Prevention Tests ---")
    test_secret_flags_exit_code_2_and_no_leakage()

    print("\n--- [4] Idempotency & Hash Determinism Tests ---")
    test_cli_idempotency_and_determinism()
    test_missing_credentials_exit_code_3()

    print("\n" + "=" * 75)
    print(f"SUMMARY: {passed_tests} PASSED, {failed_tests} FAILED out of {passed_tests + failed_tests} tests")
    print("=" * 75)

    out_file = PROJECT_ROOT / "verification" / "stress_test_m3_results.json"
    out_file.write_text(
        json.dumps({
            "passed": passed_tests,
            "failed": failed_tests,
            "total": passed_tests + failed_tests,
            "tests": test_results,
        }, indent=2),
        encoding="utf-8"
    )
    return 0 if failed_tests == 0 else 1


if __name__ == "__main__":
    sys.exit(main())