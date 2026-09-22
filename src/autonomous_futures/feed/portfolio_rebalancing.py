"""Phase 299: Dynamic Multi-Asset Risk Orchestration, Capital Allocation & Portfolio Rebalancing.

Establishes:
1. Hawkes-informed dynamic risk parity allocation across candidate universe (BTC, ETH, SOL)
   with w_i* propto 1 / (sigma_i * (1 + lambda_i)) subject to aggregate exposure cap
   (<= 60.00 USDT), per-asset margin ceilings (<= 25.00 USDT), and cash reserve floor (>= 40.0%).
2. Cross-asset Hawkes spillover and contagion guards based on empirical cross-excitation matrix
   alpha_ij and branching ratio gamma_ij = alpha_ij / beta_ij, throttling or freezing recipient
   assets upon source hazard (rho_j >= 0.85, severe OFI toxicity, flash crash drop <= -10.0%),
   with emergency portfolio freeze on supercritical rho >= 1.0.
3. Micro-order rebalancing execution engine with hysteresis drift detector (|w_i - w_i*| > 2.5%),
   child order slicing strictly <= 5.00 USDT cap, ROUND_DOWN step size precision, and passive
   matching simulation with maker fees.
4. Continuous mathematical double-entry zero-drift balance governance maintaining
   |Delta| < 10^-15 USDT across all rebalancing cycles, fills, fee deductions, and margin transfers.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from pydantic import Field

from autonomous_futures.domain.contracts import DomainModel
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.feed.canary_activation import (
    CANARY_STAGED_SYMBOLS,
    DEFAULT_REFERENCE_PRICES,
    STARTING_EQUITY_USDT,
)
from autonomous_futures.feed.paper_execution import (
    ChildOrderIntention,
    OrderExecutionFill,
    OrderSide,
    OrderStatus,
    OrderType,
    SimulatedPassiveMatchingEngine,
    TimeInForce,
)
from autonomous_futures.feed.paper_ledger import (
    DOUBLE_ENTRY_MAX_DRIFT,
    PaperExecutionLedger,
)

logger = logging.getLogger(__name__)

# =====================================================================
# Constants & Defaults
# =====================================================================

DEFAULT_SYMBOLS: tuple[str, ...] = tuple(CANARY_STAGED_SYMBOLS)  # ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_AGGREGATE_EXPOSURE_CAP_USDT = Decimal("60.00")
DEFAULT_PER_ASSET_MARGIN_CEILING_USDT = Decimal("25.00")
DEFAULT_MIN_CASH_RESERVE_FLOOR_PCT = Decimal("40.0")
DEFAULT_VARIANCE_FLOOR_SIGMA_MIN = Decimal("0.0001")  # 1e-4 variance/volatility floor
DEFAULT_HYSTERESIS_THRESHOLD_PCT = Decimal("2.5")  # 2.5% allocation drift band
DEFAULT_MAX_CHUNK_CAP_USDT = Decimal("5.00")
DEFAULT_DEFAULT_CHUNK_USDT = Decimal("2.50")
DEFAULT_MIN_CHUNK_FLOOR_USDT = Decimal("1.00")
DEFAULT_MAKER_FEE_RATE = Decimal("0.0002")  # 0.02%
DEFAULT_TAKER_FEE_RATE = Decimal("0.0004")  # 0.04%

DEFAULT_STEP_SIZES: dict[str, Decimal] = {
    "BTCUSDT": Decimal("0.00001"),
    "ETHUSDT": Decimal("0.001"),
    "SOLUSDT": Decimal("0.01"),
}

UPSTREAM_PHASE298_ROOT_HASH = "b2ea1dc7053aec1ecd6dd9845d776380093b925e056b891b64c8a454a62bf837"
DEFAULT_PHASE299_OUTPUT_DIR = Path("artifacts/research/phase299")

# Baseline Hawkes Process Parameters (Empirical Multi-Asset Estimates)
DEFAULT_HAWKES_MU: dict[str, Decimal] = {
    "BTCUSDT": Decimal("0.10"),
    "ETHUSDT": Decimal("0.12"),
    "SOLUSDT": Decimal("0.15"),
}

DEFAULT_HAWKES_ALPHA: dict[tuple[str, str], Decimal] = {
    # Self-excitation
    ("BTCUSDT", "BTCUSDT"): Decimal("0.25"),
    ("ETHUSDT", "ETHUSDT"): Decimal("0.28"),
    ("SOLUSDT", "SOLUSDT"): Decimal("0.35"),
    # Cross-excitation (off-diagonal: (recipient, source))
    ("BTCUSDT", "ETHUSDT"): Decimal("0.12"),
    ("BTCUSDT", "SOLUSDT"): Decimal("0.05"),
    ("ETHUSDT", "BTCUSDT"): Decimal("0.10"),
    ("ETHUSDT", "SOLUSDT"): Decimal("0.05"),
    ("SOLUSDT", "BTCUSDT"): Decimal("0.18"),  # Primary BTC -> Satellite SOL
    ("SOLUSDT", "ETHUSDT"): Decimal("0.15"),  # Primary ETH -> Satellite SOL
}

DEFAULT_HAWKES_BETA: dict[tuple[str, str], Decimal] = {
    (si, sj): Decimal("1.0") for si in DEFAULT_SYMBOLS for sj in DEFAULT_SYMBOLS
}

# =====================================================================
# Domain Exceptions
# =====================================================================


class PortfolioRebalancingError(DomainViolation):
    """Base exception for portfolio rebalancing domain invariant violations."""


class RiskParityAllocationError(PortfolioRebalancingError):
    """Raised when risk parity weight normalization or computation fails."""


class AggregateExposureCapExceededError(PortfolioRebalancingError):
    """Raised when portfolio aggregate exposure exceeds 60.00 USDT."""


class PerAssetMarginCapExceededError(PortfolioRebalancingError):
    """Raised when an individual asset margin allocation exceeds 25.00 USDT."""


class CashReserveBufferBreachedError(PortfolioRebalancingError):
    """Raised when cash reserve drops below the minimum 40.0% floor."""


class CrossAssetContagionFrozenError(PortfolioRebalancingError):
    """Raised when order dispatch is attempted on an asset frozen by contagion guards."""


class MicroChildOrderCapExceededError(PortfolioRebalancingError):
    """Raised when a child order exceeds the mandatory 5.00 USDT cap."""


class DoubleEntryDriftError(PortfolioRebalancingError):
    """Raised when mathematical double-entry drift exceeds 1e-15 USDT."""


class GatewayHeartbeatStaleError(PortfolioRebalancingError):
    """Raised when gateway heartbeat age exceeds 500 ms."""


# =====================================================================
# Enums
# =====================================================================


class RebalanceRegime(StrEnum):
    """Operational regimes for portfolio risk orchestration."""

    NOMINAL = "NOMINAL"
    DRIFT_ALERT = "DRIFT_ALERT"
    REBALANCING_ACTIVE = "REBALANCING_ACTIVE"
    SPILLOVER_THROTTLED = "SPILLOVER_THROTTLED"
    EMERGENCY_FROZEN = "EMERGENCY_FROZEN"


class ContagionLevel(StrEnum):
    """Severity levels for cross-asset Hawkes spillover and contagion."""

    NONE = "NONE"
    ELEVATED_SPILLOVER = "ELEVATED_SPILLOVER"
    SEVERE_CONTAGION = "SEVERE_CONTAGION"
    SUPERCRITICAL_LOCKOUT = "SUPERCRITICAL_LOCKOUT"


class DriftStatus(StrEnum):
    """Portfolio allocation drift status against hysteresis bands."""

    BALANCED = "BALANCED"
    DRIFT_TOLERABLE = "DRIFT_TOLERABLE"
    DRIFT_EXCEEDED = "DRIFT_EXCEEDED"


class RebalanceTrackId(StrEnum):
    """Verification simulation track identifiers."""

    TRACK_1 = "track_1"
    TRACK_2 = "track_2"
    TRACK_3 = "track_3"
    TRACK_4 = "track_4"


# =====================================================================
# Domain Models & Telemetry Structures
# =====================================================================


class AssetRiskMetrics(DomainModel):
    """Risk and allocation telemetry per individual candidate asset."""

    symbol: str
    current_price: Decimal
    rolling_volatility_sigma: Decimal
    jump_intensity_lambda: Decimal
    spectral_radius_rho: Decimal
    target_weight: Decimal
    current_weight: Decimal
    drift_pct: Decimal
    target_allocation_usdt: Decimal
    current_allocation_usdt: Decimal
    rebalance_delta_usdt: Decimal


class SpilloverContagionSnapshot(DomainModel):
    """Detailed observation of cross-asset spillover interaction."""

    timestamp_utc: str
    source_symbol: str
    recipient_symbol: str
    cross_excitation_alpha: Decimal
    branching_ratio_gamma: Decimal
    spectral_radius_rho: Decimal
    ofi_toxicity: Decimal
    price_drop_pct: Decimal
    contagion_level: ContagionLevel
    capital_deallocation_factor: Decimal
    is_dispatch_frozen: bool
    rationale: str


class SpilloverGuardEvaluationResult(DomainModel):
    """Portfolio-wide spillover guard evaluation outcome."""

    timestamp_utc: str
    contagion_level: ContagionLevel
    is_portfolio_frozen: bool
    systemic_spectral_radius: Decimal
    frozen_symbols: list[str] = Field(default_factory=list)
    deallocation_factors: dict[str, Decimal] = Field(default_factory=dict)
    hazards_detected: dict[str, list[str]] = Field(default_factory=dict)
    snapshots: list[SpilloverContagionSnapshot] = Field(default_factory=list)
    rationale: str = ""


class DriftEvaluationResult(DomainModel):
    """Evaluation result from PortfolioDriftDetector."""

    timestamp_utc: str
    status: DriftStatus
    max_drift_pct: Decimal
    hysteresis_threshold_pct: Decimal
    rebalance_required: bool
    drifts: dict[str, Decimal]
    target_allocations: dict[str, Decimal]
    current_allocations: dict[str, Decimal]
    deltas: dict[str, Decimal]


class RebalanceExecutionRecord(DomainModel):
    """Audit record for a rebalancing execution attempt."""

    rebalance_id: str
    timestamp_utc: str
    symbol: str
    side: OrderSide
    drift_pct: Decimal
    rebalance_notional_usdt: Decimal
    sliced_child_orders_count: int
    filled_notional_usdt: Decimal
    total_fees_usdt: Decimal
    status: str
    child_orders: list[ChildOrderIntention] = Field(default_factory=list)


class PortfolioRebalanceSnapshot(DomainModel):
    """Real-time portfolio-level balance, allocation, and double-entry snapshot."""

    timestamp_utc: str
    starting_equity: Decimal
    cash: Decimal
    allocated_margin: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_equity: Decimal
    double_entry_drift: Decimal
    zero_drift_verified: bool
    asset_metrics: dict[str, AssetRiskMetrics] = Field(default_factory=dict)
    aggregate_exposure_usdt: Decimal
    cash_reserve_pct: Decimal
    regime: RebalanceRegime


class CanaryPortfolioRebalancingReport(DomainModel):
    """Structured JSON audit report conforming to Phase 299 Merkle DAG specification."""

    verified: bool = True
    phase: str = "phase_299"
    timestamp_ms: int
    timestamp_utc: str
    regime: RebalanceRegime
    circuit_state: str = "NORMAL"
    paper_safe: bool = True
    execution_authority: bool = False
    candidates: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    snapshots: list[PortfolioRebalanceSnapshot] = Field(default_factory=list)
    spillover_evaluations: list[SpilloverGuardEvaluationResult] = Field(default_factory=list)
    rebalance_records: list[RebalanceExecutionRecord] = Field(default_factory=list)
    double_entry_verified: bool = True
    max_observed_drift: Decimal = Decimal("0")
    upstream_hash: str = UPSTREAM_PHASE298_ROOT_HASH
    phase_hash: str = ""
    merkle_root: str = ""


# =====================================================================
# R1: Dynamic Hawkes Risk-Parity Allocator
# =====================================================================


class DynamicRiskParityAllocator:
    """Computes dynamic Hawkes risk-parity asset allocations subject to portfolio bounds.

    Target dynamic weights:
        w_i* proportional to 1 / (sigma_i * (1 + lambda_i))
    with variance floor sigma_min = 1e-4.

    Bounds enforced:
        - Aggregate exposure cap <= 60.00 USDT
        - Per-asset margin ceiling <= 25.00 USDT
        - Cash reserve floor >= 40.0% (>= 40.00 USDT on 100.00 USDT equity)
        - Proportional downscaling if unconstrained notional breaches capacity.
    """

    def __init__(
        self,
        symbols: Sequence[str] = DEFAULT_SYMBOLS,
        aggregate_exposure_cap_usdt: Decimal = DEFAULT_AGGREGATE_EXPOSURE_CAP_USDT,
        per_asset_margin_ceiling_usdt: Decimal = DEFAULT_PER_ASSET_MARGIN_CEILING_USDT,
        min_cash_reserve_floor_pct: Decimal = DEFAULT_MIN_CASH_RESERVE_FLOOR_PCT,
        variance_floor_sigma_min: Decimal = DEFAULT_VARIANCE_FLOOR_SIGMA_MIN,
        rolling_window_size: int = 30,
    ) -> None:
        self.symbols: list[str] = [s.strip().upper() for s in symbols]
        self.aggregate_exposure_cap_usdt = aggregate_exposure_cap_usdt
        self.per_asset_margin_ceiling_usdt = per_asset_margin_ceiling_usdt
        self.min_cash_reserve_floor_pct = min_cash_reserve_floor_pct
        self.variance_floor_sigma_min = variance_floor_sigma_min
        self.rolling_window_size = rolling_window_size

        self._price_history: dict[str, deque[Decimal]] = {
            s: deque(maxlen=rolling_window_size + 1) for s in self.symbols
        }
        self._return_history: dict[str, deque[Decimal]] = {
            s: deque(maxlen=rolling_window_size) for s in self.symbols
        }

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Record latest observed mid/mark price and update rolling returns."""
        sym = symbol.strip().upper()
        if sym not in self._price_history:
            self._price_history[sym] = deque(maxlen=self.rolling_window_size + 1)
            self._return_history[sym] = deque(maxlen=self.rolling_window_size)

        prices = self._price_history[sym]
        if prices:
            prev_price = prices[-1]
            if prev_price > Decimal("0"):
                ret = (price - prev_price) / prev_price
                self._return_history[sym].append(ret)
        prices.append(price)

    def compute_rolling_volatility(self, symbol: str) -> Decimal:
        """Compute sample standard deviation of rolling returns with sigma_min floor."""
        sym = symbol.strip().upper()
        returns = self._return_history.get(sym)
        if not returns or len(returns) < 2:
            return self.variance_floor_sigma_min

        rets = [float(r) for r in returns]
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
        vol = math.sqrt(max(0.0, var))
        dec_vol = Decimal(f"{vol:.8f}")
        return max(dec_vol, self.variance_floor_sigma_min)

    def compute_risk_parity_weights(
        self,
        volatilities: dict[str, Decimal] | None = None,
        jump_intensities: dict[str, Decimal] | None = None,
    ) -> dict[str, Decimal]:
        """Calculate dynamic risk parity weights w_i* propto 1 / (sigma_i * (1 + lambda_i)).

        Normalized such that sum(w_i*) = 1.0.
        """
        vols = volatilities or {s: self.compute_rolling_volatility(s) for s in self.symbols}
        jumps = jump_intensities or {s: Decimal("0.0") for s in self.symbols}

        scores: dict[str, Decimal] = {}
        for sym in self.symbols:
            sigma_val = vols.get(sym, self.variance_floor_sigma_min)
            sigma_clamped = max(sigma_val, self.variance_floor_sigma_min)

            lambda_val = jumps.get(sym, Decimal("0.0"))
            lambda_clamped = max(lambda_val, Decimal("0.0"))

            denominator = sigma_clamped * (Decimal("1.0") + lambda_clamped)
            if denominator <= Decimal("0"):
                raise RiskParityAllocationError(
                    f"Invalid non-positive denominator for symbol {sym}: {denominator}"
                )
            scores[sym] = Decimal("1.0") / denominator

        total_score = sum(scores.values(), Decimal("0"))
        if total_score <= Decimal("0"):
            raise RiskParityAllocationError(f"Total risk score sum is non-positive: {total_score}")

        weights: dict[str, Decimal] = {}
        # Calculate raw weights rounded to 8 decimal places
        for sym in self.symbols:
            raw_w = (scores[sym] / total_score).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            weights[sym] = raw_w

        # Ensure exact sum to 1.0 by adjusting residual on the largest weight
        current_sum = sum(weights.values(), Decimal("0"))
        residual = Decimal("1.00000000") - current_sum
        if residual != Decimal("0") and self.symbols:
            largest_sym = max(self.symbols, key=lambda s: weights[s])
            weights[largest_sym] += residual

        return weights

    def compute_target_allocations(
        self,
        weights: dict[str, Decimal],
        total_equity_usdt: Decimal = STARTING_EQUITY_USDT,
        redistribute_excess: bool = False,
    ) -> dict[str, Decimal]:
        """Compute target dollar allocations adhering strictly to portfolio ceilings.

        Invariants:
            1. Total exposure <= aggregate_exposure_cap_usdt (60.00 USDT)
            2. Cash reserve >= min_cash_reserve_floor_pct (40.0% of total equity)
            3. Each asset allocation <= per_asset_margin_ceiling_usdt (25.00 USDT)
        """
        if total_equity_usdt <= Decimal("0"):
            raise RiskParityAllocationError(
                f"Total equity must be positive, got {total_equity_usdt}"
            )

        # Maximum allowable portfolio allocation under cash reserve constraint
        reserve_ratio = self.min_cash_reserve_floor_pct / Decimal("100.0")
        max_allocatable_by_reserve = (
            total_equity_usdt * (Decimal("1.0") - reserve_ratio)
        ).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        effective_max_portfolio = min(self.aggregate_exposure_cap_usdt, max_allocatable_by_reserve)

        if not redistribute_excess:
            # Baseline clamping: initial allocation proportional to weights, clamped at ceiling
            allocations: dict[str, Decimal] = {}
            for sym in self.symbols:
                w = weights.get(sym, Decimal("0"))
                raw_dollar = (w * effective_max_portfolio).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )
                clamped_dollar = min(raw_dollar, self.per_asset_margin_ceiling_usdt)
                allocations[sym] = clamped_dollar
            return allocations

        # Water-filling redistribution:
        # iteratively clamp breached assets and redistribute excess capacity
        allocations = {
            s: (weights.get(s, Decimal("0")) * effective_max_portfolio).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
            for s in self.symbols
        }

        capped_symbols: set[str] = set()
        for _ in range(len(self.symbols)):
            newly_capped = False
            excess_pool = Decimal("0")
            uncapped_symbols = [s for s in self.symbols if s not in capped_symbols]

            for s in uncapped_symbols:
                if allocations[s] > self.per_asset_margin_ceiling_usdt:
                    excess_pool += allocations[s] - self.per_asset_margin_ceiling_usdt
                    allocations[s] = self.per_asset_margin_ceiling_usdt
                    capped_symbols.add(s)
                    newly_capped = True

            if not newly_capped or excess_pool <= Decimal("0"):
                break

            remaining = [s for s in self.symbols if s not in capped_symbols]
            if not remaining:
                break

            sum_uncapped_weights = sum(
                (weights.get(s, Decimal("0")) for s in remaining), Decimal("0")
            )
            if sum_uncapped_weights <= Decimal("0"):
                break

            for s in remaining:
                boost = (
                    excess_pool * weights.get(s, Decimal("0")) / sum_uncapped_weights
                ).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                allocations[s] += boost

        # Final safety check: ensure no asset exceeds per_asset_margin_ceiling_usdt
        for s in self.symbols:
            allocations[s] = min(allocations[s], self.per_asset_margin_ceiling_usdt)

        # Scale down if aggregate exceeds cap
        total_alloc = sum(allocations.values(), Decimal("0"))
        if total_alloc > effective_max_portfolio:
            scale = effective_max_portfolio / total_alloc
            for s in self.symbols:
                allocations[s] = (allocations[s] * scale).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )

        return allocations

    def compute_effective_weights(
        self,
        allocations: dict[str, Decimal],
        total_equity_usdt: Decimal = STARTING_EQUITY_USDT,
    ) -> dict[str, Decimal]:
        """Compute effective weights w_i = allocation_i / total_equity."""
        if total_equity_usdt <= Decimal("0"):
            return {s: Decimal("0") for s in self.symbols}
        return {
            s: (allocations.get(s, Decimal("0")) / total_equity_usdt).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
            for s in self.symbols
        }


