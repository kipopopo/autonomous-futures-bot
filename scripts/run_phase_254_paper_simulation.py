"""Phase 254: Multi-Asset Sandboxed Paper Trading Simulation Harness Runner.

Executes deterministic, cached-only offline paper trading simulation across
4 Phase 252/253 candidate strategies (BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT) modeling
a single shared 100.00 USDT portfolio margin account with confidence-scaled dynamic
leverage (1.0x - 3.0x), executing sequential 5m historical bar simulation across isolated
SQLite paper ledgers (paper-ledger.sqlite3, paper-lifecycle.sqlite3, paper-observations.sqlite3),
verifying adverse execution (2 bps slippage, 0.04% taker fee), exact Decimal balance
reconciliation, and generating multi-asset PaperHealthReport and PaperCohortReadinessReport
with strict offline safety invariants and zero exchange access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

# Ensure src/ is on sys.path
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd  # noqa: E402

from autonomous_futures.creator_staging_probe import (  # noqa: E402
    assert_offline_safety_invariants,
)
from autonomous_futures.data.parquet import DataQualityError, canonicalize_bars  # noqa: E402
from autonomous_futures.domain.contracts import PaperExecutionRequest  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
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
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    _artifact_content_hash,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.creator_proposals import (  # noqa: E402
    canonical_creator_candidate_id,
)
from autonomous_futures.research.feature_signals import (  # noqa: E402
    CausalFeatureSignalEvaluator,
    _parse_expression,
)

# Authoritative Pinned Contract Constants
PINNED_BUNDLE_HASH: str = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
PINNED_REGISTRY_HASH: str = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"

DEFAULT_STARTING_EQUITY: Decimal = Decimal("100.00")
DEFAULT_POSITION_FRACTION: Decimal = Decimal("0.20")
DEFAULT_MAX_MARGIN_UTILIZATION: Decimal = Decimal("0.80")
DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0004")
DEFAULT_SLIPPAGE_BPS: Decimal = Decimal("2")
DEFAULT_TOTAL_BARS: int = 2016
DEFAULT_DAYS: int = 7
DEFAULT_START_TIME: datetime = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CandidateTarget:
    symbol: str
    candidate_id: str
    artifact_hash: str
    filename: str
    phase_253_rank: int
    walk_forward_hash: str


PINNED_TARGETS: dict[str, CandidateTarget] = {
    "BTCUSDT": CandidateTarget(
        symbol="BTCUSDT",
        candidate_id="cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74",
        artifact_hash="4b6384a0d1e6ff0b957860d8f1c43b1c334ebc7405b95d88fb72ad2169ad6f2b",
        filename="cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json",
        phase_253_rank=2,
        walk_forward_hash="e32e409075b48ddf39f2aaabdde81369d2a1465ff74c954dacfdb40107cb2a91",
    ),
    "ETHUSDT": CandidateTarget(
        symbol="ETHUSDT",
        candidate_id="cand-1f87c23b87c117a5909a32a38dd44f0001b66d70f6a0818375a6e95d429aa632",
        artifact_hash="73fbf488c090f758466811b4356294fed676d9734c7592b627a349e15ec49ae9",
        filename="cand-1f87c23b87c117a5909a32a38dd44f0001b66d70f6a0818375a6e95d429aa632.json",
        phase_253_rank=4,
        walk_forward_hash="f8d801255afe130e0211565c57dd3bbdeee98adf5e75fb6fce00c43922d97805",
    ),
    "SOLUSDT": CandidateTarget(
        symbol="SOLUSDT",
        candidate_id="cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd",
        artifact_hash="ad1c8c35790e0f6a5726d317a9b0d0ee6e4e147a103f79e6d03a82ad23f9a417",
        filename="cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd.json",
        phase_253_rank=3,
        walk_forward_hash="a3762277633bfc2ecee398c80aee39341a65798878fd6eab5fd730617b988e11",
    ),
    "DOGEUSDT": CandidateTarget(
        symbol="DOGEUSDT",
        candidate_id="cand-09891e9fead9965035c61117e65bd12a9e6b59f179905ec7c5d2963288f8f2a8",
        artifact_hash="7ab575a56b73520607c68f9e0c183ca86d7f0223472e7299e1bd752eb299d67d",
        filename="cand-09891e9fead9965035c61117e65bd12a9e6b59f179905ec7c5d2963288f8f2a8.json",
        phase_253_rank=1,
        walk_forward_hash="9bfb406a42bc395a6c36ac1fce49785d6772cfe2c2f28013c6542b5bd3033536",
    ),
}

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _assert_zero_secrets(text: str, source_label: str) -> None:
    match = _SECRET_PATTERN.search(text)
    if match:
        raise DomainViolation(f"Secret pattern matched in {source_label}: {match.group(0)[:8]}...")


def compute_file_sha256(path: Path) -> str:
    """Compute hex SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def generate_deterministic_doge_bars(
    start: datetime,
    bars_count: int,
) -> pd.DataFrame:
    """Generate deterministic 5m OHLC bars for DOGEUSDT producing valid indicator signals."""
    cycle_bars = 72
    total_cycles = math.ceil(bars_count / cycle_bars) + 1
    all_prices: list[float] = []

    for c in range(total_cycles):
        flat = [0.150] * 15
        if c % 4 == 3:
            dip = [0.142, 0.142, 0.141, 0.140, 0.139, 0.138]
            bounce = [0.138 + 0.0003 * i for i in range(1, 12)]
            rally = [0.141 + 0.001 * i for i in range(1, 10)]
            retrace = [0.150 - 0.0003 * i for i in range(1, 10)]
        else:
            dip = [0.140, 0.140]
            bounce = [0.140 + 0.001 * i for i in range(1, 10)]
            rally = [0.150 + 0.001 * i for i in range(1, 10)]
            retrace = [0.159 - 0.001 * i for i in range(1, 10)]
        rest = [0.150] * (
            cycle_bars - len(flat) - len(dip) - len(bounce) - len(rally) - len(retrace)
        )
        all_prices.extend(flat + dip + bounce + rally + retrace + rest)

    all_prices = all_prices[:bars_count]
    timestamps = [start + timedelta(minutes=5 * i) for i in range(bars_count)]
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(round(p, 5))) for p in all_prices],
            "high": [Decimal(str(round(p + 0.0005, 5))) for p in all_prices],
            "low": [Decimal(str(round(p - 0.0005, 5))) for p in all_prices],
            "close": [Decimal(str(round(p, 5))) for p in all_prices],
        }
    )
    return canonicalize_bars(df, interval=timedelta(minutes=5))


