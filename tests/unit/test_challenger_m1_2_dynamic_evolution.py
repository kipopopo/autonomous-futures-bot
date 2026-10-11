"""Empirical Challenger Test Suite for Milestone M1 / Phase 315.

Challenger instance: teamwork_preview_challenger (challenger_m1_2)
Mission: Empirically challenge Milestone M1:
1. Multithreaded concurrent queries against load_verified_canary_auto_evolution().
2. SQLite telemetry resilience when sqlite database is empty, corrupted, or missing.
3. Continuous double-entry solvency zero-drift balance invariant (|drift| < 1e-15 USDT).
4. Stage transitions, timing precision, OOS qualification hurdle logic, and macro gating.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryAutoEvolutionResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    load_verified_canary_auto_evolution,
)

UPSTREAM_PHASE305_ROOT = "0cbf6a93a5332789d5053f72e7e494b03b48ccd0ff7c62118bb339d5d905aa7c"


def _rehash_summary(summary: dict[str, Any]) -> None:
    payload = {
        "phase": summary["phase"],
        "upstream_hash": summary["upstream_hash"],
        "perf": summary["performance"],
        "solvency": summary["solvency"],
        "verified": summary["verified"],
        "paper_safe": summary["paper_safe"],
        "execution_authority": summary["execution_authority"],
        "circuit_state": summary["circuit_state"],
        "candidates": summary["candidates"],
        "autopsies_trace": summary["autopsies_trace"],
        "health_evaluations": summary["health_evaluations"],
        "mutations_trace": summary["mutations_trace"],
        "shadow_evaluations": summary["shadow_evaluations"],
    }
    summary["phase_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    hashes = summary["artifact_hashes"]
    merkle_combined = ":".join(
        (
            summary["upstream_hash"],
            hashes["sqlite3"],
            hashes["events_jsonl"],
            summary["phase_hash"],
        )
    )
    summary["merkle_root"] = hashlib.sha256(merkle_combined.encode("utf-8")).hexdigest()


def _build_test_artifacts(
    target_dir: Path,
    autopsy_count: int = 1,
    drift: float = 0.0,
    starting_equity: float = 100.0,
    cash_balance: float = 100.02,
    realized_pnl: float = 0.02,
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    db_path = target_dir / "canary-evolution-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE autopsies (
                trade_id TEXT PRIMARY KEY,
                candidate_id TEXT,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                fill_qty REAL,
                entry_timing_error_bps REAL,
                hawkes_slip_drag_bps REAL,
                adverse_selection_bps REAL,
                realized_edge_bps REAL,
                gross_pnl_usdt REAL,
                fee_cost_usdt REAL,
                net_pnl_usdt REAL,
                cause TEXT,
                timestamp_ms INTEGER
            )
            """
        )
        for i in range(autopsy_count):
            conn.execute(
                "INSERT INTO autopsies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"tr-btc-{i:03d}",
                    "cand-btcusdt-dcb-002",
                    "BTCUSDT",
                    "BUY",
                    95000.0,
                    95250.0,
                    0.0001,
                    1.05,
                    2.98,
                    1.0,
                    20.19,
                    0.025,
                    0.005,
                    0.02,
                    "ORGANIC_ALPHA",
                    1710000000000 + i * 1000,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    events_path = target_dir / "canary-evolution-events.jsonl"
    with open(events_path, "w", encoding="utf-8") as f:
        for i in range(autopsy_count):
            f.write(
                json.dumps(
                    {
                        "event": "TRADE_AUTOPSY",
                        "data": {
                            "trade_id": f"tr-btc-{i:03d}",
                            "candidate_id": "cand-btcusdt-dcb-002",
                            "symbol": "BTCUSDT",
                            "side": "BUY",
                            "entry_price": 95000.0,
                            "exit_price": 95250.0,
                            "fill_qty": 0.0001,
                            "entry_timing_error_bps": 1.05,
                            "hawkes_slip_drag_bps": 2.98,
                            "adverse_selection_bps": 1.0,
                            "realized_edge_bps": 20.19,
                            "gross_pnl_usdt": 0.025,
                            "fee_cost_usdt": 0.005,
                            "net_pnl_usdt": 0.02,
                            "cause": "ORGANIC_ALPHA",
                            "timestamp_ms": 1710000000000 + i * 1000,
                        },
                    }
                )
                + "\n"
            )

    sqlite_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    events_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()

    solvency_dict = {
        "starting_equity_usdt": starting_equity,
        "cash_balance_usdt": cash_balance,
        "allocated_margin_usdt": 0.0,
        "unrealized_pnl_usdt": 0.0,
        "realized_pnl_usdt": realized_pnl,
        "total_equity_usdt": starting_equity + realized_pnl,
        "reserve_ratio": 1.0,
        "reserve_adequate": True,
        "drift_usdt": drift,
        "zero_drift_valid": abs(drift) < 1e-15,
        "exposure_within_limit": True,
    }

    perf_dict = {
        "total_autopsies_conducted": autopsy_count,
        "autopsy_cause_distribution": {"ORGANIC_ALPHA": autopsy_count},
        "mean_entry_timing_error_bps": 1.05,
        "mean_hawkes_slip_drag_bps": 2.98,
        "mean_adverse_selection_bps": 1.0,
        "mean_realized_edge_bps": 20.19,
        "health_tier_distribution": {"ELITE": 1, "HEALTHY": 0, "DEGRADED": 0, "PROBATIONARY": 0},
        "staged_mutations_count": 0,
        "promoted_candidates_count": 0,
    }

    autopsies_trace = [
        {
            "trade_id": f"tr-btc-{i:03d}",
            "candidate_id": "cand-btcusdt-dcb-002",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "entry_price": 95000.0,
            "exit_price": 95250.0,
            "fill_qty": 0.0001,
            "entry_timing_error_bps": 1.05,
            "hawkes_slip_drag_bps": 2.98,
            "adverse_selection_bps": 1.0,
            "realized_edge_bps": 20.19,
            "gross_pnl_usdt": 0.025,
            "fee_cost_usdt": 0.005,
            "net_pnl_usdt": 0.02,
            "cause": "ORGANIC_ALPHA",
            "timestamp_ms": 1710000000000 + i * 1000,
        }
        for i in range(autopsy_count)
    ]

    summary_payload = {
        "phase": "phase_306",
        "status": "EVOLUTION_VERIFIED",
        "verified": True,
        "paper_safe": True,
        "execution_authority": False,
        "timestamp_utc": "2026-09-23T07:00:00+00:00",
        "timestamp_ms": 1790146800000,
        "upstream_merkle_dag": {"phase_305": UPSTREAM_PHASE305_ROOT},
        "upstream_hash": UPSTREAM_PHASE305_ROOT,
        "phase_hash": "",
        "merkle_root": "",
        "artifact_hashes": {
            "sqlite3": sqlite_hash,
            "events_jsonl": events_hash,
        },
        "circuit_state": "NORMAL",
        "performance": perf_dict,
        "solvency": solvency_dict,
        "candidates": ["cand-btcusdt-dcb-002"],
        "autopsies_trace": autopsies_trace,
        "health_evaluations": {
            "cand-btcusdt-dcb-002": {
                "candidate_id": "cand-btcusdt-dcb-002",
                "symbol": "BTCUSDT",
                "tier": "ELITE",
                "rolling_sharpe": 3.85,
                "win_rate_pct": 100.0,
                "max_drawdown_pct": 0.0,
                "hawkes_resilience_score": 90.0,
                "total_trades": autopsy_count,
                "consecutive_losses": 0,
                "needs_mutation": False,
            }
        },
        "mutations_trace": [],
        "shadow_evaluations": [
            {
                "staged_candidate_id": "cand-btcusdt-evo-003",
                "parent_candidate_id": "cand-btcusdt-dcb-002",
                "symbol": "BTCUSDT",
                "shadow_ticks": 20,
                "shadow_sharpe": 2.10,
                "parent_sharpe": 1.50,
                "improvement_pct": 40.0,
                "promoted": True,
                "rejection_reason": None,
            }
        ],
    }
    _rehash_summary(summary_payload)

    summary_path = target_dir / "evolution-summary.json"
    summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    report_path = target_dir / "canary-evolution-report.json"
    report_path.write_text(
        json.dumps(
            {
                "phase": "phase_306",
                "title": "Phase 306 Auto-Evolution Report",
                "merkle_root": summary_payload["merkle_root"],
                "upstream_hash": UPSTREAM_PHASE305_ROOT,
                "summary": summary_payload,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return target_dir


class TestEmpiricalMilestone1Concurrency:
    """Challenge 1: Multithreaded concurrent queries against auto-evolution."""

    def test_concurrent_multithreaded_load_verified_canary_auto_evolution(
        self, tmp_path: Path
    ) -> None:
        """Stress-test load_verified_canary_auto_evolution with 40 concurrent threads."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        num_threads = 40
        num_iterations = 3

        def _worker(thread_idx: int) -> list[CanaryAutoEvolutionResponse]:
            results = []
            for it in range(num_iterations):
                sim_ts = (1728610000 + (thread_idx * 3) + it) * 1000
                res = load_verified_canary_auto_evolution(
                    artifacts_dir,
                    simulated_timestamp_ms=sim_ts,
                )
                assert isinstance(res, CanaryAutoEvolutionResponse)
                assert res.verified is True
                assert res.live_progress.is_live_daemon_active is True
                assert abs(res.solvency.drift_usdt) < 1e-15
                results.append(res)
            return results

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(_worker, i) for i in range(num_threads)]
            all_results = []
            for f in concurrent.futures.as_completed(futures):
                all_results.extend(f.result())

        assert len(all_results) == num_threads * num_iterations
        # Verify diversity of dynamic stages observed across threads
        observed_stages = {r.live_progress.current_cycle_stage for r in all_results}
        assert len(observed_stages) >= 4, f"Observed stages across threads: {observed_stages}"

    def test_concurrent_multithreaded_fastapi_endpoint(self, tmp_path: Path) -> None:
        """Stress-test GET /api/v1/canary/evolution via concurrent TestClient calls."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        app = create_app(canary_phase_dir=artifacts_dir)
        client = TestClient(app)

        errors: list[str] = []
        status_codes: list[int] = []
        lock = threading.Lock()

        def _call_api() -> None:
            try:
                resp = client.get("/api/v1/canary/evolution")
                with lock:
                    status_codes.append(resp.status_code)
                    if resp.status_code != 200:
                        errors.append(f"HTTP {resp.status_code}: {resp.text}")
                    else:
                        data = resp.json()
                        assert "live_progress" in data
                        assert data["live_progress"]["daemon_status"] == "ONLINE 24/7"
            except Exception as ex:
                with lock:
                    errors.append(str(ex))

        threads = [threading.Thread(target=_call_api) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Encountered concurrent API errors: {errors}"
        assert len(status_codes) == 30
        assert all(sc == 200 for sc in status_codes)


class TestEmpiricalMilestone1SQLiteResilience:
    """Challenge 2: SQLite telemetry resilience when sqlite db is empty or corrupt."""

    def test_sqlite_resilience_missing_lifecycle_database(self, tmp_path: Path) -> None:
        """Verify behavior when canary-lifecycle-telemetry.sqlite3 is missing."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        # Ensure no lifecycle db exists in tmp_path
        lifecycle_db = artifacts_dir / "canary-lifecycle-telemetry.sqlite3"
        assert not lifecycle_db.exists()

        res = load_verified_canary_auto_evolution(artifacts_dir)
        assert res.live_progress.closed_trades_count == 0
        assert res.live_progress.cycle_progress_pct == 80.0
        assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"
        assert res.live_progress.stage_status_label == "WAITING_FOR_SAMPLES (0/5)"
        assert res.live_progress.oos_gate.samples_acquired == 0

    def test_sqlite_resilience_empty_zero_byte_database(self, tmp_path: Path) -> None:
        """Verify behavior when canary-lifecycle-telemetry.sqlite3 is 0 bytes (corrupt header)."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        lifecycle_db = artifacts_dir / "canary-lifecycle-telemetry.sqlite3"
        lifecycle_db.write_bytes(b"")  # 0-byte file

        # Must not raise sqlite3.DatabaseError; should catch and fallback gracefully
        res = load_verified_canary_auto_evolution(artifacts_dir)
        assert res.live_progress.closed_trades_count == 0
        assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"

    def test_sqlite_resilience_corrupted_garbage_bytes(self, tmp_path: Path) -> None:
        """Verify behavior when canary-lifecycle-telemetry.sqlite3 is filled with garbage bytes."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        lifecycle_db = artifacts_dir / "canary-lifecycle-telemetry.sqlite3"
        lifecycle_db.write_bytes(b"INVALID_SQLITE_GARBAGE_PAYLOAD\x00\xff\xfe\x01\x02")

        res = load_verified_canary_auto_evolution(artifacts_dir)
        assert res.live_progress.closed_trades_count == 0
        assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"

    def test_sqlite_resilience_table_exists_but_empty(self, tmp_path: Path) -> None:
        """Verify behavior when trade_autopsies table exists but contains 0 rows."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        lifecycle_db = artifacts_dir / "canary-lifecycle-telemetry.sqlite3"
        conn = sqlite3.connect(lifecycle_db)
        try:
            conn.execute("CREATE TABLE trade_autopsies (trade_id TEXT PRIMARY KEY, symbol TEXT)")
            conn.commit()
        finally:
            conn.close()

        res = load_verified_canary_auto_evolution(artifacts_dir)
        assert res.live_progress.closed_trades_count == 0
        assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"
        assert res.live_progress.cycle_progress_pct == 80.0

    def test_sqlite_resilience_unexpected_table_schema(self, tmp_path: Path) -> None:
        """Verify behavior when SQLite has unrelated tables only."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        lifecycle_db = artifacts_dir / "canary-lifecycle-telemetry.sqlite3"
        conn = sqlite3.connect(lifecycle_db)
        try:
            conn.execute("CREATE TABLE other_table (id INT PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO other_table VALUES (1, 'foo')")
            conn.commit()
        finally:
            conn.close()

        res = load_verified_canary_auto_evolution(artifacts_dir)
        assert res.live_progress.closed_trades_count == 0
        assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"

    def test_required_phase306_sqlite_artifact_missing_fails_closed(self, tmp_path: Path) -> None:
        """Verify missing phase 306 sqlite telemetry strictly fails closed."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        sqlite_file = artifacts_dir / "canary-evolution-telemetry.sqlite3"
        sqlite_file.unlink()

        with pytest.raises(CanaryEvidenceNotFoundError, match="Required Phase 306 evidence"):
            load_verified_canary_auto_evolution(artifacts_dir)


class TestEmpiricalMilestone1SolvencyZeroDriftInvariant:
    """Challenge 3: Double-entry balance zero-drift invariant (|drift| < 1e-15 USDT)."""

    def test_solvency_conservation_across_all_dynamic_evolution_stages(
        self, tmp_path: Path
    ) -> None:
        """Verify double-entry balance conservation across all 15 discrete second slices."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        base_sec = 1728610000

        for sec in range(15):
            sim_ts = (base_sec + sec) * 1000
            res = load_verified_canary_auto_evolution(
                artifacts_dir,
                simulated_timestamp_ms=sim_ts,
            )

            # Check solvency item
            solvency = res.solvency
            assert solvency.zero_balance_drift_verified is True
            assert abs(solvency.drift_usdt) < 1e-15

            # Mathematical double-entry verification:
            # Cash + Allocated Margin == Starting Equity + Realized PnL
            cash = Decimal(str(solvency.cash_usdt))
            margin = Decimal(str(solvency.allocated_margin_usdt))
            starting = Decimal(str(solvency.starting_equity_usdt))
            realized = Decimal(str(solvency.realized_pnl_usdt))
            drift = abs(cash + margin - starting - realized)
            assert drift < Decimal("1e-15"), f"Drift {drift} exceeded 1e-15 at sec {sec}"

            # Check ledger item
            ledger = res.ledger
            assert ledger.zero_balance_drift is True
            assert abs(ledger.drift) < 1e-15

    def test_solvency_conservation_across_sample_progressions(self, tmp_path: Path) -> None:
        """Verify double-entry balance conservation across sample counts 0..20."""
        artifacts_dir = _build_test_artifacts(tmp_path)

        for trade_sample in [0, 1, 2, 3, 4, 5, 8, 12, 20]:
            res = load_verified_canary_auto_evolution(
                artifacts_dir,
                simulated_closed_trades=trade_sample,
            )
            assert abs(res.solvency.drift_usdt) < 1e-15
            assert res.solvency.zero_balance_drift_verified is True
            assert res.ledger.zero_balance_drift is True

    def test_solvency_oracle_detects_adversarial_drift(self, tmp_path: Path) -> None:
        """Verify that if drift breaches 1e-15, auto-evolution strictly rejects."""
        # Create artifacts with non-zero drift breaching 1e-15
        artifacts_dir = tmp_path / "drift_tampered"
        _build_test_artifacts(
            artifacts_dir,
            drift=1e-14,  # breaches 1e-15
            starting_equity=100.0,
            cash_balance=100.02,
            realized_pnl=0.02,
        )

        with pytest.raises(
            CanaryEvidenceIntegrityError, match="Double-entry zero-drift balance invariant breached"
        ):
            load_verified_canary_auto_evolution(artifacts_dir)

    def test_solvency_oracle_detects_equity_component_discrepancy(self, tmp_path: Path) -> None:
        """Verify that if cash + margin does not reconcile with starting + realized, it rejects."""
        artifacts_dir = tmp_path / "reconciliation_tampered"
        _build_test_artifacts(
            artifacts_dir,
            drift=0.0,
            starting_equity=100.0,
            cash_balance=95.0,  # missing 5 USDT
            realized_pnl=0.0,
        )

        with pytest.raises(
            CanaryEvidenceIntegrityError, match="solvency components disagree with declared values"
        ):
            load_verified_canary_auto_evolution(artifacts_dir)


class TestEmpiricalMilestone1DynamicEvolutionLogic:
    """Challenge 4: Stage transitions, timing precision, OOS gate, and macro gating."""

    def test_cycle_stage_precision_boundaries(self, tmp_path: Path) -> None:
        """Verify boundary timestamps for all 5 stages within the 15-second cycle."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        base = 1500000000

        # Boundary checks (exact seconds)
        stages_by_sec = {
            0: "INGRESS",
            1: "INGRESS",
            2: "INGRESS",
            3: "HEALTH_EVALUATION",
            4: "HEALTH_EVALUATION",
            5: "HEALTH_EVALUATION",
            6: "TRADE_AUTOPSY",
            7: "TRADE_AUTOPSY",
            8: "TRADE_AUTOPSY",
            9: "MUTATION_STAGING",
            10: "MUTATION_STAGING",
            11: "MUTATION_STAGING",
            12: "SHADOW_OOS_GATE",
            13: "SHADOW_OOS_GATE",
            14: "SHADOW_OOS_GATE",
        }

        for sec, expected_stage in stages_by_sec.items():
            res = load_verified_canary_auto_evolution(
                artifacts_dir,
                simulated_timestamp_ms=(base + sec) * 1000,
            )
            act_stage = res.live_progress.current_cycle_stage
            assert act_stage == expected_stage, f"Failed at {sec}: {expected_stage} != {act_stage}"
            expected_countdown = 15 - sec if sec > 0 else 15
            assert res.live_progress.next_cycle_seconds == expected_countdown

    def test_oos_gate_transition_matrix(self, tmp_path: Path) -> None:
        """Verify full matrix of sample count and Sharpe improvement."""
        artifacts_dir = _build_test_artifacts(tmp_path)

        # 1. trades < 5: always WAITING_FOR_SAMPLES regardless of shadow evaluations
        for t in range(5):
            res = load_verified_canary_auto_evolution(
                artifacts_dir,
                simulated_closed_trades=t,
            )
            assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"
            assert res.live_progress.cycle_progress_pct == 80.0 + (t / 5.0 * 20.0)

        # 2. trades == 5 with fixture's 40.0% improvement (>= 15.0% hurdle): QUALIFIED
        res_qual = load_verified_canary_auto_evolution(
            artifacts_dir,
            simulated_closed_trades=5,
        )
        assert res_qual.live_progress.stage_status == "QUALIFIED"
        assert res_qual.live_progress.cycle_progress_pct == 100.0

    def test_macro_gating_adversarial_regime_fuzzing(self, tmp_path: Path) -> None:
        """Verify behavior with various adversarial and unexpected macro regime inputs."""
        artifacts_dir = _build_test_artifacts(tmp_path)

        cases = [
            ("BEARISH_DOWNTREND", "BEARISH", True, False),
            ("MEGA_BULLISH", "BULLISH_ALIGNED", False, True),
            ("SIDEWAYS_CHOP", "NEUTRAL", True, False),
            ("RANDOM_STRING", "NEUTRAL", True, False),
            ("", "NEUTRAL", True, False),
        ]

        for input_regime, expected_regime, expected_filtered, expected_allowed in cases:
            res = load_verified_canary_auto_evolution(
                artifacts_dir,
                simulated_macro_regime=input_regime,
            )
            mg = res.live_progress.macro_gating_state
            assert mg.regime == expected_regime, f"Failed for {input_regime}"
            assert mg.longs_filtered is expected_filtered
            assert mg.is_long_allowed is expected_allowed
            assert len(mg.explanation_ms) > 10
            assert len(mg.explanation) > 10

    def test_live_progress_json_serialization_roundtrip(self, tmp_path: Path) -> None:
        """Verify model_dump and JSON serialization roundtrip without NaN or Infinity."""
        artifacts_dir = _build_test_artifacts(tmp_path)
        res = load_verified_canary_auto_evolution(artifacts_dir)

        json_str = res.model_dump_json()
        assert "NaN" not in json_str
        assert "Infinity" not in json_str

        # Roundtrip parse
        data = json.loads(json_str)
        assert data["live_progress"]["daemon_pid"] == 87549
        assert data["solvency"]["zero_balance_drift_verified"] is True
        assert len(data["live_progress"]["scanned_symbols"]) == 8
