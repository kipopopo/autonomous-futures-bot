"""Phase 317 Milestone 2: Multi-Timeframe Candle Ring Buffer & Ingress Sequencer.

Manages 40 rolling candle ring buffers (collections.deque(maxlen=150)) across 8 active pairs
(BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX) and 5 timeframes (4h, 1h, 15m, 5m, 1m).
Features:
- Exact Decimal precision Candle objects with integer timestamp_ms.
- Smart hierarchical TTL refresh schedule: 4h (3600s), 1h (900s), 15m (300s), 5m (60s), 1m (15s).
- Concurrency throttling with asyncio.Semaphore(5).
- Dual-gateway public REST fallback to https://fapi.binance.com/fapi/v1/klines.
- 2-tier chronological gap padding via ChronologicalCandleSynchronizer.
- Exposes refresh_all(), refresh_due_candles(), and get_multi_tf_candles(symbol).
"""

from __future__ import annotations

import asyncio
import collections
import logging
import sys
import time
from collections.abc import Sequence
from typing import Any, Final

import httpx

from autonomous_futures.feed.kline_parser import parse_raw_kline
from autonomous_futures.feed.kline_synchronizer import ChronologicalCandleSynchronizer
from autonomous_futures.strategy.ict_mmxm import Candle

logger = logging.getLogger("autonomous_futures.feed.kline_sequencer")

BINANCE_PUBLIC_REST_BASE: Final[str] = "https://fapi.binance.com"

ACTIVE_PAIRS: Final[tuple[str, ...]] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "LINKUSDT",
    "APTUSDT",
    "ADAUSDT",
)

ACTIVE_TIMEFRAMES: Final[tuple[str, ...]] = ("4h", "1h", "15m", "5m", "1m")

TTL_SECONDS: Final[dict[str, float]] = {
    "4h": 3600.0,
    "1h": 900.0,
    "15m": 300.0,
    "5m": 60.0,
    "1m": 15.0,
}


