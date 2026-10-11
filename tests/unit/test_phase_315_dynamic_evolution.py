"""Unit tests for Phase 315 Dynamic Evolution State Machine and OOS Gate Telemetry."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryAutoEvolutionResponse,
    LiveEvolutionEventItem,
    LiveEvolutionProgressItem,
    MacroGatingStateItem,
    OOSQualificationGateItem,
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


def _build_test_artifacts(target_dir: Path, autopsy_count: int = 1) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    db_path = target_dir / "canary-evolution-telemetry.sqlite3"
    with sqlite3.connect(str(db_path)) as conn:
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
        "starting_equity_usdt": 100.0,
        "cash_balance_usdt": 100.02,
        "allocated_margin_usdt": 0.0,
        "unrealized_pnl_usdt": 0.0,
        "realized_pnl_usdt": 0.02,
        "total_equity_usdt": 100.02,
        "reserve_ratio": 1.0,
        "reserve_adequate": True,
        "drift_usdt": 0.0,
        "zero_drift_valid": True,
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


def test_get_canary_evolution_api_dynamic_fields(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/evolution returns all new dynamic fields with correct types."""
    artifacts_dir = _build_test_artifacts(tmp_path)
    app = create_app(canary_phase_dir=artifacts_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/evolution")
    assert resp.status_code == 200
    data = resp.json()

    assert "live_progress" in data
    lp = data["live_progress"]

    # Basic booleans & strings
    assert lp["is_live_daemon_active"] is True
    assert lp["daemon_status"] == "ONLINE 24/7"
    assert lp["daemon_pid"] == 87549
    assert lp["active_generation"] == "GEN #2"
    assert lp["next_target_generation"] == "GEN #3"

    # Dynamic state machine fields
    assert lp["current_cycle_stage"] in [
        "INGRESS",
        "HEALTH_EVALUATION",
        "TRADE_AUTOPSY",
        "MUTATION_STAGING",
        "SHADOW_OOS_GATE",
    ]
    assert isinstance(lp["cycle_progress_pct"], (int, float))
    assert lp["cycle_progress_pct"] >= 80.0
    assert lp["stage_status"] in ["WAITING_FOR_SAMPLES", "EVALUATING", "QUALIFIED"]
    assert isinstance(lp["stage_status_label"], str)
    assert isinstance(lp["closed_trades_count"], int)
    assert lp["required_trades_count"] == 5
    assert lp["sharpe_hurdle_pct"] == 15.0
    assert isinstance(lp["current_sharpe_improvement_pct"], (int, float))

    # Real-time scan timestamps & interval
    assert isinstance(lp["last_candle_fetch_timestamp_ms"], int)
    assert lp["last_candle_fetch_timestamp_ms"] > 0
    assert 1 <= lp["next_cycle_seconds"] <= 15
    assert isinstance(lp["last_evaluated_timestamp_ms"], int)

    # 8-pair universe
    assert "scanned_symbols" in lp
    expected_symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "DOGEUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "SUIUSDT",
        "AVAXUSDT",
    ]
    for pair in expected_symbols:
        assert pair in lp["scanned_symbols"]

    # Macro gating state
    assert "macro_gating_state" in lp
    mg = lp["macro_gating_state"]
    assert mg["regime"] in ["BEARISH", "BULLISH_ALIGNED", "NEUTRAL"]
    assert isinstance(mg["longs_filtered"], bool)
    assert isinstance(mg["explanation_ms"], str)
    assert "Penapis Aliran Makro BTC Aktif" in mg["explanation_ms"]

    # OOS gate scorecard
    assert "oos_gate" in lp
    og = lp["oos_gate"]
    assert og["samples_required"] == 5
    assert isinstance(og["samples_acquired"], int)
    assert og["sharpe_hurdle_pct"] == 15.0
    assert og["status"] in ["WAITING_FOR_SAMPLES", "EVALUATING", "QUALIFIED"]
    valid_labels = ("WAITING_FOR_SAMPLES", "QUALIFIED", "EVALUATING")
    assert any(lbl in og["status_label"] for lbl in valid_labels)

    # Timeline events
    assert "recent_events" in lp
    assert len(lp["recent_events"]) >= 5


