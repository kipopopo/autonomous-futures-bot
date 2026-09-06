"""Phase 261 Milestone M1: Adversarial Stress & Security Test Suite.

Empirical challenger test suite probing:
1. Credential injection and bypass vectors (sneaky kwargs, headers, client leaking).
2. Malformed / extreme data injection (NaN, Inf, negatives, geometry inversions).
3. Timestamp jitter, 1ms drift, duplicates, non-monotonic timestamps.
4. Boundary edge cases (exact interval multiples, day rollovers, leap days, exact closing ms).
5. Fallback cascade resilience under corrupted Parquet files.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pandas as pd
import pytest

from autonomous_futures.feed.rest_client import (
    BinanceDataQualityError,
    BinancePublicRestClient,
    BinanceSecurityViolation,
    calculate_closed_bar_boundary,
    generate_deterministic_synthetic_bars,
    parse_raw_klines_to_canonical_df,
    validate_canonical_dataframe,
)

# ===========================================================================
# Helper Fixtures & Generators
# ===========================================================================


def create_valid_kline_row(
    open_time_ms: int,
    open_p: float = 100.0,
    high_p: float = 105.0,
    low_p: float = 95.0,
    close_p: float = 102.0,
    volume: float = 50.0,
    interval_ms: int = 300_000,
) -> list[Any]:
    """Generate a single well-formed 12-element Binance kline row."""
    close_time_ms = open_time_ms + interval_ms - 1
    return [
        open_time_ms,
        str(open_p),
        str(high_p),
        str(low_p),
        str(close_p),
        str(volume),
        close_time_ms,
        str(volume * close_p),  # quote volume
        100,  # trades
        str(volume * 0.5),  # taker buy base
        str(volume * 0.5 * close_p),  # taker buy quote
        "0",  # ignore
    ]


def create_valid_canonical_df(
    periods: int = 10,
    start: str = "2026-09-06 00:00:00",
    freq: str = "5min",
) -> pd.DataFrame:
    """Generate a canonical OHLCV DataFrame."""
    ts = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(periods)],
            "high": [105.0 + i for i in range(periods)],
            "low": [95.0 + i for i in range(periods)],
            "close": [102.0 + i for i in range(periods)],
            "volume": [50.0 + i * 2 for i in range(periods)],
        },
        index=pd.DatetimeIndex(ts, name="timestamp"),
    )


# ===========================================================================
# 1. Security Penetration & Credential Sneak Vectors
# ===========================================================================


class TestSecurityPenetration:
    """Probing zero-credential invariants and authentication parameter rejection."""

    def test_standard_api_key_kwarg_rejected(self) -> None:
        """Standard api_key and API_KEY must raise BinanceSecurityViolation."""
        with pytest.raises(BinanceSecurityViolation):
            BinancePublicRestClient(api_key="secret")
        with pytest.raises(BinanceSecurityViolation):
            BinancePublicRestClient(API_KEY="secret")

    def test_standard_secret_and_token_kwargs_rejected(self) -> None:
        """api_secret, token, password, auth must raise BinanceSecurityViolation."""
        for kw in ("api_secret", "secret", "token", "password", "auth", "private_key"):
            with pytest.raises(BinanceSecurityViolation):
                kwargs: dict[str, Any] = {kw: "val"}
                BinancePublicRestClient(**kwargs)

    def test_sneaky_apikey_kwarg_rejected(self) -> None:
        """Sneaky 'ApiKey' and 'apikey' kwargs must raise BinanceSecurityViolation."""
        with pytest.raises((BinanceSecurityViolation, ValueError)):
            BinancePublicRestClient(ApiKey="sneaky_key")
        with pytest.raises((BinanceSecurityViolation, ValueError)):
            BinancePublicRestClient(apikey="sneaky_key")

    def test_sneaky_x_mbx_apikey_kwarg_rejected(self) -> None:
        """Underscore variant 'x_mbx_apikey' and 'privatekey' must be rejected."""
        with pytest.raises((BinanceSecurityViolation, ValueError)):
            BinancePublicRestClient(x_mbx_apikey="sneaky_key")
        with pytest.raises((BinanceSecurityViolation, ValueError)):
            BinancePublicRestClient(privatekey="sneaky_key")

    def test_sneaky_header_auth_rejected(self) -> None:
        """Header variations like X-API-KEY and ApiKey must be rejected."""
        with pytest.raises(BinanceSecurityViolation):
            BinancePublicRestClient(headers={"X-API-KEY": "secret"})
        with pytest.raises(BinanceSecurityViolation):
            BinancePublicRestClient(headers={"ApiKey": "secret"})

    def test_external_client_with_auth_header_rejected(self) -> None:
        """Passing an external httpx.AsyncClient with X-MBX-APIKEY must be rejected."""

        async def _run() -> None:
            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json=[])

            transport = httpx.MockTransport(handler)
            external_client = httpx.AsyncClient(
                base_url="https://fapi.binance.com",
                transport=transport,
                headers={"X-MBX-APIKEY": "leaked_secret"},
            )

            # Constructor or request execution MUST reject an authenticated client
            with pytest.raises(BinanceSecurityViolation):
                client = BinancePublicRestClient(client=external_client)
                await client.fetch_raw_klines("BTCUSDT", limit=1)

        asyncio.run(_run())

    def test_external_client_with_auth_tuple_rejected(self) -> None:
        """Passing an external httpx.AsyncClient with auth credentials must be rejected."""
        external_client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            auth=("user", "password"),
        )
        with pytest.raises(BinanceSecurityViolation):
            BinancePublicRestClient(client=external_client)


# ===========================================================================
# 2. Adversarial Kline Data Injection
# ===========================================================================


class TestAdversarialKlineDataInjection:
    """Probing parser and validator against corrupted, non-finite, and inverted prices."""

    @pytest.mark.parametrize(
        "bad_val",
        [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, -99999.0],
    )
    @pytest.mark.parametrize("col", ["open", "high", "low", "close"])
    def test_validate_df_rejects_bad_ohlc_values(self, col: str, bad_val: float) -> None:
        """Every OHLC column must reject NaN, +/-Inf, 0.0, and negative numbers."""
        df = create_valid_canonical_df()
        df.loc[df.index[2], col] = bad_val
        with pytest.raises(BinanceDataQualityError):
            validate_canonical_dataframe(df)

    @pytest.mark.parametrize("bad_vol", [float("nan"), float("inf"), float("-inf"), -0.001, -100.0])
    def test_validate_df_rejects_bad_volume(self, bad_vol: float) -> None:
        """Volume column must reject NaN, +/-Inf, and negative values."""
        df = create_valid_canonical_df()
        df.loc[df.index[2], "volume"] = bad_vol
        with pytest.raises(BinanceDataQualityError):
            validate_canonical_dataframe(df)

    def test_validate_df_accepts_zero_volume(self) -> None:
        """Zero volume is valid on illiquid candles."""
        df = create_valid_canonical_df()
        df.loc[df.index[2], "volume"] = 0.0
        validate_canonical_dataframe(df)  # Should not raise

    def test_validate_df_rejects_inverted_high_low(self) -> None:
        """High < Low must be rejected."""
        df = create_valid_canonical_df()
        df.loc[df.index[2], "high"] = 80.0
        df.loc[df.index[2], "low"] = 120.0
        with pytest.raises(BinanceDataQualityError, match=r"Candle geometry error"):
            validate_canonical_dataframe(df)

    def test_validate_df_rejects_high_below_open(self) -> None:
        """High < Open must be rejected."""
        df = create_valid_canonical_df()
        df.loc[df.index[2], "open"] = 110.0
        df.loc[df.index[2], "high"] = 105.0
        with pytest.raises(BinanceDataQualityError, match=r"Candle geometry error"):
            validate_canonical_dataframe(df)

    def test_validate_df_rejects_high_below_close(self) -> None:
        """High < Close must be rejected."""
        df = create_valid_canonical_df()
        df.loc[df.index[2], "close"] = 110.0
        df.loc[df.index[2], "high"] = 105.0
        with pytest.raises(BinanceDataQualityError, match=r"Candle geometry error"):
            validate_canonical_dataframe(df)

    def test_validate_df_rejects_low_above_open(self) -> None:
        """Low > Open must be rejected."""
        df = create_valid_canonical_df()
        df.loc[df.index[2], "open"] = 90.0
        df.loc[df.index[2], "low"] = 95.0
        with pytest.raises(BinanceDataQualityError, match=r"Candle geometry error"):
            validate_canonical_dataframe(df)

    def test_validate_df_rejects_low_above_close(self) -> None:
        """Low > Close must be rejected."""
        df = create_valid_canonical_df()
        df.loc[df.index[2], "close"] = 90.0
        df.loc[df.index[2], "low"] = 95.0
        with pytest.raises(BinanceDataQualityError, match=r"Candle geometry error"):
            validate_canonical_dataframe(df)

    @pytest.mark.parametrize(
        "bad_field_idx, bad_val",
        [
            (1, "NaN"),
            (1, "Infinity"),
            (1, "-Infinity"),
            (1, "0.0"),
            (1, "-10.0"),
            (1, "invalid_num"),
            (2, "0.0"),
            (3, "-5.0"),
            (4, "NaN"),
            (5, "-1.0"),
            (5, "NaN"),
        ],
    )
    def test_parse_raw_klines_rejects_corrupt_strings(
        self, bad_field_idx: int, bad_val: str
    ) -> None:
        """Raw klines with bad strings must raise BinanceDataQualityError."""
        row = create_valid_kline_row(1700000000000)
        row[bad_field_idx] = bad_val
        with pytest.raises(BinanceDataQualityError):
            parse_raw_klines_to_canonical_df([row], only_closed=False)

    def test_parse_raw_klines_handles_astronomical_timestamp(self) -> None:
        """Astronomical epoch timestamp must raise BinanceDataQualityError."""
        bad_row = create_valid_kline_row(10**20)
        with pytest.raises(BinanceDataQualityError):
            parse_raw_klines_to_canonical_df([bad_row], only_closed=False)

    def test_validate_relational_geometry_error_message_accuracy(self) -> None:
        """In relational mode, the error message must report the violating row's high, not row 0."""
        ts = pd.date_range("2026-09-06 00:00:00", periods=5, freq="5min", tz="UTC")
        df = pd.DataFrame(
            {
                "timestamp": ts,
                "open": [100.0] * 5,
                "high": [105.0, 105.0, 80.0, 105.0, 105.0],  # Row 2 high is 80.0 < low (90.0)
                "low": [90.0] * 5,
                "close": [102.0] * 5,
                "volume": [10.0] * 5,
            }
        )
        with pytest.raises(BinanceDataQualityError) as exc_info:
            validate_canonical_dataframe(df)

        msg = str(exc_info.value)
        # Violating row high is 80.0; it must NOT report high (105.0) from row 0
        assert "high (80.0)" in msg or "80" in msg


