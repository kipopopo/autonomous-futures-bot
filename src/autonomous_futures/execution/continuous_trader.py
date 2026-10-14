"""Continuous 24/7 Self-Driving Trading Daemon (Phase 310 R4).

Runs continuously on the Kainode Linux VPS (or local development), integrating:
- Dual-mode Binance Futures Gateway Bridge (REST & WebSocket)
- Multi-horizon macro trend filtering (BTC 1h EMA 50 > EMA 200)
- 15m Macro-Confluence Liquidity Dip Scalper on SOLUSDT & ETHUSDT
- Protective bracket orders (Take Profit 2.0x ATR, Stop Loss 1.2x ATR, 2h Time Decay)
- Strict micro-capital confinement (<= 5.00 USDT child, <= 25.00 USDT aggregate, >= 75% cash)
- Continuous double-entry zero-drift ledger reconciliation (|drift| < 10^-15 USDT)
- Closed-loop trade autopsy feedback and candidate health updates
- Real-time Telegram alerts via Telegram sidecar notifier integration
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    BinanceFuturesGateway,
)
from autonomous_futures.execution.live_orders import LiveOrderBook
from autonomous_futures.execution.self_driving import (
    SelfDrivingTradingEngine,
    build_default_self_driving_engine,
)
from autonomous_futures.feed.kline_sequencer import (
    ACTIVE_PAIRS,
    MultiTimeframeCandleSequencer,
)
from autonomous_futures.notify.telegram import (
    TelegramNotifierClient,
    escape_markdown_v2,
    resolve_telegram_credentials,
)
from autonomous_futures.strategy.ict_mmxm import (
    Candle as IctCandle,
)
from autonomous_futures.strategy.ict_mmxm import (
    IctMmxmEngine,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    compute_ema,
)

logger = logging.getLogger("autonomous_futures.execution.continuous_trader")


class ContinuousSelfDrivingTrader:
    """Master 24/7 Continuous Trader Daemon for Binance Futures."""

    def __init__(
        self,
        storage_dir: Path,
        symbols: list[str] | None = None,
        starting_capital_usdt: Decimal = Decimal("100.00"),
        poll_interval_seconds: float = 15.0,
        gateway: BinanceFuturesGateway | None = None,
        telegram_enabled: bool = True,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.symbols = list(symbols) if symbols is not None else list(ACTIVE_PAIRS)
        self.starting_capital_usdt = starting_capital_usdt
        self.poll_interval_seconds = poll_interval_seconds
        self.running = False
        self._shutdown_event = asyncio.Event()

        # Gateway resolution
        self.gateway = gateway or BinanceFuturesGateway()
        self.live_orders = LiveOrderBook(self.gateway, self.storage_dir)

        # Initialize internal SelfDrivingTradingEngine
        self.engine: SelfDrivingTradingEngine = build_default_self_driving_engine(
            starting_capital_usdt=self.starting_capital_usdt,
            gateway=self.gateway,
            storage_dir=self.storage_dir,
        )

        # Telegram notifier client setup
        self.telegram_client: TelegramNotifierClient | None = None
        if telegram_enabled:
            tg_config = resolve_telegram_credentials()
            if tg_config.is_configured:
                self.telegram_client = TelegramNotifierClient(tg_config)
                logger.info("Telegram trade notification client configured.")
            else:
                logger.info("Telegram credentials not configured; alerts disabled.")

        # Local candidate candle cache (symbol -> list[Candle])
        self.candle_history: dict[str, list[Candle]] = {sym: [] for sym in self.symbols}
        self.btc_1h_history: list[Candle] = []
        self.last_candle_fetch_ts: float = 0.0

        # Multi-timeframe candle sequencer (4h, 1h, 15m, 5m, 1m across expanded pairs)
        sequencer_symbols = list(dict.fromkeys(["BTCUSDT"] + self.symbols))
        self.sequencer = MultiTimeframeCandleSequencer(
            gateway=self.gateway,
            symbols=sequencer_symbols,
        )

        # ICT MMXM pattern recognition engine with 50% Equilibrium OTE tuning
        self.ict_engine = IctMmxmEngine(
            lookback_htf=100,
            default_tick_size=Decimal("0.01"),
            ote_lower=Decimal("0.62"),
        )
        self.last_export_ts: float = time.time()

    def get_multi_tf_candles(
        self, symbol: str
    ) -> tuple[list[IctCandle], list[IctCandle], list[IctCandle], list[IctCandle], list[IctCandle]]:
        """Returns (4h, 1h, 15m, 5m, 1m) candles for the given symbol."""
        return self.sequencer.get_multi_tf_candles(symbol)

    def get_macro_candles(self, timeframe: str) -> list[Candle]:
        return [
            Candle(
                timestamp_ms=c.timestamp_ms,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in self.sequencer.get_candles("BTCUSDT", timeframe)
        ]

    async def send_telegram_alert(self, text: str) -> None:
        """Sends an urgent markdown message to the configured Telegram channel."""
        if not self.telegram_client:
            return
        try:
            await asyncio.to_thread(
                self.telegram_client.send_message,
                text,
                parse_mode="MarkdownV2",
            )
        except Exception as exc:
            logger.warning("Failed to send Telegram alert: %s", exc)

    async def synchronize_and_verify_connectivity(self) -> Decimal:
        """Connects to Binance Futures, checks clock drift, and syncs account balance."""
        logger.info("Testing connectivity to Binance Futures (%s)...", self.gateway.rest_base)
        server_time = await self.gateway.get_server_time()
        offset = await self.gateway.sync_clock_drift()
        logger.info("Server time: %s, Clock drift offset: %d ms", server_time, offset)

        await self.gateway.refresh_exchange_filters()
        acc = await self.gateway.get_account_balance()
        wallet_str = acc["totalWalletBalance"]
        avail_str = acc["availableBalance"]
        wallet_balance = Decimal(str(wallet_str))
        logger.info(
            "Binance Account Verified: Wallet Balance = %s USDT, Available = %s USDT",
            wallet_str,
            avail_str,
        )

        return wallet_balance

    async def update_market_candles(self) -> None:
        """Fetches latest 1h BTC candles and 15m candidate candles from Binance."""
        # 1. Update BTC 1h candles (need >= 200 bars for EMA 200)
        try:
            raw_btc = await self.gateway.get_klines("BTCUSDT", interval="1h", limit=250)
            self.btc_1h_history = [
                Candle(
                    timestamp_ms=int(r[0]),
                    open=Decimal(str(r[1])),
                    high=Decimal(str(r[2])),
                    low=Decimal(str(r[3])),
                    close=Decimal(str(r[4])),
                    volume=Decimal(str(r[5])),
                )
                for r in raw_btc
            ]
            if self.btc_1h_history and "BTCUSDT" in self.engine.candidates:
                self.engine.candidates["BTCUSDT"].current_price = self.btc_1h_history[-1].close
        except Exception as exc:
            logger.warning("Failed to fetch BTCUSDT 1h klines: %s", exc)

        # 2. Update 15m candles for each scalper symbol
        for sym in self.symbols:
            try:
                raw_sym = await self.gateway.get_klines(sym, interval="15m", limit=100)
                self.candle_history[sym] = [
                    Candle(
                        timestamp_ms=int(r[0]),
                        open=Decimal(str(r[1])),
                        high=Decimal(str(r[2])),
                        low=Decimal(str(r[3])),
                        close=Decimal(str(r[4])),
                        volume=Decimal(str(r[5])),
                    )
                    for r in raw_sym
                ]
            except Exception as exc:
                logger.warning("Failed to fetch %s 15m klines: %s", sym, exc)

        self.last_candle_fetch_ts = time.time()

    async def run_single_cycle(self) -> None:
        """Executes one scan and risk evaluation cycle."""
        now_ms = int(time.time() * 1000)

        # Non-blocking hierarchical TTL refresh across 40 streams (< 15ms when cached)
        try:
            await self.sequencer.refresh_due_candles(now_ts=time.time())
            seq_btc_1h = self.sequencer.get_candles("BTCUSDT", "1h")
            if seq_btc_1h:
                self.btc_1h_history = [
                    Candle(
                        timestamp_ms=c.timestamp_ms,
                        open=c.open,
                        high=c.high,
                        low=c.low,
                        close=c.close,
                        volume=c.volume,
                    )
                    for c in seq_btc_1h
                ]
            for sym in self.symbols:
                seq_15m = self.sequencer.get_candles(sym, "15m")
                if seq_15m:
                    self.candle_history[sym] = [
                        Candle(
                            timestamp_ms=c.timestamp_ms,
                            open=c.open,
                            high=c.high,
                            low=c.low,
                            close=c.close,
                            volume=c.volume,
                        )
                        for c in seq_15m
                    ]
        except Exception as seq_err:
            logger.debug("Sequencer cycle refresh note: %s", seq_err)

        # Publish real account observations before any strategy evaluation.
        from autonomous_futures.execution.account_evidence import SNAPSHOT_NAME, observe_account

        if getattr(self.gateway, "offline_mode", True) is False:
            try:
                await self.live_orders.reconcile()
                await observe_account(self.gateway, self.storage_dir / SNAPSHOT_NAME)
            except Exception as exc:
                logger.error("Account observation failed; trading blocked: %s", exc)
                return
            # Live execution must not call the engine's simulation matching methods.
            # Signal evaluation can proceed, but authority is unavailable until
            # exchange reconciliation and measured microstructure evidence are wired.
            logger.info("Exchange observed; live dispatch blocked pending execution qualification")
            return
        try:
            positions = await self.gateway.get_position_risk()
            pos_by_sym = {p["symbol"]: p for p in positions}
        except Exception as exc:
            logger.error("Position state unknown; skipping cycle: %s", exc)
            return

        # 1.1 Drain pending ICT autopsies into SQLite tables and events log (< 15ms latency)
        if getattr(self.engine, "has_pending_autopsies", lambda: False)():
            try:
                db_target = self.storage_dir / "canary-production-telemetry.sqlite3"
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self.engine.drain_pending_autopsies, db_target),
                        timeout=0.005,
                    )
                except TimeoutError:
                    logger.warning("Autopsy drain disk I/O exceeded 5.0ms budget; continuing cycle")
            except Exception as drain_err:
                logger.warning("Autopsy drain non-fatal error: %s", drain_err)

        # 2. Multi-pair ICT MMXM Twins Reversal evaluation across all candidate pairs
        for sym in self.sequencer.symbols:
            c4h, c1h, c15m, c5m, c1m = self.sequencer.get_multi_tf_candles(sym)
            if not self.sequencer.is_trade_ready(sym) or len(c5m) < 5 or len(c1m) < 5:
                continue

            spec = DEFAULT_SPECS.get(sym, {})
            tick_size = spec.get("tick_size", Decimal("0.01"))
            setup_state = self.ict_engine.evaluate_twins_setup(
                symbol=sym,
                candles_4h=c4h,
                candles_1h=c1h,
                candles_15m=c15m,
                candles_5m=c5m,
                candles_1m=c1m,
                tick_size=tick_size,
            )

            if setup_state.step_6_ready:
                exch_pos = pos_by_sym.get(sym)
                pos_amt = (
                    Decimal(str(exch_pos.get("positionAmt", "0"))) if exch_pos else Decimal("0")
                )
                cand_state = self.engine.candidates.get(sym)
                local_qty = cand_state.position_qty if cand_state else Decimal("0")

                if abs(pos_amt) == Decimal("0") and abs(local_qty) == Decimal("0"):
                    ict_order = self.engine.dispatch_ict_intention(setup_state, now_ms=now_ms)
                    if ict_order is not None:
                        logger.info(
                            "DISPATCHED ICT ORDER: %s %s %s @ %s",
                            ict_order.symbol,
                            ict_order.side.value,
                            ict_order.quantity,
                            ict_order.price,
                        )
                        alert_msg = (
                            f"🚀 *New ICT Twins Reversal Executed "
                            f"\\({escape_markdown_v2(sym)}\\)*\n"
                            f"Side: `{ict_order.side.value}` \\(MAKER LIMIT\\)\n"
                            f"Price: `{ict_order.price}` USDT\n"
                            f"Notional: `{ict_order.notional_usdt}` USDT\n"
                            f"Stop Loss: `{ict_order.stop_loss}` USDT\n"
                            f"Take Profit: `{ict_order.take_profit}` USDT\n"
                            f"Tag: `{escape_markdown_v2(ict_order.client_order_id)}`"
                        )
                        await self.send_telegram_alert(alert_msg)

        if not self.btc_1h_history:
            logger.debug("Waiting for BTC 1h history to populate...")
            return

        # Synchronize BTCUSDT current price and macro EMAs in engine
        btc_close = self.btc_1h_history[-1].close
        if "BTCUSDT" in self.engine.candidates:
            self.engine.candidates["BTCUSDT"].current_price = btc_close

        closes_1h = [c.close for c in self.btc_1h_history]
        if len(closes_1h) >= 50:
            e50 = compute_ema(closes_1h, 50)
            e200 = compute_ema(closes_1h, 200) if len(closes_1h) >= 200 else e50
            self.engine.latest_btc_ema50 = float(e50[-1])
            self.engine.latest_btc_ema200 = float(e200[-1])

        # 3. Evaluate Scalper on each candidate symbol
        for sym in self.symbols:
            candles = self.candle_history.get(sym, [])
            if not self.sequencer.is_trade_ready(sym) or len(candles) < 25:
                continue

            latest_closed_bar = candles[-1]
            history = candles[:-1]

            # Update current mark price in engine
            current_mark = latest_closed_bar.close
            if sym in self.engine.candidates:
                self.engine.candidates[sym].current_price = current_mark

            # Check if we already have an active position on exchange
            exch_pos = pos_by_sym.get(sym)
            pos_amt = Decimal(str(exch_pos.get("positionAmt", "0"))) if exch_pos else Decimal("0")

            if abs(pos_amt) > Decimal("0"):
                # Position is open: check TP / SL / Time decay
                cand_state = self.engine.candidates.get(sym)
                if cand_state and cand_state.entry_price > 0:
                    tp = cand_state.take_profit
                    sl = cand_state.stop_loss
                    entry_bar_idx = cand_state.entry_bar_index
                    current_bar_idx = len(candles)

                    is_tp = tp > 0 and current_mark >= tp
                    is_sl = sl > 0 and current_mark <= sl
                    is_decay = (current_bar_idx - entry_bar_idx) >= 8

                    if is_tp or is_sl or is_decay:
                        if is_tp:
                            exit_reason = "TAKE_PROFIT"
                        elif is_sl:
                            exit_reason = "STOP_LOSS"
                        else:
                            exit_reason = "TIME_DECAY"

                        logger.info(
                            "Position exit condition met for %s (%s): "
                            "mark=%s, entry=%s, TP=%s, SL=%s",
                            sym,
                            exit_reason,
                            current_mark,
                            cand_state.entry_price,
                            tp,
                            sl,
                        )
                        # Dispatch exit order
                        exit_order = self.engine.evaluate_and_dispatch_scalper(
                            symbol=sym,
                            bar=latest_closed_bar,
                            history=history,
                            btc_1h_candles=self.btc_1h_history,
                            btc_4h_candles=self.get_macro_candles("4h"),
                            now_ms=now_ms,
                        )
                        if exit_order:
                            await self.send_telegram_alert(
                                f"🎯 *Trade Exit Realized \\({escape_markdown_v2(sym)}\\)*\n"
                                f"Reason: `{exit_reason}`\n"
                                f"Price: `{exit_order.price}` USDT\n"
                                f"Realized PnL: `{exit_order.realized_pnl_usdt}` USDT"
                            )
                continue

            # No open position: evaluate new liquidity sweep entry
            order = self.engine.evaluate_and_dispatch_scalper(
                symbol=sym,
                bar=latest_closed_bar,
                history=history,
                btc_1h_candles=self.btc_1h_history,
                btc_4h_candles=self.get_macro_candles("4h"),
                now_ms=now_ms,
            )
            if order is not None:
                logger.info(
                    "DISPATCHED ENTRY ORDER: %s %s %s @ %s (SL=%s, TP=%s)",
                    order.symbol,
                    order.side.value,
                    order.quantity,
                    order.price,
                    order.stop_loss,
                    order.take_profit,
                )
                await self.send_telegram_alert(
                    f"🚀 *New Scalper Signal Executed \\({escape_markdown_v2(sym)}\\)*\n"
                    f"Side: `{order.side.value}` \\(MAKER LIMIT\\)\n"
                    f"Price: `{order.price}` USDT\n"
                    f"Notional: `{order.notional_usdt}` USDT\n"
                    f"Stop Loss: `{order.stop_loss}` USDT\n"
                    f"Take Profit: `{order.take_profit}` USDT"
                )

        # 3. Export live-prices.json and Merkle DAG artifacts periodically (every 10s)
        now_wall = time.time()
        if now_wall - self.last_export_ts >= 10.0:
            try:
                prices_payload = {
                    "timestamp_ms": now_ms,
                    "prices": {
                        sym: float(c.current_price) for sym, c in self.engine.candidates.items()
                    },
                    "btc_macro": {
                        "current_price": float(self.engine.candidates["BTCUSDT"].current_price)
                        if "BTCUSDT" in self.engine.candidates
                        else 0.0,
                        "ema50_1h": getattr(self.engine, "latest_btc_ema50", 0.0),
                        "ema200_1h": getattr(self.engine, "latest_btc_ema200", 0.0),
                        "regime": "BULLISH ALIGNED"
                        if getattr(self.engine, "latest_btc_ema50", 0.0)
                        > getattr(self.engine, "latest_btc_ema200", 0.0)
                        else "BEARISH / SIDEWAYS",
                    },
                    "source": "continuous_trader",
                }
                (self.storage_dir / "live-prices.json").write_text(
                    json.dumps(prices_payload, indent=2), encoding="utf-8"
                )
            except Exception as lp_err:
                logger.debug("Could not write live-prices.json: %s", lp_err)

            self.engine.export_artifacts(self.storage_dir)
            self.last_export_ts = now_wall

    async def start(self) -> None:
        """Starts the continuous trading loop."""
        self.running = True
        logger.info("Starting Continuous Self-Driving Trader Daemon...")

        # Initial connectivity probe & balance sync
        try:
            wallet_balance = await self.synchronize_and_verify_connectivity()
            # Send Telegram startup notification
            await self.send_telegram_alert(
                f"🟢 *Autonomous Futures Bot Online*\n"
                f"Mode: `Binance Futures Testnet`\n"
                f"Wallet: `{wallet_balance:.2f}` USDT\n"
                f"Candidates: `{escape_markdown_v2(', '.join(self.symbols))}`\n"
                f"Strategy: `15m Macro Liquidity Scalper`"
            )
        except Exception as init_err:
            logger.error("Initial exchange sync failed; startup blocked: %s", init_err)
            self.running = False
            return

        cycle_count = 0
        while self.running and not self._shutdown_event.is_set():
            try:
                cycle_count += 1
                await self.run_single_cycle()
            except Exception as loop_err:
                logger.error("Error in continuous trading cycle #%d: %s", cycle_count, loop_err)

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.poll_interval_seconds,
                )
                break
            except TimeoutError:
                pass

        if hasattr(self.engine, "close_telemetry_db"):
            self.engine.close_telemetry_db()
        logger.info("Continuous Self-Driving Trader Daemon shutdown complete.")

    def stop(self) -> None:
        """Signals the daemon to stop cleanly."""
        logger.info("Stop requested for Continuous Trader Daemon.")
        self.running = False
        self._shutdown_event.set()
        if hasattr(self.engine, "close_telemetry_db"):
            self.engine.close_telemetry_db()

    async def __aenter__(self) -> ContinuousSelfDrivingTrader:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
        if hasattr(self.engine, "close_telemetry_db"):
            self.engine.close_telemetry_db()
