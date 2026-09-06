"""Phase 261: Unauthenticated Binance Futures Public REST Kline Client & Offline Fallback Cascade.

Fetches historical 5m candlestick bars from Binance Futures public REST API
(https://fapi.binance.com/fapi/v1/klines) with strict zero credentials,
automatic unclosed bar exclusion, canonical DataFrame transformation,
robust error hierarchy, and a 3-tier offline fallback cascade
(Primary REST -> Fallback 1 Local Parquet -> Fallback 2 Deterministic Synthetic).
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx
import pandas as pd

from autonomous_futures.data.quality import DataQualityError
from autonomous_futures.feed.models import CanonicalBar, ms_to_utc_datetime

logger = logging.getLogger(__name__)

DEFAULT_REST_URL: str = "https://fapi.binance.com"
DEFAULT_INTERVAL: str = "5m"
DEFAULT_WARMUP_BARS: int = 100
DEFAULT_TIMEOUT_SECONDS: float = 5.0
DEFAULT_MAX_RETRIES: int = 2
DEFAULT_BACKOFF_FACTOR: float = 0.5
INTERVAL_5M_MS: int = 300_000
DEFAULT_HISTORY_DIR: Path = Path("research/immutable-data/5m/canonical")

FORBIDDEN_AUTH_TOKENS: frozenset[str] = frozenset(
    {
        "apikey",
        "apisecret",
        "secret",
        "token",
        "password",
        "auth",
        "privatekey",
        "xmbxapikey",
        "signature",
        "authorization",
        "bearer",
        "key",
    }
)
# Maintained for backward compatibility with external callers
FORBIDDEN_AUTH_KEYS: frozenset[str] = FORBIDDEN_AUTH_TOKENS


def is_forbidden_auth_key(k: str) -> bool:
    """Check if key or header name matches any normalized forbidden authentication token.

    Converts key to lowercase and strips all non-alphanumeric characters (including
    hyphens and underscores) prior to checking against canonical forbidden roots.
    """
    norm_k = re.sub(r"[^a-z0-9]", "", k.lower())
    return any(tok in norm_k for tok in FORBIDDEN_AUTH_TOKENS)


ALLOWED_INTERVALS: frozenset[str] = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
)

SYMBOL_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z0-9]{3,20}$")

SYMBOL_BASE_PRICES: dict[str, float] = {
    "BTCUSDT": 85000.0,
    "ETHUSDT": 3100.0,
    "SOLUSDT": 180.0,
    "DOGEUSDT": 0.150,
}


# ---------------------------------------------------------------------------
# Error Hierarchy
# ---------------------------------------------------------------------------


class BinanceRestError(Exception):
    """Base exception for all Binance REST client operations."""


class BinanceSecurityViolation(BinanceRestError, ValueError):
    """Raised when authentication credentials or secret headers are improperly attempted."""


class BinanceHttpError(BinanceRestError):
    """Raised on non-2xx HTTP responses from Binance REST API."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        response_body: str | None = None,
    ) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.response_body = response_body