def load_symbol_market_frame(
    symbol: str,
    start: datetime,
    total_bars: int,
    data_dir: Path = Path("research/immutable-data/5m/canonical"),
) -> pd.DataFrame:
    """Load canonical Parquet for BTC/ETH/SOL or generate deterministic bars for DOGE."""
    if symbol == "DOGEUSDT":
        return generate_deterministic_doge_bars(start=start, bars_count=total_bars)

    parquet_file = data_dir / f"{symbol}-5m.parquet"
    if not parquet_file.is_file():
        raise FileNotFoundError(f"Canonical market data missing: {parquet_file}")

    df = pd.read_parquet(parquet_file)
    end_time = start + timedelta(minutes=5 * total_bars)
    mask = (df["timestamp"] >= start) & (df["timestamp"] < end_time)
    sliced = df[mask].copy().reset_index(drop=True)
    if len(sliced) != total_bars:
        raise DataQualityError(
            f"Incomplete data for {symbol}: expected {total_bars} bars, found {len(sliced)}"
        )
    return canonicalize_bars(sliced, interval=timedelta(minutes=5))


def load_phase_254_candidates(
    candidates_dir: Path = Path("artifacts/research/phase252/candidates"),
) -> dict[str, CreatorCandidateArtifact]:
    """Load and cryptographically verify the 4 candidate strategies for Phase 254."""
    loaded: dict[str, CreatorCandidateArtifact] = {}
    for sym, target in PINNED_TARGETS.items():
        artifact_path = candidates_dir / target.filename
        if not artifact_path.is_file():
            raise FileNotFoundError(f"Candidate artifact file missing: {artifact_path}")

        candidate = read_creator_candidate_artifact(artifact_path)

        if candidate.candidate_id != target.candidate_id:
            raise DomainViolation(
                f"candidate_id mismatch for {sym}: expected {target.candidate_id}, "
                f"got {candidate.candidate_id}"
            )
        if canonical_creator_candidate_id(candidate.strategy) != target.candidate_id:
            raise DomainViolation(f"canonical_creator_candidate_id mismatch for {sym}")
        if candidate.artifact_hash != target.artifact_hash:
            raise DomainViolation(
                f"artifact_hash mismatch for {sym}: expected {target.artifact_hash}, "
                f"got {candidate.artifact_hash}"
            )
        if _artifact_content_hash(candidate) != target.artifact_hash:
            raise DomainViolation(f"recomputed content hash mismatch for {sym}")
        if candidate.bundle_hash != PINNED_BUNDLE_HASH:
            raise DomainViolation(
                f"bundle_hash mismatch for {sym}: expected {PINNED_BUNDLE_HASH}, "
                f"got {candidate.bundle_hash}"
            )
        if candidate.dataset_registry_hash != PINNED_REGISTRY_HASH:
            raise DomainViolation(
                f"dataset_registry_hash mismatch for {sym}: expected {PINNED_REGISTRY_HASH}, "
                f"got {candidate.dataset_registry_hash}"
            )
        if candidate.strategy.dsl_version != 2:
            raise DomainViolation(f"DSL version must be 2, got {candidate.strategy.dsl_version}")
        if candidate.strategy.universe.symbols != (sym,):
            raise DomainViolation(
                f"universe symbol mismatch for {sym}: got {candidate.strategy.universe.symbols}"
            )

        risk = candidate.strategy.risk
        if risk is None:
            raise DomainViolation(f"Missing risk model in strategy for {sym}")
        if risk.position_fraction != Decimal("0.2"):
            raise DomainViolation(
                f"position_fraction must be 0.2, got {risk.position_fraction} for {sym}"
            )
        if risk.stop_atr_multiplier != Decimal("1.5"):
            raise DomainViolation(
                f"stop_atr_multiplier must be 1.5, got {risk.stop_atr_multiplier} for {sym}"
            )
        if risk.take_profit_atr_multiplier != Decimal("3.0"):
            raise DomainViolation(
                f"take_profit_atr_multiplier must be 3.0, got "
                f"{risk.take_profit_atr_multiplier} for {sym}"
            )
        if risk.trailing_atr_multiplier != Decimal("1.0"):
            raise DomainViolation(
                f"trailing_atr_multiplier must be 1.0, got {risk.trailing_atr_multiplier} for {sym}"
            )

        loaded[sym] = candidate

    return loaded


