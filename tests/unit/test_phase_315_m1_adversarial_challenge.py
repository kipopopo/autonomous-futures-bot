"""Adversarial Empirical Challenge for Phase 315 Milestone M1.

Empirical verification of:
1. Dynamic cycle progression across 1,000 boundary & fractional timestamps.
2. Trade sample count boundary behavior (0, 1, 4, 5, 6, 100) and strict [80.0, 100.0]% bounds.
3. Macro gating regimes under simulated Bearish, Bullish, and Neutral market conditions.
4. Cryptographic SHA-256 Merkle DAG hash integrity & immutability under mutation.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from autonomous_futures.api.canary import (
    CanaryEvidenceIntegrityError,
    _build_macro_gating_state,
    load_verified_canary_auto_evolution,
)

CYCLE_STAGES = [
    "INGRESS",
    "HEALTH_EVALUATION",
    "TRADE_AUTOPSY",
    "MUTATION_STAGING",
    "SHADOW_OOS_GATE",
]

EXPECTED_PHASE305_UPSTREAM_HASH = "0cbf6a93a5332789d5053f72e7e494b03b48ccd0ff7c62118bb339d5d905aa7c"
EXPECTED_PHASE306_PAYLOAD_HASH = "521bcb2f8bf0f35c8bb838419ba233bcbe72eeba6652b9710622675907511fd5"
EXPECTED_PHASE306_MERKLE_ROOT = "818fd82458a8fb19420dd0179c8f78b0c273e5d2a71b1968b083d20f99e23dbe"


# ==============================================================================
# 1. DYNAMIC CYCLE PROGRESSION STRESS HARNESS (1,000 TIMESTAMPS)
# ==============================================================================


class TestDynamicCycleProgression1000Probes:
    """Empirical probe verifying dynamic 15s cycle progression across 1,000 timestamps."""

    @pytest.mark.parametrize(
        ("ts_ms", "expected_stage", "expected_next_sec", "expected_sec_in_cycle"),
        [
            (0, "INGRESS", 15, 0),
            (2999, "INGRESS", 13, 2),
            (3000, "HEALTH_EVALUATION", 12, 3),
            (5999, "HEALTH_EVALUATION", 10, 5),
            (6000, "TRADE_AUTOPSY", 9, 6),
            (8999, "TRADE_AUTOPSY", 7, 8),
            (9000, "MUTATION_STAGING", 6, 9),
            (11999, "MUTATION_STAGING", 4, 11),
            (12000, "SHADOW_OOS_GATE", 3, 12),
            (14999, "SHADOW_OOS_GATE", 1, 14),
            (15000, "INGRESS", 15, 0),
            (15001, "INGRESS", 15, 0),
            (16000, "INGRESS", 14, 1),
            (17999, "INGRESS", 13, 2),
            (18000, "HEALTH_EVALUATION", 12, 3),
            (29999, "SHADOW_OOS_GATE", 1, 14),
            (30000, "INGRESS", 15, 0),
            (1_000_000_000_000, "MUTATION_STAGING", 5, 10),  # 1e12 ms (1e9 s % 15 = 10)
            (1_000_000_000_000_000, "MUTATION_STAGING", 5, 10),  # 1e15 ms (1e12 s % 15 = 10)
        ],
    )
    def test_exact_cycle_boundary_timestamps(
        self,
        ts_ms: int,
        expected_stage: str,
        expected_next_sec: int,
        expected_sec_in_cycle: int,
    ) -> None:
        """Probe exact sub-second, second, and cross-cycle transitions."""
        res = load_verified_canary_auto_evolution(simulated_timestamp_ms=ts_ms)
        prog = res.live_progress

        sec_in_cycle = (ts_ms // 1000) % 15
        assert sec_in_cycle == expected_sec_in_cycle
        assert prog.current_cycle_stage == expected_stage
        assert prog.next_cycle_seconds == expected_next_sec
        assert 1 <= prog.next_cycle_seconds <= 15
        assert prog.last_evaluated_timestamp_ms == ts_ms
        assert prog.last_candle_fetch_timestamp_ms == ts_ms - (sec_in_cycle * 1000)
        assert prog.last_candle_fetch_timestamp_ms <= ts_ms
        assert ts_ms - prog.last_candle_fetch_timestamp_ms < 15000

    def test_thousand_randomized_fractional_timestamps_probe(self) -> None:
        """Stress-test 1,000 arbitrary float & fractional timestamps across epochs."""
        rng = random.Random(315_001)

        # Generate 1,000 diverse timestamps: microsecond fractions, large epochs, boundaries
        sample_timestamps: list[float] = []

        # 1. Fine-grained stepping around every boundary of a 15-second cycle
        for sec in range(16):
            for offset_ms in [-1.5, -0.1, 0.0, 0.1, 1.0, 499.5, 999.0, 999.9]:
                sample_timestamps.append(sec * 1000.0 + offset_ms)

        # 2. Add random fractional samples across small, medium, and astronomical epoch ranges
        for _ in range(1000 - len(sample_timestamps)):
            tier = rng.choice(["small", "medium", "large", "future"])
            if tier == "small":
                val = rng.uniform(0.0, 120.0) * 1000.0
            elif tier == "medium":
                val = rng.uniform(10_000.0, 500_000.0) * 1000.0
            elif tier == "large":
                val = rng.uniform(1_700_000_000.0, 1_800_000_000.0) * 1000.0
            else:
                val = rng.uniform(1e12, 1e14)
            sample_timestamps.append(val)

        assert len(sample_timestamps) == 1000

        # Execute all 1,000 probes and assert mathematical invariants
        for raw_ts in sample_timestamps:
            now_epoch_ms = int(raw_ts)
            res = load_verified_canary_auto_evolution(simulated_timestamp_ms=now_epoch_ms)
            prog = res.live_progress

            sec_in_cycle = (now_epoch_ms // 1000) % 15
            expected_stage_idx = min(4, sec_in_cycle // 3)
            expected_stage = CYCLE_STAGES[expected_stage_idx]
            expected_next_sec = 15 - sec_in_cycle if sec_in_cycle > 0 else 15
            expected_last_candle_ts = now_epoch_ms - (sec_in_cycle * 1000)

            # Invariant 1: Cycle stage correctness
            assert prog.current_cycle_stage == expected_stage
            assert prog.current_cycle_stage in CYCLE_STAGES

            # Invariant 2: Countdown bounded strictly in [1, 15]
            assert prog.next_cycle_seconds == expected_next_sec
            assert 1 <= prog.next_cycle_seconds <= 15

            # Invariant 3: Candle fetch timestamp never in future, anchored to cycle boundary
            assert prog.last_candle_fetch_timestamp_ms == expected_last_candle_ts
            assert prog.last_candle_fetch_timestamp_ms <= now_epoch_ms
            assert (now_epoch_ms - prog.last_candle_fetch_timestamp_ms) == (sec_in_cycle * 1000)
            assert (now_epoch_ms - prog.last_candle_fetch_timestamp_ms) < 15000

            # Invariant 4: Monotonic daemon PID & status
            assert prog.daemon_pid == 87549
            assert prog.daemon_status == "ONLINE 24/7"
            assert prog.is_live_daemon_active is True

    def test_ordered_monotonic_stage_progression_across_full_cycle(self) -> None:
        """Verify sequential execution visits every single stage in strictly ascending order."""
        stages_observed: list[str] = []
        for sec in range(15):
            ts = sec * 1000 + 500  # midpoint of each second
            res = load_verified_canary_auto_evolution(simulated_timestamp_ms=ts)
            stages_observed.append(res.live_progress.current_cycle_stage)

        assert stages_observed == [
            "INGRESS",
            "INGRESS",
            "INGRESS",
            "HEALTH_EVALUATION",
            "HEALTH_EVALUATION",
            "HEALTH_EVALUATION",
            "TRADE_AUTOPSY",
            "TRADE_AUTOPSY",
            "TRADE_AUTOPSY",
            "MUTATION_STAGING",
            "MUTATION_STAGING",
            "MUTATION_STAGING",
            "SHADOW_OOS_GATE",
            "SHADOW_OOS_GATE",
            "SHADOW_OOS_GATE",
        ]


# ==============================================================================
# 2. SAMPLE COUNT BOUNDARY & OOS GATE STRESS HARNESS
# ==============================================================================


class TestSampleCountBoundariesAndOOSGate:
    """Empirical probe verifying sample counts 0, 1, 4, 5, 6, 100 and [80.0, 100.0]% bounds."""

    @pytest.mark.parametrize(
        ("trades_count", "expected_pct", "expected_status", "expected_status_label"),
        [
            (0, 80.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (0/5)"),
            (1, 84.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (1/5)"),
            (2, 88.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (2/5)"),
            (3, 92.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (3/5)"),
            (4, 96.0, "WAITING_FOR_SAMPLES", "WAITING_FOR_SAMPLES (4/5)"),
            (5, 100.0, "QUALIFIED", "QUALIFIED (5/5)"),
            (6, 100.0, "QUALIFIED", "QUALIFIED (6/5)"),
            (10, 100.0, "QUALIFIED", "QUALIFIED (10/5)"),
            (100, 100.0, "QUALIFIED", "QUALIFIED (100/5)"),
            (1000, 100.0, "QUALIFIED", "QUALIFIED (1000/5)"),
        ],
    )
    def test_sample_count_boundary_progress_and_status(
        self,
        trades_count: int,
        expected_pct: float,
        expected_status: str,
        expected_status_label: str,
    ) -> None:
        """Verify progress percentage is strictly bounded and labels format correctly."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=trades_count)
        prog = res.live_progress

        assert prog.closed_trades_count == trades_count
        assert prog.required_trades_count == 5
        assert prog.cycle_progress_pct == expected_pct
        assert 80.0 <= prog.cycle_progress_pct <= 100.0
        assert prog.stage_status == expected_status
        assert prog.stage_status_label == expected_status_label

        # OOS gate item synchronization
        assert prog.oos_gate.samples_acquired == trades_count
        assert prog.oos_gate.samples_required == 5
        assert prog.oos_gate.status == expected_status
        assert prog.oos_gate.status_label == expected_status_label

    def test_monotonic_progress_growth_across_sample_ladder(self) -> None:
        """Verify progress percentage is monotonic and non-decreasing from 0 to 100 trades."""
        previous_pct = 0.0
        for count in range(0, 101):
            res = load_verified_canary_auto_evolution(simulated_closed_trades=count)
            pct = res.live_progress.cycle_progress_pct

            assert 80.0 <= pct <= 100.0
            assert pct >= previous_pct
            previous_pct = pct

    def test_oos_gate_sharpe_hurdle_boundary_transition(self, tmp_path: Path) -> None:
        """Verify OOS gate transitions to EVALUATING if Sharpe < 15%, and QUALIFIED if >= 15%."""
        # Setup temporary artifact with controlled shadow evaluation improvement
        summary_path = tmp_path / "evolution-summary.json"
        report_path = tmp_path / "canary-evolution-report.json"
        sqlite_path = tmp_path / "canary-evolution-telemetry.sqlite3"
        events_path = tmp_path / "canary-evolution-events.jsonl"

        # Copy authentic db and events from phase306
        src_p306 = Path("artifacts/research/phase306")
        sqlite_path.write_bytes((src_p306 / "canary-evolution-telemetry.sqlite3").read_bytes())
        events_path.write_bytes((src_p306 / "canary-evolution-events.jsonl").read_bytes())
        report_path.write_bytes((src_p306 / "canary-evolution-report.json").read_bytes())

        base_summary = json.loads((src_p306 / "evolution-summary.json").read_text(encoding="utf-8"))

        def run_with_shadow_improvement(improvement: float) -> str:
            mod_summary = dict(base_summary)
            mod_summary["shadow_evaluations"] = [
                {
                    "staged_candidate_id": "cand-ethusdt-evo-002",
                    "parent_candidate_id": "cand-ethusdt-dcb-003",
                    "symbol": "ETHUSDT",
                    "shadow_ticks": 20,
                    "shadow_sharpe": 2.1,
                    "parent_sharpe": -5.0,
                    "improvement_pct": improvement,
                    "promoted": improvement >= 15.0,
                    "rejection_reason": None,
                }
            ]
            # Recompute payload hash and Merkle root
            payload = {
                "phase": mod_summary["phase"],
                "upstream_hash": mod_summary["upstream_hash"],
                "perf": mod_summary["performance"],
                "solvency": mod_summary["solvency"],
                "verified": mod_summary["verified"],
                "paper_safe": mod_summary["paper_safe"],
                "execution_authority": mod_summary["execution_authority"],
                "circuit_state": mod_summary["circuit_state"],
                "candidates": mod_summary["candidates"],
                "autopsies_trace": mod_summary["autopsies_trace"],
                "health_evaluations": mod_summary["health_evaluations"],
                "mutations_trace": mod_summary["mutations_trace"],
                "shadow_evaluations": mod_summary["shadow_evaluations"],
            }
            mod_summary["phase_hash"] = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            merkle_combined = ":".join(
                (
                    mod_summary["upstream_hash"],
                    mod_summary["artifact_hashes"]["sqlite3"],
                    mod_summary["artifact_hashes"]["events_jsonl"],
                    mod_summary["phase_hash"],
                )
            )
            mod_summary["merkle_root"] = hashlib.sha256(merkle_combined.encode("utf-8")).hexdigest()
            summary_path.write_text(json.dumps(mod_summary, indent=2), encoding="utf-8")

            res = load_verified_canary_auto_evolution(tmp_path, simulated_closed_trades=5)
            return res.live_progress.stage_status

        # Test hurdle boundaries:
        # At 14.99% -> EVALUATING
        assert run_with_shadow_improvement(14.99) == "EVALUATING"
        # At exactly 15.00% -> QUALIFIED
        assert run_with_shadow_improvement(15.00) == "QUALIFIED"
        # At 15.01% -> QUALIFIED
        assert run_with_shadow_improvement(15.01) == "QUALIFIED"
        # At 0.0% -> EVALUATING
        assert run_with_shadow_improvement(0.0) == "EVALUATING"

    def test_scanned_symbols_universe_contains_all_eight_pairs(self) -> None:
        """Verify the dynamic evolution progress reports all 8 high-volume pairs."""
        res = load_verified_canary_auto_evolution()
        symbols = res.live_progress.scanned_symbols
        expected_universe = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "DOGEUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "SUIUSDT",
            "AVAXUSDT",
        ]
        assert symbols == expected_universe
        assert len(symbols) == 8


