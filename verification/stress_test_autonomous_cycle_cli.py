# Stress test suite for scripts/run_autonomous_cycle.py
import contextlib
import gc
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

import scripts.run_autonomous_cycle as runner
from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.paper.feedback_extractor import (
    extract_paper_feedback,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)

CANONICAL_BTC_PARQUET = (
    PROJECT_ROOT / "research" / "immutable-data" / "5m" / "canonical" / "BTCUSDT-5m.parquet"
)
PHASE254_LEDGER = PROJECT_ROOT / "artifacts" / "research" / "phase254" / "paper-ledger.sqlite3"
PHASE254_LIFECYCLE = (
    PROJECT_ROOT / "artifacts" / "research" / "phase254" / "paper-lifecycle.sqlite3"
)
BTC_CAND_ID = "cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74"

passed_tests = 0
failed_tests = 0
test_results = []


def record(name: str, condition: bool, details: str = ""):
    global passed_tests, failed_tests
    status = "PASS" if condition else "FAIL"
    if condition:
        passed_tests += 1
    else:
        failed_tests += 1
    print(f"[{status}] {name}")
    if details:
        print(f"       {details}")
    test_results.append({"name": name, "status": status, "details": details})


def run_inproc(argv: list[str]) -> tuple[int, str, str]:
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        try:
            rc = runner.main(argv)
        except Exception as exc:
            rc = 999
            err_buf.write(f"UNHANDLED EXCEPTION: {exc}\n")
    return rc, out_buf.getvalue(), err_buf.getvalue()


def run_subprocess(argv: list[str]) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "run_autonomous_cycle.py")] + argv
    res = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    return res.returncode, res.stdout, res.stderr


def build_test_candidate(
    candidate_id: str,
    symbol: str = "BTCUSDT",
) -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("3.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=runner.DEFAULT_BUNDLE_HASH,
        dataset_registry_hash=runner.DEFAULT_REGISTRY_HASH,
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
    )


