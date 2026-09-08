"""Empirical Challenger Verification Suite for Milestone 2 Iteration 3.

Empirically tests:
1. 81/81 assertions in verification/stress_test_autonomous_cycle_cli.py
2. Repeat execution idempotency with fixed --now (inproc & subprocess parity, byte-for-byte artifact identity, in-place re-runs)
"""

# ruff: noqa: E402, E501

from __future__ import annotations

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

import scripts.run_autonomous_cycle as runner
from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import TickerSnapshot
from autonomous_futures.paper.feedback_extractor import extract_paper_feedback
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.paper.sqlite_ledger import PaperRestartRecoveryError
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    _artifact_content_hash,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
    build_creator_qualification_failure_feedback,
)
from autonomous_futures.research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    QualificationGateResult,
    QualificationMetric,
    _qualification_content_hash,
)

CANONICAL_BTC_PARQUET = (
    PROJECT_ROOT / "research" / "immutable-data" / "5m" / "canonical" / "BTCUSDT-5m.parquet"
)
PHASE254_LEDGER = PROJECT_ROOT / "artifacts" / "research" / "phase254" / "paper-ledger.sqlite3"
PHASE254_LIFECYCLE = (
    PROJECT_ROOT / "artifacts" / "research" / "phase254" / "paper-lifecycle.sqlite3"
)
BTC_CAND_ID = "cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74"
NOW_FIXED = "2026-09-08T12:00:00Z"
NOW_DT = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

passed_count = 0
failed_count = 0
log_records: list[dict[str, Any]] = []


def record(test_id: str, condition: bool, details: str = ""):
    global passed_count, failed_count
    status = "PASS" if condition else "FAIL"
    if condition:
        passed_count += 1
    else:
        failed_count += 1
    print(f"[{status}] {test_id}")
    if details:
        print(f"       {details}")
    log_records.append({"id": test_id, "status": status, "details": details})


def run_inproc(argv: list[str]) -> tuple[int, str, str]:
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        try:
            rc = runner.main(argv)
        except Exception as exc:
            rc = 999
            err_buf.write(f"UNHANDLED: {exc}\n")
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


def build_candidate_artifact(
    candidate_id: str,
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trail_mult: str = "1.0",
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
            stop_atr_multiplier=Decimal(stop_mult),
            take_profit_atr_multiplier=Decimal(tp_mult),
            trailing_atr_multiplier=Decimal(trail_mult),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=runner.DEFAULT_BUNDLE_HASH,
        dataset_registry_hash=runner.DEFAULT_REGISTRY_HASH,
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=NOW_DT,
    )


def build_qualification(
    candidate: CreatorCandidateArtifact, decision: str = "rejected"
) -> CreatorCandidateQualificationArtifact:
    gates = (
        QualificationGateResult(
            gate_id="oos_profit_factor_min",
            passed=decision == "qualified",
            observed=Decimal("1.5"),
            threshold=Decimal("1.0"),
            comparator="gte",
            reason_code="oos_profit_factor_acceptable"
            if decision == "qualified"
            else "oos_profit_factor_below_threshold",
        ),
    )
    metrics = (QualificationMetric(metric_id="profit_factor", value=Decimal("1.5")),)
    provisional = CreatorCandidateQualificationArtifact.model_validate(
        {
            "qualification_version": 1,
            "candidate_id": candidate.candidate_id,
            "candidate_artifact_hash": candidate.artifact_hash,
            "bundle_hash": candidate.bundle_hash,
            "dataset_registry_hash": candidate.dataset_registry_hash,
            "evaluator_run_id": "run-test-eval-001",
            "evaluator_version": "1.0.0",
            "decision": decision,
            "metrics": metrics,
            "gates": gates,
            "windows_evaluated": 5,
            "qualification_policy_id": "policy-test-001",
            "oos_aggregation_hash": "d" * 64,
            "source": "walk_forward_oos",
            "evaluated_at": NOW_DT,
            "promotion_state": "unpromoted",
            "execution_authority": False,
            "qualification_hash": "0" * 64,
        }
    )
    return provisional.model_copy(
        update={"qualification_hash": _qualification_content_hash(provisional)}
    )


