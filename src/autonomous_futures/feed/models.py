"""Phase 257: Feed Domain Models and Wire Parsers.

CanonicalBar and TickerSnapshot models inheriting from DomainModel
with strict Decimal precision (zero floats allowed) and timezone-aware
UTC datetimes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import Field, field_validator, model_validator

from autonomous_futures.domain.contracts import (
    DomainModel,
    StrictNonNegativeDecimal,
    StrictPositiveDecimal,
)


def ms_to_utc_datetime(ms: int) -> datetime:
    """Convert Unix epoch milliseconds to timezone-aware UTC datetime with zero float conversion."""
    if isinstance(ms, bool) or not isinstance(ms, int):
        raise ValueError(f"timestamp_ms must be an integer, got {type(ms).__name__}")
    if ms < 0:
        raise ValueError(f"timestamp_ms must be non-negative, got {ms}")
    seconds = ms // 1000
    microseconds = (ms % 1000) * 1000
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(microseconds=microseconds)


def _unwrap_stream_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Unwrap combined stream envelope {"stream": "...", "data": {...}} if present."""
    if "stream" in data and "data" in data and isinstance(data["data"], dict):
        return data["data"]
    return data


def _ensure_strict_decimal(v: Any, field_name: str) -> Decimal:
    """Enforce strict decimal conversion with zero float allowance."""
    if isinstance(v, bool):
        raise ValueError(f"Boolean values are forbidden for {field_name}")
    if isinstance(v, float):
        raise ValueError(
            f"Float values are strictly forbidden for {field_name}; use Decimal or str"
        )
    if isinstance(v, Decimal):
        if not v.is_finite():
            raise ValueError(f"Non-finite Decimal is forbidden for {field_name}")
        return v
    try:
        parsed = Decimal(str(v))
        if not parsed.is_finite():
            raise ValueError(f"Non-finite Decimal is forbidden for {field_name}")
        return parsed
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {v!r}") from exc


class CanonicalBar(DomainModel):
    """Canonical candlestick bar representation for futures market data."""

    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    interval: str = Field(min_length=1)
    timestamp: datetime
    close_time: datetime
    open: StrictPositiveDecimal
    high: StrictPositiveDecimal
    low: StrictPositiveDecimal
    close: StrictPositiveDecimal
    volume: StrictNonNegativeDecimal
    quote_volume: StrictNonNegativeDecimal
    trades: int = Field(ge=0, strict=True)
    taker_buy_base: StrictNonNegativeDecimal
    taker_buy_quote: StrictNonNegativeDecimal
    is_closed: bool = Field(strict=True)

    @field_validator("timestamp", "close_time")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC)

    @field_validator(
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base",
        "taker_buy_quote",
        mode="before",
    )
    @classmethod
    def validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _ensure_strict_decimal(v, info.field_name)

    @model_validator(mode="after")
    def validate_bar_invariants(self) -> CanonicalBar:
        if self.close_time < self.timestamp:
            raise ValueError("close_time must not be before timestamp")
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) cannot be less than low ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError(
                f"high ({self.high}) must be >= open ({self.open}) and close ({self.close})"
            )
        if self.low > self.open or self.low > self.close:
            raise ValueError(
                f"low ({self.low}) must be <= open ({self.open}) and close ({self.close})"
            )
        if self.taker_buy_base > self.volume + Decimal("1e-8"):
            raise ValueError(
                f"taker_buy_base ({self.taker_buy_base}) cannot exceed volume ({self.volume})"
            )
        if self.taker_buy_quote > self.quote_volume + Decimal("1e-8"):
            raise ValueError(
                f"taker_buy_quote ({self.taker_buy_quote}) cannot exceed "
                f"quote_volume ({self.quote_volume})"
            )
        return self


