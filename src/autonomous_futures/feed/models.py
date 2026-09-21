"""Phase 257: Feed Domain Models and Wire Parsers.

CanonicalBar and TickerSnapshot models inheriting from DomainModel
with strict Decimal precision (zero floats allowed) and timezone-aware
UTC datetimes.
"""

from __future__ import annotations

from collections.abc import Mapping
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


def _unwrap_stream_payload(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Unwrap combined stream envelope {"stream": "...", "data": {...}} if present."""
    if "stream" in data and "data" in data and isinstance(data["data"], (dict, Mapping)):
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


def _to_int(v: object, field_name: str = "integer") -> int:
    """Convert object to int safely, rejecting booleans and non-integers."""
    if isinstance(v, bool):
        raise ValueError(f"Boolean values are forbidden for {field_name}, got {v!r}")
    if isinstance(v, int):
        return v
    try:
        return int(str(v))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid integer value for {field_name}: {v!r}") from exc


class OrderBookLevel(DomainModel):
    """Single level in an orderbook depth ladder."""

    price: StrictPositiveDecimal
    quantity: StrictNonNegativeDecimal

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _ensure_strict_decimal(v, info.field_name)


class OrderBookDepthSnapshot(DomainModel):
    """Top-of-book depth snapshot (e.g. depth5) with strict Decimal precision and UTC timestamps."""

    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    last_update_id: int = Field(ge=0, strict=True)
    event_time: datetime
    transaction_time: datetime | None = None
    prev_last_update_id: int | None = None

    @field_validator("event_time")
    @classmethod
    def require_utc_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC)

    @field_validator("transaction_time")
    @classmethod
    def require_utc_transaction_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC) if value is not None else None

    @property
    def best_bid(self) -> OrderBookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> OrderBookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def best_bid_price(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask_price(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid_price is not None and self.best_ask_price is not None:
            return self.best_ask_price - self.best_bid_price
        return None

    @property
    def spread_bps(self) -> Decimal | None:
        if self.best_bid_price is not None and self.best_ask_price is not None:
            mid = (self.best_bid_price + self.best_ask_price) / Decimal("2")
            if mid <= Decimal("0"):
                return Decimal("0")
            return ((self.best_ask_price - self.best_bid_price) / mid) * Decimal("10000")
        return None


class AggregateTrade(DomainModel):
    """Binance aggregate trade event with strict Decimal precision and UTC timestamps."""

    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    aggregate_trade_id: int = Field(ge=0, strict=True)
    price: StrictPositiveDecimal
    quantity: StrictPositiveDecimal
    trade_time: datetime
    is_buyer_maker: bool = Field(strict=True)
    first_trade_id: int | None = None
    last_trade_id: int | None = None
    event_time: datetime | None = None

    @field_validator("trade_time")
    @classmethod
    def require_utc_trade_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC)

    @field_validator("event_time")
    @classmethod
    def require_utc_event_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC) if value is not None else None

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _ensure_strict_decimal(v, info.field_name)

    @property
    def agg_trade_id(self) -> int:
        return self.aggregate_trade_id


class MarkPriceSnapshot(DomainModel):
    """Mark price and funding rate snapshot with strict Decimal precision and UTC timestamps."""

    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    mark_price: StrictPositiveDecimal
    index_price: StrictPositiveDecimal
    estimated_settle_price: StrictPositiveDecimal | None = None
    funding_rate: Decimal
    next_funding_time: datetime
    event_time: datetime

    @field_validator("next_funding_time", "event_time")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timezone-aware UTC timestamp required")
        return value.astimezone(UTC)

    @field_validator("mark_price", "index_price", "funding_rate", mode="before")
    @classmethod
    def validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _ensure_strict_decimal(v, info.field_name)

    @field_validator("estimated_settle_price", mode="before")
    @classmethod
    def validate_optional_settle_price(cls, v: Any, info: Any) -> Decimal | None:
        if v is None or v == "":
            return None
        return _ensure_strict_decimal(v, info.field_name)


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


def parse_binance_depth5(payload: Mapping[str, object]) -> OrderBookDepthSnapshot:
    """Parse Binance Futures top-5 depth WebSocket message into OrderBookDepthSnapshot."""
    data_map: Mapping[str, object] = payload
    if "data" in payload and isinstance(payload["data"], Mapping):
        data_map = payload["data"]

    symbol = ""
    if "s" in data_map and data_map["s"]:
        symbol = str(data_map["s"]).upper()
    elif "stream" in payload and isinstance(payload["stream"], str):
        stream_part = payload["stream"].split("@", 1)[0]
        symbol = stream_part.upper()

    if not symbol:
        raise ValueError("Missing symbol in depth payload")

    if "b" not in data_map or "a" not in data_map:
        raise KeyError("Missing required fields in depth payload: 'b' and/or 'a'")

    raw_bids = data_map["b"]
    raw_asks = data_map["a"]
    if not isinstance(raw_bids, (list, tuple)) or not isinstance(raw_asks, (list, tuple)):
        raise ValueError("Invalid format for bids or asks")

    bids_list: list[OrderBookLevel] = []
    for item in raw_bids[:5]:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            raise ValueError(f"Invalid depth level format: {item!r}")
        bids_list.append(
            OrderBookLevel(
                price=_ensure_strict_decimal(item[0], "bid_price"),
                quantity=_ensure_strict_decimal(item[1], "bid_quantity"),
            )
        )

    asks_list: list[OrderBookLevel] = []
    for item in raw_asks[:5]:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            raise ValueError(f"Invalid depth level format: {item!r}")
        asks_list.append(
            OrderBookLevel(
                price=_ensure_strict_decimal(item[0], "ask_price"),
                quantity=_ensure_strict_decimal(item[1], "ask_quantity"),
            )
        )

    if bool(bids_list) != bool(asks_list):
        raise ValueError("Empty bids or asks in depth payload with one-sided book")

    if "stream" not in payload and bids_list and asks_list:
        if bids_list[0].price > asks_list[0].price:
            raise ValueError(
                "crossed book detected: "
                f"best_bid ({bids_list[0].price}) > best_ask ({asks_list[0].price})"
            )

    if "u" not in data_map and "lastUpdateId" not in data_map:
        raise KeyError("Missing required field 'u' or 'lastUpdateId' in depth payload")

    last_update_id = _to_int(
        data_map.get("u") if "u" in data_map else data_map["lastUpdateId"], "last_update_id"
    )
    prev_last_update_id = (
        _to_int(data_map["pu"], "prev_last_update_id")
        if "pu" in data_map and data_map["pu"] is not None
        else None
    )

    e_ms = data_map.get("E")
    t_ms = data_map.get("T")
    if e_ms is None and t_ms is not None:
        e_ms = t_ms
    elif e_ms is None:
        e_ms = int(datetime.now(UTC).timestamp() * 1000)

    event_time = ms_to_utc_datetime(_to_int(e_ms, "event_time"))
    transaction_time = (
        ms_to_utc_datetime(_to_int(t_ms, "transaction_time")) if t_ms is not None else None
    )

    return OrderBookDepthSnapshot(
        symbol=symbol,
        bids=tuple(bids_list),
        asks=tuple(asks_list),
        last_update_id=last_update_id,
        event_time=event_time,
        transaction_time=transaction_time,
        prev_last_update_id=prev_last_update_id,
    )


def parse_binance_agg_trade(payload: Mapping[str, object]) -> AggregateTrade:
    """Parse Binance Futures aggregate trade WebSocket message into AggregateTrade."""
    data_map: Mapping[str, object] = payload
    if "data" in payload and isinstance(payload["data"], Mapping):
        data_map = payload["data"]

    symbol = ""
    if "s" in data_map and data_map["s"]:
        symbol = str(data_map["s"]).upper()
    elif "stream" in payload and isinstance(payload["stream"], str):
        stream_part = payload["stream"].split("@", 1)[0]
        symbol = stream_part.upper()

    if not symbol:
        raise ValueError("Missing symbol in aggTrade payload")

    required_keys = ("a", "p", "q", "T", "m")
    for k in required_keys:
        if k not in data_map:
            raise KeyError(f"Missing required field '{k}' in aggTrade payload")

    trade_time_ms = _to_int(data_map["T"], "trade_time")
    trade_time = ms_to_utc_datetime(trade_time_ms)

    event_time = (
        ms_to_utc_datetime(_to_int(data_map["E"], "event_time"))
        if "E" in data_map and data_map["E"] is not None
        else None
    )

    first_trade_id = (
        _to_int(data_map["f"], "first_trade_id")
        if "f" in data_map and data_map["f"] is not None
        else None
    )
    last_trade_id = (
        _to_int(data_map["l"], "last_trade_id")
        if "l" in data_map and data_map["l"] is not None
        else None
    )

    is_buyer_maker = data_map["m"]
    if not isinstance(is_buyer_maker, bool):
        raise ValueError(f"is_buyer_maker 'm' must be boolean, got {type(is_buyer_maker).__name__}")

    return AggregateTrade(
        symbol=symbol,
        aggregate_trade_id=_to_int(data_map["a"], "aggregate_trade_id"),
        price=_ensure_strict_decimal(data_map["p"], "price"),
        quantity=_ensure_strict_decimal(data_map["q"], "quantity"),
        trade_time=trade_time,
        is_buyer_maker=is_buyer_maker,
        first_trade_id=first_trade_id,
        last_trade_id=last_trade_id,
        event_time=event_time,
    )


def parse_binance_mark_price(payload: Mapping[str, object]) -> MarkPriceSnapshot:
    """Parse Binance Futures markPriceUpdate WebSocket message into MarkPriceSnapshot."""
    data_map: Mapping[str, object] = payload
    if "data" in payload and isinstance(payload["data"], Mapping):
        data_map = payload["data"]

    symbol = ""
    if "s" in data_map and data_map["s"]:
        symbol = str(data_map["s"]).upper()
    elif "stream" in payload and isinstance(payload["stream"], str):
        stream_part = payload["stream"].split("@", 1)[0]
        symbol = stream_part.upper()

    if not symbol:
        raise ValueError("Missing symbol in markPrice payload")

    required_keys = ("p", "i", "r", "T", "E")
    for k in required_keys:
        if k not in data_map:
            raise KeyError(f"Missing required field '{k}' in markPrice payload")

    mark_price = _ensure_strict_decimal(data_map["p"], "mark_price")
    index_price = _ensure_strict_decimal(data_map["i"], "index_price")
    estimated_settle_price = (
        _ensure_strict_decimal(data_map["P"], "estimated_settle_price")
        if "P" in data_map and data_map["P"] is not None and data_map["P"] != ""
        else None
    )
    funding_rate = _ensure_strict_decimal(data_map["r"], "funding_rate")

    next_funding_time_ms = _to_int(data_map["T"], "next_funding_time")
    next_funding_time = ms_to_utc_datetime(next_funding_time_ms)

    event_time_ms = _to_int(data_map["E"], "event_time")
    event_time = ms_to_utc_datetime(event_time_ms)

    return MarkPriceSnapshot(
        symbol=symbol,
        mark_price=mark_price,
        index_price=index_price,
        estimated_settle_price=estimated_settle_price,
        funding_rate=funding_rate,
        next_funding_time=next_funding_time,
        event_time=event_time,
    )


__all__ = [
    "AggregateTrade",
    "CanonicalBar",
    "MarkPriceSnapshot",
    "OrderBookDepthSnapshot",
    "OrderBookLevel",
    "TickerSnapshot",
    "ms_to_utc_datetime",
    "parse_binance_agg_trade",
    "parse_binance_book_ticker",
    "parse_binance_depth5",
    "parse_binance_kline",
    "parse_binance_mark_price",
]
