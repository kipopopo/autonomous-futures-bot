"""Phase 257: Feed Telemetry Accumulator.

Captures network ingestion latency, message throughput, tick counts,
and bid-ask spread stability metrics in thread-safe data structures.
"""

from __future__ import annotations

import math
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot


def _compute_float_percentile(sorted_vals: list[float], p: float) -> float:
    """Compute percentile from sorted float list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * (p / 100.0)
    low = int(idx)
    high = low + 1
    if high >= len(sorted_vals):
        return sorted_vals[-1]
    weight = idx - low
    return sorted_vals[low] + weight * (sorted_vals[high] - sorted_vals[low])


def _compute_decimal_percentile(sorted_vals: list[Decimal], p: float) -> Decimal:
    """Compute percentile from sorted Decimal list."""
    if not sorted_vals:
        return Decimal("0")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    p_dec = Decimal(str(p)) / Decimal("100")
    idx = Decimal(len(sorted_vals) - 1) * p_dec
    low = int(idx)
    high = low + 1
    if high >= len(sorted_vals):
        return sorted_vals[-1]
    weight = idx - Decimal(low)
    return sorted_vals[low] + weight * (sorted_vals[high] - sorted_vals[low])


@dataclass(slots=True, frozen=True)
class LatencyMetrics:
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    std_dev_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "min_ms": round(self.min_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
            "std_dev_ms": round(self.std_dev_ms, 3),
        }


@dataclass(slots=True, frozen=True)
class SpreadMetrics:
    count: int
    mean_bps: Decimal
    std_bps: Decimal
    min_bps: Decimal
    max_bps: Decimal
    p50_bps: Decimal
    p95_bps: Decimal
    p99_bps: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean_bps": str(self.mean_bps),
            "std_bps": str(self.std_bps),
            "min_bps": str(self.min_bps),
            "max_bps": str(self.max_bps),
            "p50_bps": str(self.p50_bps),
            "p95_bps": str(self.p95_bps),
            "p99_bps": str(self.p99_bps),
        }


@dataclass(slots=True, frozen=True)
class FeedTelemetrySnapshot:
    total_messages: int
    duration_seconds: float
    throughput_msg_per_sec: float
    latency_overall: LatencyMetrics
    latency_by_stream: dict[str, LatencyMetrics]
    latency_by_symbol: dict[str, LatencyMetrics]
    spread_by_symbol: dict[str, SpreadMetrics]
    message_counts_by_stream: dict[str, int]
    message_counts_by_symbol: dict[str, int]
    error_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_messages": self.total_messages,
            "duration_seconds": round(self.duration_seconds, 3),
            "throughput_msg_per_sec": round(self.throughput_msg_per_sec, 2),
            "latency_overall": self.latency_overall.to_dict(),
            "latency_by_stream": {k: v.to_dict() for k, v in self.latency_by_stream.items()},
            "latency_by_symbol": {k: v.to_dict() for k, v in self.latency_by_symbol.items()},
            "spread_by_symbol": {k: v.to_dict() for k, v in self.spread_by_symbol.items()},
            "message_counts_by_stream": dict(self.message_counts_by_stream),
            "message_counts_by_symbol": dict(self.message_counts_by_symbol),
            "error_count": self.error_count,
        }


class FeedTelemetryAccumulator:
    """Thread-safe in-memory metrics accumulator for WebSocket feed latency and spreads."""

    def __init__(self, symbols: tuple[str, ...] | None = None) -> None:
        self._lock = threading.Lock()
        self.monitored_symbols = tuple(s.upper() for s in symbols) if symbols else ()
        self._start_monotonic: float = 0.0
        self._end_monotonic: float = 0.0
        self._latencies_overall: list[float] = []
        self._latencies_by_stream: dict[str, list[float]] = defaultdict(list)
        self._latencies_by_symbol: dict[str, list[float]] = defaultdict(list)
        self._spreads_by_symbol: dict[str, list[Decimal]] = defaultdict(list)
        self._counts_by_stream: Counter[str] = Counter()
        self._counts_by_symbol: Counter[str] = Counter()
        self._book_ticker_counts: Counter[str] = Counter()
        self._kline_counts: Counter[str] = Counter()
        self._latest_mid_prices: dict[str, Decimal] = {}
        self._latest_spread_bps: dict[str, Decimal] = {}
        self._error_count: int = 0

    def start(self) -> None:
        with self._lock:
            if self._start_monotonic == 0.0:
                self._start_monotonic = time.monotonic()
            self._end_monotonic = 0.0

    def stop(self) -> None:
        with self._lock:
            self._end_monotonic = time.monotonic()

    def record_message(
        self,
        stream: str,
        symbol: str,
        event_time_ms: int,
        vps_received_time_ms: float,
    ) -> float:
        """Record an incoming message timestamp and compute latency."""
        delta_t_ms = max(0.0, vps_received_time_ms - float(event_time_ms))
        with self._lock:
            self._latencies_overall.append(delta_t_ms)
            if stream:
                self._latencies_by_stream[stream].append(delta_t_ms)
                self._counts_by_stream[stream] += 1
            if symbol:
                sym = symbol.upper()
                self._latencies_by_symbol[sym].append(delta_t_ms)
                self._counts_by_symbol[sym] += 1
        return delta_t_ms

    def record_spread(self, symbol: str, spread_bps: Decimal) -> None:
        """Record bid-ask spread stability observation in strict Decimal."""
        with self._lock:
            sym = symbol.upper()
            self._spreads_by_symbol[sym].append(spread_bps)
            self._latest_spread_bps[sym] = spread_bps

    def record_ticker(
        self,
        ticker: TickerSnapshot,
        recv_ns: int | None = None,
        record_latency: bool = True,
    ) -> float:
        """Convenience method to record a TickerSnapshot.

        If record_latency is True (default for standalone calls), records wire latency
        via record_message. Set record_latency=False when wire arrival latency has
        already been recorded at frame ingress.
        """
        vps_ms = (recv_ns / 1_000_000.0) if recv_ns is not None else (time.time() * 1000.0)
        event_ms = int(ticker.event_time.timestamp() * 1000.0)
        stream_name = f"{ticker.symbol.lower()}@bookTicker"
        with self._lock:
            self._book_ticker_counts[ticker.symbol] += 1
            self._latest_mid_prices[ticker.symbol] = ticker.mid_price
        self.record_spread(ticker.symbol, ticker.spread_bps)
        if record_latency:
            return self.record_message(
                stream=stream_name,
                symbol=ticker.symbol,
                event_time_ms=event_ms,
                vps_received_time_ms=vps_ms,
            )
        return max(0.0, vps_ms - float(event_ms))

    def record_bar(
        self,
        bar: CanonicalBar,
        recv_ns: int | None = None,
        record_latency: bool = True,
    ) -> float:
        """Convenience method to record a CanonicalBar.

        If record_latency is True (default for standalone calls), records wire latency
        via record_message. Set record_latency=False when wire arrival latency has
        already been recorded at frame ingress.
        """
        vps_ms = (recv_ns / 1_000_000.0) if recv_ns is not None else (time.time() * 1000.0)
        event_ms = int(bar.close_time.timestamp() * 1000.0)
        stream_name = f"{bar.symbol.lower()}@kline_{bar.interval}"
        with self._lock:
            self._kline_counts[bar.symbol] += 1
        if record_latency:
            return self.record_message(
                stream=stream_name,
                symbol=bar.symbol,
                event_time_ms=event_ms,
                vps_received_time_ms=vps_ms,
            )
        return max(0.0, vps_ms - float(event_ms))

    def record_error(self) -> None:
        with self._lock:
            self._error_count += 1

    def _summarize_latencies(self, latencies: list[float]) -> LatencyMetrics:
        if not latencies:
            return LatencyMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        sorted_l = sorted(latencies)
        count = len(sorted_l)
        mean_l = sum(sorted_l) / count
        variance = sum((x - mean_l) ** 2 for x in sorted_l) / count
        std_dev = math.sqrt(variance)
        return LatencyMetrics(
            count=count,
            p50_ms=_compute_float_percentile(sorted_l, 50.0),
            p95_ms=_compute_float_percentile(sorted_l, 95.0),
            p99_ms=_compute_float_percentile(sorted_l, 99.0),
            min_ms=sorted_l[0],
            max_ms=sorted_l[-1],
            mean_ms=mean_l,
            std_dev_ms=std_dev,
        )

    def _summarize_spreads(self, spreads: list[Decimal]) -> SpreadMetrics:
        if not spreads:
            return SpreadMetrics(
                0,
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
            )
        sorted_s = sorted(spreads)
        count = len(sorted_s)
        mean_bps = sum(sorted_s, Decimal("0")) / Decimal(count)
        variance = sum(((s - mean_bps) ** 2 for s in sorted_s), Decimal("0")) / Decimal(count)
        std_bps = variance.sqrt()
        return SpreadMetrics(
            count=count,
            mean_bps=mean_bps,
            std_bps=std_bps,
            min_bps=sorted_s[0],
            max_bps=sorted_s[-1],
            p50_bps=_compute_decimal_percentile(sorted_s, 50.0),
            p95_bps=_compute_decimal_percentile(sorted_s, 95.0),
            p99_bps=_compute_decimal_percentile(sorted_s, 99.0),
        )

    def snapshot(self) -> FeedTelemetrySnapshot:
        """Generate point-in-time summary metrics snapshot."""
        with self._lock:
            end_t = self._end_monotonic if self._end_monotonic > 0 else time.monotonic()
            duration = (
                max(0.001, end_t - self._start_monotonic) if self._start_monotonic > 0 else 0.001
            )
            total_msgs = len(self._latencies_overall)
            throughput = total_msgs / duration

            lat_overall_data = list(self._latencies_overall)
            lat_stream_data = {k: list(v) for k, v in self._latencies_by_stream.items()}
            lat_symbol_data = {k: list(v) for k, v in self._latencies_by_symbol.items()}
            spread_symbol_data = {k: list(v) for k, v in self._spreads_by_symbol.items()}
            counts_stream = dict(self._counts_by_stream)
            counts_symbol = dict(self._counts_by_symbol)
            err_count = self._error_count

        lat_overall = self._summarize_latencies(lat_overall_data)
        lat_stream = {k: self._summarize_latencies(v) for k, v in lat_stream_data.items()}
        lat_symbol = {k: self._summarize_latencies(v) for k, v in lat_symbol_data.items()}
        spread_symbol = {k: self._summarize_spreads(v) for k, v in spread_symbol_data.items()}

        return FeedTelemetrySnapshot(
            total_messages=total_msgs,
            duration_seconds=duration,
            throughput_msg_per_sec=throughput,
            latency_overall=lat_overall,
            latency_by_stream=lat_stream,
            latency_by_symbol=lat_symbol,
            spread_by_symbol=spread_symbol,
            message_counts_by_stream=counts_stream,
            message_counts_by_symbol=counts_symbol,
            error_count=err_count,
        )

    def compile_summary(self, elapsed_seconds: float) -> dict[str, Any]:
        """Generate full summary dictionary matching probe schema."""
        with self._lock:
            total_msgs = len(self._latencies_overall)
            dur = max(0.001, elapsed_seconds)
            throughput = total_msgs / dur

            lat_overall_data = list(self._latencies_overall)
            lat_symbol_data = {k: list(v) for k, v in self._latencies_by_symbol.items()}
            spread_symbol_data = {k: list(v) for k, v in self._spreads_by_symbol.items()}
            all_symbols = set(self._counts_by_symbol.keys())
            if self.monitored_symbols:
                all_symbols.update(self.monitored_symbols)
            counts_by_symbol = dict(self._counts_by_symbol)
            book_ticker_counts = dict(self._book_ticker_counts)
            kline_counts = dict(self._kline_counts)
            latest_mid_prices = dict(self._latest_mid_prices)
            latest_spread_bps = dict(self._latest_spread_bps)

        lat_overall = self._summarize_latencies(lat_overall_data)
        overall_lat_dict = {
            "min": round(lat_overall.min_ms, 2),
            "p50": round(lat_overall.p50_ms, 2),
            "p95": round(lat_overall.p95_ms, 2),
            "p99": round(lat_overall.p99_ms, 2),
            "max": round(lat_overall.max_ms, 2),
            "mean": round(lat_overall.mean_ms, 2),
            "std_dev": round(lat_overall.std_dev_ms, 2),
        }

        by_symbol: dict[str, Any] = {}
        symbol_breakdown: dict[str, Any] = {}
        spread_stability: dict[str, Any] = {}

        for sym in sorted(all_symbols):
            lat = self._summarize_latencies(lat_symbol_data.get(sym, []))
            spread = self._summarize_spreads(spread_symbol_data.get(sym, []))
            bt_cnt = book_ticker_counts.get(sym, 0)
            kl_cnt = kline_counts.get(sym, 0)
            tot_cnt = counts_by_symbol.get(sym, bt_cnt + kl_cnt)

            by_symbol[sym] = {
                "book_ticker_count": bt_cnt,
                "kline_count": kl_cnt,
                "total_count": tot_cnt,
                "latency_ms": {
                    "min": round(lat.min_ms, 2),
                    "p50": round(lat.p50_ms, 2),
                    "p95": round(lat.p95_ms, 2),
                    "p99": round(lat.p99_ms, 2),
                    "max": round(lat.max_ms, 2),
                    "mean": round(lat.mean_ms, 2),
                    "std_dev": round(lat.std_dev_ms, 2),
                },
                "spread_bps": {
                    "min": round(float(spread.min_bps), 4),
                    "p50": round(float(spread.p50_bps), 4),
                    "p95": round(float(spread.p95_bps), 4),
                    "p99": round(float(spread.p99_bps), 4),
                    "max": round(float(spread.max_bps), 4),
                    "mean": round(float(spread.mean_bps), 4),
                    "std_dev": round(float(spread.std_bps), 4),
                },
                "latest_mid_price": str(latest_mid_prices.get(sym, Decimal("0"))),
                "latest_spread_bps": str(round(float(latest_spread_bps.get(sym, Decimal("0"))), 4)),
            }

            symbol_breakdown[sym] = {
                "bookTicker": bt_cnt,
                "kline_5m": kl_cnt,
                "total": tot_cnt,
            }

            spread_stability[sym] = {
                "mean_spread_bps": round(float(spread.mean_bps), 4),
                "std_spread_bps": round(float(spread.std_bps), 4),
                "min_spread_bps": round(float(spread.min_bps), 4),
                "max_spread_bps": round(float(spread.max_bps), 4),
                "sample_count": spread.count,
            }

        return {
            "total_messages_received": total_msgs,
            "total_throughput_msgs_per_sec": round(throughput, 2),
            "throughput_msgs_per_sec": round(throughput, 2),
            "latency_ms": overall_lat_dict,
            "ingestion_latency_ms": overall_lat_dict,
            "by_symbol": by_symbol,
            "symbol_breakdown": symbol_breakdown,
            "spread_stability": spread_stability,
        }