def build_failure_feedback(
    candidate: CreatorCandidateArtifact,
) -> CreatorQualificationFailureFeedback:
    qualification = build_qualification(candidate, decision="rejected")
    fb = build_creator_qualification_failure_feedback(qualification)
    assert fb is not None
    return fb


def test_suite_stress_test_assertions():
    print("\n--- TEST GROUP 1: Stress Test Suite Verification (81/81 assertions) ---")
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "verification" / "stress_test_autonomous_cycle_cli.py"),
    ]
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    record(
        "G1.1: stress_test_autonomous_cycle_cli.py exits with code 0",
        res.returncode == 0,
        f"returncode={res.returncode}",
    )
    has_81_passed = "81 PASSED, 0 FAILED out of 81 assertions" in res.stdout
    record(
        "G1.2: Exactly 81 PASSED, 0 FAILED confirmed in output",
        has_81_passed,
        f"found 81/81 statement: {has_81_passed}",
    )


def test_suite_idempotency_and_determinism():
    print("\n--- TEST GROUP 2: Repeat Execution Idempotency & Determinism (Fixed --now) ---")
    with tempfile.TemporaryDirectory() as td_str:
        td = Path(td_str)

        # Create a synthetic failure feedback JSON
        cand_orig = build_candidate_artifact("cand-test-det-001")
        cand_path = td / "cand_orig.json"
        cand_path.write_text(cand_orig.model_dump_json(indent=2), encoding="utf-8")

        fb = build_failure_feedback(cand_orig)
        fb_path = td / "feedback.json"
        fb_path.write_text(fb.model_dump_json(indent=2), encoding="utf-8")

        # 2.1: In-process repeat runs to different output dirs
        out1 = td / "out1"
        out2 = td / "out2"
        common_args = [
            "--symbol",
            "BTCUSDT",
            "--feedback-path",
            str(fb_path),
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--now",
            NOW_FIXED,
            "--windows-count",
            "3",
            "--bars-per-window",
            "288",
        ]

        rc1, out1_str, err1 = run_inproc(common_args + ["--output-dir", str(out1)])
        rc2, out2_str, err2 = run_inproc(common_args + ["--output-dir", str(out2)])

        record(
            "G2.1: In-proc Run 1 and Run 2 exit with code 0",
            rc1 == 0 and rc2 == 0,
            f"rc1={rc1}, rc2={rc2}",
        )
        audit1 = json.loads(out1_str)
        audit2 = json.loads(out2_str)

        record(
            "G2.2: cycle_hash is bitwise identical across in-proc runs",
            audit1["cycle_hash"] == audit2["cycle_hash"],
            f"cycle_hash={audit1['cycle_hash']}",
        )
        record(
            "G2.3: audit_hash is bitwise identical across in-proc runs",
            audit1["audit_hash"] == audit2["audit_hash"],
            f"audit_hash={audit1['audit_hash']}",
        )

        res_bytes1 = (out1 / "autonomous-cycle-result.json").read_bytes()
        res_bytes2 = (out2 / "autonomous-cycle-result.json").read_bytes()
        audit_bytes1 = (out1 / "cycle-audit.json").read_bytes()
        audit_bytes2 = (out2 / "cycle-audit.json").read_bytes()

        record(
            "G2.4: autonomous-cycle-result.json is 100% byte-for-byte identical",
            res_bytes1 == res_bytes2,
            f"bytes={len(res_bytes1)}",
        )
        record(
            "G2.5: cycle-audit.json is 100% byte-for-byte identical",
            audit_bytes1 == audit_bytes2,
            f"bytes={len(audit_bytes1)}",
        )

        # 2.2: Subprocess parity
        out_sub = td / "out_sub"
        sub_rc, sub_out, sub_err = run_subprocess(common_args + ["--output-dir", str(out_sub)])
        record("G2.6: Subprocess run exits with code 0", sub_rc == 0, f"sub_rc={sub_rc}")
        audit_sub = json.loads(sub_out)
        record(
            "G2.7: Subprocess cycle_hash matches in-proc cycle_hash",
            audit_sub["cycle_hash"] == audit1["cycle_hash"],
            f"sub_cycle_hash={audit_sub['cycle_hash']}",
        )
        record(
            "G2.8: Subprocess audit_hash matches in-proc audit_hash",
            audit_sub["audit_hash"] == audit1["audit_hash"],
            f"sub_audit_hash={audit_sub['audit_hash']}",
        )

        # 2.3: In-place rerun idempotency (5 successive runs into same directory)
        inplace_dir = td / "inplace"
        inplace_hashes = []
        for _i in range(5):
            rc_in, out_in_str, _ = run_inproc(common_args + ["--output-dir", str(inplace_dir)])
            if rc_in == 0:
                audit_in = json.loads(out_in_str)
                inplace_hashes.append((audit_in["cycle_hash"], audit_in["audit_hash"]))
        all_match = len(inplace_hashes) == 5 and all(h == inplace_hashes[0] for h in inplace_hashes)
        record(
            "G2.9: 5 successive in-place reruns into same directory succeed with identical hashes",
            all_match,
            f"runs={len(inplace_hashes)}, unique_hashes={len(set(inplace_hashes))}",
        )

        # 2.4: Equivalent ISO timestamp formats (Z vs +00:00)
        out_tz = td / "out_tz"
        rc_tz, out_tz_str, _ = run_inproc(
            [
                "--symbol",
                "BTCUSDT",
                "--feedback-path",
                str(fb_path),
                "--parquet-path",
                str(CANONICAL_BTC_PARQUET),
                "--now",
                "2026-09-08T12:00:00+00:00",
                "--windows-count",
                "3",
                "--bars-per-window",
                "288",
                "--output-dir",
                str(out_tz),
            ]
        )
        audit_tz = json.loads(out_tz_str)
        record(
            "G2.10: ISO 8601 with '+00:00' matches 'Z' deterministically",
            rc_tz == 0
            and audit_tz["cycle_hash"] == audit1["cycle_hash"]
            and audit_tz["audit_hash"] == audit1["audit_hash"],
            f"rc_tz={rc_tz}, hash_match={audit_tz['cycle_hash'] == audit1['cycle_hash']}",
        )


