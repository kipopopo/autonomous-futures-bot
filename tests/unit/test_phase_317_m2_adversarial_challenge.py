"""Phase 317 Milestone 2 Adversarial Challenge & Stress Test Suite.

Adversarially probes:
1. Malformed data stress testing: dirty klines (negative prices, inverted envelopes,
   missing fields, string floats, non-numeric timestamps, non-finite values) and
   strict domain rejection.
2. Gap interpolation stress testing: single-bar, double-bar, three-bar, and 10-bar gaps
   across multiple horizons; asserts <= 2 flat hold padding and > 2 halt gap isolation.
3. Memory leak benchmark: pushing 20,000 candles into all 40 rolling buffers,
   asserting memory consumption strictly < 5.0 MB and deque maxlen=150 bounds buffer size.
4. Concurrency semaphore and fallback resilience under network fault injection.
"""

from __future__ import annotations

import asyncio
import gc
import tracemalloc
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

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
from autonomous_futures.strategy.ict_mmxm import Candle

# =============================================================================
# Helper Utilities
# =============================================================================


def _make_raw_kline(
    ts_ms: Any = 1700000000000,
    open_p: Any = "100.0",
    high_p: Any = "105.0",
    low_p: Any = "95.0",
    close_p: Any = "102.0",
    volume: Any = "500.0",
) -> list[Any]:
    return [
        ts_ms,
        open_p,
        high_p,
        low_p,
        close_p,
        volume,
        ts_ms + 59999 if isinstance(ts_ms, int) else 1700000059999,
        "51000.0",
        50,
        "250.0",
        "25500.0",
        "0",
    ]


def _make_candle(ts_ms: int, p: str = "100.0", vol: str = "100.0") -> Candle:
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
# Suite 1: Malformed Data Stress Testing
# =============================================================================


