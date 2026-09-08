"""Empirical Challenger 2 Verification Suite for Milestone 2 Iteration 2.

Comprehensive empirical verification:
1. Repeat execution idempotency with fixed --now produces 100% identical cycle_hash,
   audit_hash, cycle-audit.json, and autonomous-cycle-result.json.
2. CLI execution with real Parquet data (BTCUSDT) and active LivePaperEngine operates
   without regression across both qualification pass and qualification fail paths.
3. Open trade immutability under candidate admission: active trade retains Candidate A
   artifact, rules, indicators, and ledger attribution even after Candidate B is admitted.
4. Engine restart recovery: an engine initialized with Candidate B correctly recovers an
   active trade opened under Candidate A from SQLite position state with full artifact fidelity.
5. In-place rerun idempotency into existing directory without file corruption.
"""

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
from dataclasses import dataclass
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
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
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
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

passed_count = 0
failed_count = 0
results: list[dict[str, Any]] = []


def record(name: str, passed: bool, details: str = ""):
    global passed_count, failed_count
    status = "PASS" if passed else "FAIL"
    if passed:
        passed_count += 1
    else:
        failed_count += 1
    print(f"[{status}] {name}")
    if details:
        print(f"       {details}")
    results.append({"name": name, "status": status, "details": details})


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


def build_candidate(
    candidate_id: str,
    features: tuple[FeatureRef, ...] | None = None,
    entry: EntryExit | None = None,
    exit_rules: EntryExit | None = None,
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trail_mult: str = "1.0",
    symbol: str = "BTCUSDT",
) -> CreatorCandidateArtifact:
    feats = features or (FeatureRef(name="rsi", lookback=14, shift=1),)
    ent = entry or EntryExit(long="rsi <= 30", short="rsi >= 70")
    ex = exit_rules or EntryExit(long="rsi >= 50", short="rsi <= 50")
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=feats,
        entry=ent,
        exit=ex,
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
        created_at=NOW,
    )


