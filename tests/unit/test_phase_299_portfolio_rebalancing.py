"""Unit Test Suite for Phase 299: Portfolio Risk Orchestration & Rebalancing Engine.

Comprehensive testing for:
1. DynamicRiskParityAllocator (R1):
   - Dynamic Hawkes risk-parity weights w_i* propto 1 / (sigma_i * (1 + lambda_i))
   - Variance floor sigma_min = 1e-4 enforcement
   - Aggregate exposure cap <= 60.00 USDT, per-asset margin ceiling <= 25.00 USDT
   - Minimum cash reserve floor >= 40.0% (>= 40.00 USDT on 100.00 USDT equity)
   - Water-filling redistribution and downscaling on lower equity levels
   - Rolling return volatility calculation
2. CrossAssetSpilloverGuard (R2):
   - Hawkes branching matrix and spectral radius rho calculation
   - Hazard triggers: rho_j >= 0.85, |OFI_j| > 0.80, flash crash drop <= -10.0%
   - Instantaneous capital de-allocation on coupled recipients (gamma_ij)
   - Supercritical runaway rho >= 1.0 emergency portfolio freeze
   - Severe flash crash (<= -15.0%) dispatch freeze
   - Recovery hysteresis requiring >= 3 consecutive clean ticks
3. Micro-Order Rebalancing Engine & Drift Detector (R3):
   - Hysteresis band drift detection (rebalance only when drift > 2.5%)
   - Child order slicing strictly <= 5.00 USDT cap
   - ROUND_DOWN step size precision for exchange filters
   - Downscaled chunk cap (<= 1.25 USDT) under elevated contagion
   - Fail-closed rejection of frozen symbols
   - Simulated passive matching with maker fees (0.02%)
4. Continuous Mathematical Double-Entry Zero-Drift Balance Governance (R4):
   - Assets = Cash + Allocated Margin + Unrealized PnL
   - Equity = Starting Equity + Realized PnL
   - Strict drift tolerance |Delta| < 10^-15 USDT across all cycles
   - DoubleEntryDriftError raised on synthetic drift
5. Verification Runner & Merkle DAG Provenance:
   - Tracks 1 to 4 deterministic execution
   - Cryptographic SHA-256 Merkle DAG linking Phase 298 parent hash.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Generator
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.canary_activation import DEFAULT_REFERENCE_PRICES
from autonomous_futures.feed.paper_execution import OrderSide
from autonomous_futures.feed.paper_ledger import (
    DOUBLE_ENTRY_MAX_DRIFT,
    PaperExecutionLedger,
)
from autonomous_futures.feed.portfolio_rebalancing import (
    DEFAULT_AGGREGATE_EXPOSURE_CAP_USDT,
    DEFAULT_MAX_CHUNK_CAP_USDT,
    DEFAULT_PER_ASSET_MARGIN_CEILING_USDT,
    DEFAULT_SYMBOLS,
    DEFAULT_VARIANCE_FLOOR_SIGMA_MIN,
    UPSTREAM_PHASE298_ROOT_HASH,
    CanaryPortfolioRebalancingRunner,
    ContagionLevel,
    CrossAssetContagionFrozenError,
    CrossAssetSpilloverGuard,
    DoubleEntryDriftError,
    DriftStatus,
    DynamicRiskParityAllocator,
    MicroRebalancingEngine,
    PortfolioDriftDetector,
    RebalanceRegime,
    RiskParityAllocationError,
    create_portfolio_snapshot,
    verify_double_entry_zero_drift,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def allocator() -> DynamicRiskParityAllocator:
    """Standard DynamicRiskParityAllocator instance."""
    return DynamicRiskParityAllocator()


@pytest.fixture
def guard() -> CrossAssetSpilloverGuard:
    """Standard CrossAssetSpilloverGuard instance."""
    return CrossAssetSpilloverGuard()


@pytest.fixture
def drift_detector() -> PortfolioDriftDetector:
    """Standard PortfolioDriftDetector instance with 2.5% hysteresis."""
    return PortfolioDriftDetector(hysteresis_threshold_pct=Decimal("2.5"))


@pytest.fixture
def rebalance_engine() -> MicroRebalancingEngine:
    """Standard MicroRebalancingEngine instance."""
    return MicroRebalancingEngine()


@pytest.fixture
def ledger() -> PaperExecutionLedger:
    """Standard double-entry paper execution ledger with 100 USDT starting equity."""
    return PaperExecutionLedger(starting_equity=Decimal("100.00"))


@pytest.fixture
def temp_output_dir() -> Generator[Path]:
    """Provide a temporary directory cleaned up after test execution."""
    td = tempfile.mkdtemp(prefix="phase299_test_")
    yield Path(td)
    shutil.rmtree(td, ignore_errors=True)


# =====================================================================
# R1 Tests: DynamicRiskParityAllocator
# =====================================================================


def test_dynamic_risk_parity_weights_inverse_relationship(
    allocator: DynamicRiskParityAllocator,
) -> None:
    """Verify w_i* propto 1 / (sigma_i * (1 + lambda_i)). Higher risk yields lower weight."""
    vols = {
        "BTCUSDT": Decimal("0.0100"),  # Lowest vol
        "ETHUSDT": Decimal("0.0200"),  # Medium vol
        "SOLUSDT": Decimal("0.0400"),  # Highest vol
    }
    jumps = {
        "BTCUSDT": Decimal("0.0"),
        "ETHUSDT": Decimal("0.0"),
        "SOLUSDT": Decimal("0.0"),
    }

    weights = allocator.compute_risk_parity_weights(vols, jumps)
    assert weights["BTCUSDT"] > weights["ETHUSDT"] > weights["SOLUSDT"]
    total_w = sum(weights.values(), Decimal("0"))
    assert total_w == Decimal("1.00000000")


def test_dynamic_risk_parity_weights_with_jump_intensities(
    allocator: DynamicRiskParityAllocator,
) -> None:
    """Verify Hawkes jump intensities penalize allocation via (1 + lambda_i) factor."""
    # Equal volatilities
    vols = {s: Decimal("0.0200") for s in DEFAULT_SYMBOLS}
    # BTC has high jump clustering, SOL has low
    jumps = {
        "BTCUSDT": Decimal("0.80"),  # High jump intensity
        "ETHUSDT": Decimal("0.20"),  # Moderate jump intensity
        "SOLUSDT": Decimal("0.00"),  # Low jump intensity
    }

    weights = allocator.compute_risk_parity_weights(vols, jumps)
    # SOL should have the largest allocation due to zero jump arrivals
    assert weights["SOLUSDT"] > weights["ETHUSDT"] > weights["BTCUSDT"]
    assert sum(weights.values(), Decimal("0")) == Decimal("1.00000000")


def test_variance_floor_sigma_min_enforcement(
    allocator: DynamicRiskParityAllocator,
) -> None:
    """Verify that zero or sub-floor volatility is clamped to variance_floor_sigma_min (1e-4)."""
    vols = {
        "BTCUSDT": Decimal("0.0"),  # Should clamp to 1e-4
        "ETHUSDT": Decimal("0.00001"),  # Below floor, should clamp to 1e-4
        "SOLUSDT": Decimal("0.0200"),
    }
    jumps = {s: Decimal("0.0") for s in DEFAULT_SYMBOLS}

    weights = allocator.compute_risk_parity_weights(vols, jumps)
    # BTC and ETH both clamp to 1e-4, so their weights should be equal (within residual rounding)
    assert abs(weights["BTCUSDT"] - weights["ETHUSDT"]) <= Decimal("0.00000010")
    assert weights["BTCUSDT"] > weights["SOLUSDT"]
    assert sum(weights.values(), Decimal("0")) == Decimal("1.00000000")


def test_target_allocations_capacity_and_reserve_invariants(
    allocator: DynamicRiskParityAllocator,
) -> None:
    """Verify aggregate exposure cap <= 60.00 USDT, per-asset <= 25.00 USDT, cash >= 40.0%."""
    weights = {
        "BTCUSDT": Decimal("0.50"),
        "ETHUSDT": Decimal("0.30"),
        "SOLUSDT": Decimal("0.20"),
    }
    allocations = allocator.compute_target_allocations(
        weights, total_equity_usdt=Decimal("100.00"), redistribute_excess=False
    )

    total_exposure = sum(allocations.values(), Decimal("0"))
    assert total_exposure <= DEFAULT_AGGREGATE_EXPOSURE_CAP_USDT
    for _sym, dollar in allocations.items():
        assert dollar <= DEFAULT_PER_ASSET_MARGIN_CEILING_USDT

    cash_reserve = Decimal("100.00") - total_exposure
    assert cash_reserve >= Decimal("40.00")


def test_target_allocations_per_asset_margin_ceiling_clamping(
    allocator: DynamicRiskParityAllocator,
) -> None:
    """Verify individual asset allocation is clamped at 25.00 USDT even if weight is high."""
    # Extreme weight on BTC
    weights = {
        "BTCUSDT": Decimal("0.80"),
        "ETHUSDT": Decimal("0.10"),
        "SOLUSDT": Decimal("0.10"),
    }
    allocations = allocator.compute_target_allocations(
        weights, total_equity_usdt=Decimal("100.00"), redistribute_excess=False
    )

    # 0.80 * 60.00 = 48.00 USDT, but must clamp to 25.00 USDT
    assert allocations["BTCUSDT"] == Decimal("25.00")
    assert allocations["ETHUSDT"] == Decimal("6.00")
    assert allocations["SOLUSDT"] == Decimal("6.00")
    assert sum(allocations.values(), Decimal("0")) == Decimal("37.00")
    assert Decimal("100.00") - Decimal("37.00") >= Decimal("40.00")


def test_target_allocations_water_filling_redistribution(
    allocator: DynamicRiskParityAllocator,
) -> None:
    """Verify redistribute_excess=True reallocates excess capacity without exceeding 25.00 USDT."""
    weights = {
        "BTCUSDT": Decimal("0.60"),  # Raw: 36.00 USDT -> clamp to 25.00, excess 11.00 USDT
        "ETHUSDT": Decimal("0.20"),  # Raw: 12.00 USDT -> gets half of 11.00 = 17.50 USDT
        "SOLUSDT": Decimal("0.20"),  # Raw: 12.00 USDT -> gets half of 11.00 = 17.50 USDT
    }
    allocations = allocator.compute_target_allocations(
        weights, total_equity_usdt=Decimal("100.00"), redistribute_excess=True
    )

    assert allocations["BTCUSDT"] == Decimal("25.00")
    assert allocations["ETHUSDT"] == Decimal("17.50")
    assert allocations["SOLUSDT"] == Decimal("17.50")
    assert sum(allocations.values(), Decimal("0")) == Decimal("60.00")


def test_target_allocations_scaled_on_low_equity(
    allocator: DynamicRiskParityAllocator,
) -> None:
    """Verify proportional scaling down on reduced total equity (e.g. 50.00 USDT)."""
    weights = {
        "BTCUSDT": Decimal("0.40"),
        "ETHUSDT": Decimal("0.35"),
        "SOLUSDT": Decimal("0.25"),
    }
    # On 50 USDT equity, 40% cash reserve requires 20.00 USDT cash floor, max exposure 30.00 USDT
    allocations = allocator.compute_target_allocations(weights, total_equity_usdt=Decimal("50.00"))
    total_alloc = sum(allocations.values(), Decimal("0"))
    assert total_alloc <= Decimal("30.00")
    assert Decimal("50.00") - total_alloc >= Decimal("20.00")


def test_rolling_volatility_calculation(allocator: DynamicRiskParityAllocator) -> None:
    """Verify price updates produce genuine rolling volatility."""
    prices = [
        Decimal("60000.00"),
        Decimal("60600.00"),  # +1.0%
        Decimal("59994.00"),  # -1.0%
        Decimal("60593.94"),  # +1.0%
        Decimal("59987.00"),  # -1.0%
    ]
    for p in prices:
        allocator.update_price("BTCUSDT", p)

    vol = allocator.compute_rolling_volatility("BTCUSDT")
    assert vol > DEFAULT_VARIANCE_FLOOR_SIGMA_MIN
    assert vol > Decimal("0.005")  # roughly ~1.0% volatility


def test_invalid_equity_raises_risk_parity_error(
    allocator: DynamicRiskParityAllocator,
) -> None:
    """Verify non-positive equity raises RiskParityAllocationError."""
    weights = {s: Decimal("0.33333333") for s in DEFAULT_SYMBOLS}
    with pytest.raises(RiskParityAllocationError, match="Total equity must be positive"):
        allocator.compute_target_allocations(weights, total_equity_usdt=Decimal("0.00"))


# =====================================================================
# R2 Tests: CrossAssetSpilloverGuard
# =====================================================================


def test_hawkes_branching_ratio_and_spectral_radius(
    guard: CrossAssetSpilloverGuard,
) -> None:
    """Verify Hawkes branching ratio gamma_ij and empirical spectral radius."""
    # Cross-excitation: SOL is coupled to BTC (alpha=0.18, beta=1.0)
    gamma_sol_btc = guard.get_branching_ratio(recipient="SOLUSDT", source="BTCUSDT")
    assert gamma_sol_btc == Decimal("0.18")

    rho = guard.compute_spectral_radius()
    # Baseline empirical spectral radius should be subcritical (around ~0.45 - 0.50)
    assert Decimal("0.30") < rho < Decimal("0.70")


def test_cross_asset_spillover_hazard_triggers(guard: CrossAssetSpilloverGuard) -> None:
    """Verify detection of source hazards (rho >= 0.85, severe OFI, flash crash)."""
    # Trigger 1: OFI toxicity on BTC
    res_ofi = guard.evaluate_spillover_hazards(ofi_toxicities={"BTCUSDT": Decimal("-0.85")})
    assert "BTCUSDT" in res_ofi.hazards_detected
    assert any("SEVERE_OFI_TOXICITY" in h for h in res_ofi.hazards_detected["BTCUSDT"])

    # Trigger 2: Flash crash drop on ETH (-12%)
    res_crash = guard.evaluate_spillover_hazards(price_drops={"ETHUSDT": Decimal("-0.12")})
    assert "ETHUSDT" in res_crash.hazards_detected
    assert any("FLASH_CRASH_DROP" in h for h in res_crash.hazards_detected["ETHUSDT"])

    # Trigger 3: Spectral radius breach on SOL (rho = 0.89)
    res_rho = guard.evaluate_spillover_hazards(spectral_radii={"SOLUSDT": Decimal("0.89")})
    assert "SOLUSDT" in res_rho.hazards_detected
    assert any("SPECTRAL_RADIUS_BREACH" in h for h in res_rho.hazards_detected["SOLUSDT"])


def test_contagion_capital_deallocation_on_satellite_asset(
    guard: CrossAssetSpilloverGuard,
) -> None:
    """Verify distress in primary anchor (BTC) dampens target allocation on satellite (SOL)."""
    initial_allocs = {
        "BTCUSDT": Decimal("25.00"),
        "ETHUSDT": Decimal("20.00"),
        "SOLUSDT": Decimal("15.00"),
    }

    # BTC suffers flash crash (-12%) and OFI toxicity (-0.85)
    guard_res = guard.evaluate_spillover_hazards(
        ofi_toxicities={"BTCUSDT": Decimal("-0.85")},
        price_drops={"BTCUSDT": Decimal("-0.12")},
    )

    # SOL has gamma = 0.18 from BTC -> deallocation factor should be positive
    sol_factor = guard_res.deallocation_factors["SOLUSDT"]
    assert sol_factor >= Decimal("0.25")

    dampened_allocs = guard.apply_deallocation_to_targets(initial_allocs, guard_res)
    assert dampened_allocs["SOLUSDT"] < initial_allocs["SOLUSDT"]
    # BTC unconstrained target unchanged by guard (already in distress)
    assert dampened_allocs["BTCUSDT"] == initial_allocs["BTCUSDT"]


def test_supercritical_runaway_emergency_portfolio_freeze(
    guard: CrossAssetSpilloverGuard,
) -> None:
    """Verify supercritical spectral radius (rho >= 1.0) triggers emergency portfolio lockout."""
    res = guard.evaluate_spillover_hazards(systemic_spectral_radius=Decimal("1.08"))
    assert res.is_portfolio_frozen is True
    assert res.contagion_level == ContagionLevel.SUPERCRITICAL_LOCKOUT
    assert set(res.frozen_symbols) == set(DEFAULT_SYMBOLS)


def test_severe_flash_crash_freezes_order_dispatch(
    guard: CrossAssetSpilloverGuard,
) -> None:
    """Verify severe flash crash (drop <= -15.0%) freezes order dispatch."""
    res = guard.evaluate_spillover_hazards(
        price_drops={"BTCUSDT": Decimal("-0.18")}  # -18% flash crash
    )
    assert "BTCUSDT" in res.frozen_symbols
    assert "SOLUSDT" in res.frozen_symbols  # coupled satellite also frozen


def test_contagion_recovery_hysteresis(guard: CrossAssetSpilloverGuard) -> None:
    """Verify recovery requires >= 3 consecutive clean ticks before lifting hazard/freeze."""
    # Tick 0: Hazard trigger
    res0 = guard.evaluate_spillover_hazards(ofi_toxicities={"BTCUSDT": Decimal("-0.90")})
    assert "BTCUSDT" in res0.hazards_detected

    # Tick 1: Clean tick (rho <= 0.80, ofi <= 0.50, drop > -0.05)
    res1 = guard.evaluate_spillover_hazards(ofi_toxicities={"BTCUSDT": Decimal("0.10")})
    assert "BTCUSDT" in res1.hazards_detected  # Still active (count = 1)

    # Tick 2: Clean tick
    res2 = guard.evaluate_spillover_hazards(ofi_toxicities={"BTCUSDT": Decimal("0.05")})
    assert "BTCUSDT" in res2.hazards_detected  # Still active (count = 2)

    # Tick 3: Third consecutive clean tick -> recovery satisfied
    res3 = guard.evaluate_spillover_hazards(ofi_toxicities={"BTCUSDT": Decimal("0.02")})
    assert "BTCUSDT" not in res3.hazards_detected  # Cleared!


# =====================================================================
# R3 Tests: PortfolioDriftDetector & MicroRebalancingEngine
# =====================================================================


def test_portfolio_drift_detector_hysteresis_band(
    drift_detector: PortfolioDriftDetector,
) -> None:
    """Verify rebalance triggered IF AND ONLY IF max drift > 2.5%."""
    # Case 1: Drift within hysteresis (e.g. 1.5% drift)
    active_allocs_1 = {
        "BTCUSDT": Decimal("24.00"),
        "ETHUSDT": Decimal("18.00"),
        "SOLUSDT": Decimal("12.00"),
    }
    target_allocs_1 = {
        "BTCUSDT": Decimal("25.50"),
        "ETHUSDT": Decimal("17.00"),
        "SOLUSDT": Decimal("12.00"),
    }
    # Max drift is 1.50 / 100 = 1.5% <= 2.5%
    res1 = drift_detector.evaluate_drift(
        active_allocs_1, target_allocs_1, total_equity_usdt=Decimal("100.00")
    )
    assert res1.rebalance_required is False
    assert res1.status == DriftStatus.DRIFT_TOLERABLE

    # Case 2: Drift exceeds hysteresis (e.g. 5.0% drift)
    active_allocs_2 = {
        "BTCUSDT": Decimal("20.00"),
        "ETHUSDT": Decimal("18.00"),
        "SOLUSDT": Decimal("12.00"),
    }
    target_allocs_2 = {
        "BTCUSDT": Decimal("25.50"),
        "ETHUSDT": Decimal("18.00"),
        "SOLUSDT": Decimal("12.00"),
    }
    # Max drift is 5.50 / 100 = 5.5% > 2.5%
    res2 = drift_detector.evaluate_drift(
        active_allocs_2, target_allocs_2, total_equity_usdt=Decimal("100.00")
    )
    assert res2.rebalance_required is True
    assert res2.status == DriftStatus.DRIFT_EXCEEDED


def test_micro_order_slicing_strictly_under_five_usdt_cap(
    rebalance_engine: MicroRebalancingEngine,
) -> None:
    """Verify child orders are sliced strictly <= 5.00 USDT cap with ROUND_DOWN precision."""
    # Rebalance delta = +14.00 USDT on BTCUSDT at price 60000.00
    price = Decimal("60000.00")
    orders = rebalance_engine.synthesize_rebalancing_orders(
        symbol="BTCUSDT",
        drift_delta_usdt=Decimal("14.00"),
        reference_price=price,
        step_size=Decimal("0.00001"),
    )

    assert len(orders) >= 3
    for order in orders:
        assert order.notional_usdt <= DEFAULT_MAX_CHUNK_CAP_USDT
        assert order.notional_usdt >= Decimal("1.00")  # Above dust floor
        assert order.side == OrderSide.BUY
        assert order.symbol == "BTCUSDT"
        assert order.client_order_id.startswith("c=canary-p299-btcusdt-")
        # Step size compliance
        assert (order.quantity % Decimal("0.00001")) == Decimal("0.0")


def test_micro_order_slicing_sell_side(
    rebalance_engine: MicroRebalancingEngine,
) -> None:
    """Verify negative drift delta generates SELL child orders."""
    orders = rebalance_engine.synthesize_rebalancing_orders(
        symbol="ETHUSDT",
        drift_delta_usdt=Decimal("-8.00"),
        reference_price=Decimal("3000.00"),
        step_size=Decimal("0.001"),
    )
    assert len(orders) >= 2
    for order in orders:
        assert order.side == OrderSide.SELL
        assert order.notional_usdt <= DEFAULT_MAX_CHUNK_CAP_USDT


def test_micro_order_slicing_downscaled_under_elevated_contagion(
    rebalance_engine: MicroRebalancingEngine,
) -> None:
    """Verify child chunk cap is downscaled to <= 1.25 USDT under elevated contagion."""
    orders = rebalance_engine.synthesize_rebalancing_orders(
        symbol="SOLUSDT",
        drift_delta_usdt=Decimal("6.00"),
        reference_price=Decimal("100.00"),
        step_size=Decimal("0.01"),
        elevated_contagion=True,
    )
    for order in orders:
        # Downscaled cap of 1.25 USDT (at px 100, 0.01 SOL = 1.00 USDT <= 1.25 USDT)
        assert order.notional_usdt <= Decimal("1.25")


def test_micro_order_slicing_frozen_symbol_fails_closed(
    rebalance_engine: MicroRebalancingEngine,
) -> None:
    """Verify frozen symbol raises CrossAssetContagionFrozenError."""
    with pytest.raises(
        CrossAssetContagionFrozenError,
        match="Cannot synthesize rebalancing order for frozen symbol",
    ):
        rebalance_engine.synthesize_rebalancing_orders(
            symbol="BTCUSDT",
            drift_delta_usdt=Decimal("10.00"),
            reference_price=Decimal("60000.00"),
            is_frozen=True,
        )


def test_passive_matching_simulated_fill_and_fee_deduction(
    rebalance_engine: MicroRebalancingEngine,
    ledger: PaperExecutionLedger,
) -> None:
    """Verify simulated passive execution records maker fee (0.02%) and updates ledger."""
    orders = rebalance_engine.synthesize_rebalancing_orders(
        symbol="SOLUSDT",
        drift_delta_usdt=Decimal("5.00"),
        reference_price=Decimal("150.00"),
        step_size=Decimal("0.01"),
    )
    assert orders

    child = orders[0]
    fill = rebalance_engine.execute_passive_fill(
        child, ledger, fill_price=Decimal("150.00"), maker_fee_rate=Decimal("0.0002")
    )

    assert fill.is_maker is True
    expected_fee = (fill.fill_notional_usdt * Decimal("0.0002")).quantize(
        Decimal("0.00000001"), rounding=ROUND_DOWN
    )
    assert fill.fee_usdt == expected_fee
    assert ledger.total_fees_usdt == expected_fee


# =====================================================================
# R4 Tests: Continuous Mathematical Double-Entry Zero-Drift Governance
# =====================================================================


def test_continuous_double_entry_zero_drift_across_multiple_fills(
    rebalance_engine: MicroRebalancingEngine,
    ledger: PaperExecutionLedger,
) -> None:
    """Verify |Delta| < 10^-15 USDT across simulated fills and fee deductions."""
    # Verify starting equity
    assert ledger.drift == Decimal("0")

    symbols_deltas = [
        ("BTCUSDT", Decimal("15.00"), Decimal("60000.00")),
        ("ETHUSDT", Decimal("12.00"), Decimal("3000.00")),
        ("SOLUSDT", Decimal("8.00"), Decimal("150.00")),
    ]

    for sym, delta, px in symbols_deltas:
        orders = rebalance_engine.synthesize_rebalancing_orders(
            symbol=sym,
            drift_delta_usdt=delta,
            reference_price=px,
            step_size=rebalance_engine.step_sizes[sym],
        )
        for order in orders:
            rebalance_engine.execute_passive_fill(order, ledger, fill_price=order.price)
            # Assert zero-drift invariant holds after every individual child order execution
            drift_val = verify_double_entry_zero_drift(ledger)
            assert drift_val < DOUBLE_ENTRY_MAX_DRIFT
            assert drift_val == Decimal("0")


def test_double_entry_drift_breach_raises_domain_error(
    ledger: PaperExecutionLedger,
) -> None:
    """Verify that any balance drift >= 1e-15 USDT immediately raises DoubleEntryDriftError."""
    # Artificially inject 1e-14 USDT drift
    ledger.cash += Decimal("0.00000000000001")
    assert ledger.drift >= DOUBLE_ENTRY_MAX_DRIFT

    with pytest.raises(DoubleEntryDriftError, match="Double-entry drift"):
        verify_double_entry_zero_drift(ledger)


def test_portfolio_snapshot_creation_and_reconciliation(
    allocator: DynamicRiskParityAllocator,
    ledger: PaperExecutionLedger,
) -> None:
    """Verify create_portfolio_snapshot returns verified zero-drift snapshot."""
    weights = {"BTCUSDT": Decimal("0.40"), "ETHUSDT": Decimal("0.35"), "SOLUSDT": Decimal("0.25")}
    target_allocs = {
        "BTCUSDT": Decimal("24.00"),
        "ETHUSDT": Decimal("21.00"),
        "SOLUSDT": Decimal("15.00"),
    }
    prices = dict(DEFAULT_REFERENCE_PRICES)
    vols = {s: Decimal("0.02") for s in DEFAULT_SYMBOLS}
    jumps = {s: Decimal("0.0") for s in DEFAULT_SYMBOLS}

    snapshot = create_portfolio_snapshot(
        ledger=ledger,
        allocator=allocator,
        weights=weights,
        target_allocations=target_allocs,
        prices=prices,
        volatilities=vols,
        jump_intensities=jumps,
        spectral_radius=Decimal("0.45"),
        regime=RebalanceRegime.NOMINAL,
    )

    assert snapshot.zero_drift_verified is True
    assert snapshot.double_entry_drift < DOUBLE_ENTRY_MAX_DRIFT
    assert snapshot.starting_equity == Decimal("100.00")
    assert snapshot.regime == RebalanceRegime.NOMINAL


# =====================================================================
# R5 / Track Tests: CanaryPortfolioRebalancingRunner & Merkle DAG
# =====================================================================


def test_runner_track_1_risk_parity_allocation(temp_output_dir: Path) -> None:
    """Verify deterministic execution of Track 1."""
    runner = CanaryPortfolioRebalancingRunner(output_dir=temp_output_dir)
    res = runner.run_track_1_risk_parity_allocation()
    assert res["status"] == "PASSED"
    assert Decimal(res["total_allocation_usdt"]) <= DEFAULT_AGGREGATE_EXPOSURE_CAP_USDT
    assert Decimal(res["cash_reserve_usdt"]) >= Decimal("40.00")


def test_runner_track_2_spillover_contagion_throttling(temp_output_dir: Path) -> None:
    """Verify deterministic execution of Track 2."""
    runner = CanaryPortfolioRebalancingRunner(output_dir=temp_output_dir)
    res = runner.run_track_2_spillover_contagion_throttling()
    assert res["status"] == "PASSED"
    assert Decimal(res["sol_deallocation_factor"]) > Decimal("0")
    assert res["supercritical_lockout_verified"] is True


def test_runner_track_3_micro_rebalancing_execution(temp_output_dir: Path) -> None:
    """Verify deterministic execution of Track 3."""
    runner = CanaryPortfolioRebalancingRunner(output_dir=temp_output_dir)
    res = runner.run_track_3_micro_rebalancing_execution()
    assert res["status"] == "PASSED"
    assert res["child_orders_count"] > 0
    assert Decimal(res["double_entry_drift"]) < DOUBLE_ENTRY_MAX_DRIFT


def test_runner_track_4_full_lifecycle_and_merkle_dag(temp_output_dir: Path) -> None:
    """Verify Track 4 produces verified report and SHA-256 Merkle DAG linking Phase 298 root."""
    runner = CanaryPortfolioRebalancingRunner(output_dir=temp_output_dir)
    report = runner.run_track_4_full_lifecycle_and_merkle_dag()

    assert report.verified is True
    assert report.double_entry_verified is True
    assert report.max_observed_drift < DOUBLE_ENTRY_MAX_DRIFT
    assert report.upstream_hash == UPSTREAM_PHASE298_ROOT_HASH
    assert len(report.phase_hash) == 64
    assert len(report.merkle_root) == 64

    # Verify files created on disk
    assert (temp_output_dir / "canary-portfolio-rebalancing-report.json").exists()
    assert (temp_output_dir / "portfolio-rebalancing-summary.json").exists()
    assert (temp_output_dir / "canary-portfolio-rebalancing-telemetry.sqlite3").exists()
    assert (temp_output_dir / "canary-orders.jsonl").exists()


def test_runner_execute_all_tracks(temp_output_dir: Path) -> None:
    """Verify end-to-end execution of all tracks via execute_all_tracks."""
    runner = CanaryPortfolioRebalancingRunner(output_dir=temp_output_dir)
    summary = runner.execute_all_tracks()
    assert summary["verified"] is True
    assert summary["tracks"]["track_1"]["status"] == "PASSED"
    assert summary["tracks"]["track_2"]["status"] == "PASSED"
    assert summary["tracks"]["track_3"]["status"] == "PASSED"
    assert summary["tracks"]["track_4"]["status"] == "PASSED"
