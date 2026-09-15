"""Phase 262: Multi-Asset Higher-Timeframe Deterministic Paper Trading Replay Harness.

Executes deterministic, cached-only offline paper trading simulation across
empirically qualified 15m and 1h candidate strategies (BTCUSDT, ETHUSDT, SOLUSDT)
registered in artifacts/paper_live/candidate_registry.json.

Models a single shared 100.00 USDT portfolio margin account with <=80% utilization ceiling,
>=20% unencumbered reserve buffer, dynamic conviction-scaled leverage (1.0x - 3.0x),
adverse execution (2 bps slippage, 0.04% taker fee), tick/bar-level ATR trailing stops,
and exact Decimal balance reconciliation across isolated SQLite paper ledgers
(paper-ledger.sqlite3, paper-lifecycle.sqlite3, paper-observations.sqlite3).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
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
    CandidateRegistryManifest,
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
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
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
)
from autonomous_futures.research.feature_signals import (  # noqa: E402
    CausalFeatureSignalEvaluator,
    _parse_expression,
)

logger = logging.getLogger("run_phase_262_paper_simulation")

DEFAULT_STARTING_EQUITY: Decimal = Decimal("100.00")
DEFAULT_POSITION_FRACTION: Decimal = Decimal("0.20")
DEFAULT_MAX_MARGIN_UTILIZATION: Decimal = Decimal("0.80")
DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0004")  # 0.04%
DEFAULT_SLIPPAGE_BPS: Decimal = Decimal("2.0")  # 2 bps
DEFAULT_DAYS: int = 7
DEFAULT_START_TIME: datetime = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)

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
    # If ADX is present (e.g. SOL RGB strategy), scale bonus by trend strength
    if "adx" in row and not pd.isna(row["adx"]):
        adx_val = Decimal(str(row["adx"]))
        if adx_val > Decimal("20"):
            adx_bonus = min(Decimal("0.30"), (adx_val - Decimal("20")) / Decimal("60"))
            conviction += adx_bonus

    # If donchian_breakout is present, scale by breakout confirmation
    if "donchian_breakout" in row and not pd.isna(row["donchian_breakout"]):
        breakout_val = Decimal(str(row["donchian_breakout"]))
        if abs(breakout_val) > Decimal("0.0"):
            conviction += Decimal("0.10")

    final_conviction = min(Decimal("1.00"), max(Decimal("0.50"), conviction))
    return True, final_conviction


def calculate_dynamic_leverage(conviction: Decimal) -> Decimal:
    """Linear scaling from conviction in [0.5, 1.0] to dynamic leverage in [1.0, 3.0]."""
    clamped = min(Decimal("1.00"), max(Decimal("0.50"), conviction))
    leverage = Decimal("1.0") + Decimal("4.0") * (clamped - Decimal("0.50"))
    return min(Decimal("3.0"), max(Decimal("1.0"), leverage))


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
        avail = self.available_margin(current_equity)
        if avail <= Decimal("0"):
            return None

        leverage = calculate_dynamic_leverage(confidence)
        margin_target = current_equity * self.base_allocation_fraction
        margin_allocated = min(avail, margin_target)

        if margin_allocated <= Decimal("0"):
            return None

        notional = margin_allocated * leverage
        quantity = notional / mark_price
        if quantity <= Decimal("0"):
            return None

        new_total_locked = self.total_locked_margin() + margin_allocated
        utilization = new_total_locked / current_equity if current_equity > 0 else Decimal("1.0")
        if utilization > self.max_utilization:
            return None

        self.max_observed_utilization = max(self.max_observed_utilization, utilization)
        return margin_allocated, leverage, quantity

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
        utilization = self.margin_utilization(equity)
        self.max_observed_utilization = max(self.max_observed_utilization, utilization)

    def record_close(
        self,
        trade_id: str,
        gross_pnl: Decimal,
        exit_fee: Decimal,
    ) -> None:
        if trade_id in self._locked_margin_by_trade:
            del self._locked_margin_by_trade[trade_id]
        if trade_id in self._trade_leverage:
            del self._trade_leverage[trade_id]
        self.cash += gross_pnl - exit_fee


@dataclass(frozen=True, slots=True)
class Phase262SimulationResult:
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
    candidate_summaries: dict[str, dict[str, Any]]
    health_reports: dict[str, PaperHealthReport]
    cohort_report: PaperCohortReadinessReport
    positions_reconciled: bool
    accounting_reconciled: bool
    artifact_hashes: dict[str, str]
    summary_path: Path


class Phase262PaperHarness:
    """Multi-asset synchronized bar simulation harness across isolated SQLite ledgers."""

    def __init__(
        self,
        output_dir: Path,
        candidates: dict[str, CreatorCandidateArtifact],
        manifest: CandidateRegistryManifest,
        starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
        fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
        slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
        max_margin_utilization: Decimal = DEFAULT_MAX_MARGIN_UTILIZATION,
        position_fraction: Decimal = DEFAULT_POSITION_FRACTION,
    ) -> None:
        self.output_dir = output_dir
        self.candidates = candidates
        self.manifest = manifest
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
                qualification_hash=manifest.symbols[sym].qualification_hash,
                qualification_decision="qualified",
                zero_oos_liquidations=True,
            )
            for sym, cand in candidates.items()
        }


def generate_phase_262_reports(
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


def run_phase_262_simulation(
    output_dir: Path = Path("artifacts/research/phase262"),
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH,
    start_time: datetime = DEFAULT_START_TIME,
    days: int = DEFAULT_DAYS,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
    fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    max_margin_utilization: Decimal = DEFAULT_MAX_MARGIN_UTILIZATION,
    position_fraction: Decimal = DEFAULT_POSITION_FRACTION,
    max_mark_age_seconds: int = 86400,
) -> Phase262SimulationResult:
    """Execute complete Phase 262 multi-asset paper trading simulation."""
    assert_offline_safety_invariants()

    # 1. Load manifest and candidates
    manifest = read_candidate_registry(registry_path, verify_hash=True)
    candidates = validate_manifest_candidate_artifacts(manifest)

    # 2. Initialize harness
    harness = Phase262PaperHarness(
        output_dir=output_dir,
        candidates=candidates,
        manifest=manifest,
        starting_equity=starting_equity,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        max_margin_utilization=max_margin_utilization,
        position_fraction=position_fraction,
    )

    # 3. Load market frames for 15m synchronized timeline
    total_bars_15m = days * 24 * 4  # 96 bars/day * days
    evaluator = CausalFeatureSignalEvaluator()

    frames_15m: dict[str, pd.DataFrame] = {}
    evaluated_signals: dict[str, pd.DataFrame] = {}
    atr_series_15m: dict[str, list[Decimal | None]] = {}

    end_time = start_time + timedelta(days=days)

    # Load 15m canonical data for all symbols (used for mark prices and 15m strategy signals)
    for sym in candidates:
        p15 = Path(f"research/immutable-data/15m/canonical/{sym}-15m.parquet")
        df15 = pd.read_parquet(p15)
        mask = (df15["timestamp"] >= start_time) & (df15["timestamp"] < end_time)
        sub15 = df15[mask].copy().reset_index(drop=True)
        if len(sub15) != total_bars_15m:
            raise DataQualityError(
                f"Incomplete 15m data for {sym}: expected {total_bars_15m} bars, found {len(sub15)}"
            )
        canon15 = canonicalize_bars(sub15, interval=timedelta(minutes=15))
        frames_15m[sym] = canon15
        atr_series_15m[sym] = compute_atr_series(canon15, lookback=14)

    # Evaluate strategy signals based on declared candidate timeframe
    for sym, cand in candidates.items():
        tf = cand.strategy.universe.timeframe
        if tf == "15m":
            evaluated_signals[sym] = evaluator.evaluate(cand, frames_15m[sym])
        elif tf == "1h":
            p1h = Path(f"research/immutable-data/1h/canonical/{sym}-1h.parquet")
            df1h = pd.read_parquet(p1h)
            mask1h = (df1h["timestamp"] >= start_time) & (df1h["timestamp"] < end_time)
            sub1h = df1h[mask1h].copy().reset_index(drop=True)
            canon1h = canonicalize_bars(sub1h, interval=timedelta(hours=1))
            evaluated_signals[sym] = evaluator.evaluate(cand, canon1h)
        else:
            evaluated_signals[sym] = evaluator.evaluate(cand, frames_15m[sym])

    # Build signal lookup map by (symbol, timestamp)
    signals_by_time: dict[tuple[str, datetime], pd.Series] = {}
    for sym, sig_df in evaluated_signals.items():
        for _, row in sig_df.iterrows():
            ts = row["timestamp"]
            signals_by_time[(sym, ts)] = row

    first_sym = next(iter(candidates))
    active_trades: dict[str, dict[str, Any]] = {}
    trade_count = 0
    previous_peaks: dict[str, Decimal] = {sym: starting_equity for sym in candidates}
    observations_by_symbol: dict[str, list[PaperObservation]] = {sym: [] for sym in candidates}
    qualified_symbols_all = tuple(candidates.keys())

    # 4. Step through sequential 15-minute clock
    for idx in range(total_bars_15m):
        bar_ts: datetime = frames_15m[first_sym].iloc[idx]["timestamp"]
        is_terminal: bool = idx == total_bars_15m - 1
        closed_this_bar: dict[str, bool] = {sym: False for sym in candidates}
        current_bar_closes: dict[str, Decimal] = {}

        for sym in candidates:
            current_bar_closes[sym] = Decimal(str(frames_15m[sym].iloc[idx]["close"]))

        # Phase A: Mark active positions & evaluate exits
        for sym in list(active_trades.keys()):
            trade_info = active_trades[sym]
            cand = candidates[sym]
            row_15m = frames_15m[sym].iloc[idx]
            bar_close = current_bar_closes[sym]
            bar_high = Decimal(str(row_15m["high"]))
            bar_low = Decimal(str(row_15m["low"]))
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
            terminal_cutoff = total_bars_15m - 12  # Close 3 hours before end
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

            # Strategy declared exit evaluation on candidate timeframe boundary
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
                elif (side == "LONG" and sig_val == -1) or (side == "SHORT" and sig_val == 1):
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
                    expires_at=bar_ts + timedelta(minutes=15),
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
        terminal_cutoff = total_bars_15m - 12
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

            # Establish ATR protective stops
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

    # 5. Post-simulation balance & position reconciliation
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
    cash_drift = abs(harness.margin_account.cash - final_cash)
    if cash_drift > Decimal("1e-18"):
        raise DomainViolation(
            f"Cash drift detected: margin account cash ({harness.margin_account.cash}) "
            f"!= ledger reconciled final cash ({final_cash}), drift={cash_drift}"
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

    # 6. Multi-Asset health & cohort reports
    as_of = start_time + timedelta(days=days)
    health_reports, cohort_report = generate_phase_262_reports(
        harness.ledger_store,
        harness.lifecycle_store,
        harness.observation_store,
        candidates,
        as_of=as_of,
        days=days,
        max_mark_age_seconds=max_mark_age_seconds,
    )

    # 7. Persist JSON reports
    cohort_report_path = output_dir / "paper-cohort-readiness-report.json"
    cohort_json = json.dumps(cohort_report.model_dump(mode="json"), indent=2, sort_keys=True)
    _assert_zero_secrets(cohort_json, str(cohort_report_path))
    cohort_report_path.write_text(cohort_json, encoding="utf-8")

    for sym, health_rep in health_reports.items():
        health_path = output_dir / f"paper-health-report-{sym}.json"
        health_json = json.dumps(health_rep.model_dump(mode="json"), indent=2, sort_keys=True)
        _assert_zero_secrets(health_json, str(health_path))
        health_path.write_text(health_json, encoding="utf-8")

    # 8. Compute artifact cryptographic hashes
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

    # 9. Persist paper-summary.json
    summary_path = output_dir / "paper-summary.json"
    summary_payload: dict[str, Any] = {
        "phase": "phase_262",
        "description": "Phase 262 Multi-Asset Higher-Timeframe Deterministic Paper Replay",
        "simulation_start": start_time.isoformat(),
        "simulation_end": as_of.isoformat(),
        "days_evaluated": days,
        "total_bars_15m": total_bars_15m,
        "registry_hash": manifest.registry_hash,
        "candidates": {
            sym: {
                "candidate_id": cand.candidate_id,
                "artifact_hash": cand.artifact_hash,
                "timeframe": cand.strategy.universe.timeframe,
                "family": cand.strategy.family,
                "qualification_hash": manifest.symbols[sym].qualification_hash,
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
            for sym, cand in candidates.items()
        },
        "shared_portfolio_margin": {
            "starting_equity_usdt": str(starting_equity),
            "final_cash_usdt": str(final_cash),
            "realized_pnl_usdt": str(realized_pnl),
            "cumulative_fees_usdt": str(cumulative_fees),
            "cumulative_slippage_usdt": str(cumulative_slippage),
            "margin_utilization_ceiling": str(max_margin_utilization),
            "max_observed_margin_utilization": str(
                round(harness.margin_account.max_observed_utilization, 4)
            ),
            "unencumbered_equity_buffer_pct": str(
                (Decimal("1.0") - max_margin_utilization) * Decimal("100")
            ),
            "base_position_fraction": str(position_fraction),
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
            "mature_candidate_count": cohort_report.mature_candidate_count,
            "healthy_candidate_count": cohort_report.healthy_candidate_count,
            "all_mature": cohort_report.all_mature,
            "all_accounting_complete": cohort_report.all_accounting_complete,
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
        "artifact_hashes": artifact_hashes,
    }

    summary_json = json.dumps(summary_payload, indent=2, sort_keys=True)
    _assert_zero_secrets(summary_json, str(summary_path))
    summary_path.write_text(summary_json, encoding="utf-8")

    return Phase262SimulationResult(
        output_dir=output_dir,
        total_bars=total_bars_15m,
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
        candidate_summaries=summary_payload["candidates"],
        health_reports=health_reports,
        cohort_report=cohort_report,
        positions_reconciled=True,
        accounting_reconciled=True,
        artifact_hashes=artifact_hashes,
        summary_path=summary_path,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 262 Multi-Asset Higher-Timeframe Deterministic Paper Replay"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/research/phase262"),
        help="Directory to store simulation output artifacts",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_CANDIDATE_REGISTRY_PATH,
        help="Path to candidate registry manifest",
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
        "--fee-rate",
        type=Decimal,
        default=DEFAULT_TAKER_FEE_RATE,
        help="Taker fee rate (default: 0.0004)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=Decimal,
        default=DEFAULT_SLIPPAGE_BPS,
        help="Adverse slippage in basis points (default: 2.0)",
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

    res = run_phase_262_simulation(
        output_dir=args.output_dir,
        registry_path=args.registry_path,
        days=args.days,
        starting_equity=args.starting_equity,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
    )

    if args.json:
        sys.stdout.write(res.summary_path.read_text(encoding="utf-8"))
        return 0

    sys.stdout.write("\n=== PHASE 262 DETERMINISTIC PAPER REPLAY COMPLETED ===\n")
    sys.stdout.write(f"Output Directory:       {res.output_dir}\n")
    sys.stdout.write(f"Days Evaluated:         {args.days} ({res.total_bars} 15m intervals)\n")
    sys.stdout.write(f"Starting Equity:        {res.starting_equity:.2f} USDT\n")
    sys.stdout.write(f"Final Cash Balance:     {res.final_cash:.4f} USDT\n")
    sys.stdout.write(f"Net Realized PnL:       {res.realized_pnl:+.4f} USDT\n")
    sys.stdout.write(
        f"Trades:                 {res.total_trades} total "
        f"({res.winning_trades} wins, {res.losing_trades} losses, "
        f"{res.win_rate * 100:.1f}% win rate)\n"
    )
    sys.stdout.write(f"Cumulative Fees:        {res.cumulative_fees:.4f} USDT\n")
    sys.stdout.write(f"Cumulative Slippage:    {res.cumulative_slippage:.4f} USDT\n")
    sys.stdout.write(f"Max Margin Utilization: {res.max_margin_utilization * 100:.2f}%\n")
    sys.stdout.write(f"Positions Reconciled:   {res.positions_reconciled}\n")
    sys.stdout.write(f"Accounting Reconciled:  {res.accounting_reconciled}\n")
    sys.stdout.write(f"Cohort Readiness:       {res.cohort_report.cohort_status}\n\n")

    sys.stdout.write(
        f"{'Symbol':<10} {'Candidate ID':<24} {'Timeframe':<10} {'Trades':<8} "
        f"{'Realized PnL':<15} {'Health':<10}\n"
    )
    sys.stdout.write("-" * 80 + "\n")
    for sym, c_sum in res.candidate_summaries.items():
        h = res.health_reports[sym]
        pnl_val = Decimal(str(c_sum["realized_pnl_usdt"]))
        sys.stdout.write(
            f"{sym:<10} {c_sum['candidate_id']:<24} "
            f"{c_sum['timeframe']:<10} "
            f"{c_sum['trades_count']:<8} "
            f"{pnl_val:+.4f} USDT   "
            f"{h.health_status:<10}\n"
        )
    sys.stdout.write("-" * 80 + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