class TestAdversarialMalformedDataStress:
    """Stress tests kline parser against corrupt, adversarial, and dirty payloads."""

    # 1. Negative & Zero Prices
    @pytest.mark.parametrize(
        "open_p,high_p,low_p,close_p",
        [
            ("-100.0", "105.0", "-110.0", "102.0"),
            ("100.0", "-50.0", "-100.0", "102.0"),
            ("100.0", "105.0", "-95.0", "102.0"),
            ("100.0", "105.0", "95.0", "-102.0"),
            ("-0.0001", "10.0", "-1.0", "5.0"),
            ("0.0", "105.0", "95.0", "102.0"),
            ("100.0", "0.0", "0.0", "0.0"),
            ("100.0", "105.0", "0.0", "102.0"),
            ("100.0", "105.0", "95.0", "0.0"),
        ],
    )
    def test_rejects_negative_or_zero_prices(
        self, open_p: str, high_p: str, low_p: str, close_p: str
    ) -> None:
        raw = _make_raw_kline(open_p=open_p, high_p=high_p, low_p=low_p, close_p=close_p)
        with pytest.raises(KlineParsingError, match="strictly positive"):
            parse_raw_kline(raw)

    # 2. Envelope Violations
    @pytest.mark.parametrize(
        "open_p,high_p,low_p,close_p,match_err",
        [
            ("100.0", "90.0", "95.0", "92.0", "Inverted high/low envelope"),
            ("100.0", "95.0", "90.0", "92.0", "High .* must be >= open"),
            ("92.0", "95.0", "90.0", "100.0", "High .* must be >= .* close"),
            ("85.0", "100.0", "90.0", "95.0", "Low .* must be <= open"),
            ("95.0", "100.0", "90.0", "85.0", "Low .* must be <= .* close"),
        ],
    )
    def test_rejects_inverted_envelopes(
        self, open_p: str, high_p: str, low_p: str, close_p: str, match_err: str
    ) -> None:
        raw = _make_raw_kline(open_p=open_p, high_p=high_p, low_p=low_p, close_p=close_p)
        with pytest.raises(KlineParsingError, match=match_err):
            parse_raw_kline(raw)

    # 3. Negative Volume
    def test_rejects_negative_volume(self) -> None:
        raw = _make_raw_kline(volume="-0.0001")
        with pytest.raises(KlineParsingError, match="Volume must be non-negative"):
            parse_raw_kline(raw)

    # 4. Truncated Arrays
    @pytest.mark.parametrize(
        "truncated",
        [
            [],
            [1700000000000],
            [1700000000000, "100.0"],
            [1700000000000, "100.0", "105.0"],
            [1700000000000, "100.0", "105.0", "95.0"],
            [1700000000000, "100.0", "105.0", "95.0", "102.0"],
        ],
    )
    def test_rejects_truncated_arrays(self, truncated: list[Any]) -> None:
        with pytest.raises(KlineParsingError, match="requires >= 6 elements"):
            parse_raw_kline(truncated)

    # 5. Missing Fields in Dict Mappings
    @pytest.mark.parametrize(
        "missing_dict",
        [
            # Missing ts
            {
                "open": "100.0",
                "high": "105.0",
                "low": "95.0",
                "close": "102.0",
                "volume": "50.0",
            },
            # Missing open
            {
                "t": 1700000000000,
                "high": "105.0",
                "low": "95.0",
                "close": "102.0",
                "volume": "50.0",
            },
            # Missing high
            {
                "t": 1700000000000,
                "open": "100.0",
                "low": "95.0",
                "close": "102.0",
                "volume": "50.0",
            },
            # Missing low
            {
                "t": 1700000000000,
                "open": "100.0",
                "high": "105.0",
                "close": "102.0",
                "volume": "50.0",
            },
            # Missing close
            {
                "t": 1700000000000,
                "open": "100.0",
                "high": "105.0",
                "low": "95.0",
                "volume": "50.0",
            },
            # Missing volume
            {
                "t": 1700000000000,
                "open": "100.0",
                "high": "105.0",
                "low": "95.0",
                "close": "102.0",
            },
        ],
    )
    def test_rejects_missing_fields_in_mapping(self, missing_dict: dict[str, Any]) -> None:
        with pytest.raises(KlineParsingError):
            parse_raw_kline(missing_dict)

    # 6. Non-numeric or Invalid Timestamps
    @pytest.mark.parametrize(
        "invalid_ts",
        [
            "invalid_timestamp_string",
            "1700000000000.5",  # String float timestamp
            "1700000000000.0",  # String float timestamp
            None,
            [],
            {},
            -1000,
            0,
            -1700000000000,
        ],
    )
    def test_rejects_invalid_timestamps(self, invalid_ts: Any) -> None:
        raw = _make_raw_kline(ts_ms=invalid_ts)
        with pytest.raises(KlineParsingError):
            parse_raw_kline(raw)

    # 7. Non-numeric Price Strings
    @pytest.mark.parametrize(
        "dirty_val",
        [
            "corrupted_price",
            "",
            "   ",
            "100.0.0",
            "$100.0",
            "100,000.0",
            None,
        ],
    )
    def test_rejects_non_numeric_price_strings(self, dirty_val: Any) -> None:
        raw = _make_raw_kline(open_p=dirty_val)
        with pytest.raises(KlineParsingError):
            parse_raw_kline(raw)

    # 8. Unsupported Payload Types
    @pytest.mark.parametrize(
        "invalid_payload",
        [
            123456,
            "1700000000000,100,105,95,102,500",
            b"binary_payload",
            None,
            object(),
        ],
    )
    def test_rejects_unsupported_payload_types(self, invalid_payload: Any) -> None:
        with pytest.raises(KlineParsingError, match="Unsupported kline payload type"):
            parse_raw_kline(cast(Any, invalid_payload))


# =============================================================================
# Suite 2: Gap Interpolation Stress Testing
# =============================================================================


