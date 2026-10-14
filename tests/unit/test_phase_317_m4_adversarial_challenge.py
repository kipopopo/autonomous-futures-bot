"""Phase 317 Milestone 4 Empirical Adversarial Challenge Suite.

File: tests/unit/test_phase_317_m4_adversarial_challenge.py

Adversarially probes:
1. Stage 1: Cumulative Return >= 0.0% exact boundary:
   - 0.00% -> PASS
   - -0.01% -> REJECT
   - -0.0001% -> REJECT
   - +0.01% -> PASS
   - Negative/zero starting equity handling
2. Stage 2: Max Drawdown <= 15.0% peak-to-trough boundary:
   - Exactly 15.0000% -> PASS
   - 15.0100% -> REJECT
   - Intermediate peak-to-trough 15.00% -> PASS vs 15.01% -> REJECT
   - Monotonic curves and catastrophic drawdowns
3. Stage 3: Profit Factor >= 1.05 zero-division and margin boundary:
   - 0 loss with positive profit -> float('inf') -> PASS
   - 0 loss with 0 profit -> 0.0 -> REJECT
   - 0 profit with positive loss -> 0.0 -> REJECT
   - PF = 1.049 -> REJECT
   - PF = 1.050 -> PASS
4. Stage 4: Minimum Sample Size >= 5 completed trades hurdle:
   - N = 0, 1, 2, 3, 4 trades -> WAITING_FOR_SAMPLES / REJECT
   - N = 5 trades with passing metrics -> QUALIFIED
   - N = 5 trades with failing metrics -> REJECTED (not WAITING_FOR_SAMPLES)
5. Stage 5: Monte Carlo randomized slippage (+/-0.05%) and fee variance (+/-10%):
   - Robust strategy survival >= 95.0% -> PASS
   - Fragile razor-thin margin strategy noise breakdown < 95.0% -> REJECT
   - Survival rate boundary 95.0% -> PASS vs 94.9% -> REJECT
   - Stress loss / balance drift invariant boundaries
   - Empty trades list and seed determinism
6. Candidate Lifecycle State Machine adverse transitions:
   - Initial registration: CANDIDATE
   - Transition to INCUBATING
   - Invalid transition attempt raises ValueError
   - Sudden > 15% drawdown in INCUBATING -> immediate DISQUALIFIED
   - Sample count < 5 in INCUBATING -> remains INCUBATING
   - Meeting all 5 gates in INCUBATING -> QUALIFIED
   - Sudden > 15% drawdown in ACTIVE -> immediate DISQUALIFIED
   - 5 consecutive losses in ACTIVE -> immediate DISQUALIFIED
   - Moderate shock (> 8% DD or 3 consecutive losses) in ACTIVE -> DEGRADED + spawns mutated child
   - Deterioration in DEGRADED -> DISQUALIFIED
   - Recovery in DEGRADED (DD <= 5% and 0 losses) -> ACTIVE
   - DISQUALIFIED terminal state immutability
7. Candidate Registry Manifest tampering resistance:
   - Hash invalidation on corrupted candidate file
8. Autopsy decomposition edge cases:
   - Zero fill qty, zero displacement, and fee drag attribution
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from autonomous_futures.feed.auto_evolution import (
    DEFAULT_ICT_GENOMES,
    AutopsyAttributionCause,
    CandidateLifecycleManager,
    CandidateLifecycleState,
    IctAutopsyCalculator,
    IctGenome,
)
from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS
from autonomous_futures.feed.strategy_mining import (
    FiveStageQualificationGateEvaluator,
    Phase317OosGateEvaluator,
)
from autonomous_futures.paper.candidate_registry import (
    read_candidate_registry,
    verify_candidate_registry_manifest,
)

# =============================================================================
# Suite 1: Stage 1 Cumulative Return Boundary Tests
# =============================================================================

class TestStage1CumulativeReturnBoundary:
    """Adversarial stress-testing of Stage 1: Cumulative Return >= 0.0%."""

    @pytest.fixture
    def evaluator(self) -> Phase317OosGateEvaluator:
        return Phase317OosGateEvaluator()

    def test_exact_zero_return_passes(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Cumulative return of exactly 0.00% must PASS Stage 1."""
        ret = evaluator.compute_cumulative_return(starting_equity=100.0, final_equity=100.0)
        assert ret == 0.0

        res = evaluator.evaluate(
            avg_return_pct=0.0,
            worst_drawdown_pct=5.0,
            profit_factor=1.5,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_1_return"] is True
        assert res["qualified"] is True
        assert res["status"] == "QUALIFIED"

    def test_marginal_negative_return_rejected(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Cumulative return of -0.01% must REJECT Stage 1."""
        ret = evaluator.compute_cumulative_return(starting_equity=100.0, final_equity=99.99)
        assert pytest.approx(ret, abs=1e-5) == -0.01

        res = evaluator.evaluate(
            avg_return_pct=-0.01,
            worst_drawdown_pct=5.0,
            profit_factor=1.5,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_1_return"] is False
        assert res["qualified"] is False
        assert res["status"] == "REJECTED"

    def test_sub_basis_point_negative_return_rejected(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Cumulative return of -0.0001% must REJECT Stage 1."""
        ret = evaluator.compute_cumulative_return(starting_equity=100.0, final_equity=99.9999)
        assert ret < 0.0

        res = evaluator.evaluate(
            avg_return_pct=-0.0001,
            worst_drawdown_pct=2.0,
            profit_factor=2.0,
            trade_count=10,
            stress_survival_rate_pct=98.0,
        )
        assert res["gates_passed"]["stage_1_return"] is False
        assert res["qualified"] is False

    def test_positive_micro_return_passes(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Cumulative return of +0.01% must PASS Stage 1."""
        ret = evaluator.compute_cumulative_return(starting_equity=100.0, final_equity=100.01)
        assert ret > 0.0

        res = evaluator.evaluate(
            avg_return_pct=0.01,
            worst_drawdown_pct=5.0,
            profit_factor=1.5,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_1_return"] is True
        assert res["qualified"] is True

    def test_zero_or_negative_starting_equity_safely_handled(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Zero or negative starting equity must not raise ZeroDivisionError."""
        assert evaluator.compute_cumulative_return(0.0, 100.0) == 0.0
        assert evaluator.compute_cumulative_return(-50.0, 100.0) == 0.0

    def test_evaluate_candidate_with_negative_net_trades_fails_stage_1(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Candidate evaluation with net negative pnl must fail stage 1."""
        trades = [
            {
                "net_pnl_usdt": -0.02,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 99.8,
                "fill_qty": 0.01,
            },
            {
                "net_pnl_usdt": 0.01,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 100.1,
                "fill_qty": 0.01,
            },
            {
                "net_pnl_usdt": 0.00,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 100.0,
                "fill_qty": 0.01,
            },
            {
                "net_pnl_usdt": 0.00,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 100.0,
                "fill_qty": 0.01,
            },
            {
                "net_pnl_usdt": 0.00,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 100.0,
                "fill_qty": 0.01,
            },
        ]
        card = evaluator.evaluate_candidate(
            candidate_id="cand-test-neg-ret",
            symbol="SOLUSDT",
            trades=trades,
            starting_equity=100.0,
        )
        assert card.stage_1_return_passed is False
        assert card.all_stages_passed is False
        assert card.status_label == "REJECTED"

    def test_alias_compatibility(self) -> None:
        """Verify FiveStageQualificationGateEvaluator alias works identically."""
        assert FiveStageQualificationGateEvaluator is Phase317OosGateEvaluator


# =============================================================================
# Suite 2: Stage 2 Max Drawdown Boundary Tests
# =============================================================================

class TestStage2MaxDrawdownBoundary:
    """Adversarial stress-testing of Stage 2: Max Drawdown <= 15.0%."""

    @pytest.fixture
    def evaluator(self) -> Phase317OosGateEvaluator:
        return Phase317OosGateEvaluator()

    def test_exact_15_00_pct_drawdown_passes(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Drawdown of exactly 15.0000% must PASS Stage 2."""
        curve = [100.0, 85.0, 90.0]  # (100 - 85) / 100 = 15.00%
        dd = evaluator.compute_max_drawdown(curve)
        assert dd == 15.0

        res = evaluator.evaluate(
            avg_return_pct=5.0,
            worst_drawdown_pct=15.00,
            profit_factor=1.5,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_2_drawdown"] is True
        assert res["qualified"] is True
        assert res["status"] == "QUALIFIED"

    def test_15_01_pct_drawdown_rejected(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Drawdown of 15.0100% must REJECT Stage 2."""
        curve = [100.0, 84.99, 90.0]  # (100 - 84.99) / 100 = 15.01%
        dd = evaluator.compute_max_drawdown(curve)
        assert dd == 15.01

        res = evaluator.evaluate(
            avg_return_pct=5.0,
            worst_drawdown_pct=15.01,
            profit_factor=1.5,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_2_drawdown"] is False
        assert res["qualified"] is False
        assert res["status"] == "REJECTED"

    def test_intermediate_peak_trough_drawdown(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Peak-to-trough calculation occurs correctly even when peak is mid-curve."""
        # Peak = 200.0, Trough = 170.0 -> DD = (200 - 170) / 200 = 30 / 200 = 15.00%
        curve_pass = [100.0, 150.0, 200.0, 170.0, 190.0]
        assert evaluator.compute_max_drawdown(curve_pass) == 15.0

        # Peak = 200.0, Trough = 169.98 -> DD = 30.02 / 200 = 15.01%
        curve_fail = [100.0, 150.0, 200.0, 169.98, 190.0]
        assert evaluator.compute_max_drawdown(curve_fail) == 15.01

    def test_empty_or_monotonic_curve(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Empty or monotonically rising curves return 0.0% drawdown."""
        assert evaluator.compute_max_drawdown([]) == 0.0
        assert evaluator.compute_max_drawdown([100.0, 105.0, 110.0, 115.0]) == 0.0

    def test_catastrophic_drawdown_rejected(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Catastrophic 50% or 100% drawdown is strictly rejected."""
        assert evaluator.compute_max_drawdown([100.0, 50.0]) == 50.0
        res = evaluator.evaluate(
            avg_return_pct=5.0,
            worst_drawdown_pct=50.0,
            profit_factor=1.5,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_2_drawdown"] is False
        assert res["qualified"] is False


# =============================================================================
# Suite 3: Stage 3 Profit Factor Boundary & Zero-Division Tests
# =============================================================================

class TestStage3ProfitFactorBoundary:
    """Adversarial stress-testing of Stage 3: Profit Factor >= 1.05."""

    @pytest.fixture
    def evaluator(self) -> Phase317OosGateEvaluator:
        return Phase317OosGateEvaluator()

    def test_zero_loss_with_positive_profit_returns_inf_and_passes(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """0 loss with positive profit must return float('inf') and PASS Stage 3."""
        trades = [{"net_pnl_usdt": 2.50}, {"net_pnl_usdt": 1.20}]
        pf = evaluator.compute_profit_factor(trades)
        assert math.isinf(pf)
        assert pf > 0.0

        res = evaluator.evaluate(
            avg_return_pct=3.7,
            worst_drawdown_pct=2.0,
            profit_factor=pf,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_3_profit_factor"] is True
        assert res["qualified"] is True
        assert res["status"] == "QUALIFIED"

    def test_zero_loss_with_zero_profit_returns_zero_and_rejects(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """0 loss with 0 profit must return 0.0 and REJECT Stage 3."""
        trades = [{"net_pnl_usdt": 0.0}, {"net_pnl_usdt": 0.0}]
        pf = evaluator.compute_profit_factor(trades)
        assert pf == 0.0

        res = evaluator.evaluate(
            avg_return_pct=0.0,
            worst_drawdown_pct=0.0,
            profit_factor=pf,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_3_profit_factor"] is False
        assert res["qualified"] is False
        assert res["status"] == "REJECTED"

    def test_zero_profit_with_positive_loss_returns_zero_and_rejects(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """All losing trades must return PF=0.0 and REJECT Stage 3."""
        trades = [{"net_pnl_usdt": -1.0}, {"net_pnl_usdt": -2.0}]
        pf = evaluator.compute_profit_factor(trades)
        assert pf == 0.0

        res = evaluator.evaluate(
            avg_return_pct=-3.0,
            worst_drawdown_pct=5.0,
            profit_factor=pf,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_3_profit_factor"] is False
        assert res["qualified"] is False

    def test_exact_1_050_profit_factor_passes(self, evaluator: Phase317OosGateEvaluator) -> None:
        """Profit factor of exactly 1.050 must PASS Stage 3."""
        trades = [{"net_pnl_usdt": 1.050}, {"net_pnl_usdt": -1.000}]
        pf = evaluator.compute_profit_factor(trades)
        assert pytest.approx(pf, abs=1e-5) == 1.050

        res = evaluator.evaluate(
            avg_return_pct=0.05,
            worst_drawdown_pct=2.0,
            profit_factor=1.050,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_3_profit_factor"] is True
        assert res["qualified"] is True
        assert res["status"] == "QUALIFIED"

    def test_marginal_1_049_profit_factor_rejects(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Profit factor of 1.049 must REJECT Stage 3."""
        trades = [{"net_pnl_usdt": 1.049}, {"net_pnl_usdt": -1.000}]
        pf = evaluator.compute_profit_factor(trades)
        assert pytest.approx(pf, abs=1e-5) == 1.049

        res = evaluator.evaluate(
            avg_return_pct=0.049,
            worst_drawdown_pct=2.0,
            profit_factor=1.049,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_3_profit_factor"] is False
        assert res["qualified"] is False
        assert res["status"] == "REJECTED"


# =============================================================================
# Suite 4: Stage 4 Sample Size Hurdle Tests
# =============================================================================

class TestStage4SampleSizeBoundary:
    """Adversarial stress-testing of Stage 4: Minimum sample size >= 5 trades."""

    @pytest.fixture
    def evaluator(self) -> Phase317OosGateEvaluator:
        return Phase317OosGateEvaluator()

    @pytest.mark.parametrize("n_trades", [0, 1, 2, 3, 4])
    def test_under_5_trades_yields_waiting_for_samples(
        self, evaluator: Phase317OosGateEvaluator, n_trades: int
    ) -> None:
        """Sample size < 5 trades must yield WAITING_FOR_SAMPLES and qualified=False."""
        res = evaluator.evaluate(
            avg_return_pct=15.0,
            worst_drawdown_pct=1.0,
            profit_factor=3.0,
            trade_count=n_trades,
            stress_survival_rate_pct=99.0,
        )
        assert res["gates_passed"]["stage_4_trade_count"] is False
        assert res["qualified"] is False
        assert res["status"] == "WAITING_FOR_SAMPLES"

    def test_candidate_evaluator_under_5_trades_label(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Candidate evaluation with 4 trades yields WAITING_FOR_SAMPLES (4/5)."""
        trades = [
            {
                "net_pnl_usdt": 1.0,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 102.0,
                "fill_qty": 0.05,
            }
            for _ in range(4)
        ]
        card = evaluator.evaluate_candidate(
            candidate_id="cand-sample-4",
            symbol="BTCUSDT",
            trades=trades,
        )
        assert card.completed_trades == 4
        assert card.stage_4_sample_size_passed is False
        assert card.all_stages_passed is False
        assert card.status_label == "WAITING_FOR_SAMPLES (4/5)"

    def test_exactly_5_trades_with_passing_metrics_qualifies(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Exactly 5 trades with passing metrics evaluates and passes."""
        res = evaluator.evaluate(
            avg_return_pct=5.0,
            worst_drawdown_pct=5.0,
            profit_factor=2.0,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_4_trade_count"] is True
        assert res["qualified"] is True
        assert res["status"] == "QUALIFIED"

    def test_5_trades_with_failing_metric_is_rejected_not_waiting(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """5 trades with failing return is REJECTED, not WAITING_FOR_SAMPLES."""
        res = evaluator.evaluate(
            avg_return_pct=-1.0,
            worst_drawdown_pct=5.0,
            profit_factor=2.0,
            trade_count=5,
            stress_survival_rate_pct=96.0,
        )
        assert res["gates_passed"]["stage_4_trade_count"] is True
        assert res["qualified"] is False
        assert res["status"] == "REJECTED"


# =============================================================================
# Suite 5: Stage 5 Monte Carlo Stress Survival Tests
# =============================================================================

class TestStage5MonteCarloStressSurvival:
    """Adversarial stress-testing of Stage 5: Monte Carlo randomized slippage & fees."""

    @pytest.fixture
    def evaluator(self) -> Phase317OosGateEvaluator:
        return Phase317OosGateEvaluator()

    def test_robust_strategy_survives_monte_carlo_noise(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Strategy with solid margin easily exceeds 95% survival over 200 runs."""
        robust_trades = [
            {
                "entry_price": 100.0,
                "exit_price": 103.0,
                "fill_qty": 0.05,
                "side": "BUY",
                "fee_cost_usdt": 0.002,
                "net_pnl_usdt": 0.148,
            }
            for _ in range(6)
        ]
        stress = evaluator.run_stress_test(robust_trades, starting_equity=100.0, random_seed=123)
        assert stress.simulations_count == 200
        assert stress.survival_rate_pct >= 95.0
        assert stress.passed is True

    def test_fragile_thin_margin_strategy_fails_under_perturbation(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Strategy with razor-thin returns wiped out by fee/slippage noise fails."""
        # Trades with nominal drawdown right at 15.0% threshold
        # Noise reliably pushes perturbed drawdown above 15% ceiling
        fragile_trades = [
            {
                "entry_price": 100.0,
                "exit_price": 98.0,
                "fill_qty": 3.0,
                "side": "BUY",
                "fee_cost_usdt": 0.10,
                "net_pnl_usdt": -6.10,
            },
            {
                "entry_price": 100.0,
                "exit_price": 98.0,
                "fill_qty": 3.0,
                "side": "BUY",
                "fee_cost_usdt": 0.10,
                "net_pnl_usdt": -6.10,
            },
            {
                "entry_price": 100.0,
                "exit_price": 99.0,
                "fill_qty": 3.0,
                "side": "BUY",
                "fee_cost_usdt": 0.10,
                "net_pnl_usdt": -3.10,
            },
        ]
        stress = evaluator.run_stress_test(fragile_trades, starting_equity=100.0, random_seed=42)
        assert stress.simulations_count == 200
        # Perturbed drawdown exceeds 15% on the majority of runs -> survival rate collapses
        assert stress.survival_rate_pct < 95.0
        assert stress.passed is False

    def test_direct_evaluate_survival_rate_boundary(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Survival rate boundary: 95.0% PASS vs 94.9% REJECT."""
        pass_res = evaluator.evaluate(
            avg_return_pct=5.0,
            worst_drawdown_pct=5.0,
            profit_factor=1.8,
            trade_count=6,
            stress_survival_rate_pct=95.0,
        )
        assert pass_res["gates_passed"]["stage_5_stress_resilience"] is True
        assert pass_res["qualified"] is True

        fail_res = evaluator.evaluate(
            avg_return_pct=5.0,
            worst_drawdown_pct=5.0,
            profit_factor=1.8,
            trade_count=6,
            stress_survival_rate_pct=94.9,
        )
        assert fail_res["gates_passed"]["stage_5_stress_resilience"] is False
        assert fail_res["qualified"] is False
        assert fail_res["status"] == "REJECTED"

    def test_empty_trades_stress_test_returns_zero_survival(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Empty trades list returns 0 survival and passed=False."""
        stress = evaluator.run_stress_test([])
        assert stress.simulations_count == 0
        assert stress.survival_rate_pct == 0.0
        assert stress.passed is False

    def test_monte_carlo_seed_reproducibility(
        self, evaluator: Phase317OosGateEvaluator
    ) -> None:
        """Deterministic seed yields bit-for-bit identical results."""
        trades = [
            {
                "entry_price": 100.0,
                "exit_price": 102.0,
                "fill_qty": 0.1,
                "side": "BUY",
                "net_pnl_usdt": 0.2,
            }
            for _ in range(5)
        ]
        s1 = evaluator.run_stress_test(trades, random_seed=999)
        s2 = evaluator.run_stress_test(trades, random_seed=999)
        assert s1.survival_rate_pct == s2.survival_rate_pct
        assert s1.max_perturbed_drawdown_pct == s2.max_perturbed_drawdown_pct
        assert s1.survival_count == s2.survival_count


# =============================================================================
# Suite 6: Candidate Lifecycle Adverse Transitions & State Machine Stress
# =============================================================================

class TestCandidateLifecycleAdverseTransitions:
    """Adversarial stress-testing of candidate state machine transitions."""

    @pytest.fixture
    def manager(self) -> CandidateLifecycleManager:
        evaluator = Phase317OosGateEvaluator()
        return CandidateLifecycleManager(gate_evaluator=evaluator)

    @pytest.fixture
    def sample_genome(self) -> IctGenome:
        return DEFAULT_ICT_GENOMES["SOLUSDT"]

    def test_initial_candidate_state_is_candidate(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Newly registered genome starts in CANDIDATE state."""
        ctx = manager.register_new_candidate(sample_genome)
        assert ctx.state == CandidateLifecycleState.CANDIDATE
        assert ctx.candidate_id == "cand-solusdt-ict-001"

    def test_transition_to_incubating_succeeds_from_candidate(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Valid transition CANDIDATE -> INCUBATING."""
        ctx = manager.register_new_candidate(sample_genome)
        manager.transition_to_incubating(ctx.candidate_id)
        assert ctx.state == CandidateLifecycleState.INCUBATING

    def test_invalid_transition_to_incubating_raises_value_error(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Attempting to transition to INCUBATING when already INCUBATING raises ValueError."""
        ctx = manager.register_new_candidate(sample_genome)
        manager.transition_to_incubating(ctx.candidate_id)
        with pytest.raises(ValueError, match="Cannot transition to INCUBATING from INCUBATING"):
            manager.transition_to_incubating(ctx.candidate_id)

    def test_incubating_sudden_drawdown_over_15_pct_forces_disqualification(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Sudden > 15% drawdown in INCUBATING forces immediate DISQUALIFIED."""
        ctx = manager.register_new_candidate(sample_genome)
        manager.transition_to_incubating(ctx.candidate_id)

        # Single trade with -15.10 USDT loss on 100 USDT capital -> 15.10% drawdown
        catastrophic_trade = {
            "net_pnl_usdt": -15.10,
            "side": "BUY",
            "entry_price": 100.0,
            "exit_price": 84.9,
            "fill_qty": 1.0,
            "cause": "ADVERSE_SELECTION",
        }
        state, child = manager.on_trade_completed(ctx.candidate_id, catastrophic_trade)

        assert state == CandidateLifecycleState.DISQUALIFIED
        assert ctx.state == CandidateLifecycleState.DISQUALIFIED
        assert ctx.running_drawdown_pct > 15.0
        assert child is None

    def test_incubating_under_sample_size_remains_incubating(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Trades < 5 keep state in INCUBATING (waiting for samples)."""
        ctx = manager.register_new_candidate(sample_genome)
        manager.transition_to_incubating(ctx.candidate_id)

        for _ in range(4):
            trade = {
                "net_pnl_usdt": 0.50,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 101.0,
                "fill_qty": 0.5,
            }
            state, _ = manager.on_trade_completed(ctx.candidate_id, trade)
            assert state == CandidateLifecycleState.INCUBATING

        assert len(ctx.trades_history) == 4
        assert ctx.state == CandidateLifecycleState.INCUBATING

    def test_incubating_passing_all_gates_becomes_qualified(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Reaching 5 winning robust trades transitions INCUBATING -> QUALIFIED."""
        ctx = manager.register_new_candidate(sample_genome)
        manager.transition_to_incubating(ctx.candidate_id)

        for i in range(5):
            trade = {
                "net_pnl_usdt": 1.0,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 102.0,
                "fill_qty": 0.5,
                "fee_cost_usdt": 0.01,
            }
            state, _ = manager.on_trade_completed(ctx.candidate_id, trade)
            if i < 4:
                assert state == CandidateLifecycleState.INCUBATING
            else:
                assert state == CandidateLifecycleState.QUALIFIED

        assert ctx.state == CandidateLifecycleState.QUALIFIED

    def test_active_candidate_sudden_drawdown_over_15_pct_disqualifies(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Sudden > 15% drawdown on ACTIVE candidate forces immediate DISQUALIFIED."""
        ctx = manager.register_new_candidate(sample_genome)
        ctx.state = CandidateLifecycleState.ACTIVE

        trade = {
            "net_pnl_usdt": -15.20,
            "side": "BUY",
            "entry_price": 100.0,
            "exit_price": 84.8,
            "fill_qty": 1.0,
            "cause": "FLASH_CRASH",
        }
        state, _ = manager.on_trade_completed(ctx.candidate_id, trade)
        assert state == CandidateLifecycleState.DISQUALIFIED
        assert ctx.state == CandidateLifecycleState.DISQUALIFIED

    def test_active_candidate_five_consecutive_losses_disqualifies(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """5 consecutive losses on ACTIVE candidate forces DISQUALIFIED."""
        ctx = manager.register_new_candidate(sample_genome)
        ctx.state = CandidateLifecycleState.ACTIVE

        # 4 small losses -> transitions to DEGRADED on 3rd/4th
        for i in range(4):
            trade = {
                "net_pnl_usdt": -0.5,
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 99.5,
                "fill_qty": 1.0,
            }
            state, _ = manager.on_trade_completed(ctx.candidate_id, trade)
            if i >= 2:
                assert state == CandidateLifecycleState.DEGRADED

        # 5th consecutive loss -> DISQUALIFIED
        trade5 = {
            "net_pnl_usdt": -0.5,
            "side": "BUY",
            "entry_price": 100.0,
            "exit_price": 99.5,
            "fill_qty": 1.0,
        }
        state5, _ = manager.on_trade_completed(ctx.candidate_id, trade5)
        assert state5 == CandidateLifecycleState.DISQUALIFIED
        assert ctx.state == CandidateLifecycleState.DISQUALIFIED

    def test_active_candidate_moderate_shock_degrades_and_spawns_child(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Active candidate with drawdown > 8% degrades and registers spawned mutated child."""
        ctx = manager.register_new_candidate(sample_genome)
        ctx.state = CandidateLifecycleState.ACTIVE

        trade = {
            "net_pnl_usdt": -8.50,  # 8.50% drawdown > 8.0%
            "side": "BUY",
            "entry_price": 100.0,
            "exit_price": 91.5,
            "fill_qty": 1.0,
            "cause": "TIMING_ERROR",
            "realized_edge_bps": -25.0,
            "entry_timing_error_bps": 30.0,
            "adverse_selection_bps": 20.0,
        }
        state, child = manager.on_trade_completed(ctx.candidate_id, trade)
        assert state == CandidateLifecycleState.DEGRADED
        assert ctx.state == CandidateLifecycleState.DEGRADED
        assert child is not None
        assert child.generation == 2
        assert child.parent_candidate_id == ctx.candidate_id
        # Spawned child must be registered in the registry
        assert child.candidate_id in manager.registry

    def test_degraded_candidate_recovery_to_active(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """DEGRADED candidate recovering DD <= 5.0% and 0 consecutive losses returns to ACTIVE."""
        ctx = manager.register_new_candidate(sample_genome)
        ctx.state = CandidateLifecycleState.DEGRADED
        ctx.running_drawdown_pct = 7.0
        ctx.consecutive_losses = 3

        # Winning trade with enough profit to recover equity
        recovery_trade = {
            "net_pnl_usdt": 10.0,
            "side": "BUY",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "fill_qty": 1.0,
        }
        state, _ = manager.on_trade_completed(ctx.candidate_id, recovery_trade)
        assert state == CandidateLifecycleState.ACTIVE
        assert ctx.state == CandidateLifecycleState.ACTIVE
        assert ctx.consecutive_losses == 0

    def test_disqualified_state_is_terminal(
        self, manager: CandidateLifecycleManager, sample_genome: IctGenome
    ) -> None:
        """Once DISQUALIFIED, subsequent winning trades do not reactivate."""
        ctx = manager.register_new_candidate(sample_genome)
        ctx.state = CandidateLifecycleState.DISQUALIFIED

        winning_trade = {
            "net_pnl_usdt": 50.0,
            "side": "BUY",
            "entry_price": 100.0,
            "exit_price": 150.0,
            "fill_qty": 1.0,
        }
        state, _ = manager.on_trade_completed(ctx.candidate_id, winning_trade)
        assert state == CandidateLifecycleState.DISQUALIFIED
        assert ctx.state == CandidateLifecycleState.DISQUALIFIED


# =============================================================================
# Suite 7: Candidate Registry Manifest Tamper Resistance
# =============================================================================

class TestCandidateRegistryManifestTamperResistance:
    """Verifies candidate registry cryptographic manifest fail-closed behavior."""

    def test_tampered_candidate_manifest_fails_verification(self, tmp_path: Path) -> None:
        """Tampering with manifest hashes or contents fails verification."""
        manifest_path = Path("artifacts/paper_live/candidate_registry.json")
        assert manifest_path.is_file()

        # Read original manifest
        manifest = read_candidate_registry(manifest_path, verify_hash=True)
        assert verify_candidate_registry_manifest(manifest) is True

        # Write corrupted manifest copy to tmp_path with modified candidate_artifact_hash
        corrupted_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        first_sym = next(iter(corrupted_data["symbols"]))
        corrupted_data["symbols"][first_sym]["candidate_artifact_hash"] = "0" * 64
        corrupted_file = tmp_path / "candidate_registry_tampered.json"
        corrupted_file.write_text(json.dumps(corrupted_data), encoding="utf-8")

        corrupted_manifest = read_candidate_registry(corrupted_file, verify_hash=False)
        assert verify_candidate_registry_manifest(corrupted_manifest) is False

    def test_all_8_pairs_have_valid_canonical_ids_and_artifacts(self) -> None:
        """All enrolled pairs have valid artifact files with non-zero size."""
        manifest_path = Path("artifacts/paper_live/candidate_registry.json")
        manifest = read_candidate_registry(manifest_path, verify_hash=True)

        for sym, entry in manifest.symbols.items():
            assert sym in ACTIVE_PAIRS
            art_path = Path(entry.artifact_path)
            assert art_path.is_file()
            assert art_path.stat().st_size > 0
            # Read artifact content
            content = json.loads(art_path.read_text(encoding="utf-8"))
            assert content["candidate_id"] == entry.candidate_id
            assert sym in content["strategy"]["universe"]["symbols"]

        for sym in ACTIVE_PAIRS:
            ict_art_path = Path(f"artifacts/paper_live/candidates/cand-{sym.lower()}-ict-001.json")
            assert ict_art_path.is_file()
            assert ict_art_path.stat().st_size > 0


# =============================================================================
# Suite 8: Autopsy Calculator Edge Cases & Invariant Handling
# =============================================================================

class TestAutopsyCalculatorEdgeCases:
    """Adversarial testing of autopsy calculator math under edge conditions."""

    @pytest.fixture
    def calc(self) -> IctAutopsyCalculator:
        return IctAutopsyCalculator(maker_fee_rate=0.0002, taker_fee_rate=0.0004)

    def test_zero_fill_qty_produces_zero_pnl(self, calc: IctAutopsyCalculator) -> None:
        """Zero fill qty yields 0.0 gross and net pnl without crashing."""
        metrics = calc.compute_metrics(
            trade_id="trd-zero-qty",
            candidate_id="cand-ethusdt-ict-001",
            symbol="ETHUSDT",
            side="BUY",
            entry_price=2000.0,
            exit_price=2050.0,
            fill_qty=0.0,
            optimal_price=2000.0,
            fvg_boundary_price=2000.0,
            lowest_price_during_trade=1990.0,
            highest_price_during_trade=2060.0,
            timestamp_ms=1700000000000,
        )
        assert metrics.gross_pnl_usdt == 0.0
        assert metrics.net_pnl_usdt == 0.0
        assert metrics.fee_cost_usdt == 0.0

    def test_flat_trade_zero_displacement_has_fee_drag(self, calc: IctAutopsyCalculator) -> None:
        """Flat trade (entry == exit) has 0 gross pnl and negative net pnl due to fee."""
        metrics = calc.compute_metrics(
            trade_id="trd-flat",
            candidate_id="cand-ethusdt-ict-001",
            symbol="ETHUSDT",
            side="BUY",
            entry_price=2000.0,
            exit_price=2000.0,
            fill_qty=0.01,
            optimal_price=2000.0,
            fvg_boundary_price=2000.0,
            lowest_price_during_trade=1995.0,
            highest_price_during_trade=2005.0,
            timestamp_ms=1700000000000,
        )
        assert metrics.gross_pnl_usdt == 0.0
        assert metrics.net_pnl_usdt < 0.0
        assert metrics.bracket_efficiency == 0.0
        assert metrics.cause == AutopsyAttributionCause.REGIME_MISMATCH

    def test_adverse_timing_delay_attribution(self, calc: IctAutopsyCalculator) -> None:
        """Large entry timing error (> 15 bps) with minimal FVG slippage triggers TIMING_DELAY."""
        metrics = calc.compute_metrics(
            trade_id="trd-timing-delay",
            candidate_id="cand-ethusdt-ict-001",
            symbol="ETHUSDT",
            side="BUY",
            entry_price=2005.0,  # 25 bps above optimal (2000.0)
            exit_price=1995.0,
            fill_qty=0.01,
            optimal_price=2000.0,
            fvg_boundary_price=2004.0,  # slippage = 5.0 bps <= 10.0
            lowest_price_during_trade=1990.0,
            highest_price_during_trade=2006.0,
            timestamp_ms=1700000000000,
        )
        assert metrics.entry_timing_error_bps > 15.0
        assert metrics.fvg_slippage_bps <= 10.0
        assert metrics.cause == AutopsyAttributionCause.TIMING_DELAY
