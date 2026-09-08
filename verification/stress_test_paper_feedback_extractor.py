"""Empirical Challenger Stress Harness: Feedback Extractor Idempotency, Determinism & Concurrency.

Executed by teamwork_preview_challenger_m1_2.
Verifies:
1. 100 consecutive extractions determinism (byte-for-byte identical JSON and qualification_hash).
2. Path resolution parity (directory path vs direct paper-ledger.sqlite3 file path).
3. Concurrency safety (PRAGMA busy_timeout = 1000, mode=ro, zero database locks under 50 threads).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src is on Python path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.paper.feedback_extractor import (  # noqa: E402
    PaperFeedbackExtractor,
    PaperQualificationPolicy,
    extract_paper_feedback,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("empirical_challenger")

NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_HASH = "b" * 64

REAL_DB_DIR = Path("artifacts/paper/phase251")
REAL_LEDGER_FILE = Path("artifacts/paper/phase251/paper-ledger.sqlite3")
REAL_CANDIDATE_ID = "cand-a5454657c3fc480b03246904e7674eeabe9f35890ee863c24ce2788e3f5c4c15"
REAL_SYMBOL = "DOGEUSDT"


def build_candidate(
    cand_id: str = "cand-stress-001", symbol: str = "BTCUSDT"
) -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=cand_id,
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
        candidate_id=cand_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_HASH,
        creator_run_id="run-stress-001",
        research_seed=123,
        created_at=NOW,
    )


def create_synthetic_db(storage_dir: Path, num_trades: int = 10, breach: bool = True) -> Path:
    storage_dir.mkdir(parents=True, exist_ok=True)
    db_path = storage_dir / "paper-ledger.sqlite3"
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
    t_start = NOW - timedelta(days=5)
    cand_art = build_candidate()

    for i in range(num_trades):
        trade_id = f"tr-stress-{i:04d}"
        t_open = t_start + timedelta(hours=i * 2)
        t_close = t_open + timedelta(minutes=45)

        if breach:
            entry_p = Decimal("50000.00")
            exit_p = Decimal("48000.00") if i % 2 == 0 else Decimal("49000.00")
            net_pnl = Decimal("-20.00") if i % 2 == 0 else Decimal("-10.00")
            gross_pnl = Decimal("-19.96") if i % 2 == 0 else Decimal("-9.96")
        else:
            entry_p = Decimal("50000.00")
            exit_p = Decimal("52000.00")
            net_pnl = Decimal("20.00")
            gross_pnl = Decimal("20.04")

        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (?, 'open', ?, ?, ?, 'BTCUSDT', 'LONG', '0.01',
             ?, ?, ?, '0.02', NULL, '0.01', NULL, NULL)
            """,
            (
                seq,
                trade_id,
                cand_art.candidate_id,
                cand_art.artifact_hash,
                str(entry_p),
                t_open.isoformat(),
                f"app-o-{seq}",
            ),
        )
        seq += 1

        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (?, 'close', ?, ?, ?, 'BTCUSDT', 'LONG', '0.01', ?, ?, ?, '0.02', '0.02', '0.01', ?, ?)
            """,
            (
                seq,
                trade_id,
                cand_art.candidate_id,
                cand_art.artifact_hash,
                str(exit_p),
                t_close.isoformat(),
                f"app-c-{seq}",
                str(gross_pnl),
                str(net_pnl),
            ),
        )
        seq += 1

    conn.commit()
    conn.close()
    return db_path


def run_test_1_determinism_100_extractions() -> dict[str, Any]:
    logger.info("=== TEST 1: 100 Consecutive Extractions Determinism & Byte Parity ===")

    assert REAL_LEDGER_FILE.is_file(), f"Real DB missing: {REAL_LEDGER_FILE}"

    # 1.1: Real DB with standard policy (returns None 100 consecutive times)
    standard_policy = PaperQualificationPolicy()
    extractor_real = PaperFeedbackExtractor(REAL_DB_DIR, policy=standard_policy)

    results_standard = []
    t0 = time.perf_counter()
    for _ in range(100):
        res = extractor_real.extract(
            symbol=REAL_SYMBOL,
            candidate_id=REAL_CANDIDATE_ID,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
        )
        results_standard.append(res)
    t1 = time.perf_counter()

    assert all(r is None for r in results_standard), (
        "Expected None for all 100 runs under standard policy"
    )
    logger.info(
        "Test 1.1 PASSED: 100/100 runs returned None in %.3fs (avg %.2fms/run)",
        t1 - t0,
        (t1 - t0) * 10,
    )

    # 1.2: Real DB with strict policy (breach -> CreatorQualificationFailureFeedback 100x)
    strict_policy = PaperQualificationPolicy(
        policy_id="strict-policy-stress",
        paper_profit_factor_min=Decimal("200.0"),  # Real DB PF is ~130.02
        paper_win_rate_min=Decimal("45.0"),
        paper_drawdown_max=Decimal("15.0"),
        paper_trades_min=5,
    )
    extractor_strict = PaperFeedbackExtractor(REAL_DB_DIR, policy=strict_policy)

    hashes = []
    jsons = []
    t0 = time.perf_counter()
    for _ in range(100):
        fb = extractor_strict.extract(
            symbol=REAL_SYMBOL,
            candidate_id=REAL_CANDIDATE_ID,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
        )
        assert fb is not None, "Expected failure feedback under strict policy"
        hashes.append(fb.qualification_hash)
        jsons.append(fb.model_dump_json(indent=2))
    t1 = time.perf_counter()

    unique_hashes = set(hashes)
    unique_jsons = set(jsons)

    assert len(unique_hashes) == 1, (
        f"Expected exactly 1 unique qualification_hash, got {len(unique_hashes)}"
    )
    assert len(unique_jsons) == 1, (
        f"Expected exactly 1 unique JSON payload, got {len(unique_jsons)}"
    )
    logger.info(
        "Test 1.2 PASSED: 100/100 breach extractions 100%% byte-identical (hash: %s) in %.3fs",
        hashes[0],
        t1 - t0,
    )

    # 1.3: Synthetic breach DB (100 consecutive extractions)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        create_synthetic_db(tmp_path, num_trades=10, breach=True)
        cand = build_candidate()
        extractor_synth = PaperFeedbackExtractor(tmp_path)

        synth_hashes = []
        synth_jsons = []
        t0 = time.perf_counter()
        for _ in range(100):
            fb = extractor_synth.extract(candidate_artifact=cand)
            assert fb is not None
            synth_hashes.append(fb.qualification_hash)
            synth_jsons.append(fb.model_dump_json(indent=2))
        t1 = time.perf_counter()

        assert len(set(synth_hashes)) == 1, (
            f"Synthetic DB expected 1 unique hash, got {len(set(synth_hashes))}"
        )
        assert len(set(synth_jsons)) == 1, (
            f"Synthetic DB expected 1 unique JSON, got {len(set(synth_jsons))}"
        )
        logger.info(
            "Test 1.3 PASSED: 100/100 synthetic breach extractions 100%% byte-identical in %.3fs",
            t1 - t0,
        )

    return {
        "standard_100_runs_passed": True,
        "strict_100_runs_passed": True,
        "strict_qualification_hash": hashes[0],
        "strict_json_bytes": len(jsons[0].encode("utf-8")),
        "synthetic_100_runs_passed": True,
        "synthetic_qualification_hash": synth_hashes[0],
    }


def run_test_2_path_resolution_parity() -> dict[str, Any]:
    logger.info("=== TEST 2: Path Resolution Parity (Directory vs Direct SQLite File) ===")

    strict_policy = PaperQualificationPolicy(
        policy_id="strict-policy-path-parity",
        paper_net_pnl_min=Decimal("500.0"),  # Real DB is +281.11 -> breaches
        paper_profit_factor_min=Decimal("1.05"),
        paper_win_rate_min=Decimal("45.0"),
        paper_drawdown_max=Decimal("15.0"),
        paper_trades_min=5,
    )

    paths_to_test = [
        ("relative_dir", REAL_DB_DIR),
        ("relative_file", REAL_LEDGER_FILE),
        ("absolute_dir", REAL_DB_DIR.resolve()),
        ("absolute_file", REAL_LEDGER_FILE.resolve()),
        ("string_rel_dir", str(REAL_DB_DIR)),
        ("string_rel_file", str(REAL_LEDGER_FILE)),
        ("string_abs_dir", str(REAL_DB_DIR.resolve())),
        ("string_abs_file", str(REAL_LEDGER_FILE.resolve())),
    ]

    feedbacks = {}
    trades_counts = {}

    for label, p in paths_to_test:
        extractor = PaperFeedbackExtractor(p, policy=strict_policy)
        trades = extractor.get_closed_trades(symbol=REAL_SYMBOL, candidate_id=REAL_CANDIDATE_ID)
        fb = extractor.extract(
            symbol=REAL_SYMBOL,
            candidate_id=REAL_CANDIDATE_ID,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_HASH,
        )
        assert fb is not None, f"Expected breach feedback for path variant {label}"
        feedbacks[label] = fb
        trades_counts[label] = len(trades)

    first_tc = list(trades_counts.values())[0]
    for lbl, tc in trades_counts.items():
        assert tc == first_tc, f"Trade count mismatch for {lbl}: {tc} != {first_tc}"
    logger.info(
        "Verified all %d path variants retrieved identical trade count: %d trades",
        len(paths_to_test),
        first_tc,
    )

    ref_fb = feedbacks["relative_dir"]
    ref_json = ref_fb.model_dump_json(indent=2)
    ref_hash = ref_fb.qualification_hash

    for lbl, fb in feedbacks.items():
        assert fb.qualification_hash == ref_hash, (
            f"Hash mismatch for {lbl}: {fb.qualification_hash} != {ref_hash}"
        )
        assert fb.model_dump_json(indent=2) == ref_json, f"JSON payload mismatch for {lbl}"
        assert len(fb.failed_gates) == len(ref_fb.failed_gates)
        for g_actual, g_ref in zip(fb.failed_gates, ref_fb.failed_gates, strict=True):
            assert g_actual.gate_id == g_ref.gate_id
            assert g_actual.passed == g_ref.passed
            assert g_actual.observed == g_ref.observed
            assert g_actual.threshold == g_ref.threshold
            assert g_actual.reason_code == g_ref.reason_code

    logger.info(
        "Test 2 PASSED: 100%% parity across %d path variants (hash: %s)",
        len(paths_to_test),
        ref_hash,
    )

    return {
        "path_variants_tested": [lbl for lbl, _ in paths_to_test],
        "parity_confirmed": True,
        "qualification_hash": ref_hash,
        "trade_count": first_tc,
    }


def run_test_3_concurrency_and_locks() -> dict[str, Any]:
    logger.info("=== TEST 3: Concurrency Safety & SQLite Lock Stress ===")

    # 3.1: Connection PRAGMAs verification
    extractor = PaperFeedbackExtractor(REAL_DB_DIR)
    conn = extractor.reader._connect_readonly(extractor.ledger_db_path)
    assert conn is not None, "Failed to connect read-only to ledger"

    query_only_val = conn.execute("PRAGMA query_only;").fetchone()[0]
    busy_timeout_val = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    logger.info("Connection PRAGMA query_only: %s (expected 1)", query_only_val)
    logger.info("Connection PRAGMA busy_timeout: %s ms (expected 1000)", busy_timeout_val)
    assert query_only_val == 1, f"PRAGMA query_only expected 1, got {query_only_val}"
    assert busy_timeout_val == 1000, f"PRAGMA busy_timeout expected 1000, got {busy_timeout_val}"

    # Verify write attempt raises OperationalError (readonly database)
    write_failed = False
    try:
        conn.execute("CREATE TABLE test_write_fail (id INT);")
    except sqlite3.OperationalError as exc:
        write_failed = True
        logger.info("Read-only enforcement verified: write failed as expected with: %s", exc)
    finally:
        conn.close()
    assert write_failed, "Write unexpectedly succeeded on read-only connection!"

    # 3.2: 50 Concurrent Reader Threads Stress Test
    strict_policy = PaperQualificationPolicy(
        policy_id="strict-concurrency-test",
        paper_profit_factor_min=Decimal("200.0"),
        paper_win_rate_min=Decimal("45.0"),
        paper_drawdown_max=Decimal("15.0"),
        paper_trades_min=5,
    )

    num_threads = 50
    calls_per_thread = 10
    total_calls = num_threads * calls_per_thread
    logger.info(
        "Launching %d concurrent threads (%d total extractions)...", num_threads, total_calls
    )

    lock_errors: list[Exception] = []
    hashes_collected: list[str] = []
    lock = threading.Lock()

    def worker_reader(thread_id: int) -> None:
        try:
            thread_extractor = PaperFeedbackExtractor(REAL_DB_DIR, policy=strict_policy)
            for _ in range(calls_per_thread):
                fb = thread_extractor.extract(
                    symbol=REAL_SYMBOL,
                    candidate_id=REAL_CANDIDATE_ID,
                    bundle_hash=BUNDLE_HASH,
                    dataset_registry_hash=DATASET_HASH,
                )
                assert fb is not None
                with lock:
                    hashes_collected.append(fb.qualification_hash)
        except Exception as exc:
            with lock:
                lock_errors.append(exc)
            logger.error("Thread %d failed with: %s", thread_id, exc)

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker_reader, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    t1 = time.perf_counter()

    assert len(lock_errors) == 0, (
        f"Encountered {len(lock_errors)} errors during concurrent reads: {lock_errors}"
    )
    assert len(hashes_collected) == total_calls, (
        f"Expected {total_calls} hashes, got {len(hashes_collected)}"
    )
    assert len(set(hashes_collected)) == 1, (
        f"Hashes deviated across threads: {set(hashes_collected)}"
    )
    logger.info(
        "Test 3.2 PASSED: %d concurrent extractions in %.3fs without locks (%.1f ops/sec)",
        total_calls,
        t1 - t0,
        total_calls / (t1 - t0),
    )

    # 3.3: Concurrent Reads During Active SQLite Writer Transactions
    logger.info("Testing concurrent reads during active background database transactions...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = create_synthetic_db(tmp_path, num_trades=20, breach=True)
        cand = build_candidate()

        stop_writer = threading.Event()
        writer_errors: list[Exception] = []
        writes_completed = [0]

        def background_writer():
            w_conn = sqlite3.connect(db_path, timeout=5.0)
            seq = 1000
            try:
                while not stop_writer.is_set():
                    w_conn.execute(
                        "INSERT INTO paper_position_state VALUES (?, 1, ?)",
                        (f"tr-state-{seq}", json.dumps({"status": "active", "seq": seq})),
                    )
                    w_conn.commit()
                    seq += 1
                    writes_completed[0] += 1
                    time.sleep(0.005)
            except Exception as exc:
                writer_errors.append(exc)
            finally:
                w_conn.close()

        writer_thread = threading.Thread(target=background_writer)
        writer_thread.start()

        reader_errors: list[Exception] = []
        reader_hashes: list[str] = []

        def active_concurrent_reader(rid: int):
            try:
                for _ in range(25):
                    fb = extract_paper_feedback(
                        ledger_path=tmp_path,
                        candidate_artifact=cand,
                    )
                    assert fb is not None
                    with lock:
                        reader_hashes.append(fb.qualification_hash)
                    time.sleep(0.002)
            except Exception as exc:
                with lock:
                    reader_errors.append(exc)

        reader_threads = [
            threading.Thread(target=active_concurrent_reader, args=(i,)) for i in range(20)
        ]
        for rt in reader_threads:
            rt.start()
        for rt in reader_threads:
            rt.join()

        stop_writer.set()
        writer_thread.join()

        assert len(writer_errors) == 0, f"Writer thread failed: {writer_errors}"
        assert len(reader_errors) == 0, (
            f"Reader threads threw errors during active writes: {reader_errors}"
        )
        assert len(reader_hashes) == 20 * 25, f"Expected 500 reads, got {len(reader_hashes)}"
        assert len(set(reader_hashes)) == 1, f"Read hashes deviated: {set(reader_hashes)}"
        logger.info(
            "Test 3.3 PASSED: %d reads concurrent with %d commits (zero locks)",
            len(reader_hashes),
            writes_completed[0],
        )

    return {
        "query_only": query_only_val,
        "busy_timeout_ms": busy_timeout_val,
        "readonly_enforcement_passed": write_failed,
        "concurrent_50_threads_total_calls": total_calls,
        "concurrent_throughput_ops_sec": round(total_calls / (t1 - t0), 1),
        "concurrent_reads_during_active_writes_passed": True,
        "active_writer_commits": writes_completed[0],
    }


def main() -> int:
    logger.info("Starting Empirical Stress Harness for Paper Ledger Feedback Extractor...")
    summary = {}
    try:
        summary["test_1_determinism"] = run_test_1_determinism_100_extractions()
        summary["test_2_path_resolution"] = run_test_2_path_resolution_parity()
        summary["test_3_concurrency"] = run_test_3_concurrency_and_locks()
        logger.info("ALL EMPIRICAL CHALLENGES PASSED WITH 100%% COMPLIANCE!")
        print("\n--- SUMMARY JSON ---")
        print(json.dumps(summary, indent=2))
        return 0
    except Exception as exc:
        logger.exception("Empirical stress test failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
