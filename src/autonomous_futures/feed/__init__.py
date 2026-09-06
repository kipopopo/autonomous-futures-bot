"""Phase 257 & Phase 261: Binance Futures Feed Ingestion & REST Kline Client Module."""

from autonomous_futures.feed.client import BinancePublicFeedClient
from autonomous_futures.feed.models import (
    CanonicalBar,
    TickerSnapshot,
    ms_to_utc_datetime,
    parse_binance_book_ticker,
    parse_binance_kline,
)
from autonomous_futures.feed.monitor import CircuitBreakerFeedMonitor
from autonomous_futures.feed.rest_client import (
    BinanceDataQualityError,
    BinanceHttpError,
    BinanceNetworkError,
    BinancePublicRestClient,
    BinanceRateLimitError,
    BinanceRestError,
    BinanceSecurityViolation,
    BinanceTimeoutError,
    calculate_closed_bar_boundary,
    fetch_binance_futures_klines,
    fetch_klines_with_fallback,
    fetch_warmup_bars_with_fallback,
    generate_deterministic_synthetic_bars,
    load_parquet_warmup_bars,
    parse_raw_kline_to_canonical_bar,
    parse_raw_klines_to_canonical_bars,
    parse_raw_klines_to_canonical_df,
    validate_canonical_dataframe,
)
from autonomous_futures.feed.telemetry import (
    FeedTelemetryAccumulator,
    FeedTelemetrySnapshot,
    LatencyMetrics,
    SpreadMetrics,
)

__all__ = [
    "BinanceDataQualityError",
    "BinanceHttpError",
    "BinanceNetworkError",
    "BinancePublicFeedClient",
    "BinancePublicRestClient",
    "BinanceRateLimitError",
    "BinanceRestError",
    "BinanceSecurityViolation",
    "BinanceTimeoutError",
    "CanonicalBar",
    "CircuitBreakerFeedMonitor",
    "FeedTelemetryAccumulator",
    "FeedTelemetrySnapshot",
    "LatencyMetrics",
    "SpreadMetrics",
    "TickerSnapshot",
    "calculate_closed_bar_boundary",
    "fetch_binance_futures_klines",
    "fetch_klines_with_fallback",
    "fetch_warmup_bars_with_fallback",
    "generate_deterministic_synthetic_bars",
    "load_parquet_warmup_bars",
    "ms_to_utc_datetime",
    "parse_binance_book_ticker",
    "parse_binance_kline",
    "parse_raw_kline_to_canonical_bar",
    "parse_raw_klines_to_canonical_bars",
    "parse_raw_klines_to_canonical_df",
    "validate_canonical_dataframe",
]