# ==============================================================================
# 3. MACRO GATING REGIMES STRESS HARNESS
# ==============================================================================


class TestMacroGatingRegimesStress:
    """Empirical probe verifying macro gating states under Bearish, Bullish, and Neutral regimes."""

    @pytest.mark.parametrize(
        ("regime_input", "expected_regime", "expected_filtered", "expected_allowed"),
        [
            ("BEARISH", "BEARISH", True, False),
            ("bearish", "BEARISH", True, False),
            ("BTC_BEARISH_DOWN", "BEARISH", True, False),
            ("BULLISH", "BULLISH_ALIGNED", False, True),
            ("bullish", "BULLISH_ALIGNED", False, True),
            ("BULLISH_ALIGNED", "BULLISH_ALIGNED", False, True),
            ("NEUTRAL", "NEUTRAL", True, False),
            ("neutral", "NEUTRAL", True, False),
            ("SIDEWAYS", "NEUTRAL", True, False),
            ("CHOP_REGIME", "NEUTRAL", True, False),
            ("", "NEUTRAL", True, False),
            ("UNRECOGNIZED_VOLATILE", "NEUTRAL", True, False),
        ],
    )
    def test_macro_gating_regimes_case_and_fallback(
        self,
        regime_input: str,
        expected_regime: str,
        expected_filtered: bool,
        expected_allowed: bool,
    ) -> None:
        """Verify robust parsing, normalization, and fail-closed default for unknown regimes."""
        res = load_verified_canary_auto_evolution(simulated_macro_regime=regime_input)
        gating = res.live_progress.macro_gating_state

        assert gating.regime == expected_regime
        assert gating.longs_filtered is expected_filtered
        assert gating.is_long_allowed is expected_allowed

        # Multilingual explanations sanity check
        if expected_regime == "BEARISH":
            assert "Penapis Aliran Makro BTC Aktif" in gating.explanation_ms
            assert "Bearish" in gating.explanation_ms
            assert "EMA 50 < EMA 200" in gating.explanation_ms
            assert "modal micro-capital" in gating.explanation_ms
            assert "Bearish" in gating.explanation
            assert "EMA 50 < EMA 200" in gating.explanation
        elif expected_regime == "BULLISH_ALIGNED":
            assert "Penapis Aliran Makro BTC Aktif" in gating.explanation_ms
            assert "Bullish Aligned" in gating.explanation_ms
            assert "EMA 50 > EMA 200" in gating.explanation_ms
            assert "dibenarkan" in gating.explanation_ms
            assert "Bullish" in gating.explanation
            assert "permitted" in gating.explanation
        else:  # NEUTRAL
            assert (
                "Neutral" in gating.explanation_ms or "transitional" in gating.explanation.lower()
            )
            assert gating.longs_filtered is True

    def test_macro_gating_builder_numerical_precision(self) -> None:
        """Verify price and EMA values are rounded cleanly to 2 decimal places."""
        gating = _build_macro_gating_state(
            regime="BEARISH",
            btc_price=82612.34567,
            ema50=82800.99999,
            ema200=83500.11111,
        )
        assert gating.btc_price == 82612.35
        assert gating.ema50_1h == 82801.00
        assert gating.ema200_1h == 83500.11
        assert gating.regime == "BEARISH"
        assert gating.longs_filtered is True
        assert gating.is_long_allowed is False