# =====================================================================
# R2: Cross-Asset Spillover & Contagion Guard
# =====================================================================


class CrossAssetSpilloverGuard:
    """Monitors empirical Hawkes cross-excitation and branching ratios across assets.

    Hazard triggers on source asset j:
        - Spectral radius / hazard intensity: rho_j >= 0.85 (or systemic rho >= 0.85)
        - Severe OFI toxicity: |OFI_j| > 0.80
        - Flash crash drop: delta_P_j / P_j <= -10.0% (-0.10)

    Actions:
        - Instantaneous dynamic capital de-allocation on coupled recipient assets i (gamma_ij)
        - Order dispatch freeze on affected/recipient assets if supercritical (rho >= 1.0)
          or flash crash is severe
        - Recovery hysteresis: requires rho_j <= 0.80, |OFI_j| <= 0.50, and price recovery
          for >= 3 consecutive ticks to restore nominal state.
    """

    def __init__(
        self,
        symbols: Sequence[str] = DEFAULT_SYMBOLS,
        hazard_spectral_radius_threshold: Decimal = Decimal("0.85"),
        supercritical_threshold: Decimal = Decimal("1.00"),
        ofi_toxicity_threshold: Decimal = Decimal("0.80"),
        flash_crash_drop_threshold: Decimal = Decimal("-0.10"),
        severe_flash_crash_threshold: Decimal = Decimal("-0.15"),
        nominal_recovery_spectral_radius: Decimal = Decimal("0.80"),
        nominal_recovery_ofi: Decimal = Decimal("0.50"),
        recovery_ticks_required: int = 3,
        cross_excitation_matrix: dict[tuple[str, str], Decimal] | None = None,
        decay_matrix: dict[tuple[str, str], Decimal] | None = None,
    ) -> None:
        self.symbols: list[str] = [s.strip().upper() for s in symbols]
        self.hazard_spectral_radius_threshold = hazard_spectral_radius_threshold
        self.supercritical_threshold = supercritical_threshold
        self.ofi_toxicity_threshold = ofi_toxicity_threshold
        self.flash_crash_drop_threshold = flash_crash_drop_threshold
        self.severe_flash_crash_threshold = severe_flash_crash_threshold
        self.nominal_recovery_spectral_radius = nominal_recovery_spectral_radius
        self.nominal_recovery_ofi = nominal_recovery_ofi
        self.recovery_ticks_required = recovery_ticks_required

        self.alpha: dict[tuple[str, str], Decimal] = dict(
            cross_excitation_matrix or DEFAULT_HAWKES_ALPHA
        )
        self.beta: dict[tuple[str, str], Decimal] = dict(decay_matrix or DEFAULT_HAWKES_BETA)

        self._active_hazards: dict[str, list[str]] = {}
        self._consecutive_recovery_ticks: dict[str, int] = {s: 0 for s in self.symbols}
        self._frozen_symbols: set[str] = set()
        self._is_portfolio_frozen: bool = False

    def get_branching_ratio(self, recipient: str, source: str) -> Decimal:
        """Branching ratio gamma_ij = alpha_ij / beta_ij."""
        r = recipient.strip().upper()
        s = source.strip().upper()
        a = self.alpha.get((r, s), Decimal("0.0"))
        b = self.beta.get((r, s), Decimal("1.0"))
        if b <= Decimal("0"):
            return Decimal("0.0")
        return (a / b).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

    def compute_spectral_radius(
        self, custom_alpha: dict[tuple[str, str], Decimal] | None = None
    ) -> Decimal:
        """Compute spectral radius rho(Gamma) = max(|eigvals(Gamma)|) of branching matrix."""
        alpha_map = custom_alpha or self.alpha
        n = len(self.symbols)
        mat = np.zeros((n, n), dtype=np.float64)

        for i, si in enumerate(self.symbols):
            for j, sj in enumerate(self.symbols):
                a = float(alpha_map.get((si, sj), Decimal("0.0")))
                b = float(self.beta.get((si, sj), Decimal("1.0")))
                mat[i, j] = a / b if b > 0.0 else 0.0

        eigvals = np.linalg.eigvals(mat)
        rho_val = float(np.max(np.abs(eigvals)))
        return Decimal(f"{rho_val:.6f}")

    def evaluate_spillover_hazards(
        self,
        cross_excitation_matrix: dict[tuple[str, str], Decimal] | None = None,
        spectral_radii: dict[str, Decimal] | None = None,
        ofi_toxicities: dict[str, Decimal] | None = None,
        price_drops: dict[str, Decimal] | None = None,
        systemic_spectral_radius: Decimal | None = None,
    ) -> SpilloverGuardEvaluationResult:
        """Evaluate multi-asset hazard signals and determine required dampening/freezes."""
        if cross_excitation_matrix is not None:
            self.alpha.update(cross_excitation_matrix)

        sys_rho = systemic_spectral_radius or self.compute_spectral_radius()
        spec_radii = spectral_radii or {s: sys_rho for s in self.symbols}
        ofis = ofi_toxicities or {s: Decimal("0.0") for s in self.symbols}
        drops = price_drops or {s: Decimal("0.0") for s in self.symbols}

        now_str = datetime.now(UTC).isoformat()
        current_hazards: dict[str, list[str]] = {}
        deallocation_factors: dict[str, Decimal] = {s: Decimal("0.0") for s in self.symbols}
        newly_frozen: set[str] = set()
        snapshots: list[SpilloverContagionSnapshot] = []

        # Supercritical check
        is_supercritical = sys_rho >= self.supercritical_threshold or any(
            r >= self.supercritical_threshold for r in spec_radii.values()
        )

        for src in self.symbols:
            rho_j = spec_radii.get(src, sys_rho)
            ofi_j = ofis.get(src, Decimal("0.0"))
            drop_j = drops.get(src, Decimal("0.0"))

            src_reasons: list[str] = []
            if rho_j >= self.hazard_spectral_radius_threshold:
                src_reasons.append(f"SPECTRAL_RADIUS_BREACH(rho={rho_j})")
            if abs(ofi_j) > self.ofi_toxicity_threshold:
                src_reasons.append(f"SEVERE_OFI_TOXICITY(ofi={ofi_j})")
            if drop_j <= self.flash_crash_drop_threshold:
                src_reasons.append(f"FLASH_CRASH_DROP(drop={drop_j})")

            # Recovery hysteresis evaluation
            is_clean_tick = (
                rho_j <= self.nominal_recovery_spectral_radius
                and abs(ofi_j) <= self.nominal_recovery_ofi
                and drop_j > Decimal("-0.05")
            )

            if src_reasons:
                self._consecutive_recovery_ticks[src] = 0
                current_hazards[src] = src_reasons
            elif is_clean_tick:
                self._consecutive_recovery_ticks[src] += 1
                if self._consecutive_recovery_ticks[src] >= self.recovery_ticks_required:
                    self._active_hazards.pop(src, None)
                    self._frozen_symbols.discard(src)
            else:
                self._consecutive_recovery_ticks[src] = 0

            # If source has active hazards, evaluate spillover to recipient assets
            if src_reasons:
                for rec in self.symbols:
                    if rec == src:
                        continue
                    gamma = self.get_branching_ratio(recipient=rec, source=src)
                    alpha_val = self.alpha.get((rec, src), Decimal("0.0"))

                    # Dynamic deallocation calculation: proportional to branching ratio
                    # Higher gamma (coupling) leads to stronger capital deallocation
                    # Baseline formula: deallocation = min(0.70, gamma * 2.5) with a floor of 0.20
                    coupling_strength = gamma
                    dealloc_factor = Decimal("0.0")
                    freeze_rec = False

                    if coupling_strength >= Decimal("0.10"):
                        raw_dealloc = (coupling_strength * Decimal("2.5")).quantize(
                            Decimal("0.0001"), rounding=ROUND_DOWN
                        )
                        dealloc_factor = min(Decimal("0.7000"), max(Decimal("0.2500"), raw_dealloc))
                        deallocation_factors[rec] = max(deallocation_factors[rec], dealloc_factor)

                    # Order dispatch freeze condition: supercritical rho or severe flash crash
                    if is_supercritical or drop_j <= self.severe_flash_crash_threshold:
                        freeze_rec = True
                        newly_frozen.add(rec)
                        newly_frozen.add(src)

                    # Snapshot
                    level = (
                        ContagionLevel.SUPERCRITICAL_LOCKOUT
                        if is_supercritical
                        else ContagionLevel.SEVERE_CONTAGION
                        if dealloc_factor > Decimal("0.30")
                        else ContagionLevel.ELEVATED_SPILLOVER
                    )

                    snapshots.append(
                        SpilloverContagionSnapshot(
                            timestamp_utc=now_str,
                            source_symbol=src,
                            recipient_symbol=rec,
                            cross_excitation_alpha=alpha_val,
                            branching_ratio_gamma=gamma,
                            spectral_radius_rho=rho_j,
                            ofi_toxicity=ofi_j,
                            price_drop_pct=drop_j,
                            contagion_level=level,
                            capital_deallocation_factor=dealloc_factor,
                            is_dispatch_frozen=freeze_rec,
                            rationale=(
                                f"Contagion transmission from {src} to {rec}: "
                                f"{', '.join(src_reasons)}"
                            ),
                        )
                    )

        self._active_hazards.update(current_hazards)
        if newly_frozen:
            self._frozen_symbols.update(newly_frozen)

        # Portfolio-wide freeze state
        if is_supercritical:
            self._is_portfolio_frozen = True
            self._frozen_symbols.update(self.symbols)
            overall_level = ContagionLevel.SUPERCRITICAL_LOCKOUT
            rationale = (
                f"Supercritical Hawkes spectral radius breach (rho={sys_rho:.4f} >= 1.0). "
                "Emergency portfolio freeze."
            )
        elif self._frozen_symbols:
            overall_level = ContagionLevel.SEVERE_CONTAGION
            rationale = (
                f"Cross-asset contagion active. Frozen symbols: {sorted(self._frozen_symbols)}"
            )
        elif any(f > Decimal("0") for f in deallocation_factors.values()):
            overall_level = ContagionLevel.ELEVATED_SPILLOVER
            rationale = (
                "Elevated Hawkes cross-excitation detected. Dynamic capital deallocation applied."
            )
        else:
            self._is_portfolio_frozen = False
            overall_level = ContagionLevel.NONE
            rationale = "Nominal Hawkes branching state. No contagion alerts."

        return SpilloverGuardEvaluationResult(
            timestamp_utc=now_str,
            contagion_level=overall_level,
            is_portfolio_frozen=self._is_portfolio_frozen,
            systemic_spectral_radius=sys_rho,
            frozen_symbols=sorted(self._frozen_symbols),
            deallocation_factors=deallocation_factors,
            hazards_detected=self._active_hazards,
            snapshots=snapshots,
            rationale=rationale,
        )

    def apply_deallocation_to_targets(
        self,
        target_allocations: dict[str, Decimal],
        guard_result: SpilloverGuardEvaluationResult,
    ) -> dict[str, Decimal]:
        """Apply contagion deallocation discount factor to target dollar allocations."""
        adjusted: dict[str, Decimal] = {}
        for sym, alloc in target_allocations.items():
            factor = guard_result.deallocation_factors.get(sym, Decimal("0.0"))
            mult = Decimal("1.0") - factor
            adj_val = (alloc * max(Decimal("0.0"), mult)).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
            adjusted[sym] = adj_val
        return adjusted