def setup_engine(tmp_path: Path, candidate: CreatorCandidateArtifact) -> LivePaperEngine:
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": candidate},
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
        starting_capital=Decimal("10000.00"),
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50000"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50001"),
        best_ask_qty=Decimal("2"),
        transaction_time=NOW_DT,
        event_time=NOW_DT,
    )
    return engine


def populate_closed_trades(db_path: Path, candidate: CreatorCandidateArtifact, n: int = 5):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    seq = 100
    base_t = datetime(2026, 9, 8, 1, 0, tzinfo=UTC)
    for i in range(n):
        t_open = (base_t + timedelta(hours=i)).isoformat()
        t_close = (base_t + timedelta(hours=i, minutes=25)).isoformat()
        t_id = f"trade-loss-{i:03d}"
        cur.execute(
            """
            INSERT INTO paper_ledger_events VALUES (?, 'open', ?, ?, ?, 'BTCUSDT', 'LONG', '0.01', '50000.0', ?, ?, '0.02', NULL, '0.01', NULL, NULL)
            """,
            (seq, t_id, candidate.candidate_id, candidate.artifact_hash, t_open, f"app-{seq}"),
        )
        seq += 1
        cur.execute(
            """
            INSERT INTO paper_ledger_events VALUES (?, 'close', ?, ?, ?, 'BTCUSDT', 'LONG', '0.01', '48000.0', ?, ?, '0.02', '0.02', '0.01', '-2.00', '-2.04')
            """,
            (seq, t_id, candidate.candidate_id, candidate.artifact_hash, t_close, f"app-{seq}"),
        )
        seq += 1
    conn.commit()
    conn.close()