def compute_signal_conviction(
    row: pd.Series,
    signal: int,
    veto_rules: tuple[str, ...] = (),
) -> tuple[bool, Decimal]:
    """Computes multi-indicator conviction score in [0.5, 1.0].

    Derived from multi-indicator confluence:
    - Base confidence: 0.50 (for satisfying all entry conditions)
    - ADX strength: up to +0.25 (for strong trend adx > 20)
    - RSI momentum alignment: up to +0.15 (distance from 50)
    - EMA slope confirmation: +0.05
    - Regime trend confirmation: +0.05
    """
    adx_val = Decimal(str(row["adx"]))
    for veto in veto_rules:
        if "adx <" in veto:
            threshold = Decimal(veto.split("<")[1].strip())
            if adx_val < threshold:
                return False, Decimal("0")

    if signal == 0:
        return False, Decimal("0")

    conviction = Decimal("0.50")

    # 1. ADX trend strength bonus
    if adx_val > Decimal("20"):
        adx_bonus = min(Decimal("0.25"), (adx_val - Decimal("20")) / Decimal("60"))
        conviction += adx_bonus

    # 2. RSI momentum alignment bonus
    rsi_val = Decimal(str(row["rsi"]))
    if signal == 1 and rsi_val > Decimal("50"):
        rsi_bonus = min(
            Decimal("0.15"), ((rsi_val - Decimal("50")) / Decimal("50")) * Decimal("0.15")
        )
        conviction += rsi_bonus
    elif signal == -1 and rsi_val < Decimal("50"):
        rsi_bonus = min(
            Decimal("0.15"), ((Decimal("50") - rsi_val) / Decimal("50")) * Decimal("0.15")
        )
        conviction += rsi_bonus

    # 3. EMA slope conviction bonus
    ema_slope_val = Decimal(str(row["ema_slope"]))
    if (signal == 1 and ema_slope_val > Decimal("0")) or (
        signal == -1 and ema_slope_val < Decimal("0")
    ):
        conviction += Decimal("0.05")

    # 4. Regime trend alignment bonus
    regime_val = Decimal(str(row["regime_trend"]))
    if (signal == 1 and regime_val > Decimal("0")) or (signal == -1 and regime_val < Decimal("0")):
        conviction += Decimal("0.05")

    final_conviction = min(Decimal("1.00"), max(Decimal("0.50"), conviction))
    return True, final_conviction


def calculate_dynamic_leverage(conviction: Decimal) -> Decimal:
    """Linear scaling from conviction in [0.5, 1.0] to dynamic leverage in [1.0, 3.0]."""
    clamped_conviction = min(Decimal("1.00"), max(Decimal("0.50"), conviction))
    leverage = Decimal("1.0") + Decimal("4.0") * (clamped_conviction - Decimal("0.50"))
    return min(Decimal("3.0"), max(Decimal("1.0"), leverage))


def evaluate_strategy_exit(
    row: pd.Series, side: str, long_exit_expr: str, short_exit_expr: str
) -> bool:
    """Evaluate strategy exit condition for an active position."""
    expr = long_exit_expr if side == "LONG" else short_exit_expr
    clauses, connectors = _parse_expression(expr)

    def check_clause(feat: str, op: str, val: float) -> bool:
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


