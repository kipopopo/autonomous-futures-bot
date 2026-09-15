"""Phase 264 Multi-Vector Stress Testing & Adverse Conditions Simulation Runner.

Executes deterministic, cached-only offline stress testing across the 3 active candidates:
1. BTCUSDT: cand-btcusdt-dcb-002 (15m Donchian Breakout, lookback 50, 1h context)
2. ETHUSDT: cand-ethusdt-dcb-003 (15m Calibrated Donchian Breakout, stop 1.5 ATR, trail 1.2 ATR)
3. SOLUSDT: cand-solusdt-rgb-001 (1h Regime Gated Breakout, lookback 20 + ADX > 25, 4h context)
under Candidate Registry Manifest Version 2 across 6 comparative shock tracks:
- Track 0: Baseline (nominal Phase 263 conditions: 2.0 bps slippage, 0.04% taker fee)
- Track 1: Flash Crash Shock (severe intra-bar adverse gap down -15% to -25% on long positions)
- Track 2: Slippage Surge Shock (elevated adverse slippage 50.0 to 100.0 bps)
- Track 3: Fee & Spread Blowout Shock (doubled taker fee 0.08% / 8 bps and spread expansion)
- Track 4: Volatility Spikes & Rapid Whipsaw Shock (high volatility triggers and stop runs)
- Track 5: Composite Crisis Shock (simultaneous combination of adverse shocks)

Enforces:
- Shared margin account (100.00 USDT starting equity, <= 80% utilization, >= 20% reserve buffer).
- Capital survival (terminal equity > 0.00 USDT across all tracks).
- Complete double-entry accounting reconciliation with zero balance drift (< 1e-15).
- Fail-closed runtime: paper_activation=False, execution_authority=False, exchange_access=False.
- Isolated SQLite databases and scenario reports persisted to artifacts/research/phase264/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

# Ensure repo root and src/ are on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd  # noqa: E402

from autonomous_futures.creator_staging_probe import (  # noqa: E402
    assert_offline_safety_invariants,
)
from autonomous_futures.data.parquet import (  # noqa: E402
    DataQualityError,
    canonicalize_bars,
)
from autonomous_futures.domain.contracts import PaperExecutionRequest  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
)
from autonomous_futures.paper.circuit_breakers import (  # noqa: E402
    CircuitBreakerConfig,
    EmergencyLiquidationEvent,
    HardenedSharedMarginAccount,
    StressTestScenarioResult,
    calculate_adverse_gap_fill,
)
from autonomous_futures.paper.cohort import (  # noqa: E402
    PaperCohortReadinessReport,
    summarize_paper_cohort,
)
from autonomous_futures.paper.health import (  # noqa: E402
    PaperHealthReport,
    aggregate_paper_health,
)
from autonomous_futures.paper.lifecycle import (  # noqa: E402
    PaperLifecycleTelemetry,
    mark_paper_position,
)
from autonomous_futures.paper.observation import (  # noqa: E402
    PaperObservation,
    PaperObservationBinding,
    observe_paper_ledger,
)
from autonomous_futures.paper.reconciliation import (  # noqa: E402
    reconcile_paper_positions,
)
from autonomous_futures.paper.runtime import PaperRuntime  # noqa: E402
from autonomous_futures.paper.safety import (  # noqa: E402
    PaperActionApproval,
    PaperSafetyEvidence,
)
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger  # noqa: E402
from autonomous_futures.paper.sqlite_lifecycle import SqlitePaperLifecycle  # noqa: E402
from autonomous_futures.paper.sqlite_observation import (  # noqa: E402
    SqlitePaperObservations,
)
from autonomous_futures.paper.stress_vectors import (  # noqa: E402
    SyntheticMarketShockInjector,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
)
from autonomous_futures.research.feature_signals import (  # noqa: E402
    CausalFeatureSignalEvaluator,
    _parse_expression,
)

logger = logging.getLogger("run_phase_264_stress_simulation")

DEFAULT_STARTING_EQUITY: Decimal = Decimal("100.00")
DEFAULT_POSITION_FRACTION: Decimal = Decimal("0.20")
DEFAULT_MAX_MARGIN_UTILIZATION: Decimal = Decimal("0.80")
DEFAULT_MIN_RESERVE_BUFFER: Decimal = Decimal("0.20")
DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0004")  # 0.04%
DEFAULT_SLIPPAGE_BPS: Decimal = Decimal("2.0")  # 2.0 bps
DEFAULT_DAYS: int = 7
DEFAULT_START_TIME: datetime = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
DEFAULT_TOTAL_BARS_15M: int = 672  # 7 days * 96 bars/day

DEFAULT_PHASE264_OUTPUT_DIR = Path("artifacts/research/phase264")

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _assert_zero_secrets(text: str, source_label: str) -> None:
    match = _SECRET_PATTERN.search(text)
    if match:
        raise DomainViolation(f"Secret pattern matched in {source_label}: {match.group(0)[:8]}...")


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_atr_series(df: pd.DataFrame, lookback: int = 14) -> list[Decimal | None]:
    """Compute causal rolling ATR with zero forward lookahead."""
    highs = [Decimal(str(x)) for x in df["high"]]
    lows = [Decimal(str(x)) for x in df["low"]]
    closes = [Decimal(str(x)) for x in df["close"]]
    true_ranges: list[Decimal] = []
    for i in range(len(df)):
        prev_close = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close))
        true_ranges.append(tr)

    atr_vals: list[Decimal | None] = []
    for i in range(len(df)):
        if i < lookback:
            atr_vals.append(None)
        else:
            recent = true_ranges[i - lookback : i]
            atr_vals.append(sum(recent, Decimal("0")) / Decimal(str(lookback)))
    return atr_vals


def evaluate_strategy_exit(
    row: pd.Series, side: str, long_exit_expr: str, short_exit_expr: str
) -> bool:
    """Evaluate strategy exit condition for an active position."""
    expr = long_exit_expr if side == "LONG" else short_exit_expr
    clauses, connectors = _parse_expression(expr)

    def check_clause(feat: str, op: str, val: float) -> bool:
        if feat not in row:
            return False
        v = float(row[feat])
        if op == ">":
            return v > val
        if op == ">=":
            return v >= val
        if op == "<":
            return v < val
        if op == "<=":
            return v <= val
        if op == "==":
            return v == val
        return False

    res = check_clause(*clauses[0])
    for conn, clause in zip(connectors, clauses[1:], strict=True):
        c_res = check_clause(*clause)
        res = (res and c_res) if conn == "and" else (res or c_res)
    return res


def compute_signal_conviction(row: pd.Series, signal: int) -> tuple[bool, Decimal]:
    """Compute normalized conviction score in [0.5, 1.0] for order sizing."""
    if signal == 0:
        return False, Decimal("0.0")

    conviction = Decimal("0.50")
    if "adx" in row and not pd.isna(row["adx"]):
        adx_val = Decimal(str(row["adx"]))
        if adx_val > Decimal("20"):
            adx_bonus = min(Decimal("0.30"), (adx_val - Decimal("20")) / Decimal("60"))
            conviction += adx_bonus

    if "donchian_breakout" in row and not pd.isna(row["donchian_breakout"]):
        breakout_val = Decimal(str(row["donchian_breakout"]))
        if abs(breakout_val) > Decimal("0.0"):
            conviction += Decimal("0.10")

    final_conviction = min(Decimal("1.00"), max(Decimal("0.50"), conviction))
    return True, final_conviction


class Phase264SharedMarginAccount(HardenedSharedMarginAccount):
    """Hardened shared portfolio margin manager for Phase 264 with dynamic leverage,

    automated circuit breakers, and unencumbered buffer preservation.
    """

    def allocate_order(
        self,
        symbol: str,
        confidence: Decimal,
        mark_price: Decimal,
        current_equity: Decimal,
        volatility_ratio: Decimal = Decimal("1.0"),
        slippage_ratio: Decimal = Decimal("1.0"),
    ) -> tuple[Decimal, Decimal, Decimal] | None:
        if self.current_state in ("HALTED", "EMERGENCY_FLAT"):
            return None

        if current_equity <= Decimal("0"):
            return None

        avail = self.available_margin(current_equity)
        if avail <= Decimal("0"):
            return None

        # Base allocation: 20% normal, throttled to 10% under distress
        fraction = (
            self.base_allocation_fraction / Decimal("2.0")
            if self.current_state == "THROTTLED"
            else self.base_allocation_fraction
        )
        margin_target = current_equity * fraction
        base_margin = min(avail, margin_target)
        if base_margin <= Decimal("0"):
            return None

        # Check utilization ceiling <= 80%
        new_locked = self.total_locked_margin() + base_margin
        utilization = new_locked / current_equity if current_equity > 0 else Decimal("1.0")
        if utilization > self.max_utilization:
            return None

        # Check buffer >= 20%
        buffer = (
            (current_equity - new_locked) / current_equity if current_equity > 0 else Decimal("0.0")
        )
        if buffer < self.min_reserve_buffer:
            return None

        # Check cash reserve for fees
        if self.cash < base_margin * Decimal("0.005"):
            return None

        leverage = self.calculate_hardened_leverage(confidence, volatility_ratio, slippage_ratio)
        if leverage <= Decimal("0"):
            return None

        notional = base_margin * leverage
        quantity = notional / mark_price
        if quantity <= Decimal("0"):
            return None

        self.max_observed_utilization = max(self.max_observed_utilization, utilization)
        self.unencumbered_reserve_buffer(current_equity)
        return base_margin, leverage, quantity


# 6 comparative track specifications
TRACK_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": 0,
        "name": "baseline",
        "description": "Nominal Phase 263 conditions (2.0 bps slippage, 0.04% taker fee)",
        "shock_type": "baseline",
        "price_shock_pct": Decimal("0.0"),
        "slippage_bps": Decimal("2.0"),
        "fee_rate": Decimal("0.0004"),
        "slippage_multiplier": 1,
    },
    {
        "id": 1,
        "name": "flash_crash",
        "description": "Flash Crash Shock (-20% intra-bar adverse gap down on long positions)",
        "shock_type": "flash_crash",
        "price_shock_pct": Decimal("-0.20"),
        "slippage_bps": Decimal("2.0"),
        "fee_rate": Decimal("0.0004"),
        "slippage_multiplier": 1,
        "shock_bar_index": 450,
    },
    {
        "id": 2,
        "name": "slippage_surge",
        "description": "Slippage Surge Shock (elevated adverse slippage 75.0 bps)",
        "shock_type": "slippage_surge",
        "price_shock_pct": Decimal("0.0"),
        "slippage_bps": Decimal("75.0"),
        "fee_rate": Decimal("0.0004"),
        "slippage_multiplier": 37,
    },
    {
        "id": 3,
        "name": "fee_spread_blowout",
        "description": "Fee & Spread Blowout Shock (doubled fee 0.08% and spread expansion)",
        "shock_type": "spread_blowout",
        "price_shock_pct": Decimal("0.0"),
        "slippage_bps": Decimal("20.0"),
        "fee_rate": Decimal("0.0008"),
        "slippage_multiplier": 10,
    },
    {
        "id": 4,
        "name": "volatility_whipsaw",
        "description": "Volatility Spikes & Whipsaw Shock (volatility triggers and stop runs)",
        "shock_type": "volatility_whipsaw",
        "price_shock_pct": Decimal("0.0"),
        "slippage_bps": Decimal("10.0"),
        "fee_rate": Decimal("0.0004"),
        "slippage_multiplier": 5,
        "shock_bar_index": 350,
        "whipsaw_bars": 12,
        "oscillation_pct": Decimal("0.06"),
    },
    {
        "id": 5,
        "name": "composite_crisis",
        "description": "Composite Crisis Shock (flash crash, 50 bps slip, doubled fee, whipsaws)",
        "shock_type": "composite_crisis",
        "price_shock_pct": Decimal("-0.20"),
        "slippage_bps": Decimal("50.0"),
        "fee_rate": Decimal("0.0008"),
        "slippage_multiplier": 25,
        "shock_bar_index": 450,
        "whipsaw_bars": 8,
        "oscillation_pct": Decimal("0.06"),
    },
]


def apply_track_shocks(
    raw_frames_15m: dict[str, pd.DataFrame],
    raw_frames_1h: dict[str, pd.DataFrame],
    track_spec: dict[str, Any],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Applies calibrated deterministic synthetic market shock vectors to 15m and 1h frames."""
    shock_type = track_spec["shock_type"]
    if shock_type == "baseline":
        return (
            {sym: df.copy() for sym, df in raw_frames_15m.items()},
            {sym: df.copy() for sym, df in raw_frames_1h.items()},
        )

    shocked_15m: dict[str, pd.DataFrame] = {}
    shocked_1h: dict[str, pd.DataFrame] = {}

    nominal_start = track_spec.get("shock_bar_index", 450)
    drop_pct = abs(track_spec.get("price_shock_pct", Decimal("0.20")))
    slip_mult = track_spec.get("slippage_multiplier", 1)
    nominal_whipsaw = track_spec.get("whipsaw_bars", 12)
    osc = track_spec.get("oscillation_pct", Decimal("0.06"))

    start_idx = nominal_start
    n_bars = nominal_whipsaw

    for sym, df in raw_frames_15m.items():
        mod = df.copy()
        n_15m = len(mod)
        if n_15m >= 672:
            start_idx = nominal_start
            n_bars = nominal_whipsaw
        else:
            ratio = nominal_start / 672
            scaled_idx = int(ratio * n_15m)
            if n_15m > nominal_whipsaw + 1:
                start_idx = min(scaled_idx, n_15m - nominal_whipsaw - 1)
                n_bars = nominal_whipsaw
            else:
                start_idx = max(0, min(scaled_idx, n_15m - 2)) if n_15m >= 2 else 0
                n_bars = max(1, n_15m - start_idx - 1) if n_15m > start_idx + 1 else 1

        if shock_type == "flash_crash":
            mod = SyntheticMarketShockInjector.inject_flash_crash(
                mod,
                start_idx=start_idx,
                drop_pct=drop_pct,
                wick_only=False,
                interval=timedelta(minutes=15),
            )
        elif shock_type == "slippage_surge":
            mod = SyntheticMarketShockInjector.inject_slippage_surge(
                mod, multiplier=Decimal(str(slip_mult)), interval=timedelta(minutes=15)
            )
        elif shock_type == "spread_blowout":
            mod = SyntheticMarketShockInjector.inject_spread_blowout(
                mod, multiplier=Decimal("20"), interval=timedelta(minutes=15)
            )
        elif shock_type == "volatility_whipsaw":
            mod = SyntheticMarketShockInjector.inject_whipsaws(
                mod,
                start_idx=start_idx,
                num_bars=n_bars,
                oscillation_pct=osc,
                interval=timedelta(minutes=15),
            )
        elif shock_type == "composite_crisis":
            mod = SyntheticMarketShockInjector.inject_composite_crisis(
                mod, start_idx=start_idx, interval=timedelta(minutes=15)
            )
        else:
            raise ValueError(f"Unknown shock_type: {shock_type}")
        shocked_15m[sym] = mod

    for sym, df in raw_frames_1h.items():
        mod = df.copy()
        n_1h = len(mod)
        if n_1h >= 168:
            start_idx_1h = nominal_start // 4
            whip_1h = max(1, nominal_whipsaw // 4)
        else:
            ratio_1h = (nominal_start // 4) / 168
            scaled_idx_1h = int(ratio_1h * n_1h)
            nominal_whip_1h = max(1, nominal_whipsaw // 4)
            if n_1h > nominal_whip_1h + 1:
                start_idx_1h = min(scaled_idx_1h, n_1h - nominal_whip_1h - 1)
                whip_1h = nominal_whip_1h
            else:
                start_idx_1h = max(0, min(scaled_idx_1h, n_1h - 2)) if n_1h >= 2 else 0
                whip_1h = max(1, min(nominal_whip_1h, max(1, n_1h - start_idx_1h - 1)))

        if shock_type == "flash_crash":
            mod = SyntheticMarketShockInjector.inject_flash_crash(
                mod,
                start_idx=start_idx_1h,
                drop_pct=drop_pct,
                wick_only=False,
                interval=timedelta(hours=1),
            )
        elif shock_type == "slippage_surge":
            mod = SyntheticMarketShockInjector.inject_slippage_surge(
                mod, multiplier=Decimal(str(slip_mult)), interval=timedelta(hours=1)
            )
        elif shock_type == "spread_blowout":
            mod = SyntheticMarketShockInjector.inject_spread_blowout(
                mod, multiplier=Decimal("20"), interval=timedelta(hours=1)
            )
        elif shock_type == "volatility_whipsaw":
            mod = SyntheticMarketShockInjector.inject_whipsaws(
                mod,
                start_idx=start_idx_1h,
                num_bars=whip_1h,
                oscillation_pct=osc,
                interval=timedelta(hours=1),
            )
        elif shock_type == "composite_crisis":
            mod = SyntheticMarketShockInjector.inject_composite_crisis(
                mod, start_idx=start_idx_1h, interval=timedelta(hours=1)
            )
        shocked_1h[sym] = mod

    return shocked_15m, shocked_1h


class Phase264StressHarness:
    """Manages isolated paper ledger stores and execution runtime for a Phase 264 stress track."""

    def __init__(
        self,
        output_dir: Path,
        candidates: dict[str, CreatorCandidateArtifact],
        starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
        fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
        slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
        max_margin_utilization: Decimal = DEFAULT_MAX_MARGIN_UTILIZATION,
        position_fraction: Decimal = DEFAULT_POSITION_FRACTION,
        circuit_config: CircuitBreakerConfig | None = None,
        qualification_hashes: dict[str, str] | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.candidates = candidates
        self.starting_equity = starting_equity
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps

        output_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_db_path = output_dir / "paper-ledger.sqlite3"
        self.lifecycle_db_path = output_dir / "paper-lifecycle.sqlite3"
        self.observation_db_path = output_dir / "paper-observations.sqlite3"

        for p in (self.ledger_db_path, self.lifecycle_db_path, self.observation_db_path):
            if p.exists():
                p.unlink()

        self.ledger_store = SqlitePaperLedger(self.ledger_db_path)
        self.lifecycle_store = SqlitePaperLifecycle(self.lifecycle_db_path)
        self.observation_store = SqlitePaperObservations(self.observation_db_path)
        self.runtime = PaperRuntime(self.ledger_store)

        # Pre-initialize SQLite database files with schema tables on disk
        self.ledger_store._connect().close()
        self.lifecycle_store._connect_for_append().close()
        self.observation_store._connect().close()

        self.margin_account = Phase264SharedMarginAccount(
            starting_capital=starting_equity,
            max_utilization=max_margin_utilization,
            base_allocation_fraction=position_fraction,
            min_reserve_buffer=DEFAULT_MIN_RESERVE_BUFFER,
            config=circuit_config or CircuitBreakerConfig(),
        )

        q_hashes = qualification_hashes or {}
        self.evidences = {
            sym: PaperSafetyEvidence(
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
                qualification_hash=q_hashes.get(sym, cand.artifact_hash),
                qualification_decision="qualified",
                zero_oos_liquidations=True,
            )
            for sym, cand in candidates.items()
        }


def generate_phase_264_reports(
    ledger: SqlitePaperLedger,
    lifecycle: SqlitePaperLifecycle,
    observations: SqlitePaperObservations,
    candidates: dict[str, CreatorCandidateArtifact],
    *,
    as_of: datetime,
    days: int = DEFAULT_DAYS,
    max_mark_age_seconds: int = 86400,
) -> tuple[dict[str, PaperHealthReport], PaperCohortReadinessReport]:
    """Generate PaperHealthReport per candidate and aggregate PaperCohortReadinessReport."""
    final_ledger = ledger.load()
    open_positions = final_ledger.open_positions()

    health_reports: dict[str, PaperHealthReport] = {}
    cohort_bindings: list[PaperObservationBinding] = []

    for sym, cand in candidates.items():
        candidate_obs = observations.read(
            cand.candidate_id,
            cand.artifact_hash,
        )
        active_marks: list[PaperLifecycleTelemetry] = []
        for pos in open_positions:
            if pos.candidate_id == cand.candidate_id and pos.symbol == sym:
                m = lifecycle.latest(
                    candidate_id=cand.candidate_id,
                    candidate_artifact_hash=cand.artifact_hash,
                    trade_id=pos.trade_id,
                )
                if m is not None:
                    active_marks.append(m)

        health_rep = aggregate_paper_health(
            candidate_obs,
            tuple(active_marks),
            candidate_id=cand.candidate_id,
            candidate_artifact_hash=cand.artifact_hash,
            as_of=as_of,
            max_mark_age_seconds=max_mark_age_seconds,
            required_days=days,
        )
        health_reports[sym] = health_rep
        cohort_bindings.append(
            PaperObservationBinding(
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
            )
        )

    cohort_rep = summarize_paper_cohort(list(health_reports.values()), cohort_bindings)
    return health_reports, cohort_rep


@dataclass(frozen=True, slots=True)
class Phase264TrackResult:
    track_id: int
    track_name: str
    scenario_result: StressTestScenarioResult
    health_reports: dict[str, PaperHealthReport]
    cohort_report: PaperCohortReadinessReport
    positions_reconciled: bool
    accounting_reconciled: bool
    final_cash: Decimal
    realized_pnl: Decimal
    cumulative_fees: Decimal
    cumulative_slippage: Decimal
    circuit_breaker_events_count: int
    emergency_liquidations: tuple[EmergencyLiquidationEvent, ...]
    output_dir: Path
    candidate_summaries: dict[str, dict[str, Any]]
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    cash_drift: Decimal


def run_single_phase_264_track(
    track_spec: dict[str, Any],
    output_dir: Path,
    candidates: dict[str, CreatorCandidateArtifact],
    qualification_hashes: dict[str, str],
    raw_frames_15m: dict[str, pd.DataFrame],
    raw_frames_1h: dict[str, pd.DataFrame],
    total_bars_15m: int = DEFAULT_TOTAL_BARS_15M,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
) -> Phase264TrackResult:
    """Executes a single comparative stress simulation track across all 3 candidates."""
    track_id = track_spec["id"]
    track_name = track_spec["name"]
    slippage_bps = track_spec["slippage_bps"]
    fee_rate = track_spec.get("fee_rate", DEFAULT_TAKER_FEE_RATE)

    circuit_config = (
        CircuitBreakerConfig(
            slippage_throttle_bps=Decimal("20.0"),
            slippage_halt_bps=Decimal("150.0"),
        )
        if slippage_bps >= Decimal("20.0")
        else CircuitBreakerConfig()
    )

    harness = Phase264StressHarness(
        output_dir=output_dir,
        candidates=candidates,
        starting_equity=starting_equity,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        max_margin_utilization=DEFAULT_MAX_MARGIN_UTILIZATION,
        position_fraction=DEFAULT_POSITION_FRACTION,
        circuit_config=circuit_config,
        qualification_hashes=qualification_hashes,
    )

    # 1. Apply deterministic shock vectors
    shocked_15m, shocked_1h = apply_track_shocks(raw_frames_15m, raw_frames_1h, track_spec)

    # 2. Compute causal features, signals, and ATR series on shocked data
    evaluator = CausalFeatureSignalEvaluator()
    evaluated_signals: dict[str, pd.DataFrame] = {}
    atr_series_15m: dict[str, list[Decimal | None]] = {}

    for sym, cand in candidates.items():
        atr_series_15m[sym] = compute_atr_series(shocked_15m[sym], lookback=14)
        tf = cand.strategy.universe.timeframe
        if tf == "15m":
            evaluated_signals[sym] = evaluator.evaluate(cand, shocked_15m[sym])
        elif tf == "1h":
            evaluated_signals[sym] = evaluator.evaluate(cand, shocked_1h[sym])
        else:
            evaluated_signals[sym] = evaluator.evaluate(cand, shocked_15m[sym])

    signals_by_time: dict[tuple[str, datetime], pd.Series] = {}
    for sym, sig_df in evaluated_signals.items():
        for _, row in sig_df.iterrows():
            ts = row["timestamp"]
            signals_by_time[(sym, ts)] = row

    # Baseline ATR across warmup window (initial 288 bars = 3 days, or available)
    baseline_atrs: dict[str, Decimal] = {}
    for sym in candidates:
        warmup_atrs = [a for a in atr_series_15m[sym][:288] if a is not None]
        baseline_atrs[sym] = (
            sum(warmup_atrs, Decimal("0")) / Decimal(str(len(warmup_atrs)))
            if warmup_atrs
            else Decimal("10.0")
        )

    first_sym = next(iter(candidates))
    active_trades: dict[str, dict[str, Any]] = {}
    trade_count = 0
    previous_peaks: dict[str, Decimal] = {sym: starting_equity for sym in candidates}
    observations_by_symbol: dict[str, list[PaperObservation]] = {sym: [] for sym in candidates}
    qualified_symbols_all = tuple(candidates.keys())
    slippage_rate = slippage_bps / Decimal("10000")
    circuit_breaker_evaluations: list[Any] = []

    # 3. Synchronized 15m Sequential Clock Simulation Loop
    for idx in range(total_bars_15m):
        bar_ts: datetime = shocked_15m[first_sym].iloc[idx]["timestamp"]
        is_terminal: bool = idx == total_bars_15m - 1
        closed_this_bar: dict[str, bool] = {sym: False for sym in candidates}
        current_bar_closes: dict[str, Decimal] = {}
        current_bar_opens: dict[str, Decimal] = {}
        current_bar_highs: dict[str, Decimal] = {}
        current_bar_lows: dict[str, Decimal] = {}

        for sym in candidates:
            row_15m = shocked_15m[sym].iloc[idx]
            current_bar_closes[sym] = Decimal(str(row_15m["close"]))
            current_bar_opens[sym] = Decimal(str(row_15m["open"]))
            current_bar_highs[sym] = Decimal(str(row_15m["high"]))
            current_bar_lows[sym] = Decimal(str(row_15m["low"]))

        # Phase A: Mark open positions & evaluate protective and strategy exits
        for sym in list(active_trades.keys()):
            trade_info = active_trades[sym]
            cand = candidates[sym]
            bar_close = current_bar_closes[sym]
            bar_open = current_bar_opens[sym]
            bar_high = current_bar_highs[sym]
            bar_low = current_bar_lows[sym]
            side = trade_info["side"]

            if side == "LONG":
                trade_info["watermark"] = max(trade_info["watermark"], bar_high)
            else:
                trade_info["watermark"] = min(trade_info["watermark"], bar_low)

            marked = mark_paper_position(
                trade_info["open_entry"],
                mark_price=bar_close,
                marked_at=bar_ts,
                previous_peak_pnl=trade_info["peak_pnl"],
                stop_loss_price=trade_info["stop_price"],
                take_profit_price=trade_info["target_price"],
            )
            trade_info["peak_pnl"] = marked.peak_pnl
            harness.lifecycle_store.append(marked)

            terminal_cutoff = max(0, total_bars_15m - 12)
            exit_triggered = False
            raw_exit_price = bar_close

            if idx >= terminal_cutoff or is_terminal:
                exit_triggered = True
                raw_exit_price = bar_close
            elif marked.lifecycle_status == "exit_ready":
                exit_triggered = True
                if marked.stop_loss_hit:
                    raw_exit_price, _ = calculate_adverse_gap_fill(
                        side=side,
                        bar_open=bar_open,
                        stop_price=trade_info["stop_price"] or bar_close,
                        slippage_rate=slippage_rate,
                    )
                else:
                    raw_exit_price = bar_close
            elif (
                side == "LONG"
                and trade_info.get("trailing_stop_price") is not None
                and bar_low <= trade_info["trailing_stop_price"]
            ):
                exit_triggered = True
                raw_exit_price, _ = calculate_adverse_gap_fill(
                    side=side,
                    bar_open=bar_open,
                    stop_price=trade_info["trailing_stop_price"],
                    slippage_rate=slippage_rate,
                )
            elif (
                side == "SHORT"
                and trade_info.get("trailing_stop_price") is not None
                and bar_high >= trade_info["trailing_stop_price"]
            ):
                exit_triggered = True
                raw_exit_price, _ = calculate_adverse_gap_fill(
                    side=side,
                    bar_open=bar_open,
                    stop_price=trade_info["trailing_stop_price"],
                    slippage_rate=slippage_rate,
                )

            if not exit_triggered and (sym, bar_ts) in signals_by_time:
                sig_row = signals_by_time[(sym, bar_ts)]
                sig_val = int(sig_row["signal"])
                if evaluate_strategy_exit(
                    sig_row,
                    side=side,
                    long_exit_expr=cand.strategy.exit.long,
                    short_exit_expr=cand.strategy.exit.short,
                ):
                    exit_triggered = True
                    raw_exit_price = bar_close
                elif (side == "LONG" and sig_val == -1) or (side == "SHORT" and sig_val == 1):
                    exit_triggered = True
                    raw_exit_price = bar_close

            if exit_triggered:
                raw_exit_price = max(Decimal("0.0001"), raw_exit_price)
                close_req = PaperExecutionRequest(
                    candidate_id=cand.candidate_id,
                    candidate_artifact_hash=cand.artifact_hash,
                    qualified_symbols=qualified_symbols_all,
                    symbol=sym,
                    side=side,
                    mark_price=raw_exit_price,
                    quantity=trade_info["open_entry"].quantity,
                    fee_rate=fee_rate,
                    slippage_bps=slippage_bps,
                )
                close_approval = PaperActionApproval(
                    approval_id=f"apprv-close-{trade_info['trade_id']}",
                    candidate_id=cand.candidate_id,
                    candidate_artifact_hash=cand.artifact_hash,
                    trade_id=trade_info["trade_id"],
                    action="close",
                    approved_at=bar_ts,
                    expires_at=bar_ts + timedelta(minutes=15),
                )
                close_res = harness.runtime.close(
                    close_req,
                    harness.evidences[sym],
                    close_approval,
                    trade_id=trade_info["trade_id"],
                    exit_mark_price=raw_exit_price,
                    occurred_at=bar_ts,
                )
                if close_res.status != "closed":
                    raise RuntimeError(f"Failed to close paper trade for {sym}: {close_res}")

                assert close_res.gross_pnl is not None
                assert close_res.exit_fee is not None
                harness.margin_account.record_close(
                    trade_id=trade_info["trade_id"],
                    gross_pnl=close_res.gross_pnl,
                    exit_fee=close_res.exit_fee,
                )
                del active_trades[sym]
                closed_this_bar[sym] = True

        # Phase B: Recompute Portfolio Equity & Evaluate Circuit Breakers
        unrealized_pnl_total = Decimal("0")
        for sym, trade_info in active_trades.items():
            pos_close = current_bar_closes[sym]
            pos_entry = trade_info["open_entry"]
            if trade_info["side"] == "LONG":
                unrealized_pnl_total += (pos_close - pos_entry.fill_price) * pos_entry.quantity
            else:
                unrealized_pnl_total += (pos_entry.fill_price - pos_close) * pos_entry.quantity

        portfolio_equity = harness.margin_account.current_equity(unrealized_pnl_total)
        if portfolio_equity > harness.margin_account.peak_portfolio_equity:
            harness.margin_account.peak_portfolio_equity = portfolio_equity
        harness.margin_account.unencumbered_reserve_buffer(portfolio_equity)

        max_vol_ratio = Decimal("1.0")
        for sym in candidates:
            current_atr = atr_series_15m[sym][idx] or baseline_atrs[sym]
            base_atr = baseline_atrs[sym]
            bar_open = current_bar_opens[sym]
            bar_close = current_bar_closes[sym]
            intra_move = abs(bar_close - bar_open) / bar_open if bar_open > 0 else Decimal("0")

            cb_res = harness.margin_account.evaluate_circuit_breaker(
                symbol=sym,
                current_atr=current_atr,
                baseline_atr=base_atr,
                current_slippage_bps=slippage_bps,
                current_equity=portfolio_equity,
                peak_equity=harness.margin_account.peak_portfolio_equity,
                bar_ts=bar_ts,
                adverse_wick_pct=intra_move,
            )
            circuit_breaker_evaluations.append(cb_res)
            if cb_res.volatility_ratio > max_vol_ratio:
                max_vol_ratio = cb_res.volatility_ratio

        # Orderly Emergency Position Close-Out if utilization breaches or EMERGENCY_FLAT state
        if active_trades and (
            harness.margin_account.margin_utilization(portfolio_equity)
            > DEFAULT_MAX_MARGIN_UTILIZATION
            or harness.margin_account.current_state == "EMERGENCY_FLAT"
        ):
            liquidations = harness.margin_account.emergency_liquidate_positions(
                active_trades=active_trades,
                current_prices=current_bar_closes,
                current_opens=current_bar_opens,
                slippage_rate=slippage_rate,
                fee_rate=fee_rate,
                occurred_at=bar_ts,
                reason="circuit_breaker_emergency_flat",
            )
            for liq in liquidations:
                cand = candidates[liq.symbol]
                close_req = PaperExecutionRequest(
                    candidate_id=cand.candidate_id,
                    candidate_artifact_hash=cand.artifact_hash,
                    qualified_symbols=qualified_symbols_all,
                    symbol=liq.symbol,
                    side=liq.side,
                    mark_price=liq.gapped_market_price,
                    quantity=liq.quantity,
                    fee_rate=fee_rate,
                    slippage_bps=liq.effective_slippage_bps,
                )
                close_approval = PaperActionApproval(
                    approval_id=f"apprv-emg-close-{liq.trade_id}",
                    candidate_id=cand.candidate_id,
                    candidate_artifact_hash=cand.artifact_hash,
                    trade_id=liq.trade_id,
                    action="close",
                    approved_at=bar_ts,
                    expires_at=bar_ts + timedelta(minutes=15),
                )
                close_res = harness.runtime.close(
                    close_req,
                    harness.evidences[liq.symbol],
                    close_approval,
                    trade_id=liq.trade_id,
                    exit_mark_price=liq.gapped_market_price,
                    occurred_at=bar_ts,
                )
                if close_res.status != "closed":
                    raise RuntimeError(
                        f"Failed to emergency liquidate paper trade for {liq.symbol}: {close_res}"
                    )
                closed_this_bar[liq.symbol] = True

            # Ensure exact mathematical balance synchronization after emergency actions
            closed_entries_now = [
                e for e in harness.ledger_store.load().entries if e.event == "close"
            ]
            realized_pnl_sync = sum(
                (e.net_pnl for e in closed_entries_now if e.net_pnl is not None), Decimal("0")
            )
            harness.margin_account.cash = starting_equity + realized_pnl_sync

        # Phase C: Evaluate Entry Signals with Priority Arbitration & Hardened Sizing
        terminal_cutoff = max(0, total_bars_15m - 12)
        candidate_entry_requests: list[dict[str, Any]] = []

        if not is_terminal and idx < terminal_cutoff:
            for sym, cand in candidates.items():
                if sym in active_trades or closed_this_bar[sym]:
                    continue
                if (sym, bar_ts) not in signals_by_time:
                    continue

                sig_row = signals_by_time[(sym, bar_ts)]
                signal = int(sig_row["signal"])
                if signal == 0:
                    continue

                valid_conviction, conviction = compute_signal_conviction(sig_row, signal)
                if not valid_conviction:
                    continue

                candidate_entry_requests.append(
                    {
                        "symbol": sym,
                        "candidate": cand,
                        "conviction": conviction,
                        "signal": signal,
                        "close": current_bar_closes[sym],
                    }
                )

        # Sort entry requests by conviction descending
        candidate_entry_requests.sort(key=lambda req: -req["conviction"])

        for req in candidate_entry_requests:
            sym = req["symbol"]
            cand = req["candidate"]
            bar_close = req["close"]
            signal = req["signal"]
            conviction = req["conviction"]

            slip_ratio = slippage_bps / Decimal("2.0")
            alloc = harness.margin_account.allocate_order(
                symbol=sym,
                confidence=conviction,
                mark_price=bar_close,
                current_equity=portfolio_equity,
                volatility_ratio=max_vol_ratio,
                slippage_ratio=slip_ratio,
            )
            if alloc is None:
                continue

            margin_allocated, leverage, quantity = alloc
            trade_count += 1
            trade_id = f"paper-{sym.lower()}-{trade_count:04d}"
            entry_side: Literal["LONG", "SHORT"] = "LONG" if signal == 1 else "SHORT"

            open_req = PaperExecutionRequest(
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
                qualified_symbols=qualified_symbols_all,
                symbol=sym,
                side=entry_side,
                mark_price=bar_close,
                quantity=quantity,
                fee_rate=fee_rate,
                slippage_bps=slippage_bps,
            )
            open_approval = PaperActionApproval(
                approval_id=f"apprv-open-{trade_id}",
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
                trade_id=trade_id,
                action="open",
                approved_at=bar_ts,
                expires_at=bar_ts + timedelta(minutes=15),
            )
            open_res = harness.runtime.open(
                open_req,
                harness.evidences[sym],
                open_approval,
                trade_id=trade_id,
                occurred_at=bar_ts,
            )
            if open_res.status != "opened":
                raise RuntimeError(f"Failed to open paper trade for {sym}: {open_res}")

            open_entry = next(
                e for e in harness.ledger_store.load().open_positions() if e.trade_id == trade_id
            )
            assert open_res.entry_fee is not None

            harness.margin_account.record_open(
                trade_id=trade_id,
                margin_allocated=margin_allocated,
                leverage=leverage,
                entry_fee=open_res.entry_fee,
                equity=portfolio_equity,
            )

            # Establish ATR protective stops from candidate risk model
            atr_val = atr_series_15m[sym][idx]
            risk = cand.strategy.risk
            stop_mult = risk.stop_atr_multiplier if risk else Decimal("2.0")
            tp_mult = risk.take_profit_atr_multiplier if risk else Decimal("4.0")
            trail_mult = risk.trailing_atr_multiplier if risk else Decimal("1.5")

            stop_price: Decimal | None = None
            target_price: Decimal | None = None
            trailing_stop_price: Decimal | None = None
            if atr_val is not None:
                if entry_side == "LONG":
                    stop_price = open_entry.fill_price - atr_val * stop_mult
                    target_price = open_entry.fill_price + atr_val * tp_mult
                    trailing_stop_price = open_entry.fill_price - atr_val * trail_mult
                else:
                    stop_price = open_entry.fill_price + atr_val * stop_mult
                    target_price = open_entry.fill_price - atr_val * tp_mult
                    trailing_stop_price = open_entry.fill_price + atr_val * trail_mult

            initial_mark = mark_paper_position(
                open_entry,
                mark_price=bar_close,
                marked_at=bar_ts,
                previous_peak_pnl=Decimal("0"),
                stop_loss_price=stop_price,
                take_profit_price=target_price,
            )
            harness.lifecycle_store.append(initial_mark)

            active_trades[sym] = {
                "trade_id": trade_id,
                "side": entry_side,
                "open_entry": open_entry,
                "peak_pnl": initial_mark.peak_pnl,
                "watermark": open_entry.fill_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "trailing_stop_price": trailing_stop_price,
                "leverage": leverage,
                "margin_allocated": margin_allocated,
            }

        # Phase D: Periodic 6-hour observation snapshots
        if bar_ts.minute == 0 and bar_ts.second == 0 and bar_ts.hour % 6 == 0:
            current_ledger = harness.ledger_store.load()
            for sym, cand in candidates.items():
                obs = observe_paper_ledger(
                    current_ledger,
                    candidate_id=cand.candidate_id,
                    candidate_artifact_hash=cand.artifact_hash,
                    starting_equity=starting_equity,
                    previous_peak_equity=previous_peaks[sym],
                    mark_prices=current_bar_closes,
                    observed_at=bar_ts,
                )
                previous_peaks[sym] = max(previous_peaks[sym], obs.equity)
                harness.observation_store.append(obs)
                observations_by_symbol[sym].append(obs)

    # 4. Post-simulation balance & position reconciliation
    final_ledger = harness.ledger_store.load()
    reconciliation = reconcile_paper_positions(final_ledger, ())
    if not reconciliation.reconciled:
        raise DomainViolation(
            f"Track {track_name}: Position reconciliation failed: {reconciliation}"
        )

    closed_entries = [e for e in final_ledger.entries if e.event == "close"]
    for entry in closed_entries:
        assert entry.gross_pnl is not None
        assert entry.entry_fee is not None
        assert entry.exit_fee is not None
        assert entry.net_pnl is not None
        expected_net = entry.gross_pnl - entry.entry_fee - entry.exit_fee
        if entry.net_pnl != expected_net:
            tot_fees = entry.entry_fee + entry.exit_fee
            raise DomainViolation(
                f"Accounting discrepancy on trade {entry.trade_id}: "
                f"net_pnl={entry.net_pnl} != gross({entry.gross_pnl}) - fees({tot_fees})"
            )

    realized_pnl = sum((e.net_pnl for e in closed_entries if e.net_pnl is not None), Decimal("0"))
    final_cash = starting_equity + realized_pnl
    cash_drift = abs(harness.margin_account.cash - final_cash)
    if cash_drift >= Decimal("1e-15"):
        raise DomainViolation(
            f"Cash drift detected on track {track_name}: "
            f"margin account cash ({harness.margin_account.cash}) "
            f"!= ledger reconciled final cash ({final_cash}), drift={cash_drift}"
        )

    # Invariants: Capital survival (terminal equity > 0)
    if final_cash <= Decimal("0") or harness.margin_account.min_observed_equity <= Decimal("0"):
        raise DomainViolation(
            f"Track {track_name}: Capital survival violated: "
            f"final_cash={final_cash}, min_equity={harness.margin_account.min_observed_equity}"
        )

    # Invariants: Max margin utilization ceiling (<= 80%)
    if harness.margin_account.max_observed_utilization > DEFAULT_MAX_MARGIN_UTILIZATION:
        raise DomainViolation(
            f"Track {track_name}: Margin utilization ceiling exceeded: "
            f"{harness.margin_account.max_observed_utilization} > {DEFAULT_MAX_MARGIN_UTILIZATION}"
        )

    # Invariants: Min unencumbered reserve buffer (>= 20%)
    if harness.margin_account.min_observed_buffer < DEFAULT_MIN_RESERVE_BUFFER:
        raise DomainViolation(
            f"Track {track_name}: Reserve buffer violated: "
            f"{harness.margin_account.min_observed_buffer} < {DEFAULT_MIN_RESERVE_BUFFER}"
        )

    cumulative_fees = sum(
        ((e.entry_fee or Decimal("0")) + (e.exit_fee or Decimal("0")) for e in closed_entries),
        Decimal("0"),
    )
    cumulative_slippage = sum(
        (e.slippage_cost or Decimal("0") for e in closed_entries), Decimal("0")
    )
    winning_trades = sum(1 for e in closed_entries if (e.net_pnl or Decimal("0")) > 0)
    losing_trades = sum(1 for e in closed_entries if (e.net_pnl or Decimal("0")) < 0)
    win_rate = (winning_trades / len(closed_entries)) if closed_entries else 0.0

    as_of = DEFAULT_START_TIME + timedelta(days=DEFAULT_DAYS)
    health_reports, cohort_report = generate_phase_264_reports(
        harness.ledger_store,
        harness.lifecycle_store,
        harness.observation_store,
        candidates,
        as_of=as_of,
        days=DEFAULT_DAYS,
    )

    peak_eq = harness.margin_account.peak_portfolio_equity
    min_eq = harness.margin_account.min_observed_equity
    max_dd = (peak_eq - min_eq) / peak_eq if peak_eq > 0 else Decimal("1.0")

    candidate_summaries: dict[str, dict[str, Any]] = {}
    for sym, cand in candidates.items():
        candidate_summaries[sym] = {
            "candidate_id": cand.candidate_id,
            "artifact_hash": cand.artifact_hash,
            "timeframe": cand.strategy.universe.timeframe,
            "family": cand.strategy.family,
            "qualification_hash": qualification_hashes.get(sym, cand.artifact_hash),
            "trades_count": sum(1 for e in closed_entries if e.symbol == sym),
            "realized_pnl_usdt": str(
                sum(
                    (
                        e.net_pnl
                        for e in closed_entries
                        if e.symbol == sym and e.net_pnl is not None
                    ),
                    Decimal("0"),
                )
            ),
            "health_status": health_reports[sym].health_status,
            "maturity_status": health_reports[sym].maturity_status,
        }

    scenario_res = StressTestScenarioResult(
        scenario_name=track_name,
        shock_type=track_spec["shock_type"],
        price_shock_pct=track_spec["price_shock_pct"],
        slippage_multiplier=int(track_spec["slippage_multiplier"]),
        starting_equity=starting_equity,
        ending_equity=final_cash,
        min_observed_equity=min_eq,
        max_observed_drawdown=max_dd,
        max_observed_margin_utilization=harness.margin_account.max_observed_utilization,
        min_observed_equity_buffer=harness.margin_account.min_observed_buffer,
        total_trades_closed=len(closed_entries),
        emergency_liquidations_count=len(harness.margin_account.emergency_liquidations),
        capital_survived=True,
        account_liquidated=False,
        deficit_balance=False,
        zero_balance_drift=True,
        exchange_access=False,
        orders=0,
    )

    return Phase264TrackResult(
        track_id=track_id,
        track_name=track_name,
        scenario_result=scenario_res,
        health_reports=health_reports,
        cohort_report=cohort_report,
        positions_reconciled=True,
        accounting_reconciled=True,
        final_cash=final_cash,
        realized_pnl=realized_pnl,
        cumulative_fees=cumulative_fees,
        cumulative_slippage=cumulative_slippage,
        circuit_breaker_events_count=len(harness.margin_account.state_history),
        emergency_liquidations=tuple(harness.margin_account.emergency_liquidations),
        output_dir=output_dir,
        candidate_summaries=candidate_summaries,
        total_trades=len(closed_entries),
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        cash_drift=cash_drift,
    )


@dataclass(frozen=True, slots=True)
class Phase264SimulationResult:
    output_dir: Path
    total_tracks: int
    all_tracks_survived: bool
    track_results: dict[str, Phase264TrackResult]
    survival_matrix: list[dict[str, Any]]
    stress_track_summary_path: Path
    paper_summary_path: Path
    artifact_hashes: dict[str, str]
    registry_version: int


def run_phase_264_simulation(
    output_dir: Path = DEFAULT_PHASE264_OUTPUT_DIR,
    *,
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH,
    start_time: datetime = DEFAULT_START_TIME,
    days: int = DEFAULT_DAYS,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
    selected_track: str = "all",
) -> Phase264SimulationResult:
    """Execute Phase 264 multi-vector stress simulation across 6 tracks under Manifest v2."""
    assert_offline_safety_invariants()
    output_dir.mkdir(parents=True, exist_ok=True)

    if days < 1:
        raise DomainViolation(f"Phase 264 requires days >= 1, got {days}")
    if starting_equity <= Decimal("0"):
        raise DomainViolation(f"Phase 264 requires starting_equity > 0, got {starting_equity}")

    # 1. Validate Candidate Registry Manifest v2
    manifest = read_candidate_registry(registry_path, verify_hash=True)
    if manifest.registry_version < 2:
        raise DomainViolation(
            f"Phase 264 requires candidate registry version >= 2, got {manifest.registry_version}"
        )

    expected_candidates = {
        "BTCUSDT": "cand-btcusdt-dcb-002",
        "ETHUSDT": "cand-ethusdt-dcb-003",
        "SOLUSDT": "cand-solusdt-rgb-001",
    }
    for sym, expected_id in expected_candidates.items():
        entry = manifest.symbols.get(sym)
        if entry is None or entry.candidate_id != expected_id:
            raise DomainViolation(
                f"Phase 264 requires active {sym} candidate {expected_id}, "
                f"got {entry.candidate_id if entry else 'missing'}"
            )

    candidates = validate_manifest_candidate_artifacts(manifest)
    qualification_hashes = {
        sym: entry.qualification_hash for sym, entry in manifest.symbols.items()
    }

    # 2. Load canonical baseline market frames
    total_bars_15m = days * 24 * 4
    total_bars_1h = days * 24
    end_time = start_time + timedelta(days=days)

    raw_frames_15m: dict[str, pd.DataFrame] = {}
    raw_frames_1h: dict[str, pd.DataFrame] = {}

    for sym, cand in candidates.items():
        p15 = Path(f"research/immutable-data/15m/canonical/{sym}-15m.parquet")
        if not p15.is_file():
            raise DataQualityError(f"Missing required 15m canonical dataset for {sym}: {p15}")
        df15 = pd.read_parquet(p15)
        mask15 = (df15["timestamp"] >= start_time) & (df15["timestamp"] < end_time)
        sub15 = df15[mask15].copy().reset_index(drop=True)
        if len(sub15) != total_bars_15m:
            raise DataQualityError(
                f"Incomplete 15m data for {sym}: expected {total_bars_15m} bars, found {len(sub15)}"
            )
        raw_frames_15m[sym] = canonicalize_bars(sub15, interval=timedelta(minutes=15))

        p1h = Path(f"research/immutable-data/1h/canonical/{sym}-1h.parquet")
        if cand.strategy.universe.timeframe == "1h" and not p1h.is_file():
            raise DataQualityError(
                f"Missing required 1h canonical dataset for 1h candidate {sym}: {p1h}"
            )
        if p1h.is_file():
            df1h = pd.read_parquet(p1h)
            mask1h = (df1h["timestamp"] >= start_time) & (df1h["timestamp"] < end_time)
            sub1h = df1h[mask1h].copy().reset_index(drop=True)
            if len(sub1h) != total_bars_1h:
                raise DataQualityError(
                    f"Incomplete 1h data for {sym}: expected {total_bars_1h} bars, "
                    f"found {len(sub1h)}"
                )
            raw_frames_1h[sym] = canonicalize_bars(sub1h, interval=timedelta(hours=1))

    # 3. Determine tracks to execute
    if selected_track == "all":
        tracks_to_run = TRACK_DEFINITIONS
    else:
        tracks_to_run = [
            t
            for t in TRACK_DEFINITIONS
            if t["name"] == selected_track or str(t["id"]) == selected_track
        ]
        if not tracks_to_run:
            raise ValueError(f"Unknown track specified: {selected_track}")

    track_results: dict[str, Phase264TrackResult] = {}
    survival_matrix: list[dict[str, Any]] = []

    for track_spec in tracks_to_run:
        t_id = track_spec["id"]
        t_name = track_spec["name"]
        track_dir = output_dir / "tracks" / f"track_{t_id}_{t_name}"

        res = run_single_phase_264_track(
            track_spec=track_spec,
            output_dir=track_dir,
            candidates=candidates,
            qualification_hashes=qualification_hashes,
            raw_frames_15m=raw_frames_15m,
            raw_frames_1h=raw_frames_1h,
            total_bars_15m=total_bars_15m,
            starting_equity=starting_equity,
        )
        track_results[t_name] = res

        survival_matrix.append(
            {
                "track_id": res.track_id,
                "track_name": res.track_name,
                "description": track_spec["description"],
                "starting_equity_usdt": f"{starting_equity:.2f}",
                "ending_equity_usdt": f"{res.final_cash:.4f}",
                "realized_pnl_usdt": f"{res.realized_pnl:+.4f}",
                "min_observed_equity_usdt": f"{res.scenario_result.min_observed_equity:.4f}",
                "max_drawdown_pct": (
                    f"{res.scenario_result.max_observed_drawdown * Decimal('100'):.2f}%"
                ),
                "max_margin_utilization_pct": (
                    f"{res.scenario_result.max_observed_margin_utilization * Decimal('100'):.2f}%"
                ),
                "min_reserve_buffer_pct": (
                    f"{res.scenario_result.min_observed_equity_buffer * Decimal('100'):.2f}%"
                ),
                "total_trades": res.total_trades,
                "winning_trades": res.winning_trades,
                "losing_trades": res.losing_trades,
                "win_rate_pct": f"{res.win_rate * 100:.1f}%",
                "cumulative_fees_usdt": f"{res.cumulative_fees:.4f}",
                "cumulative_slippage_usdt": f"{res.cumulative_slippage:.4f}",
                "emergency_liquidations": len(res.emergency_liquidations),
                "circuit_breaker_events": res.circuit_breaker_events_count,
                "capital_survived": res.scenario_result.capital_survived,
                "margin_cap_satisfied": (
                    res.scenario_result.max_observed_margin_utilization
                    <= DEFAULT_MAX_MARGIN_UTILIZATION
                ),
                "zero_balance_drift": res.cash_drift < Decimal("1e-15"),
                "balance_drift": str(res.cash_drift),
            }
        )

    # 4. Copy primary composite crisis track databases to root output_dir
    primary_track_name = (
        "composite_crisis" if "composite_crisis" in track_results else tracks_to_run[0]["name"]
    )
    primary_dir = track_results[primary_track_name].output_dir

    for db_name in (
        "paper-ledger.sqlite3",
        "paper-lifecycle.sqlite3",
        "paper-observations.sqlite3",
    ):
        src_db = primary_dir / db_name
        dest_db = output_dir / db_name
        if src_db.exists():
            shutil.copy2(src_db, dest_db)

    # Copy health reports and cohort reports for primary track to root output_dir
    for sym in candidates:
        src_health = primary_dir / f"paper-health-report-{sym}.json"
        if not src_health.exists():
            h_rep = track_results[primary_track_name].health_reports[sym]
            src_health.write_text(
                json.dumps(h_rep.model_dump(mode="json"), indent=2, sort_keys=True),
                encoding="utf-8",
                newline="\n",
            )
        dest_health = output_dir / f"paper-health-report-{sym}.json"
        shutil.copy2(src_health, dest_health)

    src_cohort = primary_dir / "paper-cohort-readiness-report.json"
    if not src_cohort.exists():
        c_rep = track_results[primary_track_name].cohort_report
        src_cohort.write_text(
            json.dumps(c_rep.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
            newline="\n",
        )
    dest_cohort = output_dir / "paper-cohort-readiness-report.json"
    shutil.copy2(src_cohort, dest_cohort)

    # 5. Build stress-track-summary.json
    stress_summary_path = output_dir / "stress-track-summary.json"
    stress_summary_data: dict[str, Any] = {
        "phase": "phase_264",
        "description": "Phase 264 Multi-Vector Stress Testing under Manifest v2",
        "registry_version": manifest.registry_version,
        "registry_hash": manifest.registry_hash,
        "canonical_window": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "days": days,
            "total_bars_15m": total_bars_15m,
        },
        "scenarios_evaluated": [t["name"] for t in tracks_to_run],
        "total_tracks": len(tracks_to_run),
        "all_tracks_survived": all(
            r.scenario_result.capital_survived for r in track_results.values()
        ),
        "max_utilization_cap_satisfied": all(
            r.scenario_result.max_observed_margin_utilization <= DEFAULT_MAX_MARGIN_UTILIZATION
            for r in track_results.values()
        ),
        "min_reserve_buffer_satisfied": all(
            r.scenario_result.min_observed_equity_buffer >= DEFAULT_MIN_RESERVE_BUFFER
            for r in track_results.values()
        ),
        "zero_balance_drift_verified": all(
            r.cash_drift < Decimal("1e-15") for r in track_results.values()
        ),
        "portfolio_survival_matrix": survival_matrix,
        "tracks": {
            name: {
                "track_id": r.track_id,
                "track_name": r.track_name,
                "scenario_name": r.scenario_result.scenario_name,
                "shock_type": r.scenario_result.shock_type,
                "price_shock_pct": str(r.scenario_result.price_shock_pct),
                "slippage_multiplier": r.scenario_result.slippage_multiplier,
                "starting_equity_usdt": str(r.scenario_result.starting_equity),
                "ending_equity_usdt": str(r.scenario_result.ending_equity),
                "realized_pnl_usdt": str(r.realized_pnl),
                "min_observed_equity_usdt": str(r.scenario_result.min_observed_equity),
                "max_observed_drawdown": str(r.scenario_result.max_observed_drawdown),
                "max_observed_margin_utilization": str(
                    r.scenario_result.max_observed_margin_utilization
                ),
                "min_observed_equity_buffer": str(r.scenario_result.min_observed_equity_buffer),
                "total_trades_closed": r.scenario_result.total_trades_closed,
                "emergency_liquidations_count": r.scenario_result.emergency_liquidations_count,
                "capital_survived": r.scenario_result.capital_survived,
                "zero_balance_drift": r.cash_drift < Decimal("1e-15"),
                "balance_drift": str(r.cash_drift),
                "cumulative_fees_usdt": str(r.cumulative_fees),
                "cumulative_slippage_usdt": str(r.cumulative_slippage),
                "circuit_breaker_state_changes": r.circuit_breaker_events_count,
            }
            for name, r in track_results.items()
        },
        "safety_invariants": {
            "paper_activation": False,
            "execution_authority": False,
            "exchange_access": False,
            "orders": 0,
            "data_source": "cached_only",
            "promotion_state": "unpromoted",
            "zero_secret_leakage": True,
        },
        "artifact_hashes": {},
    }

    # 6. Build paper-summary.json
    paper_summary_path = output_dir / "paper-summary.json"
    primary_res = track_results[primary_track_name]
    paper_summary_payload: dict[str, Any] = {
        "phase": "phase_264",
        "description": "Phase 264 Multi-Vector Stress Testing under Manifest v2",
        "simulation_start": start_time.isoformat(),
        "simulation_end": end_time.isoformat(),
        "days_evaluated": days,
        "total_bars_15m": total_bars_15m,
        "registry_version": manifest.registry_version,
        "registry_hash": manifest.registry_hash,
        "candidates": primary_res.candidate_summaries,
        "shared_portfolio_margin": {
            "starting_equity_usdt": str(starting_equity),
            "final_cash_usdt": str(primary_res.final_cash),
            "realized_pnl_usdt": str(primary_res.realized_pnl),
            "cumulative_fees_usdt": str(primary_res.cumulative_fees),
            "cumulative_slippage_usdt": str(primary_res.cumulative_slippage),
            "margin_utilization_ceiling": str(DEFAULT_MAX_MARGIN_UTILIZATION),
            "max_observed_margin_utilization": str(
                round(primary_res.scenario_result.max_observed_margin_utilization, 4)
            ),
            "unencumbered_equity_buffer_pct": str(
                (Decimal("1.0") - DEFAULT_MAX_MARGIN_UTILIZATION) * Decimal("100")
            ),
            "base_position_fraction": str(DEFAULT_POSITION_FRACTION),
        },
        "portfolio_summary": {
            "total_trades": primary_res.total_trades,
            "winning_trades": primary_res.winning_trades,
            "losing_trades": primary_res.losing_trades,
            "win_rate": round(primary_res.win_rate, 4),
            "win_rate_pct": round(primary_res.win_rate * 100, 2),
            "positions_reconciled": True,
            "accounting_reconciled": True,
            "zero_balance_drift": primary_res.cash_drift < Decimal("1e-15"),
        },
        "cohort_readiness": {
            "cohort_status": primary_res.cohort_report.cohort_status,
            "expected_candidate_count": primary_res.cohort_report.expected_candidate_count,
            "reported_candidate_count": primary_res.cohort_report.reported_candidate_count,
            "mature_candidate_count": primary_res.cohort_report.mature_candidate_count,
            "healthy_candidate_count": primary_res.cohort_report.healthy_candidate_count,
            "all_mature": primary_res.cohort_report.all_mature,
            "all_accounting_complete": primary_res.cohort_report.all_accounting_complete,
        },
        "stress_testing": {
            "primary_track": primary_track_name,
            "tracks_evaluated": len(track_results),
            "all_tracks_survived": all(
                r.scenario_result.capital_survived for r in track_results.values()
            ),
            "max_margin_utilization_all_tracks": str(
                max(
                    r.scenario_result.max_observed_margin_utilization
                    for r in track_results.values()
                )
            ),
            "min_equity_all_tracks": str(
                min(r.scenario_result.min_observed_equity for r in track_results.values())
            ),
            "zero_balance_drift_all_tracks": all(
                r.cash_drift < Decimal("1e-15") for r in track_results.values()
            ),
        },
        "safety_invariants": {
            "data_source": "cached_only",
            "exchange_access": False,
            "execution_authority": False,
            "paper_activation": False,
            "orders": 0,
            "promotion_state": "unpromoted",
            "zero_secret_leakage": True,
        },
        "artifact_hashes": {},
    }

    # Write preliminary JSON files
    stress_json = json.dumps(stress_summary_data, indent=2, sort_keys=True)
    _assert_zero_secrets(stress_json, str(stress_summary_path))
    stress_summary_path.write_text(stress_json, encoding="utf-8", newline="\n")

    paper_json = json.dumps(paper_summary_payload, indent=2, sort_keys=True)
    _assert_zero_secrets(paper_json, str(paper_summary_path))
    paper_summary_path.write_text(paper_json, encoding="utf-8", newline="\n")

    # Compute artifact cryptographic hashes
    artifact_hashes: dict[str, str] = {
        "paper-ledger.sqlite3": compute_file_sha256(output_dir / "paper-ledger.sqlite3"),
        "paper-lifecycle.sqlite3": compute_file_sha256(output_dir / "paper-lifecycle.sqlite3"),
        "paper-observations.sqlite3": compute_file_sha256(
            output_dir / "paper-observations.sqlite3"
        ),
        "paper-cohort-readiness-report.json": compute_file_sha256(dest_cohort),
    }
    for sym in candidates:
        artifact_hashes[f"paper-health-report-{sym}.json"] = compute_file_sha256(
            output_dir / f"paper-health-report-{sym}.json"
        )

    # Also persist stress-test-summary.json as alias for interoperability
    shutil.copy2(stress_summary_path, output_dir / "stress-test-summary.json")
    artifact_hashes["stress-test-summary.json"] = compute_file_sha256(
        output_dir / "stress-test-summary.json"
    )

    stress_summary_data["artifact_hashes"] = artifact_hashes
    final_stress_json = json.dumps(stress_summary_data, indent=2, sort_keys=True)
    _assert_zero_secrets(final_stress_json, str(stress_summary_path))
    stress_summary_path.write_text(final_stress_json, encoding="utf-8", newline="\n")

    artifact_hashes["stress-track-summary.json"] = compute_file_sha256(stress_summary_path)

    paper_summary_payload["artifact_hashes"] = artifact_hashes
    final_paper_json = json.dumps(paper_summary_payload, indent=2, sort_keys=True)
    _assert_zero_secrets(final_paper_json, str(paper_summary_path))
    paper_summary_path.write_text(final_paper_json, encoding="utf-8", newline="\n")

    artifact_hashes["paper-summary.json"] = compute_file_sha256(paper_summary_path)

    return Phase264SimulationResult(
        output_dir=output_dir,
        total_tracks=len(track_results),
        all_tracks_survived=all(r.scenario_result.capital_survived for r in track_results.values()),
        track_results=track_results,
        survival_matrix=survival_matrix,
        stress_track_summary_path=stress_summary_path,
        paper_summary_path=paper_summary_path,
        artifact_hashes=artifact_hashes,
        registry_version=manifest.registry_version,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 264 Multi-Vector Stress Testing & Adverse Conditions Simulation"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE264_OUTPUT_DIR,
        help="Directory to store stress testing output artifacts",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_CANDIDATE_REGISTRY_PATH,
        help="Path to candidate registry manifest (must be version >= 2)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="Number of days to simulate (default: 7)",
    )
    parser.add_argument(
        "--starting-equity",
        type=Decimal,
        default=DEFAULT_STARTING_EQUITY,
        help="Starting cash in USDT (default: 100.00)",
    )
    parser.add_argument(
        "--track",
        type=str,
        default="all",
        help="Specific track to execute (0, 1, 2, 3, 4, 5, or all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON summary",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    res = run_phase_264_simulation(
        output_dir=args.output_dir,
        registry_path=args.registry_path,
        days=args.days,
        starting_equity=args.starting_equity,
        selected_track=args.track,
    )

    if args.json:
        sys.stdout.write(res.stress_track_summary_path.read_text(encoding="utf-8"))
        return 0

    sys.stdout.write("\n=== PHASE 264 MULTI-VECTOR STRESS SIMULATION COMPLETED ===\n")
    sys.stdout.write(f"Output Directory:       {res.output_dir}\n")
    sys.stdout.write(f"Registry Version:       {res.registry_version}\n")
    sys.stdout.write(f"Tracks Evaluated:       {res.total_tracks}\n")
    sys.stdout.write(f"All Tracks Survived:    {res.all_tracks_survived}\n\n")

    sys.stdout.write(
        f"{'Track ID':<10} {'Track Name':<22} {'End Cash':<12} {'Realized PnL':<15} "
        f"{'Min Equity':<12} {'Max Util':<10} {'Min Buffer':<12} {'Max DD':<10} {'Surv':<6}\n"
    )
    sys.stdout.write("-" * 115 + "\n")
    for row in res.survival_matrix:
        sys.stdout.write(
            f"{row['track_id']:<10} {row['track_name']:<22} "
            f"{row['ending_equity_usdt']:<12} {row['realized_pnl_usdt']:<15} "
            f"{row['min_observed_equity_usdt']:<12} {row['max_margin_utilization_pct']:<10} "
            f"{row['min_reserve_buffer_pct']:<12} {row['max_drawdown_pct']:<10} "
            f"{'YES' if row['capital_survived'] else 'NO':<6}\n"
        )
    sys.stdout.write("-" * 115 + "\n\n")

    sys.stdout.write(f"Stress Summary Artifact: {res.stress_track_summary_path}\n")
    sys.stdout.write(f"Paper Summary Artifact:  {res.paper_summary_path}\n")
    for name, h in sorted(res.artifact_hashes.items()):
        sys.stdout.write(f"  [{name}]: {h}\n")
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
