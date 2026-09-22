"""Unit Test Suite for Phase 298: Strategy Mining & Microstructure Mutation Engine.

Covers:
1. Microstructure Feature Calculations (OFI, z-score, Momentum, Hawkes, Donchian, ATR, ADX)
2. MicrostructureMomentum (MSM) candidate formulation & contract validity
3. MicrostructureMutationEngine parameter mutation, bounds, deterministic seeding & genealogy
4. ContinuousOOSGateEvaluator 5 strict qualification gates (both passing and failing paths)
5. Candidate pruning and ranking behavior
6. Phase 297 Flash Crash (-20%) and Spread Shock (10.0%) Microstructure Resilience Gate
7. Mathematical double-entry zero-drift balance reconciliation (|drift| < 10^-15 USDT)
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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
    CandidateFamilyCode,
    ContinuousOOSGateEvaluator,
    DynamicStrategyMiner,
    MicrostructureMutationEngine,
    MutationType,
    compute_adx,
    compute_donchian_breakout_signal,
    compute_donchian_channel,
    compute_hawkes_spectral_radius_gate,
    compute_microstructure_momentum_signal,
    compute_ofi_zscore,
    compute_order_flow_imbalance,
    compute_rolling_volatility,
    compute_trade_flow_momentum,
    compute_wilder_atr,
)
from autonomous_futures.feed.stress_fault_injection import MarketFaultInjector
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)

# =====================================================================
# Fixtures & Helpers
# =====================================================================


def _make_depth_snapshot(
    symbol: str = "BTCUSDT",
    best_bid: Decimal = Decimal("60000.00"),
    bid_qty: Decimal = Decimal("1.5000"),
    best_ask: Decimal = Decimal("60001.00"),
    ask_qty: Decimal = Decimal("1.2000"),
    ts: datetime | None = None,
) -> OrderBookDepthSnapshot:
    """Construct a clean OrderBookDepthSnapshot."""
    t = ts or datetime.now(UTC)
    bids = (
        OrderBookLevel(price=best_bid, quantity=bid_qty),
        OrderBookLevel(price=best_bid - Decimal("10.00"), quantity=Decimal("2.0")),
    )
    asks = (
        OrderBookLevel(price=best_ask, quantity=ask_qty),
        OrderBookLevel(price=best_ask + Decimal("10.00"), quantity=Decimal("2.0")),
    )
    return OrderBookDepthSnapshot(
        symbol=symbol.upper(),
        bids=bids,
        asks=asks,
        last_update_id=100,
        prev_last_update_id=99,
        event_time=t,
    )


def _make_dummy_dcb_candidate(symbol: str = "BTCUSDT") -> CreatorCandidateArtifact:
    """Create a valid baseline DonchianBreakout candidate."""
    sym = symbol.upper()
    sym_lower = symbol.lower()
    cid = f"cand-{sym_lower}-dcb-001"
    now = datetime.now(UTC)

    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=cid,
        family="donchian_channel_breakout",
        universe=StrategyUniverse(
            symbols=(sym,),
            timeframe="15m",
            regime_context_timeframe="1h",
        ),
        features=(FeatureRef(name="donchian_breakout", lookback=50, shift=1),),
        entry=EntryExit(long="donchian_breakout > 0.0", short="donchian_breakout < 0.0"),
        exit=EntryExit(long="donchian_breakout < 0.0", short="donchian_breakout > 0.0"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("2.5"),
            take_profit_atr_multiplier=Decimal("5.0"),
            trailing_atr_multiplier=Decimal("2.0"),
        ),
    )

    return build_creator_candidate_artifact(
        candidate_id=cid,
        strategy=strategy,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="unit-test-run",
        research_seed=42,
        created_at=now,
    )


def _make_dummy_rgb_candidate(symbol: str = "SOLUSDT") -> CreatorCandidateArtifact:
    """Create a valid baseline RegimeVolatilityBreakout candidate."""
    sym = symbol.upper()
    sym_lower = symbol.lower()
    cid = f"cand-{sym_lower}-rgb-001"
    now = datetime.now(UTC)

    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=cid,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(sym,),
            timeframe="1h",
            regime_context_timeframe="4h",
        ),
        features=(
            FeatureRef(name="donchian_breakout", lookback=20, shift=1),
            FeatureRef(name="adx", lookback=14, shift=1),
        ),
        entry=EntryExit(
            long="donchian_breakout > 0.0 and adx > 25.0",
            short="donchian_breakout < 0.0 and adx > 25.0",
        ),
        exit=EntryExit(long="donchian_breakout < 0.0", short="donchian_breakout > 0.0"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("2.0"),
            take_profit_atr_multiplier=Decimal("4.0"),
            trailing_atr_multiplier=Decimal("1.5"),
        ),
    )

    return build_creator_candidate_artifact(
        candidate_id=cid,
        strategy=strategy,
        bundle_hash="c" * 64,
        dataset_registry_hash="d" * 64,
        creator_run_id="unit-test-run",
        research_seed=43,
        created_at=now,
    )


# =====================================================================
# 1. Microstructure Feature Calculations Tests
# =====================================================================


def test_order_flow_imbalance_calculation() -> None:
    """Verify Cont-Kukanov-Stoikov OFI calculation across orderbook transitions."""
    # Case 1: Best bid increases in price (strong buy flow)
    d0 = _make_depth_snapshot(best_bid=Decimal("60000.00"), bid_qty=Decimal("1.0"))
    d1 = _make_depth_snapshot(best_bid=Decimal("60001.00"), bid_qty=Decimal("2.0"))
    ofi = compute_order_flow_imbalance(d0, d1)
    # Δq_b = 2.0 (since p_curr > p_prev), Δq_a = 0 (same ask) -> OFI = 2.0
    assert ofi == Decimal("2.0")

    # Case 2: Best bid price stays equal, quantity decreases (cancelled bids or sold into)
    d2 = _make_depth_snapshot(best_bid=Decimal("60001.00"), bid_qty=Decimal("0.5"))
    ofi2 = compute_order_flow_imbalance(d1, d2)
    # Δq_b = 0.5 - 2.0 = -1.5 -> OFI = -1.5
    assert ofi2 == Decimal("-1.5")

    # Case 3: Best ask increases in price (ask moved up = buying through ask)
    d3 = _make_depth_snapshot(
        best_bid=Decimal("60001.00"),
        bid_qty=Decimal("0.5"),
        best_ask=Decimal("60003.00"),
        ask_qty=Decimal("1.5"),
    )
    ofi3 = compute_order_flow_imbalance(d2, d3)
    # Δq_a = -q_prev_a = -1.2, Δq_b = 0.5 - 0.5 = 0.0 -> OFI = 0 - (-1.2) = 1.2
    assert ofi3 == Decimal("1.2")

    # Case 4: Empty orderbook edge case
    empty_depth = OrderBookDepthSnapshot(
        symbol="BTCUSDT",
        bids=(),
        asks=(),
        last_update_id=1,
        event_time=datetime.now(UTC),
    )
    assert compute_order_flow_imbalance(empty_depth, d0) == Decimal("0.0")


def test_ofi_zscore_calculation() -> None:
    """Verify rolling z-score computation on OFI series."""
    # Constant sequence (zero variance) should return 0.0
    constant_series = [Decimal("1.5")] * 20
    assert compute_ofi_zscore(constant_series, window=10) == 0.0

    # Short sequence (< 2 items)
    assert compute_ofi_zscore([Decimal("1.0")], window=10) == 0.0

    # Dynamic sequence with known positive spike at end
    series = [Decimal(str(i)) for i in range(10)]  # 0 to 9
    z = compute_ofi_zscore(series, window=10)
    assert z > 1.0  # 9 is significantly above mean 4.5


def test_trade_flow_momentum() -> None:
    """Verify volume-weighted taker trade flow momentum."""
    t_now = datetime.now(UTC)

    # All taker buys (is_buyer_maker=False) -> momentum = +1.0
    trades_buy = [
        AggregateTrade(
            symbol="BTCUSDT",
            aggregate_trade_id=i,
            price=Decimal("60000"),
            quantity=Decimal("1.0"),
            first_trade_id=i,
            last_trade_id=i,
            trade_time=t_now,
            is_buyer_maker=False,
        )
        for i in range(5)
    ]
    assert compute_trade_flow_momentum(trades_buy, window_seconds=60.0) == 1.0

    # All taker sells (is_buyer_maker=True) -> momentum = -1.0
    trades_sell = [
        AggregateTrade(
            symbol="BTCUSDT",
            aggregate_trade_id=i,
            price=Decimal("60000"),
            quantity=Decimal("1.0"),
            first_trade_id=i,
            last_trade_id=i,
            trade_time=t_now,
            is_buyer_maker=True,
        )
        for i in range(5)
    ]
    assert compute_trade_flow_momentum(trades_sell, window_seconds=60.0) == -1.0

    # Balanced trades -> momentum = 0.0
    assert compute_trade_flow_momentum(trades_buy + trades_sell, window_seconds=60.0) == 0.0

    # Empty trade list -> 0.0
    assert compute_trade_flow_momentum([], window_seconds=60.0) == 0.0


def test_hawkes_spectral_radius_gate() -> None:
    """Verify Hawkes spectral radius gating passes below ceiling and vetoes at or above."""
    # Under ceiling (e.g. 0.85) -> passes
    assert compute_hawkes_spectral_radius_gate(0.50, ceiling=0.85) is True
    assert compute_hawkes_spectral_radius_gate(Decimal("0.84"), ceiling=Decimal("0.85")) is True

    # At or above ceiling -> vetoed
    assert compute_hawkes_spectral_radius_gate(0.85, ceiling=0.85) is False
    assert compute_hawkes_spectral_radius_gate(0.92, ceiling=0.85) is False
    assert compute_hawkes_spectral_radius_gate(1.05, ceiling=0.85) is False


def test_microstructure_momentum_signal() -> None:
    """Verify MicrostructureMomentum directional signals and veto interlocks."""
    # Long entry: z_ofi >= 1.5, mom >= 0.15, rho < 0.85 -> +1.0
    sig_long = compute_microstructure_momentum_signal(
        z_ofi=2.0,
        momentum=0.25,
        hawkes_rho=0.50,
        z_entry=1.5,
        mom_threshold=0.15,
        rho_veto=0.85,
    )
    assert sig_long == 1.0

    # Short entry: z_ofi <= -1.5, mom <= -0.15, rho < 0.85 -> -1.0
    sig_short = compute_microstructure_momentum_signal(
        z_ofi=-1.8,
        momentum=-0.20,
        hawkes_rho=0.50,
        z_entry=1.5,
        mom_threshold=0.15,
        rho_veto=0.85,
    )
    assert sig_short == -1.0

    # Neutral / sub-threshold -> 0.0
    sig_neutral = compute_microstructure_momentum_signal(
        z_ofi=0.5,
        momentum=0.05,
        hawkes_rho=0.50,
        z_entry=1.5,
        mom_threshold=0.15,
        rho_veto=0.85,
    )
    assert sig_neutral == 0.0

    # Hawkes supercritical veto suppresses ANY entry/position
    sig_vetoed = compute_microstructure_momentum_signal(
        z_ofi=3.5,
        momentum=0.80,
        hawkes_rho=0.95,  # Supercritical / elevated
        z_entry=1.5,
        mom_threshold=0.15,
        rho_veto=0.85,
    )
    assert sig_vetoed == 0.0

    # Long exit when z_ofi falls below exit threshold (e.g. 0.2)
    sig_exit_long = compute_microstructure_momentum_signal(
        z_ofi=0.1,
        momentum=0.0,
        hawkes_rho=0.50,
        z_exit=0.2,
        current_position_side="LONG",
    )
    assert sig_exit_long == 0.0


def test_donchian_channels_and_breakout() -> None:
    """Verify causal Donchian channel upper/lower computation and breakout signals."""
    prices = [Decimal(str(p)) for p in range(100, 150)]
    upper, lower = compute_donchian_channel(prices, lookback=20, shift=1)
    assert upper == Decimal("148")
    assert lower == Decimal("129")

    # Current price exceeds upper -> +1.0
    assert compute_donchian_breakout_signal(Decimal("150"), upper, lower) == 1.0
    # Current price below lower -> -1.0
    assert compute_donchian_breakout_signal(Decimal("120"), upper, lower) == -1.0
    # Inside channel -> 0.0
    assert compute_donchian_breakout_signal(Decimal("140"), upper, lower) == 0.0


def test_wilder_atr_and_adx() -> None:
    """Verify Wilder ATR and ADX calculation on synthetic series."""
    highs = [Decimal(str(100 + i * 2)) for i in range(40)]
    lows = [Decimal(str(98 + i * 2)) for i in range(40)]
    closes = [Decimal(str(99 + i * 2)) for i in range(40)]

    atr = compute_wilder_atr(highs, lows, closes, period=14)
    assert atr > Decimal("0.0")

    adx = compute_adx(highs, lows, closes, period=14)
    assert adx > 0.0


def test_rolling_volatility() -> None:
    """Verify rolling volatility calculation."""
    prices = [Decimal(str(100 + (i % 5))) for i in range(30)]
    vol = compute_rolling_volatility(prices, lookback=20)
    assert vol >= Decimal("0.0")


# =====================================================================
# 2. MSM Candidate Formulation & Contract Compatibility Tests
# =====================================================================


def test_create_base_microstructure_momentum_candidate() -> None:
    """Verify valid creation of MicrostructureMomentum (MSM) candidate."""
    engine = MicrostructureMutationEngine(seed=42)
    candidate = engine.create_base_microstructure_momentum_candidate("BTCUSDT")

    assert candidate.candidate_id == "cand-btcusdt-msm-001"
    assert candidate.strategy.family == "microstructure_momentum"
    assert candidate.strategy.universe.symbols == ("BTCUSDT",)
    assert candidate.strategy.dsl_version == 2
    assert candidate.strategy.risk is not None
    assert candidate.strategy.risk.position_fraction == Decimal("0.10")
    assert len(candidate.strategy.features) == 2
    assert candidate.strategy.features[0].name == "ofi_zscore"
    assert candidate.strategy.features[1].name == "trade_momentum"
    assert len(candidate.artifact_hash) == 64


def test_strategy_family_codes_mapping() -> None:
    """Verify mappings between candidate family codes and StrategyFamily literals."""
    assert CandidateFamilyCode.DCB == "DCB"
    assert CandidateFamilyCode.RGB == "RGB"
    assert CandidateFamilyCode.MSM == "MSM"


# =====================================================================
# 3. MicrostructureMutationEngine Tests
# =====================================================================


def test_mutation_engine_deterministic_seed() -> None:
    """Verify identical seeds produce identical candidate mutations and records."""
    engine1 = MicrostructureMutationEngine(seed=42)
    engine2 = MicrostructureMutationEngine(seed=42)

    base = _make_dummy_dcb_candidate("BTCUSDT")

    cand1 = engine1.mutate_donchian_breakout(base, generation=1, variant_index=1)
    cand2 = engine2.mutate_donchian_breakout(base, generation=1, variant_index=1)

    assert cand1.candidate_id == cand2.candidate_id
    assert cand1.artifact_hash == cand2.artifact_hash
    assert len(engine1.genealogy) == 1
    assert len(engine2.genealogy) == 1
    assert engine1.genealogy[0].mutated_parameters == engine2.genealogy[0].mutated_parameters


def test_mutate_donchian_breakout_boundaries() -> None:
    """Verify mutated DonchianBreakout parameters conform to strict valid search spaces."""
    engine = MicrostructureMutationEngine(seed=101)
    base = _make_dummy_dcb_candidate("BTCUSDT")

    mutated = engine.mutate_donchian_breakout(base, generation=1, variant_index=1)

    assert mutated.candidate_id == "cand-btcusdt-dcb-g1v1"
    assert mutated.strategy.family == "donchian_channel_breakout"

    # Verify lookback within [10, 100]
    lookback = mutated.strategy.features[0].lookback
    assert 10 <= lookback <= 100

    # Verify risk parameters within bounds
    risk = mutated.strategy.risk
    assert risk is not None
    assert Decimal("1.0") <= risk.stop_atr_multiplier <= Decimal("3.5")
    assert Decimal("2.5") <= risk.take_profit_atr_multiplier <= Decimal("6.0")
    assert Decimal("0.8") <= risk.trailing_atr_multiplier <= Decimal("2.5")
    assert Decimal("0.05") <= risk.position_fraction <= Decimal("0.20")


def test_mutate_regime_breakout_boundaries() -> None:
    """Verify mutated RegimeVolatilityBreakout parameters conform to search space."""
    engine = MicrostructureMutationEngine(seed=102)
    base = _make_dummy_rgb_candidate("SOLUSDT")

    mutated = engine.mutate_regime_breakout(base, generation=2, variant_index=1)

    assert mutated.candidate_id == "cand-solusdt-rgb-g2v1"
    assert mutated.strategy.family == "regime_gated_breakout"

    # Verify features
    feature_names = [f.name for f in mutated.strategy.features]
    assert "donchian_breakout" in feature_names
    assert "adx" in feature_names

    # Verify risk
    risk = mutated.strategy.risk
    assert risk is not None
    assert Decimal("1.2") <= risk.stop_atr_multiplier <= Decimal("3.0")
    assert Decimal("2.5") <= risk.take_profit_atr_multiplier <= Decimal("5.5")


def test_mutate_microstructure_momentum_boundaries() -> None:
    """Verify mutated MicrostructureMomentum parameters conform to search space."""
    engine = MicrostructureMutationEngine(seed=103)
    base_msm = engine.create_base_microstructure_momentum_candidate("ETHUSDT")

    mutated = engine.mutate_microstructure_momentum(base_msm, generation=1, variant_index=2)

    assert mutated.candidate_id == "cand-ethusdt-msm-g1v2"
    assert mutated.strategy.family == "microstructure_momentum"

    ofi_window = mutated.strategy.features[0].lookback
    assert 20 <= ofi_window <= 200

    risk = mutated.strategy.risk
    assert risk is not None
    assert Decimal("1.0") <= risk.stop_atr_multiplier <= Decimal("2.5")
    assert Decimal("2.0") <= risk.take_profit_atr_multiplier <= Decimal("4.5")
    assert Decimal("0.05") <= risk.position_fraction <= Decimal("0.15")


def test_mutation_genealogy_tracking() -> None:
    """Verify genealogy records correctly track parameter diffs and mutation lineage."""
    engine = MicrostructureMutationEngine(seed=200)
    base = _make_dummy_dcb_candidate("BTCUSDT")

    engine.mutate_donchian_breakout(base, generation=1, variant_index=1)
    engine.mutate_donchian_breakout(base, generation=1, variant_index=2)

    assert len(engine.genealogy) == 2
    rec = engine.genealogy[0]
    assert rec.parent_candidate_id == base.candidate_id
    assert rec.mutated_candidate_id == "cand-btcusdt-dcb-g1v1"
    assert rec.mutation_type == MutationType.PARAM_PERTURBATION
    assert "lookback" in rec.mutated_parameters
    assert "stop_atr_multiplier" in rec.mutated_parameters


def test_generate_candidate_variants_across_symbols() -> None:
    """Verify generating candidate variants across symbols produces all 3 families."""
    engine = MicrostructureMutationEngine(seed=42)
    baselines = {
        "BTCUSDT": _make_dummy_dcb_candidate("BTCUSDT"),
        "ETHUSDT": _make_dummy_dcb_candidate("ETHUSDT"),
        "SOLUSDT": _make_dummy_rgb_candidate("SOLUSDT"),
    }

    variants = engine.generate_candidate_variants(
        baseline_candidates=baselines,
        variants_per_symbol=3,
        generation=1,
    )

    assert len(variants) == 3
    assert len(variants["BTCUSDT"]) == 3
    assert len(variants["ETHUSDT"]) == 3
    assert len(variants["SOLUSDT"]) == 3

    # Ensure MSM was introduced via cross-family evolution
    all_cands = [c for clist in variants.values() for c in clist]
    families = {c.strategy.family for c in all_cands}
    assert "donchian_channel_breakout" in families
    assert "regime_gated_breakout" in families
    assert "microstructure_momentum" in families


# =====================================================================
# 4. ContinuousOOSGateEvaluator: 5 Strict Gates Tests
# =====================================================================


def test_gate_1_average_return() -> None:
    """Gate 1: Average Return >= 0.0%."""
    evaluator = ContinuousOOSGateEvaluator(min_avg_return_pct=Decimal("0.0"))
    cand = _make_dummy_dcb_candidate("BTCUSDT")

    # Positive return: 100 -> 105 (+5.0%) -> PASS
    trades = [{"pnl_usdt": Decimal("1.0")} for _ in range(5)]
    eq_curve_pos = [Decimal("100.00"), Decimal("105.00")]
    rec_pass = evaluator.evaluate_candidate(cand, trades, eq_curve_pos)
    assert rec_pass.gates_passed["avg_return"] is True

    # Negative return: 100 -> 98 (-2.0%) -> FAIL
    eq_curve_neg = [Decimal("100.00"), Decimal("98.00")]
    rec_fail = evaluator.evaluate_candidate(cand, trades, eq_curve_neg)
    assert rec_fail.gates_passed["avg_return"] is False
    assert rec_fail.qualified is False


def test_gate_2_worst_drawdown() -> None:
    """Gate 2: Worst Drawdown <= 15.0%."""
    evaluator = ContinuousOOSGateEvaluator(max_worst_drawdown_pct=Decimal("15.00"))
    cand = _make_dummy_dcb_candidate("BTCUSDT")
    trades = [{"pnl_usdt": Decimal("1.0")} for _ in range(5)]

    # Drawdown 10% (100 -> 110 -> 99 -> 110: (110-99)/110 = 10%) -> PASS
    eq_curve_pass = [
        Decimal("100.00"),
        Decimal("110.00"),
        Decimal("99.00"),
        Decimal("110.00"),
    ]
    rec_pass = evaluator.evaluate_candidate(cand, trades, eq_curve_pass)
    assert rec_pass.gates_passed["worst_drawdown"] is True

    # Drawdown 20% (100 -> 80) -> FAIL
    eq_curve_fail = [Decimal("100.00"), Decimal("80.00")]
    rec_fail = evaluator.evaluate_candidate(cand, trades, eq_curve_fail)
    assert rec_fail.gates_passed["worst_drawdown"] is False
    assert rec_fail.qualified is False


def test_gate_3_profit_factor() -> None:
    """Gate 3: Profit Factor >= 1.05."""
    evaluator = ContinuousOOSGateEvaluator(min_profit_factor=Decimal("1.05"))
    cand = _make_dummy_dcb_candidate("BTCUSDT")
    eq_curve = [Decimal("100.00"), Decimal("102.00")]

    # Gross profit 3.0, gross loss 2.0 -> PF = 1.50 -> PASS
    trades_pass = [
        {"pnl_usdt": Decimal("1.5")},
        {"pnl_usdt": Decimal("1.5")},
        {"pnl_usdt": Decimal("-1.0")},
        {"pnl_usdt": Decimal("-1.0")},
        {"pnl_usdt": Decimal("0.5")},
    ]
    rec_pass = evaluator.evaluate_candidate(cand, trades_pass, eq_curve)
    assert rec_pass.gates_passed["profit_factor"] is True

    # Gross profit 1.0, gross loss 2.0 -> PF = 0.50 -> FAIL
    trades_fail = [
        {"pnl_usdt": Decimal("1.0")},
        {"pnl_usdt": Decimal("-1.0")},
        {"pnl_usdt": Decimal("-1.0")},
        {"pnl_usdt": Decimal("0.0")},
        {"pnl_usdt": Decimal("0.0")},
    ]
    rec_fail = evaluator.evaluate_candidate(cand, trades_fail, eq_curve)
    assert rec_fail.gates_passed["profit_factor"] is False
    assert rec_fail.qualified is False


def test_gate_4_trade_count_and_window() -> None:
    """Gate 4: Minimum 5 trades across >= 1 window."""
    evaluator = ContinuousOOSGateEvaluator(min_trade_count=5, min_window_count=1)
    cand = _make_dummy_dcb_candidate("BTCUSDT")
    eq_curve = [Decimal("100.00"), Decimal("105.00")]

    # 5 trades -> PASS
    trades_5 = [{"pnl_usdt": Decimal("1.0")} for _ in range(5)]
    rec_pass = evaluator.evaluate_candidate(cand, trades_5, eq_curve, window_count=1)
    assert rec_pass.gates_passed["trade_count"] is True

    # 4 trades -> FAIL
    trades_4 = [{"pnl_usdt": Decimal("1.0")} for _ in range(4)]
    rec_fail = evaluator.evaluate_candidate(cand, trades_4, eq_curve, window_count=1)
    assert rec_fail.gates_passed["trade_count"] is False
    assert rec_fail.qualified is False


def test_gate_5_microstructure_resilience_and_drift() -> None:
    """Gate 5: Microstructure resilience vs flash crash (-20%) and spread shock (10.0%)."""
    evaluator = ContinuousOOSGateEvaluator(loss_budget_usdt=Decimal("7.00"))
    injector = MarketFaultInjector()

    # Normal risk: position_fraction 0.10, stop 2.0 -> passes with loss < 7.00 USDT
    cand_safe = _make_dummy_dcb_candidate("BTCUSDT")
    fc_surv, ss_surv, fc_loss, ss_loss, z_drift, drift = (
        evaluator.evaluate_microstructure_resilience(
            cand_safe, injector=injector, reference_price=Decimal("60000.00")
        )
    )

    assert fc_surv is True
    assert ss_surv is True
    assert fc_loss < Decimal("7.00")
    assert ss_loss < Decimal("7.00")
    assert z_drift is True
    assert drift < DOUBLE_ENTRY_MAX_DRIFT

    # High risk: position_fraction 0.45, stop 30.0 (wide unhedged drop) -> fails Gate 5
    cand_risky = copy.deepcopy(cand_safe)
    assert cand_risky.strategy.risk is not None
    cand_risky.strategy.risk.position_fraction = Decimal("0.45")
    cand_risky.strategy.risk.stop_atr_multiplier = Decimal("30.0")

    fc_surv_r, _, fc_loss_r, _, _, _ = evaluator.evaluate_microstructure_resilience(
        cand_risky, injector=injector
    )
    # 45.00 USDT notional * 20% drop = 9.00 USDT loss > 7.00 USDT budget
    assert fc_loss_r > Decimal("7.00")
    assert fc_surv_r is False


def test_evaluate_candidate_all_passed() -> None:
    """Verify candidate passing all 5 gates achieves qualified=True."""
    evaluator = ContinuousOOSGateEvaluator()
    cand = _make_dummy_dcb_candidate("BTCUSDT")

    # Construct compliant winning simulation
    trades = [
        {"pnl_usdt": Decimal("0.50")},
        {"pnl_usdt": Decimal("0.60")},
        {"pnl_usdt": Decimal("-0.20")},
        {"pnl_usdt": Decimal("0.40")},
        {"pnl_usdt": Decimal("0.30")},
        {"pnl_usdt": Decimal("-0.10")},
    ]
    eq_curve = [
        Decimal("100.00"),
        Decimal("100.50"),
        Decimal("101.10"),
        Decimal("100.90"),
        Decimal("101.30"),
        Decimal("101.60"),
        Decimal("101.50"),
    ]

    record = evaluator.evaluate_candidate(cand, trades, eq_curve)
    assert record.qualified is True
    assert all(record.gates_passed.values())


# =====================================================================
# 5. Candidate Pruning Tests
# =====================================================================


def test_candidate_pruning() -> None:
    """Verify candidate pruning filters unviable variants and ranks qualified candidates."""
    evaluator = ContinuousOOSGateEvaluator()

    cand1 = _make_dummy_dcb_candidate("BTCUSDT")
    cand2 = _make_dummy_rgb_candidate("SOLUSDT")

    # Evaluate cand1 as qualified
    trades_good = [{"pnl_usdt": Decimal("1.0")} for _ in range(6)]
    eq_good = [Decimal("100.00"), Decimal("106.00")]
    rec1 = evaluator.evaluate_candidate(cand1, trades_good, eq_good)
    assert rec1.qualified is True

    # Evaluate cand2 as unqualified (drawdown 20%)
    trades_bad = [{"pnl_usdt": Decimal("-1.0")} for _ in range(6)]
    eq_bad = [Decimal("100.00"), Decimal("80.00")]
    rec2 = evaluator.evaluate_candidate(cand2, trades_bad, eq_bad)
    assert rec2.qualified is False

    records = {cand1.candidate_id: rec1, cand2.candidate_id: rec2}

    # Prune candidates: only cand1 should remain
    pruned = evaluator.prune_candidates([cand1, cand2], records, top_k=1)
    assert len(pruned) == 1
    assert pruned[0].candidate_id == cand1.candidate_id

    # Filter viable candidate IDs
    viable_ids = evaluator.filter_viable_candidates(records)
    assert viable_ids == [cand1.candidate_id]

    # When no candidate qualifies, return empty list
    pruned_empty = evaluator.prune_candidates([cand2], {cand2.candidate_id: rec2}, top_k=1)
    assert pruned_empty == []


# =====================================================================
# 6. DynamicStrategyMiner Foundation Tests
# =====================================================================


def test_dynamic_strategy_miner_execution(tmp_path: Path) -> None:
    """Verify DynamicStrategyMiner executes hypothesis formulation and OOS evaluation."""
    miner = DynamicStrategyMiner(
        manifest_path=tmp_path / "registry.json",
        output_dir=tmp_path / "research",
        starting_capital=Decimal("100.00"),
        seed=42,
    )

    baselines = {
        "BTCUSDT": _make_dummy_dcb_candidate("BTCUSDT"),
        "SOLUSDT": _make_dummy_rgb_candidate("SOLUSDT"),
    }

    results = miner.execute_mining_cycle(baselines, variants_per_symbol=2, generation=1)

    assert len(results) == 4  # 2 symbols * 2 variants
    for cid, record in results.items():
        assert record.candidate_id == cid
        assert isinstance(record.qualified, bool)
        assert len(record.gates_passed) == 5
