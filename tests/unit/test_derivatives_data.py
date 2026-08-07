from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from autonomous_futures.data.alignment import (
    align_derivatives_to_primary,
    canonicalize_funding_rows,
    canonicalize_mark_price_klines,
)
from autonomous_futures.data.parquet import DataQualityError

START = pd.Timestamp("2026-08-07T00:00:00Z")


def _mark_rows() -> list[list[object]]:
    return [
        [
            START.value // 1_000_000,
            "100",
            "101",
            "99",
            "100.5",
            START.value // 1_000_000 + 299_999,
        ],
        [
            START.value // 1_000_000 + 300_000,
            "100.5",
            "102",
            "100",
            "101.5",
            START.value // 1_000_000 + 599_999,
        ],
        [
            START.value // 1_000_000 + 600_000,
            "101.5",
            "103",
            "101",
            "102.5",
            START.value // 1_000_000 + 899_999,
        ],
    ]


def test_mark_price_klines_are_canonical_and_closed() -> None:
    canonical = canonicalize_mark_price_klines(
        _mark_rows(),
        symbol="BTCUSDT",
        interval="5m",
        end_exclusive_ms=START.value // 1_000_000 + 900_000,
    )

    assert canonical["timestamp"].tolist() == [
        START,
        START + pd.Timedelta(minutes=5),
        START + pd.Timedelta(minutes=10),
    ]
    assert canonical["close"].tolist() == [
        Decimal("100.5"),
        Decimal("101.5"),
        Decimal("102.5"),
    ]
    assert canonical["symbol"].tolist() == ["BTCUSDT"] * 3


def test_mark_price_rejects_invalid_close_boundary() -> None:
    rows = _mark_rows()
    rows[1][-1] = START.value // 1_000_000 + 600_000

    with pytest.raises(DataQualityError, match="close_time"):
        canonicalize_mark_price_klines(
            rows,
            symbol="BTCUSDT",
            interval="5m",
            end_exclusive_ms=START.value // 1_000_000 + 900_000,
        )


def test_mark_price_accepts_full_binance_kline_response_shape() -> None:
    short_row = _mark_rows()[0]
    full_row = [
        short_row[0],
        short_row[1],
        short_row[2],
        short_row[3],
        short_row[4],
        "0",
        short_row[5],
        "0",
        1,
        "0",
        "0",
        "0",
    ]

    canonical = canonicalize_mark_price_klines(
        [full_row],
        symbol="BTCUSDT",
        interval="5m",
        end_exclusive_ms=START.value // 1_000_000 + 300_000,
    )

    assert canonical.loc[0, "close"] == Decimal("100.5")


def test_funding_events_are_sorted_and_preserve_decimal_precision() -> None:
    rows = [
        {
            "symbol": "BTCUSDT",
            "fundingTime": START.value // 1_000_000 + 28_800_000,
            "fundingRate": "-0.00007500",
            "markPrice": "100.12500000",
        },
        {
            "symbol": "BTCUSDT",
            "fundingTime": START.value // 1_000_000,
            "fundingRate": "0.00010000",
            "markPrice": "99.87500000",
        },
    ]

    canonical = canonicalize_funding_rows(
        rows,
        symbol="BTCUSDT",
        start_ms=START.value // 1_000_000,
        end_exclusive_ms=START.value // 1_000_000 + 28_800_001,
    )

    assert canonical["funding_time"].tolist() == [
        START,
        START + pd.Timedelta(hours=8),
    ]
    assert canonical["funding_rate"].tolist() == [
        Decimal("0.00010000"),
        Decimal("-0.00007500"),
    ]


def test_alignment_is_causal_and_keeps_funding_provenance() -> None:
    primary = pd.DataFrame(
        {
            "timestamp": [
                START,
                START + pd.Timedelta(minutes=5),
                START + pd.Timedelta(minutes=10),
            ],
            "close": [Decimal("100"), Decimal("101"), Decimal("102")],
        }
    )
    mark = canonicalize_mark_price_klines(
        _mark_rows(),
        symbol="BTCUSDT",
        interval="5m",
        end_exclusive_ms=START.value // 1_000_000 + 900_000,
    )
    funding = canonicalize_funding_rows(
        [
            {
                "symbol": "BTCUSDT",
                "fundingTime": START.value // 1_000_000,
                "fundingRate": "0.00010000",
                "markPrice": "100",
            },
            {
                "symbol": "BTCUSDT",
                "fundingTime": START.value // 1_000_000 + 420_000,
                "fundingRate": "0.00020000",
                "markPrice": "101",
            },
        ],
        symbol="BTCUSDT",
        start_ms=START.value // 1_000_000,
        end_exclusive_ms=START.value // 1_000_000 + 900_000,
    )

    aligned = align_derivatives_to_primary(primary, mark_price=mark, funding=funding)

    assert aligned["mark_close"].tolist() == [
        Decimal("100.5"),
        Decimal("101.5"),
        Decimal("102.5"),
    ]
    assert pd.isna(aligned.loc[0, "funding_rate"])
    assert aligned.loc[1, "funding_rate"] == Decimal("0.00010000")
    assert aligned.loc[2, "funding_rate"] == Decimal("0.00020000")
    assert pd.isna(aligned.loc[0, "funding_event_time"])
    assert aligned.loc[1, "funding_event_time"] == START
    assert aligned.loc[2, "funding_event_time"] == START + pd.Timedelta(minutes=7)