class BinanceRateLimitError(BinanceHttpError):
    """Raised when HTTP 429 or HTTP 418 rate limit is encountered."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        retry_after: float = 1.0,
        is_ban: bool = False,
        response_body: str | None = None,
    ) -> None:
        super().__init__(status_code, message, response_body=response_body)
        self.retry_after = retry_after
        self.is_ban = is_ban


class BinanceTimeoutError(BinanceRestError):
    """Raised when network requests exceed timeout limit across all retry attempts."""


class BinanceNetworkError(BinanceRestError):
    """Raised on connection/transport failures (DNS, connection reset, etc.)."""


class BinanceDataQualityError(BinanceRestError, DataQualityError):
    """Raised when REST kline payload violates data quality contracts."""


# ---------------------------------------------------------------------------
# Boundary Calculation & Cleanliness Validation Functions
# ---------------------------------------------------------------------------


def calculate_closed_bar_boundary(
    now_ms: int | None = None,
    interval_ms: int = INTERVAL_5M_MS,
) -> int:
    """Compute latest closed bar boundary endTime in epoch milliseconds.

    Formula: endTime = ((now_ms // interval_ms) * interval_ms) - 1.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    if now_ms < 0:
        raise ValueError(f"now_ms must be non-negative, got {now_ms}")
    if interval_ms <= 0:
        raise ValueError(f"interval_ms must be strictly positive, got {interval_ms}")
    return ((now_ms // interval_ms) * interval_ms) - 1


def interval_to_milliseconds(interval: str) -> int:
    """Convert supported interval string to duration in milliseconds."""
    if not interval:
        raise ValueError("Interval string cannot be empty")
    unit = interval[-1]
    val_str = interval[:-1]
    if not val_str.isdigit():
        raise ValueError(f"Invalid interval format: {interval!r}")
    value = int(val_str)
    if unit == "m":
        return value * 60 * 1000
    if unit == "h":
        return value * 3600 * 1000
    if unit == "d":
        return value * 86400 * 1000
    if unit == "w":
        return value * 7 * 86400 * 1000
    if unit == "M":
        return value * 30 * 86400 * 1000
    raise ValueError(f"Unsupported interval unit: {unit!r}")


def validate_canonical_dataframe(
    df: pd.DataFrame,
    expected_interval: pd.Timedelta | timedelta | None = None,
) -> None:
    """Validate canonical OHLCV DataFrame data cleanliness and schema contracts.

    Checks:
    1. Non-empty DataFrame.
    2. DatetimeIndex is UTC-aware (or 'timestamp' column is UTC-aware).
    3. Columns 'open', 'high', 'low', 'close', 'volume' exist.
    4. All OHLC values are finite and strictly positive (> 0).
    5. Volume values are finite and non-negative (>= 0).
    6. Candlestick geometric invariants: high >= low, high >= max(open, close),
       low <= min(open, close).
    7. Timestamps are strictly monotonic increasing with zero duplicate timestamps.
    8. Consecutive intervals exactly match expected_interval with zero temporal gaps.
    """
    if df.empty:
        raise BinanceDataQualityError("Canonical DataFrame must contain at least one row")

    if isinstance(df.index, pd.DatetimeIndex):
        dt_index = df.index
    elif "timestamp" in df.columns:
        ts_col = pd.to_datetime(df["timestamp"], utc=True)
        dt_index = pd.DatetimeIndex(ts_col)
    else:
        raise BinanceDataQualityError(
            "DataFrame index must be pd.DatetimeIndex or 'timestamp' column present, "
            f"got index type {type(df.index).__name__}"
        )

    if dt_index.tz is None or str(dt_index.tz) not in ("UTC", "datetime.timezone.utc"):
        raise BinanceDataQualityError("DatetimeIndex must be timezone-aware UTC")

    required_cols = ("open", "high", "low", "close", "volume")
    missing = set(required_cols).difference(df.columns)
    if missing:
        raise BinanceDataQualityError(f"Missing required OHLCV columns: {sorted(missing)}")

    for col in ("open", "high", "low", "close"):
        vals = pd.to_numeric(df[col], errors="coerce")
        if vals.isna().any() or not vals.map(math.isfinite).all():
            raise BinanceDataQualityError(f"OHLC column '{col}' contains non-finite values")
        if (vals <= 0).any():
            raise BinanceDataQualityError(
                f"OHLC column '{col}' must contain strictly positive values"
            )

    vol = pd.to_numeric(df["volume"], errors="coerce")
    if vol.isna().any() or not vol.map(math.isfinite).all():
        raise BinanceDataQualityError("Volume column contains non-finite values")
    if (vol < 0).any():
        raise BinanceDataQualityError("Volume column must contain non-negative values")

    open_s = pd.to_numeric(df["open"])
    high_s = pd.to_numeric(df["high"])
    low_s = pd.to_numeric(df["low"])
    close_s = pd.to_numeric(df["close"])

    if (high_s < low_s).any():
        bad_pos = int((high_s < low_s).to_numpy().nonzero()[0][0])
        bad_ts = dt_index[bad_pos]
        val_h = high_s.iloc[bad_pos]
        val_l = low_s.iloc[bad_pos]
        raise BinanceDataQualityError(
            f"Candle geometry error: high ({val_h}) < low ({val_l}) at {bad_ts}"
        )

    max_oc = pd.concat([open_s, close_s], axis=1).max(axis=1)
    if (high_s < max_oc).any():
        bad_pos = int((high_s < max_oc).to_numpy().nonzero()[0][0])
        bad_ts = dt_index[bad_pos]
        val_h = high_s.iloc[bad_pos]
        val_max = max_oc.iloc[bad_pos]
        raise BinanceDataQualityError(
            f"Candle geometry error: high ({val_h}) < max(open, close) ({val_max}) at {bad_ts}"
        )

    min_oc = pd.concat([open_s, close_s], axis=1).min(axis=1)
    if (low_s > min_oc).any():
        bad_pos = int((low_s > min_oc).to_numpy().nonzero()[0][0])
        bad_ts = dt_index[bad_pos]
        val_l = low_s.iloc[bad_pos]
        val_min = min_oc.iloc[bad_pos]
        raise BinanceDataQualityError(
            f"Candle geometry error: low ({val_l}) > min(open, close) ({val_min}) at {bad_ts}"
        )

    if not dt_index.is_monotonic_increasing:
        raise BinanceDataQualityError("DatetimeIndex must be monotonically increasing")
    if not dt_index.is_unique:
        raise BinanceDataQualityError("duplicate timestamps are not allowed")

    delta: pd.Timedelta
    if expected_interval is None:
        delta = pd.Timedelta(minutes=5)
    elif isinstance(expected_interval, pd.Timedelta):
        delta = expected_interval
    else:
        delta = pd.Timedelta(expected_interval)

    if len(dt_index) > 1:
        diffs = dt_index[1:] - dt_index[:-1]
        mismatches = diffs != delta
        if mismatches.any():
            bad_indices = [i for i, m in enumerate(mismatches) if m]
            bad_pos = bad_indices[0]
            expected_next = dt_index[bad_pos] + delta
            actual_next = dt_index[bad_pos + 1]
            raise BinanceDataQualityError(
                f"timestamp gap: expected {expected_next.isoformat()} but received "
                f"{actual_next.isoformat()}"
            )


# ---------------------------------------------------------------------------
# Raw Kline Parsing Functions
# ---------------------------------------------------------------------------


def parse_raw_klines_to_canonical_df(
    raw_klines: Sequence[Sequence[Any]],
    *,
    interval: str = DEFAULT_INTERVAL,
    expected_interval_ms: int | None = None,
    only_closed: bool = True,
    current_time_ms: int | None = None,
    limit: int | None = None,
    as_datetime_index: bool = True,
) -> pd.DataFrame:
    """Parse raw Binance kline arrays into strongly typed canonical OHLC DataFrame.

    Raw kline schema:
    [0] open_time (ms), [1] open, [2] high, [3] low, [4] close, [5] volume,
    [6] close_time (ms), [7] quote_volume, [8] trades, [9] taker_buy_base,
    [10] taker_buy_quote, [11] ignore
    """
    if not raw_klines:
        raise BinanceDataQualityError("Raw klines array is empty")

    now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)
    int_ms = (
        expected_interval_ms
        if expected_interval_ms is not None
        else interval_to_milliseconds(interval)
    )

    timestamps: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    for idx, row in enumerate(raw_klines):
        if len(row) < 7:
            raise BinanceDataQualityError(
                f"Invalid kline row length at index {idx}: expected >= 7, got {len(row)}"
            )

        try:
            open_time_ms = int(row[0])
            close_time_ms = int(row[6])
        except (ValueError, TypeError) as exc:
            raise BinanceDataQualityError(f"Malformed timestamp at row {idx}: {exc}") from exc

        # Exclude in-progress / unclosed bar if requested (closed only when close_time_ms < now_ms)
        if only_closed and close_time_ms >= now_ms:
            continue

        try:
            open_p = float(row[1])
            high_p = float(row[2])
            low_p = float(row[3])
            close_p = float(row[4])
            volume = float(row[5])
        except (ValueError, TypeError) as exc:
            raise BinanceDataQualityError(f"Malformed numeric value at row {idx}: {exc}") from exc

        # Value cleanliness assertions
        if not (
            math.isfinite(open_p)
            and math.isfinite(high_p)
            and math.isfinite(low_p)
            and math.isfinite(close_p)
        ):
            raise BinanceDataQualityError(f"OHLC values must be finite at row {idx}")
        if open_p <= 0 or high_p <= 0 or low_p <= 0 or close_p <= 0:
            raise BinanceDataQualityError(f"OHLC values must be strictly positive at row {idx}")
        if not math.isfinite(volume) or volume < 0:
            raise BinanceDataQualityError(f"Volume must be finite non-negative at row {idx}")
        if (
            high_p < low_p
            or high_p < open_p
            or high_p < close_p
            or low_p > open_p
            or low_p > close_p
        ):
            raise BinanceDataQualityError(f"Bar geometry invariants violated at row {idx}")

        try:
            dt_utc = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC)
        except (OSError, OverflowError, ValueError) as exc:
            raise BinanceDataQualityError(
                f"Corrupted or out-of-range timestamp at row {idx} ({open_time_ms}): {exc}"
            ) from exc
        timestamps.append(dt_utc)
        opens.append(open_p)
        highs.append(high_p)
        lows.append(low_p)
        closes.append(close_p)
        volumes.append(volume)

    if not timestamps:
        raise BinanceDataQualityError("No closed klines remain after filtering unclosed bars")

    dt_index = pd.DatetimeIndex(timestamps, name="timestamp")
    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dt_index,
    )

    df = df.sort_index(kind="mergesort")

    expected_delta = pd.Timedelta(milliseconds=int_ms)
    validate_canonical_dataframe(df, expected_interval=expected_delta)

    if limit is not None and len(df) > limit:
        df = df.tail(limit)

    if not as_datetime_index:
        df = df.reset_index()

    return df


def parse_raw_kline_to_canonical_bar(
    row: Sequence[Any],
    symbol: str,
    interval: str = DEFAULT_INTERVAL,
    current_time_ms: int | None = None,
) -> CanonicalBar:
    """Parse a single 12-element raw Binance kline row into a strongly typed CanonicalBar."""
    if len(row) < 7:
        raise BinanceDataQualityError(f"Invalid kline row length: expected >= 7, got {len(row)}")

    try:
        open_time_ms = int(row[0])
        close_time_ms = int(row[6])
    except (ValueError, TypeError) as exc:
        raise BinanceDataQualityError(f"Malformed timestamp: {exc}") from exc

    now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)
    is_closed = close_time_ms < now_ms

    try:
        return CanonicalBar(
            symbol=symbol.upper(),
            interval=interval,
            timestamp=ms_to_utc_datetime(open_time_ms),
            close_time=ms_to_utc_datetime(close_time_ms),
            open=Decimal(str(row[1])),
            high=Decimal(str(row[2])),
            low=Decimal(str(row[3])),
            close=Decimal(str(row[4])),
            volume=Decimal(str(row[5])),
            quote_volume=Decimal(str(row[7])) if len(row) > 7 else Decimal("0"),
            trades=int(row[8]) if len(row) > 8 else 0,
            taker_buy_base=Decimal(str(row[9])) if len(row) > 9 else Decimal("0"),
            taker_buy_quote=Decimal(str(row[10])) if len(row) > 10 else Decimal("0"),
            is_closed=is_closed,
        )
    except Exception as exc:
        raise BinanceDataQualityError(f"Failed to create CanonicalBar: {exc}") from exc


