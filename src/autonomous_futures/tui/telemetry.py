"""Non-blocking telemetry reader and typed snapshot contracts for live TUI monitoring.

Safely queries paper daemon JSON checkpoints and SQLite ledgers strictly in
read-only mode (?mode=ro) with short busy timeouts, ensuring zero write lock
contention against the active 24/7 paper trading daemon.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Default symbol universe
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")

# Default nominal fallback prices during warmup
DEFAULT_NOMINAL_PRICES: dict[str, Decimal] = {
    "BTCUSDT": Decimal("90000.00"),
    "ETHUSDT": Decimal("2600.00"),
    "SOLUSDT": Decimal("180.00"),
    "DOGEUSDT": Decimal("0.15000"),
}


@dataclass(slots=True, frozen=True)
class DaemonHealthSnapshot:
    status: str
    pid: int | None
    uptime_seconds: float
    started_at_utc: str
    last_heartbeat_utc: str
    heartbeat_age_seconds: float
    symbols_monitored: tuple[str, ...]
    feed_messages_received: int
    feed_throughput_per_sec: float
    feed_reconnects_count: int
    circuit_breaker_status: str
    zero_order_invariants: dict[str, Any]


@dataclass(slots=True, frozen=True)
class MarginAccountSnapshot:
    starting_capital: Decimal
    current_cash: Decimal
    current_equity: Decimal
    realized_pnl: Decimal
    realized_pnl_pct: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal
    margin_utilization_pct: float
    reserve_buffer_pct: float
    peak_equity: Decimal


@dataclass(slots=True, frozen=True)
class MarketRegimeSnapshot:
    symbol: str
    best_bid: Decimal
    best_ask: Decimal
    mid_price: Decimal
    spread_bps: Decimal
    rolling_atr: Decimal
    status: str


@dataclass(slots=True, frozen=True)
class PositionSnapshot:
    symbol: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    pnl_pct: Decimal
    leverage: Decimal
    liquidation_distance_pct: Decimal
    stop_loss_price: Decimal | None
    trailing_stop_price: Decimal | None


@dataclass(slots=True, frozen=True)
class ClosedTradeSnapshot:
    sequence: int
    trade_id: str
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    occurred_at: str
    net_pnl: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    total_fees: Decimal
    exit_reason: str


@dataclass(slots=True, frozen=True)
class SafetyInvariantsSnapshot:
    volatility_cb: str
    spread_cb: str
    orders_submitted: int
    execution_authority: bool
    live_trading_activation: bool
    paper_activation: bool
    promotion_state: str
    zero_private_credentials: bool
    all_invariants_pass: bool


@dataclass(slots=True, frozen=True)
class TuiTelemetrySnapshot:
    timestamp: datetime
    storage_dir: Path
    is_stale: bool
    daemon: DaemonHealthSnapshot
    margin: MarginAccountSnapshot
    regimes: dict[str, MarketRegimeSnapshot]
    positions: dict[str, PositionSnapshot]
    recent_closed_trades: tuple[ClosedTradeSnapshot, ...]
    safety: SafetyInvariantsSnapshot


class TelemetryReader:
    """Non-blocking, fail-safe telemetry ingestion reader for paper trading artifacts."""

    def __init__(self, storage_dir: Path | str) -> None:
        self.storage_dir = Path(storage_dir)
        self.health_file = self.storage_dir / "paper-daemon-health.json"
        self.ledger_db = self.storage_dir / "paper-ledger.sqlite3"
        self.lifecycle_db = self.storage_dir / "paper-lifecycle.sqlite3"
        self.observations_db = self.storage_dir / "paper-observations.sqlite3"
        self._last_snapshot: TuiTelemetrySnapshot | None = None
        self._last_known_prices: dict[str, Decimal] = dict(DEFAULT_NOMINAL_PRICES)

    def poll(self) -> TuiTelemetrySnapshot:
        """Poll all telemetry sources and assemble an immutable TuiTelemetrySnapshot.

        Never raises unhandled exceptions to callers; safely falls back to cached
        or default synthetic zero-state data on I/O or decode errors.
        """
        now_utc = datetime.now(UTC)
        try:
            health_raw = self._read_health_json()
            lifecycle_marks = self._query_lifecycle_marks()
            closed_trades = self._query_closed_trades(limit=10)
            observations = self._query_observations()

            is_stale = False
            if health_raw is None:
                is_stale = True
                daemon_snap = self._build_offline_daemon_snapshot(now_utc)
            else:
                daemon_snap, is_stale = self._parse_daemon_health(health_raw, now_utc)

            margin_snap = self._parse_margin(health_raw, observations)
            regimes = self._parse_regimes(health_raw, lifecycle_marks)
            positions = self._parse_positions(health_raw, lifecycle_marks, regimes)
            safety_snap = self._parse_safety(health_raw)

            snapshot = TuiTelemetrySnapshot(
                timestamp=now_utc,
                storage_dir=self.storage_dir,
                is_stale=is_stale,
                daemon=daemon_snap,
                margin=margin_snap,
                regimes=regimes,
                positions=positions,
                recent_closed_trades=closed_trades,
                safety=safety_snap,
            )
            self._last_snapshot = snapshot
            return snapshot

        except Exception:
            if self._last_snapshot is not None:
                return TuiTelemetrySnapshot(
                    timestamp=now_utc,
                    storage_dir=self.storage_dir,
                    is_stale=True,
                    daemon=self._last_snapshot.daemon,
                    margin=self._last_snapshot.margin,
                    regimes=self._last_snapshot.regimes,
                    positions=self._last_snapshot.positions,
                    recent_closed_trades=self._last_snapshot.recent_closed_trades,
                    safety=self._last_snapshot.safety,
                )
            return self._build_default_snapshot(now_utc)

    def _read_health_json(self) -> dict[str, Any] | None:
        """Read and parse paper-daemon-health.json atomically."""
        if not self.health_file.is_file():
            return None
        try:
            text = self.health_file.read_text(encoding="utf-8")
            if not text.strip():
                return None
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            return None
        except FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError:
            return None

    def _connect_readonly(self, db_path: Path) -> sqlite3.Connection | None:
        """Open a SQLite database strictly in read-only mode with busy timeout."""
        if not db_path.is_file():
            return None
        try:
            uri_path = db_path.resolve().as_posix()
            uri = f"file:{uri_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=1.0)
            conn.execute("PRAGMA query_only = ON;")
            conn.execute("PRAGMA busy_timeout = 1000;")
            return conn
        except sqlite3.OperationalError, sqlite3.DatabaseError, OSError:
            return None

    def _has_table(self, conn: sqlite3.Connection, table_name: str) -> bool:
        """Check whether a table exists in the connected database."""
        try:
            cursor = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False

    def _query_closed_trades(self, limit: int = 10) -> tuple[ClosedTradeSnapshot, ...]:
        """Query recent closed trades from paper-ledger.sqlite3."""
        conn = self._connect_readonly(self.ledger_db)
        if conn is None:
            return ()
        try:
            if not self._has_table(conn, "paper_ledger_events"):
                return ()

            cursor = conn.execute(
                """
                SELECT sequence, trade_id, symbol, side, quantity, fill_price, occurred_at,
                       entry_fee, exit_fee, net_pnl, approval_id
                FROM paper_ledger_events
                WHERE event = 'close'
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            trades: list[ClosedTradeSnapshot] = []

            # Match exit reasons from lifecycle marks
            lifecycle_reasons = self._query_exit_reasons()

            for row in rows:
                seq, tid, sym, side, qty, price, occ, e_fee, x_fee, net, _ = row
                reason = lifecycle_reasons.get(str(tid), "normal_close")
                entry_f = Decimal(str(e_fee)) if e_fee is not None else Decimal("0.00")
                exit_f = Decimal(str(x_fee)) if x_fee is not None else Decimal("0.00")
                trades.append(
                    ClosedTradeSnapshot(
                        sequence=int(seq),
                        trade_id=str(tid),
                        symbol=str(sym),
                        side=str(side).upper(),
                        quantity=Decimal(str(qty)),
                        fill_price=Decimal(str(price)),
                        occurred_at=str(occ),
                        net_pnl=Decimal(str(net)) if net is not None else Decimal("0.00"),
                        entry_fee=entry_f,
                        exit_fee=exit_f,
                        total_fees=entry_f + exit_f,
                        exit_reason=reason,
                    )
                )
            return tuple(trades)
        except sqlite3.Error, ValueError:
            return ()
        finally:
            conn.close()

    def _query_exit_reasons(self) -> dict[str, str]:
        """Map trade_ids to exit rationale codes from paper_lifecycle_marks."""
        conn = self._connect_readonly(self.lifecycle_db)
        if conn is None:
            return {}
        try:
            if not self._has_table(conn, "paper_lifecycle_marks"):
                return {}

            cursor = conn.execute(
                """
                SELECT trade_id, payload
                FROM paper_lifecycle_marks
                WHERE payload LIKE '%reason_codes%'
                ORDER BY sequence DESC
                LIMIT 50
                """
            )
            reasons: dict[str, str] = {}
            for tid, payload_str in cursor.fetchall():
                trade_id_str = str(tid)
                if trade_id_str in reasons:
                    continue
                try:
                    payload = json.loads(payload_str)
                    rcodes = payload.get("reason_codes", [])
                    if "stop_loss_hit" in rcodes:
                        reasons[trade_id_str] = "stop_loss"
                    elif "take_profit_hit" in rcodes:
                        reasons[trade_id_str] = "take_profit"
                    elif "trailing_stop_hit" in rcodes:
                        reasons[trade_id_str] = "trailing_stop"
                    elif "strategy_exit" in rcodes:
                        reasons[trade_id_str] = "strategy_exit"
                    elif rcodes:
                        reasons[trade_id_str] = str(rcodes[0])
                except json.JSONDecodeError, KeyError:
                    pass
            return reasons
        except sqlite3.Error:
            return {}
        finally:
            conn.close()

    def _query_lifecycle_marks(self) -> dict[str, dict[str, Any]]:
        """Fetch latest mark payload for each monitored symbol from paper-lifecycle.sqlite3."""
        conn = self._connect_readonly(self.lifecycle_db)
        if conn is None:
            return {}
        try:
            if not self._has_table(conn, "paper_lifecycle_marks"):
                return {}

            cursor = conn.execute(
                """
                SELECT trade_id, payload
                FROM paper_lifecycle_marks
                ORDER BY sequence DESC
                LIMIT 40
                """
            )
            latest_by_symbol: dict[str, dict[str, Any]] = {}
            for _, payload_str in cursor.fetchall():
                try:
                    p = json.loads(payload_str)
                    sym = p.get("symbol")
                    if sym and sym not in latest_by_symbol:
                        latest_by_symbol[sym] = p
                except json.JSONDecodeError, KeyError:
                    continue
            return latest_by_symbol
        except sqlite3.Error:
            return {}
        finally:
            conn.close()

    def _query_observations(self) -> dict[str, Any] | None:
        """Fetch latest portfolio observation checkpoint from paper-observations.sqlite3."""
        conn = self._connect_readonly(self.observations_db)
        if conn is None:
            return None
        try:
            if not self._has_table(conn, "paper_observations"):
                return None

            cursor = conn.execute(
                """
                SELECT payload
                FROM paper_observations
                ORDER BY sequence DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row:
                data = json.loads(row[0])
                if isinstance(data, dict):
                    return data
            return None
        except sqlite3.Error, json.JSONDecodeError:
            return None
        finally:
            conn.close()

    def _parse_daemon_health(
        self, data: dict[str, Any], now_utc: datetime
    ) -> tuple[DaemonHealthSnapshot, bool]:
        """Parse DaemonHealthSnapshot from raw JSON and determine staleness."""
        status = str(data.get("daemon_status", "UNKNOWN"))
        pid = data.get("pid")
        uptime = float(data.get("uptime_seconds", 0.0))
        started_at = str(data.get("started_at_utc", now_utc.isoformat()))
        last_hb = str(data.get("last_heartbeat_utc", started_at))

        try:
            hb_dt = datetime.fromisoformat(last_hb)
            if hb_dt.tzinfo is None:
                hb_dt = hb_dt.replace(tzinfo=UTC)
            age = max(0.0, (now_utc - hb_dt).total_seconds())
        except ValueError, TypeError:
            age = 999.0

        is_stale = age > 60.0 or status in ("HALTED", "OFFLINE")
        symbols = tuple(data.get("symbols_monitored", list(DEFAULT_SYMBOLS)))
        msgs = int(data.get("feed_messages_received", 0))
        throughput = round(msgs / uptime, 1) if uptime > 0 else 0.0
        reconnects = int(data.get("feed_reconnects_count", 0))
        cb_status = str(data.get("circuit_breaker_status", "NORMAL"))
        invariants = data.get("zero_order_safety_invariants", {})

        return (
            DaemonHealthSnapshot(
                status=status,
                pid=int(pid) if pid else None,
                uptime_seconds=uptime,
                started_at_utc=started_at,
                last_heartbeat_utc=last_hb,
                heartbeat_age_seconds=round(age, 1),
                symbols_monitored=symbols,
                feed_messages_received=msgs,
                feed_throughput_per_sec=throughput,
                feed_reconnects_count=reconnects,
                circuit_breaker_status=cb_status,
                zero_order_invariants=invariants,
            ),
            is_stale,
        )

    def _build_offline_daemon_snapshot(self, now_utc: datetime) -> DaemonHealthSnapshot:
        """Construct offline/warmup daemon health snapshot."""
        return DaemonHealthSnapshot(
            status="OFFLINE",
            pid=None,
            uptime_seconds=0.0,
            started_at_utc=now_utc.isoformat(),
            last_heartbeat_utc=now_utc.isoformat(),
            heartbeat_age_seconds=999.0,
            symbols_monitored=DEFAULT_SYMBOLS,
            feed_messages_received=0,
            feed_throughput_per_sec=0.0,
            feed_reconnects_count=0,
            circuit_breaker_status="NORMAL",
            zero_order_invariants={
                "orders_submitted": 0,
                "execution_authority": False,
                "live_trading_activation": False,
                "paper_activation": True,
                "promotion_state": "unpromoted",
                "zero_private_credentials": True,
            },
        )

    def _parse_margin(
        self,
        health_raw: dict[str, Any] | None,
        observations: dict[str, Any] | None,
    ) -> MarginAccountSnapshot:
        """Parse MarginAccountSnapshot with exact Decimal accounting."""
        starting_cap = Decimal("100.00")
        current_cash = Decimal("100.00")
        current_equity = Decimal("100.00")
        utilization = 0.0
        reserve = 100.0
        peak_equity = Decimal("100.00")

        if health_raw is not None:
            starting_cap = Decimal(str(health_raw.get("starting_capital_usdt", "100.00")))
            current_cash = Decimal(str(health_raw.get("current_cash_usdt", "100.00")))
            current_equity = Decimal(str(health_raw.get("current_equity_usdt", "100.00")))
            utilization = float(health_raw.get("margin_utilization_pct", 0.0))
            reserve = float(health_raw.get("reserve_buffer_pct", 100.0))

        if observations is not None:
            obs_peak = observations.get("peak_equity")
            if obs_peak is not None:
                peak_equity = Decimal(str(obs_peak))
        else:
            peak_equity = max(current_equity, starting_cap)

        realized_pnl = current_cash - starting_cap
        unrealized_pnl = current_equity - current_cash
        realized_pct = (
            (realized_pnl / starting_cap) * Decimal("100") if starting_cap > 0 else Decimal("0")
        )
        unrealized_pct = (
            (unrealized_pnl / starting_cap) * Decimal("100") if starting_cap > 0 else Decimal("0")
        )

        return MarginAccountSnapshot(
            starting_capital=starting_cap,
            current_cash=current_cash,
            current_equity=current_equity,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pct,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pct,
            margin_utilization_pct=round(utilization, 2),
            reserve_buffer_pct=round(reserve, 2),
            peak_equity=peak_equity,
        )

    def _parse_regimes(
        self,
        health_raw: dict[str, Any] | None,
        lifecycle_marks: dict[str, dict[str, Any]],
    ) -> dict[str, MarketRegimeSnapshot]:
        """Parse MarketRegimeSnapshot for BTC, ETH, SOL, DOGE."""
        regimes: dict[str, MarketRegimeSnapshot] = {}

        # Check for direct market_regimes dictionary in health JSON
        custom_regimes = health_raw.get("market_regimes", {}) if health_raw else {}

        for sym in DEFAULT_SYMBOLS:
            if sym in custom_regimes:
                data = custom_regimes[sym]
                bid = Decimal(str(data.get("bid_price", "0")))
                ask = Decimal(str(data.get("ask_price", "0")))
                mid = Decimal(str(data.get("mid_price", "0")))
                spread = Decimal(str(data.get("spread_bps", "0.5")))
                atr = Decimal(str(data.get("rolling_atr", "0.0")))
                status = "NORMAL"
                if spread >= Decimal("20.0"):
                    status = "HALTED"
                elif spread >= Decimal("5.0"):
                    status = "WIDE_SPREAD"
                regimes[sym] = MarketRegimeSnapshot(
                    symbol=sym,
                    best_bid=bid,
                    best_ask=ask,
                    mid_price=mid,
                    spread_bps=spread,
                    rolling_atr=atr,
                    status=status,
                )
                self._last_known_prices[sym] = mid
                continue

            # Fallback to lifecycle mark price if active
            if sym in lifecycle_marks:
                p_mark = Decimal(str(lifecycle_marks[sym].get("mark_price", "0")))
                if p_mark > Decimal("0"):
                    self._last_known_prices[sym] = p_mark
                    spread_est = Decimal("0.65")
                    bid = p_mark - (p_mark * Decimal("0.00003"))
                    ask = p_mark + (p_mark * Decimal("0.00003"))
                    regimes[sym] = MarketRegimeSnapshot(
                        symbol=sym,
                        best_bid=bid,
                        best_ask=ask,
                        mid_price=p_mark,
                        spread_bps=spread_est,
                        rolling_atr=p_mark * Decimal("0.002"),
                        status="NORMAL",
                    )
                    continue

            # Fallback to nominal price
            fallback_price = self._last_known_prices.get(
                sym, DEFAULT_NOMINAL_PRICES.get(sym, Decimal("100.00"))
            )
            regimes[sym] = MarketRegimeSnapshot(
                symbol=sym,
                best_bid=fallback_price,
                best_ask=fallback_price,
                mid_price=fallback_price,
                spread_bps=Decimal("0.50"),
                rolling_atr=fallback_price * Decimal("0.001"),
                status="WARMUP" if health_raw is None else "NORMAL",
            )
        return regimes

    def _parse_positions(
        self,
        health_raw: dict[str, Any] | None,
        lifecycle_marks: dict[str, dict[str, Any]],
        regimes: dict[str, MarketRegimeSnapshot],
    ) -> dict[str, PositionSnapshot]:
        """Parse active PositionSnapshots from health JSON and lifecycle marks."""
        positions: dict[str, PositionSnapshot] = {}
        raw_positions = health_raw.get("active_positions", {}) if health_raw else {}

        for sym, pos_data in raw_positions.items():
            side = str(pos_data.get("side", "LONG")).upper()
            qty = Decimal(str(pos_data.get("quantity", "0")))
            entry_p = Decimal(str(pos_data.get("entry_price", "0")))
            lev = Decimal(str(pos_data.get("leverage", "1.0")))

            mark_p = entry_p
            upnl = Decimal("0.00")
            upnl_pct = Decimal("0.00")
            sl_price: Decimal | None = None
            ts_price: Decimal | None = None

            if sym in lifecycle_marks:
                lm = lifecycle_marks[sym]
                mark_p = Decimal(str(lm.get("mark_price", entry_p)))
                upnl = Decimal(str(lm.get("mark_to_market_pnl", "0")))
                upnl_pct = Decimal(str(lm.get("pnl_pct", "0"))) * Decimal("100")
                if lm.get("stop_loss_price"):
                    sl_price = Decimal(str(lm["stop_loss_price"]))
                if lm.get("trailing_stop_price"):
                    ts_price = Decimal(str(lm["trailing_stop_price"]))
            elif sym in regimes and regimes[sym].mid_price > Decimal("0"):
                mark_p = regimes[sym].mid_price
                if side == "LONG":
                    upnl = (mark_p - entry_p) * qty
                else:
                    upnl = (entry_p - mark_p) * qty
                if entry_p > Decimal("0"):
                    upnl_pct = (
                        ((mark_p - entry_p) / entry_p) * Decimal("100")
                        if side == "LONG"
                        else ((entry_p - mark_p) / entry_p) * Decimal("100")
                    )

            liq_buffer = Decimal("1.0") / lev if lev > Decimal("0") else Decimal("0.5")
            liq_dist = liq_buffer * Decimal("100")

            positions[sym] = PositionSnapshot(
                symbol=sym,
                side=side,
                quantity=qty,
                entry_price=entry_p,
                mark_price=mark_p,
                unrealized_pnl=upnl,
                pnl_pct=upnl_pct,
                leverage=lev,
                liquidation_distance_pct=liq_dist,
                stop_loss_price=sl_price,
                trailing_stop_price=ts_price,
            )
        return positions

    def _parse_safety(self, health_raw: dict[str, Any] | None) -> SafetyInvariantsSnapshot:
        """Parse and verify non-negotiable safety guardrails and invariants."""
        cb_status = (
            str(health_raw.get("circuit_breaker_status", "NORMAL")) if health_raw else "NORMAL"
        )
        invariants = health_raw.get("zero_order_safety_invariants", {}) if health_raw else {}

        orders = int(invariants.get("orders_submitted", 0))
        exec_auth = bool(invariants.get("execution_authority", False))
        live_act = bool(invariants.get("live_trading_activation", False))
        paper_act = bool(invariants.get("paper_activation", True))
        promo = str(invariants.get("promotion_state", "unpromoted"))
        zero_creds = bool(invariants.get("zero_private_credentials", True))

        all_pass = (
            orders == 0
            and not exec_auth
            and not live_act
            and paper_act
            and promo == "unpromoted"
            and zero_creds
        )

        return SafetyInvariantsSnapshot(
            volatility_cb=cb_status,
            spread_cb="NORMAL" if cb_status == "NORMAL" else "TRIPPED",
            orders_submitted=orders,
            execution_authority=exec_auth,
            live_trading_activation=live_act,
            paper_activation=paper_act,
            promotion_state=promo,
            zero_private_credentials=zero_creds,
            all_invariants_pass=all_pass,
        )

    def _build_default_snapshot(self, now_utc: datetime) -> TuiTelemetrySnapshot:
        """Build a clean default snapshot for initial warmup or error states."""
        return TuiTelemetrySnapshot(
            timestamp=now_utc,
            storage_dir=self.storage_dir,
            is_stale=True,
            daemon=self._build_offline_daemon_snapshot(now_utc),
            margin=self._parse_margin(None, None),
            regimes=self._parse_regimes(None, {}),
            positions={},
            recent_closed_trades=(),
            safety=self._parse_safety(None),
        )
