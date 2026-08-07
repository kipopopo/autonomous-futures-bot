from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd

from .builder import INTERVAL_MS, KlineInterval
from .parquet import DataQualityError, canonicalize_bars

FUNDING_COLUMNS = (
    "symbol",
    "funding_time",
    "funding_rate",
    "funding_mark_price",
)
MARK_PRICE_COLUMNS = (
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "close_time",
)


def _parse_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise DataQualityError(f"invalid integer in {field}: {value!r}")
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise DataQualityError(f"invalid integer in {field}: {value!r}") from exc


def _parse_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataQualityError(f"invalid decimal in {field}: {value!r}") from exc
    if not parsed.is_finite():
        raise DataQualityError(f"invalid non-finite decimal in {field}: {value!r}")
    return parsed


def _interval_delta(interval: KlineInterval) -> timedelta:
    try:
        return timedelta(milliseconds=INTERVAL_MS[interval])
    except KeyError as exc:
        raise DataQualityError(f"unsupported mark-price interval: {interval}") from exc


def canonicalize_mark_price_klines(
    rows: Sequence[Sequence[object]],
    *,
    symbol: str,
    interval: KlineInterval,
    end_exclusive_ms: int,
) -> pd.DataFrame:
    """Validate Binance mark-price kline rows as closed canonical bars."""
    if not symbol:
        raise DataQualityError("symbol must not be empty")
    interval_ms = INTERVAL_MS.get(interval)
    if interval_ms is None:
        raise DataQualityError(f"unsupported mark-price interval: {interval}")
    if end_exclusive_ms <= 0:
        raise DataQualityError("end_exclusive_ms must be positive")
    if not rows:
        raise DataQualityError("mark-price dataset must contain at least one row")

    canonical_rows: list[dict[str, object]] = []
    for row in rows:
        if len(row) < 6:
            raise DataQualityError("mark-price kline row must contain at least six values")
        close_index = 6 if len(row) >= 12 else 5
        open_ms = _parse_int(row[0], field="open_time")
        close_ms = _parse_int(row[close_index], field="close_time")
        if close_ms != open_ms + interval_ms - 1:
            raise DataQualityError(f"close_time does not match {interval} candle boundaries")
        if open_ms < 0 or close_ms >= end_exclusive_ms:
            raise DataQualityError("mark-price kline is outside the closed requested range")
        canonical_rows.append(
            {
                "symbol": symbol,
                "timestamp": pd.to_datetime(open_ms, unit="ms", utc=True),
                "open": _parse_decimal(row[1], field="open"),
                "high": _parse_decimal(row[2], field="high"),
                "low": _parse_decimal(row[3], field="low"),
                "close": _parse_decimal(row[4], field="close"),
                "close_time": pd.to_datetime(close_ms, unit="ms", utc=True),
            }
        )

    canonical = pd.DataFrame(canonical_rows)
    canonical = canonicalize_bars(canonical, interval=_interval_delta(interval))
    return canonical.loc[:, MARK_PRICE_COLUMNS]


def canonicalize_funding_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    symbol: str,
    start_ms: int,
    end_exclusive_ms: int,
) -> pd.DataFrame:
    """Validate public funding events without inventing a fixed event cadence."""
    if not symbol:
        raise DataQualityError("symbol must not be empty")
    if start_ms < 0 or end_exclusive_ms <= start_ms:
        raise DataQualityError("funding range must be a positive half-open interval")
    if not rows:
        raise DataQualityError("funding dataset must contain at least one row")

    canonical_rows: list[dict[str, object]] = []
    seen_times: set[int] = set()
    for row in rows:
        if row.get("symbol") != symbol:
            raise DataQualityError("funding row symbol does not match requested symbol")
        funding_ms = _parse_int(row.get("fundingTime"), field="fundingTime")
        if not start_ms <= funding_ms < end_exclusive_ms:
            raise DataQualityError("funding event is outside the requested half-open range")
        if funding_ms in seen_times:
            raise DataQualityError("duplicate funding times are not allowed")
        seen_times.add(funding_ms)
        canonical_rows.append(
            {
                "symbol": symbol,
                "funding_time": pd.to_datetime(funding_ms, unit="ms", utc=True),
                "funding_rate": _parse_decimal(row.get("fundingRate"), field="fundingRate"),
                "funding_mark_price": _parse_decimal(row.get("markPrice"), field="markPrice"),
            }
        )

    canonical = pd.DataFrame(canonical_rows).sort_values("funding_time", kind="mergesort")
    return canonical.reset_index(drop=True).loc[:, FUNDING_COLUMNS]


def align_derivatives_to_primary(
    primary: pd.DataFrame,
    *,
    mark_price: pd.DataFrame,
    funding: pd.DataFrame,
) -> pd.DataFrame:
    """Attach exact mark bars and strictly prior funding events to primary bars."""
    if "timestamp" not in primary.columns:
        raise DataQualityError("primary frame must contain timestamp")
    primary_canonical = canonicalize_bars(
        primary,
        interval=timedelta(minutes=5),
    )
    required_mark = set(MARK_PRICE_COLUMNS)
    if not required_mark.issubset(mark_price.columns):
        missing = sorted(required_mark.difference(mark_price.columns))
        raise DataQualityError(f"mark-price frame is missing columns: {', '.join(missing)}")
    if mark_price["timestamp"].duplicated().any():
        raise DataQualityError("duplicate mark-price timestamps are not allowed")

    mark_for_merge = mark_price.loc[:, MARK_PRICE_COLUMNS].rename(
        columns={
            "symbol": "mark_symbol",
            "open": "mark_open",
            "high": "mark_high",
            "low": "mark_low",
            "close": "mark_close",
            "close_time": "mark_close_time",
        }
    )
    aligned = primary_canonical.merge(
        mark_for_merge,
        on="timestamp",
        how="left",
        sort=False,
        validate="one_to_one",
    )
    if aligned["mark_close"].isna().any():
        raise DataQualityError("mark-price coverage is incomplete for primary bars")

    required_funding = set(FUNDING_COLUMNS)
    if not required_funding.issubset(funding.columns):
        missing = sorted(required_funding.difference(funding.columns))
        raise DataQualityError(f"funding frame is missing columns: {', '.join(missing)}")
    if funding["funding_time"].duplicated().any():
        raise DataQualityError("duplicate funding times are not allowed")
    funding_for_merge = (
        funding.loc[:, FUNDING_COLUMNS]
        .rename(columns={"funding_time": "funding_event_time"})
        .sort_values("funding_event_time", kind="mergesort")
    )
    aligned["timestamp"] = pd.DatetimeIndex(aligned["timestamp"]).as_unit("ms")
    funding_for_merge["funding_event_time"] = pd.DatetimeIndex(
        funding_for_merge["funding_event_time"]
    ).as_unit("ms")
    aligned = pd.merge_asof(
        aligned.sort_values("timestamp", kind="mergesort"),
        funding_for_merge,
        left_on="timestamp",
        right_on="funding_event_time",
        direction="backward",
        allow_exact_matches=False,
    )
    return aligned.reset_index(drop=True)


__all__ = [
    "FUNDING_COLUMNS",
    "MARK_PRICE_COLUMNS",
    "align_derivatives_to_primary",
    "canonicalize_funding_rows",
    "canonicalize_mark_price_klines",
]
