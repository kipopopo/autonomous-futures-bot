"""Autonomous Futures Bot - Phase 310: Real Autonomous Trading Engine.

Self-Driving Trading Engine integrating:
- Dual-mode Binance Futures Gateway Bridge (REST & WebSocket)
- 15m Macro-Confluence Liquidity Dip Scalper with Bitcoin Macro Trend Gate
- Closed-loop self-learning & trade autopsy feedback
  (StrategyAutopsyEngine & ContinuousSelfLearningDaemon)
- SQLite telemetry persistence (trade_autopsies, candidate_health, orders)
- Dynamic micro-capital bounds (child <= 5.00 USDT, aggregate <= 25.00 USDT, cash >= 75.0%)
- Fail-closed 3.00 USDT daily drawdown circuit breaker
- Strict mathematical double-entry zero-drift balance invariant (|drift| < 10^-15 USDT)
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import logging
import math
import shutil
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.execution.binance_gateway import (
    BinanceFuturesGateway,
    generate_client_order_id,
    generate_p317_ict_client_order_id,
    quantize_step_size,
    quantize_tick_size,
)
from autonomous_futures.feed.auto_evolution import (
    DEFAULT_ICT_GENOMES,
    AutopsyAttributionCause,
    CandidateHealthEvaluation,
    CandidateHealthTier,
    ContinuousSelfLearningDaemon,
    IctAutopsyCalculator,
    IctAutopsyMetrics,
    StrategyAutopsyEngine,
    TradeAutopsyRecord,
)
from autonomous_futures.safety.kill_switch import (
    CentralizedSolvencyLedger,
    HardwareOSKillSwitchEngine,
    KillSwitchState,
    MultiSigGovernanceEngine,
    SignerIdentity,
    SolvencyLedgerSnapshot,
)
from autonomous_futures.strategy.ict_mmxm import TwinsSetupState
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
    ScalperSignal,
)

logger = logging.getLogger("autonomous_futures.execution.self_driving")


def _finite_evidence_value(value: float | None) -> bool:
    """Return whether an optional telemetry value is finite without inventing a fallback."""
    try:
        return value is not None and math.isfinite(value)
    except TypeError:
        return False


UPSTREAM_PHASE_309_MERKLE_ROOT = "5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844"


class SelfDrivingState(enum.StrEnum):
    """Lifecycle states of the autonomous self-driving trading engine."""

    COLD_STANDBY = "COLD_STANDBY"
    PRE_FLIGHT_CHECK = "PRE_FLIGHT_CHECK"
    MICRO_CAPITAL_ACTIVE = "MICRO_CAPITAL_ACTIVE"
    HAWKES_THROTTLED = "HAWKES_THROTTLED"
    CIRCUIT_FLATTENED = "CIRCUIT_FLATTENED"
    KILL_SWITCH_HALTED = "KILL_SWITCH_HALTED"


class OrderSide(enum.StrEnum):
    """Trading order side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(enum.StrEnum):
    """State of an autonomous child order."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclasses.dataclass
class MicroCapitalConfig:
    """Strict risk boundaries for micro-capital self-driving confinement."""

    max_micro_order_notional_usdt: Decimal = Decimal("5.00")
    max_aggregate_exposure_usdt: Decimal = Decimal("25.00")
    min_cash_reserve_pct: Decimal = Decimal("75.0")
    intra_day_loss_ceiling_usdt: Decimal = Decimal("3.00")
    max_hawkes_spectral_radius: float = 1.0
    max_heartbeat_latency_ms: float = 500.0

    def __post_init__(self) -> None:
        values = (
            self.max_micro_order_notional_usdt,
            self.max_aggregate_exposure_usdt,
            self.min_cash_reserve_pct,
            self.intra_day_loss_ceiling_usdt,
        )
        if not all(v.is_finite() for v in values) or not (
            Decimal("0") < self.max_micro_order_notional_usdt <= Decimal("5")
            and Decimal("0") < self.max_aggregate_exposure_usdt <= Decimal("25")
            and Decimal("75") <= self.min_cash_reserve_pct <= Decimal("100")
            and Decimal("0") < self.intra_day_loss_ceiling_usdt <= Decimal("3")
        ):
            raise ValueError("Configuration cannot relax the micro-capital limits")


@dataclasses.dataclass
class CandidateState:
    """Real-time position and allocation tracking for an individual market candidate."""

    symbol: str
    current_price: Decimal
    position_qty: Decimal = Decimal("0.0")
    entry_price: Decimal = Decimal("0.0")
    allocated_exposure_usdt: Decimal = Decimal("0.0")
    unrealized_pnl_usdt: Decimal = Decimal("0.0")
    realized_pnl_usdt: Decimal = Decimal("0.0")
    total_fees_usdt: Decimal = Decimal("0.0")
    trades_count: int = 0
    health_tier: CandidateHealthTier = CandidateHealthTier.PROBATIONARY
    entry_time_ms: int = 0
    entry_bar_index: int = 0
    _stop_loss: Decimal | None = dataclasses.field(default=None, repr=False)
    _take_profit: Decimal | None = dataclasses.field(default=None, repr=False)

    @property
    def stop_loss(self) -> Decimal:
        return self._stop_loss if self._stop_loss is not None else Decimal("0.0")

    @stop_loss.setter
    def stop_loss(self, val: Decimal | None) -> None:
        self._stop_loss = val

    @property
    def take_profit(self) -> Decimal:
        return self._take_profit if self._take_profit is not None else Decimal("0.0")

    @take_profit.setter
    def take_profit(self, val: Decimal | None) -> None:
        self._take_profit = val


@dataclasses.dataclass
class SelfDrivingOrder:
    """Individual sliced order placed by the self-driving engine."""

    order_id: str
    symbol: str
    side: OrderSide
    order_type: str
    price: Decimal
    quantity: Decimal
    notional_usdt: Decimal
    status: OrderStatus
    timestamp_ms: int
    client_order_id: str
    fee_usdt: Decimal = Decimal("0.0")
    realized_pnl_usdt: Decimal = Decimal("0.0")
    execution_latency_ms: float = 0.0
    is_maker: bool = True
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    max_hold_bars: int = 8


class Phase317SolvencyLedger(CentralizedSolvencyLedger):
    """Enforces mathematical double-entry zero-drift balance invariant under mark-to-market."""

    def __init__(self, starting_equity: Decimal | float = Decimal("100.00")) -> None:
        super().__init__(starting_equity=starting_equity)
        self.min_cash_reserve_floor_pct = Decimal("75")
        self._margins: dict[str, Decimal] = {}
        self._quantities: dict[str, Decimal] = {}

    def record_fill(
        self,
        symbol: str,
        side: str,
        qty: Decimal | float,
        price: Decimal | float,
        fee: Decimal | float = Decimal("0"),
        realized_pnl: Decimal | float = Decimal("0"),
    ) -> bool:
        """Conserve wallet while reserving/releasing position capital exactly."""
        quantity, fill_price = Decimal(str(qty)), Decimal(str(price))
        fee_dec, pnl = Decimal(str(fee)), Decimal(str(realized_pnl))
        previous = self._quantities.get(symbol, Decimal("0"))
        change = quantity if side == "BUY" else -quantity
        current = previous + change
        old_margin = self._margins.get(symbol, Decimal("0"))
        if previous == 0 or previous * change >= 0:
            new_margin = old_margin + quantity * fill_price
        else:
            close_qty = min(abs(previous), quantity)
            released = old_margin * close_qty / abs(previous)
            new_margin = (
                old_margin - released + max(Decimal("0"), quantity - close_qty) * fill_price
            )
        self.cash += old_margin - new_margin + pnl - fee_dec
        self.allocated_margin += new_margin - old_margin
        self.realized_pnl += pnl - fee_dec
        self.total_fees += fee_dec
        self._margins[symbol] = new_margin
        self._quantities[symbol] = current
        return True

    def get_snapshot(self) -> SolvencyLedgerSnapshot:
        """Returns verified double-entry snapshot with mark-to-market zero-drift reconciliation."""
        total_equity = self.cash + self.allocated_margin + self.unrealized_pnl
        expected_equity = self.starting_equity + self.realized_pnl + self.unrealized_pnl
        drift = total_equity - expected_equity
        zero_drift = abs(drift) < Decimal("1e-15")

        cash_pct = (
            (self.cash / total_equity) * Decimal("100.0") if total_equity > 0 else Decimal("0")
        )
        unencumbered_cash_ok = cash_pct >= self.min_cash_reserve_floor_pct

        return SolvencyLedgerSnapshot(
            starting_equity=float(self.starting_equity),
            cash=float(self.cash),
            allocated_margin=float(self.allocated_margin),
            unrealized_pnl=float(self.unrealized_pnl),
            realized_pnl=float(self.realized_pnl),
            total_equity=float(total_equity),
            drift=float(drift),
            zero_balance_drift=zero_drift,
            cash_reserve_pct=float(cash_pct),
            unencumbered_cash_verified=unencumbered_cash_ok,
        )

    def flatten_position(self, symbol: str, notional: float, fee: float = 0.001) -> None:
        """Simulates position flattening during emergency shutdown with margin return."""
        fee_dec = Decimal(str(fee))
        notional_dec = Decimal(str(notional))
        self.cash -= fee_dec
        self.total_fees += fee_dec
        self.realized_pnl -= fee_dec
        if self.allocated_margin > Decimal("0.0"):
            released = min(self.allocated_margin, notional_dec)
            self.allocated_margin -= released
            self.cash += released


class SelfDrivingTradingEngine:
    """Master Autonomous Trading Engine with Binance Gateway and Autopsy Feedback."""

    def __init__(
        self,
        starting_capital_usdt: Decimal = Decimal("100.00"),
        config: MicroCapitalConfig | None = None,
        multisig: MultiSigGovernanceEngine | None = None,
        kill_switch: HardwareOSKillSwitchEngine | None = None,
        gateway: BinanceFuturesGateway | None = None,
        storage_dir: Path | None = None,
    ) -> None:
        self.config = config or MicroCapitalConfig()
        self.state = SelfDrivingState.COLD_STANDBY
        self.gateway = gateway or BinanceFuturesGateway(offline_mode=True)
        self.storage_dir = storage_dir or Path("artifacts/research/phase310")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Multi-Sig Governance Engine setup
        if multisig is not None:
            self.multisig = multisig
        else:
            default_signers = [
                SignerIdentity("signer-cro-alice", "pub-alice-cro-310", "CHIEF_RISK_OFFICER"),
                SignerIdentity("signer-sec-bob", "pub-bob-sec-310", "SECURITY_OFFICER"),
                SignerIdentity("signer-dev-charlie", "pub-charlie-dev-310", "LEAD_DEV_DEVOPS"),
            ]
            self.multisig = MultiSigGovernanceEngine(signers=default_signers, required_quorum=2)

        # Centralized Solvency Ledger
        self.ledger = Phase317SolvencyLedger(starting_equity=starting_capital_usdt)

        # Hardware/OS Kill Switch
        if kill_switch is not None:
            self.kill_switch = kill_switch
        else:
            self.kill_switch = HardwareOSKillSwitchEngine(
                governance=self.multisig,
                solvency_ledger=self.ledger,
            )

        # Strategy & Autopsy Components
        self.trend_filter = MacroTrendFilter()
        self.scalper = MacroLiquidityDipScalper()
        self.autopsy_engine = StrategyAutopsyEngine(taker_fee_rate=0.0004, maker_fee_rate=0.0002)
        self.self_learning_daemon = ContinuousSelfLearningDaemon(min_sample_size=5)

        # Market tracking state (Phase 315: 8-pair universe)
        self.candidates: dict[str, CandidateState] = {
            "BTCUSDT": CandidateState(symbol="BTCUSDT", current_price=Decimal("0")),
            "ETHUSDT": CandidateState(symbol="ETHUSDT", current_price=Decimal("0")),
            "SOLUSDT": CandidateState(symbol="SOLUSDT", current_price=Decimal("0")),
            "DOGEUSDT": CandidateState(symbol="DOGEUSDT", current_price=Decimal("0")),
            "BNBUSDT": CandidateState(symbol="BNBUSDT", current_price=Decimal("0")),
            "XRPUSDT": CandidateState(symbol="XRPUSDT", current_price=Decimal("0")),
            "SUIUSDT": CandidateState(symbol="SUIUSDT", current_price=Decimal("0")),
            "AVAXUSDT": CandidateState(symbol="AVAXUSDT", current_price=Decimal("0")),
            "NEARUSDT": CandidateState(symbol="NEARUSDT", current_price=Decimal("0")),
            "LINKUSDT": CandidateState(symbol="LINKUSDT", current_price=Decimal("0")),
            "APTUSDT": CandidateState(symbol="APTUSDT", current_price=Decimal("0")),
            "ADAUSDT": CandidateState(symbol="ADAUSDT", current_price=Decimal("0")),
        }

        # Execution records & telemetry
        self.orders: list[SelfDrivingOrder] = []
        self.events_log: list[dict[str, Any]] = []
        self.autopsies: dict[str, list[TradeAutopsyRecord]] = {sym: [] for sym in self.candidates}
        self.health_evaluations: dict[str, CandidateHealthEvaluation] = {}
        self.interlock_blocks_count: int = 0
        self.intra_day_loss_usdt: Decimal = Decimal("0.0")
        self.latest_btc_ema50: float = 0.0
        self.latest_btc_ema200: float = 0.0

        # Phase 317 M4: ICT Autopsy decoupled queue and telemetry
        self._pending_autopsies: deque[dict[str, Any] | IctAutopsyMetrics] = deque()
        self.ict_autopsy_calculator = IctAutopsyCalculator()
        self.ict_autopsies: dict[str, list[IctAutopsyMetrics]] = {
            sym: [] for sym in self.candidates
        }

        # Database initialization
        self._telemetry_conn: sqlite3.Connection | None = None
        self._telemetry_db_path: Path | None = None
        self._db_lock = threading.RLock()
        self._autopsy_lock = threading.Lock()
        self.db_path = self.storage_dir / "canary-production-telemetry.sqlite3"
        self.events_path = self.storage_dir / "canary-production-events.jsonl"
        self._init_sqlite_db()

    @property
    def event_log(self) -> list[dict[str, Any]]:
        """Alias for events_log for Phase 309/310 compatibility."""
        return self.events_log

    def __iter__(self) -> Any:
        """Enables tuple unpacking (engine, multisig) for legacy factory call compatibility."""
        return iter((self, self.multisig))

    def _init_sqlite_db(self) -> None:
        """Initializes SQLite telemetry tables and compatibility views."""
        conn = self._get_telemetry_db_conn(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trade_autopsies (
                trade_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                fill_qty REAL NOT NULL,
                entry_timing_error_bps REAL NOT NULL,
                hawkes_slip_drag_bps REAL NOT NULL,
                adverse_selection_bps REAL NOT NULL,
                realized_edge_bps REAL NOT NULL,
                gross_pnl_usdt REAL NOT NULL,
                fee_cost_usdt REAL NOT NULL,
                net_pnl_usdt REAL NOT NULL,
                hold_duration_bars INTEGER NOT NULL,
                hold_duration_ms INTEGER NOT NULL,
                cause TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL
            );
        """)
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS candidate_health (
                candidate_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                tier TEXT NOT NULL,
                rolling_sharpe REAL NOT NULL,
                win_rate_pct REAL NOT NULL,
                max_drawdown_pct REAL NOT NULL,
                hawkes_resilience_score REAL NOT NULL,
                total_trades INTEGER NOT NULL,
                consecutive_losses INTEGER NOT NULL,
                needs_mutation INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                client_order_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                notional_usdt REAL NOT NULL,
                status TEXT NOT NULL,
                fee_usdt REAL NOT NULL,
                realized_pnl_usdt REAL NOT NULL,
                timestamp_ms INTEGER NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS solvency_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_ms INTEGER NOT NULL,
                cash REAL NOT NULL,
                allocated_margin REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                starting_equity REAL NOT NULL,
                total_equity REAL NOT NULL,
                drift REAL NOT NULL
            );
        """)
        cur.execute("CREATE VIEW IF NOT EXISTS trades AS SELECT * FROM orders;")
        cur.execute("CREATE VIEW IF NOT EXISTS autopsies AS SELECT * FROM trade_autopsies;")
        cur.execute("CREATE VIEW IF NOT EXISTS reconciliation AS SELECT * FROM solvency_snapshots;")
        cur.execute("CREATE VIEW IF NOT EXISTS telemetry AS SELECT * FROM candidate_health;")
        conn.commit()

    def _get_telemetry_db_conn(self, db_path: Path | None = None) -> sqlite3.Connection:
        """Retrieves or creates a cached persistent SQLite connection in WAL mode.

        Eliminates the ~16-19ms overhead of connecting/closing per transaction on Windows NTFS.
        """
        target = Path(db_path or self.db_path).resolve()
        with self._db_lock:
            if self._telemetry_conn is not None and self._telemetry_db_path == target:
                return self._telemetry_conn

            if self._telemetry_conn is not None:
                try:
                    self._telemetry_conn.commit()
                except Exception:
                    pass
                try:
                    self._telemetry_conn.close()
                except Exception:
                    pass

            target.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(target, check_same_thread=False, timeout=30.0)
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            self._telemetry_conn = conn
            self._telemetry_db_path = target
            return self._telemetry_conn

    def close_telemetry_db(self) -> None:
        """Closes cached SQLite telemetry database connection if open."""
        with self._db_lock:
            if self._telemetry_conn is not None:
                try:
                    self._telemetry_conn.commit()
                except Exception:
                    pass
                try:
                    self._telemetry_conn.close()
                except Exception:
                    pass
                self._telemetry_conn = None
                self._telemetry_db_path = None

    def close(self) -> None:
        """Closes all engine resources and active database handles."""
        self.close_telemetry_db()

    def __del__(self) -> None:
        self.close_telemetry_db()

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Appends a structured event line to JSONL audit file and in-memory log."""
        record = {
            "timestamp_ms": int(time.time() * 1000),
            "event_type": event_type,
            "state": self.state.value,
            **payload,
        }
        self.events_log.append(record)
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def _record_event(self, event_type: str, message: str = "", **kwargs: Any) -> None:
        """Compatibility helper for recording events."""
        self._append_event(event_type, {"message": message, **kwargs})

    def perform_preflight_checks(self) -> bool:
        """Performs initial multi-sig quorum and kill-switch pre-flight sanity checks."""
        self.state = SelfDrivingState.PRE_FLIGHT_CHECK

        # 1. Kill-Switch must be Armed Normal
        if self.kill_switch.state != KillSwitchState.ARMED_NORMAL:
            logger.error(
                "Pre-flight check failed: Kill-switch is in state %s", self.kill_switch.state
            )
            self.state = SelfDrivingState.KILL_SWITCH_HALTED
            return False

        # 2. Solvency ledger must exhibit exact zero-drift balance
        snap: SolvencyLedgerSnapshot = self.ledger.get_snapshot()
        if not snap.zero_balance_drift:
            logger.error(
                "Pre-flight check failed: Balance drift %s breaches zero-drift", snap.drift
            )
            return False

        # 3. Cash reserve must satisfy minimum threshold
        if snap.cash_reserve_pct < float(self.config.min_cash_reserve_pct):
            logger.error(
                "Pre-flight check failed: Cash reserve %s%% < min %s%%",
                snap.cash_reserve_pct,
                self.config.min_cash_reserve_pct,
            )
            return False

        self.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE
        self._append_event("PRE_FLIGHT_PASSED", {"status": "SUCCESS"})
        return True

    def run_pre_flight_check(self) -> bool:
        """Alias for perform_preflight_checks for Phase 309/310 compatibility."""
        return self.perform_preflight_checks()

    def _round_step_size(self, quantity: Decimal, step_size: Decimal) -> Decimal:
        """Rounds down order quantity strictly obeying Binance LOT_SIZE step rules."""
        return quantize_step_size(quantity, step_size)

    def _round_tick_size(self, price: Decimal, tick_size: Decimal) -> Decimal:
        """Rounds price to Binance PRICE_FILTER tick size."""
        return quantize_tick_size(price, tick_size)

    def _calculate_child_order_qty(
        self,
        symbol: str,
        price: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Calculates Binance-compliant micro-order quantity with MIN_NOTIONAL precision step-up.

        Returns:
            (quantized_price, quantized_qty, actual_notional)
        """
        if price <= Decimal("0"):
            return Decimal("0.0"), Decimal("0.0"), Decimal("0.0")

        spec = self.gateway.symbol_specs.get(symbol.upper(), {})
        step_size = spec.get("step_size", Decimal("0.001"))
        tick_size = spec.get("tick_size", Decimal("0.01"))
        min_notional = spec.get("min_notional", Decimal("5.00"))

        quantized_price = self._round_tick_size(price, tick_size)
        if quantized_price <= Decimal("0"):
            return quantized_price, Decimal("0.0"), Decimal("0.0")

        target_notional = self.config.max_micro_order_notional_usdt

        raw_qty = target_notional / quantized_price
        quantized_qty = self._round_step_size(raw_qty, step_size)
        actual_notional = quantized_qty * quantized_price

        if quantized_qty < spec.get("min_qty", step_size) or not (
            min_notional <= actual_notional <= self.config.max_micro_order_notional_usdt
        ):
            return quantized_price, Decimal("0"), Decimal("0")

        return quantized_price, quantized_qty, actual_notional

    def process_microstructure_tick(
        self,
        symbol: str,
        price: Decimal,
        hawkes_spectral_radius: float | None = None,
        heartbeat_age_ms: float | None = None,
        ensemble_signal: str = "NEUTRAL",
        ts_ms: int | None = None,
        *,
        hawkes_rho: float | None = None,
        heartbeat_latency_ms: float | None = None,
        signal_confidence: float = 0.85,
        now_ms: int | None = None,
        **kwargs: Any,
    ) -> SelfDrivingOrder | None:
        """Ingests live market tick, runs risk interlocks, and dispatches micro order."""
        hsr = hawkes_spectral_radius if hawkes_spectral_radius is not None else hawkes_rho
        h_age = heartbeat_age_ms if heartbeat_age_ms is not None else heartbeat_latency_ms
        now_timestamp = (
            ts_ms
            if ts_ms is not None
            else (now_ms if now_ms is not None else int(time.time() * 1000))
        )

        # Handle negative, zero, or sub-tick price fail-closed
        spec = self.gateway.symbol_specs.get(symbol.upper(), {})
        tick_size = spec.get("tick_size", Decimal("0.01"))
        if price <= Decimal("0") or price < (tick_size * Decimal("0.5")):
            logger.warning("Order rejected: Invalid or sub-tick price %s for %s", price, symbol)
            self.interlock_blocks_count += 1
            self._append_event("INVALID_PRICE_BLOCK", {"symbol": symbol, "price": str(price)})
            return None

        # Ensure engine is active
        if self.state not in (
            SelfDrivingState.MICRO_CAPITAL_ACTIVE,
            SelfDrivingState.HAWKES_THROTTLED,
        ):
            logger.warning("Order rejected: Engine not active (state=%s)", self.state)
            self.interlock_blocks_count += 1
            return None

        # Update candidate mark price & unrealized PnL
        cand = self.candidates.get(symbol.upper())
        if not cand:
            return None

        cand.current_price = price
        if cand.position_qty > Decimal("0"):
            cand.unrealized_pnl_usdt = (price - cand.entry_price) * cand.position_qty
        elif cand.position_qty < Decimal("0"):
            cand.unrealized_pnl_usdt = (cand.entry_price - price) * abs(cand.position_qty)
        else:
            cand.unrealized_pnl_usdt = Decimal("0.0")

        # Update solvency ledger unrealized PnL
        total_upnl = sum((c.unrealized_pnl_usdt for c in self.candidates.values()), Decimal("0.0"))
        self.ledger.unrealized_pnl = total_upnl

        # Daily risk remains active even when market-quality evidence is unavailable.
        if self.intra_day_loss_usdt >= self.config.intra_day_loss_ceiling_usdt:
            logger.error(
                "Interlock tripped: Intra-day loss %s USDT >= ceiling 3.00 USDT",
                self.intra_day_loss_usdt,
            )
            self.state = SelfDrivingState.CIRCUIT_FLATTENED
            self._flatten_all_positions(now_timestamp, reason="Intra-day loss ceiling breached")
            self.interlock_blocks_count += 1
            return None

        # Missing or malformed measurements must never become synthetic clean readings.
        try:
            measured_hsr = float(hsr) if hsr is not None else None
            measured_h_age = float(h_age) if h_age is not None else None
            evidence_valid = (
                measured_hsr is not None
                and measured_h_age is not None
                and math.isfinite(measured_hsr)
                and math.isfinite(measured_h_age)
                and measured_hsr >= 0.0
                and measured_h_age >= 0.0
            )
        except TypeError, ValueError, OverflowError:
            measured_hsr = None
            measured_h_age = None
            evidence_valid = False
        if not evidence_valid:
            logger.warning("Order blocked: measured Hawkes and heartbeat evidence is required")
            self.interlock_blocks_count += 1
            self._append_event(
                "MICROSTRUCTURE_EVIDENCE_MISSING_BLOCK",
                {
                    "symbol": symbol,
                    "hawkes_present": hsr is not None,
                    "heartbeat_present": h_age is not None,
                },
            )
            return None

        assert measured_hsr is not None and measured_h_age is not None

        # 1. Heartbeat latency interlock (<= 500 ms)
        if measured_h_age > self.config.max_heartbeat_latency_ms:
            logger.warning("Interlock tripped: Heartbeat age %.1f ms > 500 ms", measured_h_age)
            self.interlock_blocks_count += 1
            self._append_event(
                "HEARTBEAT_STALE_BLOCK", {"symbol": symbol, "latency_ms": str(measured_h_age)}
            )
            return None

        # 2. Hawkes risk interlock (rho < 1.0)
        if measured_hsr >= self.config.max_hawkes_spectral_radius:
            logger.warning(
                "Interlock tripped: Hawkes spectral radius %.3f >= 1.0",
                measured_hsr,
            )
            self.state = SelfDrivingState.HAWKES_THROTTLED
            self.interlock_blocks_count += 1
            self._append_event(
                "HAWKES_RUNAWAY_THROTTLE",
                {"symbol": symbol, "hawkes": str(measured_hsr)},
            )
            return None
        if self.state == SelfDrivingState.HAWKES_THROTTLED:
            self.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE

        # If signal is neutral or confidence insufficient, no action needed
        if ensemble_signal not in ("LONG", "SHORT", "BUY", "SELL") or signal_confidence < 0.60:
            return None

        side = OrderSide.BUY if ensemble_signal in ("LONG", "BUY") else OrderSide.SELL

        # 6. Sizing and quantization with Binance MIN_NOTIONAL step-up compliance
        quantized_price, quantized_qty, actual_notional = self._calculate_child_order_qty(
            symbol, price
        )
        spec = self.gateway.symbol_specs.get(symbol.upper(), {})
        min_notional = spec.get("min_notional", Decimal("5.00"))

        if quantized_qty <= Decimal("0") or actual_notional < min_notional:
            logger.warning(
                "Order rejected: Rounded notional %s < min notional %s USDT",
                actual_notional,
                min_notional,
            )
            self.interlock_blocks_count += 1
            self._append_event(
                "MIN_NOTIONAL_INCOMPATIBLE_BLOCK",
                {"symbol": symbol, "price": str(price), "notional": str(actual_notional)},
            )
            return None

        # 4. Aggregate exposure check (<= 25.00 USDT)
        current_aggregate_exposure = sum(
            c.allocated_exposure_usdt for c in self.candidates.values()
        )
        if current_aggregate_exposure + actual_notional > self.config.max_aggregate_exposure_usdt:
            logger.warning(
                "Interlock tripped: Exposure %s + slice > max %s USDT",
                current_aggregate_exposure,
                self.config.max_aggregate_exposure_usdt,
            )
            self.interlock_blocks_count += 1
            self._append_event(
                "AGGREGATE_EXPOSURE_CAP_BLOCK",
                {"symbol": symbol, "exposure": str(current_aggregate_exposure + actual_notional)},
            )
            return None

        # 5. Cash reserve floor check (>= 75.0%)
        projected_cash = self.ledger.cash - actual_notional
        total_equity = self.ledger.starting_equity + self.ledger.realized_pnl
        cash_reserve_pct = (
            (projected_cash / total_equity) * Decimal("100")
            if total_equity > Decimal("0")
            else Decimal("0")
        )
        if cash_reserve_pct < self.config.min_cash_reserve_pct:
            logger.warning(
                "Interlock tripped: Cash reserve %.2f%% < floor 75.0%%",
                float(cash_reserve_pct),
            )
            self.interlock_blocks_count += 1
            self._append_event(
                "CASH_RESERVE_FLOOR_BLOCK",
                {"symbol": symbol, "cash_reserve_pct": str(cash_reserve_pct)},
            )
            return None

        # 7. Create and execute order
        cid = generate_client_order_id(symbol, now_timestamp)
        order_id = f"ord-p310-{symbol.lower()[:3]}-{len(self.orders) + 1:04d}"
        order = SelfDrivingOrder(
            order_id=order_id,
            symbol=symbol.upper(),
            side=side,
            order_type="LIMIT",
            price=quantized_price,
            quantity=quantized_qty,
            notional_usdt=actual_notional,
            status=OrderStatus.PENDING,
            timestamp_ms=now_timestamp,
            client_order_id=cid,
            is_maker=True,
        )

        # Execute fill (via gateway or internal matching)
        self._execute_fill(order, quantized_price, now_timestamp)
        self.orders.append(order)
        self._record_order_in_db(order)
        return order

    def _execute_fill(
        self,
        order: SelfDrivingOrder,
        fill_price: Decimal,
        now_ms: int,
    ) -> None:
        """Executes fill and reconciles centralized double-entry solvency ledger."""
        if not self.gateway.offline_mode:
            raise RuntimeError(
                "Live orders require exchange-confirmed execution; simulated fills disabled"
            )
        cand = self.candidates[order.symbol]
        fee_rate = Decimal("0.0002") if order.is_maker else Decimal("0.0004")
        fee_cost = (order.notional_usdt * fee_rate).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )

        prev_qty = cand.position_qty
        new_qty = (
            prev_qty + order.quantity if order.side == OrderSide.BUY else prev_qty - order.quantity
        )

        realized_pnl = Decimal("0.0")

        # Position closing or opening
        if prev_qty > Decimal("0") and order.side == OrderSide.SELL:
            # Closing long
            close_qty = min(prev_qty, order.quantity)
            realized_pnl = (fill_price - cand.entry_price) * close_qty
            cand.realized_pnl_usdt += realized_pnl
            if realized_pnl < Decimal("0"):
                self.intra_day_loss_usdt += abs(realized_pnl)
            # Trigger trade autopsy
            self._trigger_autopsy(
                cand=cand,
                exit_price=fill_price,
                fill_qty=close_qty,
                now_ms=now_ms,
                cause=AutopsyAttributionCause.ORGANIC_ALPHA
                if realized_pnl >= 0
                else AutopsyAttributionCause.SPREAD_CROSS,
            )

        elif prev_qty < Decimal("0") and order.side == OrderSide.BUY:
            # Closing short
            close_qty = min(abs(prev_qty), order.quantity)
            realized_pnl = (cand.entry_price - fill_price) * close_qty
            cand.realized_pnl_usdt += realized_pnl
            if realized_pnl < Decimal("0"):
                self.intra_day_loss_usdt += abs(realized_pnl)
            # Trigger trade autopsy
            self._trigger_autopsy(
                cand=cand,
                exit_price=fill_price,
                fill_qty=close_qty,
                now_ms=now_ms,
                cause=AutopsyAttributionCause.ORGANIC_ALPHA
                if realized_pnl >= 0
                else AutopsyAttributionCause.SPREAD_CROSS,
            )
        else:
            # Opening new position
            cand.entry_price = fill_price
            cand.entry_time_ms = now_ms
            cand.current_price = fill_price

        cand.position_qty = new_qty
        if new_qty == Decimal("0.0"):
            cand.unrealized_pnl_usdt = Decimal("0.0")
            cand.allocated_exposure_usdt = Decimal("0.0")
            cand.entry_price = Decimal("0.0")
            cand.entry_time_ms = 0
            cand.entry_bar_index = 0
            cand.stop_loss = None
            cand.take_profit = None
        else:
            cand.allocated_exposure_usdt = abs(new_qty) * fill_price
        cand.total_fees_usdt += fee_cost
        cand.trades_count += 1

        order.status = OrderStatus.FILLED
        order.fee_usdt = fee_cost
        order.realized_pnl_usdt = realized_pnl

        # Reconcile CentralizedSolvencyLedger:
        self.ledger.record_fill(
            symbol=order.symbol,
            side=order.side.value,
            qty=order.quantity,
            price=fill_price,
            fee=fee_cost,
            realized_pnl=realized_pnl,
        )

        total_upnl = sum((c.unrealized_pnl_usdt for c in self.candidates.values()), Decimal("0.0"))
        self.ledger.unrealized_pnl = total_upnl

        self._record_solvency_snapshot(now_ms)
        self._append_event(
            "FILL",
            {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "price": str(fill_price),
                "qty": str(order.quantity),
                "fee": str(fee_cost),
                "realized_pnl": str(realized_pnl),
            },
        )

    def _trigger_autopsy(
        self,
        cand: CandidateState,
        exit_price: Decimal,
        fill_qty: Decimal,
        now_ms: int,
        cause: AutopsyAttributionCause,
        *,
        optimal_price: float | None = None,
        hawkes_intensity: float | None = None,
        adverse_delta_pct: float | None = None,
        fvg_boundary_price: float | None = None,
        lowest_price_during_trade: float | None = None,
        highest_price_during_trade: float | None = None,
    ) -> None:
        """Record autopsy only when its market-quality inputs were actually observed."""
        generic_inputs = (optimal_price, hawkes_intensity, adverse_delta_pct)
        if not all(_finite_evidence_value(value) for value in generic_inputs):
            self._append_event(
                "TRADE_AUTOPSY_SKIPPED_MISSING_EVIDENCE",
                {
                    "symbol": cand.symbol,
                    "trade_id": f"trd-{cand.symbol.lower()[:3]}-{now_ms}",
                    "missing": [
                        name
                        for name, value in (
                            ("optimal_price", optimal_price),
                            ("hawkes_intensity", hawkes_intensity),
                            ("adverse_delta_pct", adverse_delta_pct),
                        )
                        if value is None
                    ],
                },
            )
            return
        assert optimal_price is not None
        assert hawkes_intensity is not None
        assert adverse_delta_pct is not None
        if optimal_price <= 0.0 or hawkes_intensity < 0.0 or adverse_delta_pct < 0.0:
            self._append_event(
                "TRADE_AUTOPSY_SKIPPED_INVALID_EVIDENCE",
                {"symbol": cand.symbol, "timestamp_ms": now_ms},
            )
            return

        trade_id = f"trd-{cand.symbol.lower()[:3]}-{now_ms}"
        hold_duration_ms = max(0, now_ms - cand.entry_time_ms)
        hold_duration_bars = max(1, hold_duration_ms // (15 * 60 * 1000))

        autopsy = self.autopsy_engine.deconstruct_trade(
            trade_id=trade_id,
            candidate_id=f"cand-{cand.symbol.lower()}-scalper",
            symbol=cand.symbol,
            side="BUY" if cand.position_qty >= 0 else "SELL",
            entry_price=float(cand.entry_price),
            exit_price=float(exit_price),
            fill_qty=float(fill_qty),
            optimal_price=optimal_price,
            hawkes_intensity=hawkes_intensity,
            adverse_delta_pct=adverse_delta_pct,
            timestamp_ms=now_ms,
        )

        # Store autopsy
        self.autopsies[cand.symbol].append(autopsy)

        # Evaluate candidate health tier
        eval_result = self.self_learning_daemon.evaluate_candidate(
            candidate_id=f"cand-{cand.symbol.lower()}-scalper",
            symbol=cand.symbol,
            autopsies=self.autopsies[cand.symbol],
        )
        cand.health_tier = eval_result.tier
        self.health_evaluations[cand.symbol] = eval_result

        # Persist to SQLite
        self._record_autopsy_in_db(autopsy, hold_duration_bars, hold_duration_ms)
        self._record_health_in_db(eval_result, now_ms)
        self._append_event(
            "TRADE_AUTOPSY",
            {
                "trade_id": trade_id,
                "symbol": cand.symbol,
                "net_pnl": autopsy.net_pnl_usdt,
                "cause": autopsy.cause.value,
                "tier": eval_result.tier.value,
            },
        )

        ict_inputs = (
            optimal_price,
            fvg_boundary_price,
            lowest_price_during_trade,
            highest_price_during_trade,
        )
        if not all(_finite_evidence_value(value) for value in ict_inputs):
            self._append_event(
                "ICT_AUTOPSY_SKIPPED_MISSING_EVIDENCE",
                {"symbol": cand.symbol, "trade_id": trade_id},
            )
            return
        assert fvg_boundary_price is not None
        assert lowest_price_during_trade is not None
        assert highest_price_during_trade is not None
        if (
            fvg_boundary_price <= 0.0
            or lowest_price_during_trade <= 0.0
            or highest_price_during_trade <= 0.0
            or lowest_price_during_trade > highest_price_during_trade
        ):
            self._append_event(
                "ICT_AUTOPSY_SKIPPED_INVALID_EVIDENCE",
                {"symbol": cand.symbol, "trade_id": trade_id},
            )
            return
        # Queue only complete evidence; the drain path no longer synthesizes omitted prices.
        with self._autopsy_lock:
            self._pending_autopsies.append(
                {
                    "trade_id": trade_id,
                    "candidate_id": f"cand-{cand.symbol.lower()}-ict-001",
                    "symbol": cand.symbol,
                    "side": "BUY" if cand.position_qty >= 0 else "SELL",
                    "entry_price": float(cand.entry_price),
                    "exit_price": float(exit_price),
                    "fill_qty": float(fill_qty),
                    "optimal_price": optimal_price,
                    "fvg_boundary_price": fvg_boundary_price,
                    "lowest_price_during_trade": lowest_price_during_trade,
                    "highest_price_during_trade": highest_price_during_trade,
                    "timestamp_ms": now_ms,
                }
            )

    def has_pending_autopsies(self) -> bool:
        """Returns True if pending ICT autopsy records are queued for draining."""
        with self._autopsy_lock:
            return len(self._pending_autopsies) > 0

    def enqueue_ict_autopsy(self, autopsy_data: dict[str, Any] | IctAutopsyMetrics) -> None:
        """Enqueues an ICT autopsy record in non-blocking fashion (< 0.05ms)."""
        with self._autopsy_lock:
            self._pending_autopsies.append(autopsy_data)

    def drain_pending_autopsies(self, db_path: Path | None = None) -> list[IctAutopsyMetrics]:
        """Asynchronously drains pending autopsies into SQLite tables ict_trade_autopsies

        and ict_candidate_registry and appends JSONL event logs.
        """
        with self._autopsy_lock:
            if not self._pending_autopsies:
                return []
            raw_items = list(self._pending_autopsies)
            self._pending_autopsies.clear()

        target_db = db_path or self.db_path
        drained_metrics: list[IctAutopsyMetrics] = []
        rows_to_insert = []
        events_to_append = []

        for item in raw_items:
            if isinstance(item, IctAutopsyMetrics):
                metrics = item
            else:
                required_evidence = (
                    "trade_id",
                    "symbol",
                    "side",
                    "entry_price",
                    "exit_price",
                    "fill_qty",
                    "optimal_price",
                    "fvg_boundary_price",
                    "lowest_price_during_trade",
                    "highest_price_during_trade",
                    "timestamp_ms",
                )
                missing_evidence = [
                    name for name in required_evidence if name not in item or item[name] is None
                ]
                if missing_evidence:
                    self._append_event(
                        "ICT_AUTOPSY_REJECTED_INCOMPLETE_EVIDENCE",
                        {
                            "trade_id": item.get("trade_id"),
                            "symbol": item.get("symbol"),
                            "missing": missing_evidence,
                        },
                    )
                    continue
                try:
                    numeric_evidence = {
                        name: float(item[name])
                        for name in (
                            "entry_price",
                            "exit_price",
                            "fill_qty",
                            "optimal_price",
                            "fvg_boundary_price",
                            "lowest_price_during_trade",
                            "highest_price_during_trade",
                        )
                    }
                    timestamp_ms = int(item["timestamp_ms"])
                    evidence_valid = (
                        all(
                            math.isfinite(value) and value > 0.0
                            for value in numeric_evidence.values()
                        )
                        and timestamp_ms > 0
                    )
                except TypeError, ValueError, OverflowError:
                    evidence_valid = False
                    numeric_evidence = {}
                    timestamp_ms = 0
                if (
                    not evidence_valid
                    or not isinstance(item["side"], str)
                    or item["side"].upper() not in {"BUY", "SELL"}
                    or numeric_evidence["lowest_price_during_trade"]
                    > numeric_evidence["highest_price_during_trade"]
                ):
                    self._append_event(
                        "ICT_AUTOPSY_REJECTED_INVALID_EVIDENCE",
                        {"trade_id": item["trade_id"], "symbol": item["symbol"]},
                    )
                    continue
                metrics = self.ict_autopsy_calculator.compute_metrics(
                    trade_id=item["trade_id"],
                    candidate_id=item.get("candidate_id", f"cand-{item['symbol'].lower()}-ict-001"),
                    symbol=item["symbol"],
                    side=item["side"],
                    entry_price=numeric_evidence["entry_price"],
                    exit_price=numeric_evidence["exit_price"],
                    fill_qty=numeric_evidence["fill_qty"],
                    optimal_price=numeric_evidence["optimal_price"],
                    fvg_boundary_price=numeric_evidence["fvg_boundary_price"],
                    lowest_price_during_trade=numeric_evidence["lowest_price_during_trade"],
                    highest_price_during_trade=numeric_evidence["highest_price_during_trade"],
                    timestamp_ms=timestamp_ms,
                )
            drained_metrics.append(metrics)
            self.ict_autopsies.setdefault(metrics.symbol, []).append(metrics)

            rows_to_insert.append(
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
                )
            )

            events_to_append.append(
                {
                    "timestamp_ms": metrics.timestamp_ms,
                    "event_type": "ICT_TRADE_AUTOPSY",
                    "trade_id": metrics.trade_id,
                    "symbol": metrics.symbol,
                    "bracket_efficiency": metrics.bracket_efficiency,
                    "net_pnl": metrics.net_pnl_usdt,
                    "cause": str(metrics.cause),
                }
            )

        # Persist to SQLite
        try:
            with self._db_lock:
                conn = self._get_telemetry_db_conn(target_db)
                cur = conn.cursor()
                cur.executemany(
                    """
                    INSERT OR REPLACE INTO ict_trade_autopsies (
                        trade_id, candidate_id, symbol, side, entry_price, exit_price,
                        fill_qty, entry_timing_error_bps, fvg_slippage_bps, mae_bps, mfe_bps,
                        bracket_efficiency, realized_edge_bps, gross_pnl_usdt, fee_cost_usdt,
                        net_pnl_usdt, cause, timestamp_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )
                # Update ict_candidate_registry
                for m in drained_metrics:
                    genome = DEFAULT_ICT_GENOMES.get(m.symbol)
                    ote_lower = float(genome.ote_lower) if genome else 0.62
                    ote_upper = float(genome.ote_upper) if genome else 0.79
                    stdv_tp1 = float(genome.stdv_tp1) if genome else 2.0
                    stdv_tp2 = float(genome.stdv_tp2) if genome else 4.0
                    lookback_htf = genome.lookback_htf if genome else 100
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO ict_candidate_registry (
                            candidate_id, symbol, generation, parent_candidate_id,
                            ote_lower, ote_upper, stdv_tp1, stdv_tp2, lookback_htf,
                            health_tier, is_active, updated_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            m.candidate_id,
                            m.symbol,
                            1,
                            None,
                            ote_lower,
                            ote_upper,
                            stdv_tp1,
                            stdv_tp2,
                            lookback_htf,
                            "HEALTHY" if m.net_pnl_usdt >= 0 else "DEGRADED",
                            1,
                            m.timestamp_ms,
                        ),
                    )
                conn.commit()
        except Exception as db_err:
            logger.warning("Error inserting ict_trade_autopsies (non-fatal): %s", db_err)
            with self._autopsy_lock:
                self._pending_autopsies.extendleft(reversed(raw_items))

        # Append to JSONL events log
        try:
            with open(self.events_path, "a", encoding="utf-8") as f:
                for ev in events_to_append:
                    f.write(json.dumps(ev) + "\n")
        except Exception as ev_err:
            logger.debug("Error writing JSONL event: %s", ev_err)

        return drained_metrics

    def evaluate_and_dispatch_scalper(
        self,
        symbol: str,
        bar: Candle,
        history: Sequence[Candle],
        btc_1h_candles: Sequence[Candle],
        btc_4h_candles: Sequence[Candle] | None = None,
        now_ms: int | None = None,
    ) -> SelfDrivingOrder | None:
        """Evaluates 15m candle close through MacroTrendFilter & MacroLiquidityDipScalper.

        If entry conditions are satisfied, dispatches Maker Limit Order.
        If existing position is active, checks Stop Loss, Take Profit, or Time Decay Stop.
        """
        ts = now_ms if now_ms is not None else bar.timestamp_ms
        cand = self.candidates[symbol.upper()]

        # 1. Manage active position (SL, TP, Time Decay Stop)
        if cand.position_qty != Decimal("0"):
            hold_bars = max(1, (ts - cand.entry_time_ms) // (15 * 60 * 1000))
            is_long = cand.position_qty > Decimal("0")

            # Stop loss hit
            sl_hit = (
                (bar.low <= cand.stop_loss if is_long else bar.high >= cand.stop_loss)
                if cand.stop_loss is not None and cand.stop_loss > Decimal("0")
                else False
            )
            if sl_hit:
                assert cand.stop_loss is not None
                logger.info("Stop Loss triggered on %s at %s", symbol, cand.stop_loss)
                return self._exit_position(cand, cand.stop_loss, ts, reason="STOP_LOSS")

            # Take profit hit
            tp_hit = (
                (bar.high >= cand.take_profit if is_long else bar.low <= cand.take_profit)
                if cand.take_profit is not None and cand.take_profit > Decimal("0")
                else False
            )
            if tp_hit:
                assert cand.take_profit is not None
                logger.info("Take Profit triggered on %s at %s", symbol, cand.take_profit)
                return self._exit_position(cand, cand.take_profit, ts, reason="TAKE_PROFIT")

            # Time decay momentum stop (8 bars = 120 mins)
            if hold_bars >= 8:
                logger.info("Time decay stop triggered on %s at %s", symbol, bar.close)
                return self._exit_position(cand, bar.close, ts, reason="TIME_DECAY_STOP")

        # 2. Evaluate new dip entry if flat
        if cand.position_qty == Decimal("0"):
            macro_regime = self.trend_filter.evaluate_regime(
                list(btc_1h_candles),
                list(btc_4h_candles) if btc_4h_candles else None,
            )
            signal: ScalperSignal | None = self.scalper.evaluate_15m_bar(
                symbol=symbol,
                bar=bar,
                history=list(history),
                macro_trend_allowed=macro_regime,
            )
            if signal:
                cand.stop_loss = signal.stop_loss
                cand.take_profit = signal.take_profit
                order = self.process_microstructure_tick(
                    symbol=symbol,
                    price=signal.sweep_price,
                    ensemble_signal=signal.side,
                    ts_ms=ts,
                )
                if order:
                    order.stop_loss = signal.stop_loss
                    order.take_profit = signal.take_profit
                    order.max_hold_bars = signal.max_hold_bars
                return order

        return None

    def dispatch_ict_intention(
        self,
        setup: TwinsSetupState,
        now_ms: int | None = None,
    ) -> SelfDrivingOrder | None:
        """Dispatches a validated ICT Twins Reversal setup through micro-capital risk interlocks."""
        if not setup.step_6_ready or setup.side is None:
            return None

        # Precondition: Engine must not be circuit-flattened or manually halted
        if self.state in (SelfDrivingState.CIRCUIT_FLATTENED, SelfDrivingState.KILL_SWITCH_HALTED):
            return None

        symbol = setup.symbol.upper()
        cand = self.candidates.get(symbol)
        if cand is None:
            return None

        # Precondition: Candidate must be flat
        if cand.position_qty != Decimal("0"):
            return None

        now_timestamp = now_ms if now_ms is not None else int(time.time() * 1000)

        # Reference entry price from setup
        entry_price = setup.m1_cisd_price or setup.ote_705 or cand.current_price
        if entry_price <= Decimal("0"):
            return None

        # Intra-day loss ceiling interlock (<= 3.00 USDT)
        if self.intra_day_loss_usdt >= self.config.intra_day_loss_ceiling_usdt:
            logger.error(
                "Interlock tripped: Intra-day loss %s USDT >= ceiling 3.00 USDT",
                self.intra_day_loss_usdt,
            )
            self.state = SelfDrivingState.CIRCUIT_FLATTENED
            self._flatten_all_positions(now_timestamp, reason="Intra-day loss ceiling breached")
            self.interlock_blocks_count += 1
            return None

        # Sizing with MIN_NOTIONAL and step_size rounding
        quantized_price, quantized_qty, actual_notional = self._calculate_child_order_qty(
            symbol, entry_price
        )
        spec = self.gateway.symbol_specs.get(symbol, {})
        min_notional = spec.get("min_notional", Decimal("5.00"))
        if quantized_qty <= Decimal("0") or actual_notional < min_notional:
            logger.warning(
                "ICT Order rejected: Rounded notional %s < min notional %s USDT",
                actual_notional,
                min_notional,
            )
            self.interlock_blocks_count += 1
            return None

        # A strict cap has no lot-size tolerance.
        max_allowed_child = self.config.max_micro_order_notional_usdt
        if actual_notional > max_allowed_child:
            logger.warning(
                "ICT Order rejected: Notional %s > max allowed %s USDT",
                actual_notional,
                max_allowed_child,
            )
            self.interlock_blocks_count += 1
            return None

        # Aggregate portfolio exposure check (<= 25.00 USDT)
        current_aggregate_exposure = sum(
            c.allocated_exposure_usdt for c in self.candidates.values()
        )
        if current_aggregate_exposure + actual_notional > self.config.max_aggregate_exposure_usdt:
            logger.warning(
                "Interlock tripped: Exposure %s + slice > max %s USDT",
                current_aggregate_exposure,
                self.config.max_aggregate_exposure_usdt,
            )
            self.interlock_blocks_count += 1
            self._append_event(
                "AGGREGATE_EXPOSURE_CAP_BLOCK",
                {"symbol": symbol, "exposure": str(current_aggregate_exposure + actual_notional)},
            )
            return None

        # Cash reserve floor check (>= 75.0%)
        projected_cash = self.ledger.cash - actual_notional
        total_equity = self.ledger.starting_equity + self.ledger.realized_pnl
        cash_reserve_pct = (
            (projected_cash / total_equity) * Decimal("100")
            if total_equity > Decimal("0")
            else Decimal("0")
        )
        if cash_reserve_pct < self.config.min_cash_reserve_pct:
            logger.warning(
                "Interlock tripped: Cash reserve %.2f%% < floor 75.0%%",
                float(cash_reserve_pct),
            )
            self.interlock_blocks_count += 1
            self._append_event(
                "CASH_RESERVE_FLOOR_BLOCK",
                {"symbol": symbol, "cash_reserve_pct": str(cash_reserve_pct)},
            )
            return None

        # Store protective brackets on candidate state
        cand.stop_loss = setup.stop_loss if setup.stop_loss is not None else Decimal("0.0")
        cand.take_profit = (
            setup.take_profit_partial
            if setup.take_profit_partial is not None
            else (setup.take_profit_final or Decimal("0.0"))
        )

        cid = generate_p317_ict_client_order_id(symbol, now_timestamp, role="ict")
        order_id = f"ord-p317-{symbol.lower()[:3]}-{len(self.orders) + 1:04d}"
        order = SelfDrivingOrder(
            order_id=order_id,
            symbol=symbol,
            side=OrderSide.BUY if setup.side == "BUY" else OrderSide.SELL,
            order_type="LIMIT",
            price=quantized_price,
            quantity=quantized_qty,
            notional_usdt=actual_notional,
            status=OrderStatus.PENDING,
            timestamp_ms=now_timestamp,
            client_order_id=cid,
            is_maker=True,
            stop_loss=setup.stop_loss,
            take_profit=cand.take_profit,
            max_hold_bars=12,
        )

        self._execute_fill(order, quantized_price, now_timestamp)
        self.orders.append(order)
        self._record_order_in_db(order)
        return order

    def _exit_position(
        self,
        cand: CandidateState,
        exit_price: Decimal | None,
        ts_ms: int,
        reason: str,
    ) -> SelfDrivingOrder:
        """Exits active candidate position."""
        spec = self.gateway.symbol_specs.get(cand.symbol, {})
        tick_size = spec.get("tick_size", Decimal("0.01"))

        effective_price = exit_price if exit_price is not None else cand.current_price
        quantized_price = self._round_tick_size(effective_price, tick_size)
        quantized_qty = abs(cand.position_qty)
        if quantized_qty * quantized_price > self.config.max_micro_order_notional_usdt:
            quantized_qty = self._round_step_size(
                self.config.max_micro_order_notional_usdt / quantized_price,
                spec["step_size"],
            )
        if quantized_qty <= 0:
            raise ValueError("Exit lot is incompatible with the strict child cap")
        notional = quantized_qty * quantized_price

        reason_upper = reason.upper()
        if reason_upper in ("TAKE_PROFIT", "TP"):
            role = "tp"
        elif reason_upper in ("STOP_LOSS", "SL"):
            role = "sl"
        else:
            role = "cl"

        cid = generate_p317_ict_client_order_id(cand.symbol, ts_ms=ts_ms, role=role)
        order_id = f"ord-p317-{cand.symbol.lower()[:3]}-{len(self.orders) + 1:04d}"
        exit_side = OrderSide.BUY if cand.position_qty < Decimal("0") else OrderSide.SELL

        order = SelfDrivingOrder(
            order_id=order_id,
            symbol=cand.symbol,
            side=exit_side,
            order_type="LIMIT",
            price=quantized_price,
            quantity=quantized_qty,
            notional_usdt=notional,
            status=OrderStatus.PENDING,
            timestamp_ms=ts_ms,
            client_order_id=cid,
            is_maker=role != "sl" and reason_upper not in ("STOP_LOSS", "EMERGENCY", "FLATTEN"),
            stop_loss=None,
            take_profit=None,
        )
        self._execute_fill(order, quantized_price, ts_ms)
        self.orders.append(order)
        self._record_order_in_db(order)
        return order

    def _flatten_all_positions(
        self,
        now_ms: int | str | None = None,
        reason: str = "Circuit flattened",
    ) -> None:
        """Emergency fail-closed auto-flattening of all open candidate positions."""
        if isinstance(now_ms, str):
            reason = now_ms
            ts = int(time.time() * 1000)
        elif now_ms is None:
            ts = int(time.time() * 1000)
        else:
            ts = now_ms

        if not self.gateway.offline_mode:
            raise RuntimeError("Live flatten requires confirmed reduce-only exchange execution")
        logger.warning("Flattening all positions: %s", reason)
        for cand in self.candidates.values():
            while cand.position_qty != 0:
                if cand.current_price <= 0:
                    raise ValueError("Cannot flatten without a valid current price")
                self._exit_position(cand, cand.current_price, ts, reason="FLATTEN")
        self._append_event("ALL_POSITIONS_FLATTENED", {"reason": reason})

    # =========================================================================
    # Database Persistence
    # =========================================================================

    def _record_order_in_db(self, order: SelfDrivingOrder) -> None:
        """Persists order record to SQLite."""
        with self._db_lock:
            conn = self._get_telemetry_db_conn(self.db_path)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO orders (
                    order_id, client_order_id, symbol, side, order_type, price,
                    quantity, notional_usdt, status, fee_usdt, realized_pnl_usdt, timestamp_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.client_order_id,
                    order.symbol,
                    order.side.value,
                    order.order_type,
                    float(order.price),
                    float(order.quantity),
                    float(order.notional_usdt),
                    order.status.value,
                    float(order.fee_usdt),
                    float(order.realized_pnl_usdt),
                    order.timestamp_ms,
                ),
            )
            conn.commit()

    def _record_autopsy_in_db(
        self,
        autopsy: TradeAutopsyRecord,
        hold_bars: int,
        hold_ms: int,
    ) -> None:
        """Persists trade autopsy record to SQLite."""
        with self._db_lock:
            conn = self._get_telemetry_db_conn(self.db_path)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO trade_autopsies (
                    trade_id, candidate_id, symbol, side, entry_price, exit_price,
                    fill_qty, entry_timing_error_bps, hawkes_slip_drag_bps, adverse_selection_bps,
                    realized_edge_bps, gross_pnl_usdt, fee_cost_usdt, net_pnl_usdt,
                    hold_duration_bars, hold_duration_ms, cause, timestamp_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    autopsy.trade_id,
                    autopsy.candidate_id,
                    autopsy.symbol,
                    autopsy.side,
                    autopsy.entry_price,
                    autopsy.exit_price,
                    autopsy.fill_qty,
                    autopsy.entry_timing_error_bps,
                    autopsy.hawkes_slip_drag_bps,
                    autopsy.adverse_selection_bps,
                    autopsy.realized_edge_bps,
                    autopsy.gross_pnl_usdt,
                    autopsy.fee_cost_usdt,
                    autopsy.net_pnl_usdt,
                    hold_bars,
                    hold_ms,
                    autopsy.cause.value,
                    autopsy.timestamp_ms,
                ),
            )
            conn.commit()

    def _record_health_in_db(self, eval_result: CandidateHealthEvaluation, now_ms: int) -> None:
        """Persists candidate health evaluation to SQLite."""
        with self._db_lock:
            conn = self._get_telemetry_db_conn(self.db_path)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO candidate_health (
                    candidate_id, symbol, tier, rolling_sharpe, win_rate_pct,
                    max_drawdown_pct, hawkes_resilience_score, total_trades,
                    consecutive_losses, needs_mutation, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval_result.candidate_id,
                    eval_result.symbol,
                    eval_result.tier.value,
                    eval_result.rolling_sharpe,
                    eval_result.win_rate_pct,
                    eval_result.max_drawdown_pct,
                    eval_result.hawkes_resilience_score,
                    eval_result.total_trades,
                    eval_result.consecutive_losses,
                    1 if eval_result.needs_mutation else 0,
                    now_ms,
                ),
            )
            conn.commit()

    def _record_solvency_snapshot(self, now_ms: int) -> None:
        """Persists double-entry solvency snapshot to SQLite."""
        with self._db_lock:
            conn = self._get_telemetry_db_conn(self.db_path)
            cur = conn.cursor()
            snap = self.ledger.get_snapshot()
            cur.execute(
                """
                INSERT INTO solvency_snapshots (
                    timestamp_ms, cash, allocated_margin, unrealized_pnl,
                    realized_pnl, starting_equity, total_equity, drift
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_ms,
                    float(snap.cash),
                    float(snap.allocated_margin),
                    float(snap.unrealized_pnl),
                    float(snap.realized_pnl),
                    float(snap.starting_equity),
                    float(snap.total_equity),
                    float(snap.drift),
                ),
            )
            conn.commit()

    # =========================================================================
    # Artifact Export & Merkle DAG Lineage
    # =========================================================================

    def export_artifacts(self, target_dir: Path | None = None) -> dict[str, Any]:
        """Exports the 5 persistent cryptographic Merkle DAG research artifacts.

        1. canary-production-telemetry.sqlite3
        2. canary-production-events.jsonl
        3. canary-production-report.json
        4. canary-production-execution.json
        5. production-summary.json
        """
        out_dir = target_dir or self.storage_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        sqlite_path = out_dir / "canary-production-telemetry.sqlite3"
        events_path = out_dir / "canary-production-events.jsonl"
        report_path = out_dir / "canary-production-report.json"
        exec_path = out_dir / "canary-production-execution.json"
        summary_path = out_dir / "production-summary.json"

        # Ensure sqlite and events files exist
        if sqlite_path != self.db_path and self.db_path.exists():
            shutil.copy2(self.db_path, sqlite_path)
        elif not sqlite_path.exists():
            self._init_sqlite_db()

        if events_path != self.events_path and self.events_path.exists():
            shutil.copy2(self.events_path, events_path)
        elif not events_path.exists():
            self._append_event("INIT", {"message": "Phase 310 trading engine initialized"})

        now_ms = int(time.time() * 1000)
        snap = self.ledger.get_snapshot()
        solvency_dict = dataclasses.asdict(snap)
        execution_mode = (
            "OFFLINE_SIMULATION" if self.gateway.offline_mode else "LIVE_SUBMISSION_UNIMPLEMENTED"
        )
        execution_authority = False

        # 3. canary-production-report.json
        report_data = {
            "phase": "phase_310",
            "timestamp_ms": now_ms,
            "execution_mode": execution_mode,
            "execution_authority": execution_authority,
            "artifact_integrity_only": True,
            "engine_state": self.state.value,
            "solvency": solvency_dict,
            "micro_capital_confinement": {
                "scope": "LEGACY_SIMULATION_ONLY_NOT_APPROVED_LIVE_POLICY",
                "max_micro_order_notional_usdt": float(self.config.max_micro_order_notional_usdt),
                "max_aggregate_exposure_usdt": float(self.config.max_aggregate_exposure_usdt),
                "min_cash_reserve_pct": float(self.config.min_cash_reserve_pct),
                "intra_day_loss_ceiling_usdt": float(self.config.intra_day_loss_ceiling_usdt),
            },
            "candidates": {
                sym: {
                    "current_price": float(c.current_price),
                    "position_qty": float(c.position_qty),
                    "allocated_exposure_usdt": float(c.allocated_exposure_usdt),
                    "unrealized_pnl_usdt": float(c.unrealized_pnl_usdt),
                    "realized_pnl_usdt": float(c.realized_pnl_usdt),
                    "trades_count": c.trades_count,
                    "health_tier": c.health_tier.value,
                }
                for sym, c in self.candidates.items()
            },
            "macro_btc": {
                "current_price": (
                    float(self.candidates["BTCUSDT"].current_price)
                    if "BTCUSDT" in self.candidates
                    else 0.0
                ),
                "ema50_1h": getattr(self, "latest_btc_ema50", 0.0),
                "ema200_1h": getattr(self, "latest_btc_ema200", 0.0),
                "regime": (
                    "BULLISH ALIGNED"
                    if getattr(self, "latest_btc_ema50", 0.0)
                    > getattr(self, "latest_btc_ema200", 0.0)
                    else "BEARISH / SIDEWAYS"
                ),
            },
            "total_orders": len(self.orders),
            "interlock_blocks_count": self.interlock_blocks_count,
            "intra_day_loss_usdt": float(self.intra_day_loss_usdt),
        }
        report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

        # 4. canary-production-execution.json
        execution_data = {
            "phase": "phase_310",
            "timestamp_ms": now_ms,
            "execution_mode": execution_mode,
            "execution_authority": execution_authority,
            "orders": [
                {
                    "order_id": o.order_id,
                    "client_order_id": o.client_order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "order_type": o.order_type,
                    "price": float(o.price),
                    "quantity": float(o.quantity),
                    "notional_usdt": float(o.notional_usdt),
                    "status": o.status.value,
                    "fee_usdt": float(o.fee_usdt),
                    "realized_pnl_usdt": float(o.realized_pnl_usdt),
                    "is_maker": o.is_maker,
                    "timestamp_ms": o.timestamp_ms,
                    "execution_source": "INTERNAL_SIMULATION",
                    "exchange_confirmed": False,
                }
                for o in self.orders
            ],
            "total_internal_simulated_fills": len(self.orders),
            "total_exchange_confirmed_fills": 0,
        }
        exec_path.write_text(json.dumps(execution_data, indent=2), encoding="utf-8")

        # Compute individual artifact SHA-256 hashes
        sq_hash = hashlib.sha256(sqlite_path.read_bytes()).hexdigest()
        ev_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()
        rep_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
        ex_hash = hashlib.sha256(exec_path.read_bytes()).hexdigest()

        drift_str = str(solvency_dict.get("drift", "0.0"))
        upstream_hash = UPSTREAM_PHASE_309_MERKLE_ROOT

        # Merkle DAG derivation
        combined_payload = (
            f"phase_310:{upstream_hash}:{sq_hash}:{ev_hash}:{rep_hash}:{ex_hash}:{drift_str}"
        )
        phase_hash = hashlib.sha256(combined_payload.encode()).hexdigest()
        merkle_root = hashlib.sha256(f"{upstream_hash}:{phase_hash}".encode()).hexdigest()

        # 5. production-summary.json
        summary_data = {
            "phase": "phase_310",
            "verified": False,
            "artifact_integrity_verified": True,
            "status": "RESEARCH_SIMULATION_ONLY",
            "execution_mode": execution_mode,
            "execution_authority": execution_authority,
            "total_exchange_confirmed_fills": 0,
            "timestamp_ms": now_ms,
            "engine_state": self.state.value,
            "total_orders": len(self.orders),
            "total_trades": sum(c.trades_count for c in self.candidates.values()),
            "interlock_blocks_count": self.interlock_blocks_count,
            "intra_day_loss_usdt": float(self.intra_day_loss_usdt),
            "aggregate_exposure_usdt": float(
                sum(c.allocated_exposure_usdt for c in self.candidates.values())
            ),
            "candidates": list(self.candidates.keys()),
            "solvency": solvency_dict,
            "upstream_hash": upstream_hash,
            "phase_hash": phase_hash,
            "merkle_root": merkle_root,
            "artifact_hashes": {
                "sqlite3": sq_hash,
                "events_jsonl": ev_hash,
                "report_json": rep_hash,
                "execution_json": ex_hash,
            },
            "upstream_merkle_dag": {
                "phase_309": upstream_hash,
            },
        }
        summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

        return summary_data


def build_default_self_driving_engine(
    starting_capital_usdt: Decimal = Decimal("100.00"),
    gateway: BinanceFuturesGateway | None = None,
    storage_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> SelfDrivingTradingEngine:
    """Factory creating and initializing a nominal SelfDrivingTradingEngine."""
    dir_path = storage_dir if storage_dir is not None else output_dir
    path_obj = Path(dir_path) if dir_path is not None else None
    engine = SelfDrivingTradingEngine(
        starting_capital_usdt=starting_capital_usdt,
        gateway=gateway,
        storage_dir=path_obj,
    )
    engine.perform_preflight_checks()
    return engine