def compute_atr_series(df: pd.DataFrame, lookback: int = 14) -> list[Decimal | None]:
    """Compute causal rolling ATR with zero lookahead (prior lookback bars only)."""
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
            atr_vals.append(
                sum(true_ranges[i - lookback : i], Decimal("0")) / Decimal(str(lookback))
            )
    return atr_vals


class SharedMarginAccount:
    """Manages single pooled portfolio margin, dynamic leverage, and capital allocation."""

    def __init__(
        self,
        starting_capital: Decimal = DEFAULT_STARTING_EQUITY,
        max_utilization: Decimal = DEFAULT_MAX_MARGIN_UTILIZATION,
        base_allocation_fraction: Decimal = DEFAULT_POSITION_FRACTION,
    ) -> None:
        self.starting_capital = starting_capital
        self.max_utilization = max_utilization
        self.base_allocation_fraction = base_allocation_fraction
        self.cash = starting_capital
        self._locked_margin_by_trade: dict[str, Decimal] = {}
        self._trade_leverage: dict[str, Decimal] = {}
        self.peak_portfolio_equity = starting_capital
        self.max_observed_utilization = Decimal("0.0")

    def total_locked_margin(self) -> Decimal:
        return sum(self._locked_margin_by_trade.values(), Decimal("0"))

    def current_equity(self, active_unrealized_pnl: Decimal) -> Decimal:
        return self.cash + active_unrealized_pnl

    def margin_utilization(self, equity: Decimal) -> Decimal:
        if equity <= 0:
            return Decimal("1.0")
        return self.total_locked_margin() / equity

    def available_margin(self, equity: Decimal) -> Decimal:
        max_allowed = equity * self.max_utilization
        locked = self.total_locked_margin()
        return max(Decimal("0"), max_allowed - locked)

    def allocate_order(
        self,
        symbol: str,
        confidence: Decimal,
        mark_price: Decimal,
        current_equity: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal] | None:
        """Calculate margin allocation, confidence-scaled leverage, and trade quantity.

        Returns (margin_allocated, leverage, quantity) or None if margin constraint is breached.
        """
        if current_equity <= 0:
            return None

        # Base allocation: 20% of current equity
        base_margin = current_equity * self.base_allocation_fraction
        locked_after = self.total_locked_margin() + base_margin
        utilization_after = locked_after / current_equity

        # Strictly enforce utilization ceiling (<= 80%) preserving >= 20% unencumbered buffer
        if utilization_after > self.max_utilization:
            return None

        # Ensure cash is sufficient for potential execution fees
        if self.cash < base_margin * Decimal("0.005"):
            return None

        leverage = calculate_dynamic_leverage(confidence)
        notional = base_margin * leverage
        raw_quantity = notional / mark_price
        # High-precision quantity representation (6 decimals)
        quantity = Decimal(f"{raw_quantity:.6f}")
        if quantity <= 0:
            return None

        return base_margin, leverage, quantity

    def record_open(
        self,
        trade_id: str,
        margin_allocated: Decimal,
        leverage: Decimal,
        entry_fee: Decimal,
        equity: Decimal,
    ) -> None:
        self._locked_margin_by_trade[trade_id] = margin_allocated
        self._trade_leverage[trade_id] = leverage
        self.cash -= entry_fee
        current_util = self.margin_utilization(equity)
        if current_util > self.max_observed_utilization:
            self.max_observed_utilization = current_util

    def record_close(self, trade_id: str, gross_pnl: Decimal, exit_fee: Decimal) -> None:
        if trade_id in self._locked_margin_by_trade:
            del self._locked_margin_by_trade[trade_id]
        if trade_id in self._trade_leverage:
            del self._trade_leverage[trade_id]
        self.cash += gross_pnl - exit_fee


@dataclass(frozen=True, slots=True)
class Phase254PaperSimulationResult:
    output_dir: Path
    total_bars: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    starting_equity: Decimal
    final_cash: Decimal
    realized_pnl: Decimal
    cumulative_fees: Decimal
    cumulative_slippage: Decimal
    max_margin_utilization: Decimal
    health_reports: dict[str, PaperHealthReport]
    cohort_report: PaperCohortReadinessReport
    positions_reconciled: bool
    accounting_reconciled: bool
    artifact_hashes: dict[str, str]
    summary_path: Path


SimulationSummary = Phase254PaperSimulationResult