class TickerSnapshot(DomainModel):
    """Best bid/ask ticker snapshot with microsecond-exact UTC timestamps."""

    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    best_bid_price: StrictPositiveDecimal
    best_bid_qty: StrictNonNegativeDecimal
    best_ask_price: StrictPositiveDecimal
    best_ask_qty: StrictNonNegativeDecimal
    transaction_time: datetime
    event_time: datetime

    @field_validator("transaction_time", "event_time")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC)

    @field_validator(
        "best_bid_price",
        "best_bid_qty",
        "best_ask_price",
        "best_ask_qty",
        mode="before",
    )
    @classmethod
    def validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _ensure_strict_decimal(v, info.field_name)

    @model_validator(mode="after")
    def validate_spread(self) -> TickerSnapshot:
        if self.best_bid_price > self.best_ask_price:
            raise ValueError(
                f"crossed book detected: best_bid_price ({self.best_bid_price}) "
                f"> best_ask_price ({self.best_ask_price})"
            )
        return self

    @property
    def mid_price(self) -> Decimal:
        return (self.best_bid_price + self.best_ask_price) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.best_ask_price - self.best_bid_price

    @property
    def spread_bps(self) -> Decimal:
        mid = self.mid_price
        if mid <= Decimal("0"):
            return Decimal("0")
        return (self.spread / mid) * Decimal("10000")


def parse_binance_kline(data: dict[str, Any]) -> CanonicalBar | None:
    """Parse Binance Futures kline WebSocket message into CanonicalBar."""
    if "result" in data and "s" not in data and "k" not in data and "stream" not in data:
        return None

    raw = _unwrap_stream_payload(data)
    if "result" in raw and "s" not in raw and "k" not in raw:
        return None

    k = raw.get("k", raw)
    symbol = str(k.get("s") or raw.get("s", "")).upper()
    if not symbol:
        raise ValueError("Missing symbol in kline payload")

    if "t" not in k or "T" not in k or "o" not in k or "c" not in k:
        raise KeyError("Missing required fields in kline payload")

    return CanonicalBar(
        symbol=symbol,
        interval=str(k.get("i", "5m")),
        timestamp=ms_to_utc_datetime(int(k["t"])),
        close_time=ms_to_utc_datetime(int(k["T"])),
        open=_ensure_strict_decimal(k["o"], "open"),
        high=_ensure_strict_decimal(k["h"], "high"),
        low=_ensure_strict_decimal(k["l"], "low"),
        close=_ensure_strict_decimal(k["c"], "close"),
        volume=_ensure_strict_decimal(k["v"], "volume"),
        quote_volume=_ensure_strict_decimal(k["q"], "quote_volume"),
        trades=int(k["n"]),
        taker_buy_base=_ensure_strict_decimal(k["V"], "taker_buy_base"),
        taker_buy_quote=_ensure_strict_decimal(k["Q"], "taker_buy_quote"),
        is_closed=bool(k["x"]),
    )


def parse_binance_book_ticker(data: dict[str, Any]) -> TickerSnapshot | None:
    """Parse Binance Futures bookTicker WebSocket message into TickerSnapshot."""
    if "result" in data and "s" not in data and "b" not in data and "stream" not in data:
        return None

    raw = _unwrap_stream_payload(data)
    if "result" in raw and "s" not in raw and "b" not in raw:
        return None

    if "b" not in raw or "a" not in raw or "s" not in raw:
        raise KeyError("Missing required fields in bookTicker payload")

    symbol = str(raw["s"]).upper()
    if not symbol:
        raise ValueError("Missing symbol in bookTicker payload")

    t_ms = int(raw["T"]) if "T" in raw else int(raw["E"])
    e_ms = int(raw.get("E", t_ms))

    b_qty = raw.get("B", "0")
    a_qty = raw.get("A", "0")

    return TickerSnapshot(
        symbol=symbol,
        best_bid_price=_ensure_strict_decimal(raw["b"], "best_bid_price"),
        best_bid_qty=_ensure_strict_decimal(b_qty, "best_bid_qty"),
        best_ask_price=_ensure_strict_decimal(raw["a"], "best_ask_price"),
        best_ask_qty=_ensure_strict_decimal(a_qty, "best_ask_qty"),
        transaction_time=ms_to_utc_datetime(t_ms),
        event_time=ms_to_utc_datetime(e_ms),
    )