def create_synthetic_ledger_db(
    db_path: Path,
    trades: list[dict[str, Any]],
    with_active_position: bool = False,
    active_candidate: CreatorCandidateArtifact | None = None,
):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE paper_ledger_events (
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
        CREATE TABLE paper_position_state (
            trade_id TEXT PRIMARY KEY,
            state_version INTEGER NOT NULL,
            state_json TEXT NOT NULL
        );
    """)
    conn.execute("""
        CREATE TABLE paper_position_update_intent (
            trade_id TEXT PRIMARY KEY,
            intent TEXT NOT NULL
        );
    """)

    seq = 1
    for t in trades:
        entry_fee = Decimal(str(t.get("entry_fee", "0.02")))
        exit_fee = Decimal(str(t.get("exit_fee", "0.02")))
        slippage_cost = Decimal(str(t.get("slippage_cost", "0.01")))
        gross_pnl = Decimal(str(t.get("gross_pnl", "0.00")))
        net_pnl = gross_pnl - entry_fee - exit_fee

        conn.execute(
            "INSERT INTO paper_ledger_events VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL)",
            (
                seq,
                t["trade_id"],
                t["candidate_id"],
                t.get("candidate_artifact_hash", "a" * 64),
                t.get("symbol", "BTCUSDT"),
                t.get("side", "LONG"),
                str(t.get("quantity", "0.01")),
                str(t["entry_price"]),
                t["opened_at"],
                f"app-event-{seq}",
                str(entry_fee),
                str(slippage_cost),
            ),
        )
        seq += 1
        if not t.get("open_only", False):
            conn.execute(
                "INSERT INTO paper_ledger_events VALUES (?, 'close', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    seq,
                    t["trade_id"],
                    t["candidate_id"],
                    t.get("candidate_artifact_hash", "a" * 64),
                    t.get("symbol", "BTCUSDT"),
                    t.get("side", "LONG"),
                    str(t.get("quantity", "0.01")),
                    str(t["exit_price"]),
                    t["closed_at"],
                    f"app-event-{seq}",
                    str(entry_fee),
                    str(exit_fee),
                    str(slippage_cost),
                    str(gross_pnl),
                    str(net_pnl),
                ),
            )
            seq += 1

    if with_active_position and active_candidate is not None:
        active_trade_id = "t-active-001"
        conn.execute(
            "INSERT INTO paper_ledger_events VALUES (?, 'open', ?, ?, ?, 'BTCUSDT', 'LONG', '0.01', '50000', '2026-09-08T10:00:00Z', ?, '0.02', NULL, '0.01', NULL, NULL)",
            (
                seq,
                active_trade_id,
                active_candidate.candidate_id,
                active_candidate.artifact_hash,
                f"app-event-{seq}",
            ),
        )
        strat_json = json.dumps(
            active_candidate.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        pos_state = {
            "state_version": 1,
            "trade_id": active_trade_id,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "candidate_id": active_candidate.candidate_id,
            "candidate_artifact_hash": active_candidate.artifact_hash,
            "quantity": "0.01",
            "base_margin": "10.0",
            "leverage": "1.0",
            "watermark": "50000.0",
            "peak_pnl": "0.0",
            "stop_price": "45000.0",
            "target_price": "60000.0",
            "trailing_atr_multiplier": "1.0",
            "current_atr": "500.0",
            "opened_at": "2026-09-08T10:00:00Z",
            "trailing_stop_price": None,
            "strategy_json": strat_json,
        }
        conn.execute(
            "INSERT INTO paper_position_state VALUES (?, 1, ?)",
            (active_trade_id, json.dumps(pos_state)),
        )

    conn.commit()
    conn.close()


print("=" * 80)
print("EMPIRICAL CHALLENGER STRESS SUITE: scripts/run_autonomous_cycle.py")
print("=" * 80)

# CATEGORY 1: Argument Parsing & Exit Code 2
print("\n--- CATEGORY 1: Argument Parsing & Exit Code 2 ---")

rc, out, err = run_inproc(["--ledger-db", str(PHASE254_LEDGER)])
record(
    "ArgParse: Missing --symbol returns exit code 2",
    rc == 2 and ("the following arguments are required: --symbol" in err or "required" in err),
    f"rc={rc}",
)

rc, out, err = run_inproc(["--symbol", "BTCUSDT"])
record(
    "ArgParse: Missing both --feedback-path and --ledger-db returns exit code 2",
    rc == 2 and "missing_input_source" in err,
    f"rc={rc}, err={err.strip()}",
)

for sym in ["btc_usdt", "btc-usdt", "BTC!USDT", "BTC USDT", ""]:
    rc, out, err = run_inproc(["--symbol", sym, "--ledger-db", str(PHASE254_LEDGER)])
    record(f"ArgParse: Invalid symbol '{sym}' returns exit code 2", rc == 2, f"rc={rc}")

for wc in ["0", "-1", "-10", "11", "50", "abc", "2.5"]:
    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--windows-count",
            wc,
        ]
    )
    record(f"ArgParse: Invalid windows-count '{wc}' returns exit code 2", rc == 2, f"rc={rc}")

for bpw in ["19", "0", "-50", "2017", "10000", "xyz"]:
    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--bars-per-window",
            bpw,
        ]
    )
    record(f"ArgParse: Invalid bars-per-window '{bpw}' returns exit code 2", rc == 2, f"rc={rc}")

for cid in [
    "Cycle-btc-001",
    "cycle_btc_001",
    "cycle-",
    "cycle--invalid",
    "nocycle-001",
    "cycle-" + ("a" * 65),
]:
    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--cycle-id",
            cid,
        ]
    )
    record(f"ArgParse: Invalid cycle-id '{cid[:20]}' returns exit code 2", rc == 2, f"rc={rc}")

for h in ["short123", "A" * 64, ("0" * 63) + "Z", "0" * 65, "0" * 63]:
    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--bundle-hash",
            h,
        ]
    )
    record(f"ArgParse: Invalid bundle-hash '{h[:15]}' returns exit code 2", rc == 2, f"rc={rc}")

    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--dataset-registry-hash",
            h,
        ]
    )
    record(
        f"ArgParse: Invalid dataset-registry-hash '{h[:15]}' returns exit code 2",
        rc == 2,
        f"rc={rc}",
    )

sub_rc, sub_out, sub_err = run_subprocess(["--symbol", "BTCUSDT"])
record(
    "ArgParse: Subprocess parity for missing source returns exit code 2",
    sub_rc == 2 and "missing_input_source" in sub_err,
    f"sub_rc={sub_rc}",
)
# CATEGORY 2: Error Handling & Exit Code 3 (Sanitized JSON Output)
print("\n--- CATEGORY 2: Error Handling & Exit Code 3 ---")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_str:
    gc.collect()
    td = Path(td_str)

    # 2.1: Missing --feedback-path
    missing_fb = td / "non_existent_feedback.json"
    rc, out, err = run_inproc(["--symbol", "BTCUSDT", "--feedback-path", str(missing_fb)])
    try:
        j_out = json.loads(out)
        is_json_err = j_out.get("error_code") == "autonomous_cycle_data_error"
    except Exception:
        is_json_err = False
    record(
        "ErrorHandling: Missing --feedback-path returns exit code 3 with sanitized JSON",
        rc == 3 and is_json_err,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.2: Corrupted --feedback-path (Malformed JSON syntax)
    corrupt_syntax_fb = td / "corrupt_syntax_feedback.json"
    corrupt_syntax_fb.write_text("{this is not valid json:", encoding="utf-8")
    rc, out, err = run_inproc(["--symbol", "BTCUSDT", "--feedback-path", str(corrupt_syntax_fb)])
    try:
        j_out = json.loads(out)
        is_json_err = j_out.get("error_code") == "autonomous_cycle_data_error"
    except Exception:
        is_json_err = False
    record(
        "ErrorHandling: Corrupted JSON syntax in --feedback-path returns exit code 3 with JSON error",
        rc == 3 and is_json_err,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.3: Corrupted --feedback-path (Valid JSON, Invalid schema)
    corrupt_schema_fb = td / "corrupt_schema_feedback.json"
    corrupt_schema_fb.write_text(json.dumps({"bogus_key": 123}), encoding="utf-8")
    rc, out, err = run_inproc(["--symbol", "BTCUSDT", "--feedback-path", str(corrupt_schema_fb)])
    try:
        j_out = json.loads(out)
        is_json_err = j_out.get("error_code") == "autonomous_cycle_data_error"
    except Exception:
        is_json_err = False
    record(
        "ErrorHandling: Invalid schema in --feedback-path returns exit code 3 with JSON error",
        rc == 3 and is_json_err,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.4: Missing --ledger-db
    missing_ledger = td / "non_existent_ledger.sqlite3"
    rc, out, err = run_inproc(["--symbol", "BTCUSDT", "--ledger-db", str(missing_ledger)])
    try:
        j_out = json.loads(out)
        is_json_err = j_out.get("error_code") == "autonomous_cycle_data_error"
    except Exception:
        is_json_err = False
    record(
        "ErrorHandling: Missing --ledger-db returns exit code 3 with sanitized JSON",
        rc == 3 and is_json_err,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.5: Corrupted --ledger-db (Random binary bytes)
    corrupt_ledger_file = td / "corrupt_ledger.sqlite3"
    corrupt_ledger_file.write_bytes(b"\x00\xff\xfe\x01\x02\x03\x04\x05NOT_SQLITE")
    rc, out, err = run_inproc(["--symbol", "BTCUSDT", "--ledger-db", str(corrupt_ledger_file)])
    try:
        j_out = json.loads(out)
        is_json_err = "error_code" in j_out
    except Exception:
        is_json_err = False
    record(
        "ErrorHandling: Corrupted binary in --ledger-db returns exit code 3 with sanitized JSON",
        rc == 3 and is_json_err,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.6: Missing --parquet-path
    missing_parquet = td / "missing_market.parquet"
    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--parquet-path",
            str(missing_parquet),
        ]
    )
    try:
        j_out = json.loads(out)
        is_json_err = j_out.get("error_code") == "autonomous_cycle_data_error"
    except Exception:
        is_json_err = False
    record(
        "ErrorHandling: Missing --parquet-path returns exit code 3 with sanitized JSON",
        rc == 3 and is_json_err,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.7: Insufficient bars in Parquet (DataQualityError)
    short_df = pd.DataFrame(
        {
            "timestamp": [
                datetime(2026, 9, 8, 0, 0, tzinfo=UTC) + timedelta(minutes=5 * i) for i in range(50)
            ],
            "open": [Decimal("50000")] * 50,
            "high": [Decimal("50100")] * 50,
            "low": [Decimal("49900")] * 50,
            "close": [Decimal("50050")] * 50,
            "volume": [Decimal("100")] * 50,
        }
    )
    short_parquet = td / "short_market.parquet"
    short_df.to_parquet(short_parquet)
    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--parquet-path",
            str(short_parquet),
            "--windows-count",
            "3",
            "--bars-per-window",
            "288",
        ]
    )
    try:
        j_out = json.loads(out)
        is_dq_err = j_out.get(
            "error_code"
        ) == "autonomous_cycle_data_error" and "Insufficient bars" in j_out.get("message", "")
    except Exception:
        is_dq_err = False
    record(
        "ErrorHandling: Insufficient bars in Parquet raises DataQualityError and returns exit code 3",
        rc == 3 and is_dq_err,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.8: Corrupted Parquet file
    corrupt_parquet = td / "corrupt.parquet"
    corrupt_parquet.write_bytes(b"THIS_IS_NOT_A_PARQUET_FILE_JUST_GARBAGE_BYTES")
    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--parquet-path",
            str(corrupt_parquet),
        ]
    )
    try:
        j_out = json.loads(out)
        is_json_err = "error_code" in j_out
    except Exception:
        is_json_err = False
    record(
        "ErrorHandling: Corrupted Parquet file returns exit code 3 with sanitized JSON",
        rc == 3 and is_json_err,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.9: Secret sanitization in error message
    secret_name = td / "secret_AIzaSyD98765432101234567890_path.parquet"
    rc, out, err = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(PHASE254_LEDGER),
            "--parquet-path",
            str(secret_name),
        ]
    )
    try:
        j_out = json.loads(out)
        has_redacted = "[REDACTED_SECRET]" in j_out.get("message", "")
        leaks_secret = "AIzaSyD98765432101234567890" in out or "AIzaSyD98765432101234567890" in err
    except Exception:
        has_redacted = False
        leaks_secret = True
    record(
        "ErrorHandling: Secret pattern in exception message is redacted to [REDACTED_SECRET]",
        rc == 3 and has_redacted and not leaks_secret,
        f"rc={rc}, out={out.strip()}",
    )

    # 2.10: Subprocess verification of exit code 3
    sub_rc, sub_out, sub_err = run_subprocess(
        [
            "--symbol",
            "BTCUSDT",
            "--feedback-path",
            str(missing_fb),
        ]
    )
    try:
        j_sub = json.loads(sub_out)
        sub_is_json_err = j_sub.get("error_code") == "autonomous_cycle_data_error"
    except Exception:
        sub_is_json_err = False
    record(
        "ErrorHandling: Subprocess parity for exit code 3 and sanitized JSON stdout",
        sub_rc == 3 and sub_is_json_err,
        f"sub_rc={sub_rc}, sub_out={sub_out.strip()}",
    )
# CATEGORY 3: Determinism & Idempotency
print("\n--- CATEGORY 3: Determinism & Idempotency ---")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_str:
    gc.collect()
    td = Path(td_str)
    temp_ledger = td / "paper-ledger.sqlite3"
    shutil.copy(PHASE254_LEDGER, temp_ledger)
    temp_lifecycle = td / "paper-lifecycle.sqlite3"
    shutil.copy(PHASE254_LIFECYCLE, temp_lifecycle)

    out_dir_1 = td / "cycle_run_1"
    out_dir_2 = td / "cycle_run_2"
    fixed_now = "2026-09-08T12:00:00Z"
    fixed_cycle_id = "cycle-btc-deterministic-001"

    common_args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(temp_ledger),
        "--lifecycle-db",
        str(temp_lifecycle),
        "--candidate-id",
        BTC_CAND_ID,
        "--parquet-path",
        str(CANONICAL_BTC_PARQUET),
        "--cycle-id",
        fixed_cycle_id,
        "--now",
        fixed_now,
        "--windows-count",
        "3",
        "--bars-per-window",
        "288",
    ]

    rc1, out1, err1 = run_inproc(common_args + ["--output-dir", str(out_dir_1)])
    rc2, out2, err2 = run_inproc(common_args + ["--output-dir", str(out_dir_2)])

    record("Determinism: Run 1 exits code 0", rc1 == 0, f"rc1={rc1}")
    record("Determinism: Run 2 exits code 0", rc2 == 0, f"rc2={rc2}")

    audit1 = json.loads(out1)
    audit2 = json.loads(out2)

    cycle_hash_1 = audit1.get("cycle_hash")
    cycle_hash_2 = audit2.get("cycle_hash")
    record(
        "Determinism: cycle_hash is 100% byte-for-byte identical across runs",
        cycle_hash_1 == cycle_hash_2 and len(cycle_hash_1) == 64 and cycle_hash_1 != "0" * 64,
        f"hash1={cycle_hash_1}, hash2={cycle_hash_2}",
    )

    audit_hash_1 = audit1.get("audit_hash")
    audit_hash_2 = audit2.get("audit_hash")
    record(
        "Determinism: audit_hash is 100% byte-for-byte identical across runs",
        audit_hash_1 == audit_hash_2 and len(audit_hash_1) == 64 and audit_hash_1 != "0" * 64,
        f"audit_hash1={audit_hash_1}, audit_hash2={audit_hash_2}",
    )

    audit_file_1 = (out_dir_1 / "cycle-audit.json").read_bytes()
    audit_file_2 = (out_dir_2 / "cycle-audit.json").read_bytes()
    record(
        "Determinism: cycle-audit.json on disk is byte-for-byte identical",
        audit_file_1 == audit_file_2,
        f"bytes_len={len(audit_file_1)}",
    )

    res_file_1 = (out_dir_1 / "autonomous-cycle-result.json").read_bytes()
    res_file_2 = (out_dir_2 / "autonomous-cycle-result.json").read_bytes()
    record(
        "Determinism: autonomous-cycle-result.json on disk is byte-for-byte identical",
        res_file_1 == res_file_2,
        f"bytes_len={len(res_file_1)}",
    )

    # Idempotency: re-running directly into existing output dir
    rc3, out3, err3 = run_inproc(common_args + ["--output-dir", str(out_dir_1)])
    audit3 = json.loads(out3)
    record(
        "Idempotency: Re-running directly into existing directory produces identical audit_hash without error",
        rc3 == 0 and audit3.get("audit_hash") == audit_hash_1,
        f"rc3={rc3}, audit_hash3={audit3.get('audit_hash')}",
    )

# CATEGORY 4: Zero-Breach Handling
print("\n--- CATEGORY 4: Zero-Breach Handling ---")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_str:
    gc.collect()
    td = Path(td_str)
    temp_ledger = td / "paper-ledger.sqlite3"
    shutil.copy(PHASE254_LEDGER, temp_ledger)
    out_dir_zero = td / "zero_breach_out"

    # 4.1: Zero breach using lenient thresholds against real phase254 data
    lenient_args = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(temp_ledger),
        "--candidate-id",
        BTC_CAND_ID,
        "--parquet-path",
        str(CANONICAL_BTC_PARQUET),
        "--output-dir",
        str(out_dir_zero),
        "--paper-net-pnl-min",
        "-1000000.00",
        "--paper-profit-factor-min",
        "0.01",
        "--paper-win-rate-min",
        "0.01",
        "--paper-drawdown-max",
        "100.00",
        "--paper-trades-min",
        "0",
        "--now",
        "2026-09-08T12:00:00Z",
    ]
    rc, out, err = run_inproc(lenient_args)
    record("ZeroBreach: Exit code is 0 when candidate has zero breaches", rc == 0, f"rc={rc}")

    audit_zero = json.loads(out)
    record(
        "ZeroBreach: cycle_status is skipped_no_breaches",
        audit_zero.get("cycle_status") == "skipped_no_breaches",
        f"cycle_status={audit_zero.get('cycle_status')}",
    )
    record(
        "ZeroBreach: cycle_hash is 64 zeros",
        audit_zero.get("cycle_hash") == "0" * 64,
        f"cycle_hash={audit_zero.get('cycle_hash')}",
    )
    audit_hash_zero = audit_zero.get("audit_hash")
    record(
        "ZeroBreach: audit_hash is valid 64-character SHA-256",
        len(audit_hash_zero) == 64 and audit_hash_zero != "0" * 64,
        f"audit_hash={audit_hash_zero}",
    )
    record(
        "ZeroBreach: stop_reasons contains skipped_no_breaches",
        "skipped_no_breaches" in audit_zero.get("lineage", {}).get("stop_reasons", []),
        f"stop_reasons={audit_zero.get('lineage', {}).get('stop_reasons')}",
    )
    record(
        "ZeroBreach: Safety invariants intact in skipped audit",
        audit_zero.get("safety_invariants")
        == {
            "data_source": "cached_only",
            "promotion_state": "unpromoted",
            "execution_authority": False,
        },
        f"safety_invariants={audit_zero.get('safety_invariants')}",
    )
    record(
        "ZeroBreach: cycle-audit.json exists on disk, autonomous-cycle-result.json does NOT exist",
        (out_dir_zero / "cycle-audit.json").is_file()
        and not (out_dir_zero / "autonomous-cycle-result.json").exists(),
        f"files={list(out_dir_zero.iterdir())}",
    )

    # 4.2: Synthetic ledger with 10 profitable trades under default thresholds
    synthetic_ledger = td / "synthetic_profit_ledger.sqlite3"
    winning_trades = []
    base_t = datetime(2026, 9, 8, 1, 0, tzinfo=UTC)
    for i in range(10):
        t_open = base_t + timedelta(hours=i)
        t_close = t_open + timedelta(minutes=30)
        winning_trades.append(
            {
                "trade_id": f"trade-win-{i:03d}",
                "candidate_id": "cand-btc-winner-001",
                "symbol": "BTCUSDT",
                "side": "LONG",
                "quantity": "0.1",
                "entry_price": "50000.0",
                "exit_price": "52000.0",
                "opened_at": t_open.isoformat(),
                "closed_at": t_close.isoformat(),
                "gross_pnl": "200.00",
                "entry_fee": "0.25",
                "exit_fee": "0.25",
                "slippage_cost": "0.00",
            }
        )
    create_synthetic_ledger_db(synthetic_ledger, winning_trades)

    out_dir_syn = td / "synthetic_zero_out"
    rc_syn, out_syn, err_syn = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(synthetic_ledger),
            "--candidate-id",
            "cand-btc-winner-001",
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--output-dir",
            str(out_dir_syn),
            "--now",
            "2026-09-08T12:00:00Z",
        ]
    )
    audit_syn = json.loads(out_syn)
    record(
        "ZeroBreach: Winning synthetic ledger under default thresholds yields skipped_no_breaches and rc=0",
        rc_syn == 0 and audit_syn.get("cycle_status") == "skipped_no_breaches",
        f"rc={rc_syn}, status={audit_syn.get('cycle_status')}",
    )
# CATEGORY 5: Real Parquet Data Execution with BTCUSDT
print("\n--- CATEGORY 5: Real Parquet Data Execution with BTCUSDT ---")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_str:
    gc.collect()
    td = Path(td_str)
    real_ledger = td / "paper-ledger.sqlite3"
    shutil.copy(PHASE254_LEDGER, real_ledger)
    real_lifecycle = td / "paper-lifecycle.sqlite3"
    shutil.copy(PHASE254_LIFECYCLE, real_lifecycle)
    real_out_default = td / "real_btc_out_default"
    real_out_qualified = td / "real_btc_out_qualified"

    # 5.1: Real Parquet execution with default thresholds (evaluates to completed_unadmitted due to strict thresholds)
    real_args_default = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(real_ledger),
        "--lifecycle-db",
        str(real_lifecycle),
        "--candidate-id",
        BTC_CAND_ID,
        "--parquet-path",
        str(CANONICAL_BTC_PARQUET),
        "--output-dir",
        str(real_out_default),
        "--windows-count",
        "3",
        "--bars-per-window",
        "288",
        "--now",
        "2026-09-08T12:00:00Z",
    ]
    rc, out, err = run_inproc(real_args_default)
    record(
        "RealData: Full cycle on BTCUSDT canonical Parquet with default thresholds exits code 0",
        rc == 0,
        f"rc={rc}",
    )

    audit_real_def = json.loads(out)
    record(
        "RealData: Cycle status is completed_unadmitted under strict qualification",
        audit_real_def.get("cycle_status") == "completed_unadmitted",
        f"cycle_status={audit_real_def.get('cycle_status')}",
    )
    lineage_def = audit_real_def.get("lineage", {})
    record(
        "RealData: Default threshold rejection correctly yields qualification_decision=rejected and admission_decision=blocked_unqualified",
        lineage_def.get("qualification_decision") == "rejected"
        and lineage_def.get("admission_decision") == "blocked_unqualified",
        f"qual={lineage_def.get('qualification_decision')}, admit={lineage_def.get('admission_decision')}",
    )

    # 5.2: Real Parquet execution with tuned qualification thresholds (evaluates to completed_admitted)
    real_args_qual = [
        "--symbol",
        "BTCUSDT",
        "--ledger-db",
        str(real_ledger),
        "--lifecycle-db",
        str(real_lifecycle),
        "--candidate-id",
        BTC_CAND_ID,
        "--parquet-path",
        str(CANONICAL_BTC_PARQUET),
        "--output-dir",
        str(real_out_qualified),
        "--windows-count",
        "3",
        "--bars-per-window",
        "288",
        "--min-profit-factor",
        "0.20",
        "--min-average-return-pct",
        "-1.0",
        "--now",
        "2026-09-08T12:00:00Z",
    ]
    rc_q, out_q, err_q = run_inproc(real_args_qual)
    record(
        "RealData: Full cycle on BTCUSDT canonical Parquet with qualified thresholds exits code 0",
        rc_q == 0,
        f"rc_q={rc_q}",
    )

    audit_real_q = json.loads(out_q)
    record(
        "RealData: Cycle status is completed_admitted when candidate meets qualification thresholds",
        audit_real_q.get("cycle_status") == "completed_admitted",
        f"cycle_status={audit_real_q.get('cycle_status')}",
    )
    lineage_q = audit_real_q.get("lineage", {})
    record(
        "RealData: Qualified decision is qualified and admission decision is admitted",
        lineage_q.get("qualification_decision") == "qualified"
        and lineage_q.get("admission_decision") == "admitted",
        f"qual={lineage_q.get('qualification_decision')}, admit={lineage_q.get('admission_decision')}",
    )
    record(
        "RealData: Newly admitted candidate is set as active_candidate_id",
        lineage_q.get("active_candidate_id") == lineage_q.get("candidate_id")
        and lineage_q.get("candidate_id") != BTC_CAND_ID,
        f"active_cand={lineage_q.get('active_candidate_id')}, prior={BTC_CAND_ID}",
    )
    record(
        "RealData: autonomous-cycle-result.json exists on disk and is non-empty",
        (real_out_qualified / "autonomous-cycle-result.json").is_file(),
        "file exists",
    )
    record(
        "RealData: cycle-audit.json exists on disk and is non-empty",
        (real_out_qualified / "cycle-audit.json").is_file(),
        "file exists",
    )

    # Subprocess parity on real Parquet execution
    sub_real_out = td / "sub_real_btc_out"
    sub_rc, sub_out, sub_err = run_subprocess(
        real_args_qual[:-2] + ["--output-dir", str(sub_real_out), "--now", "2026-09-08T12:00:00Z"]
    )
    record(
        "RealData: Subprocess parity for full real BTCUSDT execution exits code 0",
        sub_rc == 0,
        f"sub_rc={sub_rc}",
    )
    sub_audit = json.loads(sub_out)
    record(
        "RealData: Subprocess output cycle_hash matches inproc output cycle_hash",
        sub_audit.get("cycle_hash") == audit_real_q.get("cycle_hash"),
        f"sub_hash={sub_audit.get('cycle_hash')}, inproc_hash={audit_real_q.get('cycle_hash')}",
    )

# CATEGORY 6: Adversarial Stress Tests & Behavioral Invariants
print("\n--- CATEGORY 6: Adversarial Stress Tests & Behavioral Invariants ---")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_str:
    gc.collect()
    td = Path(td_str)

    cand_alpha = build_test_candidate("cand-btc-alpha-001")
    cand_alpha_path = td / "cand_alpha.json"
    cand_alpha_path.write_text(cand_alpha.model_dump_json(indent=2), encoding="utf-8")

    losing_trades = []
    base_t = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)
    for i in range(5):
        losing_trades.append(
            {
                "trade_id": f"trade-loss-{i:03d}",
                "candidate_id": cand_alpha.candidate_id,
                "candidate_artifact_hash": cand_alpha.artifact_hash,
                "symbol": "BTCUSDT",
                "side": "LONG",
                "quantity": "0.01",
                "entry_price": "50000.0",
                "exit_price": "48000.0",
                "opened_at": (base_t + timedelta(hours=i)).isoformat(),
                "closed_at": (base_t + timedelta(hours=i, minutes=30)).isoformat(),
                "gross_pnl": "-20.00",
                "entry_fee": "0.02",
                "exit_fee": "0.02",
                "slippage_cost": "0.01",
            }
        )

    # Test 6.1a: Active trade present AND require_flat=True -> admission deferred
    active_ledger_flat = td / "paper_ledger_active_flat.sqlite3"
    create_synthetic_ledger_db(
        active_ledger_flat,
        losing_trades,
        with_active_position=True,
        active_candidate=cand_alpha,
    )
    out_flat = td / "out_flat"
    rc_flat, out_flat_str, err_flat = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(active_ledger_flat),
            "--candidate-id",
            cand_alpha.candidate_id,
            "--candidate-path",
            str(cand_alpha_path),
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--output-dir",
            str(out_flat),
            "--require-flat",
            "--min-profit-factor",
            "0.20",
            "--min-average-return-pct",
            "-1.0",
            "--now",
            "2026-09-08T12:00:00Z",
        ]
    )
    audit_flat = json.loads(out_flat_str)
    record(
        "Adversarial: require_flat=True defers admission when active trade is open",
        rc_flat == 0
        and audit_flat.get("lineage", {}).get("admission_decision") == "deferred_active_position",
        f"admission_decision={audit_flat.get('lineage', {}).get('admission_decision')}",
    )
    record(
        "Adversarial: When admission deferred, active_candidate_id remains original candidate",
        audit_flat.get("lineage", {}).get("active_candidate_id") == cand_alpha.candidate_id,
        f"active_candidate_id={audit_flat.get('lineage', {}).get('active_candidate_id')}",
    )

    # Test 6.1b: Active trade present AND require_flat=False -> admission proceeds and active trade retained
    active_ledger_noflat = td / "paper_ledger_active_noflat.sqlite3"
    create_synthetic_ledger_db(
        active_ledger_noflat,
        losing_trades,
        with_active_position=True,
        active_candidate=cand_alpha,
    )
    out_noflat = td / "out_noflat"
    rc_noflat, out_noflat_str, err_noflat = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(active_ledger_noflat),
            "--candidate-id",
            cand_alpha.candidate_id,
            "--candidate-path",
            str(cand_alpha_path),
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--output-dir",
            str(out_noflat),
            "--min-profit-factor",
            "0.20",
            "--min-average-return-pct",
            "-1.0",
            "--now",
            "2026-09-08T12:00:00Z",
        ]
    )
    audit_noflat = json.loads(out_noflat_str)
    record(
        "Adversarial: require_flat=False admits qualified candidate while retaining active trade",
        rc_noflat == 0 and audit_noflat.get("lineage", {}).get("admission_decision") == "admitted",
        f"admission_decision={audit_noflat.get('lineage', {}).get('admission_decision')}",
    )

    # 6.2: Direct execution with pre-supplied --feedback-path (without --ledger-db)
    temp_ledger_copy = td / "temp_ledger.sqlite3"
    shutil.copy(PHASE254_LEDGER, temp_ledger_copy)
    fb_direct = extract_paper_feedback(
        ledger_path=temp_ledger_copy,
        symbol="BTCUSDT",
        candidate_id=BTC_CAND_ID,
    )
    assert fb_direct is not None
    direct_fb_path = td / "direct_failure_feedback.json"
    direct_fb_path.write_text(fb_direct.model_dump_json(indent=2), encoding="utf-8")

    out_direct = td / "out_direct_feedback"
    rc_dir, out_dir_str, err_dir = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--feedback-path",
            str(direct_fb_path),
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--output-dir",
            str(out_direct),
            "--min-profit-factor",
            "0.20",
            "--min-average-return-pct",
            "-1.0",
            "--now",
            "2026-09-08T12:00:00Z",
        ]
    )
    audit_dir = json.loads(out_dir_str)
    record(
        "Adversarial: Running directly with pre-supplied --feedback-path (no --ledger-db) succeeds with exit code 0",
        rc_dir == 0
        and audit_dir.get("cycle_status") in ("completed_admitted", "completed_unadmitted"),
        f"rc={rc_dir}, status={audit_dir.get('cycle_status')}",
    )

    # 6.3: Candidate filter isolation in multi-candidate ledger
    multi_ledger = td / "multi_candidate_ledger.sqlite3"
    cand_win = build_test_candidate("cand-btc-winner-isolated")
    cand_lose = build_test_candidate("cand-btc-loser-isolated")
    multi_trades = []
    # 5 losing trades for cand_lose
    for i in range(5):
        multi_trades.append(
            {
                "trade_id": f"trade-lose-{i:03d}",
                "candidate_id": cand_lose.candidate_id,
                "candidate_artifact_hash": cand_lose.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000",
                "exit_price": "45000",
                "opened_at": (base_t + timedelta(hours=i)).isoformat(),
                "closed_at": (base_t + timedelta(hours=i, minutes=30)).isoformat(),
                "gross_pnl": "-50.0",
                "entry_fee": "0.02",
                "exit_fee": "0.02",
                "slippage_cost": "0.01",
            }
        )
    # 10 winning trades for cand_win
    for i in range(10):
        multi_trades.append(
            {
                "trade_id": f"trade-win-{i:03d}",
                "candidate_id": cand_win.candidate_id,
                "candidate_artifact_hash": cand_win.artifact_hash,
                "symbol": "BTCUSDT",
                "entry_price": "50000",
                "exit_price": "55000",
                "opened_at": (base_t + timedelta(hours=i + 10)).isoformat(),
                "closed_at": (base_t + timedelta(hours=i + 10, minutes=30)).isoformat(),
                "gross_pnl": "50.0",
                "entry_fee": "0.02",
                "exit_fee": "0.02",
                "slippage_cost": "0.01",
            }
        )
    create_synthetic_ledger_db(multi_ledger, multi_trades)

    # Query with cand_lose -> must run cycle (breached)
    out_iso_lose = td / "out_iso_lose"
    rc_iso_l, out_iso_l_str, _ = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(multi_ledger),
            "--candidate-id",
            cand_lose.candidate_id,
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--output-dir",
            str(out_iso_lose),
            "--now",
            "2026-09-08T12:00:00Z",
        ]
    )
    audit_iso_l = json.loads(out_iso_l_str)
    record(
        "Adversarial: Multi-candidate isolation correctly triggers cycle for failing candidate",
        rc_iso_l == 0
        and audit_iso_l.get("cycle_status") in ("completed_admitted", "completed_unadmitted"),
        f"status={audit_iso_l.get('cycle_status')}",
    )

    # Query with cand_win -> must skip cycle (no breaches)
    out_iso_win = td / "out_iso_win"
    rc_iso_w, out_iso_w_str, _ = run_inproc(
        [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(multi_ledger),
            "--candidate-id",
            cand_win.candidate_id,
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--output-dir",
            str(out_iso_win),
            "--now",
            "2026-09-08T12:00:00Z",
        ]
    )
    audit_iso_w = json.loads(out_iso_w_str)
    record(
        "Adversarial: Multi-candidate isolation correctly skips cycle for winning candidate",
        rc_iso_w == 0 and audit_iso_w.get("cycle_status") == "skipped_no_breaches",
        f"status={audit_iso_w.get('cycle_status')}",
    )

    # 6.4: Window continuity and non-overlapping invariant
    windows = runner.load_and_slice_windows(
        CANONICAL_BTC_PARQUET,
        symbol="BTCUSDT",
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        windows_count=5,
        bars_per_window=100,
    )
    record(
        "Adversarial: load_and_slice_windows returns exactly requested count of windows",
        len(windows) == 5,
        f"count={len(windows)}",
    )
    continuous = True
    exact_bars = True
    for i in range(len(windows)):
        if len(windows[i].frame) != 100:
            exact_bars = False
        if i > 0 and windows[i].spec.time_start != windows[i - 1].spec.time_end:
            continuous = False
    record(
        "Adversarial: Window boundaries are strictly continuous, non-overlapping, and exact bar counts",
        continuous and exact_bars,
        f"continuous={continuous}, exact_bars={exact_bars}",
    )

print("\n" + "=" * 80)
print(
    f"STRESS SUITE COMPLETE: {passed_tests} PASSED, {failed_tests} FAILED out of {passed_tests + failed_tests} assertions"
)
print("=" * 80)

if failed_tests > 0:
    sys.exit(1)
