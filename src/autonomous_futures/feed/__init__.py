"""Phase 257: Live Market Read-Only WebSocket Feed Ingestion Module."""

from autonomous_futures.feed.client import BinancePublicFeedClient
from autonomous_futures.feed.models import (
    CanonicalBar,
    TickerSnapshot,
    ms_to_utc_datetime,
    parse_binance_book_ticker,
    parse_binance_kline,
)
from autonomous_futures.feed.monitor import CircuitBreakerFeedMonitor
from autonomous_futures.feed.telemetry import (
    FeedTelemetryAccumulator,
    FeedTelemetrySnapshot,
    LatencyMetrics,
    SpreadMetrics,
)

__all__ = [
    "BinancePublicFeedClient",
    "CanonicalBar",
    "CircuitBreakerFeedMonitor",
    "FeedTelemetryAccumulator",
    "FeedTelemetrySnapshot",
    "LatencyMetrics",
    "SpreadMetrics",
    "TickerSnapshot",
    "ms_to_utc_datetime",
    "parse_binance_book_ticker",
    "parse_binance_kline",
]