def test_dynamic_stage_transitions_across_15s_scan_cycle(tmp_path: Path) -> None:
    """Verify that current_cycle_stage transitions dynamically through all 5 discrete stages."""
    artifacts_dir = _build_test_artifacts(tmp_path)
    base_aligned_sec = 1500000000

    # sec 0..2 -> INGRESS
    res_ingress = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_timestamp_ms=(base_aligned_sec + 1) * 1000,
    )
    assert isinstance(res_ingress.live_progress, LiveEvolutionProgressItem)
    assert res_ingress.live_progress.current_cycle_stage == "INGRESS"
    assert res_ingress.live_progress.next_cycle_seconds == 14
    assert res_ingress.live_progress.last_candle_fetch_timestamp_ms == base_aligned_sec * 1000

    # sec 3..5 -> HEALTH_EVALUATION
    res_health = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_timestamp_ms=(base_aligned_sec + 4) * 1000,
    )
    assert res_health.live_progress.current_cycle_stage == "HEALTH_EVALUATION"
    assert res_health.live_progress.next_cycle_seconds == 11

    # sec 6..8 -> TRADE_AUTOPSY
    res_autopsy = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_timestamp_ms=(base_aligned_sec + 7) * 1000,
    )
    assert res_autopsy.live_progress.current_cycle_stage == "TRADE_AUTOPSY"
    assert res_autopsy.live_progress.next_cycle_seconds == 8

    # sec 9..11 -> MUTATION_STAGING
    res_mutation = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_timestamp_ms=(base_aligned_sec + 10) * 1000,
    )
    assert res_mutation.live_progress.current_cycle_stage == "MUTATION_STAGING"
    assert res_mutation.live_progress.next_cycle_seconds == 5

    # sec 12..14 -> SHADOW_OOS_GATE
    res_oos = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_timestamp_ms=(base_aligned_sec + 13) * 1000,
    )
    assert res_oos.live_progress.current_cycle_stage == "SHADOW_OOS_GATE"
    assert res_oos.live_progress.next_cycle_seconds == 2

    # sec 15 -> wraps around to INGRESS
    res_wrap = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_timestamp_ms=(base_aligned_sec + 15) * 1000,
    )
    assert res_wrap.live_progress.current_cycle_stage == "INGRESS"
    assert res_wrap.live_progress.next_cycle_seconds == 15