# ==============================================================================
# 4. MERKLE DAG HASH INTEGRITY & IMMUTABILITY HARNESS
# ==============================================================================


class TestMerkleDAGHashIntegrityAndImmutability:
    """Empirical probe verifying SHA-256 Merkle DAG hash integrity and tamper resistance."""

    def test_baseline_phase306_hashes_match_expected_constants(self) -> None:
        """Verify baseline Phase 306 summary, payload, and Merkle root match canonical hashes."""
        src_p306 = Path("artifacts/research/phase306")
        summary = json.loads((src_p306 / "evolution-summary.json").read_text(encoding="utf-8"))

        upstream_hash = str(summary.get("upstream_hash", ""))
        phase_hash = str(summary.get("phase_hash", ""))
        merkle_root = str(summary.get("merkle_root", ""))

        assert upstream_hash == EXPECTED_PHASE305_UPSTREAM_HASH
        assert phase_hash == EXPECTED_PHASE306_PAYLOAD_HASH
        assert merkle_root == EXPECTED_PHASE306_MERKLE_ROOT

    def test_mutating_live_progress_does_not_affect_merkle_dag(self) -> None:
        """Verify modifying live_progress fields has zero effect on Phase 306 Merkle DAG."""
        res = load_verified_canary_auto_evolution()

        # Adversarially mutate live_progress attributes in memory
        res.live_progress.cycle_progress_pct = 0.0
        res.live_progress.current_cycle_stage = "CORRUPTED_STAGE"
        res.live_progress.closed_trades_count = 9999
        res.live_progress.stage_status = "MALICIOUS"
        res.live_progress.macro_gating_state.regime = "COMPROMISED"
        res.live_progress.macro_gating_state.longs_filtered = False

        # Reload verified artifact fresh from disk and assert DAG verification passes unaltered
        fresh_res = load_verified_canary_auto_evolution()
        assert fresh_res.verified is True
        assert fresh_res.phase == "phase_306"
        assert fresh_res.status == "SIMULATION_ARTIFACT_VERIFIED"
        assert fresh_res.solvency.zero_balance_drift_verified is True
        assert fresh_res.solvency.drift_usdt == 0.0

    def test_tamper_summary_phase_hash_raises_integrity_error(self, tmp_path: Path) -> None:
        """Verify tampering with summary phase_hash raises CanaryEvidenceIntegrityError."""
        src_p306 = Path("artifacts/research/phase306")
        (tmp_path / "canary-evolution-telemetry.sqlite3").write_bytes(
            (src_p306 / "canary-evolution-telemetry.sqlite3").read_bytes()
        )
        (tmp_path / "canary-evolution-events.jsonl").write_bytes(
            (src_p306 / "canary-evolution-events.jsonl").read_bytes()
        )
        (tmp_path / "canary-evolution-report.json").write_bytes(
            (src_p306 / "canary-evolution-report.json").read_bytes()
        )

        tampered_summary = json.loads(
            (src_p306 / "evolution-summary.json").read_text(encoding="utf-8")
        )
        # Corrupt the payload hash
        tampered_summary["phase_hash"] = "deadbeef" * 8
        (tmp_path / "evolution-summary.json").write_text(
            json.dumps(tampered_summary, indent=2), encoding="utf-8"
        )

        with pytest.raises(CanaryEvidenceIntegrityError, match="Phase 306 payload hash mismatch"):
            load_verified_canary_auto_evolution(tmp_path)

    def test_tamper_solvency_drift_raises_integrity_error(self, tmp_path: Path) -> None:
        """Verify injecting even 1e-14 solvency drift raises CanaryEvidenceIntegrityError."""
        src_p306 = Path("artifacts/research/phase306")
        (tmp_path / "canary-evolution-telemetry.sqlite3").write_bytes(
            (src_p306 / "canary-evolution-telemetry.sqlite3").read_bytes()
        )
        (tmp_path / "canary-evolution-events.jsonl").write_bytes(
            (src_p306 / "canary-evolution-events.jsonl").read_bytes()
        )
        (tmp_path / "canary-evolution-report.json").write_bytes(
            (src_p306 / "canary-evolution-report.json").read_bytes()
        )

        tampered_summary = json.loads(
            (src_p306 / "evolution-summary.json").read_text(encoding="utf-8")
        )
        tampered_summary["solvency"]["drift_usdt"] = 0.00000000000001  # 1e-14
        tampered_summary["solvency"]["zero_drift_valid"] = False

        # Rehash so it passes payload hash check and hits solvency invariant check
        payload = {
            "phase": tampered_summary["phase"],
            "upstream_hash": tampered_summary["upstream_hash"],
            "perf": tampered_summary["performance"],
            "solvency": tampered_summary["solvency"],
            "verified": tampered_summary["verified"],
            "paper_safe": tampered_summary["paper_safe"],
            "execution_authority": tampered_summary["execution_authority"],
            "circuit_state": tampered_summary["circuit_state"],
            "candidates": tampered_summary["candidates"],
            "autopsies_trace": tampered_summary["autopsies_trace"],
            "health_evaluations": tampered_summary["health_evaluations"],
            "mutations_trace": tampered_summary["mutations_trace"],
            "shadow_evaluations": tampered_summary["shadow_evaluations"],
        }
        tampered_summary["phase_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        merkle_combined = ":".join(
            (
                tampered_summary["upstream_hash"],
                tampered_summary["artifact_hashes"]["sqlite3"],
                tampered_summary["artifact_hashes"]["events_jsonl"],
                tampered_summary["phase_hash"],
            )
        )
        tampered_summary["merkle_root"] = hashlib.sha256(
            merkle_combined.encode("utf-8")
        ).hexdigest()
        (tmp_path / "evolution-summary.json").write_text(
            json.dumps(tampered_summary, indent=2), encoding="utf-8"
        )

        with pytest.raises(
            CanaryEvidenceIntegrityError,
            match="Double-entry zero-drift balance invariant breached",
        ):
            load_verified_canary_auto_evolution(tmp_path)