# ===========================================================================
# 3. Timestamp Jitter, Drift & Discontinuity
# ===========================================================================


class TestTimestampJitterAndDrift:
    """Probing strict 300s spacing, drift tolerance, and ordering."""

    def test_under_spaced_jitter_299s_rejected(self) -> None:
        """299s interval (1 second short) must be rejected with 'timestamp gap'."""
        ts = [
            pd.Timestamp("2026-09-06 00:00:00", tz="UTC"),
            pd.Timestamp("2026-09-06 00:04:59", tz="UTC"),  # 299s
            pd.Timestamp("2026-09-06 00:09:59", tz="UTC"),
        ]
        df = pd.DataFrame(
            {
                "open": [100.0] * 3,
                "high": [105.0] * 3,
                "low": [95.0] * 3,
                "close": [102.0] * 3,
                "volume": [10.0] * 3,
            },
            index=pd.DatetimeIndex(ts),
        )
        with pytest.raises(BinanceDataQualityError, match=r"timestamp gap"):
            validate_canonical_dataframe(df)

    def test_over_spaced_jitter_301s_rejected(self) -> None:
        """301s interval (1 second long) must be rejected with 'timestamp gap'."""
        ts = [
            pd.Timestamp("2026-09-06 00:00:00", tz="UTC"),
            pd.Timestamp("2026-09-06 00:05:01", tz="UTC"),  # 301s
            pd.Timestamp("2026-09-06 00:10:01", tz="UTC"),
        ]
        df = pd.DataFrame(
            {
                "open": [100.0] * 3,
                "high": [105.0] * 3,
                "low": [95.0] * 3,
                "close": [102.0] * 3,
                "volume": [10.0] * 3,
            },
            index=pd.DatetimeIndex(ts),
        )
        with pytest.raises(BinanceDataQualityError, match=r"timestamp gap"):
            validate_canonical_dataframe(df)

    def test_millisecond_drift_rejected(self) -> None:
        """1 millisecond drift (300,001 ms) must be rejected with 'timestamp gap'."""
        ts = [
            pd.Timestamp("2026-09-06 00:00:00.000", tz="UTC"),
            pd.Timestamp("2026-09-06 00:05:00.001", tz="UTC"),
        ]
        df = pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [105.0, 105.0],
                "low": [95.0, 95.0],
                "close": [102.0, 102.0],
                "volume": [10.0, 10.0],
            },
            index=pd.DatetimeIndex(ts),
        )
        with pytest.raises(BinanceDataQualityError, match=r"timestamp gap"):
            validate_canonical_dataframe(df)

    def test_duplicate_timestamps_rejected(self) -> None:
        """Identical timestamps must be rejected with 'duplicate timestamps'."""
        ts = [
            pd.Timestamp("2026-09-06 00:00:00", tz="UTC"),
            pd.Timestamp("2026-09-06 00:00:00", tz="UTC"),
        ]
        df = pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [105.0, 105.0],
                "low": [95.0, 95.0],
                "close": [102.0, 102.0],
                "volume": [10.0, 10.0],
            },
            index=pd.DatetimeIndex(ts),
        )
        with pytest.raises(BinanceDataQualityError, match=r"duplicate timestamps are not allowed"):
            validate_canonical_dataframe(df)

    def test_non_monotonic_timestamps_rejected(self) -> None:
        """Inverted timestamps must be rejected with 'monotonically increasing'."""
        ts = [
            pd.Timestamp("2026-09-06 00:05:00", tz="UTC"),
            pd.Timestamp("2026-09-06 00:00:00", tz="UTC"),
        ]
        df = pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [105.0, 105.0],
                "low": [95.0, 95.0],
                "close": [102.0, 102.0],
                "volume": [10.0, 10.0],
            },
            index=pd.DatetimeIndex(ts),
        )
        with pytest.raises(
            BinanceDataQualityError, match=r"DatetimeIndex must be monotonically increasing"
        ):
            validate_canonical_dataframe(df)

    def test_naive_timezone_rejected(self) -> None:
        """Timezone-naive DatetimeIndex must be rejected."""
        ts = pd.date_range("2026-09-06 00:00:00", periods=5, freq="5min")  # Naive
        df = pd.DataFrame(
            {
                "open": [100.0] * 5,
                "high": [105.0] * 5,
                "low": [95.0] * 5,
                "close": [102.0] * 5,
                "volume": [10.0] * 5,
            },
            index=ts,
        )
        with pytest.raises(
            BinanceDataQualityError, match=r"DatetimeIndex must be timezone-aware UTC"
        ):
            validate_canonical_dataframe(df)

    def test_non_utc_timezone_rejected(self) -> None:
        """DatetimeIndex in US/Eastern or Asia/Tokyo must be rejected."""
        ts = pd.date_range("2026-09-06 00:00:00", periods=5, freq="5min", tz="Asia/Tokyo")
        df = pd.DataFrame(
            {
                "open": [100.0] * 5,
                "high": [105.0] * 5,
                "low": [95.0] * 5,
                "close": [102.0] * 5,
                "volume": [10.0] * 5,
            },
            index=ts,
        )
        with pytest.raises(
            BinanceDataQualityError, match=r"DatetimeIndex must be timezone-aware UTC"
        ):
            validate_canonical_dataframe(df)