# =====================================================================
# R3: Micro-Order Rebalancing Engine & Drift Detector
# =====================================================================


class PortfolioDriftDetector:
    """Detects allocation drift |w_i - w_i*| against hysteresis band (default 2.5%)."""

    def __init__(
        self,
        hysteresis_threshold_pct: Decimal = DEFAULT_HYSTERESIS_THRESHOLD_PCT,
    ) -> None:
        # If passed as percentage (e.g. 2.5), convert to ratio (0.025)
        self.hysteresis_threshold_pct = hysteresis_threshold_pct
        self.hysteresis_ratio = (
            (hysteresis_threshold_pct / Decimal("100.0"))
            if hysteresis_threshold_pct >= Decimal("1.0")
            else hysteresis_threshold_pct
        )

    def detect_drifts(
        self,
        active_weights: dict[str, Decimal],
        target_weights: dict[str, Decimal],
    ) -> dict[str, Decimal]:
        """Compute absolute allocation drift per symbol: |w_i - w_i*|."""
        drifts: dict[str, Decimal] = {}
        all_syms = set(active_weights.keys()) | set(target_weights.keys())
        for sym in all_syms:
            w_act = active_weights.get(sym, Decimal("0.0"))
            w_tgt = target_weights.get(sym, Decimal("0.0"))
            drift = abs(w_act - w_tgt).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            drifts[sym] = drift
        return drifts

    def is_rebalance_triggered(self, drifts: dict[str, Decimal]) -> bool:
        """Check if any asset's drift exceeds the hysteresis threshold."""
        return any(d > self.hysteresis_ratio for d in drifts.values())

    def evaluate_drift(
        self,
        active_allocations: dict[str, Decimal],
        target_allocations: dict[str, Decimal],
        total_equity_usdt: Decimal = STARTING_EQUITY_USDT,
    ) -> DriftEvaluationResult:
        """Full evaluation of portfolio drift producing structured DriftEvaluationResult."""
        now_str = datetime.now(UTC).isoformat()
        eq = max(Decimal("0.0001"), total_equity_usdt)

        active_w = {
            s: (a / eq).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            for s, a in active_allocations.items()
        }
        target_w = {
            s: (a / eq).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            for s, a in target_allocations.items()
        }

        drifts = self.detect_drifts(active_w, target_w)
        deltas = {
            s: (
                target_allocations.get(s, Decimal("0")) - active_allocations.get(s, Decimal("0"))
            ).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            for s in set(active_allocations.keys()) | set(target_allocations.keys())
        }

        max_drift = max(drifts.values()) if drifts else Decimal("0.0")
        max_drift_pct = (max_drift * Decimal("100.0")).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )

        rebalance_required = max_drift > self.hysteresis_ratio
        status = (
            DriftStatus.DRIFT_EXCEEDED
            if rebalance_required
            else DriftStatus.DRIFT_TOLERABLE
            if max_drift > Decimal("0")
            else DriftStatus.BALANCED
        )

        return DriftEvaluationResult(
            timestamp_utc=now_str,
            status=status,
            max_drift_pct=max_drift_pct,
            hysteresis_threshold_pct=self.hysteresis_threshold_pct,
            rebalance_required=rebalance_required,
            drifts=drifts,
            target_allocations=target_allocations,
            current_allocations=active_allocations,
            deltas=deltas,
        )