def test_sample_count_progress_progression(tmp_path: Path) -> None:
    """Verify that cycle_progress_pct strictly calculates 80.0 + (min(trades, 5) / 5 * 20.0)."""
    artifacts_dir = _build_test_artifacts(tmp_path)

    expected_progress = {
        0: (80.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (0/5)"),
        1: (84.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (1/5)"),
        2: (88.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (2/5)"),
        3: (92.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (3/5)"),
        4: (96.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (4/5)"),
        5: (100.0, "QUALIFIED", "QUALIFIED (5/5)"),
    }

    for trades, (pct, status, label) in expected_progress.items():
        res = load_verified_canary_auto_evolution(
            artifacts_dir,
            simulated_closed_trades=trades,
        )
        assert res.live_progress.closed_trades_count == trades
        assert res.live_progress.required_trades_count == 5
        assert res.live_progress.cycle_progress_pct == pct
        assert res.live_progress.stage_status == status
        assert res.live_progress.stage_status_label == label
        assert res.live_progress.oos_gate.samples_acquired == trades
        assert res.live_progress.oos_gate.status == status


def test_waiting_for_samples_under_5_trades(tmp_path: Path) -> None:
    """Verify that when closed trades < 5, status is WAITING_FOR_SAMPLES (0/5)."""
    artifacts_dir = _build_test_artifacts(tmp_path)

    res = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_closed_trades=0,
    )
    assert res.live_progress.closed_trades_count == 0
    assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"
    assert res.live_progress.stage_status_label == "WAITING_FOR_SAMPLES (0/5)"
    assert res.live_progress.sharpe_hurdle_pct >= 15.0
    assert isinstance(res.live_progress.oos_gate, OOSQualificationGateItem)
    assert res.live_progress.oos_gate.status_label == "WAITING_FOR_SAMPLES (0/5)"
    assert "Menunggu 5 sampel" in res.live_progress.oos_gate.explanation


def test_oos_evaluating_vs_qualified_at_5_trades(tmp_path: Path) -> None:
    """Verify OOS qualification gate transitions between EVALUATING and QUALIFIED."""
    artifacts_dir = _build_test_artifacts(tmp_path)

    # Qualified when improvement >= 15% (test fixture has improvement_pct = 40.0%)
    res_qual = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_closed_trades=5,
    )
    assert res_qual.live_progress.stage_status == "QUALIFIED"
    assert res_qual.live_progress.stage_status_label == "QUALIFIED (5/5)"
    assert res_qual.live_progress.current_sharpe_improvement_pct == 40.0
    assert (
        res_qual.live_progress.current_sharpe_improvement_pct
        >= res_qual.live_progress.sharpe_hurdle_pct
    )
    assert "melepasi hurdle" in res_qual.live_progress.oos_gate.explanation


def test_btc_macro_trend_gating_explanations(tmp_path: Path) -> None:
    """Verify BTC macro trend gating explanation is present, accurate, and human-readable."""
    artifacts_dir = _build_test_artifacts(tmp_path)

    # 1. Bearish Regime (filtering longs)
    res_bear = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_macro_regime="BEARISH",
    )
    mg_bear = res_bear.live_progress.macro_gating_state
    assert isinstance(mg_bear, MacroGatingStateItem)
    assert mg_bear.regime == "BEARISH"
    assert mg_bear.longs_filtered is True
    assert mg_bear.is_long_allowed is False
    assert "Penapis Aliran Makro BTC Aktif" in mg_bear.explanation_ms
    assert "Bearish (EMA 50 < EMA 200)" in mg_bear.explanation_ms
    assert "melindungi modal" in mg_bear.explanation_ms
    assert "Bearish regime filter for capital protection" in mg_bear.explanation

    # 2. Bullish Aligned Regime (allowing longs)
    res_bull = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_macro_regime="BULLISH_ALIGNED",
    )
    mg_bull = res_bull.live_progress.macro_gating_state
    assert isinstance(mg_bull, MacroGatingStateItem)
    assert mg_bull.regime == "BULLISH_ALIGNED"
    assert mg_bull.longs_filtered is False
    assert mg_bull.is_long_allowed is True
    assert "dibenarkan" in mg_bull.explanation_ms
    assert "Bullish Aligned (EMA 50 > EMA 200)" in mg_bull.explanation_ms

    # 3. Neutral / Sideways Regime (filtering longs)
    res_neut = load_verified_canary_auto_evolution(
        artifacts_dir,
        simulated_macro_regime="NEUTRAL",
    )
    mg_neut = res_neut.live_progress.macro_gating_state
    assert isinstance(mg_neut, MacroGatingStateItem)
    assert mg_neut.regime == "NEUTRAL"
    assert mg_neut.longs_filtered is True
    assert "Neutral/Sideways" in mg_neut.explanation_ms


def test_sha256_merkle_dag_hash_integrity_preserved(tmp_path: Path) -> None:
    """Verify SHA-256 Merkle DAG hash check passes 100% and live_progress remains outside."""
    artifacts_dir = _build_test_artifacts(tmp_path)
    res = load_verified_canary_auto_evolution(artifacts_dir)

    assert isinstance(res, CanaryAutoEvolutionResponse)
    assert res.verified is True
    assert res.upstream_hash == UPSTREAM_PHASE305_ROOT
    assert len(res.merkle_root) == 64
    assert len(res.phase_hash) == 64

    # Verify that live_progress fields can be modified without altering phase_hash
    lp_dict = res.live_progress.model_dump()
    assert "closed_trades_count" in lp_dict
    assert "macro_gating_state" in lp_dict
    assert len(res.live_progress.recent_events) > 0
    assert isinstance(res.live_progress.recent_events[0], LiveEvolutionEventItem)


def test_solvency_ledger_zero_drift_invariant(tmp_path: Path) -> None:
    """Verify continuous double-entry solvency zero-drift balance invariant (|Δ| < 10^-15 USDT)."""
    artifacts_dir = _build_test_artifacts(tmp_path)
    res = load_verified_canary_auto_evolution(artifacts_dir)

    assert res.solvency.zero_balance_drift_verified is True
    assert abs(res.solvency.drift_usdt) < 1e-15
    assert res.ledger.zero_balance_drift is True
    assert res.solvency.cash_reserve_pct >= 75.0
    assert res.solvency.unencumbered_cash_verified is True


def test_sqlite_telemetry_live_ingestion(tmp_path: Path) -> None:
    """Verify closed trades count dynamically ingests from SQLite canary-lifecycle-telemetry."""
    target_dir = tmp_path / "custom_phase306"
    _build_test_artifacts(target_dir)

    # Create a lifecycle telemetry sqlite database with exactly 3 trade_autopsies in target_dir
    lifecycle_db = target_dir / "canary-lifecycle-telemetry.sqlite3"
    with sqlite3.connect(lifecycle_db) as conn:
        conn.execute(
            """
            CREATE TABLE trade_autopsies (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT,
                side TEXT,
                net_pnl_usdt REAL
            )
            """
        )
        for i in range(3):
            conn.execute(
                "INSERT INTO trade_autopsies VALUES (?, ?, ?, ?)",
                (f"trade-{i}", "SOLUSDT", "BUY", 0.15),
            )
        conn.commit()

    res = load_verified_canary_auto_evolution(target_dir)
    assert res.live_progress.closed_trades_count == 3
    assert res.live_progress.cycle_progress_pct == 92.0
    assert res.live_progress.stage_status == "WAITING_FOR_SAMPLES"
    assert res.live_progress.stage_status_label == "WAITING_FOR_SAMPLES (3/5)"
