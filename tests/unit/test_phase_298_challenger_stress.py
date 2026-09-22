"""Phase 298 Adversarial Challenger Stress & Boundary Test Suite.

Adversarially challenges Phase 298:
- Challenge 1: Parameter Mutation Robustness & Determinism
- Challenge 2: Qualification Gate Stress (boundary values, strict rejection)
- Challenge 3: Flash Crash (-20%) & Spread Shock (10.0%) Microstructure Invariants
- Challenge 4: Open Trade Immutability Under Hot-Reload
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from autonomous_futures.data.quality import DataQualityError
from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import (
    AggregateTrade,
    OrderBookDepthSnapshot,
    OrderBookLevel,
)
from autonomous_futures.feed.paper_ledger import DOUBLE_ENTRY_MAX_DRIFT
from autonomous_futures.feed.strategy_mining import (
    ContinuousOOSGateEvaluator,
    MicrostructureMutationEngine,
    Phase298OOSGateRecord,
    compute_donchian_channel,
    compute_hawkes_spectral_radius_gate,
    compute_microstructure_momentum_signal,
    compute_ofi_zscore,
    compute_order_flow_imbalance,
    compute_rolling_volatility,
    compute_trade_flow_momentum,
)
from autonomous_futures.paper.candidate_registry import (
    CandidateManifestEntry,
    CandidateRegistryHotReloader,
    build_candidate_registry_manifest,
    write_candidate_registry,
)
from autonomous_futures.paper.live_engine import (
    ActivePaperTrade,
    evaluate_strategy_exit,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

# =====================================================================
# Fixtures & Helpers
# =====================================================================


def _make_depth(
    best_bid: Decimal = Decimal("60000.00"),
    bid_qty: Decimal = Decimal("1.00"),
    best_ask: Decimal = Decimal("60001.00"),
    ask_qty: Decimal = Decimal("1.00"),
    symbol: str = "BTCUSDT",
) -> OrderBookDepthSnapshot:
    """Helper to build depth snapshot."""
    return OrderBookDepthSnapshot(
        symbol=symbol,
        bids=(OrderBookLevel(price=best_bid, quantity=bid_qty),),
        asks=(OrderBookLevel(price=best_ask, quantity=ask_qty),),
        last_update_id=1,
        prev_last_update_id=0,
        event_time=datetime.now(UTC),
    )


def _make_candidate(
    cid: str = "cand-btcusdt-dcb-001",
    family: str = "donchian_channel_breakout",
    symbol: str = "BTCUSDT",
    lookback: int = 50,
    pos_frac: Decimal = Decimal("0.10"),
    stop_atr: Decimal = Decimal("2.0"),
    tp_atr: Decimal = Decimal("4.0"),
    long_exit: str = "donchian_breakout < 0.0",
    short_exit: str = "donchian_breakout > 0.0",
    seed: int = 42,
) -> CreatorCandidateArtifact:
    """Construct valid test candidate artifact."""
    strat = StrategySpec(
        dsl_version=2,
        strategy_id=cid,
        family=family,  # type: ignore[arg-type]
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="donchian_breakout", lookback=lookback, shift=1),),
        entry=EntryExit(long="donchian_breakout > 0.0", short="donchian_breakout < 0.0"),
        exit=EntryExit(long=long_exit, short=short_exit),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=pos_frac,
            stop_atr_multiplier=stop_atr,
            take_profit_atr_multiplier=tp_atr,
            trailing_atr_multiplier=Decimal("1.5"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=cid,
        strategy=strat,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="stress-test",
        research_seed=seed,
        created_at=datetime.now(UTC),
    )


# =====================================================================
# Challenge 1: Parameter Mutation Robustness & Seed Determinism
# =====================================================================


class TestChallenge1ParameterMutationAndDeterminism:
    """Challenge 1: Stress-test parameter mutation engine, extreme seeds, and boundary inputs."""

    @pytest.mark.parametrize(
        "extreme_seed",
        [0, 1, 42, 2**31 - 1, 2**63 - 1],
    )
    def test_extreme_non_negative_seed_initialization_and_mutation(self, extreme_seed: int) -> None:
        """Verify mutation engine operates cleanly under boundary and extreme non-negative seeds."""
        engine = MicrostructureMutationEngine(seed=extreme_seed)
        cand = _make_candidate(cid="cand-btcusdt-dcb-base", seed=extreme_seed)

        # Mutate across generations
        mutated_dcb = engine.mutate_donchian_breakout(cand, generation=1, variant_index=1)
        assert mutated_dcb.candidate_id.startswith("cand-btcusdt-dcb-g1v1")
        assert mutated_dcb.strategy.risk is not None
        assert Decimal("0.05") <= mutated_dcb.strategy.risk.position_fraction <= Decimal("0.20")
        assert Decimal("1.0") <= mutated_dcb.strategy.risk.stop_atr_multiplier <= Decimal("3.5")

        # MSM candidate creation under extreme seed
        msm = engine.create_base_microstructure_momentum_candidate("BTCUSDT", seed=extreme_seed)
        assert msm.strategy.family == "microstructure_momentum"
        assert msm.strategy.dsl_version == 2
        assert msm.strategy.risk is not None
        assert msm.strategy.risk.position_fraction == Decimal("0.10")

    def test_negative_seed_vulnerability(self) -> None:
        """Vulnerability V1: MicrostructureMutationEngine crashes on negative seed mutation.

        The contract for CreatorCandidateArtifact strictly enforces research_seed >= 0.
        When MicrostructureMutationEngine is initialized with negative seed, it does not
        preflight validate seed >= 0, causing late unhandled DataQualityError during mutation.
        """
        # Base candidate creation with negative seed fails in artifact builder:
        with pytest.raises(DataQualityError, match="research_seed"):
            _make_candidate(cid="cand-btcusdt-neg", seed=-1)

        # MutationEngine initialized with negative seed:
        engine = MicrostructureMutationEngine(seed=-5000)
        valid_cand = _make_candidate(cid="cand-btcusdt-valid", seed=42)

        # When generation=1, variant=1, research_seed = -5000 + 1000 + 1 = -3999 < 0
        # Crashes with DataQualityError instead of raising a clean domain configuration error
        with pytest.raises(DataQualityError, match="research_seed"):
            engine.mutate_donchian_breakout(valid_cand, generation=1, variant_index=1)

    def test_exact_seed_determinism_reproducibility(self) -> None:
        """Verify identical seed produces 100% byte-for-byte identical mutations."""
        cand = _make_candidate(cid="cand-btcusdt-dcb-base", seed=12345)

        engine_a = MicrostructureMutationEngine(seed=12345)
        mutations_a = [
            engine_a.mutate_donchian_breakout(cand, generation=g, variant_index=v)
            for g in range(1, 4)
            for v in range(1, 4)
        ]

        engine_b = MicrostructureMutationEngine(seed=12345)
        mutations_b = [
            engine_b.mutate_donchian_breakout(cand, generation=g, variant_index=v)
            for g in range(1, 4)
            for v in range(1, 4)
        ]

        for ma, mb in zip(mutations_a, mutations_b, strict=True):
            assert ma.candidate_id == mb.candidate_id
            assert ma.artifact_hash == mb.artifact_hash
            assert ma.strategy.risk.position_fraction == mb.strategy.risk.position_fraction  # type: ignore[union-attr]
            assert ma.strategy.risk.stop_atr_multiplier == mb.strategy.risk.stop_atr_multiplier  # type: ignore[union-attr]
            assert ma.strategy.features[0].lookback == mb.strategy.features[0].lookback

    def test_distinct_seeds_produce_different_variations(self) -> None:
        """Verify different seeds explore different parameter spaces."""
        cand = _make_candidate(cid="cand-btcusdt-dcb-base")
        engine_1 = MicrostructureMutationEngine(seed=101)
        engine_2 = MicrostructureMutationEngine(seed=999)

        m1 = engine_1.mutate_donchian_breakout(cand, generation=1, variant_index=1)
        m2 = engine_2.mutate_donchian_breakout(cand, generation=1, variant_index=1)

        diff = (
            m1.strategy.features[0].lookback != m2.strategy.features[0].lookback
            or m1.strategy.risk.stop_atr_multiplier != m2.strategy.risk.stop_atr_multiplier  # type: ignore[union-attr]
            or m1.strategy.risk.take_profit_atr_multiplier  # type: ignore[union-attr]
            != m2.strategy.risk.take_profit_atr_multiplier  # type: ignore[union-attr]
        )
        assert diff, "Different seeds should produce different parameter mutations"

    def test_donchian_channel_boundary_lookbacks(self) -> None:
        """Stress-test Donchian bounds with L = 10, L = 100, and minimum boundary data."""
        # L = 10
        prices_11 = [Decimal(str(100 + i)) for i in range(11)]
        up_10, low_10 = compute_donchian_channel(prices_11, lookback=10, shift=1)
        assert up_10 == Decimal("109")
        assert low_10 == Decimal("100")

        # L = 100
        prices_101 = [Decimal(str(1000 + (i % 17))) for i in range(101)]
        up_100, low_100 = compute_donchian_channel(prices_101, lookback=100, shift=1)
        assert up_100 == Decimal("1016")
        assert low_100 == Decimal("1000")

        # Boundary: insufficient prices should raise ValueError
        with pytest.raises(ValueError, match="Insufficient prices"):
            compute_donchian_channel(prices_101[:50], lookback=100, shift=1)

    def test_rolling_volatility_zero_and_boundary_conditions(self) -> None:
        """Verify rolling volatility handles zero volatility, constant prices, and small series."""
        # Insufficient data
        assert compute_rolling_volatility([Decimal("100")], lookback=20) == Decimal("0.0")

        # Zero volatility (constant prices)
        constant_prices = [Decimal("50000.00")] * 30
        vol_zero = compute_rolling_volatility(constant_prices, lookback=20)
        assert vol_zero == Decimal("0.0"), "Constant price series must yield 0.0 volatility"

        # Active volatility
        alternating = [Decimal("50000") if i % 2 == 0 else Decimal("51000") for i in range(30)]
        vol_active = compute_rolling_volatility(alternating, lookback=20)
        assert vol_active > Decimal("0.0")

    def test_order_flow_imbalance_empty_and_degenerate_books(self) -> None:
        """Verify OFI computation safely handles empty bids/asks and identical books."""
        empty_bids = OrderBookDepthSnapshot(
            symbol="BTCUSDT",
            bids=(),
            asks=(OrderBookLevel(price=Decimal("60001"), quantity=Decimal("1")),),
            last_update_id=1,
            prev_last_update_id=0,
            event_time=datetime.now(UTC),
        )
        full_book = _make_depth()
        # Empty book returns 0.0
        assert compute_order_flow_imbalance(empty_bids, full_book) == Decimal("0.0")
        assert compute_order_flow_imbalance(full_book, empty_bids) == Decimal("0.0")

        # Identical books: delta_q_b = 0, delta_q_a = 0 -> OFI = 0.0
        assert compute_order_flow_imbalance(full_book, full_book) == Decimal("0.0")

    def test_ofi_zscore_degenerate_and_extreme_inputs(self) -> None:
        """Verify OFI z-score calculation handles empty, constant, and extreme series."""
        # Empty or single element
        assert compute_ofi_zscore([]) == 0.0
        assert compute_ofi_zscore([Decimal("5.0")]) == 0.0

        # Constant series (standard deviation < 1e-12)
        constant_series = [Decimal("10.0")] * 50
        assert compute_ofi_zscore(constant_series) == 0.0

        # Extreme values
        extreme_series = [Decimal("1e12")] * 25 + [Decimal("2e12")]
        z = compute_ofi_zscore(extreme_series)
        assert isinstance(z, float)
        assert not (z != z)  # not NaN

    def test_trade_flow_momentum_boundary_cases(self) -> None:
        """Verify trade flow momentum handles empty trades, all buy, all sell."""
        # Empty trades
        assert compute_trade_flow_momentum([]) == 0.0

        now = datetime.now(UTC)

        # All taker buys (is_buyer_maker=False)
        buy_trades = [
            AggregateTrade(
                symbol="BTCUSDT",
                aggregate_trade_id=i,
                price=Decimal("60000"),
                quantity=Decimal("1.0"),
                first_trade_id=i,
                last_trade_id=i,
                trade_time=now - timedelta(seconds=i),
                is_buyer_maker=False,
            )
            for i in range(5)
        ]
        assert compute_trade_flow_momentum(buy_trades, reference_time=now) == 1.0

        # All taker sells (is_buyer_maker=True)
        sell_trades = [
            AggregateTrade(
                symbol="BTCUSDT",
                aggregate_trade_id=i,
                price=Decimal("60000"),
                quantity=Decimal("1.0"),
                first_trade_id=i,
                last_trade_id=i,
                trade_time=now - timedelta(seconds=i),
                is_buyer_maker=True,
            )
            for i in range(5)
        ]
        assert compute_trade_flow_momentum(sell_trades, reference_time=now) == -1.0

    def test_hawkes_spectral_radius_veto_boundaries(self) -> None:
        """Verify Hawkes spectral radius veto boundary at rho = 0.85."""
        assert compute_hawkes_spectral_radius_gate(0.0, ceiling=0.85) is True
        assert compute_hawkes_spectral_radius_gate(0.8499, ceiling=0.85) is True
        assert compute_hawkes_spectral_radius_gate(0.8500, ceiling=0.85) is False
        assert compute_hawkes_spectral_radius_gate(0.8501, ceiling=0.85) is False
        assert compute_hawkes_spectral_radius_gate(1.0000, ceiling=0.85) is False

    def test_microstructure_momentum_signal_veto_and_thresholds(self) -> None:
        """Verify MSM signal logic, thresholds, and supercritical Hawkes suppression."""
        # Long entry
        sig_long = compute_microstructure_momentum_signal(
            z_ofi=2.0, momentum=0.20, hawkes_rho=0.50, z_entry=1.5, mom_threshold=0.15
        )
        assert sig_long == 1.0

        # Hawkes supercritical veto suppresses long entry
        sig_vetoed = compute_microstructure_momentum_signal(
            z_ofi=2.0, momentum=0.20, hawkes_rho=0.86, z_entry=1.5, mom_threshold=0.15
        )
        assert sig_vetoed == 0.0

        # Short entry
        sig_short = compute_microstructure_momentum_signal(
            z_ofi=-2.0, momentum=-0.20, hawkes_rho=0.50, z_entry=1.5, mom_threshold=0.15
        )
        assert sig_short == -1.0


# =====================================================================
# Challenge 2: Qualification Gate Stress
# =====================================================================


class TestChallenge2QualificationGateStress:
    """Challenge 2: Adversarially stress 5 qualification gates at strict threshold boundaries."""

    @pytest.fixture
    def evaluator(self) -> ContinuousOOSGateEvaluator:
        return ContinuousOOSGateEvaluator()

    @pytest.fixture
    def baseline_candidate(self) -> CreatorCandidateArtifact:
        return _make_candidate(cid="cand-btcusdt-stress-gate")

    def test_gate1_return_boundary_and_quantization_leak_empirical_observation(
        self, evaluator: ContinuousOOSGateEvaluator, baseline_candidate: CreatorCandidateArtifact
    ) -> None:
        """Verify Gate 1 (avg_return >= 0.0%).

        EMPIRICAL OBSERVATION (Vulnerability V2):
        `avg_return_pct.quantize(Decimal('0.0001'))` rounds return = -0.00001% to
        Decimal('-0.0000'). In Python, `Decimal('-0.0000') >= Decimal('0.0')` is True!
        Therefore, an infinitesimal loss (-0.00001%) leaks through the gate and PASSES!
        However, a resolvable negative return of -0.0001% (-0.0001% <= Decimal('0.0001'))
        quantizes to Decimal('-0.0001') and is strictly REJECTED.
        """
        trades = [{"pnl_usdt": Decimal("1.0"), "is_win": True}] * 5

        # Return = -0.00001%: Quantization leak observation
        eq_curve_sub_tick = [Decimal("100.0000"), Decimal("99.99999")]
        rec_sub = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades,
            equity_curve=eq_curve_sub_tick,
            window_count=1,
        )
        # Because of .quantize(Decimal("0.0001")), Decimal("-0.0000") >= 0.0 is True:
        assert rec_sub.details.avg_return_pct == Decimal("-0.0000")
        assert rec_sub.gates_passed["avg_return"] is True  # EMPIRICAL LEAK IDENTIFIED

        # Return = -0.0001%: resolvable negative return is strictly REJECTED
        eq_curve_fail = [Decimal("100.0000"), Decimal("99.9999")]
        rec_fail = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades,
            equity_curve=eq_curve_fail,
            window_count=1,
        )
        assert rec_fail.details.avg_return_pct == Decimal("-0.0001")
        assert rec_fail.gates_passed["avg_return"] is False
        assert rec_fail.qualified is False

        # Return = 0.0000% -> MUST PASS
        eq_curve_pass = [Decimal("100.0000"), Decimal("100.0000")]
        rec_pass = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades,
            equity_curve=eq_curve_pass,
            window_count=1,
        )
        assert rec_pass.gates_passed["avg_return"] is True

        # Return = +0.0001% -> MUST PASS
        eq_curve_pos = [Decimal("100.0000"), Decimal("100.0001")]
        rec_pos = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades,
            equity_curve=eq_curve_pos,
            window_count=1,
        )
        assert rec_pos.gates_passed["avg_return"] is True

    def test_gate2_drawdown_boundary(
        self, evaluator: ContinuousOOSGateEvaluator, baseline_candidate: CreatorCandidateArtifact
    ) -> None:
        """Test Gate 2 (worst_drawdown <= 15.0%): strict rejection of drawdown > 15.0%."""
        trades = [{"pnl_usdt": Decimal("0.5"), "is_win": True}] * 5

        # Peak 100 -> Trough 84.9999 (drawdown = 15.0001%) -> MUST FAIL
        eq_curve_fail = [Decimal("100.0000"), Decimal("84.9999"), Decimal("100.0000")]
        rec_fail = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades,
            equity_curve=eq_curve_fail,
            window_count=1,
        )
        assert rec_fail.gates_passed["worst_drawdown"] is False
        assert rec_fail.qualified is False

        # Peak 100 -> Trough 85.0000 (drawdown = 15.0000%) -> MUST PASS
        eq_curve_exact = [Decimal("100.0000"), Decimal("85.0000"), Decimal("100.0000")]
        rec_exact = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades,
            equity_curve=eq_curve_exact,
            window_count=1,
        )
        assert rec_exact.gates_passed["worst_drawdown"] is True

        # Peak 100 -> Trough 85.0001 (drawdown = 14.9999%) -> MUST PASS
        eq_curve_safe = [Decimal("100.0000"), Decimal("85.0001"), Decimal("100.0000")]
        rec_safe = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades,
            equity_curve=eq_curve_safe,
            window_count=1,
        )
        assert rec_safe.gates_passed["worst_drawdown"] is True

    def test_gate3_profit_factor_boundary(
        self, evaluator: ContinuousOOSGateEvaluator, baseline_candidate: CreatorCandidateArtifact
    ) -> None:
        """Test Gate 3 (profit_factor >= 1.05): strict rejection when PF = 1.0499."""
        eq_curve = [Decimal("100.00"), Decimal("102.00")]

        # PF = 1.0499 -> MUST FAIL
        # Gross profit = 10.499, gross loss = 10.000, 3 trades with pnl=0.0 -> PF = 1.0499
        trades_fail = [
            {"pnl_usdt": Decimal("10.499"), "is_win": True},
            {"pnl_usdt": Decimal("-10.000"), "is_win": False},
            {"pnl_usdt": Decimal("0.000"), "is_win": False},
            {"pnl_usdt": Decimal("0.000"), "is_win": False},
            {"pnl_usdt": Decimal("0.000"), "is_win": False},
        ]

        rec_fail = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades_fail,
            equity_curve=eq_curve,
            window_count=1,
        )
        assert rec_fail.details.profit_factor == Decimal("1.0499")
        assert rec_fail.gates_passed["profit_factor"] is False
        assert rec_fail.qualified is False

        # PF = 1.0500 -> MUST PASS
        trades_pass = [
            {"pnl_usdt": Decimal("10.500"), "is_win": True},
            {"pnl_usdt": Decimal("-10.000"), "is_win": False},
            {"pnl_usdt": Decimal("0.000"), "is_win": False},
            {"pnl_usdt": Decimal("0.000"), "is_win": False},
            {"pnl_usdt": Decimal("0.000"), "is_win": False},
        ]

        rec_pass = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=trades_pass,
            equity_curve=eq_curve,
            window_count=1,
        )
        assert rec_pass.details.profit_factor == Decimal("1.0500")
        assert rec_pass.gates_passed["profit_factor"] is True

    def test_gate4_trade_count_and_window_boundary(
        self, evaluator: ContinuousOOSGateEvaluator, baseline_candidate: CreatorCandidateArtifact
    ) -> None:
        """Test Gate 4 (min trade count >= 5 in >= 1 window): strict rejection when trades < 5."""
        eq_curve = [Decimal("100.00"), Decimal("105.00")]
        four_trades = [{"pnl_usdt": Decimal("1.25"), "is_win": True}] * 4
        five_trades = [{"pnl_usdt": Decimal("1.00"), "is_win": True}] * 5

        # Trade count = 4, window = 1 -> MUST FAIL
        rec_4 = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=four_trades,
            equity_curve=eq_curve,
            window_count=1,
        )
        assert rec_4.gates_passed["trade_count"] is False
        assert rec_4.qualified is False

        # Trade count = 5, window = 0 -> MUST FAIL
        rec_0_win = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=five_trades,
            equity_curve=eq_curve,
            window_count=0,
        )
        assert rec_0_win.gates_passed["trade_count"] is False
        assert rec_0_win.qualified is False

        # Trade count = 5, window = 1 -> MUST PASS
        rec_5 = evaluator.evaluate_candidate(
            candidate=baseline_candidate,
            simulation_trades=five_trades,
            equity_curve=eq_curve,
            window_count=1,
        )
        assert rec_5.gates_passed["trade_count"] is True

    def test_gate5_microstructure_resilience_rejection_on_excess_risk(
        self, evaluator: ContinuousOOSGateEvaluator
    ) -> None:
        """Test Gate 5: Candidate with reckless risk settings is strictly rejected."""
        # Risk settings: position fraction 0.50 (50 USDT notional), stop ATR 20.0 (20% stop)
        # Loss under crash = (50 * 0.20) + fees = 10.04 USDT > 7.00 USDT loss budget!
        reckless_cand = _make_candidate(
            cid="cand-reckless-001",
            pos_frac=Decimal("0.50"),
            stop_atr=Decimal("20.0"),
        )
        trades = [{"pnl_usdt": Decimal("1.0"), "is_win": True}] * 5
        eq_curve = [Decimal("100.00"), Decimal("105.00")]

        rec = evaluator.evaluate_candidate(
            candidate=reckless_cand,
            simulation_trades=trades,
            equity_curve=eq_curve,
            window_count=1,
        )
        assert rec.gates_passed["microstructure_resilience"] is False
        assert rec.qualified is False
        assert rec.details.flash_crash_loss_usdt > Decimal("7.00")
        assert rec.details.flash_crash_survived is False

    def test_candidate_pruning_and_viable_filtering(
        self, evaluator: ContinuousOOSGateEvaluator
    ) -> None:
        """Verify pruning algorithm excludes candidates failing ANY gate and retains top viable."""
        cand_pass = _make_candidate(cid="cand-pass-001")
        cand_fail_ret = _make_candidate(cid="cand-fail-ret")
        cand_fail_dd = _make_candidate(cid="cand-fail-dd")
        cand_fail_pf = _make_candidate(cid="cand-fail-pf")
        cand_fail_trades = _make_candidate(cid="cand-fail-trades")

        trades_ok = [{"pnl_usdt": Decimal("1.0"), "is_win": True}] * 6
        eq_ok = [Decimal("100.00"), Decimal("106.00")]

        records: dict[str, Phase298OOSGateRecord] = {
            "cand-pass-001": evaluator.evaluate_candidate(
                cand_pass, trades_ok, eq_ok, window_count=1
            ),
            "cand-fail-ret": evaluator.evaluate_candidate(
                cand_fail_ret, trades_ok, [Decimal("100.00"), Decimal("95.00")], window_count=1
            ),
            "cand-fail-dd": evaluator.evaluate_candidate(
                cand_fail_dd,
                trades_ok,
                [Decimal("100.00"), Decimal("80.00"), Decimal("102.00")],
                window_count=1,
            ),
            "cand-fail-pf": evaluator.evaluate_candidate(
                cand_fail_pf,
                [
                    {"pnl_usdt": Decimal("1.0"), "is_win": True},
                    {"pnl_usdt": Decimal("-2.0"), "is_win": False},
                ]
                * 3,
                eq_ok,
                window_count=1,
            ),
            "cand-fail-trades": evaluator.evaluate_candidate(
                cand_fail_trades, trades_ok[:3], eq_ok, window_count=1
            ),
        }

        viable_ids = evaluator.filter_viable_candidates(records)
        assert viable_ids == ["cand-pass-001"], (
            f"Only passing candidate should be viable, got {viable_ids}"
        )

        pruned = evaluator.prune_candidates(
            [cand_pass, cand_fail_ret, cand_fail_dd, cand_fail_pf, cand_fail_trades],
            gate_records=records,
            top_k=1,
        )
        assert len(pruned) == 1
        assert pruned[0].candidate_id == "cand-pass-001"


# =====================================================================
# Challenge 3: Flash Crash & Spread Shock Microstructure Invariants
# =====================================================================


class TestChallenge3MicrostructureInvariants:
    """Challenge 3: Verify capital survival, loss <= 7.00 USDT, and zero drift under shocks."""

    @pytest.fixture
    def evaluator(self) -> ContinuousOOSGateEvaluator:
        return ContinuousOOSGateEvaluator()

    @pytest.mark.parametrize(
        "pos_fraction,stop_atr",
        [
            (Decimal("0.05"), Decimal("1.5")),
            (Decimal("0.10"), Decimal("2.0")),
            (Decimal("0.15"), Decimal("2.5")),
            (Decimal("0.20"), Decimal("3.0")),
        ],
    )
    def test_solvency_and_loss_budget_across_compliant_risk_profiles(
        self,
        evaluator: ContinuousOOSGateEvaluator,
        pos_fraction: Decimal,
        stop_atr: Decimal,
    ) -> None:
        """Verify compliant candidates survive flash crash and spread shock within budget."""
        cid_slug = f"cand-risk-p{int(pos_fraction * 100)}-s{int(stop_atr * 10)}"
        cand = _make_candidate(
            cid=cid_slug,
            pos_frac=pos_fraction,
            stop_atr=stop_atr,
        )

        fc_surv, ss_surv, fc_loss, ss_loss, z_drift, drift_val = (
            evaluator.evaluate_microstructure_resilience(cand)
        )

        # 1. Loss budget invariant
        assert fc_surv is True, f"Flash crash failed for {pos_fraction}, {stop_atr}: loss={fc_loss}"
        assert ss_surv is True, (
            f"Spread shock failed for {pos_fraction}, {stop_atr}: loss={ss_loss}"
        )
        assert fc_loss <= Decimal("7.00"), f"Flash crash loss {fc_loss} exceeded 7.00 USDT"
        assert ss_loss <= Decimal("7.00"), f"Spread shock loss {ss_loss} exceeded 7.00 USDT"

        # 2. Terminal equity strictly positive
        starting_eq = Decimal("100.00")
        assert starting_eq - fc_loss > Decimal("0.00")
        assert starting_eq - ss_loss > Decimal("0.00")

        # 3. Exact double-entry zero-drift balance reconciliation
        assert z_drift is True
        assert drift_val < DOUBLE_ENTRY_MAX_DRIFT
        assert drift_val == Decimal("0.00")

    def test_monte_carlo_random_shocks_zero_drift_reconciliation(
        self, evaluator: ContinuousOOSGateEvaluator
    ) -> None:
        """Adversarially simulate 1,000 shocks and verify exact zero balance drift."""
        cand = _make_candidate(cid="cand-monte-carlo-shock")

        for i in range(1000):
            # Perturb starting equity between 50.00 and 500.00 USDT
            starting_equity = Decimal(str(50 + (i % 450)))
            _, _, fc_loss, ss_loss, z_drift, drift_val = (
                evaluator.evaluate_microstructure_resilience(
                    candidate=cand,
                    starting_equity=starting_equity,
                )
            )

            assert z_drift is True, f"Iteration {i} failed zero-drift check"
            assert drift_val < DOUBLE_ENTRY_MAX_DRIFT
            assert drift_val == Decimal("0.00")


# =====================================================================
# Challenge 4: Open Trade Immutability Under Hot-Reload
# =====================================================================


class TestChallenge4OpenTradeImmutabilityUnderHotReload:
    """Challenge 4: Verify open position exit rules remain strictly unmutated."""

    def test_active_trade_exit_rules_retained_across_hot_reload(self, tmp_path: Path) -> None:
        """Hot-reload Candidate B; verify trade under Candidate A retains original exit rules."""
        manifest_path = tmp_path / "candidate_registry.json"
        candidates_dir = tmp_path / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)

        # 1. Candidate A: DonchianBreakout with exit rule `donchian_breakout < 0.0`
        cand_a = _make_candidate(
            cid="cand-btcusdt-dcb-002",
            family="donchian_channel_breakout",
            symbol="BTCUSDT",
            long_exit="donchian_breakout < 0.0",
            short_exit="donchian_breakout > 0.0",
        )
        art_path_a = candidates_dir / f"{cand_a.candidate_id}.json"
        write_creator_candidate_artifact(art_path_a, cand_a)

        # Publish Manifest Version 2
        entry_a = CandidateManifestEntry(
            candidate_id=cand_a.candidate_id,
            candidate_artifact_hash=cand_a.artifact_hash,
            artifact_path=str(art_path_a),
            qualification_hash="1" * 64,
            admitted_at=datetime.now(UTC).isoformat(),
        )
        manifest_v2 = build_candidate_registry_manifest(
            symbols={"BTCUSDT": entry_a},
            registry_version=2,
            updated_at=datetime.now(UTC),
        )
        write_candidate_registry(manifest_path, manifest_v2)

        # 2. Mock live paper engine with active trade under Candidate A
        class MockEngine:
            def __init__(self) -> None:
                self.candidates: dict[str, CreatorCandidateArtifact] = {"BTCUSDT": cand_a}
                self.qualified_symbols: tuple[str, ...] = ("BTCUSDT",)
                self.admission_decisions: dict[str, Any] = {}
                self.admitted_history: list[tuple[CreatorCandidateArtifact, str]] = []

            def admit_candidate(
                self,
                candidate: CreatorCandidateArtifact,
                qualification_hash: str | None = None,
                require_flat: bool = False,
            ) -> None:
                self.admitted_history.append((candidate, qualification_hash or ""))
                self.candidates[candidate.strategy.universe.symbols[0]] = candidate

        engine = MockEngine()

        # Simulate Active Trade opened under Candidate A
        # The trade directly binds `trade.candidate = cand_a`
        open_time = datetime.now(UTC)
        trade = ActivePaperTrade(
            trade_id="tr-active-001",
            candidate_id=cand_a.candidate_id,
            candidate_artifact_hash=cand_a.artifact_hash,
            symbol="BTCUSDT",
            side="LONG",
            open_entry=None,  # type: ignore[arg-type]
            quantity=Decimal("0.01"),
            base_margin=Decimal("10.00"),
            leverage=Decimal("1.0"),
            watermark=Decimal("60000.00"),
            peak_pnl=Decimal("0.00"),
            stop_price=Decimal("58000.00"),
            target_price=Decimal("65000.00"),
            trailing_atr_multiplier=cand_a.strategy.risk.trailing_atr_multiplier,  # type: ignore[union-attr]
            current_atr=Decimal("500.00"),
            opened_at=open_time,
            candidate=cand_a,  # BOUND TO CANDIDATE A
        )

        reloader = CandidateRegistryHotReloader(
            manifest_path=manifest_path,
            engine=engine,
            base_dir=tmp_path,
        )

        # 3. Create Candidate B: MicrostructureMomentum with exit rule `ofi_zscore < 0.2`
        # Note: Candidate B has completely different exit rules than Candidate A!
        cand_b = _make_candidate(
            cid="cand-btcusdt-msm-001",
            family="microstructure_momentum",
            symbol="BTCUSDT",
            long_exit="ofi_zscore < 0.2",
            short_exit="ofi_zscore > -0.2",
        )
        art_path_b = candidates_dir / f"{cand_b.candidate_id}.json"
        write_creator_candidate_artifact(art_path_b, cand_b)

        # Publish Manifest Version 3 with Candidate B
        entry_b = CandidateManifestEntry(
            candidate_id=cand_b.candidate_id,
            candidate_artifact_hash=cand_b.artifact_hash,
            artifact_path=str(art_path_b),
            qualification_hash="2" * 64,
            admitted_at=datetime.now(UTC).isoformat(),
        )
        manifest_v3 = build_candidate_registry_manifest(
            symbols={"BTCUSDT": entry_b},
            registry_version=3,
            updated_at=datetime.now(UTC),
        )
        write_candidate_registry(manifest_path, manifest_v3)

        # 4. Trigger hot-reload
        reloaded = reloader.check_and_reload()
        assert reloaded is True, "Hot reload should succeed"
        assert engine.candidates["BTCUSDT"].candidate_id == "cand-btcusdt-msm-001"
        assert reloader.reload_count == 1

        # 5. VERIFY OPEN TRADE IMMUTABILITY:
        # The active trade MUST still reference Candidate A, not Candidate B!
        assert trade.candidate is not None
        assert trade.candidate.candidate_id == "cand-btcusdt-dcb-002"
        assert trade.candidate_id == "cand-btcusdt-dcb-002"
        assert trade.candidate.artifact_hash == cand_a.artifact_hash
        assert trade.candidate.strategy.exit.long == "donchian_breakout < 0.0"

        # 6. Test exit evaluation against candle row:
        # Scenario: ofi_zscore = 0.1 (would trigger Candidate B's exit: ofi_zscore < 0.2)
        # BUT donchian_breakout = 1.0 (does NOT trigger Candidate A's exit: donchian_breakout < 0.0)
        candle_row = pd.Series(
            {
                "donchian_breakout": 1.0,  # inside / above breakout: Candidate A should NOT exit
                "ofi_zscore": 0.1,  # Candidate B WOULD exit here
            }
        )

        # Evaluate exit using active trade's candidate exit rules:
        should_exit_trade = evaluate_strategy_exit(
            row=candle_row,
            side=trade.side,
            long_exit_expr=trade.candidate.strategy.exit.long,
            short_exit_expr=trade.candidate.strategy.exit.short,
        )
        assert should_exit_trade is False, (
            "Active trade MUST NOT exit under Candidate B's condition (ofi_zscore < 0.2); "
            "it must evaluate against Candidate A's condition (donchian_breakout < 0.0)."
        )

        # Scenario: donchian_breakout = -0.5 (Candidate A exit condition met)
        exit_row = pd.Series(
            {
                "donchian_breakout": -0.5,
                "ofi_zscore": 2.5,
            }
        )
        should_exit_trade_now = evaluate_strategy_exit(
            row=exit_row,
            side=trade.side,
            long_exit_expr=trade.candidate.strategy.exit.long,
            short_exit_expr=trade.candidate.strategy.exit.short,
        )
        assert should_exit_trade_now is True, (
            "Active trade MUST exit when its bound Candidate A condition is met."
        )

    def test_fail_closed_rejection_of_corrupt_or_tampered_manifest(self, tmp_path: Path) -> None:
        """Verify hot-reloader rejects corrupt JSON or tampered manifest fail-closed."""
        manifest_path = tmp_path / "candidate_registry.json"
        candidates_dir = tmp_path / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)

        cand_a = _make_candidate(cid="cand-btcusdt-safe")
        art_path_a = candidates_dir / f"{cand_a.candidate_id}.json"
        write_creator_candidate_artifact(art_path_a, cand_a)

        entry_a = CandidateManifestEntry(
            candidate_id=cand_a.candidate_id,
            candidate_artifact_hash=cand_a.artifact_hash,
            artifact_path=str(art_path_a),
            qualification_hash="1" * 64,
            admitted_at=datetime.now(UTC).isoformat(),
        )
        manifest_v2 = build_candidate_registry_manifest(
            symbols={"BTCUSDT": entry_a},
            registry_version=2,
            updated_at=datetime.now(UTC),
        )
        write_candidate_registry(manifest_path, manifest_v2)

        class MockEngine:
            def __init__(self) -> None:
                self.candidates = {"BTCUSDT": cand_a}

            def admit_candidate(self, *args: Any, **kwargs: Any) -> None:
                pass

        engine = MockEngine()
        reloader = CandidateRegistryHotReloader(manifest_path=manifest_path, engine=engine)

        # Initial clean reload
        assert reloader.check_and_reload() is True
        assert reloader.last_reload_status == "RELOADED"

        # Tamper: corrupt the file content with garbage
        manifest_path.write_text("CORRUPT_NOT_JSON{", encoding="utf-8")

        # Reload should fail closed and retain existing candidates
        res = reloader.check_and_reload()
        assert res is False
        assert reloader.last_reload_status == "FAILED_CORRUPT"
        assert engine.candidates["BTCUSDT"].candidate_id == "cand-btcusdt-safe"

        # Tamper: valid JSON but invalid registry_hash
        manifest_dict = manifest_v2.model_dump(mode="json")
        manifest_dict["registry_hash"] = "0" * 64  # deliberate mismatch
        manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")

        res_tamper = reloader.check_and_reload()
        assert res_tamper is False
        assert reloader.last_reload_status == "FAILED_HASH_MISMATCH"
        assert engine.candidates["BTCUSDT"].candidate_id == "cand-btcusdt-safe"