def parse_raw_klines_to_canonical_bars(
    raw_klines: Sequence[Sequence[Any]],
    symbol: str,
    interval: str = DEFAULT_INTERVAL,
    only_closed: bool = True,
    current_time_ms: int | None = None,
    limit: int | None = None,
) -> list[CanonicalBar]:
    """Parse raw Binance klines into a list of CanonicalBar domain objects."""
    now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)
    bars: list[CanonicalBar] = []
    for row in raw_klines:
        if only_closed and len(row) >= 7:
            try:
                close_time_ms = int(row[6])
                if close_time_ms >= now_ms:
                    continue
            except ValueError, TypeError:
                pass
        bars.append(
            parse_raw_kline_to_canonical_bar(
                row, symbol=symbol, interval=interval, current_time_ms=now_ms
            )
        )
    if limit is not None and len(bars) > limit:
        bars = bars[-limit:]
    return bars


# ---------------------------------------------------------------------------
# Offline Fallback Generators & Parquet Loader
# ---------------------------------------------------------------------------


def generate_deterministic_synthetic_bars(
    symbol: str,
    bars_count: int = DEFAULT_WARMUP_BARS,
    end_time: datetime | None = None,
    base_price: float | None = None,
    as_datetime_index: bool = True,
) -> pd.DataFrame:
    """Generate deterministic 5m OHLC bars aligned to UTC 5m boundary."""
    now_dt = end_time or datetime.now(UTC)
    now_ms = int(now_dt.timestamp() * 1000)
    last_closed_open_s = ((now_ms // INTERVAL_5M_MS) - 1) * (INTERVAL_5M_MS // 1000)
    start_s = last_closed_open_s - (bars_count - 1) * (INTERVAL_5M_MS // 1000)

    sym = symbol.upper()
    base = base_price or SYMBOL_BASE_PRICES.get(sym, 100.0)

    timestamps: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    for i in range(bars_count):
        ts = datetime.fromtimestamp(start_s + i * 300, tz=UTC)
        angle = (i % 36) * (2 * math.pi / 36)
        variation = (base * 0.005) * math.sin(angle)
        close_p = base + variation
        open_p = close_p - (base * 0.001) * math.cos(angle)
        high_p = max(open_p, close_p) + (base * 0.002)
        low_p = min(open_p, close_p) - (base * 0.002)
        volume = 1000.0 + 200.0 * math.sin(angle)

        timestamps.append(ts)
        opens.append(round(open_p, 6))
        highs.append(round(high_p, 6))
        lows.append(round(low_p, 6))
        closes.append(round(close_p, 6))
        volumes.append(round(volume, 4))

    dt_index = pd.DatetimeIndex(timestamps, name="timestamp")
    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dt_index,
    )
    validate_canonical_dataframe(df)

    if not as_datetime_index:
        df = df.reset_index()

    return df


def load_parquet_warmup_bars(
    symbol: str,
    warmup_bars: int = DEFAULT_WARMUP_BARS,
    history_dir: Path | str = DEFAULT_HISTORY_DIR,
    align_timestamps: bool = True,
    now: datetime | None = None,
    as_datetime_index: bool = True,
) -> pd.DataFrame | None:
    """Load warmup bars from local Parquet file. Returns None if absent or incomplete."""
    path = Path(history_dir) / f"{symbol.upper()}-5m.parquet"
    if not path.is_file():
        return None
    try:
        df = pd.read_parquet(path)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            logger.warning(
                "Parquet %s missing required columns: %s", path, required - set(df.columns)
            )
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df_sorted = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        if len(df_sorted) < warmup_bars:
            logger.warning(
                "Parquet %s has only %d rows (< %d required)",
                path,
                len(df_sorted),
                warmup_bars,
            )
            return None
        tail_df = df_sorted.tail(warmup_bars).copy().reset_index(drop=True)
        if align_timestamps:
            now_dt = now or datetime.now(UTC)
            now_ms = int(now_dt.timestamp() * 1000)
            last_closed_open_s = ((now_ms // INTERVAL_5M_MS) - 1) * (INTERVAL_5M_MS // 1000)
            start_s = last_closed_open_s - (warmup_bars - 1) * (INTERVAL_5M_MS // 1000)
            tail_df["timestamp"] = [
                datetime.fromtimestamp(start_s + i * (INTERVAL_5M_MS // 1000), tz=UTC)
                for i in range(warmup_bars)
            ]

        if as_datetime_index:
            tail_df = tail_df.set_index("timestamp")
            tail_df.index.name = "timestamp"
            tail_df = tail_df[["open", "high", "low", "close", "volume"]]

        validate_canonical_dataframe(tail_df)
        return tail_df
    except Exception as exc:
        logger.warning("Failed to load Parquet %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# BinancePublicRestClient Implementation
# ---------------------------------------------------------------------------


class BinancePublicRestClient:
    """Resilient async public unauthenticated client for Binance Futures REST endpoints."""

    DEFAULT_BASE_URL: str = DEFAULT_REST_URL
    DEFAULT_TIMEOUT: float = DEFAULT_TIMEOUT_SECONDS
    DEFAULT_MAX_RETRIES: int = DEFAULT_MAX_RETRIES
    DEFAULT_BACKOFF_FACTOR: float = DEFAULT_BACKOFF_FACTOR

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        timeout_seconds: float | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        # Strict zero-credential invariant enforcement
        for k in kwargs:
            if is_forbidden_auth_key(k):
                raise BinanceSecurityViolation(
                    f"Credentials and authenticated parameters are strictly forbidden: {k}"
                )
            raise TypeError(
                f"BinancePublicRestClient.__init__() got an unexpected keyword argument '{k}'"
            )

        if headers is not None:
            for k in headers:
                if is_forbidden_auth_key(k):
                    raise BinanceSecurityViolation(
                        f"Credentials and authenticated headers are strictly forbidden: {k}"
                    )

        if client is not None:
            if getattr(client, "auth", None) is not None:
                raise BinanceSecurityViolation(
                    "External client must not have authentication configured (client.auth is set)"
                )
            if hasattr(client, "headers"):
                for k in client.headers:
                    if is_forbidden_auth_key(k):
                        raise BinanceSecurityViolation(
                            f"External client contains forbidden authentication header: {k}"
                        )
            self._client: httpx.AsyncClient | None = client
            self._owns_client = False
        else:
            self._client = None
            self._owns_client = True

        effective_timeout = timeout_seconds if timeout_seconds is not None else timeout

        self.base_url = base_url.rstrip("/")
        self.timeout = effective_timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._transport = transport

        self._headers: dict[str, str] = {
            "User-Agent": "AutonomousFuturesBot/1.0 (PublicRestClient; Unauthenticated)",
            "Accept": "application/json",
        }
        if headers:
            self._headers.update(headers)

    @property
    def is_unauthenticated(self) -> bool:
        """Guarantee that client operates with zero credentials."""
        return True

    @property
    def api_keys_loaded(self) -> int:
        """Guarantee that zero API keys are loaded."""
        return 0

    async def __aenter__(self) -> Self:
        """Enter async context manager, initializing HTTP client session."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                transport=self._transport,
                timeout=self.timeout,
                headers=self._headers,
            )
            self._owns_client = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context manager and close managed HTTP client session."""
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def aclose(self) -> None:
        """Close underlying HTTP client session if owned."""
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def close(self) -> None:
        """Alias for aclose()."""
        await self.aclose()

    def _get_active_client(self) -> httpx.AsyncClient:
        """Retrieve active client or lazily instantiate one."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                transport=self._transport,
                timeout=self.timeout,
                headers=self._headers,
            )
            self._owns_client = True
        return self._client

    def _verify_unauthenticated_request(
        self,
        headers: dict[str, str] | None,
        params: dict[str, Any] | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Assert zero authentication headers or parameters exist in outgoing request."""
        if headers:
            for k in headers:
                if is_forbidden_auth_key(k):
                    raise BinanceSecurityViolation(f"Forbidden header detected: {k}")
        if params:
            for k in params:
                if is_forbidden_auth_key(k):
                    raise BinanceSecurityViolation(f"Forbidden query parameter detected: {k}")
        if client is not None:
            if getattr(client, "auth", None) is not None:
                raise BinanceSecurityViolation(
                    "Active client must not have authentication configured (client.auth is set)"
                )
            if hasattr(client, "headers"):
                for k in client.headers:
                    if is_forbidden_auth_key(k):
                        raise BinanceSecurityViolation(
                            f"Active client contains forbidden authentication header: {k}"
                        )

    async def _send_request(
        self,
        client: httpx.AsyncClient,
        request: httpx.Request,
    ) -> httpx.Response:
        """Inspect all headers and auth on prepared request before wire transmission."""
        if getattr(client, "auth", None) is not None:
            raise BinanceSecurityViolation(
                "Active client has authentication configured (client.auth is set)"
            )
        for k in request.headers:
            if is_forbidden_auth_key(k):
                raise BinanceSecurityViolation(
                    f"Forbidden credential header detected on prepared request: {k}"
                )
        return await client.send(request)

    async def _execute_with_retry(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute GET request with timeout, rate limit handling, and backoff retries."""
        client = self._get_active_client()
        self._verify_unauthenticated_request(self._headers, params, client=client)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                request = client.build_request("GET", path, params=params)
                response = await self._send_request(client, request)

                # HTTP 418: IP Ban - fail immediately without retrying
                if response.status_code == 418:
                    raise BinanceRateLimitError(
                        418,
                        "IP has been banned by Binance Futures API",
                        is_ban=True,
                        response_body=response.text,
                    )

                # HTTP 429: Rate Limit Exceeded
                if response.status_code == 429:
                    retry_after_header = response.headers.get("Retry-After", "1.0")
                    try:
                        retry_after = float(retry_after_header)
                    except ValueError:
                        retry_after = 1.0
                    retry_after = min(retry_after, 10.0)

                    if attempt < self.max_retries:
                        logger.warning(
                            "Rate limited (HTTP 429) requesting %s; sleeping %.2fs (attempt %d/%d)",
                            path,
                            retry_after,
                            attempt + 1,
                            self.max_retries,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    raise BinanceRateLimitError(
                        429,
                        "Request rate limit exceeded",
                        retry_after=retry_after,
                        response_body=response.text,
                    )

                # HTTP 4xx Client Errors (excluding 429) - deterministic failure, do not retry
                if 400 <= response.status_code < 500:
                    raise BinanceHttpError(
                        response.status_code,
                        f"Client error on {path}: {response.text}",
                        response_body=response.text,
                    )

                # HTTP 5xx Server Errors - transient, retry if attempts remain
                if response.status_code >= 500:
                    if attempt < self.max_retries:
                        backoff = self.backoff_factor * (2**attempt)
                        logger.warning(
                            "Server error (HTTP %d) requesting %s; "
                            "retrying in %.2fs (attempt %d/%d)",
                            response.status_code,
                            path,
                            backoff,
                            attempt + 1,
                            self.max_retries,
                        )

                        await asyncio.sleep(backoff)
                        continue
                    raise BinanceHttpError(
                        response.status_code,
                        f"Server error on {path}: {response.text}",
                        response_body=response.text,
                    )

                response.raise_for_status()
                return response.json()

            except (httpx.TimeoutException, TimeoutError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = self.backoff_factor * (2**attempt)
                    logger.debug(
                        "Timeout on %s; retrying in %.2fs (attempt %d/%d): %s",
                        path,
                        backoff,
                        attempt + 1,
                        self.max_retries,
                        exc,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise BinanceTimeoutError(
                    f"Request to {path} timed out after {self.max_retries + 1} attempts"
                ) from exc

            except (httpx.NetworkError, ConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = self.backoff_factor * (2**attempt)
                    logger.debug(
                        "Network error on %s; retrying in %.2fs (attempt %d/%d): %s",
                        path,
                        backoff,
                        attempt + 1,
                        self.max_retries,
                        exc,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise BinanceNetworkError(
                    f"Network error on {path} after {self.max_retries + 1} attempts: {exc}"
                ) from exc

            except BinanceRestError:
                raise

            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = self.backoff_factor * (2**attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise BinanceRestError(f"Unexpected error on {path}: {exc}") from exc

        raise BinanceRestError(
            f"Failed request to {path} after {self.max_retries + 1} attempts: {last_error}"
        )

    async def get_server_time(self) -> int:
        """Fetch current Binance Futures exchange time in milliseconds."""
        payload = await self._execute_with_retry("/fapi/v1/time")
        if not isinstance(payload, dict) or "serverTime" not in payload:
            raise BinanceDataQualityError("Invalid payload returned from /fapi/v1/time")
        return int(payload["serverTime"])

    async def fetch_raw_klines(
        self,
        symbol: str,
        *,
        interval: str = DEFAULT_INTERVAL,
        limit: int = DEFAULT_WARMUP_BARS,
        end_time: int | datetime | None = None,
        endTime: int | datetime | None = None,
    ) -> list[list[Any]]:
        """Fetch raw 12-element kline arrays from GET /fapi/v1/klines."""
        sym = symbol.strip().upper()
        if not SYMBOL_PATTERN.match(sym):
            raise ValueError(f"Invalid symbol format: {symbol!r}")
        if interval not in ALLOWED_INTERVALS:
            raise ValueError(
                f"Invalid interval: {interval!r}; allowed: {sorted(ALLOWED_INTERVALS)}"
            )
        if not (1 <= limit <= 1500):
            raise ValueError(f"Limit must be between 1 and 1500, got {limit}")

        target_end = end_time if end_time is not None else endTime
        end_time_ms: int | None = None
        if target_end is not None:
            if isinstance(target_end, datetime):
                end_time_ms = int(target_end.astimezone(UTC).timestamp() * 1000)
            elif isinstance(target_end, (int, float)):
                end_time_ms = int(target_end)
            else:
                raise ValueError(f"Invalid end_time type: {type(target_end)}")

        params: dict[str, Any] = {
            "symbol": sym,
            "interval": interval,
            "limit": limit,
        }
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        payload = await self._execute_with_retry("/fapi/v1/klines", params=params)
        if not isinstance(payload, list):
            raise BinanceDataQualityError(
                f"Expected list response from /fapi/v1/klines, got {type(payload).__name__}"
            )
        return payload

    async def fetch_klines(
        self,
        symbol: str,
        *,
        interval: str = DEFAULT_INTERVAL,
        limit: int = DEFAULT_WARMUP_BARS,
        end_time: int | datetime | None = None,
        endTime: int | datetime | None = None,
        now: datetime | None = None,
        only_closed: bool = True,
        as_datetime_index: bool = True,
    ) -> pd.DataFrame:
        """Fetch latest klines and return validated canonical pd.DataFrame.

        When only_closed=True and no end_time is provided, automatically aligns
        endTime to the preceding closed candle boundary to exclude currently developing bars.
        """
        now_ms = int(now.timestamp() * 1000) if now is not None else int(time.time() * 1000)
        target_end = end_time if end_time is not None else endTime

        # Automatically calculate closed bar boundary if end_time not provided
        if only_closed and target_end is None:
            interval_ms = interval_to_milliseconds(interval)
            target_end = calculate_closed_bar_boundary(now_ms, interval_ms)

        # Request limit + 5 to ensure we have >= limit closed bars even if clock skews
        fetch_limit = min(limit + 5, 1500) if only_closed else limit

        raw_data = await self.fetch_raw_klines(
            symbol,
            interval=interval,
            limit=fetch_limit,
            end_time=target_end,
        )

        return parse_raw_klines_to_canonical_df(
            raw_data,
            interval=interval,
            only_closed=only_closed,
            current_time_ms=now_ms,
            limit=limit,
            as_datetime_index=as_datetime_index,
        )


# ---------------------------------------------------------------------------
# Standalone Fetch Helpers & Fallback Cascade
# ---------------------------------------------------------------------------


async def fetch_klines_with_fallback(
    symbol: str,
    warmup_bars: int = DEFAULT_WARMUP_BARS,
    *,
    limit: int | None = None,
    only_closed: bool = True,
    interval: str = DEFAULT_INTERVAL,
    history_dir: Path | str = DEFAULT_HISTORY_DIR,
    offline: bool = False,
    align_timestamps: bool = True,
    rest_client: BinancePublicRestClient | None = None,
    now: datetime | None = None,
    as_datetime_index: bool = True,
) -> pd.DataFrame:
    """Cascade: Primary REST -> Fallback 1 Local Parquet -> Fallback 2 Deterministic Synthetic."""
    sym = symbol.upper()
    effective_bars = limit if limit is not None else warmup_bars

    if not offline:
        client = rest_client or BinancePublicRestClient()
        owns_client = rest_client is None
        try:
            df = await client.fetch_klines(
                sym,
                interval=interval,
                limit=effective_bars,
                only_closed=only_closed,
                now=now,
                as_datetime_index=as_datetime_index,
            )
            df.attrs["source"] = "REST"
            logger.info("Seeded %d bars for %s via public REST API", len(df), sym)
            return df
        except Exception as exc:
            logger.warning(
                "REST warmup fetch failed for %s (%s); cascading to offline fallback",
                sym,
                exc,
            )
        finally:
            if owns_client:
                await client.aclose()

    # Fallback 1: Local Parquet
    parquet_df = load_parquet_warmup_bars(
        sym,
        warmup_bars=effective_bars,
        history_dir=history_dir,
        align_timestamps=align_timestamps,
        now=now,
        as_datetime_index=as_datetime_index,
    )
    if parquet_df is not None:
        parquet_df.attrs["source"] = "Parquet"
        logger.info("Seeded %d bars for %s from local Parquet", len(parquet_df), sym)
        return parquet_df

    # Fallback 2: Deterministic Synthetic
    synth_df = generate_deterministic_synthetic_bars(
        sym,
        bars_count=effective_bars,
        end_time=now,
        as_datetime_index=as_datetime_index,
    )
    synth_df.attrs["source"] = "Synthetic"
    logger.info("Seeded %d bars for %s via deterministic synthetic generator", len(synth_df), sym)
    return synth_df


# Alias for compatibility with various callers
fetch_warmup_bars_with_fallback = fetch_klines_with_fallback


async def fetch_binance_futures_klines(
    symbol: str,
    *,
    interval: str = DEFAULT_INTERVAL,
    limit: int = DEFAULT_WARMUP_BARS,
    end_time: int | datetime | None = None,
    endTime: int | datetime | None = None,
    base_url: str = DEFAULT_REST_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    only_closed: bool = True,
    as_datetime_index: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
    client: httpx.AsyncClient | None = None,
) -> pd.DataFrame:
    """Fetch Binance Futures historical klines using an async context-managed client."""
    target_end = end_time if end_time is not None else endTime
    async with BinancePublicRestClient(
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        backoff_factor=backoff_factor,
        transport=transport,
        client=client,
    ) as rest_client:
        return await rest_client.fetch_klines(
            symbol,
            interval=interval,
            limit=limit,
            end_time=target_end,
            only_closed=only_closed,
            as_datetime_index=as_datetime_index,
        )