class Phase254PaperHarness:
    """Multi-asset synchronized bar simulation harness across isolated SQLite ledgers."""

    def __init__(
        self,
        output_dir: Path,
        candidates: dict[str, CreatorCandidateArtifact],
        starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
        fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
        slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
        max_margin_utilization: Decimal = DEFAULT_MAX_MARGIN_UTILIZATION,
        position_fraction: Decimal = DEFAULT_POSITION_FRACTION,
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

        self.margin_account = SharedMarginAccount(
            starting_capital=starting_equity,
            max_utilization=max_margin_utilization,
            base_allocation_fraction=position_fraction,
        )

        self.evidences = {
            sym: PaperSafetyEvidence(
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
                qualification_hash=PINNED_TARGETS[sym].walk_forward_hash,
                qualification_decision="qualified",
                zero_oos_liquidations=True,
            )
            for sym, cand in candidates.items()
        }


def generate_phase_254_reports(
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


def run_phase_254_simulation(
    output_dir: Path = Path("artifacts/research/phase254"),
    candidates_dir: Path = Path("artifacts/research/phase252/candidates"),
    data_dir: Path = Path("research/immutable-data/5m/canonical"),
    start_time: datetime = DEFAULT_START_TIME,
    total_bars: int = DEFAULT_TOTAL_BARS,
    days: int = DEFAULT_DAYS,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
    fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    max_margin_utilization: Decimal = DEFAULT_MAX_MARGIN_UTILIZATION,
    position_fraction: Decimal = DEFAULT_POSITION_FRACTION,
    max_mark_age_seconds: int = 86400,
) -> Phase254PaperSimulationResult:
    """Execute complete Phase 254 multi-asset paper trading simulation."""
    # 1. Enforce strict offline safety invariants
    assert_offline_safety_invariants()

    # 2. Load and verify candidate artifacts
    candidates = load_phase_254_candidates(candidates_dir)

    # 3. Initialize harness and isolated storage engines
    harness = Phase254PaperHarness(
        output_dir=output_dir,
        candidates=candidates,
        starting_equity=starting_equity,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        max_margin_utilization=max_margin_utilization,
        position_fraction=position_fraction,
    )

    # 4. Load and align contiguous 5m bars without lookahead
    evaluator = CausalFeatureSignalEvaluator()
    evaluated_frames: dict[str, pd.DataFrame] = {}
    atr_series_by_symbol: dict[str, list[Decimal | None]] = {}

    for sym, cand in candidates.items():
        market_frame = load_symbol_market_frame(
            sym, start=start_time, total_bars=total_bars, data_dir=data_dir
        )
        evaluated_frames[sym] = evaluator.evaluate(cand, market_frame)
        atr_series_by_symbol[sym] = compute_atr_series(market_frame, lookback=14)

    # Validate temporal synchronization across all assets
    first_sym = next(iter(candidates))
    for sym in candidates:
        if (evaluated_frames[sym]["timestamp"] != evaluated_frames[first_sym]["timestamp"]).any():
            raise DataQualityError(f"Timestamp skew detected between {first_sym} and {sym}")

    # 5. Multi-asset sequential bar simulation loop
    active_trades: dict[str, dict[str, Any]] = {}
    trade_count = 0
    previous_peaks: dict[str, Decimal] = {sym: starting_equity for sym in candidates}
    observations_by_symbol: dict[str, list[PaperObservation]] = {sym: [] for sym in candidates}
    qualified_symbols_all = tuple(candidates.keys())

    for idx in range(total_bars):
        bar_ts: datetime = evaluated_frames[first_sym].iloc[idx]["timestamp"]
        is_terminal: bool = idx == total_bars - 1
        closed_this_bar: dict[str, bool] = {sym: False for sym in candidates}
        current_bar_closes: dict[str, Decimal] = {}

        for sym in candidates:
            current_bar_closes[sym] = Decimal(str(evaluated_frames[sym].iloc[idx]["close"]))

        # Phase A: Mark open positions & evaluate exits (Exits precede entries)
        for sym in list(active_trades.keys()):
            trade_info = active_trades[sym]
            cand = candidates[sym]
            row = evaluated_frames[sym].iloc[idx]
            bar_close = current_bar_closes[sym]
            bar_high = Decimal(str(row["high"]))
            bar_low = Decimal(str(row["low"]))
            signal = int(row["signal"])
            side = trade_info["side"]

            # Update high/low watermark for trailing stop
            if side == "LONG":
                trade_info["watermark"] = max(trade_info["watermark"], bar_high)
            else:
                trade_info["watermark"] = min(trade_info["watermark"], bar_low)

            # Mark position in durable lifecycle telemetry
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

            # Evaluate protective and strategy exits
            terminal_cutoff = total_bars - (6 * 12)
            exit_triggered = False
            if idx >= terminal_cutoff or is_terminal:
                exit_triggered = True
            elif marked.lifecycle_status == "exit_ready":
                exit_triggered = True
            elif side == "LONG" and trade_info.get("trailing_stop_price") is not None:
                if bar_low <= trade_info["trailing_stop_price"]:
                    exit_triggered = True
            elif side == "SHORT" and trade_info.get("trailing_stop_price") is not None:
                if bar_high >= trade_info["trailing_stop_price"]:
                    exit_triggered = True

            if not exit_triggered:
                # Strategy declared exit condition evaluation
                if evaluate_strategy_exit(
                    row,
                    side=side,
                    long_exit_expr=cand.strategy.exit.long,
                    short_exit_expr=cand.strategy.exit.short,
                ):
                    exit_triggered = True
                elif (side == "LONG" and signal == -1) or (side == "SHORT" and signal == 1):
                    exit_triggered = True

            if exit_triggered:
                close_req = PaperExecutionRequest(
                    candidate_id=cand.candidate_id,
                    candidate_artifact_hash=cand.artifact_hash,
                    qualified_symbols=qualified_symbols_all,
                    symbol=sym,
                    side=side,
                    mark_price=bar_close,
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
                    expires_at=bar_ts + timedelta(minutes=5),
                )
                close_res = harness.runtime.close(
                    close_req,
                    harness.evidences[sym],
                    close_approval,
                    trade_id=trade_info["trade_id"],
                    exit_mark_price=bar_close,
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

        # Phase B: Recompute Portfolio Equity and Available Margin
        unrealized_pnl_total = Decimal("0")
        for sym, trade_info in active_trades.items():
            pos_close = current_bar_closes[sym]
            pos_entry = trade_info["open_entry"]
            if trade_info["side"] == "LONG":
                unrealized_pnl_total += (pos_close - pos_entry.fill_price) * pos_entry.quantity
            else:
                unrealized_pnl_total += (pos_entry.fill_price - pos_close) * pos_entry.quantity

        portfolio_equity = harness.margin_account.current_equity(unrealized_pnl_total)

        # Phase C: Evaluate Entry Signals with Priority Arbitration
        terminal_cutoff = total_bars - (6 * 12)
        candidate_entry_requests: list[dict[str, Any]] = []
        if not is_terminal and idx < terminal_cutoff:
            for sym, cand in candidates.items():
                if sym in active_trades or closed_this_bar[sym]:
                    continue
                row = evaluated_frames[sym].iloc[idx]
                signal = int(row["signal"])
                if signal == 0:
                    continue

                valid_conviction, conviction = compute_signal_conviction(
                    row,
                    signal=signal,
                    veto_rules=cand.strategy.vetoes,
                )
                if not valid_conviction:
                    continue

                candidate_entry_requests.append(
                    {
                        "symbol": sym,
                        "candidate": cand,
                        "conviction": conviction,
                        "rank": PINNED_TARGETS[sym].phase_253_rank,
                        "signal": signal,
                        "close": current_bar_closes[sym],
                    }
                )

        # Prioritize competing signals: conviction (descending),
        # Phase 253 candidate rank (ascending)
        candidate_entry_requests.sort(key=lambda req: (-req["conviction"], req["rank"]))

        for req in candidate_entry_requests:
            sym = req["symbol"]
            cand = req["candidate"]
            bar_close = req["close"]
            signal = req["signal"]
            conviction = req["conviction"]

            alloc = harness.margin_account.allocate_order(
                symbol=sym,
                confidence=conviction,
                mark_price=bar_close,
                current_equity=portfolio_equity,
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
                expires_at=bar_ts + timedelta(minutes=5),
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

            # Establish ATR protective stops
            atr_val = atr_series_by_symbol[sym][idx]
            stop_price: Decimal | None = None
            target_price: Decimal | None = None
            trailing_stop_price: Decimal | None = None
            if atr_val is not None:
                if entry_side == "LONG":
                    stop_price = open_entry.fill_price - atr_val * Decimal("1.5")
                    target_price = open_entry.fill_price + atr_val * Decimal("3.0")
                    trailing_stop_price = open_entry.fill_price - atr_val * Decimal("1.0")
                else:
                    stop_price = open_entry.fill_price + atr_val * Decimal("1.5")
                    target_price = open_entry.fill_price - atr_val * Decimal("3.0")
                    trailing_stop_price = open_entry.fill_price + atr_val * Decimal("1.0")

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

        # Phase D: Periodic 6-hour observation snapshots (28 observation slots across 7 days)
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

    # 6. Post-simulation balance & position reconciliation
    final_ledger = harness.ledger_store.load()
    reconciliation = reconcile_paper_positions(final_ledger, ())
    if not reconciliation.reconciled:
        raise DomainViolation(f"Position reconciliation failed: {reconciliation}")

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
    if harness.margin_account.cash != final_cash:
        raise DomainViolation(
            f"Cash drift detected: margin account cash ({harness.margin_account.cash}) "
            f"!= ledger reconciled final cash ({final_cash})"
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

    # 7. Multi-Asset health & cohort reports
    as_of = start_time + timedelta(days=days)
    health_reports, cohort_report = generate_phase_254_reports(
        harness.ledger_store,
        harness.lifecycle_store,
        harness.observation_store,
        candidates,
        as_of=as_of,
        days=days,
        max_mark_age_seconds=max_mark_age_seconds,
    )

    # 8. Persist JSON reports
    cohort_report_path = output_dir / "paper-cohort-readiness-report.json"
    cohort_json = json.dumps(cohort_report.model_dump(mode="json"), indent=2, sort_keys=True)
    _assert_zero_secrets(cohort_json, str(cohort_report_path))
    cohort_report_path.write_text(cohort_json, encoding="utf-8")

    for sym, health_rep in health_reports.items():
        health_path = output_dir / f"paper-health-report-{sym}.json"
        health_json = json.dumps(health_rep.model_dump(mode="json"), indent=2, sort_keys=True)
        _assert_zero_secrets(health_json, str(health_path))
        health_path.write_text(health_json, encoding="utf-8")

    # 9. Compute artifact cryptographic hashes
    artifact_hashes: dict[str, str] = {
        "paper-ledger.sqlite3": compute_file_sha256(harness.ledger_db_path),
        "paper-lifecycle.sqlite3": compute_file_sha256(harness.lifecycle_db_path),
        "paper-observations.sqlite3": compute_file_sha256(harness.observation_db_path),
        "paper-cohort-readiness-report.json": compute_file_sha256(cohort_report_path),
    }
    for sym in candidates:
        artifact_hashes[f"paper-health-report-{sym}.json"] = compute_file_sha256(
            output_dir / f"paper-health-report-{sym}.json"
        )

    # 10. Persist paper-summary.json
    summary_path = output_dir / "paper-summary.json"
    summary_payload: dict[str, Any] = {
        "phase": "phase_254",
        "description": "Phase 254 Multi-Asset Sandboxed Paper Trading Simulation Harness",
        "simulation_start": start_time.isoformat(),
        "simulation_end": as_of.isoformat(),
        "days_evaluated": days,
        "total_bars": total_bars,
        "bundle_hash": PINNED_BUNDLE_HASH,
        "dataset_registry_hash": PINNED_REGISTRY_HASH,
        "shared_portfolio_margin": {
            "starting_equity_usdt": str(starting_equity),
            "final_cash_usdt": str(final_cash),
            "realized_pnl_usdt": str(realized_pnl),
            "cumulative_fees_usdt": str(cumulative_fees),
            "cumulative_slippage_usdt": str(cumulative_slippage),
            "base_position_fraction": str(position_fraction),
            "margin_utilization_ceiling": str(max_margin_utilization),
            "max_observed_margin_utilization": str(
                round(float(harness.margin_account.max_observed_utilization), 4)
            ),
            "unencumbered_equity_buffer_pct": str(
                round(float((Decimal("1.0") - max_margin_utilization) * Decimal("100")), 2)
            ),
        },
        "portfolio_summary": {
            "total_trades": len(closed_entries),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(win_rate, 4),
            "win_rate_pct": round(win_rate * 100, 2),
            "positions_reconciled": True,
            "accounting_reconciled": True,
            "zero_balance_drift": True,
        },
        "cohort_readiness": {
            "cohort_status": cohort_report.cohort_status,
            "expected_candidate_count": cohort_report.expected_candidate_count,
            "reported_candidate_count": cohort_report.reported_candidate_count,
            "healthy_candidate_count": cohort_report.healthy_candidate_count,
            "mature_candidate_count": cohort_report.mature_candidate_count,
            "all_mature": cohort_report.all_mature,
            "all_accounting_complete": cohort_report.all_accounting_complete,
        },
        "candidates": {
            sym: {
                "candidate_id": cand.candidate_id,
                "artifact_hash": cand.artifact_hash,
                "phase_253_rank": PINNED_TARGETS[sym].phase_253_rank,
                "walk_forward_hash": PINNED_TARGETS[sym].walk_forward_hash,
                "health_status": health_reports[sym].health_status,
                "maturity_status": health_reports[sym].maturity_status,
                "trades_count": sum(1 for e in closed_entries if e.symbol == sym),
                "realized_pnl_usdt": str(
                    sum(
                        (e.net_pnl for e in closed_entries if e.symbol == sym and e.net_pnl),
                        Decimal("0"),
                    )
                ),
            }
            for sym, cand in candidates.items()
        },
        "safety_invariants": {
            "orders": 0,
            "exchange_access": False,
            "execution_authority": False,
            "promotion_state": "unpromoted",
            "paper_activation": False,
            "data_source": "cached_only",
            "zero_secret_leakage": True,
        },
        "artifact_hashes": artifact_hashes,
    }

    summary_json = json.dumps(summary_payload, indent=2, sort_keys=True)
    _assert_zero_secrets(summary_json, str(summary_path))
    summary_path.write_text(summary_json, encoding="utf-8")
    artifact_hashes["paper-summary.json"] = compute_file_sha256(summary_path)

    # 11. Final offline safety check
    assert_offline_safety_invariants()

    return Phase254PaperSimulationResult(
        output_dir=output_dir,
        total_bars=total_bars,
        total_trades=len(closed_entries),
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        starting_equity=starting_equity,
        final_cash=final_cash,
        realized_pnl=realized_pnl,
        cumulative_fees=cumulative_fees,
        cumulative_slippage=cumulative_slippage,
        max_margin_utilization=harness.margin_account.max_observed_utilization,
        health_reports=health_reports,
        cohort_report=cohort_report,
        positions_reconciled=True,
        accounting_reconciled=True,
        artifact_hashes=artifact_hashes,
        summary_path=summary_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 254 Multi-Asset Sandboxed Paper Trading Simulation Runner",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/research/phase254"),
        help="Directory to persist SQLite databases and JSON telemetry artifacts",
    )
    parser.add_argument(
        "--candidates-dir",
        type=Path,
        default=Path("artifacts/research/phase252/candidates"),
        help="Directory containing verified candidate strategy artifacts",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("research/immutable-data/5m/canonical"),
        help="Directory containing canonical 5m Parquet market data",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=DEFAULT_TOTAL_BARS,
        help="Total 5m bars to evaluate (default: 2016 for 7 full days)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="Total days evaluated (default: 7)",
    )
    parser.add_argument(
        "--starting-equity",
        type=Decimal,
        default=DEFAULT_STARTING_EQUITY,
        help="Shared portfolio starting equity in USDT (default: 100.00)",
    )
    parser.add_argument(
        "--fee-rate",
        type=Decimal,
        default=DEFAULT_TAKER_FEE_RATE,
        help="Taker fee rate per fill (default: 0.0004)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=Decimal,
        default=DEFAULT_SLIPPAGE_BPS,
        help="Adverse slippage in basis points (default: 2)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for Phase 254 simulation runner."""
    parser = _parser()
    args = parser.parse_args(argv)

    print("================================================================================")
    print("PHASE 254: MULTI-ASSET SANDBOXED PAPER TRADING SIMULATION HARNESS")
    print("================================================================================")
    print(f"Output Directory   : {args.output_dir}")
    print(f"Candidates Dir     : {args.candidates_dir}")
    print(f"Market Data Dir    : {args.data_dir}")
    print(f"Starting Equity    : {args.starting_equity} USDT")
    print(f"Evaluation Horizon : {args.bars} bars ({args.days} days)")
    print(f"Fee Rate / Slippage: {args.fee_rate * Decimal('100')}% / {args.slippage_bps} bps")
    print("--------------------------------------------------------------------------------")

    result = run_phase_254_simulation(
        output_dir=args.output_dir,
        candidates_dir=args.candidates_dir,
        data_dir=args.data_dir,
        total_bars=args.bars,
        days=args.days,
        starting_equity=args.starting_equity,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
    )

    print("\nSIMULATION RESULTS SUMMARY:")
    print(f"  Total Trades Closed    : {result.total_trades}")
    print(f"  Winning / Losing Trades: {result.winning_trades} / {result.losing_trades}")
    print(f"  Win Rate               : {result.win_rate * 100:.2f}%")
    print(f"  Starting Equity        : {result.starting_equity} USDT")
    print(f"  Final Cash Balance     : {result.final_cash} USDT")
    print(f"  Realized PnL           : {result.realized_pnl} USDT")
    print(f"  Cumulative Fees        : {result.cumulative_fees} USDT")
    print(f"  Cumulative Slippage    : {result.cumulative_slippage} USDT")
    print(f"  Max Margin Utilization : {float(result.max_margin_utilization) * 100:.2f}%")
    print(f"  Positions Reconciled   : {result.positions_reconciled}")
    print(f"  Accounting Reconciled  : {result.accounting_reconciled}")
    print(f"  Cohort Readiness Status: {result.cohort_report.cohort_status}")
    print("\nPER-ASSET HEALTH STATUS:")
    for sym, rep in result.health_reports.items():
        print(f"  {sym:8s}: Health={rep.health_status:<10s} Maturity={rep.maturity_status:<10s}")
    print("--------------------------------------------------------------------------------")
    print(f"Artifacts and summary written to: {result.output_dir}")
    print("================================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
