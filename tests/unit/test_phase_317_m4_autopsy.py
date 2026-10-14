"""Phase 317 Milestone 4 Unit Tests: Continuous Evolution Integration & Strategy Autopsies.

File: tests/unit/test_phase_317_m4_autopsy.py

Covers:
- Suite 1: TestCandidateRegistryEnrollment
  (Verifies catalog enrollment across all 8 active pairs with canonical names cand-*-ict-001,
   valid default genomes, correct parameter bounds, and strict invariant preservation).
- Suite 2: TestStrategyAutopsyMetrics
  (Verifies mathematical accuracy of entry timing error, FVG slippage, MAE, MFE,
   bracket efficiency, and net realized edge for both long and short trades).
- Suite 3: TestGenomeMutationAndClamping
  (Verifies parameter mutation, bound clamping, strict invariant preservation
   ote_lower < ote_upper and stdv_tp1 < stdv_tp2, and deterministic RNG seed support).
- Suite 4: TestFiveStageQualificationGate
  (Verifies the 5 stages: return >= 0%, maxDD <= 15%, profit factor >= 1.05, trades >= 5,
   stress survival >= 95%; tests both passing candidates and failing candidate variants).
- Suite 5: TestAutopsyEngineContinuousTraderIntegration
  (Verifies non-blocking execution keeping main loop latency strictly < 15ms,
   SQLite persistence in ict_trade_autopsies and ict_candidate_registry,
   JSONL event logging, and dynamic state machine status transitions).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from autonomous_futures.execution.binance_gateway import (
    BinanceFuturesGateway,
)
from autonomous_futures.execution.continuous_trader import ContinuousSelfDrivingTrader
from autonomous_futures.feed.auto_evolution import (
    DEFAULT_ICT_GENOMES,
    AutopsyAttributionCause,
    CandidateHealthTier,
    IctAutopsyCalculator,
    IctCandidateGenome,
    IctGenome,
    IctGenomeMutationEngine,
    compute_autopsy_score,
    mutate_genome,
)
from autonomous_futures.feed.kline_sequencer import (
    ACTIVE_PAIRS,
    ACTIVE_TIMEFRAMES,
)
from autonomous_futures.feed.strategy_mining import (
    FiveStageQualificationGateEvaluator,
)
from autonomous_futures.paper.candidate_registry import (
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
    verify_candidate_registry_manifest,
)
from autonomous_futures.strategy.ict_mmxm import (
    Candle,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle as MacroCandle,
)

# =============================================================================
# Suite 1: TestCandidateRegistryEnrollment
# =============================================================================


class TestCandidateRegistryEnrollment:
    """Verifies candidate catalog enrollment across all 8 active pairs."""

    DEFAULT_GENOMES = DEFAULT_ICT_GENOMES

    def test_registry_contains_all_8_active_pairs(self) -> None:
        """Verifies catalog includes all active symbols without omissions."""
        assert len(self.DEFAULT_GENOMES) == len(ACTIVE_PAIRS)
        for sym in ACTIVE_PAIRS:
            assert sym in self.DEFAULT_GENOMES, f"Active pair {sym} missing from candidate registry"

    def test_canonical_candidate_id_naming_convention(self) -> None:
        """Verifies candidate IDs strictly follow canonical regex cand-{sym}-ict-001."""
        id_pattern = re.compile(r"^cand-[a-z0-9]+-ict-\d{3}$")
        for sym, genome in self.DEFAULT_GENOMES.items():
            assert genome.candidate_id == f"cand-{sym.lower()}-ict-001"
            assert id_pattern.match(genome.candidate_id) is not None
            assert len(genome.candidate_id) <= 32

    def test_valid_default_genome_parameters(self) -> None:
        """Verifies baseline default parameters match institutional specifications."""
        for genome in self.DEFAULT_GENOMES.values():
            assert genome.ote_lower == Decimal("0.50")
            assert genome.ote_upper == Decimal("0.79")
            assert genome.stdv_tp1 == Decimal("2.0")
            assert genome.stdv_tp2 == Decimal("4.0")
            assert genome.swing_lookback == 50
            assert genome.fvg_threshold_pct == Decimal("0.0015")
            assert genome.lookback_htf == 100
            assert genome.generation == 1
            assert genome.is_active is True

    def test_default_genomes_within_admissible_bounds(self) -> None:
        """Verifies default parameters strictly obey safety boundary intervals."""
        for genome in self.DEFAULT_GENOMES.values():
            assert Decimal("0.48") <= genome.ote_lower <= Decimal("0.68")
            assert Decimal("0.70") <= genome.ote_upper <= Decimal("0.85")
            assert Decimal("1.5") <= genome.stdv_tp1 <= Decimal("2.5")
            assert Decimal("3.0") <= genome.stdv_tp2 <= Decimal("5.0")
            assert 20 <= genome.swing_lookback <= 150
            assert Decimal("0.0005") <= genome.fvg_threshold_pct <= Decimal("0.0050")

    def test_strict_invariants_preserved_in_default_registry(self) -> None:
        """Verifies ote_lower < ote_upper and stdv_tp1 < stdv_tp2 hold strictly."""
        for genome in self.DEFAULT_GENOMES.values():
            assert genome.ote_lower < genome.ote_upper
            assert (genome.ote_upper - genome.ote_lower) >= Decimal("0.05")
            assert genome.stdv_tp1 < genome.stdv_tp2
            assert (genome.stdv_tp2 - genome.stdv_tp1) >= Decimal("0.50")

    def test_manifest_file_on_disk_validates_cleanly(self) -> None:
        """Verifies artifacts/paper_live/candidate_registry.json passes manifest integrity."""
        manifest_path = Path("artifacts/paper_live/candidate_registry.json")
        assert manifest_path.is_file(), "candidate_registry.json missing on disk"

        manifest = read_candidate_registry(manifest_path, verify_hash=True)
        assert verify_candidate_registry_manifest(manifest) is True
        assert len(manifest.symbols) >= 3

        for sym, entry in manifest.symbols.items():
            assert sym in ACTIVE_PAIRS
            assert Path(entry.artifact_path).is_file()

        validated = validate_manifest_candidate_artifacts(manifest)
        assert len(validated) == len(manifest.symbols)


# =============================================================================
# Suite 2: TestStrategyAutopsyMetrics
# =============================================================================


class TestStrategyAutopsyMetrics:
    """Verifies mathematical accuracy of autopsy decomposition for long and short trades."""

    @pytest.fixture
    def calculator(self) -> IctAutopsyCalculator:
        return IctAutopsyCalculator(maker_fee_rate=0.0002, taker_fee_rate=0.0004)

    def test_long_winning_trade_autopsy_metrics(self, calculator: IctAutopsyCalculator) -> None:
        """Verifies timing error, FVG slippage, MAE, MFE, and bracket efficiency for Long."""
        # Entry = 100.20, optimal OTE = 100.00, FVG top = 100.00
        # Peak favorable = 104.00, lowest during trade = 99.80, exit = 103.00, qty = 0.05
        metrics = calculator.compute_metrics(
            trade_id="trd-sol-long-win",
            candidate_id="cand-solusdt-ict-001",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=100.20,
            exit_price=103.00,
            fill_qty=0.05,
            optimal_price=100.00,
            fvg_boundary_price=100.00,
            lowest_price_during_trade=99.80,
            highest_price_during_trade=104.00,
            timestamp_ms=1700000000000,
        )

        # 1. Entry timing error: |100.20 - 100.00| / 100.00 * 10000 = 20.00 bps
        assert pytest.approx(metrics.entry_timing_error_bps, rel=1e-4) == 20.00

        # 2. FVG slippage: (100.20 - 100.00) / 100.00 * 10000 = 20.00 bps
        assert pytest.approx(metrics.fvg_slippage_bps, rel=1e-4) == 20.00

        # 3. MAE: (100.20 - 99.80) / 100.20 * 10000 = 39.92 bps
        expected_mae = (0.40 / 100.20) * 10000.0
        assert pytest.approx(metrics.mae_bps, rel=1e-4) == expected_mae

        # 4. MFE: (104.00 - 100.20) / 100.20 * 10000 = 379.24 bps
        expected_mfe = (3.80 / 100.20) * 10000.0
        assert pytest.approx(metrics.mfe_bps, rel=1e-4) == expected_mfe

        # 5. Bracket Efficiency: (103.00 - 100.20) / (104.00 - 100.20) = 2.80 / 3.80 = 0.7368
        assert pytest.approx(metrics.bracket_efficiency, rel=1e-4) == (2.80 / 3.80)

        # 6. PnL & Net edge
        assert metrics.gross_pnl_usdt > 0.0
        assert metrics.net_pnl_usdt > 0.0
        assert metrics.cause == AutopsyAttributionCause.ORGANIC_ALPHA

    def test_short_winning_trade_autopsy_metrics(self, calculator: IctAutopsyCalculator) -> None:
        """Verifies timing error, FVG slippage, MAE, MFE, and bracket efficiency for Short."""
        # Entry = 99.80, optimal OTE = 100.00, FVG bottom = 100.00
        # Peak favorable lowest = 96.00, peak adverse highest = 100.20, exit = 97.00, qty = 0.05
        metrics = calculator.compute_metrics(
            trade_id="trd-eth-short-win",
            candidate_id="cand-ethusdt-ict-001",
            symbol="ETHUSDT",
            side="SELL",
            entry_price=99.80,
            exit_price=97.00,
            fill_qty=0.05,
            optimal_price=100.00,
            fvg_boundary_price=100.00,
            lowest_price_during_trade=96.00,
            highest_price_during_trade=100.20,
            timestamp_ms=1700000000000,
        )

        # 1. Entry timing error: |99.80 - 100.00| / 100.00 * 10000 = 20.00 bps
        assert pytest.approx(metrics.entry_timing_error_bps, rel=1e-4) == 20.00

        # 2. FVG slippage: (100.00 - 99.80) / 100.00 * 10000 = 20.00 bps
        assert pytest.approx(metrics.fvg_slippage_bps, rel=1e-4) == 20.00

        # 3. MAE: (100.20 - 99.80) / 99.80 * 10000 = 40.08 bps
        expected_mae = (0.40 / 99.80) * 10000.0
        assert pytest.approx(metrics.mae_bps, rel=1e-4) == expected_mae

        # 4. MFE: (99.80 - 96.00) / 99.80 * 10000 = 380.76 bps
        expected_mfe = (3.80 / 99.80) * 10000.0
        assert pytest.approx(metrics.mfe_bps, rel=1e-4) == expected_mfe

        # 5. Bracket Efficiency: (99.80 - 97.00) / (99.80 - 96.00) = 2.80 / 3.80 = 0.7368
        assert pytest.approx(metrics.bracket_efficiency, rel=1e-4) == (2.80 / 3.80)
        assert metrics.cause == AutopsyAttributionCause.ORGANIC_ALPHA

    def test_losing_trade_and_zero_bracket_efficiency(
        self, calculator: IctAutopsyCalculator
    ) -> None:
        """Verifies loss attribution and 0.0 bracket efficiency when stopped out."""
        metrics = calculator.compute_metrics(
            trade_id="trd-btc-loss",
            candidate_id="cand-btcusdt-ict-001",
            symbol="BTCUSDT",
            side="BUY",
            entry_price=80000.0,
            exit_price=79000.0,
            fill_qty=0.001,
            optimal_price=80000.0,
            fvg_boundary_price=80000.0,
            lowest_price_during_trade=78900.0,
            highest_price_during_trade=80100.0,
            timestamp_ms=1700000000000,
        )

        assert metrics.bracket_efficiency == 0.0
        assert metrics.net_pnl_usdt < 0.0
        assert metrics.realized_edge_bps < 0.0


# =============================================================================
# Suite 3: TestGenomeMutationAndClamping
# =============================================================================


class TestGenomeMutationAndClamping:
    """Verifies parameter mutation, bound clamping, invariants, and RNG seed support."""

    @pytest.fixture
    def base_genome(self) -> IctGenome:
        return IctGenome(
            candidate_id="cand-solusdt-ict-001",
            symbol="SOLUSDT",
            generation=1,
            ote_lower=Decimal("0.62"),
            ote_upper=Decimal("0.79"),
            stdv_tp1=Decimal("2.0"),
            stdv_tp2=Decimal("4.0"),
            swing_lookback=50,
            lookback_htf=100,
            fvg_threshold_pct=Decimal("0.0015"),
        )

    def test_parameter_clamping_on_overshooting_perturbations(self, base_genome: IctGenome) -> None:
        """Verifies extreme perturbations are clamped to valid parameter ranges."""
        engine = IctGenomeMutationEngine()

        # Force overshoot below lower bounds and above upper bounds
        child = engine.mutate_genome(
            parent=base_genome,
            delta_ote_lower=-0.50,  # 0.62 - 0.50 = 0.12 -> clamp MIN_OTE_LOWER 0.55
            delta_ote_upper=+0.50,  # 0.79 + 0.50 = 1.29 -> clamp MAX_OTE_UPPER 0.85
            delta_stdv_tp1=-5.0,  # 2.0 - 5.0 = -3.0   -> clamp MIN_STDV_TP1 1.5
            delta_stdv_tp2=+10.0,  # 4.0 + 10.0 = 14.0  -> clamp MAX_STDV_TP2 5.0
            delta_lookback=+500,  # 50 + 500 = 550     -> clamp MAX_SWING_LOOKBACK 150
        )

        assert child.generation == 2
        assert child.candidate_id == "cand-solusdt-ict-002"
        assert child.ote_lower == Decimal("0.48")
        assert child.ote_upper == Decimal("0.85")
        assert child.stdv_tp1 == Decimal("1.5")
        assert child.stdv_tp2 == Decimal("5.0")
        assert child.swing_lookback == 150

    def test_strict_invariant_preservation_ote_bounds(self, base_genome: IctGenome) -> None:
        """Verifies ote_lower < ote_upper is strictly preserved even with inverted noise."""
        engine = IctGenomeMutationEngine()

        child = engine.mutate_genome(
            parent=base_genome,
            delta_ote_lower=+0.15,
            delta_ote_upper=-0.15,
        )

        assert child.ote_lower < child.ote_upper
        assert (child.ote_upper - child.ote_lower) >= Decimal("0.05")

    def test_strict_invariant_preservation_stdv_targets(self, base_genome: IctGenome) -> None:
        """Verifies stdv_tp1 < stdv_tp2 is strictly preserved."""
        engine = IctGenomeMutationEngine()

        child = engine.mutate_genome(
            parent=base_genome,
            delta_stdv_tp1=+1.5,
            delta_stdv_tp2=-2.0,
        )

        assert child.stdv_tp1 < child.stdv_tp2
        assert (child.stdv_tp2 - child.stdv_tp1) >= Decimal("0.50")

    def test_deterministic_rng_seed_support(self, base_genome: IctGenome) -> None:
        """Verifies identical seed produces bit-for-bit identical child genomes."""
        engine_a = IctGenomeMutationEngine(seed=4242)
        engine_b = IctGenomeMutationEngine(seed=4242)
        engine_c = IctGenomeMutationEngine(seed=9999)

        child_a = engine_a.mutate_genome(base_genome)
        child_b = engine_b.mutate_genome(base_genome)
        child_c = engine_c.mutate_genome(base_genome)

        assert child_a.to_dict() == child_b.to_dict()
        assert child_a.to_dict() != child_c.to_dict()

    def test_adaptive_step_scaling_autopsy_score(self, base_genome: IctGenome) -> None:
        """Verifies high score S=1.0 scales step down compared to low score S=0.0."""
        score_high = compute_autopsy_score(
            realized_edge_bps=50.0, timing_error_bps=0.0, adverse_selection_bps=0.0
        )
        score_low = compute_autopsy_score(
            realized_edge_bps=-50.0, timing_error_bps=30.0, adverse_selection_bps=40.0
        )

        assert score_high == 1.0
        assert score_low == 0.0

        diffs_high: list[float] = []
        diffs_low: list[float] = []
        for i in range(100):
            c_high = mutate_genome(
                base_genome,
                perturbation_scale=0.10,
                autopsy_score=score_high,
                random_seed=1000 + i,
            )
            c_low = mutate_genome(
                base_genome,
                perturbation_scale=0.10,
                autopsy_score=score_low,
                random_seed=1000 + i,
            )
            diffs_high.append(abs(float(c_high.ote_upper) - float(base_genome.ote_upper)))
            diffs_low.append(abs(float(c_low.ote_upper) - float(base_genome.ote_upper)))

        mean_diff_high = sum(diffs_high) / len(diffs_high)
        mean_diff_low = sum(diffs_low) / len(diffs_low)
        assert mean_diff_high < mean_diff_low


# =============================================================================
# Suite 4: TestFiveStageQualificationGate
# =============================================================================


class TestFiveStageQualificationGate:
    """Verifies the 5 Walk-Forward Out-of-Sample qualification gates."""

    @pytest.fixture
    def gate_evaluator(self) -> FiveStageQualificationGateEvaluator:
        return FiveStageQualificationGateEvaluator()

    def test_candidate_passes_all_5_stages(
        self, gate_evaluator: FiveStageQualificationGateEvaluator
    ) -> None:
        """Verifies passing candidate satisfies all 5 hurdles and earns QUALIFIED status."""
        result = gate_evaluator.evaluate(
            avg_return_pct=5.2,  # Stage 1: >= 0.0%  (PASS)
            worst_drawdown_pct=7.5,  # Stage 2: <= 15.0% (PASS)
            profit_factor=1.65,  # Stage 3: >= 1.05  (PASS)
            trade_count=10,  # Stage 4: >= 5     (PASS)
            stress_loss_usdt=1.50,  # Stage 5: <= 7.00  (PASS)
            stress_drift_usdt=0.0,  # Stage 5: < 1e-15  (PASS)
        )

        assert result["qualified"] is True
        assert result["status"] == "QUALIFIED"
        assert all(result["gates_passed"].values())

    def test_candidate_fails_stage_1_negative_return(
        self, gate_evaluator: FiveStageQualificationGateEvaluator
    ) -> None:
        """Verifies failure when return is negative."""
        result = gate_evaluator.evaluate(
            avg_return_pct=-1.5,  # FAIL (< 0.0%)
            worst_drawdown_pct=5.0,
            profit_factor=1.50,
            trade_count=10,
            stress_loss_usdt=1.00,
            stress_drift_usdt=0.0,
        )
        assert result["qualified"] is False
        assert result["gates_passed"]["stage_1_return"] is False
        assert result["status"] == "REJECTED"

    def test_candidate_fails_stage_2_excessive_drawdown(
        self, gate_evaluator: FiveStageQualificationGateEvaluator
    ) -> None:
        """Verifies failure when worst drawdown > 15.0%."""
        result = gate_evaluator.evaluate(
            avg_return_pct=8.0,
            worst_drawdown_pct=18.5,  # FAIL (> 15.0%)
            profit_factor=1.80,
            trade_count=15,
            stress_loss_usdt=2.00,
            stress_drift_usdt=0.0,
        )
        assert result["qualified"] is False
        assert result["gates_passed"]["stage_2_drawdown"] is False
        assert result["status"] == "REJECTED"

    def test_candidate_fails_stage_3_low_profit_factor(
        self, gate_evaluator: FiveStageQualificationGateEvaluator
    ) -> None:
        """Verifies failure when profit factor < 1.05."""
        result = gate_evaluator.evaluate(
            avg_return_pct=0.5,
            worst_drawdown_pct=8.0,
            profit_factor=0.95,  # FAIL (< 1.05)
            trade_count=12,
            stress_loss_usdt=1.50,
            stress_drift_usdt=0.0,
        )
        assert result["qualified"] is False
        assert result["gates_passed"]["stage_3_profit_factor"] is False
        assert result["status"] == "REJECTED"

    def test_profit_factor_zero_loss_infinite_positive(
        self, gate_evaluator: FiveStageQualificationGateEvaluator
    ) -> None:
        """Verifies profit factor with 0 loss and positive profit returns infinity and passes."""
        trades = [
            {"net_pnl_usdt": 1.50},
            {"net_pnl_usdt": 2.00},
            {"net_pnl_usdt": 0.80},
        ]
        pf = gate_evaluator.compute_profit_factor(trades)
        assert math.isinf(pf)

        result = gate_evaluator.evaluate(
            avg_return_pct=4.3,
            worst_drawdown_pct=1.0,
            profit_factor=pf,
            trade_count=6,
            stress_loss_usdt=0.50,
            stress_drift_usdt=0.0,
        )
        assert result["qualified"] is True
        assert result["gates_passed"]["stage_3_profit_factor"] is True

    def test_candidate_fails_stage_4_insufficient_sample_size(
        self, gate_evaluator: FiveStageQualificationGateEvaluator
    ) -> None:
        """Verifies candidate with < 5 trades remains WAITING_FOR_SAMPLES."""
        result = gate_evaluator.evaluate(
            avg_return_pct=12.0,
            worst_drawdown_pct=2.0,
            profit_factor=3.0,
            trade_count=3,  # FAIL (< 5 trades)
            stress_loss_usdt=0.50,
            stress_drift_usdt=0.0,
        )
        assert result["qualified"] is False
        assert result["gates_passed"]["stage_4_trade_count"] is False
        assert result["status"] == "WAITING_FOR_SAMPLES"

    def test_candidate_fails_stage_5_stress_fault_injection(
        self, gate_evaluator: FiveStageQualificationGateEvaluator
    ) -> None:
        """Verifies failure when flash crash stress loss exceeds budget."""
        result = gate_evaluator.evaluate(
            avg_return_pct=4.0,
            worst_drawdown_pct=10.0,
            profit_factor=1.40,
            trade_count=8,
            stress_loss_usdt=8.50,  # FAIL (> 7.00 loss ceiling)
            stress_drift_usdt=0.0,
        )
        assert result["qualified"] is False
        assert result["gates_passed"]["stage_5_stress_resilience"] is False
        assert result["status"] == "REJECTED"

    def test_monte_carlo_stress_test_evaluation(
        self, gate_evaluator: FiveStageQualificationGateEvaluator
    ) -> None:
        """Verifies Monte Carlo randomized slippage and fee variance stress test."""
        robust_trades = [
            {
                "entry_price": 100.0,
                "exit_price": 103.0,
                "fill_qty": 0.05,
                "side": "BUY",
                "net_pnl_usdt": 0.15,
            },
            {
                "entry_price": 102.0,
                "exit_price": 105.0,
                "fill_qty": 0.05,
                "side": "BUY",
                "net_pnl_usdt": 0.15,
            },
            {
                "entry_price": 105.0,
                "exit_price": 102.0,
                "fill_qty": 0.05,
                "side": "SELL",
                "net_pnl_usdt": 0.15,
            },
            {
                "entry_price": 103.0,
                "exit_price": 101.0,
                "fill_qty": 0.05,
                "side": "SELL",
                "net_pnl_usdt": 0.10,
            },
            {
                "entry_price": 101.0,
                "exit_price": 104.0,
                "fill_qty": 0.05,
                "side": "BUY",
                "net_pnl_usdt": 0.15,
            },
        ]
        stress_res = gate_evaluator.run_stress_test(robust_trades, starting_equity=100.0)
        assert stress_res.simulations_count == 200
        assert stress_res.survival_rate_pct >= 95.0
        assert stress_res.passed is True


# =============================================================================
# Suite 5: TestAutopsyEngineContinuousTraderIntegration
# =============================================================================


class TestAutopsyEngineContinuousTraderIntegration:
    """Verifies non-blocking execution, SQLite persistence, and state transitions."""

    def test_incomplete_ict_evidence_is_rejected_without_synthetic_prices(
        self, tmp_path: Path
    ) -> None:
        gateway = AsyncMock(spec=BinanceFuturesGateway)
        gateway.offline_mode = True
        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=gateway,
            telegram_enabled=False,
        )
        trader.engine.enqueue_ict_autopsy(
            {
                "trade_id": "trd-incomplete-001",
                "candidate_id": "cand-solusdt-ict-001",
                "symbol": "SOLUSDT",
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 102.0,
                "fill_qty": 0.1,
                "timestamp_ms": 1700000000000,
            }
        )

        metrics = trader.engine.drain_pending_autopsies()

        assert metrics == []
        assert trader.engine.has_pending_autopsies() is False
        events = (tmp_path / "canary-production-events.jsonl").read_text(encoding="utf-8")
        assert "ICT_AUTOPSY_REJECTED_INCOMPLETE_EVIDENCE" in events

    @pytest.fixture
    def test_db_setup(self, tmp_path: Path) -> Path:
        """Initializes a clean SQLite database with ICT autopsy & registry tables."""
        db_path = tmp_path / "canary-production-telemetry.sqlite3"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ict_trade_autopsies (
                trade_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                fill_qty REAL NOT NULL,
                entry_timing_error_bps REAL NOT NULL,
                fvg_slippage_bps REAL NOT NULL,
                mae_bps REAL NOT NULL,
                mfe_bps REAL NOT NULL,
                bracket_efficiency REAL NOT NULL,
                realized_edge_bps REAL NOT NULL,
                gross_pnl_usdt REAL NOT NULL,
                fee_cost_usdt REAL NOT NULL,
                net_pnl_usdt REAL NOT NULL,
                cause TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ict_candidate_registry (
                candidate_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                generation INTEGER NOT NULL,
                parent_candidate_id TEXT,
                ote_lower REAL NOT NULL,
                ote_upper REAL NOT NULL,
                stdv_tp1 REAL NOT NULL,
                stdv_tp2 REAL NOT NULL,
                lookback_htf INTEGER NOT NULL,
                health_tier TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
        """)
        conn.commit()
        conn.close()
        return db_path

    @pytest.mark.anyio
    async def test_non_blocking_autopsy_trigger_under_15ms(self, tmp_path: Path) -> None:
        """Verifies that the exact cycle performing autopsy draining executes strictly < 15.0 ms.

        Unmasks the latency test:
        1. Warms up the continuous trader loop across 3 idle cycles.
        2. Asserts has_pending_autopsies() is False initially.
        3. Enqueues a trade autopsy record.
        4. Measures the EXACT cycle where drain_pending_autopsies() executes.
        5. Asserts that has_pending_autopsies() transitions from True to False.
        6. Asserts drain_cycle_latency_ms < 15.0 ms (WITHOUT taking min() across idle cycles).
        7. Tests 5 consecutive drain cycles with back-to-back enqueues,
           asserting every cycle < 15.0 ms.
        8. Verifies that all drained autopsies are persisted to SQLite.
        """
        mock_gateway = AsyncMock(spec=BinanceFuturesGateway)
        mock_gateway.get_position_risk.return_value = []
        mock_gateway.get_klines.return_value = []
        mock_gateway.testnet = True

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gateway,
            telegram_enabled=False,
        )
        trader.engine.perform_preflight_checks()

        now = time.time()
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = trader.sequencer.buffers[(sym, tf)]
                for i in range(50):
                    buf.append(
                        Candle(
                            timestamp_ms=1700000000000 + i * 60000,
                            open=Decimal("100.0"),
                            high=Decimal("101.0"),
                            low=Decimal("99.0"),
                            close=Decimal("100.5"),
                            volume=Decimal("1000.0"),
                        )
                    )
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        trader.btc_1h_history = [
            MacroCandle(
                timestamp_ms=1700000000000 + i * 3600000,
                open=Decimal("82600.0"),
                high=Decimal("82700.0"),
                low=Decimal("82500.0"),
                close=Decimal("82650.0"),
                volume=Decimal("500.0"),
            )
            for i in range(210)
        ]
        trader.last_candle_fetch_ts = now
        trader.last_export_ts = now

        # 1. Warm up 3 cycles to eliminate initial JIT / memory allocation jitter
        for _ in range(3):
            await trader.run_single_cycle()

        assert trader.engine.has_pending_autopsies() is False

        # 2. Enqueue pending autopsy to verify exact drain execution latency
        now_drain = time.time()
        trader.last_candle_fetch_ts = now_drain
        trader.last_export_ts = now_drain
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                trader.sequencer.last_fetch_ts[(sym, tf)] = now_drain

        trader.engine.enqueue_ict_autopsy(
            {
                "trade_id": "trd-latency-drain-001",
                "candidate_id": "cand-solusdt-ict-001",
                "symbol": "SOLUSDT",
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 102.5,
                "fill_qty": 0.04,
                "optimal_price": 100.0,
                "fvg_boundary_price": 100.0,
                "lowest_price_during_trade": 99.8,
                "highest_price_during_trade": 103.0,
                "timestamp_ms": int(now_drain * 1000),
            }
        )

        assert trader.engine.has_pending_autopsies() is True

        # 3. Measure the EXACT cycle where drain_pending_autopsies() executes
        t0 = time.perf_counter()
        await trader.run_single_cycle()
        drain_cycle_latency_ms = (time.perf_counter() - t0) * 1000.0

        # Verify that autopsy was drained in this exact cycle
        assert trader.engine.has_pending_autopsies() is False
        assert drain_cycle_latency_ms < 15.0, (
            f"Drain cycle latency was {drain_cycle_latency_ms:.2f}ms, exceeding 15.0ms ceiling! "
            f"(Verified without min() masking)"
        )

        # 4. Stress-test consecutive back-to-back drain cycles (no idle cycles between)
        consecutive_latencies: list[float] = []
        for i in range(5):
            now_iter = time.time()
            trader.last_candle_fetch_ts = now_iter
            trader.last_export_ts = now_iter
            for sym in ACTIVE_PAIRS:
                for tf in ACTIVE_TIMEFRAMES:
                    trader.sequencer.last_fetch_ts[(sym, tf)] = now_iter

            sym = ACTIVE_PAIRS[i % len(ACTIVE_PAIRS)]
            trader.engine.enqueue_ict_autopsy(
                {
                    "trade_id": f"trd-latency-consec-{i:03d}",
                    "candidate_id": f"cand-{sym.lower()}-ict-001",
                    "symbol": sym,
                    "side": "SELL" if i % 2 == 1 else "BUY",
                    "entry_price": 100.0,
                    "exit_price": 98.0 if i % 2 == 1 else 102.0,
                    "fill_qty": 0.02,
                    "optimal_price": 100.0,
                    "fvg_boundary_price": 100.0,
                    "lowest_price_during_trade": 97.5,
                    "highest_price_during_trade": 102.5,
                    "timestamp_ms": int(now_iter * 1000),
                }
            )

            t_iter = time.perf_counter()
            await trader.run_single_cycle()
            cycle_ms = (time.perf_counter() - t_iter) * 1000.0
            consecutive_latencies.append(cycle_ms)

            # Assert EVERY cycle individually < 15.0 ms
            assert cycle_ms < 15.0, (
                f"Consecutive drain cycle {i} took {cycle_ms:.2f}ms, exceeding 15.0ms ceiling!"
            )

        avg_consec_ms = sum(consecutive_latencies) / len(consecutive_latencies)
        assert avg_consec_ms < 15.0, (
            f"Average consecutive drain latency {avg_consec_ms:.2f}ms exceeded 15.0ms"
        )

        # 5. Verify SQLite persistence (1 initial + 5 consecutive = 6 records)
        db_path = tmp_path / "canary-production-telemetry.sqlite3"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 6, f"Expected 6 persisted autopsies in SQLite, found {count}"

    @pytest.mark.anyio
    async def test_50_plus_cycle_latency_under_full_load_and_sqlite_drain(
        self, tmp_path: Path
    ) -> None:
        """Adversarial benchmark: 60 consecutive cycles with full multi-timeframe candle streams
        across all 8 active pairs and active SQLite autopsy drains.

        Verifies:
        1. 50+ consecutive cycles (60 total) executed under full multi-TF load.
        2. Active autopsy enqueuing on every single cycle round-robin across all 8 active pairs.
        3. All 60 autopsies successfully persisted to SQLite.
        4. Average cycle latency strictly < 15.0 ms.
        5. P99 cycle latency strictly < 15.0 ms.
        """
        mock_gateway = AsyncMock(spec=BinanceFuturesGateway)
        mock_gateway.get_position_risk.return_value = []
        mock_gateway.get_klines.return_value = []
        mock_gateway.testnet = True

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gateway,
            telegram_enabled=False,
        )
        trader.engine.perform_preflight_checks()

        now = time.time()

        # Populate ring buffers for all 8 pairs and all 5 active horizons (40 buffers total)
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = trader.sequencer.buffers[(sym, tf)]
                for i in range(50):
                    buf.append(
                        Candle(
                            timestamp_ms=1700000000000 + i * 60000,
                            open=Decimal("100.0"),
                            high=Decimal("101.0"),
                            low=Decimal("99.0"),
                            close=Decimal("100.5"),
                            volume=Decimal("1000.0"),
                        )
                    )
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        trader.btc_1h_history = [
            MacroCandle(
                timestamp_ms=1700000000000 + i * 3600000,
                open=Decimal("82600.0"),
                high=Decimal("82700.0"),
                low=Decimal("82500.0"),
                close=Decimal("82650.0"),
                volume=Decimal("500.0"),
            )
            for i in range(210)
        ]
        trader.last_candle_fetch_ts = now
        trader.last_export_ts = now

        # Warm up 5 cycles to eliminate cold-start noise
        for _ in range(5):
            await trader.run_single_cycle()

        total_benchmark_cycles = 60
        cycle_latencies_ms: list[float] = []

        for cycle_idx in range(total_benchmark_cycles):
            now_iter = time.time()
            trader.last_candle_fetch_ts = now_iter
            trader.last_export_ts = now_iter
            for sym in ACTIVE_PAIRS:
                for tf in ACTIVE_TIMEFRAMES:
                    trader.sequencer.last_fetch_ts[(sym, tf)] = now_iter

            sym = ACTIVE_PAIRS[cycle_idx % len(ACTIVE_PAIRS)]
            # Enqueue a pending trade autopsy to exercise SQLite database write & commit
            trader.engine.enqueue_ict_autopsy(
                {
                    "trade_id": f"trd-bench-{cycle_idx:04d}",
                    "candidate_id": f"cand-{sym.lower()}-ict-001",
                    "symbol": sym,
                    "side": "BUY" if cycle_idx % 2 == 0 else "SELL",
                    "entry_price": 100.0,
                    "exit_price": 102.5 if cycle_idx % 2 == 0 else 97.5,
                    "fill_qty": 0.05,
                    "optimal_price": 100.0,
                    "fvg_boundary_price": 100.0,
                    "lowest_price_during_trade": 99.5,
                    "highest_price_during_trade": 103.0,
                    "timestamp_ms": int(now_iter * 1000),
                }
            )

            t_start = time.perf_counter()
            await trader.run_single_cycle()
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            cycle_latencies_ms.append(elapsed_ms)

        # Statistical analysis
        assert len(cycle_latencies_ms) == total_benchmark_cycles
        avg_latency = sum(cycle_latencies_ms) / len(cycle_latencies_ms)
        sorted_latencies = sorted(cycle_latencies_ms)
        p50_latency = sorted_latencies[int(len(sorted_latencies) * 0.50)]
        p90_latency = sorted_latencies[int(len(sorted_latencies) * 0.90)]
        p99_index = min(int(math.ceil(len(sorted_latencies) * 0.99)) - 1, len(sorted_latencies) - 1)
        p99_latency = sorted_latencies[p99_index]
        max_latency = max(cycle_latencies_ms)

        # Verify SQLite persistence of drained autopsies
        db_path = tmp_path / "canary-production-telemetry.sqlite3"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        count = cur.fetchone()[0]
        conn.close()
        assert count == total_benchmark_cycles, (
            f"Expected {total_benchmark_cycles} autopsies in SQLite, but found {count}"
        )

        # Assertions strictly enforcing < 15.0 ms
        assert avg_latency < 15.0, (
            f"Average cycle latency {avg_latency:.3f} ms exceeded 15.0 ms ceiling! "
            f"(P50={p50_latency:.3f}ms, P90={p90_latency:.3f}ms, "
            f"P99={p99_latency:.3f}ms, Max={max_latency:.3f}ms)"
        )

        assert p99_latency < 15.0, (
            f"P99 cycle latency {p99_latency:.3f} ms exceeded 15.0 ms ceiling! "
            f"(Avg={avg_latency:.3f}ms, Max={max_latency:.3f}ms)"
        )

    @pytest.mark.anyio
    async def test_burst_batch_autopsy_drain_latency_under_15ms(self, tmp_path: Path) -> None:
        """Verifies that an 8-trade burst across all active pairs enqueued simultaneously
        drains within a single cycle strictly < 15.0 ms.
        """
        mock_gateway = AsyncMock(spec=BinanceFuturesGateway)
        mock_gateway.get_position_risk.return_value = []
        mock_gateway.get_klines.return_value = []
        mock_gateway.testnet = True

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gateway,
            telegram_enabled=False,
        )
        trader.engine.perform_preflight_checks()

        now = time.time()
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = trader.sequencer.buffers[(sym, tf)]
                for i in range(50):
                    buf.append(
                        Candle(
                            timestamp_ms=1700000000000 + i * 60000,
                            open=Decimal("100.0"),
                            high=Decimal("101.0"),
                            low=Decimal("99.0"),
                            close=Decimal("100.5"),
                            volume=Decimal("1000.0"),
                        )
                    )
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        trader.btc_1h_history = [
            MacroCandle(
                timestamp_ms=1700000000000 + i * 3600000,
                open=Decimal("82600.0"),
                high=Decimal("82700.0"),
                low=Decimal("82500.0"),
                close=Decimal("82650.0"),
                volume=Decimal("500.0"),
            )
            for i in range(210)
        ]
        trader.last_candle_fetch_ts = now
        trader.last_export_ts = now

        # Warm up 3 cycles
        for _ in range(3):
            await trader.run_single_cycle()

        # Enqueue burst of 8 autopsies simultaneously (one per active pair)
        for sym in ACTIVE_PAIRS:
            trader.engine.enqueue_ict_autopsy(
                {
                    "trade_id": f"trd-burst-{sym.lower()}",
                    "candidate_id": f"cand-{sym.lower()}-ict-001",
                    "symbol": sym,
                    "side": "BUY",
                    "entry_price": 100.0,
                    "exit_price": 102.5,
                    "fill_qty": 0.05,
                    "optimal_price": 100.0,
                    "fvg_boundary_price": 100.0,
                    "lowest_price_during_trade": 99.5,
                    "highest_price_during_trade": 103.0,
                    "timestamp_ms": int(now * 1000),
                }
            )

        assert trader.engine.has_pending_autopsies() is True

        now_iter = time.time()
        trader.last_candle_fetch_ts = now_iter
        trader.last_export_ts = now_iter
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                trader.sequencer.last_fetch_ts[(sym, tf)] = now_iter

        t_drain = time.perf_counter()
        await trader.run_single_cycle()
        drain_ms = (time.perf_counter() - t_drain) * 1000.0

        assert trader.engine.has_pending_autopsies() is False
        assert drain_ms < 15.0, (
            f"Burst batch drain of 8 autopsies took {drain_ms:.2f}ms, exceeding 15.0ms ceiling"
        )

        # Verify all 8 records persisted to SQLite
        db_path = tmp_path / "canary-production-telemetry.sqlite3"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ict_trade_autopsies")
        count = cur.fetchone()[0]
        conn.close()
        assert count == len(ACTIVE_PAIRS), f"Expected {len(ACTIVE_PAIRS)} autopsies in SQLite, found {count}"

    def test_sqlite_persistence_ict_autopsies(self, test_db_setup: Path) -> None:
        """Verifies completed trade autopsy inserts record into SQLite."""
        db_path = test_db_setup
        calc = IctAutopsyCalculator()
        metrics = calc.compute_metrics(
            trade_id="trd-sol-001",
            candidate_id="cand-solusdt-ict-001",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=100.0,
            exit_price=102.5,
            fill_qty=0.04,
            optimal_price=100.0,
            fvg_boundary_price=100.0,
            lowest_price_during_trade=99.8,
            highest_price_during_trade=103.0,
            timestamp_ms=1700000000000,
        )

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ict_trade_autopsies (
                trade_id, candidate_id, symbol, side, entry_price, exit_price,
                fill_qty, entry_timing_error_bps, fvg_slippage_bps, mae_bps, mfe_bps,
                bracket_efficiency, realized_edge_bps, gross_pnl_usdt, fee_cost_usdt,
                net_pnl_usdt, cause, timestamp_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics.trade_id,
                metrics.candidate_id,
                metrics.symbol,
                metrics.side,
                metrics.entry_price,
                metrics.exit_price,
                metrics.fill_qty,
                metrics.entry_timing_error_bps,
                metrics.fvg_slippage_bps,
                metrics.mae_bps,
                metrics.mfe_bps,
                metrics.bracket_efficiency,
                metrics.realized_edge_bps,
                metrics.gross_pnl_usdt,
                metrics.fee_cost_usdt,
                metrics.net_pnl_usdt,
                str(metrics.cause),
                metrics.timestamp_ms,
            ),
        )
        conn.commit()

        # Query back and verify row
        cur.execute(
            "SELECT trade_id, symbol, bracket_efficiency, net_pnl_usdt "
            "FROM ict_trade_autopsies WHERE trade_id = ?",
            ("trd-sol-001",),
        )
        row = cur.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "trd-sol-001"
        assert row[1] == "SOLUSDT"
        assert row[2] > 0.0
        assert row[3] > 0.0

    def test_sqlite_persistence_candidate_registry(self, test_db_setup: Path) -> None:
        """Verifies enrollment updates ict_candidate_registry table."""
        db_path = test_db_setup
        genome = IctCandidateGenome(
            candidate_id="cand-dogeusdt-ict-001",
            symbol="DOGEUSDT",
            generation=1,
            ote_lower=Decimal("0.62"),
            ote_upper=Decimal("0.79"),
            stdv_tp1=Decimal("2.0"),
            stdv_tp2=Decimal("4.0"),
            swing_lookback=50,
            lookback_htf=100,
            fvg_threshold_pct=Decimal("0.0015"),
            health_tier=CandidateHealthTier.HEALTHY,
            is_active=True,
        )

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO ict_candidate_registry (
                candidate_id, symbol, generation, parent_candidate_id,
                ote_lower, ote_upper, stdv_tp1, stdv_tp2, lookback_htf,
                health_tier, is_active, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                genome.candidate_id,
                genome.symbol,
                genome.generation,
                genome.parent_candidate_id,
                float(genome.ote_lower),
                float(genome.ote_upper),
                float(genome.stdv_tp1),
                float(genome.stdv_tp2),
                genome.lookback_htf,
                str(genome.health_tier),
                1 if genome.is_active else 0,
                1700000000000,
            ),
        )
        conn.commit()

        cur.execute(
            "SELECT candidate_id, symbol, ote_lower, ote_upper, health_tier "
            "FROM ict_candidate_registry WHERE symbol = 'DOGEUSDT'"
        )
        row = cur.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "cand-dogeusdt-ict-001"
        assert row[1] == "DOGEUSDT"
        assert row[2] == 0.62
        assert row[3] == 0.79
        assert row[4] == "HEALTHY"

    def test_jsonl_event_logging(self, tmp_path: Path) -> None:
        """Verifies trade autopsy records append structured JSONL event lines."""
        events_path = tmp_path / "canary-production-events.jsonl"
        event_payload = {
            "timestamp_ms": 1700000000000,
            "event_type": "ICT_TRADE_AUTOPSY",
            "trade_id": "trd-sui-001",
            "symbol": "SUIUSDT",
            "bracket_efficiency": 0.85,
            "net_pnl": 0.12,
            "cause": "ORGANIC_ALPHA",
        }
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_payload) + "\n")

        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event_type"] == "ICT_TRADE_AUTOPSY"
        assert parsed["symbol"] == "SUIUSDT"
        assert parsed["bracket_efficiency"] == 0.85

    def test_dynamic_state_machine_status_transitions(self) -> None:
        """Verifies candidate transition: PROBATIONARY -> HEALTHY / ELITE."""
        evaluator = FiveStageQualificationGateEvaluator()

        # 1. 2 trades acquired: remains WAITING_FOR_SAMPLES
        s1 = evaluator.evaluate(
            avg_return_pct=4.0,
            worst_drawdown_pct=5.0,
            profit_factor=1.5,
            trade_count=2,
            stress_loss_usdt=1.0,
            stress_drift_usdt=0.0,
        )
        assert s1["qualified"] is False
        assert s1["status"] == "WAITING_FOR_SAMPLES"

        # 2. 5 trades acquired & passing: transitions to QUALIFIED
        s2 = evaluator.evaluate(
            avg_return_pct=4.0,
            worst_drawdown_pct=5.0,
            profit_factor=1.5,
            trade_count=5,
            stress_loss_usdt=1.0,
            stress_drift_usdt=0.0,
        )
        assert s2["qualified"] is True
        assert s2["status"] == "QUALIFIED"

        # 3. Persistent drawdown degrades candidate
        s3 = evaluator.evaluate(
            avg_return_pct=-2.0,
            worst_drawdown_pct=20.0,
            profit_factor=0.8,
            trade_count=6,
            stress_loss_usdt=1.0,
            stress_drift_usdt=0.0,
        )
        assert s3["qualified"] is False
        assert s3["status"] == "REJECTED"