class TestAdversarialGapInterpolationStress:
    """Stress tests chronological alignment, padding rules, and halt isolation."""

    def test_single_bar_gap_exactly_one_flat_hold_bar(self) -> None:
        """Inject single-bar gap: verify exactly 1 flat hold padding and zero volume."""
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        c0 = _make_candle(1700000000000, p="100.0", vol="200.0")
        c2 = _make_candle(1700000120000, p="105.0", vol="300.0")  # Missing 1m bar at 1700000060000

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

    def test_double_bar_gap_exactly_two_flat_hold_bars(self) -> None:
        """Inject double-bar gap: verify exactly 2 flat hold padding."""
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        c0 = _make_candle(1700000000000, p="150.0")
        c3 = _make_candle(1700000180000, p="155.0")  # Missing 2 bars: 60000 and 120000

        res = syncer.synchronize("ETHUSDT", "1m", [c0, c3])

        assert res.gaps_detected == 1
        assert res.bars_interpolated == 2
        assert res.has_unrepaired_gap is False
        assert len(res.candles) == 4

        for synth in (res.candles[1], res.candles[2]):
            assert synth.open == c0.close
            assert synth.high == c0.close
            assert synth.low == c0.close
            assert synth.close == c0.close
            assert synth.volume == Decimal("0")

    def test_three_bar_gap_boundary_not_padded(self) -> None:
        """Inject 3-bar gap: exceeds max_interpolate_bars=2, verify halt gap isolation."""
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        c0 = _make_candle(1700000000000, p="150.0")
        c4 = _make_candle(1700000240000, p="160.0")  # Missing 3 bars

        res = syncer.synchronize("SOLUSDT", "1m", [c0, c4])

        assert res.gaps_detected == 1
        assert res.bars_interpolated == 0
        assert res.has_unrepaired_gap is True
        assert len(res.candles) == 2

    def test_ten_bar_gap_large_halt_isolation(self) -> None:
        """Inject 10-bar gap: verify strictly > 2 halt gap isolation without flat distortion."""
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        c0 = _make_candle(1700000000000, p="200.0")
        c11 = _make_candle(1700000660000, p="220.0")  # Missing 10 bars (600,000 ms)

        res = syncer.synchronize("DOGEUSDT", "1m", [c0, c11])

        assert res.gaps_detected == 1
        assert res.bars_interpolated == 0
        assert res.has_unrepaired_gap is True
        assert len(res.candles) == 2
        assert res.candles[0].timestamp_ms == 1700000000000
        assert res.candles[1].timestamp_ms == 1700000660000

    def test_multi_horizon_gap_interpolation(self) -> None:
        """Verifies gap detection and synthetic interpolation across all standard horizons."""
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)

        for interval, interval_ms in INTERVAL_MILLISECONDS.items():
            t0 = 1700000000000
            t2 = t0 + 2 * interval_ms  # 1-bar gap
            res = syncer.synchronize("BTCUSDT", interval, [_make_candle(t0), _make_candle(t2)])
            assert res.gaps_detected == 1, f"Failed on interval {interval}"
            assert res.bars_interpolated == 1, f"Failed on interval {interval}"
            assert res.candles[1].timestamp_ms == t0 + interval_ms

            t10 = t0 + 11 * interval_ms  # 10-bar gap
            raw_seq = [_make_candle(t0), _make_candle(t10)]
            res_halt = syncer.synchronize("BTCUSDT", interval, raw_seq)
            assert res_halt.gaps_detected == 1, f"Failed on interval {interval}"
            assert res_halt.bars_interpolated == 0, f"Failed on interval {interval}"
            assert res_halt.has_unrepaired_gap is True, f"Failed on interval {interval}"

    def test_mixed_gap_sequence_chronological_integrity(self) -> None:
        """Inject mixed sequence: consecutive, 1-gap, consecutive, 2-gap, 10-gap halt, 1-gap."""
        syncer = ChronologicalCandleSynchronizer(max_interpolate_bars=2)
        step = 60_000
        t = 1700000000000

        bars = [
            _make_candle(t + 0 * step),  # [0]
            _make_candle(t + 1 * step),  # [1]
            _make_candle(t + 3 * step),  # [2] (1-bar gap: t+2)
            _make_candle(t + 4 * step),  # [3]
            _make_candle(t + 7 * step),  # [4] (2-bar gap: t+5, t+6)
            _make_candle(t + 8 * step),  # [5]
            _make_candle(t + 19 * step),  # [6] (10-bar gap: t+9..t+18 -> isolate)
            _make_candle(t + 21 * step),  # [7] (1-bar gap: t+20)
        ]

        res = syncer.synchronize("BNBUSDT", "1m", bars)

        assert res.gaps_detected == 4
        assert res.bars_interpolated == 4  # 1 + 2 + 0 + 1 = 4
        assert res.has_unrepaired_gap is True
        assert len(res.candles) == 12

    def test_shuffled_and_duplicate_timestamp_recovery(self) -> None:
        """Inject reverse-ordered candles with duplicate timestamps: verify sort and dedup."""
        syncer = ChronologicalCandleSynchronizer()
        step = 60_000
        t = 1700000000000

        c0 = _make_candle(t + 0 * step, p="100.0")
        c1 = _make_candle(t + 1 * step, p="101.0")
        c1_dup = _make_candle(t + 1 * step, p="101.5")  # Duplicate
        c2 = _make_candle(t + 2 * step, p="102.0")

        # Inverted order
        shuffled = [c2, c1, c0, c1_dup]
        res = syncer.synchronize("XRPUSDT", "1m", shuffled)

        assert len(res.candles) == 3
        assert res.candles[0].timestamp_ms == t + 0 * step
        assert res.candles[1].timestamp_ms == t + 1 * step
        assert res.candles[1].open == Decimal("101.5")  # Latest duplicate retained
        assert res.candles[2].timestamp_ms == t + 2 * step
        assert res.gaps_detected == 0