class MicroRebalancingEngine:
    """Slices portfolio rebalancing orders into micro child orders strictly <= 5.00 USDT cap.

    Enforces:
        - Child order cap <= 5.00 USDT
        - ROUND_DOWN step size precision conforming to exchange filters
        - Micro-chunk floor >= 1.00 USDT to prevent sub-dust violations
        - Immediate fail-closed rejection if symbol is frozen by CrossAssetSpilloverGuard
    """

    def __init__(
        self,
        max_chunk_cap_usdt: Decimal = DEFAULT_MAX_CHUNK_CAP_USDT,
        default_chunk_usdt: Decimal = DEFAULT_DEFAULT_CHUNK_USDT,
        min_chunk_floor_usdt: Decimal = DEFAULT_MIN_CHUNK_FLOOR_USDT,
        step_sizes: dict[str, Decimal] | None = None,
        maker_fee_rate: Decimal = DEFAULT_MAKER_FEE_RATE,
    ) -> None:
        self.max_chunk_cap_usdt = max_chunk_cap_usdt
        self.default_chunk_usdt = default_chunk_usdt
        self.min_chunk_floor_usdt = min_chunk_floor_usdt
        self.step_sizes = step_sizes or dict(DEFAULT_STEP_SIZES)
        self.maker_fee_rate = maker_fee_rate

    def synthesize_rebalancing_orders(
        self,
        symbol: str,
        drift_delta_usdt: Decimal,
        reference_price: Decimal,
        step_size: Decimal | None = None,
        is_frozen: bool = False,
        elevated_contagion: bool = False,
    ) -> list[ChildOrderIntention]:
        """Slice target rebalancing notional into compliant micro child orders."""
        sym = symbol.strip().upper()
        if is_frozen:
            raise CrossAssetContagionFrozenError(
                f"Cannot synthesize rebalancing order for frozen symbol {sym} under lockout."
            )

        if reference_price <= Decimal("0"):
            raise PortfolioRebalancingError(f"Invalid reference price for {sym}: {reference_price}")

        step = step_size or self.step_sizes.get(sym, Decimal("0.001"))
        side = OrderSide.BUY if drift_delta_usdt > Decimal("0") else OrderSide.SELL
        required_notional = abs(drift_delta_usdt)

        if required_notional < self.min_chunk_floor_usdt:
            return []

        # Effective chunk cap: downscaled under elevated contagion
        target_chunk_cap = (
            Decimal("1.25")
            if elevated_contagion
            else min(self.default_chunk_usdt, self.max_chunk_cap_usdt)
        )

        min_step_notional = reference_price * step
        if min_step_notional > self.max_chunk_cap_usdt:
            return []

        child_orders: list[ChildOrderIntention] = []
        remaining_notional = required_notional
        parent_id = f"parent-p299-{sym.lower()}-{int(time.time() * 1000)}"
        child_idx = 0

        while remaining_notional >= self.min_chunk_floor_usdt:
            chunk_dollar = min(remaining_notional, target_chunk_cap)
            if chunk_dollar < min_step_notional:
                if (
                    remaining_notional >= min_step_notional
                    and min_step_notional <= self.max_chunk_cap_usdt
                ):
                    chunk_dollar = min_step_notional
                else:
                    break

            # Slicing quantity with ROUND_DOWN precision
            raw_qty = chunk_dollar / reference_price
            qty = raw_qty.quantize(step, rounding=ROUND_DOWN)

            if qty <= Decimal("0"):
                break

            actual_notional = (qty * reference_price).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )

            # Invariant: child order notional strictly <= max_chunk_cap_usdt (5.00 USDT)
            if actual_notional > self.max_chunk_cap_usdt:
                qty = max(Decimal("0"), qty - step)
                actual_notional = (qty * reference_price).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )

            if actual_notional < self.min_chunk_floor_usdt and child_orders:
                # Residue smaller than dust floor is skipped
                break

            if qty <= Decimal("0") or actual_notional <= Decimal("0"):
                break

            if actual_notional > self.max_chunk_cap_usdt:
                raise MicroChildOrderCapExceededError(
                    f"Child order notional {actual_notional} exceeds cap {self.max_chunk_cap_usdt}"
                )

            ts_ms = int(time.time() * 1000)
            cid = f"c=canary-p299-{sym.lower()}-{ts_ms}-{child_idx}-{uuid4().hex[:6]}"

            child = ChildOrderIntention(
                client_order_id=cid,
                child_id=cid,
                parent_order_id=parent_id,
                parent_id=parent_id,
                child_index=child_idx,
                symbol=sym,
                side=side,
                order_type=OrderType.LIMIT,
                price=reference_price,
                quantity=qty,
                notional=actual_notional,
                notional_usdt=actual_notional,
                time_in_force=TimeInForce.GTC,
                status=OrderStatus.OPEN,
                created_time_ms=ts_ms,
            )

            child_orders.append(child)
            remaining_notional -= actual_notional
            child_idx += 1

        return child_orders

    def execute_passive_fill(
        self,
        order: ChildOrderIntention,
        ledger: PaperExecutionLedger,
        fill_price: Decimal | None = None,
        maker_fee_rate: Decimal | None = None,
    ) -> OrderExecutionFill:
        """Execute a simulated passive fill with exact maker fee deduction and ledger update."""
        p = fill_price or order.price
        q = order.quantity
        fee_rate = maker_fee_rate if maker_fee_rate is not None else self.maker_fee_rate

        fill_notional = (p * q).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        fee = (fill_notional * fee_rate).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        fill = OrderExecutionFill(
            fill_id=f"fill-p299-{uuid4().hex[:10]}",
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            fill_price=p,
            fill_quantity=q,
            fill_notional_usdt=fill_notional,
            fee_usdt=fee,
            is_maker=True,
            slippage_bps=Decimal("0"),
            fill_time_ms=order.created_time_ms or int(time.time() * 1000),
        )

        ledger.persist_order(order)
        ledger.persist_fill(fill)
        ledger.record_fill(fill)
        order.status = OrderStatus.FILLED

        # Immediate double-entry verification
        verify_double_entry_zero_drift(ledger)
        return fill


