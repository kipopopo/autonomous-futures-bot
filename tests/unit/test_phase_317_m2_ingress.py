"""Phase 317 Milestone 2 Unit Tests: Multi-Timeframe Kline Ingress, Parser & Synchronizer.

Verifies:
- Suite 1: TestKlineDataParser (Exact Decimal precision, envelopes, strict validation, immutability)
- Suite 2: TestChronologicalGapHandlingAndAlignment (Sorting, deduplication, 2-tier gap repair)
- Suite 3: TestMultiPairMultiTimeframeBuffer (40 ring buffers, maxlen=150, < 5MB memory footprint)
- Suite 4: TestRefreshIntervalScheduling (Hierarchical TTL cache, 75%+ reduction)
- Suite 5: TestConcurrencySemaphoreThrottle (Semaphore(5) concurrency bound)
- Suite 6: TestPublicKlineEndpointFallback (Primary error fallback to public REST)
- Suite 7: TestContinuousTraderSequencerIntegration (Integration with trader & ICT)
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from autonomous_futures.execution.continuous_trader import ContinuousSelfDrivingTrader
from autonomous_futures.feed.kline_parser import KlineParsingError, parse_raw_kline
from autonomous_futures.feed.kline_sequencer import (
    ACTIVE_PAIRS,
    ACTIVE_TIMEFRAMES,
    MultiTimeframeCandleSequencer,
)
from autonomous_futures.feed.kline_synchronizer import (
    INTERVAL_MILLISECONDS,
    ChronologicalCandleSynchronizer,
)
from autonomous_futures.strategy.ict_mmxm import Candle, IctMmxmEngine, TwinsStep

# =============================================================================
# Helper Utilities & Fixtures
# =============================================================================


def _build_raw_kline(
    ts_ms: int,
    open_p: str = "100.0",
    high_p: str = "105.0",
    low_p: str = "98.0",
    close_p: str = "104.0",
    volume: str = "1500.0",
) -> list[Any]:
    return [
        ts_ms,
        open_p,
        high_p,
        low_p,
        close_p,
        volume,
        ts_ms + 59999,
        "156000.0",
        120,
        "750.0",
        "78000.0",
        "0",
    ]


def _build_candle(ts_ms: int, p: str = "100.0", vol: str = "500.0") -> Candle:
    d = Decimal(p)
    return Candle(
        timestamp_ms=ts_ms,
        open=d,
        high=d + Decimal("2.0"),
        low=d - Decimal("2.0"),
        close=d + Decimal("1.0"),
        volume=Decimal(vol),
    )


# =============================================================================
# Suite 1: TestKlineDataParser
# =============================================================================


class TestKlineDataParser:
    """Verifies strict Decimal parsing, envelope validation, and immutability of Candle."""

    def test_parse_raw_binance_kline_array_valid(self) -> None:
        raw = _build_raw_kline(1700000000000, "185.50", "188.00", "184.20", "187.10", "2500.0")
        candle = parse_raw_kline(raw)
        assert isinstance(candle, Candle)
        assert candle.timestamp_ms == 1700000000000
        assert candle.open == Decimal("185.50")
        assert candle.high == Decimal("188.00")
        assert candle.low == Decimal("184.20")
        assert candle.close == Decimal("187.10")
        assert candle.volume == Decimal("2500.0")

    def test_parse_raw_kline_strict_decimal_precision(self) -> None:
        raw = _build_raw_kline(
            1700000000000,
            "0.0000123456789",
            "0.0000123456799",
            "0.0000123456770",
            "0.0000123456780",
            "12345678.987654321",
        )
        candle = parse_raw_kline(raw)
        assert candle.open == Decimal("0.0000123456789")
        assert candle.volume == Decimal("12345678.987654321")

    def test_parse_raw_kline_rejects_negative_prices(self) -> None:
        with pytest.raises(KlineParsingError, match="strictly positive"):
            parse_raw_kline(_build_raw_kline(1700000000000, "-10.0", "10.0", "-15.0", "5.0"))

    def test_parse_raw_kline_rejects_zero_prices(self) -> None:
        with pytest.raises(KlineParsingError, match="strictly positive"):
            parse_raw_kline(_build_raw_kline(1700000000000, "0.0", "10.0", "0.0", "5.0"))

    def test_parse_raw_kline_rejects_inverted_envelope_high_less_than_low(self) -> None:
        with pytest.raises(KlineParsingError, match="Inverted high/low"):
            parse_raw_kline(_build_raw_kline(1700000000000, "100.0", "95.0", "105.0", "100.0"))

    def test_parse_raw_kline_rejects_high_less_than_open(self) -> None:
        with pytest.raises(KlineParsingError, match="High .* must be >="):
            parse_raw_kline(_build_raw_kline(1700000000000, "110.0", "105.0", "90.0", "100.0"))

    def test_parse_raw_kline_rejects_high_less_than_close(self) -> None:
        with pytest.raises(KlineParsingError, match="High .* must be >="):
            parse_raw_kline(_build_raw_kline(1700000000000, "95.0", "100.0", "90.0", "105.0"))

    def test_parse_raw_kline_rejects_low_greater_than_open(self) -> None:
        with pytest.raises(KlineParsingError, match="Low .* must be <="):
            parse_raw_kline(_build_raw_kline(1700000000000, "90.0", "110.0", "95.0", "100.0"))

    def test_parse_raw_kline_rejects_low_greater_than_close(self) -> None:
        with pytest.raises(KlineParsingError, match="Low .* must be <="):
            parse_raw_kline(_build_raw_kline(1700000000000, "100.0", "110.0", "95.0", "90.0"))

    def test_parse_raw_kline_rejects_negative_volume(self) -> None:
        with pytest.raises(KlineParsingError, match="Volume must be non-negative"):
            parse_raw_kline(
                _build_raw_kline(1700000000000, "100.0", "105.0", "95.0", "102.0", volume="-5.0")
            )

    def test_parse_raw_kline_accepts_zero_volume(self) -> None:
        candle = parse_raw_kline(
            _build_raw_kline(1700000000000, "100.0", "105.0", "95.0", "102.0", volume="0.0")
        )
        assert candle.volume == Decimal("0.0")

    def test_parse_raw_kline_rejects_truncated_array(self) -> None:
        with pytest.raises(KlineParsingError, match="requires >= 6 elements"):
            parse_raw_kline([1700000000000, "100.0", "105.0"])

    def test_parse_raw_kline_rejects_invalid_timestamp(self) -> None:
        with pytest.raises(KlineParsingError, match="Invalid timestamp_ms"):
            parse_raw_kline(_build_raw_kline(-500, "100.0", "105.0", "95.0", "102.0"))

    def test_parse_kline_from_mapping_open_time(self) -> None:
        payload = {
            "open_time": 1700000000000,
            "open": "100.0",
            "high": "105.0",
            "low": "95.0",
            "close": "102.0",
            "volume": "500.0",
        }
        candle = parse_raw_kline(payload)
        assert candle.timestamp_ms == 1700000000000
        assert candle.close == Decimal("102.0")

    def test_parse_kline_from_mapping_timestamp_ms(self) -> None:
        payload = {
            "timestamp_ms": 1700000000000,
            "open": "100.0",
            "high": "105.0",
            "low": "95.0",
            "close": "102.0",
            "volume": "500.0",
        }
        candle = parse_raw_kline(payload)
        assert candle.timestamp_ms == 1700000000000

    def test_parse_kline_from_mapping_websocket_format(self) -> None:
        payload = {
            "t": 1700000000000,
            "o": "100.0",
            "h": "105.0",
            "l": "95.0",
            "c": "102.0",
            "v": "500.0",
        }
        candle = parse_raw_kline(payload)
        assert candle.timestamp_ms == 1700000000000
        assert candle.open == Decimal("100.0")
        assert candle.high == Decimal("105.0")
        assert candle.low == Decimal("95.0")
        assert candle.close == Decimal("102.0")
        assert candle.volume == Decimal("500.0")

    def test_parse_kline_from_mapping_missing_required_fields(self) -> None:
        payload = {"open_time": 1700000000000, "open": "100.0", "close": "102.0"}
        with pytest.raises(KlineParsingError, match="Missing required OHLCV field"):
            parse_raw_kline(payload)

    def test_parse_kline_from_mapping_missing_timestamp(self) -> None:
        payload = {
            "open": "100.0",
            "high": "105.0",
            "low": "95.0",
            "close": "102.0",
            "volume": "500.0",
        }
        with pytest.raises(KlineParsingError, match="Missing timestamp"):
            parse_raw_kline(payload)

    def test_parse_kline_from_mapping_invalid_numeric_values(self) -> None:
        payload = {
            "t": 1700000000000,
            "o": "not_a_number",
            "h": "105.0",
            "l": "95.0",
            "c": "102.0",
            "v": "500.0",
        }
        with pytest.raises(KlineParsingError, match="Numeric parse failure"):
            parse_raw_kline(payload)

    def test_parse_kline_rejects_unsupported_payload_type(self) -> None:
        with pytest.raises(KlineParsingError, match="Unsupported kline payload type"):
            parse_raw_kline(cast(Any, 12345))

    def test_candle_immutability(self) -> None:
        candle = parse_raw_kline(_build_raw_kline(1700000000000))
        with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
            candle.close = Decimal("200.0")  # type: ignore

    def test_candle_directional_properties(self) -> None:
        bull = parse_raw_kline(_build_raw_kline(1700000000000, "100.0", "105.0", "99.0", "104.0"))
        bear = parse_raw_kline(_build_raw_kline(1700000000000, "104.0", "105.0", "99.0", "100.0"))
        assert bull.is_bullish is True and bull.is_bearish is False
        assert bear.is_bearish is True and bear.is_bullish is False

    def test_candle_doji_neutral_properties(self) -> None:
        doji = parse_raw_kline(_build_raw_kline(1700000000000, "100.0", "105.0", "95.0", "100.0"))
        assert doji.is_bullish is False
        assert doji.is_bearish is False


# =============================================================================
# Suite 2: TestChronologicalGapHandlingAndAlignment
# =============================================================================


class TestChronologicalGapHandlingAndAlignment:
    """Verifies chronological sorting, deduplication, and 2-tier gap repair."""

    def test_monotonic_sorting_and_deduplication(self) -> None:
        syncer = ChronologicalCandleSynchronizer()
        c1 = _build_candle(1700000060000, "101.0")
        c2 = _build_candle(1700000000000, "100.0")
        c2_dup = _build_candle(1700000000000, "100.5")  # Duplicate timestamp
        res = syncer.synchronize("BTCUSDT", "1m", [c1, c2, c2_dup])
        assert len(res.candles) == 2
        assert res.candles[0].timestamp_ms == 1700000000000
        assert res.candles[0].open == Decimal("100.5")  # Latest duplicate retained
        assert res.candles[1].timestamp_ms == 1700000060000

    def test_consecutive_continuity_no_gaps(self) -> None:
        syncer = ChronologicalCandleSynchronizer()
        c0 = _build_candle(1700000000000, "100.0")
        c1 = _build_candle(1700000060000, "101.0")
        c2 = _build_candle(1700000120000, "102.0")
        res = syncer.synchronize("BTCUSDT", "1m", [c0, c1, c2])
        assert res.gaps_detected == 0
        assert res.bars_interpolated == 0
        assert res.has_unrepaired_gap is False
        assert len(res.candles) == 3

    def test_single_bar_gap_synthetic_flat_interpolation(self) -> None:
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        c0 = _build_candle(1700000000000, "100.0")
        c2 = _build_candle(1700000120000, "105.0")
        res = syncer.synchronize("BTCUSDT", "1m", [c0, c2])
        assert res.gaps_detected == 1
        assert res.bars_interpolated == 1
        assert res.has_unrepaired_gap is False
        assert len(res.candles) == 3
        synth = res.candles[1]
        assert synth.timestamp_ms == 1700000060000
        assert synth.open == c0.close
        assert synth.high == c0.close
        assert synth.low == c0.close
        assert synth.close == c0.close
        assert synth.volume == Decimal("0")

    def test_two_bar_gap_synthetic_interpolation(self) -> None:
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        c0 = _build_candle(1700000000000, "100.0")
        c3 = _build_candle(1700000180000, "108.0")  # Missing 2 bars
        res = syncer.synchronize("SOLUSDT", "1m", [c0, c3])
        assert res.gaps_detected == 1
        assert res.bars_interpolated == 2
        assert res.has_unrepaired_gap is False
        assert len(res.candles) == 4

    def test_three_bar_gap_exceeding_threshold_not_interpolated(self) -> None:
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        c0 = _build_candle(1700000000000, "100.0")
        c4 = _build_candle(1700000240000, "110.0")  # Missing 3 bars > max 2
        res = syncer.synchronize("SOLUSDT", "1m", [c0, c4])
        assert res.gaps_detected == 1
        assert res.bars_interpolated == 0
        assert res.has_unrepaired_gap is True
        assert len(res.candles) == 2

    def test_large_gap_exceeding_threshold_not_interpolated(self) -> None:
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        c0 = _build_candle(1700000000000, "100.0")
        c11 = _build_candle(1700000660000, "120.0")
        res = syncer.synchronize("ETHUSDT", "1m", [c0, c11])
        assert res.gaps_detected == 1
        assert res.bars_interpolated == 0
        assert res.has_unrepaired_gap is True
        assert len(res.candles) == 2

    def test_empty_candle_sequence_safety(self) -> None:
        syncer = ChronologicalCandleSynchronizer()
        res = syncer.synchronize("BNBUSDT", "5m", [])
        assert len(res.candles) == 0
        assert res.gaps_detected == 0
        assert res.bars_interpolated == 0
        assert res.has_unrepaired_gap is False

    def test_single_candle_sequence_safety(self) -> None:
        syncer = ChronologicalCandleSynchronizer()
        c = _build_candle(1700000000000, "100.0")
        res = syncer.synchronize("BNBUSDT", "5m", [c])
        assert len(res.candles) == 1
        assert res.gaps_detected == 0
        assert res.bars_interpolated == 0
        assert res.has_unrepaired_gap is False

    def test_timeframe_interval_ms_validation(self) -> None:
        syncer = ChronologicalCandleSynchronizer()
        assert syncer.get_interval_ms("1m") == 60_000
        assert syncer.get_interval_ms("5m") == 300_000
        assert syncer.get_interval_ms("15m") == 900_000
        assert syncer.get_interval_ms("1h") == 3_600_000
        assert syncer.get_interval_ms("4h") == 14_400_000

    def test_unsupported_interval_error(self) -> None:
        syncer = ChronologicalCandleSynchronizer()
        with pytest.raises(ValueError, match="Unsupported interval"):
            syncer.get_interval_ms("2h")


# =============================================================================
# Suite 3: TestMultiPairMultiTimeframeBuffer
# =============================================================================


class TestMultiPairMultiTimeframeBuffer:
    """Verifies buffer ring initialization across all 8 active pairs and memory bounds."""

    def test_buffer_initialization_all_8_pairs_and_5_timeframes(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        assert len(sequencer.symbols) == len(ACTIVE_PAIRS)
        assert set(sequencer.symbols) == set(ACTIVE_PAIRS)
        assert len(sequencer.timeframes) == 5
        assert len(sequencer.buffers) == len(ACTIVE_PAIRS) * len(ACTIVE_TIMEFRAMES)
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                assert (sym, tf) in sequencer.buffers
                assert isinstance(sequencer.buffers[(sym, tf)], deque)
                assert sequencer.buffers[(sym, tf)].maxlen == 250

    def test_bounded_ring_buffer_eviction(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw, max_buffer_bars=5)
        buf = sequencer.buffers[("BTCUSDT", "1m")]
        for i in range(10):
            buf.append(_build_candle(1700000000000 + i * 60000, str(100 + i)))
        assert len(buf) == 5
        assert buf[0].timestamp_ms == 1700000000000 + 5 * 60000
        assert buf[-1].timestamp_ms == 1700000000000 + 9 * 60000

    def test_memory_footprint_under_5mb(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw, max_buffer_bars=150)
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = sequencer.buffers[(sym, tf)]
                for i in range(150):
                    buf.append(_build_candle(1700000000000 + i * 60000, "150.0"))

        total_bytes = sequencer.total_memory_bytes()
        # 5 MB = 5,242,880 bytes
        assert total_bytes < 5_242_880, f"Memory footprint {total_bytes} bytes exceeds 5MB ceiling!"

    def test_get_candles_returns_safe_copy(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        buf = sequencer.buffers[("SOLUSDT", "15m")]
        c = _build_candle(1700000000000, "150.0")
        buf.append(c)
        snapshot = sequencer.get_candles("SOLUSDT", "15m")
        assert len(snapshot) == 1
        snapshot.clear()
        assert len(sequencer.buffers[("SOLUSDT", "15m")]) == 1

    def test_get_candles_case_insensitive(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        buf = sequencer.buffers[("SOLUSDT", "15m")]
        buf.append(_build_candle(1700000000000, "150.0"))
        candles_lower = sequencer.get_candles("solusdt", "15m")
        candles_upper = sequencer.get_candles("SOLUSDT", "15m")
        assert len(candles_lower) == 1
        assert len(candles_upper) == 1

    def test_get_multi_tf_candles_tuple_contract(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        tup = sequencer.get_multi_tf_candles("BTCUSDT")
        assert isinstance(tup, tuple)
        assert len(tup) == 5
        c4h, c1h, c15m, c5m, c1m = tup
        assert isinstance(c4h, list)
        assert isinstance(c1h, list)
        assert isinstance(c15m, list)
        assert isinstance(c5m, list)
        assert isinstance(c1m, list)

    def test_get_all_timeframes_dict_contract(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        mapping = sequencer.get_all_timeframes("ETHUSDT")
        assert isinstance(mapping, dict)
        assert set(mapping.keys()) == set(ACTIVE_TIMEFRAMES)

    def test_is_warmed_up_verification(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        assert sequencer.is_warmed_up("BTCUSDT", min_bars=5) is False
        for tf in ACTIVE_TIMEFRAMES:
            for i in range(10):
                sequencer.buffers[("BTCUSDT", tf)].append(_build_candle(1700000000000 + i * 60000))
        assert sequencer.is_warmed_up("BTCUSDT", min_bars=5) is True


# =============================================================================
# Suite 4: TestRefreshIntervalScheduling
# =============================================================================


class TestRefreshIntervalScheduling:
    """Verifies hierarchical TTL invalidation and API request reduction."""

    def test_ttl_cache_invalidation_matrix(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        now = 100000.0

        for k in sequencer.last_fetch_ts:
            sequencer.last_fetch_ts[k] = now
            sequencer.buffers[k].append(_build_candle(1700000000000))

        # At now + 10s: No series expired
        assert sequencer.is_cache_expired("BTCUSDT", "1m", now + 10.0) is False
        assert sequencer.is_cache_expired("BTCUSDT", "5m", now + 10.0) is False

        # At now + 16s: 1m expired (TTL=15s), others still valid
        assert sequencer.is_cache_expired("BTCUSDT", "1m", now + 16.0) is True
        assert sequencer.is_cache_expired("BTCUSDT", "5m", now + 16.0) is False
        assert sequencer.is_cache_expired("BTCUSDT", "15m", now + 16.0) is False

        # At now + 65s: 1m and 5m expired (TTL=60s), 15m/1h/4h valid
        assert sequencer.is_cache_expired("BTCUSDT", "5m", now + 65.0) is True
        assert sequencer.is_cache_expired("BTCUSDT", "15m", now + 65.0) is False

        # At now + 305s: 15m expired (TTL=300s), 1h/4h valid
        assert sequencer.is_cache_expired("BTCUSDT", "15m", now + 305.0) is True
        assert sequencer.is_cache_expired("BTCUSDT", "1h", now + 305.0) is False

        # At now + 905s: 1h expired (TTL=900s), 4h valid
        assert sequencer.is_cache_expired("BTCUSDT", "1h", now + 905.0) is True
        assert sequencer.is_cache_expired("BTCUSDT", "4h", now + 905.0) is False

        # At now + 3605s: 4h expired (TTL=3600s)
        assert sequencer.is_cache_expired("BTCUSDT", "4h", now + 3605.0) is True

    def test_empty_buffer_is_cache_expired(self) -> None:
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        # Even if last_fetch_ts is fresh, empty buffer should expire
        sequencer.last_fetch_ts[("SOLUSDT", "15m")] = time.time()
        assert sequencer.is_cache_expired("SOLUSDT", "15m", time.time()) is True

    @pytest.mark.anyio
    async def test_refresh_due_candles_request_reduction(self) -> None:
        mock_gw = AsyncMock()
        mock_gw.get_klines.return_value = [_build_raw_kline(1700000000000)]
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)

        # 1st cycle: Uninitialized buffers -> All 40 refreshed
        count1 = await sequencer.refresh_due_candles(now_ts=1700100000.0)
        assert count1 == len(ACTIVE_PAIRS) * len(ACTIVE_TIMEFRAMES)
        assert mock_gw.get_klines.call_count == len(ACTIVE_PAIRS) * len(ACTIVE_TIMEFRAMES)

        mock_gw.get_klines.reset_mock()

        # 2nd cycle (15s later): Only 1m candles for 8 pairs refreshed (8 calls)
        count2 = await sequencer.refresh_due_candles(now_ts=1700100015.0)
        assert count2 == len(ACTIVE_PAIRS)
        assert mock_gw.get_klines.call_count == len(ACTIVE_PAIRS)  # 80% API request reduction

    @pytest.mark.anyio
    async def test_refresh_all_force_refreshes_all_series(self) -> None:
        mock_gw = AsyncMock()
        mock_gw.get_klines.return_value = [_build_raw_kline(1700000000000)]
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)

        # Mark all series fresh
        for k in sequencer.last_fetch_ts:
            sequencer.last_fetch_ts[k] = 1700100000.0
            sequencer.buffers[k].append(_build_candle(1700000000000))

        count = await sequencer.refresh_all(force=True, now_ts=1700100005.0)
        assert count == len(ACTIVE_PAIRS) * len(ACTIVE_TIMEFRAMES)
        assert mock_gw.get_klines.call_count == len(ACTIVE_PAIRS) * len(ACTIVE_TIMEFRAMES)


# =============================================================================
# Suite 5: TestConcurrencySemaphoreThrottle
# =============================================================================


class TestConcurrencySemaphoreThrottle:
    """Verifies that concurrent network requests strictly respect the asyncio.Semaphore."""

    @pytest.mark.anyio
    async def test_semaphore_bounds_maximum_concurrent_requests(self) -> None:
        max_in_flight = 0
        current_in_flight = 0
        lock = asyncio.Lock()

        async def _mock_get_klines(sym: str, interval: str, limit: int) -> list[Any]:
            nonlocal max_in_flight, current_in_flight
            async with lock:
                current_in_flight += 1
                if current_in_flight > max_in_flight:
                    max_in_flight = current_in_flight
            await asyncio.sleep(0.02)  # Simulate network latency
            async with lock:
                current_in_flight -= 1
            return [_build_raw_kline(1700000000000)]

        mock_gw = AsyncMock()
        mock_gw.get_klines.side_effect = _mock_get_klines

        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw, concurrency_limit=5)
        await sequencer.refresh_due_candles()

        # Concurrency must never exceed 5
        assert max_in_flight <= 5
        assert max_in_flight > 1

    @pytest.mark.anyio
    async def test_custom_semaphore_concurrency_bound(self) -> None:
        max_in_flight = 0
        current_in_flight = 0
        lock = asyncio.Lock()

        async def _mock_get_klines(sym: str, interval: str, limit: int) -> list[Any]:
            nonlocal max_in_flight, current_in_flight
            async with lock:
                current_in_flight += 1
                if current_in_flight > max_in_flight:
                    max_in_flight = current_in_flight
            await asyncio.sleep(0.01)
            async with lock:
                current_in_flight -= 1
            return [_build_raw_kline(1700000000000)]

        mock_gw = AsyncMock()
        mock_gw.get_klines.side_effect = _mock_get_klines

        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw, concurrency_limit=3)
        await sequencer.refresh_due_candles()
        assert max_in_flight <= 3


# =============================================================================
# Suite 6: TestPublicKlineEndpointFallback
# =============================================================================


class TestPublicKlineEndpointFallback:
    """Verifies automated fallback to public Binance REST on gateway errors."""

    @pytest.mark.anyio
    async def test_fallback_on_primary_api_error(self) -> None:
        mock_gw = AsyncMock()
        mock_gw.get_klines.side_effect = RuntimeError("502 Bad Gateway on Testnet")

        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        fallback_data = [_build_raw_kline(1700000000000, "150.0", "155.0", "148.0", "152.0")]

        with patch.object(
            sequencer, "_fetch_public_fallback", new_callable=AsyncMock
        ) as mock_fallback:
            mock_fallback.return_value = fallback_data
            await sequencer.fetch_and_update_series("BTCUSDT", "1m")

            mock_fallback.assert_awaited_once_with("BTCUSDT", "1m", 250)
            candles = sequencer.get_candles("BTCUSDT", "1m")
            assert len(candles) == 1
            assert candles[0].open == Decimal("150.0")

    @pytest.mark.anyio
    async def test_complete_network_outage_preserves_stale_buffer(self) -> None:
        mock_gw = AsyncMock()
        mock_gw.get_klines.side_effect = ConnectionError("Primary down")

        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        sequencer.buffers[("ETHUSDT", "5m")].append(_build_candle(1700000000000, "3000.0"))

        with patch.object(
            sequencer, "_fetch_public_fallback", new_callable=AsyncMock
        ) as mock_fallback:
            mock_fallback.side_effect = ConnectionError("Public internet down")
            await sequencer.fetch_and_update_series("ETHUSDT", "5m")

            candles = sequencer.get_candles("ETHUSDT", "5m")
            assert len(candles) == 1
            assert candles[0].open == Decimal("3000.0")

    @pytest.mark.anyio
    async def test_public_fallback_network_http_error_handled_cleanly(self) -> None:
        sequencer = MultiTimeframeCandleSequencer(gateway=None)
        with patch.object(
            sequencer, "_fetch_public_fallback", new_callable=AsyncMock
        ) as mock_fallback:
            mock_fallback.side_effect = ValueError("Corrupted public response")
            # Should not raise exception
            await sequencer.fetch_and_update_series("AVAXUSDT", "15m")
            assert len(sequencer.get_candles("AVAXUSDT", "15m")) == 0


# =============================================================================
# Suite 7: TestContinuousTraderSequencerIntegration
# =============================================================================


class TestContinuousTraderSequencerIntegration:
    """Verifies end-to-end integration with ContinuousSelfDrivingTrader & IctMmxmEngine."""

    @pytest.mark.anyio
    async def test_sequencer_feeds_ict_engine_twins_setup(self) -> None:
        engine = IctMmxmEngine()
        mock_gw = AsyncMock()
        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)

        for tf, count in [("4h", 20), ("1h", 30), ("15m", 30), ("5m", 40), ("1m", 60)]:
            buf = sequencer.buffers[("SOLUSDT", tf)]
            for i in range(count):
                buf.append(_build_candle(1700000000000 + i * INTERVAL_MILLISECONDS[tf], "150.0"))

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=sequencer.get_candles("SOLUSDT", "4h"),
            candles_1h=sequencer.get_candles("SOLUSDT", "1h"),
            candles_15m=sequencer.get_candles("SOLUSDT", "15m"),
            candles_5m=sequencer.get_candles("SOLUSDT", "5m"),
            candles_1m=sequencer.get_candles("SOLUSDT", "1m"),
            tick_size=Decimal("0.01"),
        )

        assert state.symbol == "SOLUSDT"
        assert state.step in (TwinsStep.IDLE, TwinsStep.STEP_1_HTF_HIT)

    def test_continuous_trader_initializes_sequencer(self, tmp_path: Path) -> None:
        mock_gw = AsyncMock()
        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gw,
            telegram_enabled=False,
        )
        assert hasattr(trader, "sequencer")
        assert isinstance(trader.sequencer, MultiTimeframeCandleSequencer)
        assert len(trader.sequencer.buffers) == len(ACTIVE_PAIRS) * len(ACTIVE_TIMEFRAMES)
        assert hasattr(trader, "get_multi_tf_candles")

    @pytest.mark.anyio
    async def test_continuous_trader_run_single_cycle_non_blocking_execution(
        self, tmp_path: Path
    ) -> None:
        mock_gw = AsyncMock()
        mock_gw.get_position_risk.return_value = []
        mock_gw.get_klines.return_value = [_build_raw_kline(1700000000000)]

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gw,
            telegram_enabled=False,
        )

        # Prepopulate multi-timeframe candles in sequencer
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                trader.sequencer.buffers[(sym, tf)].append(_build_candle(1700000000000))
                trader.sequencer.last_fetch_ts[(sym, tf)] = time.time()

        t0 = time.perf_counter()
        await trader.run_single_cycle()
        elapsed_sec = time.perf_counter() - t0

        # When buffers are fresh/cached, execution must be non-blocking (< 150 ms)
        assert elapsed_sec < 0.150, f"run_single_cycle took {elapsed_sec * 1000:.2f} ms"