# =============================================================================
# Suite 3: Memory Leak Benchmark & Bounded Ring Buffer
# =============================================================================


class TestAdversarialMemoryLeakBenchmark:
    """Rigorous memory consumption benchmark pushing high-frequency candles."""

    def test_20000_candles_into_40_buffers_strictly_under_5mb(self) -> None:
        """Push 20,000 candles into all 40 rolling buffers (800,000 total pushes).

        Asserts:
        - deque maxlen=150 bounds each buffer strictly to 150 items.
        - Deep memory footprint remains strictly < 5.0 MB (5,242,880 bytes).
        - Tracemalloc tracked memory remains strictly < 5.0 MB.
        """
        gc.collect()
        tracemalloc.start()

        sequencer = MultiTimeframeCandleSequencer(max_buffer_bars=150)
        assert len(sequencer.buffers) == 40

        t0 = 1700000000000
        # Push 20,000 candles into EACH of the 40 buffers
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = sequencer.buffers[(sym, tf)]
                for i in range(20000):
                    c = Candle(
                        timestamp_ms=t0 + i * 60000,
                        open=Decimal("100.50"),
                        high=Decimal("105.00"),
                        low=Decimal("99.00"),
                        close=Decimal("104.00"),
                        volume=Decimal("500.0"),
                    )
                    buf.append(c)

        gc.collect()
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # 1. Verify buffer lengths bounded strictly by maxlen=150
        for (sym, tf), buf in sequencer.buffers.items():
            assert len(buf) == 150, f"Buffer ({sym}, {tf}) length {len(buf)} != 150!"

        # 2. Verify total memory calculated by sequencer is < 5.0 MB
        total_bytes = sequencer.total_memory_bytes()
        five_mb_ceiling = 5 * 1024 * 1024  # 5,242,880 bytes
        assert total_bytes < five_mb_ceiling, (
            f"Sequencer total_memory_bytes {total_bytes} exceeds 5.0 MB ceiling!"
        )

        # 3. Verify tracemalloc peak memory < 5.0 MB
        assert peak_mem < five_mb_ceiling, (
            f"Tracemalloc peak memory {peak_mem} exceeds 5.0 MB ceiling!"
        )

    def test_memory_stability_across_repeated_push_cycles(self) -> None:
        """Pushes 5,000, then 20,000, then 40,000 candles to prove zero memory leak."""
        gc.collect()
        tracemalloc.start()

        sequencer = MultiTimeframeCandleSequencer(max_buffer_bars=150)
        t0 = 1700000000000

        # Cycle 1: 5,000 candles
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = sequencer.buffers[(sym, tf)]
                for i in range(5000):
                    buf.append(
                        Candle(
                            t0 + i * 60000,
                            Decimal("100.0"),
                            Decimal("102.0"),
                            Decimal("99.0"),
                            Decimal("101.0"),
                            Decimal("50.0"),
                        )
                    )
        gc.collect()
        mem_5k, _ = tracemalloc.get_traced_memory()

        # Cycle 2: 20,000 candles
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = sequencer.buffers[(sym, tf)]
                for i in range(5000, 20000):
                    buf.append(
                        Candle(
                            t0 + i * 60000,
                            Decimal("100.0"),
                            Decimal("102.0"),
                            Decimal("99.0"),
                            Decimal("101.0"),
                            Decimal("50.0"),
                        )
                    )
        gc.collect()
        mem_20k, _ = tracemalloc.get_traced_memory()

        # Cycle 3: 40,000 candles
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = sequencer.buffers[(sym, tf)]
                for i in range(20000, 40000):
                    buf.append(
                        Candle(
                            t0 + i * 60000,
                            Decimal("100.0"),
                            Decimal("102.0"),
                            Decimal("99.0"),
                            Decimal("101.0"),
                            Decimal("50.0"),
                        )
                    )
        gc.collect()
        mem_40k, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Memory between 20k and 40k must be nearly identical (delta < 50 KB)
        delta_bytes = abs(mem_40k - mem_20k)
        assert delta_bytes < 50 * 1024, (
            f"Memory leak detected: delta={delta_bytes} bytes between 20k and 40k pushes!"
        )