# ===========================================================================
# 4. Boundary Edge Conditions & Unclosed Candle Isolation
# ===========================================================================


class TestBoundaryEdgeCases:
    """Probing closed bar calculations across boundary transitions."""

    def test_calculate_closed_bar_boundary_exact_multiple(self) -> None:
        """At exact multiple of 300,000ms (12:05:00.000), boundary is 12:04:59.999."""
        t_boundary = 1700000100000  # exact integer multiple of 300_000
        assert t_boundary % 300_000 == 0
        boundary = calculate_closed_bar_boundary(t_boundary, 300_000)
        assert boundary == t_boundary - 1
        assert boundary % 300_000 == 299_999

    def test_calculate_closed_bar_boundary_one_ms_before_boundary(self) -> None:
        """At 1ms before boundary (12:04:59.999), boundary is 11:59:59.999."""
        t_boundary = 1700000100000
        boundary = calculate_closed_bar_boundary(t_boundary - 1, 300_000)
        assert boundary == t_boundary - 300_000 - 1

    def test_calculate_closed_bar_boundary_one_ms_after_boundary(self) -> None:
        """At 1ms after boundary (12:05:00.001), boundary is 12:04:59.999."""
        t_boundary = 1700000100000
        boundary = calculate_closed_bar_boundary(t_boundary + 1, 300_000)
        assert boundary == t_boundary - 1

    def test_calculate_closed_bar_boundary_midnight_rollover(self) -> None:
        """Day rollover at 00:00:00.000 UTC aligns exactly to preceding 23:59:59.999."""
        dt_midnight = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        now_ms = int(dt_midnight.timestamp() * 1000)
        boundary = calculate_closed_bar_boundary(now_ms, 300_000)
        expected_dt = datetime(2026, 9, 6, 23, 59, 59, 999000, tzinfo=UTC)
        assert boundary == int(expected_dt.timestamp() * 1000)

    def test_calculate_closed_bar_boundary_leap_day(self) -> None:
        """Leap day (Feb 29) boundary calculation is exact."""
        dt_leap = datetime(2024, 2, 29, 12, 0, 0, tzinfo=UTC)
        now_ms = int(dt_leap.timestamp() * 1000)
        boundary = calculate_closed_bar_boundary(now_ms, 300_000)
        expected_dt = datetime(2024, 2, 29, 11, 59, 59, 999000, tzinfo=UTC)
        assert boundary == int(expected_dt.timestamp() * 1000)

    def test_calculate_closed_bar_boundary_invalid_inputs(self) -> None:
        """Negative now_ms or non-positive interval_ms must raise ValueError."""
        with pytest.raises(ValueError, match=r"now_ms must be non-negative"):
            calculate_closed_bar_boundary(-100, 300_000)
        with pytest.raises(ValueError, match=r"interval_ms must be strictly positive"):
            calculate_closed_bar_boundary(1000, 0)
        with pytest.raises(ValueError, match=r"interval_ms must be strictly positive"):
            calculate_closed_bar_boundary(1000, -300_000)

    def test_parse_raw_klines_excludes_in_progress_candle_at_exact_closing_ms(self) -> None:
        """At exact close_time_ms, the bar is still active and must be excluded."""
        # Candle 1: 12:00:00.000 to 12:04:59.999 (aligned to 5m boundary)
        open_ms_1 = 1700000100000
        close_ms_1 = open_ms_1 + 299999
        row_1 = create_valid_kline_row(open_ms_1)

        # Candle 2: 12:05:00.000 to 12:09:59.999
        open_ms_2 = open_ms_1 + 300000
        close_ms_2 = open_ms_2 + 299999
        row_2 = create_valid_kline_row(open_ms_2)

        # At close_ms_2 (12:09:59.999), Candle 2 has not finished; it finishes at 12:10:00.000
        boundary = calculate_closed_bar_boundary(close_ms_2, 300_000)
        assert boundary == close_ms_1

        # parse_raw_klines_to_canonical_df must ONLY include Candle 1
        df = parse_raw_klines_to_canonical_df(
            [row_1, row_2],
            only_closed=True,
            current_time_ms=close_ms_2,
        )
        assert len(df) == 1
        assert df.index[-1].timestamp() * 1000 == open_ms_1


# ===========================================================================
# 5. Offline Fallback Cascade Resilience
# ===========================================================================


class TestFallbackCascadeResilience:
    """Probing fallback cascade behavior under corrupt data and edge conditions."""

    def test_deterministic_synthetic_bars_properties(self) -> None:
        """Synthetic bars must satisfy all canonical DataFrame invariants."""
        df = generate_deterministic_synthetic_bars("BTCUSDT", bars_count=100)
        assert len(df) == 100
        assert isinstance(df.index, pd.DatetimeIndex)
        assert str(df.index.tz) == "UTC"
        assert df.index.is_monotonic_increasing
        assert df.index.is_unique
        # Spacing exactly 300s
        diffs = df.index[1:] - df.index[:-1]
        assert (diffs == pd.Timedelta(minutes=5)).all()
        # Cleanliness
        validate_canonical_dataframe(df)

    def test_deterministic_synthetic_bars_all_symbols(self) -> None:
        """Synthetic bars for all portfolio symbols (BTC, ETH, SOL, DOGE) must be valid."""
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            df = generate_deterministic_synthetic_bars(sym, bars_count=50)
            validate_canonical_dataframe(df)
            assert (df["close"] > 0).all()
            assert (df["volume"] > 0).all()