class MultiTimeframeCandleSequencer:
    """High-performance, memory-bounded candle sequencer across 8 pairs and 5 horizons."""

    def __init__(
        self,
        gateway: Any | None = None,
        symbols: Sequence[str] = ACTIVE_PAIRS,
        timeframes: Sequence[str] = ACTIVE_TIMEFRAMES,
        max_buffer_bars: int = 250,
        concurrency_limit: int = 5,
        synchronizer: ChronologicalCandleSynchronizer | None = None,
    ) -> None:
        self.gateway = gateway
        self.symbols: tuple[str, ...] = tuple(s.upper() for s in symbols)
        self.timeframes: tuple[str, ...] = tuple(timeframes)
        self.max_buffer_bars: int = max_buffer_bars
        self.concurrency_limit: int = concurrency_limit
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(concurrency_limit)
        self.synchronizer: ChronologicalCandleSynchronizer = (
            synchronizer or ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        )

        # 40 Rolling Ring Buffers: (symbol, timeframe) -> deque[Candle]
        self.buffers: dict[tuple[str, str], collections.deque[Candle]] = {
            (sym, tf): collections.deque(maxlen=max_buffer_bars)
            for sym in self.symbols
            for tf in self.timeframes
        }
        # Last fetch timestamp: (symbol, timeframe) -> float
        self.series_quality: dict[tuple[str, str], bool] = {}
        self.last_fetch_ts: dict[tuple[str, str], float] = {
            (sym, tf): 0.0 for sym in self.symbols for tf in self.timeframes
        }

    def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        """Returns snapshot of current buffer as a list."""
        buf = self.buffers.get((symbol.upper(), timeframe))
        return list(buf) if buf is not None else []

    def get_multi_tf_candles(
        self, symbol: str
    ) -> tuple[list[Candle], list[Candle], list[Candle], list[Candle], list[Candle]]:
        """Returns (4h, 1h, 15m, 5m, 1m) candle sequences for ICT MMXM evaluation."""
        sym = symbol.upper()
        return (
            self.get_candles(sym, "4h"),
            self.get_candles(sym, "1h"),
            self.get_candles(sym, "15m"),
            self.get_candles(sym, "5m"),
            self.get_candles(sym, "1m"),
        )

    def get_multi_timeframe_candles(
        self, symbol: str
    ) -> tuple[list[Candle], list[Candle], list[Candle], list[Candle], list[Candle]]:
        """Alias for get_multi_tf_candles."""
        return self.get_multi_tf_candles(symbol)

    def get_all_timeframes(self, symbol: str) -> dict[str, list[Candle]]:
        """Returns mapping of all timeframes to candle sequences for given symbol."""
        sym = symbol.upper()
        return {tf: self.get_candles(sym, tf) for tf in self.timeframes}

    def is_cache_expired(self, symbol: str, timeframe: str, now_ts: float) -> bool:
        """Checks if hierarchical TTL has expired for the given series."""
        sym = symbol.upper()
        last_ts = self.last_fetch_ts.get((sym, timeframe), 0.0)
        ttl = TTL_SECONDS.get(timeframe, 60.0)
        buf = self.buffers.get((sym, timeframe))
        return (now_ts - last_ts) >= ttl or (buf is not None and len(buf) == 0)

    def is_trade_ready(self, symbol: str, now_ts: float | None = None) -> bool:
        """Every horizon must be fresh, closed and free of repaired/unrepaired gaps."""
        now = time.time() if now_ts is None else now_ts
        for tf in self.timeframes:
            key = (symbol.upper(), tf)
            candles = self.get_candles(symbol, tf)
            duration = self.synchronizer.get_interval_ms(tf)
            if (
                not candles
                or not self.series_quality.get(key, False)
                or now - self.last_fetch_ts[key] > TTL_SECONDS[tf] + 15
                or now * 1000 - (candles[-1].timestamp_ms + duration)
                > (TTL_SECONDS[tf] + 15) * 1000
            ):
                return False
        return True

    def is_warmed_up(self, symbol: str, min_bars: int = 10) -> bool:
        """Asserts whether all 5 horizons have sufficient bars for strategy evaluation."""
        sym = symbol.upper()
        return all(len(self.buffers.get((sym, tf), [])) >= min_bars for tf in self.timeframes)

    def total_memory_bytes(self) -> int:
        """Calculates deep approximate heap footprint across all buffers."""
        total = sys.getsizeof(self.buffers)
        for b in self.buffers.values():
            total += sys.getsizeof(b)
            for item in b:
                total += sys.getsizeof(item)
                total += sys.getsizeof(item.open)
        return total

    async def _fetch_public_fallback(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[list[Any]]:
        """Zero-auth fallback directly to Binance Live REST endpoint."""
        base = getattr(self.gateway, "rest_base", BINANCE_PUBLIC_REST_BASE)
        if not isinstance(base, str):
            base = BINANCE_PUBLIC_REST_BASE
        url = f"{base}/fapi/v1/klines"
        params: dict[str, str | int] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1000),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError("Expected list from public klines")
            return data

    async def fetch_and_update_series(
        self,
        symbol: str,
        interval: str,
        limit: int = 250,
        now_ts: float | None = None,
    ) -> None:
        """Fetches, parses, synchronizes, and appends candles under semaphore control."""
        sym = symbol.upper()
        async with self.semaphore:
            raw_klines: list[list[Any]] | None = None
            if self.gateway is not None and hasattr(self.gateway, "get_klines"):
                try:
                    raw_klines = await self.gateway.get_klines(sym, interval=interval, limit=limit)
                except Exception as primary_err:
                    logger.warning(
                        "Primary gateway failed for %s %s: %s; invoking public fallback",
                        sym,
                        interval,
                        primary_err,
                    )
                    try:
                        raw_klines = await self._fetch_public_fallback(sym, interval, limit)
                    except Exception as fallback_err:
                        logger.error(
                            "Public fallback failed for %s %s: %s; retaining stale buffer",
                            sym,
                            interval,
                            fallback_err,
                        )
                        return
            else:
                try:
                    raw_klines = await self._fetch_public_fallback(sym, interval, limit)
                except Exception as fallback_err:
                    logger.error(
                        "Public fetch failed for %s %s: %s; retaining stale buffer",
                        sym,
                        interval,
                        fallback_err,
                    )
                    return

            if not raw_klines:
                return

            try:
                cutoff_ms = int((now_ts if now_ts is not None else time.time()) * 1000)
                interval_ms = self.synchronizer.get_interval_ms(interval)
                parsed = [
                    parse_raw_kline(r) for r in raw_klines if int(r[0]) + interval_ms <= cutoff_ms
                ]
            except Exception as parse_err:
                logger.warning(
                    "Failed parsing raw klines for %s %s: %s",
                    sym,
                    interval,
                    parse_err,
                )
                return

            if not parsed:
                return
            existing = list(self.buffers.get((sym, interval), []))
            combined = existing + parsed
            synced = self.synchronizer.synchronize(sym, interval, combined)

            self.series_quality[(sym, interval)] = not (
                synced.has_unrepaired_gap or synced.bars_interpolated
            )
            buf = self.buffers.get((sym, interval))
            if buf is not None:
                buf.clear()
                buf.extend(synced.candles[-self.max_buffer_bars :])
            self.last_fetch_ts[(sym, interval)] = now_ts if now_ts is not None else time.time()

    async def refresh_due_candles(self, now_ts: float | None = None) -> int:
        """Refreshes all series whose TTL has expired concurrently."""
        current_time = now_ts if now_ts is not None else time.time()
        tasks = []
        for sym in self.symbols:
            for tf in self.timeframes:
                if self.is_cache_expired(sym, tf, current_time):
                    tasks.append(self.fetch_and_update_series(sym, tf, now_ts=current_time))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    async def refresh_all(self, force: bool = False, now_ts: float | None = None) -> int:
        """Refreshes streams. If force is True, all 40 streams are refreshed unconditionally."""
        current_time = now_ts if now_ts is not None else time.time()
        if force:
            tasks = [
                self.fetch_and_update_series(sym, tf, now_ts=current_time)
                for sym in self.symbols
                for tf in self.timeframes
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            return len(tasks)
        return await self.refresh_due_candles(now_ts=current_time)

    async def warmup(self, now_ts: float | None = None) -> int:
        """Cold-starts all 40 streams by refreshing all series unconditionally."""
        return await self.refresh_all(force=True, now_ts=now_ts)