# =============================================================================
# Suite 4: Concurrency & Fallback Fault Injection
# =============================================================================


class TestAdversarialConcurrencyAndFallback:
    """Fault injection on concurrency limits and public REST fallback."""

    @pytest.mark.anyio
    async def test_semaphore_strictly_throttles_concurrent_bursts(self) -> None:
        """Inject 40 simultaneous requests; assert concurrency never exceeds semaphore limit (5)."""
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def _delayed_mock(sym: str, interval: str, limit: int) -> list[Any]:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            await asyncio.sleep(0.015)
            async with lock:
                current_concurrent -= 1
            return [_make_raw_kline(1700000000000)]

        mock_gw = AsyncMock()
        mock_gw.get_klines.side_effect = _delayed_mock

        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw, concurrency_limit=5)
        # Force all 40 streams to refresh simultaneously
        count = await sequencer.refresh_all(force=True)

        assert count == 40
        assert max_concurrent <= 5
        assert max_concurrent > 1

    @pytest.mark.anyio
    async def test_cascading_gateway_failure_falls_back_cleanly(self) -> None:
        """Inject primary gateway error; assert graceful fallback to Binance public REST."""
        mock_gw = AsyncMock()
        mock_gw.get_klines.side_effect = ConnectionResetError("Binance testnet socket dropped")

        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        public_raw = [_make_raw_kline(1700000000000, "180.0", "185.0", "175.0", "182.0")]

        with patch.object(
            sequencer, "_fetch_public_fallback", new_callable=AsyncMock
        ) as mock_public:
            mock_public.return_value = public_raw
            await sequencer.fetch_and_update_series("SUIUSDT", "15m")

            mock_public.assert_awaited_once_with("SUIUSDT", "15m", 100)
            candles = sequencer.get_candles("SUIUSDT", "15m")
            assert len(candles) == 1
            assert candles[0].open == Decimal("180.0")

    @pytest.mark.anyio
    async def test_total_network_blackout_retains_stale_buffers_without_crash(self) -> None:
        """Inject total network blackout (primary and public fail); assert buffers preserved."""
        mock_gw = AsyncMock()
        mock_gw.get_klines.side_effect = TimeoutError("Primary gateway timed out")

        sequencer = MultiTimeframeCandleSequencer(gateway=mock_gw)
        # Prepopulate buffer with historic candle
        initial_candle = _make_candle(1700000000000, "50.0")
        sequencer.buffers[("AVAXUSDT", "5m")].append(initial_candle)

        with patch.object(
            sequencer, "_fetch_public_fallback", new_callable=AsyncMock
        ) as mock_public:
            mock_public.side_effect = TimeoutError("Public REST timed out")

            # Execution must not raise exception
            await sequencer.fetch_and_update_series("AVAXUSDT", "5m")

            candles = sequencer.get_candles("AVAXUSDT", "5m")
            assert len(candles) == 1
            assert candles[0].open == Decimal("50.0")