def build_qualification(
    candidate: CreatorCandidateArtifact, decision: str = "qualified"
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
            "evaluated_at": NOW,
            "promotion_state": "unpromoted",
            "execution_authority": False,
            "qualification_hash": "0" * 64,
        }
    )
    return provisional.model_copy(
        update={"qualification_hash": _qualification_content_hash(provisional)}
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
        transaction_time=NOW,
        event_time=NOW,
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


def main():
    print("=" * 80)
    print("STARTING EMPIRICAL CHALLENGER 2 VERIFICATION SUITE")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # PART 1: Repeat Execution Idempotency with Fixed --now
    # -------------------------------------------------------------------------
    print("\n--- PART 1: Repeat Execution Idempotency with Fixed --now ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_str:
        gc.collect()
        td = Path(td_str)
        ledger_copy = td / "paper-ledger.sqlite3"
        shutil.copy(PHASE254_LEDGER, ledger_copy)
        lifecycle_copy = td / "paper-lifecycle.sqlite3"
        shutil.copy(PHASE254_LIFECYCLE, lifecycle_copy)

        # 1.1 Strict qualification (rejected path) repeat determinism
        fixed_now = "2026-09-08T12:00:00Z"
        fixed_cycle_id = "cycle-btc-determ-strict"
        args_strict = [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(ledger_copy),
            "--lifecycle-db",
            str(lifecycle_copy),
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
        out_dir_1a = td / "strict_1a"
        out_dir_1b = td / "strict_1b"

        rc1a, out1a, err1a = run_inproc(args_strict + ["--output-dir", str(out_dir_1a)])
        rc1b, out1b, err1b = run_inproc(args_strict + ["--output-dir", str(out_dir_1b)])

        record(
            "Determinism (Rejected): Both runs exit code 0",
            rc1a == 0 and rc1b == 0,
            f"rc1a={rc1a}, rc1b={rc1b}",
        )
        audit1a = json.loads(out1a)
        audit1b = json.loads(out1b)

        ch1a = audit1a.get("cycle_hash")
        ch1b = audit1b.get("cycle_hash")
        record(
            "Determinism (Rejected): cycle_hash is identical across runs",
            ch1a == ch1b and ch1a is not None and len(ch1a) == 64,
            f"cycle_hash={ch1a}",
        )

        ah1a = audit1a.get("audit_hash")
        ah1b = audit1b.get("audit_hash")
        record(
            "Determinism (Rejected): audit_hash is identical across runs",
            ah1a == ah1b and ah1a is not None and len(ah1a) == 64,
            f"audit_hash={ah1a}",
        )

        audit_file_1a = (out_dir_1a / "cycle-audit.json").read_bytes()
        audit_file_1b = (out_dir_1b / "cycle-audit.json").read_bytes()
        record(
            "Determinism (Rejected): cycle-audit.json on disk is byte-for-byte identical",
            audit_file_1a == audit_file_1b,
            f"bytes={len(audit_file_1a)}",
        )

        res_file_1a = (out_dir_1a / "autonomous-cycle-result.json").read_bytes()
        res_file_1b = (out_dir_1b / "autonomous-cycle-result.json").read_bytes()
        record(
            "Determinism (Rejected): autonomous-cycle-result.json on disk is byte-for-byte identical",
            res_file_1a == res_file_1b,
            f"bytes={len(res_file_1a)}",
        )

        # 1.2 Qualified qualification (admitted path) repeat determinism
        fixed_cycle_id_qual = "cycle-btc-determ-qual"
        args_qual = [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(ledger_copy),
            "--lifecycle-db",
            str(lifecycle_copy),
            "--candidate-id",
            BTC_CAND_ID,
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--cycle-id",
            fixed_cycle_id_qual,
            "--now",
            fixed_now,
            "--windows-count",
            "3",
            "--bars-per-window",
            "288",
            "--min-profit-factor",
            "0.20",
            "--min-average-return-pct",
            "-1.0",
        ]
        out_dir_2a = td / "qual_2a"
        out_dir_2b = td / "qual_2b"

        rc2a, out2a, err2a = run_inproc(args_qual + ["--output-dir", str(out_dir_2a)])
        rc2b, out2b, err2b = run_inproc(args_qual + ["--output-dir", str(out_dir_2b)])

        record(
            "Determinism (Admitted): Both runs exit code 0",
            rc2a == 0 and rc2b == 0,
            f"rc2a={rc2a}, rc2b={rc2b}",
        )
        audit2a = json.loads(out2a)
        audit2b = json.loads(out2b)

        ch2a = audit2a.get("cycle_hash")
        ch2b = audit2b.get("cycle_hash")
        record(
            "Determinism (Admitted): cycle_hash is identical across runs",
            ch2a == ch2b and ch2a is not None and len(ch2a) == 64,
            f"cycle_hash={ch2a}",
        )

        ah2a = audit2a.get("audit_hash")
        ah2b = audit2b.get("audit_hash")
        record(
            "Determinism (Admitted): audit_hash is identical across runs",
            ah2a == ah2b and ah2a is not None and len(ah2a) == 64,
            f"audit_hash={ah2a}",
        )

        audit_file_2a = (out_dir_2a / "cycle-audit.json").read_bytes()
        audit_file_2b = (out_dir_2b / "cycle-audit.json").read_bytes()
        record(
            "Determinism (Admitted): cycle-audit.json on disk is byte-for-byte identical",
            audit_file_2a == audit_file_2b,
            f"bytes={len(audit_file_2a)}",
        )

        res_file_2a = (out_dir_2a / "autonomous-cycle-result.json").read_bytes()
        res_file_2b = (out_dir_2b / "autonomous-cycle-result.json").read_bytes()
        record(
            "Determinism (Admitted): autonomous-cycle-result.json on disk is byte-for-byte identical",
            res_file_2a == res_file_2b,
            f"bytes={len(res_file_2a)}",
        )

        # 1.3 In-place overwrite idempotency (Run into same output directory)
        rc2c, out2c, err2c = run_inproc(args_qual + ["--output-dir", str(out_dir_2a)])
        audit2c = json.loads(out2c)
        record(
            "Idempotency: Re-executing into the exact same output directory succeeds with identical audit_hash",
            rc2c == 0 and audit2c.get("audit_hash") == ah2a and audit2c.get("cycle_hash") == ch2a,
            f"rc={rc2c}, audit_hash={audit2c.get('audit_hash')}",
        )

        # 1.4 Zero-breach repeat determinism
        args_zero = [
            "--symbol",
            "BTCUSDT",
            "--ledger-db",
            str(ledger_copy),
            "--lifecycle-db",
            str(lifecycle_copy),
            "--candidate-id",
            BTC_CAND_ID,
            "--parquet-path",
            str(CANONICAL_BTC_PARQUET),
            "--cycle-id",
            "cycle-btc-determ-zero",
            "--now",
            fixed_now,
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
        ]
        out_dir_0a = td / "zero_0a"
        out_dir_0b = td / "zero_0b"
        rc0a, out0a, _ = run_inproc(args_zero + ["--output-dir", str(out_dir_0a)])
        rc0b, out0b, _ = run_inproc(args_zero + ["--output-dir", str(out_dir_0b)])

        audit0a = json.loads(out0a)
        audit0b = json.loads(out0b)
        record(
            "Determinism (Skipped): Both zero-breach runs produce identical audit_hash",
            rc0a == 0 and rc0b == 0 and audit0a.get("audit_hash") == audit0b.get("audit_hash"),
            f"audit_hash={audit0a.get('audit_hash')}",
        )

    # -------------------------------------------------------------------------
    # PART 2: Real Parquet Data & Live Paper Engine Execution
    # -------------------------------------------------------------------------
    print("\n--- PART 2: Real Parquet Data & Live Paper Engine Execution ---")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td_str:
        gc.collect()
        td = Path(td_str)
        cand_initial = build_candidate("cand-btc-live-initial")
        cand_initial_path = td / "cand_initial.json"
        cand_initial_path.write_text(cand_initial.model_dump_json(indent=2), encoding="utf-8")

        # First setup engine to initialize SQLite schema
        setup_engine(td, cand_initial)

        # Populate 5 historical closed losing trades (from 01:00 to 05:25 UTC)
        populate_closed_trades(td / "paper-ledger.sqlite3", cand_initial, n=5)

        # Reopen engine and execute open trade at 12:00 UTC
        live_engine = setup_engine(td, cand_initial)
        open_res = live_engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        record(
            "LiveEngine: Trade opened cleanly via engine",
            open_res is not None and open_res.status == "opened",
            f"open_res status={getattr(open_res, 'status', None)}",
        )
        record(
            "LiveEngine: Active trade bound to cand_initial",
            "BTCUSDT" in live_engine.active_trades
            and live_engine.active_trades["BTCUSDT"].candidate.candidate_id
            == cand_initial.candidate_id,
            f"trade.candidate={live_engine.active_trades['BTCUSDT'].candidate.candidate_id}",
        )

        # 2.1 Test CLI runner with --require-flat: admission deferred
        out_flat = td / "out_flat_cli"
        rc_flat, out_flat_str, err_flat = run_inproc(
            [
                "--symbol",
                "BTCUSDT",
                "--ledger-db",
                str(td / "paper-ledger.sqlite3"),
                "--lifecycle-db",
                str(td / "paper-lifecycle.sqlite3"),
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
                "2026-09-08T12:00:00Z",
            ]
        )
        print(f"DEBUG: rc_flat={rc_flat}, out_flat_str={out_flat_str!r}, err_flat={err_flat!r}")
        audit_flat = json.loads(out_flat_str) if out_flat_str.strip() else {}
        record(
            "RealParquet + require_flat: CLI run exits 0 and defers admission",
            rc_flat == 0
            and audit_flat.get("lineage", {}).get("admission_decision")
            == "deferred_active_position",
            f"rc={rc_flat}, admission={audit_flat.get('lineage', {}).get('admission_decision')}",
        )
        record(
            "RealParquet + require_flat: active_candidate_id remains cand_initial",
            audit_flat.get("lineage", {}).get("active_candidate_id") == cand_initial.candidate_id,
            f"active_cand={audit_flat.get('lineage', {}).get('active_candidate_id')}",
        )

        # 2.2 Test CLI runner without --require-flat: candidate admitted
        out_admit = td / "out_admit_cli"
        rc_admit, out_admit_str, err_admit = run_inproc(
            [
                "--symbol",
                "BTCUSDT",
                "--ledger-db",
                str(td / "paper-ledger.sqlite3"),
                "--lifecycle-db",
                str(td / "paper-lifecycle.sqlite3"),
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
                "2026-09-08T12:00:00Z",
            ]
        )
        audit_admit = json.loads(out_admit_str)
        record(
            "RealParquet + admission: CLI run exits 0 and admits qualified candidate",
            rc_admit == 0
            and audit_admit.get("lineage", {}).get("admission_decision") == "admitted",
            f"admission={audit_admit.get('lineage', {}).get('admission_decision')}",
        )

        new_candidate_id = audit_admit.get("lineage", {}).get("active_candidate_id")
        record(
            "RealParquet + admission: Newly admitted candidate ID is revised strategy",
            new_candidate_id is not None and new_candidate_id != cand_initial.candidate_id,
            f"new_cand={new_candidate_id}, initial={cand_initial.candidate_id}",
        )

        res_data = json.loads(
            (out_admit / "autonomous-cycle-result.json").read_text(encoding="utf-8")
        )
        cand_file = out_admit / "candidates" / f"{new_candidate_id}.json"
        record(
            "Artifact Persistence: autonomous-cycle-result.json contains full lineage and candidate artifact on disk",
            res_data.get("cycle_status") == "completed_admitted"
            and res_data.get("admission_decision") == "admitted"
            and cand_file.is_file(),
            f"status={res_data.get('cycle_status')}, cand_file_exists={cand_file.is_file()}",
        )

        # -------------------------------------------------------------------------
        # PART 3: Open Trade Immutability and Post-Admission Engine Verification
        # -------------------------------------------------------------------------
        print("\n--- PART 3: Open Trade Immutability and Engine Lifecycle Invariants ---")
        from autonomous_futures.research.creator_artifacts import read_creator_candidate_artifact

        admitted_cand = read_creator_candidate_artifact(cand_file)
        qual_admitted = build_qualification(admitted_cand, decision="qualified")

        # Admit the newly revised strategy into live_engine
        admission_dec = live_engine.admit_candidate(
            admitted_cand, qual_admitted, require_flat=False
        )

        record(
            "Engine Admission: live_engine.candidates['BTCUSDT'] is now admitted_cand",
            live_engine.candidates["BTCUSDT"].candidate_id == admitted_cand.candidate_id,
            f"engine candidate={live_engine.candidates['BTCUSDT'].candidate_id}",
        )
        record(
            "Immutability Invariant 1: Active trade strictly retains cand_initial candidate artifact",
            live_engine.active_trades["BTCUSDT"].candidate.candidate_id == cand_initial.candidate_id
            and live_engine.active_trades["BTCUSDT"].candidate.artifact_hash
            == cand_initial.artifact_hash,
            f"active trade candidate={live_engine.active_trades['BTCUSDT'].candidate.candidate_id}",
        )

        # Feed 25 bars with rising price -> RSI reaches 100.0 (well above >= 50)
        base_time = NOW
        price = Decimal("50000")
        for i in range(25):
            price += Decimal("50")
            bar_ts = base_time + timedelta(minutes=5 * (i + 1))
            bar = CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=bar_ts - timedelta(minutes=5),
                close_time=bar_ts,
                open=price - Decimal("20"),
                high=price + Decimal("20"),
                low=price - Decimal("30"),
                close=price,
                volume=Decimal("10"),
                quote_volume=Decimal("500000"),
                trades=100,
                taker_buy_base=Decimal("5"),
                taker_buy_quote=Decimal("250000"),
                is_closed=True,
            )
            live_engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=price - Decimal("1"),
                best_bid_qty=Decimal("2"),
                best_ask_price=price,
                best_ask_qty=Decimal("2"),
                transaction_time=bar_ts,
                event_time=bar_ts,
            )
            live_engine._process_closed_bar(bar)
            if "BTCUSDT" not in live_engine.active_trades:
                break

        record(
            "Immutability Invariant 2: Candidate A exit triggers and trade is closed using Candidate A rules",
            "BTCUSDT" not in live_engine.active_trades,
            f"active_trades count={len(live_engine.active_trades)}",
        )

        # Verify the closed trade event was written to SQLite with Candidate A's ID and artifact hash
        conn = sqlite3.connect(td / "paper-ledger.sqlite3")
        cur = conn.cursor()
        cur.execute(
            "SELECT candidate_id, candidate_artifact_hash FROM paper_ledger_events WHERE event = 'close' ORDER BY sequence DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()

        record(
            "Immutability Invariant 3: Closed trade event in SQLite ledger attributes strictly to Candidate A",
            row is not None
            and row[0] == cand_initial.candidate_id
            and row[1] == cand_initial.artifact_hash,
            f"ledger row={row}",
        )

        # -------------------------------------------------------------------------
        # PART 4: Engine Restart Recovery with Admitted Candidate & Open Trade
        # -------------------------------------------------------------------------
        print("\n--- PART 4: Engine Restart Recovery with Admitted Candidate & Open Trade ---")
        # Open a new trade for cand_initial in a second engine setup
        (td / "rec_sub").mkdir(parents=True, exist_ok=True)
        engine_rec = setup_engine(td / "rec_sub", cand_initial)
        rec_open = engine_rec.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        assert rec_open and rec_open.status == "opened"

        # Admit candidate B into engine_rec
        engine_rec.admit_candidate(admitted_cand, qual_admitted, require_flat=False)

        # Now simulate process termination and restart:
        # Create a new LivePaperEngine initialized ONLY with admitted_cand (Candidate B)
        restarted_engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": admitted_cand},
            ledger_db=td / "rec_sub" / "paper-ledger.sqlite3",
            lifecycle_db=td / "rec_sub" / "paper-lifecycle.sqlite3",
            observations_db=td / "rec_sub" / "paper-observations.sqlite3",
            starting_capital=Decimal("10000.00"),
        )

        record(
            "Restart Recovery: Restarted engine recognizes Candidate B as active candidate",
            restarted_engine.candidates["BTCUSDT"].candidate_id == admitted_cand.candidate_id,
            f"candidates={restarted_engine.candidates['BTCUSDT'].candidate_id}",
        )
        record(
            "Restart Recovery: Restored open trade has candidate reconstructed as Candidate A",
            "BTCUSDT" in restarted_engine.active_trades
            and restarted_engine.active_trades["BTCUSDT"].candidate.candidate_id
            == cand_initial.candidate_id
            and restarted_engine.active_trades["BTCUSDT"].candidate.artifact_hash
            == cand_initial.artifact_hash,
            f"restored candidate={restarted_engine.active_trades['BTCUSDT'].candidate.candidate_id}",
        )

    print("\n" + "=" * 80)
    print(
        f"EMPIRICAL CHALLENGER 2 SUMMARY: {passed_count} PASSED, {failed_count} FAILED out of {passed_count + failed_count} assertions"
    )
    print("=" * 80)

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