def test_suite_real_parquet_and_active_live_paper_engine():
    print("\n--- TEST GROUP 3: Real Parquet Market Data & Active LivePaperEngine Execution ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_str:
        gc.collect()
        td = Path(td_str)

        # Copy canonical ledger and lifecycle to temp
        ledger_copy = td / "paper-ledger.sqlite3"
        lifecycle_copy = td / "paper-lifecycle.sqlite3"
        shutil.copy2(PHASE254_LEDGER, ledger_copy)
        shutil.copy2(PHASE254_LIFECYCLE, lifecycle_copy)

        cand_file = (
            PROJECT_ROOT
            / "artifacts"
            / "research"
            / "phase252"
            / "candidates"
            / f"{BTC_CAND_ID}.json"
        )
        cand_initial = CreatorCandidateArtifact.model_validate_json(
            cand_file.read_text(encoding="utf-8")
        )

        # 3.1: Extract feedback from real phase254 ledger
        real_feedback = extract_paper_feedback(
            ledger_path=ledger_copy,
            lifecycle_path=lifecycle_copy,
            symbol="BTCUSDT",
            candidate_id=BTC_CAND_ID,
            candidate_artifact=cand_initial,
        )
        record(
            "G3.1: extract_paper_feedback on real Phase 254 ledger returns valid failure feedback",
            real_feedback is not None and len(real_feedback.failed_gates) > 0,
            f"candidate={BTC_CAND_ID}, failed_gates={real_feedback.failed_gates if real_feedback else None}",
        )

        # 3.2: Real Parquet cycle run with ledger extraction
        out_real_default = td / "out_real_default"
        rc_real, out_real_str, err_real = run_inproc(
            [
                "--symbol",
                "BTCUSDT",
                "--ledger-db",
                str(ledger_copy),
                "--lifecycle-db",
                str(lifecycle_copy),
                "--candidate-id",
                BTC_CAND_ID,
                "--candidate-path",
                str(cand_file),
                "--parquet-path",
                str(CANONICAL_BTC_PARQUET),
                "--output-dir",
                str(out_real_default),
                "--now",
                NOW_FIXED,
            ]
        )
        record(
            "G3.2: Full autonomous cycle on real Parquet & ledger exits code 0",
            rc_real == 0,
            f"rc={rc_real}",
        )
        audit_real = json.loads(out_real_str)
        record(
            "G3.3: Real cycle status is completed_unadmitted under strict default policy",
            audit_real["cycle_status"] == "completed_unadmitted",
            f"status={audit_real['cycle_status']}, qual_decision={audit_real['lineage']['qualification_decision']}",
        )

        # 3.3: Active LivePaperEngine setup with open trade on BTCUSDT
        engine_dir = td / "live_engine_dir"
        engine_dir.mkdir(parents=True, exist_ok=True)
        cand_initial_path = engine_dir / "cand_initial.json"
        cand_initial_path.write_text(cand_initial.model_dump_json(indent=2), encoding="utf-8")

        # Initialize engine and populate closed losing trades to allow feedback extraction
        setup_engine(engine_dir, cand_initial)
        populate_closed_trades(engine_dir / "paper-ledger.sqlite3", cand_initial, n=5)

        live_engine = setup_engine(engine_dir, cand_initial)
        open_res = live_engine.execute_open("BTCUSDT", 1, Decimal("1.0"), NOW_DT)
        record(
            "G3.4: Active position opened cleanly in LivePaperEngine",
            open_res is not None and open_res.status == "opened",
            f"status={getattr(open_res, 'status', None)}",
        )
        active_trade = live_engine.active_trades["BTCUSDT"]
        record(
            "G3.5: Active trade is bound to cand_initial",
            active_trade.candidate.candidate_id == cand_initial.candidate_id
            and active_trade.candidate.artifact_hash == cand_initial.artifact_hash,
            f"trade.candidate={active_trade.candidate.candidate_id}",
        )

        # 3.4: Run CLI cycle targeting live_engine_dir with --require-flat
        out_flat = engine_dir / "out_flat_cli"
        rc_flat, out_flat_str, _ = run_inproc(
            [
                "--symbol",
                "BTCUSDT",
                "--ledger-db",
                str(engine_dir / "paper-ledger.sqlite3"),
                "--lifecycle-db",
                str(engine_dir / "paper-lifecycle.sqlite3"),
                "--candidate-id",
                cand_initial.candidate_id,
                "--candidate-path",
                str(cand_initial_path),
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
                NOW_FIXED,
            ]
        )
        audit_flat = json.loads(out_flat_str)
        record(
            "G3.6: Active position + --require-flat defers candidate admission",
            rc_flat == 0
            and audit_flat["lineage"]["admission_decision"] == "deferred_active_position",
            f"rc={rc_flat}, decision={audit_flat['lineage']['admission_decision']}",
        )
        record(
            "G3.7: In deferred state, active_candidate_id remains original candidate",
            audit_flat["lineage"]["active_candidate_id"] == cand_initial.candidate_id,
            f"active_cand={audit_flat['lineage']['active_candidate_id']}",
        )

        # 3.5: Run CLI cycle without --require-flat -> admits new candidate
        out_admit = engine_dir / "out_admit_cli"
        rc_admit, out_admit_str, _ = run_inproc(
            [
                "--symbol",
                "BTCUSDT",
                "--ledger-db",
                str(engine_dir / "paper-ledger.sqlite3"),
                "--lifecycle-db",
                str(engine_dir / "paper-lifecycle.sqlite3"),
                "--candidate-id",
                cand_initial.candidate_id,
                "--candidate-path",
                str(cand_initial_path),
                "--parquet-path",
                str(CANONICAL_BTC_PARQUET),
                "--output-dir",
                str(out_admit),
                "--min-profit-factor",
                "0.20",
                "--min-average-return-pct",
                "-1.0",
                "--now",
                NOW_FIXED,
            ]
        )
        audit_admit = json.loads(out_admit_str)
        record(
            "G3.8: Autonomous cycle admits newly qualified candidate when require_flat=False",
            rc_admit == 0 and audit_admit["lineage"]["admission_decision"] == "admitted",
            f"rc={rc_admit}, decision={audit_admit['lineage']['admission_decision']}",
        )
        revised_cand_id = audit_admit["lineage"]["active_candidate_id"]

        # Read admitted candidate artifact
        cand_file = out_admit / "candidates" / f"{revised_cand_id}.json"
        record(
            "G3.9: Admitted candidate artifact persisted to disk",
            cand_file.is_file(),
            f"path={cand_file}",
        )
        admitted_cand = runner.read_creator_candidate_artifact(cand_file)
        qual_admitted = build_qualification(admitted_cand, decision="qualified")

        # Admit the newly revised strategy into live_engine
        live_engine.admit_candidate(admitted_cand, qual_admitted, require_flat=False)

        record(
            "G3.10: Engine candidate pool updated to admitted candidate",
            live_engine.candidates["BTCUSDT"].candidate_id == revised_cand_id,
            f"engine.cand={live_engine.candidates['BTCUSDT'].candidate_id}",
        )
        record(
            "G3.11: Active trade strictly retains cand_initial despite engine candidate update",
            live_engine.active_trades["BTCUSDT"].candidate.candidate_id == cand_initial.candidate_id
            and live_engine.active_trades["BTCUSDT"].candidate.artifact_hash
            == cand_initial.artifact_hash,
            f"active_trade.cand={live_engine.active_trades['BTCUSDT'].candidate.candidate_id}",
        )

        # 3.6: Position state retains cand_initial
        pos_states = live_engine.sqlite_ledger.load_position_states()
        record(
            "G3.12: Persisted SQLite position state retains cand_initial candidate_id & hash",
            len(pos_states) == 1
            and pos_states[0]["candidate_id"] == cand_initial.candidate_id
            and pos_states[0]["candidate_artifact_hash"] == cand_initial.artifact_hash,
            f"state={pos_states[0]['candidate_id'] if pos_states else None}",
        )

        # 3.7: Engine Restart Recovery with M2 It3 Cryptographic Content Hash Validation
        del live_engine
        gc.collect()

        restarted_engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": admitted_cand},
            ledger_db=engine_dir / "paper-ledger.sqlite3",
            lifecycle_db=engine_dir / "paper-lifecycle.sqlite3",
            observations_db=engine_dir / "paper-observations.sqlite3",
            starting_capital=Decimal("10000.00"),
        )
        record(
            "G3.13: Restarted engine restores active trade from SQLite position state",
            "BTCUSDT" in restarted_engine.active_trades,
            f"trades={list(restarted_engine.active_trades.keys())}",
        )
        restored_trade = restarted_engine.active_trades["BTCUSDT"]
        record(
            "G3.14: Restored trade candidate reconstructed with exact cand_initial fidelity and passes _artifact_content_hash",
            restored_trade.candidate.candidate_id == cand_initial.candidate_id
            and restored_trade.candidate.artifact_hash == cand_initial.artifact_hash
            and _artifact_content_hash(restored_trade.candidate) == cand_initial.artifact_hash,
            f"restored_cand={restored_trade.candidate.candidate_id}",
        )

        # 3.8: Adversarial Tamper Detection Verification (M2 It3 Security Fix Verification)
        tamper_dir = td / "tamper_dir"
        tamper_dir.mkdir(parents=True, exist_ok=True)
        tamper_ledger = tamper_dir / "paper-ledger.sqlite3"
        conn_t = sqlite3.connect(tamper_ledger)
        conn_t.execute("""
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
        conn_t.execute("""
            CREATE TABLE paper_position_state (
                trade_id TEXT PRIMARY KEY,
                state_version INTEGER NOT NULL,
                state_json TEXT NOT NULL
            );
        """)
        conn_t.execute("""
            CREATE TABLE paper_position_update_intent (
                trade_id TEXT PRIMARY KEY,
                intent TEXT NOT NULL
            );
        """)
        conn_t.execute(
            "INSERT INTO paper_ledger_events VALUES (1, 'open', 't-tamper-01', ?, ?, 'BTCUSDT', 'LONG', '0.01', '50000', '2026-09-08T10:00:00Z', 'app-1', '0.02', NULL, '0.01', NULL, NULL)",
            (cand_initial.candidate_id, cand_initial.artifact_hash),
        )
        tampered_dict = cand_initial.model_dump(mode="json")
        tampered_dict["strategy"]["risk"]["stop_atr_multiplier"] = "99.0"
        tampered_json = json.dumps(tampered_dict, sort_keys=True, separators=(",", ":"))
        pos_tampered = {
            "state_version": 1,
            "trade_id": "t-tamper-01",
            "symbol": "BTCUSDT",
            "side": "LONG",
            "candidate_id": cand_initial.candidate_id,
            "candidate_artifact_hash": cand_initial.artifact_hash,
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
            "strategy_json": tampered_json,
        }
        conn_t.execute(
            "INSERT INTO paper_position_state VALUES ('t-tamper-01', 1, ?)",
            (json.dumps(pos_tampered),),
        )
        conn_t.commit()
        conn_t.close()

        rejected_cleanly = False
        try:
            LivePaperEngine(
                symbols=("BTCUSDT",),
                candidates={"BTCUSDT": admitted_cand},
                ledger_db=tamper_ledger,
                starting_capital=Decimal("10000.00"),
            )
        except PaperRestartRecoveryError:
            rejected_cleanly = True
        except Exception as exc:
            rejected_cleanly = "stale or incompatible" in str(
                exc
            ) or "PaperRestartRecoveryError" in str(type(exc))

        record(
            "G3.15: M2 It3 cryptographic content hash rejects tampered candidate payload during recovery",
            rejected_cleanly,
            f"rejected_cleanly={rejected_cleanly}",
        )


def main():
    print("=" * 80)
    print("EMPIRICAL CHALLENGER VERIFICATION SUITE: Milestone 2 Iteration 3")
    print("=" * 80)

    test_suite_stress_test_assertions()
    test_suite_idempotency_and_determinism()
    test_suite_real_parquet_and_active_live_paper_engine()

    print("\n" + "=" * 80)
    print(
        f"VERIFICATION RESULTS: {passed_count} PASSED, {failed_count} FAILED out of {passed_count + failed_count} assertions"
    )
    print("=" * 80)

    if failed_count > 0:
        print("VERDICT: REQUEST_CHANGES")
        sys.exit(1)
    else:
        print("VERDICT: APPROVE")
        sys.exit(0)


if __name__ == "__main__":
    main()
