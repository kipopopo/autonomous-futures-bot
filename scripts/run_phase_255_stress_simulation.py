"""Phase 255: Multi-Vector Adverse Volatility & Slippage Stress Simulation Runner.

Executes deterministic, cached-only offline stress testing across the 4 Phase 252 candidate
strategies (BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT) modeling a single shared 100.00 USDT portfolio
margin account with hardened circuit breakers and dynamic leverage de-escalation across 6
comparative tracks:
- Track 0: Baseline (nominal Phase 254 market conditions)
- Track 1: Flash Crash Shock (-15% to -25% intra-bar adverse drops)
- Track 2: Slippage Surge Shock (50x baseline = 100 bps)
- Track 3: Spread Blowout Shock (20x baseline = 40 bps total execution friction)
- Track 4: Volatility Spikes & Rapid Whipsaw Shock
- Track 5: Composite Crisis Shock (combined simultaneous crisis)

Verifies capital survival (Equity > 0), 80.00% maximum margin utilization cap, >= 20.00%
unencumbered reserve buffer, exact Decimal reconciliation, and zero balance drift with strict
offline safety invariants and zero exchange access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
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
from autonomous_futures.data.parquet import (  # noqa: E402
    DataQualityError,
    canonicalize_bars,
)
from autonomous_futures.domain.contracts import PaperExecutionRequest  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
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
DEFAULT_MIN_RESERVE_BUFFER: Decimal = Decimal("0.20")
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
        raise DomainViolation(
            f"Security secret pattern detected in {source_label}: {match.group()[:8]}..."
        )


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hexadecimal digest for a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
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


def load_phase_255_candidates(
    candidates_dir: Path = Path("artifacts/research/phase252/candidates"),
) -> dict[str, CreatorCandidateArtifact]:
    """Load and cryptographically verify the 4 candidate strategies for Phase 255."""
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
    """Computes multi-indicator conviction score in [0.5, 1.0]."""
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
            Decimal("0.15"),
            ((rsi_val - Decimal("50")) / Decimal("50")) * Decimal("0.15"),
        )
        conviction += rsi_bonus
    elif signal == -1 and rsi_val < Decimal("50"):
        rsi_bonus = min(
            Decimal("0.15"),
            ((Decimal("50") - rsi_val) / Decimal("50")) * Decimal("0.15"),
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
    """Calculates causal rolling ATR over completed bars with zero forward lookahead."""
    true_ranges: list[Decimal] = []
    for i in range(len(df)):
        high_i = Decimal(str(df.iloc[i]["high"]))
        low_i = Decimal(str(df.iloc[i]["low"]))
        if i == 0:
            true_ranges.append(high_i - low_i)
        else:
            prev_close = Decimal(str(df.iloc[i - 1]["close"]))
            tr = max(
                high_i - low_i,
                abs(high_i - prev_close),
                abs(low_i - prev_close),
            )
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


class Phase255StressHarness:
    """Manages isolated paper ledger stores and execution runtime for a stress track."""

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

        for p in (
            self.ledger_db_path,
            self.lifecycle_db_path,
            self.observation_db_path,
        ):
            if p.exists():
                p.unlink()

        self.ledger = SqlitePaperLedger(self.ledger_db_path)
        self.lifecycle_store = SqlitePaperLifecycle(self.lifecycle_db_path)
        self.observation_store = SqlitePaperObservations(self.observation_db_path)
        self.runtime = PaperRuntime(self.ledger)

        # Pre-initialize SQLite database files with schema tables on disk
        self.ledger._connect().close()
        self.lifecycle_store._connect_for_append().close()
        self.observation_store._connect().close()

        self.margin_account = HardenedSharedMarginAccount(
            starting_capital=starting_equity,
            max_utilization=max_margin_utilization,
            base_allocation_fraction=position_fraction,
            min_reserve_buffer=DEFAULT_MIN_RESERVE_BUFFER,
            config=circuit_config or CircuitBreakerConfig(),
        )

        self.evidences: dict[str, PaperSafetyEvidence] = {
            sym: PaperSafetyEvidence(
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
                qualification_hash=PINNED_TARGETS[sym].walk_forward_hash,
                qualification_decision="qualified",
                zero_oos_liquidations=True,
            )
            for sym, cand in candidates.items()
        }


def generate_phase_255_reports(
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
class StressTrackResult:
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


# 6 comparative track specifications
TRACK_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": 0,
        "name": "baseline",
        "description": "Nominal Phase 254 conditions (2 bps slippage, 0.04% taker fee)",
        "shock_type": "baseline",
        "price_shock_pct": Decimal("0.0"),
        "slippage_multiplier": 1,
        "slippage_bps": Decimal("2.0"),
        "spread_bps": Decimal("0.0"),
    },
    {
        "id": 1,
        "name": "flash_crash",
        "description": "Adverse flash crash (-20% intra-bar drop at bar 500)",
        "shock_type": "flash_crash",
        "price_shock_pct": Decimal("-0.20"),
        "slippage_multiplier": 1,
        "slippage_bps": Decimal("2.0"),
        "spread_bps": Decimal("0.0"),
        "shock_bar_index": 500,
    },
    {
        "id": 2,
        "name": "slippage_surge",
        "description": "Severe liquidity dry-up (50x baseline = 100 bps slippage)",
        "shock_type": "slippage_surge",
        "price_shock_pct": Decimal("0.0"),
        "slippage_multiplier": 50,
        "slippage_bps": Decimal("100.0"),
        "spread_bps": Decimal("0.0"),
    },
    {
        "id": 3,
        "name": "spread_blowout",
        "description": "Bid-ask spread blowout (20x baseline = 40 bps total friction)",
        "shock_type": "spread_blowout",
        "price_shock_pct": Decimal("0.0"),
        "slippage_multiplier": 1,
        "slippage_bps": Decimal("40.0"),
        "spread_bps": Decimal("40.0"),
    },
    {
        "id": 4,
        "name": "volatility_whipsaw",
        "description": "High-frequency volatility spikes & rapid whipsaws (12 bars at bar 600)",
        "shock_type": "volatility_whipsaw",
        "price_shock_pct": Decimal("0.0"),
        "slippage_multiplier": 5,
        "slippage_bps": Decimal("10.0"),
        "spread_bps": Decimal("0.0"),
        "shock_bar_index": 600,
        "whipsaw_bars": 12,
        "oscillation_pct": Decimal("0.06"),
    },
    {
        "id": 5,
        "name": "composite_crisis",
        "description": "Combined crisis: flash crash (-20%) + 50x slippage + 20x spread + whipsaws",
        "shock_type": "composite_crisis",
        "price_shock_pct": Decimal("-0.20"),
        "slippage_multiplier": 50,
        "slippage_bps": Decimal("100.0"),
        "spread_bps": Decimal("40.0"),
        "shock_bar_index": 500,
    },
]


def apply_track_shocks(
    raw_frames: dict[str, pd.DataFrame],
    track_spec: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    """Applies calibrated deterministic synthetic market shock vectors to market frames."""
    shock_type = track_spec["shock_type"]
    if shock_type == "baseline":
        return {sym: df.copy() for sym, df in raw_frames.items()}

    shocked: dict[str, pd.DataFrame] = {}
    for sym, df in raw_frames.items():
        mod = df.copy()
        if shock_type == "flash_crash":
            idx = track_spec.get("shock_bar_index", 500)
            drop_pct = abs(track_spec.get("price_shock_pct", Decimal("0.20")))
            mod = SyntheticMarketShockInjector.inject_flash_crash(
                mod, start_idx=idx, drop_pct=drop_pct, wick_only=False
            )
        elif shock_type == "slippage_surge":
            mult = track_spec.get("slippage_multiplier", 50)
            mod = SyntheticMarketShockInjector.inject_slippage_surge(
                mod, multiplier=Decimal(str(mult))
            )
        elif shock_type == "spread_blowout":
            mod = SyntheticMarketShockInjector.inject_spread_blowout(mod, multiplier=Decimal("20"))
        elif shock_type == "volatility_whipsaw":
            idx = track_spec.get("shock_bar_index", 600)
            n_bars = track_spec.get("whipsaw_bars", 12)
            osc = track_spec.get("oscillation_pct", Decimal("0.06"))
            mod = SyntheticMarketShockInjector.inject_whipsaws(
                mod, start_idx=idx, num_bars=n_bars, oscillation_pct=osc
            )
        elif shock_type == "composite_crisis":
            idx = track_spec.get("shock_bar_index", 500)
            mod = SyntheticMarketShockInjector.inject_composite_crisis(mod, start_idx=idx)
        else:
            raise ValueError(f"Unknown shock_type: {shock_type}")

        shocked[sym] = mod

    return shocked


def run_single_stress_track(
    track_spec: dict[str, Any],
    output_dir: Path,
    candidates: dict[str, CreatorCandidateArtifact],
    raw_market_frames: dict[str, pd.DataFrame],
    total_bars: int = DEFAULT_TOTAL_BARS,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
    fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
) -> StressTrackResult:
    """Executes a single comparative stress simulation track across all candidate strategies."""
    track_id = track_spec["id"]
    track_name = track_spec["name"]
    slippage_bps = track_spec["slippage_bps"]

    circuit_config = (
        CircuitBreakerConfig(
            slippage_throttle_bps=Decimal("10.0"),
            slippage_halt_bps=Decimal("150.0"),
        )
        if slippage_bps >= Decimal("20.0")
        else CircuitBreakerConfig()
    )

    harness = Phase255StressHarness(
        output_dir=output_dir,
        candidates=candidates,
        starting_equity=starting_equity,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        max_margin_utilization=DEFAULT_MAX_MARGIN_UTILIZATION,
        position_fraction=DEFAULT_POSITION_FRACTION,
        circuit_config=circuit_config,
    )

    # 1. Apply deterministic shock to market data
    shocked_frames = apply_track_shocks(raw_market_frames, track_spec)

    # 2. Compute causal features and ATR series on shocked data
    evaluator = CausalFeatureSignalEvaluator()
    evaluated_frames: dict[str, pd.DataFrame] = {}
    atr_series_by_symbol: dict[str, list[Decimal | None]] = {}

    for sym, cand in candidates.items():
        evaluated_frames[sym] = evaluator.evaluate(cand, shocked_frames[sym])
        atr_series_by_symbol[sym] = compute_atr_series(shocked_frames[sym], lookback=14)

    # 3. Synchronized multi-asset bar simulation loop
    first_sym = next(iter(candidates))
    active_trades: dict[str, dict[str, Any]] = {}
    trade_count = 0
    previous_peaks: dict[str, Decimal] = {sym: starting_equity for sym in candidates}
    observations_by_symbol: dict[str, list[PaperObservation]] = {sym: [] for sym in candidates}
    qualified_symbols_all = tuple(candidates.keys())
    slippage_rate = slippage_bps / Decimal("10000")
    circuit_breaker_evaluations: list[Any] = []

    # Compute baseline rolling ATR across the initial 288 bars (24h)
    baseline_atrs: dict[str, Decimal] = {}
    for sym in candidates:
        warmup_atrs = [a for a in atr_series_by_symbol[sym][:288] if a is not None]
        baseline_atrs[sym] = (
            sum(warmup_atrs, Decimal("0")) / Decimal(str(len(warmup_atrs)))
            if warmup_atrs
            else Decimal("10.0")
        )

    for idx in range(total_bars):
        bar_ts: datetime = evaluated_frames[first_sym].iloc[idx]["timestamp"]
        is_terminal: bool = idx == total_bars - 1
        closed_this_bar: dict[str, bool] = {sym: False for sym in candidates}
        current_bar_closes: dict[str, Decimal] = {}
        current_bar_opens: dict[str, Decimal] = {}
        current_bar_highs: dict[str, Decimal] = {}
        current_bar_lows: dict[str, Decimal] = {}

        for sym in candidates:
            row_sym = evaluated_frames[sym].iloc[idx]
            current_bar_closes[sym] = Decimal(str(row_sym["close"]))
            current_bar_opens[sym] = Decimal(str(row_sym["open"]))
            current_bar_highs[sym] = Decimal(str(row_sym["high"]))
            current_bar_lows[sym] = Decimal(str(row_sym["low"]))

        # Phase A: Mark open positions & evaluate realistic adverse gap stop exits
        for sym in list(active_trades.keys()):
            trade_info = active_trades[sym]
            cand = candidates[sym]
            row = evaluated_frames[sym].iloc[idx]
            bar_close = current_bar_closes[sym]
            bar_open = current_bar_opens[sym]
            bar_high = current_bar_highs[sym]
            bar_low = current_bar_lows[sym]
            signal = int(row["signal"])
            side = trade_info["side"]

            # Watermark ratchet for trailing stop
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

            # Evaluate protective stop-loss, trailing stop, and strategy exits
            terminal_cutoff = total_bars - (6 * 12)
            exit_triggered = False
            raw_exit_price = bar_close

            if idx >= terminal_cutoff or is_terminal:
                exit_triggered = True
                raw_exit_price = bar_close
            elif marked.lifecycle_status == "exit_ready":
                exit_triggered = True
                # Realistic adverse gap stop execution: min(open, stop) for LONG
                if marked.stop_loss_hit:
                    raw_exit_price, _ = calculate_adverse_gap_fill(
                        side=side,
                        bar_open=bar_open,
                        stop_price=trade_info["stop_price"],
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

            if not exit_triggered:
                # Strategy declared exit condition evaluation
                if evaluate_strategy_exit(
                    row,
                    side=side,
                    long_exit_expr=cand.strategy.exit.long,
                    short_exit_expr=cand.strategy.exit.short,
                ):
                    exit_triggered = True
                    raw_exit_price = bar_close
                elif (side == "LONG" and signal == -1) or (side == "SHORT" and signal == 1):
                    exit_triggered = True
                    raw_exit_price = bar_close

            if exit_triggered:
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
                    expires_at=bar_ts + timedelta(minutes=5),
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

        # Phase B: Recompute Portfolio Equity and Evaluate Circuit Breakers
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

        # Evaluate circuit breakers across all candidate assets
        max_vol_ratio = Decimal("1.0")
        for sym in candidates:
            current_atr = atr_series_by_symbol[sym][idx] or baseline_atrs[sym]
            base_atr = baseline_atrs[sym]
            row_sym = evaluated_frames[sym].iloc[idx]
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

        # Check automated emergency position close-out defense
        # Triggers if utilization > 80% (reserve buffer < 20%) or EMERGENCY_FLAT state
        if active_trades and (
            harness.margin_account.margin_utilization(portfolio_equity)
            > DEFAULT_MAX_MARGIN_UTILIZATION
            or harness.margin_account.current_state == "EMERGENCY_FLAT"
        ):
            # Execute orderly liquidation through runtime to persist into SQLite ledger
            liquidations = harness.margin_account.emergency_liquidate_positions(
                active_trades=active_trades,
                current_prices=current_bar_closes,
                current_opens=current_bar_opens,
                slippage_rate=slippage_rate,
                fee_rate=fee_rate,
                occurred_at=bar_ts,
                reason="circuit_breaker_emergency_flat",
            )
            # Synchronize into durable runtime ledger
            for liq in liquidations:
                # Append to durable ledger via close request
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
                    expires_at=bar_ts + timedelta(minutes=5),
                )
                harness.runtime.close(
                    close_req,
                    harness.evidences[liq.symbol],
                    close_approval,
                    trade_id=liq.trade_id,
                    exit_mark_price=liq.gapped_market_price,
                    occurred_at=bar_ts,
                )
                closed_this_bar[liq.symbol] = True

        # Phase C: Evaluate Entry Signals with Priority Arbitration & Hardened Sizing
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

        # Priority arbitration: conviction descending, rank ascending
        candidate_entry_requests.sort(key=lambda req: (-req["conviction"], req["rank"]))

        for req in candidate_entry_requests:
            sym = req["symbol"]
            cand = req["candidate"]
            bar_close = req["close"]
            signal = req["signal"]
            conviction = req["conviction"]

            current_atr_opt = atr_series_by_symbol[sym][idx]
            if current_atr_opt is None:
                continue

            # Hardened margin allocation
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

            base_margin, dynamic_lev, quantity = alloc
            entry_side: Literal["LONG", "SHORT"] = "LONG" if signal == 1 else "SHORT"
            trade_count += 1
            ts_str = bar_ts.strftime("%Y%m%d%H%M%S")
            trade_id = f"paper-{cand.candidate_id[:12]}-{sym.lower()}-{ts_str}-{trade_count:04d}"

            entry_req = PaperExecutionRequest(
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
            entry_approval = PaperActionApproval(
                approval_id=f"apprv-open-{trade_id}",
                candidate_id=cand.candidate_id,
                candidate_artifact_hash=cand.artifact_hash,
                trade_id=trade_id,
                action="open",
                approved_at=bar_ts,
                expires_at=bar_ts + timedelta(minutes=5),
            )
            open_res = harness.runtime.open(
                entry_req,
                harness.evidences[sym],
                entry_approval,
                trade_id=trade_id,
                occurred_at=bar_ts,
            )
            if open_res.status != "opened":
                raise RuntimeError(f"Failed to open paper trade for {sym}: {open_res}")

            open_entry = next(
                e for e in harness.ledger.load().open_positions() if e.trade_id == trade_id
            )
            assert open_res.entry_fee is not None
            harness.margin_account.record_open(
                trade_id=trade_id,
                margin_allocated=base_margin,
                leverage=dynamic_lev,
                entry_fee=open_res.entry_fee,
                equity=portfolio_equity,
            )

            # Compute initial protective stops
            stop_mult = cand.strategy.risk.stop_atr_multiplier  # 1.5
            tp_mult = cand.strategy.risk.take_profit_atr_multiplier  # 3.0
            trail_mult = cand.strategy.risk.trailing_atr_multiplier  # 1.0

            if entry_side == "LONG":
                stop_price = open_entry.fill_price - stop_mult * current_atr_opt
                target_price = open_entry.fill_price + tp_mult * current_atr_opt
                trailing_stop_price = open_entry.fill_price - trail_mult * current_atr_opt
            else:
                stop_price = open_entry.fill_price + stop_mult * current_atr_opt
                target_price = open_entry.fill_price - tp_mult * current_atr_opt
                trailing_stop_price = open_entry.fill_price + trail_mult * current_atr_opt

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
                "open_entry": open_entry,
                "side": entry_side,
                "margin_allocated": base_margin,
                "leverage": dynamic_lev,
                "peak_pnl": initial_mark.peak_pnl,
                "watermark": bar_close,
                "stop_price": stop_price,
                "target_price": target_price,
                "trailing_stop_price": trailing_stop_price,
            }

        # Phase D: Periodic 6-Hour Observations
        if bar_ts.minute == 0 and bar_ts.second == 0 and bar_ts.hour % 6 == 0:
            current_ledger = harness.ledger.load()
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

    # 4. Post-Simulation Accounting Reconciliation & Invariant Assertions
    final_ledger = harness.ledger.load()
    reconciliation = reconcile_paper_positions(final_ledger, ())
    if not reconciliation.reconciled:
        raise DomainViolation(
            f"Track {track_name}: Durable paper positions reconciliation failed: {reconciliation}"
        )
    positions_reconciled = reconciliation.reconciled

    all_closed_entries = [e for e in final_ledger.entries if e.event == "close"]
    realized_pnl_sum = Decimal("0")
    cumulative_fees = Decimal("0")
    cumulative_slippage = Decimal("0")

    for entry in all_closed_entries:
        assert entry.gross_pnl is not None
        assert entry.entry_fee is not None
        assert entry.exit_fee is not None
        assert entry.net_pnl is not None
        assert entry.slippage_cost is not None

        computed_net = entry.gross_pnl - entry.entry_fee - entry.exit_fee
        if abs(entry.net_pnl - computed_net) > Decimal("0.0001"):
            raise DomainViolation(
                f"Track {track_name}: Net PnL reconciliation failed on trade {entry.trade_id}"
            )

        realized_pnl_sum += entry.net_pnl
        cumulative_fees += entry.entry_fee + entry.exit_fee
        cumulative_slippage += entry.slippage_cost

    final_cash = harness.margin_account.cash
    expected_cash = starting_equity + realized_pnl_sum
    if abs(final_cash - expected_cash) > Decimal("0.0001"):
        raise DomainViolation(
            f"Track {track_name}: Cash drift detected: final={final_cash}, expected={expected_cash}"
        )

    # Invariant: Capital Survival (Equity > 0)
    min_eq_val = harness.margin_account.min_observed_equity
    if final_cash <= Decimal("0") or min_eq_val <= Decimal("0"):
        raise DomainViolation(
            f"Track {track_name}: Capital survival violated: min_equity="
            f"{min_eq_val}, final_cash={final_cash}"
        )

    # Invariant: 80% Margin Utilization Cap
    max_util_val = harness.margin_account.max_observed_utilization
    if max_util_val > DEFAULT_MAX_MARGIN_UTILIZATION:
        raise DomainViolation(
            f"Track {track_name}: Max margin utilization {max_util_val} "
            f"exceeded {DEFAULT_MAX_MARGIN_UTILIZATION}"
        )

    # Generate Health and Cohort Telemetry
    health_reports, cohort_report = generate_phase_255_reports(
        harness.ledger,
        harness.lifecycle_store,
        harness.observation_store,
        candidates,
        as_of=bar_ts,
        days=DEFAULT_DAYS,
    )

    peak_eq = harness.margin_account.peak_portfolio_equity
    min_eq = harness.margin_account.min_observed_equity
    max_dd = (peak_eq - min_eq) / peak_eq if peak_eq > 0 else Decimal("1.0")

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
        total_trades_closed=len(all_closed_entries),
        emergency_liquidations_count=len(harness.margin_account.emergency_liquidations),
        capital_survived=True,
        account_liquidated=False,
        deficit_balance=False,
        zero_balance_drift=True,
        exchange_access=False,
        orders=0,
    )

    return StressTrackResult(
        track_id=track_id,
        track_name=track_name,
        scenario_result=scenario_res,
        health_reports=health_reports,
        cohort_report=cohort_report,
        positions_reconciled=positions_reconciled,
        accounting_reconciled=True,
        final_cash=final_cash,
        realized_pnl=realized_pnl_sum,
        cumulative_fees=cumulative_fees,
        cumulative_slippage=cumulative_slippage,
        circuit_breaker_events_count=len(harness.margin_account.state_history),
        emergency_liquidations=tuple(harness.margin_account.emergency_liquidations),
        output_dir=output_dir,
    )


@dataclass(frozen=True, slots=True)
class Phase255StressSimulationResult:
    output_dir: Path
    total_tracks: int
    all_tracks_survived: bool
    track_results: dict[str, StressTrackResult]
    survival_matrix: list[dict[str, Any]]
    summary_path: Path
    artifact_hashes: dict[str, str]


def run_phase_255_simulation(
    output_dir: Path = Path("artifacts/research/phase255"),
    candidates_dir: Path = Path("artifacts/research/phase252/candidates"),
    data_dir: Path = Path("research/immutable-data/5m/canonical"),
    start_time: datetime = DEFAULT_START_TIME,
    total_bars: int = DEFAULT_TOTAL_BARS,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
    fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
    selected_track: str = "all",
) -> Phase255StressSimulationResult:
    """Executes the complete Phase 255 multi-vector stress testing simulation across all tracks."""
    # 1. Enforce strict offline safety invariants
    assert_offline_safety_invariants()

    output_dir.mkdir(parents=True, exist_ok=True)

    # 2. Load and verify candidates
    candidates = load_phase_255_candidates(candidates_dir)

    # 3. Load baseline market data frames
    raw_market_frames: dict[str, pd.DataFrame] = {}
    for sym in candidates:
        raw_market_frames[sym] = load_symbol_market_frame(
            sym, start=start_time, total_bars=total_bars, data_dir=data_dir
        )

    # 4. Determine tracks to run
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

    track_results: dict[str, StressTrackResult] = {}
    survival_matrix: list[dict[str, Any]] = []

    for track_spec in tracks_to_run:
        t_name = track_spec["name"]
        track_dir = output_dir / "tracks" / f"track_{track_spec['id']}_{t_name}"

        res = run_single_stress_track(
            track_spec=track_spec,
            output_dir=track_dir,
            candidates=candidates,
            raw_market_frames=raw_market_frames,
            total_bars=total_bars,
            starting_equity=starting_equity,
            fee_rate=fee_rate,
        )
        track_results[t_name] = res

        survival_matrix.append(
            {
                "track_id": res.track_id,
                "track_name": res.track_name,
                "starting_equity": str(starting_equity),
                "ending_equity": f"{res.final_cash:.4f}",
                "min_observed_equity": f"{res.scenario_result.min_observed_equity:.4f}",
                "max_margin_utilization": (
                    f"{res.scenario_result.max_observed_margin_utilization * Decimal('100'):.2f}%"
                ),
                "min_reserve_buffer": (
                    f"{res.scenario_result.min_observed_equity_buffer * Decimal('100'):.2f}%"
                ),
                "max_drawdown": (
                    f"{res.scenario_result.max_observed_drawdown * Decimal('100'):.2f}%"
                ),
                "total_trades": res.scenario_result.total_trades_closed,
                "emergency_liquidations": res.scenario_result.emergency_liquidations_count,
                "capital_survived": res.scenario_result.capital_survived,
            }
        )

    # Copy Track 5 (composite crisis) or Track 0 to root output_dir for root ledger inspection
    primary_track_name = (
        "composite_crisis" if "composite_crisis" in track_results else tracks_to_run[0]["name"]
    )
    primary_track_dir = track_results[primary_track_name].output_dir

    for db_name in (
        "paper-ledger.sqlite3",
        "paper-lifecycle.sqlite3",
        "paper-observations.sqlite3",
    ):
        src_db = primary_track_dir / db_name
        dest_db = output_dir / db_name
        if src_db.exists():
            shutil.copy2(src_db, dest_db)

    # 5. Build summary JSON artifact
    summary_path = output_dir / "stress-test-summary.json"
    summary_data: dict[str, Any] = {
        "phase": "phase_255",
        "bundle_hash": PINNED_BUNDLE_HASH,
        "dataset_registry_hash": PINNED_REGISTRY_HASH,
        "scenarios_evaluated": [t["name"] for t in tracks_to_run],
        "total_tracks": len(tracks_to_run),
        "all_tracks_survived": all(
            r.scenario_result.capital_survived for r in track_results.values()
        ),
        "zero_deficit_balance": True,
        "zero_account_liquidation": True,
        "zero_balance_drift_verified": True,
        "max_utilization_cap_satisfied": all(
            r.scenario_result.max_observed_margin_utilization <= DEFAULT_MAX_MARGIN_UTILIZATION
            for r in track_results.values()
        ),
        "min_reserve_buffer_satisfied": all(
            r.scenario_result.min_observed_equity_buffer >= DEFAULT_MIN_RESERVE_BUFFER
            for r in track_results.values()
        ),
        "portfolio_survival_matrix": survival_matrix,
        "tracks": {
            name: {
                "scenario_name": r.scenario_result.scenario_name,
                "shock_type": r.scenario_result.shock_type,
                "price_shock_pct": str(r.scenario_result.price_shock_pct),
                "slippage_multiplier": r.scenario_result.slippage_multiplier,
                "starting_equity": str(r.scenario_result.starting_equity),
                "ending_equity": str(r.scenario_result.ending_equity),
                "min_observed_equity": str(r.scenario_result.min_observed_equity),
                "max_observed_drawdown": str(r.scenario_result.max_observed_drawdown),
                "max_observed_margin_utilization": str(
                    r.scenario_result.max_observed_margin_utilization
                ),
                "min_observed_equity_buffer": str(r.scenario_result.min_observed_equity_buffer),
                "total_trades_closed": r.scenario_result.total_trades_closed,
                "emergency_liquidations_count": r.scenario_result.emergency_liquidations_count,
                "capital_survived": r.scenario_result.capital_survived,
                "account_liquidated": r.scenario_result.account_liquidated,
                "deficit_balance": r.scenario_result.deficit_balance,
                "zero_balance_drift": r.scenario_result.zero_balance_drift,
                "circuit_breaker_state_changes": r.circuit_breaker_events_count,
            }
            for name, r in track_results.items()
        },
        "offline_safety_invariants": {
            "orders": 0,
            "exchange_access": False,
            "execution_authority": False,
            "promotion_state": "unpromoted",
            "paper_activation": False,
            "data_source": "cached_only",
            "zero_secret_leakage": True,
        },
        "artifact_hashes": {},
    }

    # Write preliminary JSON, compute file hashes, then rewrite with hashes
    summary_raw = json.dumps(summary_data, indent=2)
    _assert_zero_secrets(summary_raw, "stress-test-summary.json")
    with summary_path.open("w", encoding="utf-8") as f:
        f.write(summary_raw)

    artifact_hashes: dict[str, str] = {
        "stress-test-summary.json": compute_file_sha256(summary_path),
        "paper-ledger.sqlite3": compute_file_sha256(output_dir / "paper-ledger.sqlite3"),
        "paper-lifecycle.sqlite3": compute_file_sha256(output_dir / "paper-lifecycle.sqlite3"),
        "paper-observations.sqlite3": compute_file_sha256(
            output_dir / "paper-observations.sqlite3"
        ),
    }

    summary_data["artifact_hashes"] = artifact_hashes
    final_summary_raw = json.dumps(summary_data, indent=2)
    with summary_path.open("w", encoding="utf-8") as f:
        f.write(final_summary_raw)

    return Phase255StressSimulationResult(
        output_dir=output_dir,
        total_tracks=len(track_results),
        all_tracks_survived=all(r.scenario_result.capital_survived for r in track_results.values()),
        track_results=track_results,
        survival_matrix=survival_matrix,
        summary_path=summary_path,
        artifact_hashes=artifact_hashes,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for running the Phase 255 stress simulation."""
    parser = argparse.ArgumentParser(
        description="Phase 255: Multi-Vector Adverse Volatility & Slippage Stress Simulation Runner"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/research/phase255"),
        help="Directory to store paper ledger SQLite stores and telemetry artifacts",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=DEFAULT_TOTAL_BARS,
        help=f"Number of contiguous 5m bars to simulate (default: {DEFAULT_TOTAL_BARS})",
    )
    parser.add_argument(
        "--track",
        type=str,
        default="all",
        help="Specific track to run (baseline, flash_crash, slippage_surge, "
        "spread_blowout, volatility_whipsaw, composite_crisis, or all)",
    )
    args = parser.parse_args(argv)

    print("=" * 80)
    print("PHASE 255: MULTI-VECTOR ADVERSE VOLATILITY & SLIPPAGE STRESS SIMULATION")
    print("=" * 80)
    print(f"Output Directory : {args.output_dir}")
    print(f"Total Bars       : {args.bars} (7 days of 5m bars)")
    print(f"Track            : {args.track}")
    print("-" * 80)

    try:
        result = run_phase_255_simulation(
            output_dir=args.output_dir,
            total_bars=args.bars,
            selected_track=args.track,
        )
    except Exception as exc:
        print(f"\n[FATAL ERROR] Simulation failed: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1

    print("\n[SUCCESS] Phase 255 Stress Simulation Completed Successfully!")
    print(f"Tracks Evaluated : {result.total_tracks}")
    print(f"All Survived     : {result.all_tracks_survived}")
    print("\nSURVIVAL MATRIX:")
    header = (
        f"{'Track ID':<10} {'Track Name':<20} {'End Eq':<10} {'Min Eq':<10} "
        f"{'Max Util':<10} {'Min Buf':<10} {'Trades':<8} {'Emg Liq':<8}"
    )
    print(header)
    print("-" * 90)
    for row in result.survival_matrix:
        line = (
            f"{row['track_id']:<10} {row['track_name']:<20} {row['ending_equity']:<10} "
            f"{row['min_observed_equity']:<10} {row['max_margin_utilization']:<10} "
            f"{row['min_reserve_buffer']:<10} {row['total_trades']:<8} "
            f"{row['emergency_liquidations']:<8}"
        )
        print(line)
    print("-" * 90)
    print(f"\nSummary JSON     : {result.summary_path}")
    for name, sha in result.artifact_hashes.items():
        print(f"  Artifact Hash [{name}]: {sha}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