# =====================================================================
# R4: Continuous Mathematical Double-Entry Zero-Drift Governance
# =====================================================================


def compute_double_entry_drift(
    cash: Decimal,
    allocated_margin: Decimal,
    unrealized_pnl: Decimal,
    starting_equity: Decimal,
    realized_pnl: Decimal,
) -> Decimal:
    """Exact double-entry equation balance drift calculation:

    Assets = Cash + Allocated Margin + Unrealized PnL
    Equity = Starting Equity + Realized PnL
    Drift = |Assets - Equity|
    """
    assets = cash + allocated_margin + unrealized_pnl
    equity = starting_equity + realized_pnl
    return abs(assets - equity)


def verify_double_entry_zero_drift(ledger: PaperExecutionLedger) -> Decimal:
    """Verify that double-entry balance equation holds strictly within 1e-15 USDT."""
    drift_val = ledger.drift
    if drift_val >= DOUBLE_ENTRY_MAX_DRIFT:
        raise DoubleEntryDriftError(
            f"Double-entry drift {drift_val} exceeds tolerance {DOUBLE_ENTRY_MAX_DRIFT}"
        )
    return drift_val


def create_portfolio_snapshot(
    ledger: PaperExecutionLedger,
    allocator: DynamicRiskParityAllocator,
    weights: dict[str, Decimal],
    target_allocations: dict[str, Decimal],
    prices: dict[str, Decimal],
    volatilities: dict[str, Decimal],
    jump_intensities: dict[str, Decimal],
    spectral_radius: Decimal,
    regime: RebalanceRegime = RebalanceRegime.NOMINAL,
) -> PortfolioRebalanceSnapshot:
    """Create a fully reconciled PortfolioRebalanceSnapshot."""
    drift_val = verify_double_entry_zero_drift(ledger)
    now_str = datetime.now(UTC).isoformat()

    total_eq = ledger.total_equity
    cash_reserve_pct = (
        (ledger.cash / total_eq * Decimal("100.0")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if total_eq > Decimal("0")
        else Decimal("100.0")
    )

    asset_metrics: dict[str, AssetRiskMetrics] = {}
    total_alloc = Decimal("0.0")

    for sym in allocator.symbols:
        pos = ledger.positions.get(sym)
        cur_alloc = Decimal("0.0")
        if pos is not None:
            if isinstance(pos, dict):
                cur_alloc = Decimal(str(pos.get("allocated_margin", "0")))
            elif hasattr(pos, "allocated_margin"):
                cur_alloc = Decimal(str(pos.allocated_margin))
        total_alloc += cur_alloc

        p = prices.get(sym, DEFAULT_REFERENCE_PRICES.get(sym, Decimal("100.00")))
        vol = volatilities.get(sym, allocator.variance_floor_sigma_min)
        jump = jump_intensities.get(sym, Decimal("0.0"))
        tgt_w = weights.get(sym, Decimal("0.0"))
        cur_w = (
            (cur_alloc / total_eq).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            if total_eq > Decimal("0")
            else Decimal("0.0")
        )
        drift_pct = (abs(cur_w - tgt_w) * Decimal("100.0")).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        tgt_alloc = target_allocations.get(sym, Decimal("0.0"))
        delta_alloc = (tgt_alloc - cur_alloc).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        asset_metrics[sym] = AssetRiskMetrics(
            symbol=sym,
            current_price=p,
            rolling_volatility_sigma=vol,
            jump_intensity_lambda=jump,
            spectral_radius_rho=spectral_radius,
            target_weight=tgt_w,
            current_weight=cur_w,
            drift_pct=drift_pct,
            target_allocation_usdt=tgt_alloc,
            current_allocation_usdt=cur_alloc,
            rebalance_delta_usdt=delta_alloc,
        )

    return PortfolioRebalanceSnapshot(
        timestamp_utc=now_str,
        starting_equity=ledger.starting_equity,
        cash=ledger.cash,
        allocated_margin=ledger.allocated_margin,
        unrealized_pnl=ledger.unrealized_pnl,
        realized_pnl=ledger.realized_pnl,
        total_equity=total_eq,
        double_entry_drift=drift_val,
        zero_drift_verified=True,
        asset_metrics=asset_metrics,
        aggregate_exposure_usdt=ledger.allocated_margin,
        cash_reserve_pct=cash_reserve_pct,
        regime=regime,
    )


# =====================================================================
# Merkle DAG & Verification Simulation Runner (Tracks 1 - 4)
# =====================================================================


def compute_sha256_hash(data: bytes | str) -> str:
    """Compute deterministic SHA-256 hexadecimal hash."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return sha256(payload).hexdigest()


class CanaryPortfolioRebalancingRunner:
    """Deterministic 4-track simulation runner for Phase 299 verification.

    Track 1: Dynamic Hawkes Risk-Parity Allocation
    Track 2: Cross-Asset Spillover Contagion Throttling & Freeze
    Track 3: Micro-Order Rebalancing Execution & Fee Slicing
    Track 4: Full Multi-Cycle Lifecycle & Merkle DAG Hash Chain Persistence
    """

    def __init__(
        self,
        output_dir: Path | str = DEFAULT_PHASE299_OUTPUT_DIR,
        starting_equity: Decimal = STARTING_EQUITY_USDT,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.starting_equity = starting_equity
        self.allocator = DynamicRiskParityAllocator()
        self.guard = CrossAssetSpilloverGuard()
        self.drift_detector = PortfolioDriftDetector()
        self.rebalance_engine = MicroRebalancingEngine()
        self.matching_engine = SimulatedPassiveMatchingEngine()

        self.sqlite_path = self.output_dir / "canary-portfolio-rebalancing-telemetry.sqlite3"
        self.jsonl_path = self.output_dir / "canary-orders.jsonl"
        self.report_path = self.output_dir / "canary-portfolio-rebalancing-report.json"
        self.summary_path = self.output_dir / "portfolio-rebalancing-summary.json"

    def run_track_1_risk_parity_allocation(self) -> dict[str, Any]:
        """Track 1: Verify dynamic risk parity weights and capacity interlocks."""
        # Simulated nominal market state
        vols = {
            "BTCUSDT": Decimal("0.0150"),
            "ETHUSDT": Decimal("0.0220"),
            "SOLUSDT": Decimal("0.0380"),
        }
        jumps = {
            "BTCUSDT": Decimal("0.10"),
            "ETHUSDT": Decimal("0.20"),
            "SOLUSDT": Decimal("0.35"),
        }

        weights = self.allocator.compute_risk_parity_weights(vols, jumps)
        allocations = self.allocator.compute_target_allocations(weights, self.starting_equity)

        # Invariant checks:
        total_alloc = sum(allocations.values(), Decimal("0"))
        if total_alloc > DEFAULT_AGGREGATE_EXPOSURE_CAP_USDT:
            raise AggregateExposureCapExceededError(
                f"Aggregate allocation {total_alloc} exceeds 60.00 USDT"
            )

        for sym, alloc in allocations.items():
            if alloc > DEFAULT_PER_ASSET_MARGIN_CEILING_USDT:
                raise PerAssetMarginCapExceededError(
                    f"Asset {sym} allocation {alloc} exceeds 25.00 USDT ceiling"
                )

        cash_reserve = self.starting_equity - total_alloc
        if cash_reserve < Decimal("40.00"):
            raise CashReserveBufferBreachedError(
                f"Cash reserve {cash_reserve} dropped below 40.00 USDT floor"
            )

        return {
            "track": "track_1_risk_parity_allocation",
            "weights": {s: str(w) for s, w in weights.items()},
            "allocations": {s: str(a) for s, a in allocations.items()},
            "total_allocation_usdt": str(total_alloc),
            "cash_reserve_usdt": str(cash_reserve),
            "status": "PASSED",
        }

    def run_track_2_spillover_contagion_throttling(self) -> dict[str, Any]:
        """Track 2: Verify Hawkes cross-excitation hazard alerts, deallocation, and freezes."""
        # Baseline targets
        allocs = {
            "BTCUSDT": Decimal("25.00"),
            "ETHUSDT": Decimal("18.00"),
            "SOLUSDT": Decimal("15.00"),
        }

        # Scenario A: BTC experiences hazard (severe OFI toxicity and price drop)
        ofis = {"BTCUSDT": Decimal("-0.88"), "ETHUSDT": Decimal("0.10"), "SOLUSDT": Decimal("0.05")}
        drops = {
            "BTCUSDT": Decimal("-0.12"),
            "ETHUSDT": Decimal("-0.02"),
            "SOLUSDT": Decimal("-0.03"),
        }
        radii = {"BTCUSDT": Decimal("0.88"), "ETHUSDT": Decimal("0.40"), "SOLUSDT": Decimal("0.50")}

        eval_res = self.guard.evaluate_spillover_hazards(
            spectral_radii=radii, ofi_toxicities=ofis, price_drops=drops
        )

        # Coupled recipient asset (SOL) must receive capital deallocation
        deallocated = self.guard.apply_deallocation_to_targets(allocs, eval_res)
        sol_dealloc_factor = eval_res.deallocation_factors.get("SOLUSDT", Decimal("0"))
        if sol_dealloc_factor <= Decimal("0"):
            raise PortfolioRebalancingError(
                "Expected positive deallocation factor for coupled recipient SOLUSDT"
            )

        if deallocated["SOLUSDT"] >= allocs["SOLUSDT"]:
            raise PortfolioRebalancingError(
                "Target allocation for SOLUSDT was not dampended under contagion"
            )

        # Scenario B: Supercritical runaway rho >= 1.0 enforces portfolio lockout
        supercritical_eval = self.guard.evaluate_spillover_hazards(
            systemic_spectral_radius=Decimal("1.05")
        )
        if not supercritical_eval.is_portfolio_frozen:
            raise PortfolioRebalancingError(
                "Expected emergency portfolio freeze under supercritical rho >= 1.0"
            )

        return {
            "track": "track_2_spillover_contagion_throttling",
            "sol_deallocation_factor": str(sol_dealloc_factor),
            "original_sol_allocation": str(allocs["SOLUSDT"]),
            "dampened_sol_allocation": str(deallocated["SOLUSDT"]),
            "supercritical_lockout_verified": supercritical_eval.is_portfolio_frozen,
            "status": "PASSED",
        }

    def run_track_3_micro_rebalancing_execution(self) -> dict[str, Any]:
        """Track 3: Verify hysteresis drift, micro child slicing <= 5 USDT, and passive fills."""
        ledger = PaperExecutionLedger(starting_equity=self.starting_equity)
        ref_prices = dict(DEFAULT_REFERENCE_PRICES)

        active_allocs = {
            "BTCUSDT": Decimal("10.00"),
            "ETHUSDT": Decimal("10.00"),
            "SOLUSDT": Decimal("10.00"),
        }
        target_allocs = {
            "BTCUSDT": Decimal("24.00"),
            "ETHUSDT": Decimal("18.00"),
            "SOLUSDT": Decimal("12.00"),
        }

        drift_eval = self.drift_detector.evaluate_drift(
            active_allocations=active_allocs,
            target_allocations=target_allocs,
            total_equity_usdt=self.starting_equity,
        )

        if not drift_eval.rebalance_required:
            raise PortfolioRebalancingError("Expected rebalancing triggered given > 2.5% drift")

        # Slice BTC: delta is +14.00 USDT
        btc_delta = drift_eval.deltas["BTCUSDT"]
        child_orders = self.rebalance_engine.synthesize_rebalancing_orders(
            symbol="BTCUSDT",
            drift_delta_usdt=btc_delta,
            reference_price=ref_prices["BTCUSDT"],
            step_size=self.rebalance_engine.step_sizes["BTCUSDT"],
        )

        if not child_orders:
            raise PortfolioRebalancingError("Failed to synthesize child orders for BTCUSDT")

        total_filled_notional = Decimal("0")
        total_fees = Decimal("0")

        for child in child_orders:
            if child.notional_usdt > DEFAULT_MAX_CHUNK_CAP_USDT:
                raise MicroChildOrderCapExceededError(
                    f"Child order notional {child.notional_usdt} breached 5.00 USDT cap"
                )
            fill = self.rebalance_engine.execute_passive_fill(child, ledger, fill_price=child.price)
            total_filled_notional += fill.fill_notional_usdt
            total_fees += fill.fee_usdt

        drift_val = verify_double_entry_zero_drift(ledger)
        return {
            "track": "track_3_micro_rebalancing_execution",
            "child_orders_count": len(child_orders),
            "total_filled_notional": str(total_filled_notional),
            "total_fees_usdt": str(total_fees),
            "double_entry_drift": str(drift_val),
            "status": "PASSED",
        }

    def run_track_4_full_lifecycle_and_merkle_dag(self) -> CanaryPortfolioRebalancingReport:
        """Track 4: Execute multi-cycle rebalancing lifecycle and persist Merkle DAG artifacts."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ledger = PaperExecutionLedger(
            starting_equity=self.starting_equity,
            sqlite_path=self.sqlite_path,
            jsonl_path=self.jsonl_path,
        )
        ledger.initialize_database()

        ref_prices = dict(DEFAULT_REFERENCE_PRICES)
        vols = {
            "BTCUSDT": Decimal("0.0180"),
            "ETHUSDT": Decimal("0.0250"),
            "SOLUSDT": Decimal("0.0420"),
        }
        jumps = {
            "BTCUSDT": Decimal("0.12"),
            "ETHUSDT": Decimal("0.18"),
            "SOLUSDT": Decimal("0.30"),
        }

        weights = self.allocator.compute_risk_parity_weights(vols, jumps)
        target_allocs = self.allocator.compute_target_allocations(weights, self.starting_equity)

        snapshots: list[PortfolioRebalanceSnapshot] = []
        rebalance_records: list[RebalanceExecutionRecord] = []
        spillover_evals: list[SpilloverGuardEvaluationResult] = []

        # Cycle 1: Initial deployment fills
        cycle1_drift = self.drift_detector.evaluate_drift(
            active_allocations={s: Decimal("0.0") for s in DEFAULT_SYMBOLS},
            target_allocations=target_allocs,
            total_equity_usdt=self.starting_equity,
        )

        for sym in DEFAULT_SYMBOLS:
            delta = cycle1_drift.deltas[sym]
            orders = self.rebalance_engine.synthesize_rebalancing_orders(
                symbol=sym,
                drift_delta_usdt=delta,
                reference_price=ref_prices[sym],
                step_size=self.rebalance_engine.step_sizes[sym],
            )
            filled_notional = Decimal("0")
            fees = Decimal("0")
            for order in orders:
                fill = self.rebalance_engine.execute_passive_fill(
                    order, ledger, fill_price=order.price
                )
                filled_notional += fill.fill_notional_usdt
                fees += fill.fee_usdt

            rebalance_records.append(
                RebalanceExecutionRecord(
                    rebalance_id=f"reb-{sym.lower()}-{uuid4().hex[:8]}",
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    symbol=sym,
                    side=OrderSide.BUY,
                    drift_pct=cycle1_drift.max_drift_pct,
                    rebalance_notional_usdt=abs(delta),
                    sliced_child_orders_count=len(orders),
                    filled_notional_usdt=filled_notional,
                    total_fees_usdt=fees,
                    status="FILLED",
                    child_orders=orders,
                )
            )

        snap1 = create_portfolio_snapshot(
            ledger=ledger,
            allocator=self.allocator,
            weights=weights,
            target_allocations=target_allocs,
            prices=ref_prices,
            volatilities=vols,
            jump_intensities=jumps,
            spectral_radius=self.guard.compute_spectral_radius(),
            regime=RebalanceRegime.NOMINAL,
        )
        snapshots.append(snap1)

        # Cycle 2: Spillover event on BTC causes deallocation on SOL
        ofis = {"BTCUSDT": Decimal("-0.85"), "ETHUSDT": Decimal("0.0"), "SOLUSDT": Decimal("0.0")}
        drops = {"BTCUSDT": Decimal("-0.11"), "ETHUSDT": Decimal("0.0"), "SOLUSDT": Decimal("0.0")}
        guard_eval = self.guard.evaluate_spillover_hazards(ofi_toxicities=ofis, price_drops=drops)
        spillover_evals.append(guard_eval)

        dampened_targets = self.guard.apply_deallocation_to_targets(target_allocs, guard_eval)
        snap2 = create_portfolio_snapshot(
            ledger=ledger,
            allocator=self.allocator,
            weights=weights,
            target_allocations=dampened_targets,
            prices=ref_prices,
            volatilities=vols,
            jump_intensities=jumps,
            spectral_radius=guard_eval.systemic_spectral_radius,
            regime=RebalanceRegime.SPILLOVER_THROTTLED,
        )
        snapshots.append(snap2)

        # Final audit and Merkle DAG generation
        max_drift = max(s.double_entry_drift for s in snapshots)
        now = datetime.now(UTC)
        ts_ms = int(now.timestamp() * 1000)

        report = CanaryPortfolioRebalancingReport(
            verified=True,
            phase="phase_299",
            timestamp_ms=ts_ms,
            timestamp_utc=now.isoformat(),
            regime=RebalanceRegime.NOMINAL,
            circuit_state="NORMAL",
            paper_safe=True,
            execution_authority=False,
            candidates=list(DEFAULT_SYMBOLS),
            snapshots=snapshots,
            spillover_evaluations=spillover_evals,
            rebalance_records=rebalance_records,
            double_entry_verified=True,
            max_observed_drift=max_drift,
            upstream_hash=UPSTREAM_PHASE298_ROOT_HASH,
        )

        # Persist report JSON
        report_json = report.model_dump_json(indent=2)
        phase_hash = compute_sha256_hash(report_json)
        report.phase_hash = phase_hash
        report.merkle_root = compute_sha256_hash(f"{UPSTREAM_PHASE298_ROOT_HASH}:{phase_hash}")

        with open(self.report_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))

        # Persist summary JSON
        summary_payload = {
            "phase": "phase_299",
            "status": "PORTFOLIO_REBALANCING_VERIFIED",
            "timestamp_utc": now.isoformat(),
            "starting_equity_usdt": str(self.starting_equity),
            "final_equity_usdt": str(ledger.total_equity),
            "cash_usdt": str(ledger.cash),
            "allocated_margin_usdt": str(ledger.allocated_margin),
            "realized_pnl_usdt": str(ledger.realized_pnl),
            "total_fees_usdt": str(ledger.total_fees_usdt),
            "max_double_entry_drift": str(max_drift),
            "zero_drift_verified": True,
            "upstream_hash": UPSTREAM_PHASE298_ROOT_HASH,
            "phase_hash": phase_hash,
            "merkle_root": report.merkle_root,
            "candidates": list(DEFAULT_SYMBOLS),
            "upstream_merkle_dag": {
                "phase298_summary_hash": UPSTREAM_PHASE298_ROOT_HASH,
            },
        }
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_payload, f, indent=2)

        return report

    def execute_all_tracks(self) -> dict[str, Any]:
        """Execute Tracks 1-4 and return complete verification summary."""
        t1 = self.run_track_1_risk_parity_allocation()
        t2 = self.run_track_2_spillover_contagion_throttling()
        t3 = self.run_track_3_micro_rebalancing_execution()
        report = self.run_track_4_full_lifecycle_and_merkle_dag()

        return {
            "phase": "phase_299",
            "tracks": {
                "track_1": t1,
                "track_2": t2,
                "track_3": t3,
                "track_4": {
                    "status": "PASSED",
                    "merkle_root": report.merkle_root,
                    "phase_hash": report.phase_hash,
                    "max_observed_drift": str(report.max_observed_drift),
                },
            },
            "verified": True,
        }
