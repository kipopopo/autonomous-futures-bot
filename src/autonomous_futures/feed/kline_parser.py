"""Phase 317 Milestone 2: High-Precision Kline Data Parser for Binance Futures.

Parses raw Binance kline JSON tuples (REST 12-element arrays or WebSocket events)
into immutable Candle dataclass objects with exact Decimal precision.
Enforces domain validation on timestamps, prices, envelopes, and volumes.
"""

from __future__ import annotations

import decimal
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.strategy.ict_mmxm import Candle

ZERO: Decimal = Decimal("0")


class KlineParsingError(DomainViolation):
    """Raised when raw kline payload fails schema or domain invariants."""


def parse_raw_kline(raw: Sequence[Any] | Mapping[str, Any]) -> Candle:
    """Parses raw Binance kline array or mapping into an immutable Candle.

    Supported Formats:
    1. REST Array (12 elements or >= 6 elements):
       [open_time, open, high, low, close, volume, ...]
    2. WebSocket Event Mapping:
       {"t": 1700000000000, "o": "100.0", "h": "105.0", "l": "99.0", ...}
    3. Dict Mapping:
       {"open_time": 1700000000000, "open": "100.0", "high": "105.0", ...}

    Invariants Enforced:
    - Zero floating point conversions: strictly Decimal(str(val)).
    - timestamp_ms: strictly positive integer (> 0).
    - Prices: open, high, low, close > 0.
    - Envelope: high >= low, high >= open, high >= close, low <= open, low <= close.
    - Volume: volume >= 0.
    """
    if isinstance(raw, (list, tuple)):
        if len(raw) < 6:
            raise KlineParsingError(f"Kline array requires >= 6 elements, received {len(raw)}")
        try:
            ts_ms = int(raw[0])
            open_d = Decimal(str(raw[1]))
            high_d = Decimal(str(raw[2]))
            low_d = Decimal(str(raw[3]))
            close_d = Decimal(str(raw[4]))
            vol_d = Decimal(str(raw[5]))
        except (ValueError, TypeError, decimal.InvalidOperation) as exc:
            raise KlineParsingError(f"Numeric parse failure in kline array: {exc}") from exc
    elif isinstance(raw, (dict, Mapping)):
        try:
            ts_val = raw.get(
                "open_time",
                raw.get("timestamp_ms", raw.get("timestamp", raw.get("t"))),
            )
            if ts_val is None:
                raise KlineParsingError("Missing timestamp in kline mapping")
            ts_ms = int(ts_val)

            open_val = raw.get("open", raw.get("o"))
            high_val = raw.get("high", raw.get("h"))
            low_val = raw.get("low", raw.get("l"))
            close_val = raw.get("close", raw.get("c"))
            vol_val = raw.get("volume", raw.get("v"))

            if any(v is None for v in (open_val, high_val, low_val, close_val, vol_val)):
                raise KlineParsingError("Missing required OHLCV field in kline mapping")

            open_d = Decimal(str(open_val))
            high_d = Decimal(str(high_val))
            low_d = Decimal(str(low_val))
            close_d = Decimal(str(close_val))
            vol_d = Decimal(str(vol_val))
        except (ValueError, TypeError, decimal.InvalidOperation) as exc:
            raise KlineParsingError(f"Numeric parse failure in kline mapping: {exc}") from exc
    else:
        raise KlineParsingError(f"Unsupported kline payload type: {type(raw).__name__}")

    # Domain Validations
    if ts_ms <= 0:
        raise KlineParsingError(f"Invalid timestamp_ms: {ts_ms} (must be > 0)")
    if open_d <= ZERO or high_d <= ZERO or low_d <= ZERO or close_d <= ZERO:
        raise KlineParsingError("Candle prices must be strictly positive (> 0)")
    if high_d < low_d:
        raise KlineParsingError(f"Inverted high/low envelope: high={high_d} < low={low_d}")
    if high_d < open_d or high_d < close_d:
        raise KlineParsingError(f"High ({high_d}) must be >= open ({open_d}) and close ({close_d})")
    if low_d > open_d or low_d > close_d:
        raise KlineParsingError(f"Low ({low_d}) must be <= open ({open_d}) and close ({close_d})")
    if vol_d < ZERO:
        raise KlineParsingError(f"Volume must be non-negative (>= 0), got {vol_d}")

    return Candle(
        timestamp_ms=ts_ms,
        open=open_d,
        high=high_d,
        low=low_d,
        close=close_d,
        volume=vol_d,
    )
