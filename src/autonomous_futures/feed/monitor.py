"""Phase 257: Circuit Breaker Feed Monitor.

Decoupled asynchronous worker queue integrating live market WebSocket streams
(TickerSnapshot and CanonicalBar) with HardenedSharedMarginAccount.evaluate_circuit_breaker.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot
from autonomous_futures.paper.circuit_breakers import (
    CircuitBreakerEvaluationResult,
    HardenedSharedMarginAccount,
)

logger = logging.getLogger(__name__)

DEFAULT_NOMINAL_ATRS: Final[dict[str, Decimal]] = {
    "BTCUSDT": Decimal("100.0"),
    "ETHUSDT": Decimal("5.0"),
    "SOLUSDT": Decimal("0.5"),
    "DOGEUSDT": Decimal("0.001"),
}
DEFAULT_FALLBACK_ATR: Final[Decimal] = Decimal("1.0")


class CircuitBreakerFeedMonitor:
    """Decoupled asynchronous monitor feeding live ticks and bars into circuit breakers.

    Uses an internal asyncio.Queue to guarantee that high-frequency WebSocket
    ingestion is never blocked or delayed by circuit breaker evaluation.
    """

    def __init__(
        self,
        account: HardenedSharedMarginAccount,
        symbol: str = "BTCUSDT",
        symbols: tuple[str, ...] | None = None,
        baseline_atrs: Mapping[str, Decimal] | None = None,
        max_queue_size: int = 10_000,
        evaluate_on_ticker: bool = True,
        slippage_surge_eval_only: bool = False,
    ) -> None:
        self.account = account
        self.symbols: tuple[str, ...] = tuple(s.upper() for s in (symbols or (symbol,)))
        self.max_queue_size = max_queue_size
        self.evaluate_on_ticker = evaluate_on_ticker
        self.slippage_surge_eval_only = slippage_surge_eval_only

        # Baseline and rolling ATR store
        self._baseline_atrs: dict[str, Decimal] = {
            s: (
                baseline_atrs.get(s, DEFAULT_NOMINAL_ATRS.get(s, DEFAULT_FALLBACK_ATR))
                if baseline_atrs
                else DEFAULT_NOMINAL_ATRS.get(s, DEFAULT_FALLBACK_ATR)
            )
            for s in self.symbols
        }
        self._rolling_atrs: dict[str, Decimal] = dict(self._baseline_atrs)

        # Bar history and True Range tracking per symbol
        self._true_ranges: dict[str, deque[Decimal]] = {
            s: deque(maxlen=self.account.config.baseline_window_bars) for s in self.symbols
        }
        self._last_closed_bars: dict[str, CanonicalBar] = {}

        # Real-time state caches
        self._latest_slippage_bps: dict[str, Decimal] = {s: Decimal("0") for s in self.symbols}
        self._latest_mid_prices: dict[str, Decimal] = {}
        self._latest_evaluations: dict[str, CircuitBreakerEvaluationResult] = {}

        # Asynchronous worker queue and concurrency state
        self._queue: asyncio.Queue[TickerSnapshot | CanonicalBar | None] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._stopping: bool = False
        self._enqueued_count: int = 0
        self._processed_count: int = 0
        self._dropped_count: int = 0
        self._max_observed_queue_depth: int = 0

    @property
    def queue(self) -> asyncio.Queue[TickerSnapshot | CanonicalBar | None]:
        """Access internal worker queue."""
        return self._queue

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def enqueued_count(self) -> int:
        return self._enqueued_count

    @property
    def processed_count(self) -> int:
        return self._processed_count

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    @property
    def max_observed_queue_depth(self) -> int:
        return self._max_observed_queue_depth

    @property
    def current_state(self) -> str:
        return self.account.current_state

    @property
    def state_history(self) -> list[tuple[datetime, str, str]]:
        return list(self.account.state_history)

    async def push_ticker(self, ticker: TickerSnapshot) -> None:
        """Enqueue incoming ticker snapshot without blocking WebSocket read loop."""
        if self._stopping:
            return
        self._enqueued_count += 1
        depth = self._queue.qsize() + 1
        if depth > self._max_observed_queue_depth:
            self._max_observed_queue_depth = depth

        try:
            self._queue.put_nowait(ticker)
        except asyncio.QueueFull:
            self._dropped_count += 1
            logger.warning("Worker queue full, ticker dropped for %s", ticker.symbol)

    async def push_bar(self, bar: CanonicalBar) -> None:
        """Enqueue incoming canonical bar."""
        if self._stopping:
            return
        self._enqueued_count += 1
        depth = self._queue.qsize() + 1
        if depth > self._max_observed_queue_depth:
            self._max_observed_queue_depth = depth

        try:
            self._queue.put_nowait(bar)
        except asyncio.QueueFull:
            # For bars, wait for queue space to ensure zero bar loss
            await self._queue.put(bar)

    async def start(self) -> None:
        """Launch background worker task."""
        if self._worker_task is None or self._worker_task.done():
            self._stopping = False
            self._worker_task = asyncio.create_task(
                self.process_loop(), name="cb_feed_monitor_worker"
            )

    async def stop(self) -> None:
        """Signal clean termination, drain remaining queue items, and await worker."""
        if self._stopping:
            return
        self._stopping = True
        await self._queue.put(None)
        if self._worker_task is not None:
            await self._worker_task
            self._worker_task = None

    async def process_single_queue_item(self) -> None:
        """Process exactly one queue item (convenience helper for unit testing)."""
        if self._queue.empty():
            return
        item = await self._queue.get()
        if item is None:
            self._queue.task_done()
            return
        try:
            if isinstance(item, TickerSnapshot):
                self._process_ticker(item)
            elif isinstance(item, CanonicalBar):
                self._process_bar(item)
            self._processed_count += 1
        except Exception as exc:
            logger.error("Error processing queue item: %s", exc)
        finally:
            self._queue.task_done()

    async def process_loop(self) -> None:
        """Continuous consumer loop dequeuing items and evaluating risk rules."""
        while True:
            item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            try:
                if isinstance(item, TickerSnapshot):
                    self._process_ticker(item)
                elif isinstance(item, CanonicalBar):
                    self._process_bar(item)
                self._processed_count += 1
            except Exception as exc:
                logger.error("Error processing feed event: %s", exc)
            finally:
                self._queue.task_done()

    def _process_ticker(self, ticker: TickerSnapshot) -> None:
        """Process ticker snapshot, update slippage, and trigger evaluation on stress."""
        symbol = ticker.symbol
        if symbol not in self.symbols:
            return

        slip_bps = max(Decimal("0"), ticker.spread_bps)
        self._latest_slippage_bps[symbol] = slip_bps
        self._latest_mid_prices[symbol] = ticker.mid_price

        should_eval = False
        if self.evaluate_on_ticker:
            if self.slippage_surge_eval_only:
                if slip_bps >= self.account.config.slippage_throttle_bps:
                    should_eval = True
            else:
                should_eval = True

        if should_eval:
            self._evaluate(symbol=symbol, event_ts=ticker.event_time, adverse_wick_pct=Decimal("0"))

    def _process_bar(self, bar: CanonicalBar) -> None:
        """Process canonical bar: update ATR and evaluate risk rules on closed bar."""
        symbol = bar.symbol
        if symbol not in self.symbols:
            return

        # Forming (in-progress) bars do not trigger finalized candle circuit evaluations
        if not bar.is_closed:
            return

        open_p = bar.open
        high_p = bar.high
        low_p = bar.low

        adverse_wick = (
            max((high_p - open_p) / open_p, (open_p - low_p) / open_p)
            if open_p > Decimal("0")
            else Decimal("0")
        )

        prev_bar = self._last_closed_bars.get(symbol)
        if prev_bar is not None:
            prev_c = prev_bar.close
            tr = max(high_p - low_p, abs(high_p - prev_c), abs(low_p - prev_c))
        else:
            tr = high_p - low_p

        self._true_ranges[symbol].append(tr)
        self._last_closed_bars[symbol] = bar

        lookback = self.account.config.atr_lookback
        trs = self._true_ranges[symbol]
        k = len(trs)
        if k >= lookback:
            recent = list(trs)[-lookback:]
            self._rolling_atrs[symbol] = sum(recent, Decimal("0")) / Decimal(str(lookback))
        elif k > 0:
            base = self._baseline_atrs[symbol]
            self._rolling_atrs[symbol] = (
                sum(trs, Decimal("0")) + Decimal(str(lookback - k)) * base
            ) / Decimal(str(lookback))

        self._evaluate(symbol=symbol, event_ts=bar.close_time, adverse_wick_pct=adverse_wick)

    def _evaluate(self, symbol: str, event_ts: datetime, adverse_wick_pct: Decimal) -> None:
        """Invoke evaluate_circuit_breaker on HardenedSharedMarginAccount."""
        cur_atr = self._rolling_atrs.get(symbol, DEFAULT_FALLBACK_ATR)
        base_atr = self._baseline_atrs.get(symbol, DEFAULT_FALLBACK_ATR)
        if cur_atr <= Decimal("0"):
            cur_atr = DEFAULT_FALLBACK_ATR
        if base_atr <= Decimal("0"):
            base_atr = DEFAULT_FALLBACK_ATR

        slip_bps = max(Decimal("0"), self._latest_slippage_bps.get(symbol, Decimal("0")))
        equity = self.account.current_equity()
        peak = self.account.peak_portfolio_equity

        bar_ts = (
            event_ts.astimezone(UTC)
            if event_ts.tzinfo is not None
            else event_ts.replace(tzinfo=UTC)
        )

        eval_res = self.account.evaluate_circuit_breaker(
            symbol=symbol,
            current_atr=cur_atr,
            baseline_atr=base_atr,
            current_slippage_bps=slip_bps,
            current_equity=equity,
            peak_equity=peak,
            bar_ts=bar_ts,
            adverse_wick_pct=adverse_wick_pct,
        )
        self._latest_evaluations[symbol] = eval_res

    def get_latest_evaluation(self, symbol: str) -> CircuitBreakerEvaluationResult | None:
        """Return most recent evaluation for given symbol."""
        return self._latest_evaluations.get(symbol)

    def get_all_evaluations(self) -> dict[str, CircuitBreakerEvaluationResult]:
        """Return map of all current evaluations."""
        return dict(self._latest_evaluations)
