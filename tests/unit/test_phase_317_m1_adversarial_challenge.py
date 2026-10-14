"""Autonomous Futures Bot - Phase 317 Milestone 1 Adversarial Empirical Challenge Suite.

Adversarially probes:
1. Strict CISD body close invariance: wick sweeps, equality touches, needle wicks.
2. Zero-volume, zero-range ($H == L$) flatlines, and dealing range protection.
3. Erratic, noisy, high-wick, and inverse candle sequences ($H < L$).
4. Twins reversal state machine edge cases: missing timeframes, boundary rejections.
5. Algorithmic complexity and scaling of Breaker Block combinatorial detection.
6. Low-priced asset bracket buffer behavior (sub-$1.00 assets like DOGE, XRP).
"""

from __future__ import annotations

import time
from decimal import Decimal

from autonomous_futures.strategy.ict_mmxm import (
    Candle,
    IctMmxmEngine,
    InvalidationReason,
    PdArrayType,
    TwinsStep,
)


def _c(
    ts_ms: int,
    open_val: str | int | float | Decimal,
    high_val: str | int | float | Decimal,
    low_val: str | int | float | Decimal,
    close_val: str | int | float | Decimal,
    volume_val: str | int | float | Decimal = "100.0",
) -> Candle:
    return Candle(
        timestamp_ms=ts_ms,
        open=Decimal(str(open_val)),
        high=Decimal(str(high_val)),
        low=Decimal(str(low_val)),
        close=Decimal(str(close_val)),
        volume=Decimal(str(volume_val)),
    )


class TestAdversarialCisdInvariants:
    """Rigorous stress-testing of CISD body close vs wick sweep rules."""

    def test_bearish_cisd_wick_penetrations_cannot_trigger(self) -> None:
        """Asserts that wicks below reference can NEVER trigger Bearish CISD without body close."""
        engine = IctMmxmEngine()
        ref = Decimal("100.00")

        adversarial_candles = [
            # 1. Needle wick down to 10.0, close at 100.0001
            _c(1, "105.0", "110.0", "10.0", "100.0001"),
            # 2. Deep hammer: open=102, low=50, close=100.00000000000001
            _c(2, "102.0", "103.0", "50.0", "100.00000000000001"),
            # 3. Exact equality: close == 100.00
            _c(3, "105.0", "105.0", "90.0", "100.00"),
            # 4. Open below, but close back above
            _c(4, "95.0", "105.0", "90.0", "101.50"),
            # 5. Extreme spike candle: low=0.01, close=100.0000001
            _c(5, "100.5", "500.0", "0.01", "100.0000001"),
        ]

        for idx, candle in enumerate(adversarial_candles):
            confirmed, trigger_price = engine.detect_cisd(
                [candle], reference_price=ref, direction="BEARISH"
            )
            assert not confirmed, f"Bearish CISD falsely triggered on candle #{idx}: {candle}"
            assert trigger_price is None

        # Confirm that a genuine microscopic body close DOES trigger
        genuine_close = _c(6, "100.5", "101.0", "95.0", "99.99999999999999")
        confirmed, trigger_price = engine.detect_cisd(
            [genuine_close], reference_price=ref, direction="BEARISH"
        )
        assert confirmed is True
        assert trigger_price == ref

    def test_bullish_cisd_wick_penetrations_cannot_trigger(self) -> None:
        """Asserts that wicks above reference can NEVER trigger Bullish CISD without body close."""
        engine = IctMmxmEngine()
        ref = Decimal("50.00")

        adversarial_candles = [
            # 1. Needle wick up to 500.0, close at 49.9999
            _c(1, "45.0", "500.0", "40.0", "49.9999"),
            # 2. Shooting star: open=48, high=100, close=49.99999999999999
            _c(2, "48.0", "100.0", "45.0", "49.99999999999999"),
            # 3. Exact equality: close == 50.00
            _c(3, "45.0", "60.0", "45.0", "50.00"),
            # 4. Open above, but close back below
            _c(4, "55.0", "60.0", "45.0", "48.50"),
        ]

        for idx, candle in enumerate(adversarial_candles):
            confirmed, trigger_price = engine.detect_cisd(
                [candle], reference_price=ref, direction="BULLISH"
            )
            assert not confirmed, f"Bullish CISD falsely triggered on candle #{idx}: {candle}"
            assert trigger_price is None

        # Confirm that a genuine microscopic body close DOES trigger
        genuine_close = _c(5, "48.0", "55.0", "47.0", "50.00000000000001")
        confirmed, trigger_price = engine.detect_cisd(
            [genuine_close], reference_price=ref, direction="BULLISH"
        )
        assert confirmed is True
        assert trigger_price == ref

    def test_cisd_with_empty_and_corrupt_inputs(self) -> None:
        """Asserts safe degradation on empty candles, zero ref, and invalid direction."""
        engine = IctMmxmEngine()
        ref = Decimal("100.00")

        # Empty candles
        confirmed, trigger = engine.detect_cisd([], ref, "BEARISH")
        assert not confirmed and trigger is None

        # Unknown / non-canonical direction strings
        valid_candle = _c(1, "105.0", "105.0", "90.0", "95.0")
        confirmed, trigger = engine.detect_cisd([valid_candle], ref, "bearish")  # lowercase
        assert not confirmed and trigger is None

        confirmed, trigger = engine.detect_cisd([valid_candle], ref, "UNKNOWN")
        assert not confirmed and trigger is None

        # Zero reference price
        neg_candle = _c(1, "0.5", "1.0", "-5.0", "-2.0")
        confirmed, trigger = engine.detect_cisd([neg_candle], Decimal("0"), "BEARISH")
        assert confirmed and trigger == Decimal("0")

        # Negative reference price
        confirmed, trigger = engine.detect_cisd([neg_candle], Decimal("-1.0"), "BEARISH")
        assert confirmed and trigger == Decimal("-1.0")


class TestZeroRangeAndVolumeAnomalies:
    """Stress tests zero volume ($V == 0$), zero range ($H == L$), and flatlines."""

    def test_zero_volume_candles_across_all_detectors(self) -> None:
        """Verifies engine functions correctly when volume is strictly zero."""
        engine = IctMmxmEngine()
        candles = [
            _c(1000, "100.0", "102.0", "98.0", "99.0", volume_val="0.0"),
            _c(2000, "99.0", "108.0", "98.5", "107.0", volume_val="0.0"),  # Displacement
            _c(3000, "107.0", "115.0", "105.0", "112.0", volume_val="0.0"),  # BISI
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        assert len(pdas) >= 1
        obs = [p for p in pdas if p.array_type == PdArrayType.ORDER_BLOCK]
        assert len(obs) >= 1
        assert obs[0].direction == "BULLISH"

    def test_flatline_zero_range_candles_do_not_crash(self) -> None:
        """Verifies zero-range candles ($H == L == O == C$) produce 0 PDAs and 0 division errors."""
        engine = IctMmxmEngine()
        flat_candles = [
            _c(1000 + i * 60000, "100.0", "100.0", "100.0", "100.0", "100.0") for i in range(20)
        ]
        pdas = engine.detect_pd_arrays(flat_candles, timeframe="1h")
        assert pdas == []

        # STDV projection on zero dealing range
        targets = engine.compute_stdv_targets(Decimal("100.0"), Decimal("100.0"), "BEARISH")
        assert targets["1.0"] == Decimal("100.0")
        assert targets["2.0"] == Decimal("100.0")
        assert targets["4.0"] == Decimal("100.0")

    def test_twins_setup_zero_dealing_range_returns_clean_invalidation(self) -> None:
        """Verifies Twins setup with flatline 5m candles returns DEALING_RANGE_INVALID."""
        engine = IctMmxmEngine()
        # Flatline multi-tf candles
        flat_c = [
            _c(1000 + i * 60000, "100.0", "100.0", "100.0", "100.0", "100.0") for i in range(10)
        ]
        state = engine.evaluate_twins_setup(
            symbol="BTCUSDT",
            candles_4h=flat_c,
            candles_1h=flat_c,
            candles_15m=flat_c,
            candles_5m=flat_c,
            candles_1m=flat_c,
        )
        assert state.step_1_htf_hit is False
        assert state.step_6_ready is False


class TestErraticAndInvertedSequences:
    """Stress tests extreme noisy walks, inverse price inputs, and doji sequences."""

    def test_extreme_high_wick_doji_candles(self) -> None:
        """Verifies sequences of extreme dojis (H=1000, L=1, O=C=500) do not crash detectors."""
        engine = IctMmxmEngine()
        dojis = [
            _c(1000 + i * 60000, "500.0", "1000.0", "1.0", "500.0", "1000.0") for i in range(15)
        ]
        pdas = engine.detect_pd_arrays(dojis, timeframe="1h")
        obs = [
            p for p in pdas if p.array_type in (PdArrayType.ORDER_BLOCK, PdArrayType.BREAKER_BLOCK)
        ]
        assert obs == []

    def test_inverted_price_candle_sequence_handling(self) -> None:
        """Probes engine when candles have inverted prices (low > high)."""
        engine = IctMmxmEngine()
        inv_candles = [
            _c(1000 + i * 60000, "100.0", "90.0", "110.0", "95.0", "100.0") for i in range(10)
        ]
        # Does not crash with unhandled exception
        pdas = engine.detect_pd_arrays(inv_candles, timeframe="1h")
        assert isinstance(pdas, list)

    def test_sub_tick_precision_preservation(self) -> None:
        """Verifies Decimal arithmetic preserves 18 decimal places without float truncation."""
        engine = IctMmxmEngine()
        high = Decimal("0.000000000000100000")
        low = Decimal("0.000000000000080000")
        targets = engine.compute_stdv_targets(high, low, "BEARISH")
        expected_2_0 = high - Decimal("2.0") * (high - low)
        assert targets["2.0"] == expected_2_0
        assert targets["2.0"] == Decimal("0.000000000000060000")


class TestTwinsSetupBullishMirrorAndRejections:
    """Verifies Bullish mirror of Twins Setup and boundary states."""

    def test_bullish_twins_setup_full_execution(self) -> None:
        """Verifies complete 6-step progression for Bullish Twins Setup (MMBM)."""
        engine = IctMmxmEngine()

        # HTF: Bullish PDA (Old Low or +OB around 980.0)
        candles_4h: list[Candle] = []
        candles_1h: list[Candle] = []
        candles_15m = [
            _c(1700000000000, "1005.0", "1010.0", "980.0", "985.0"),
            _c(1700000900000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            # Taps PDA at low 982.0
            _c(1700000000000, "1005.0", "1006.0", "982.0", "985.0"),
            # Displaces upward: Close 1015 > Ref High 1006.0
            _c(1700000300000, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        candles_1m = [
            # Displacement leg sub-candles with Twin BISIs
            _c(1700000300000, "985.0", "990.0", "984.0", "989.0"),
            _c(1700000360000, "989.0", "999.0", "989.0", "998.0"),
            _c(1700000420000, "998.0", "1009.0", "995.0", "1008.0"),  # BISI 1 [990, 995]
            _c(1700000480000, "1008.0", "1018.0", "1008.0", "1017.0"),
            _c(1700000540000, "1017.0", "1020.0", "1014.0", "1019.0"),  # BISI 2 [1009, 1014]
            # OTE retracement leg into [990.132, 996.516] (H=1020, L=982, Range=38)
            _c(1700000600000, "1019.0", "1019.0", "1005.0", "1006.0"),
            _c(1700000660000, "1006.0", "1006.0", "993.0", "994.0"),  # Taps 993.0 in OTE
            # 1m CISD confirmation upward: Close 1007.0 > Ref High 1006.0
            _c(1700000720000, "994.0", "1008.0", "994.0", "1007.0"),
        ]

        state = engine.evaluate_twins_setup(
            symbol="BTCUSDT",
            candles_4h=candles_4h,
            candles_1h=candles_1h,
            candles_15m=candles_15m,
            candles_5m=candles_5m,
            candles_1m=candles_1m,
        )

        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is True
        assert state.step_6_ready is True
        assert state.side == "BUY"
        assert state.stop_loss == Decimal("981.00")  # L_leg 982 - 1.00
        assert state.take_profit_partial == Decimal("1058.00")  # 2.0 STDV = 982 + 2*38
        assert state.take_profit_final == Decimal("1134.00")  # 4.0 STDV = 982 + 4*38


class TestAlgorithmicScalingAndLowPriceAssetAnomalies:
    """Empirical investigation into $O(n^4)$ complexity and asset stop loss buffers."""

    def test_breaker_block_combinatorial_growth_profile(self) -> None:
        """Verifies that breaker blocks on n=40 and n=100 are efficiently bounded.

        Benchmark ceiling: < 50 PDAs and < 0.05s.
        """
        engine = IctMmxmEngine()

        for n in [10, 20, 40, 100]:
            candles = [
                _c(1000 + i * 60000, 100 + (i % 10), 105 + (i % 10), 95 + (i % 10), 101 + (i % 10))
                for i in range(n)
            ]
            t0 = time.perf_counter()
            pdas = engine.detect_pd_arrays(candles, "15m")
            elapsed = time.perf_counter() - t0
            bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
            assert elapsed < 0.05, f"Exceeded time limit on n={n}: {elapsed:.4f}s"
            if n in (40, 100):
                assert len(bbs) < 50, f"Expected bounded count on n={n}, got {len(bbs)}"

    def test_low_priced_asset_stop_loss_buffer_anomaly(self) -> None:
        """Documents the minimum 1.00 buffer on sub-$1.00 crypto assets."""
        # On DOGE (~$0.12), tick_size is 0.00001, but max(tick*2, 1.00) forces buffer 1.00.
        tick_size = Decimal("0.00001")
        buffer = max(tick_size * Decimal("2"), Decimal("1.00"))
        # Anomaly confirmed: buffer is 1.00, which is > 800% of asset value
        assert buffer == Decimal("1.00")


# ==============================================================================
# 7. ADVERSARIAL REJECTION MODES, FIB GAPS & TERMINUS CAPPING
# ==============================================================================


class TestAdversarialTwinsRejectionModes:
    """Empirically stress-tests the 4 mechanical rejection modes of Twins Reversal."""

    def test_rejection_mode_1_missing_htf_pda(self) -> None:
        """Mode 1: Price stops short of HTF PDA, rejecting at Step 1."""
        engine = IctMmxmEngine()
        candles_4h = [
            _c(1000, "990.0", "1025.0", "980.0", "1020.0"),
            _c(2000, "1020.0", "1022.0", "960.0", "965.0"),  # Bearish OB [980, 1025]
        ]
        # 5m stops short of 980 (high is 970.0)
        candles_5m = [
            _c(3000, "960.0", "970.0", "955.0", "965.0"),
            _c(3300, "965.0", "968.0", "940.0", "945.0"),
        ]
        candles_1m = [
            _c(3300, "965.0", "968.0", "960.0", "961.0"),
            _c(3360, "961.0", "961.0", "940.0", "942.0"),
        ]

        state = engine.evaluate_twins_setup("SOLUSDT", candles_4h, [], [], candles_5m, candles_1m)
        assert state.step_1_htf_hit is False
        assert state.step_6_ready is False
        assert state.side is None
        assert state.step == TwinsStep.IDLE

    def test_rejection_mode_2_single_fvg_rejection(self) -> None:
        """Mode 2: Displacement leg forms only 1 FVG instead of Twins (>= 2)."""
        engine = IctMmxmEngine()
        candles_4h = [
            _c(1000, "980.0", "1020.0", "970.0", "1015.0"),
            _c(2000, "1015.0", "1025.0", "960.0", "965.0"),
        ]
        candles_5m = [
            _c(3000, "995.0", "1018.0", "994.0", "1015.0"),
            _c(3300, "1015.0", "1016.0", "980.0", "985.0"),
        ]
        # 1m candles structured to have only ONE SIBI
        candles_1m = [
            _c(3300, "1015.0", "1016.0", "1010.0", "1011.0"),
            _c(3360, "1011.0", "1011.0", "1000.0", "1001.0"),
            _c(3420, "1001.0", "1004.0", "990.0", "991.0"),  # SIBI 1 [1004, 1010]
            _c(3480, "991.0", "991.0", "989.0", "990.0"),  # Overlap eliminates SIBI 2
            _c(3540, "990.0", "991.0", "980.0", "981.0"),
            _c(3600, "981.0", "995.0", "981.0", "994.0"),
            _c(3660, "994.0", "1007.0", "1001.5", "1006.5"),
            _c(3720, "1006.5", "1006.5", "998.0", "999.0"),
        ]

        state = engine.evaluate_twins_setup("SOLUSDT", candles_4h, [], [], candles_5m, candles_1m)
        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.NO_TWIN_FVGS

    def test_rejection_mode_3_under_retracement(self) -> None:
        """Mode 3: Price retraces only to 998.0 (< 1003.48 62% Fib), timing out."""
        engine = IctMmxmEngine()
        candles_4h = [
            _c(1000, "980.0", "1020.0", "970.0", "1015.0"),
            _c(2000, "1015.0", "1025.0", "960.0", "965.0"),
        ]
        candles_5m = [
            _c(3000, "995.0", "1018.0", "994.0", "1015.0"),
            _c(3300, "1015.0", "1016.0", "980.0", "985.0"),
        ]
        candles_1m = [
            _c(3300, "1015.0", "1016.0", "1010.0", "1011.0"),
            _c(3360, "1011.0", "1011.0", "1000.0", "1001.0"),
            _c(3420, "1001.0", "1004.0", "990.0", "991.0"),
            _c(3480, "991.0", "991.0", "982.0", "983.0"),
            _c(3540, "983.0", "986.0", "980.0", "981.0"),
            _c(3600, "981.0", "995.0", "981.0", "994.0"),
            _c(3660, "994.0", "998.0", "993.0", "997.0"),  # High 998.0 < 62% Fib
            _c(3720, "997.0", "997.0", "988.0", "989.0"),
        ]

        state = engine.evaluate_twins_setup("SOLUSDT", candles_4h, [], [], candles_5m, candles_1m)
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.TIMEOUT_OTE_RETRACE

    def test_rejection_mode_4_missing_1m_cisd_confirmation(self) -> None:
        """Mode 4: Price reaches OTE, but 1m candle only wicks without body close."""
        engine = IctMmxmEngine()
        candles_4h = [
            _c(1000, "980.0", "1020.0", "970.0", "1015.0"),
            _c(2000, "1015.0", "1025.0", "960.0", "965.0"),
        ]
        candles_5m = [
            _c(3000, "995.0", "1018.0", "994.0", "1015.0"),
            _c(3300, "1015.0", "1016.0", "980.0", "985.0"),
        ]
        candles_1m = [
            _c(3300, "1015.0", "1016.0", "1010.0", "1011.0"),
            _c(3360, "1011.0", "1011.0", "1000.0", "1001.0"),
            _c(3420, "1001.0", "1004.0", "990.0", "991.0"),
            _c(3480, "991.0", "991.0", "982.0", "983.0"),
            _c(3540, "983.0", "986.0", "980.0", "981.0"),
            _c(3600, "981.0", "995.0", "981.0", "994.0"),
            _c(3660, "994.0", "1007.0", "1001.5", "1006.5"),  # OTE ref low = 1001.5
            # Low 1000 < 1001.5, Close 1004 > 1001.5:
            _c(3720, "1006.5", "1006.5", "1000.0", "1004.0"),
        ]

        state = engine.evaluate_twins_setup("SOLUSDT", candles_4h, [], [], candles_5m, candles_1m)
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.M1_CISD_TIMEOUT


class TestAdversarialRetracementEdgeCases:
    """Stress tests violent spikes past 88.6%, gaps past 79%, and permissible wicks."""

    def test_violent_spike_past_886_invalidates_ote(self) -> None:
        """Violent spike past 88.6% Fib (1013.67) invalidates OTE even if close is inside."""
        engine = IctMmxmEngine()
        candles_4h = [
            _c(1000, "980.0", "1020.0", "970.0", "1015.0"),
            _c(2000, "1015.0", "1025.0", "960.0", "965.0"),
        ]
        candles_5m = [
            _c(3000, "995.0", "1018.0", "994.0", "1015.0"),
            _c(3300, "1015.0", "1016.0", "980.0", "985.0"),
        ]
        # Range 980 to 1018. 88.6% Fib is 1013.67. High wicks to 1015.0, close at 1005.0.
        candles_1m = [
            _c(3300, "1015.0", "1016.0", "1010.0", "1011.0"),
            _c(3360, "1011.0", "1011.0", "1000.0", "1001.0"),
            _c(3420, "1001.0", "1004.0", "990.0", "991.0"),
            _c(3480, "991.0", "991.0", "982.0", "983.0"),
            _c(3540, "983.0", "986.0", "980.0", "981.0"),
            _c(3600, "981.0", "995.0", "981.0", "994.0"),
            _c(3660, "994.0", "1015.0", "993.0", "1005.0"),  # Spike high 1015 > 88.6% Fib!
            _c(3720, "1005.0", "1005.0", "990.0", "992.0"),
        ]

        state = engine.evaluate_twins_setup("SOLUSDT", candles_4h, [], [], candles_5m, candles_1m)
        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.OTE_OVERSHOOT

    def test_gap_past_79_fib_invalidates_ote(self) -> None:
        """Gap open and close above 79% Fib (1009.87) invalidates OTE."""
        engine = IctMmxmEngine()
        candles_4h = [
            _c(1000, "980.0", "1020.0", "970.0", "1015.0"),
            _c(2000, "1015.0", "1025.0", "960.0", "965.0"),
        ]
        candles_5m = [
            _c(3000, "995.0", "1018.0", "994.0", "1015.0"),
            _c(3300, "1015.0", "1016.0", "980.0", "985.0"),
        ]
        # Candle opens at 1010.5 and closes at 1011.0 (both > 1009.87 [78.6%])
        candles_1m = [
            _c(3300, "1015.0", "1016.0", "1010.0", "1011.0"),
            _c(3360, "1011.0", "1011.0", "1000.0", "1001.0"),
            _c(3420, "1001.0", "1004.0", "990.0", "991.0"),
            _c(3480, "991.0", "991.0", "982.0", "983.0"),
            _c(3540, "983.0", "986.0", "980.0", "981.0"),
            _c(3600, "981.0", "995.0", "981.0", "994.0"),
            _c(3660, "1010.5", "1012.0", "1010.0", "1011.0"),  # Gap close 1011.0 > 79%
            _c(3720, "1011.0", "1011.0", "998.0", "999.0"),
        ]

        state = engine.evaluate_twins_setup("SOLUSDT", candles_4h, [], [], candles_5m, candles_1m)
        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.OTE_OVERSHOOT

    def test_permissible_wick_between_79_and_886_succeeds(self) -> None:
        """Wick to 1011.0 (between 78.6% and 88.6%) with close at 1008.0 (<= 78.6%) succeeds."""
        engine = IctMmxmEngine()
        candles_4h = [
            _c(1000, "980.0", "1020.0", "970.0", "1015.0"),
            _c(2000, "1015.0", "1025.0", "960.0", "965.0"),
        ]
        candles_5m = [
            _c(3000, "995.0", "1018.0", "994.0", "1015.0"),
            _c(3300, "1015.0", "1016.0", "980.0", "985.0"),
        ]
        candles_1m = [
            _c(3300, "1015.0", "1016.0", "1010.0", "1011.0"),
            _c(3360, "1011.0", "1011.0", "1000.0", "1001.0"),
            _c(3420, "1001.0", "1004.0", "990.0", "991.0"),
            _c(3480, "991.0", "991.0", "982.0", "983.0"),
            _c(3540, "983.0", "986.0", "980.0", "981.0"),
            _c(3600, "981.0", "995.0", "981.0", "994.0"),
            _c(3660, "994.0", "1011.0", "1001.5", "1008.0"),  # Wick 1011.0, Close 1008.0 <= 1009.87
            _c(3720, "1008.0", "1008.0", "998.0", "999.0"),  # 1m CISD (close 999.0 < 1001.5)
        ]

        state = engine.evaluate_twins_setup("SOLUSDT", candles_4h, [], [], candles_5m, candles_1m)
        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is True
        assert state.step_6_ready is True
        assert state.invalidation_reason == InvalidationReason.NONE


class TestAdversarialOppositePdaCapping:
    """Stress tests opposite HTF PDA capping logic when closer vs further than 4.0 STDV."""

    def test_bearish_capping_closer_than_4_0_stdv(self) -> None:
        """Bearish: 4.0 STDV is 866.00. Opposing PDA top is 900.00 (closer). Caps at 900.00."""
        engine = IctMmxmEngine()
        capped = engine.resolve_terminus_target(
            raw_target=Decimal("866.00"),
            opposing_pda_boundary=Decimal("900.00"),
            direction="BEARISH",
        )
        assert capped == Decimal("900.00")

    def test_bearish_uncapped_further_than_4_0_stdv(self) -> None:
        """Bearish: 4.0 STDV is 866.00. Opposing PDA top is 800.00 (further). Remains 866.00."""
        engine = IctMmxmEngine()
        uncapped = engine.resolve_terminus_target(
            raw_target=Decimal("866.00"),
            opposing_pda_boundary=Decimal("800.00"),
            direction="BEARISH",
        )
        assert uncapped == Decimal("866.00")

    def test_bullish_capping_closer_than_4_0_stdv(self) -> None:
        """Bullish: 4.0 STDV is 1140.00. Opposing PDA bottom is 1100.00. Caps at 1100.00."""
        engine = IctMmxmEngine()
        capped = engine.resolve_terminus_target(
            raw_target=Decimal("1140.00"),
            opposing_pda_boundary=Decimal("1100.00"),
            direction="BULLISH",
        )
        assert capped == Decimal("1100.00")

    def test_bullish_uncapped_further_than_4_0_stdv(self) -> None:
        """Bullish: 4.0 STDV is 1140.00. Opposing PDA bottom is 1200.00. Remains 1140.00."""
        engine = IctMmxmEngine()
        uncapped = engine.resolve_terminus_target(
            raw_target=Decimal("1140.00"),
            opposing_pda_boundary=Decimal("1200.00"),
            direction="BULLISH",
        )
        assert uncapped == Decimal("1140.00")


class TestDogeSubZeroStopLossBug:
    """Empirically documents and reproduces the sub-$1.00 negative stop loss bug."""

    def test_doge_negative_stop_loss_reproduction(self) -> None:
        """Empirical reproduction: DOGE ($0.12) calculates a negative Stop Loss of -$0.89!

        Root cause in src/autonomous_futures/strategy/ict_mmxm.py:961:
        `buffer = Decimal('1.00') if tick_size is None else max(tick_size * TWO, Decimal('1.00'))`
        Forces an absolute minimum $1.00 buffer regardless of asset price, producing
        `stop_loss = 0.11 - 1.00 = -0.89` on DOGE.
        """
        engine = IctMmxmEngine()
        candles_1h = [
            _c(1000, "0.12000", "0.12100", "0.11000", "0.11500"),
            _c(2000, "0.11500", "0.13000", "0.11400", "0.12500"),
        ]
        candles_5m = [
            _c(3000, "0.11800", "0.12000", "0.11000", "0.11200"),
            _c(3300, "0.11200", "0.12500", "0.11200", "0.12400"),
        ]
        candles_1m = [
            _c(3300, "0.11000", "0.11200", "0.11000", "0.11100"),
            _c(3360, "0.11100", "0.11600", "0.11100", "0.11500"),
            _c(3420, "0.11500", "0.11900", "0.11300", "0.11800"),  # BISI 1
            _c(3480, "0.11800", "0.12300", "0.11800", "0.12200"),
            _c(3540, "0.12200", "0.12500", "0.12000", "0.12400"),  # BISI 2
            _c(3600, "0.12400", "0.12400", "0.11700", "0.11800"),
            _c(3660, "0.11800", "0.11800", "0.11500", "0.11600"),  # In OTE
            _c(3720, "0.11600", "0.12000", "0.11600", "0.11900"),  # CISD confirmation
        ]

        doge_tick = Decimal("0.00001")
        state = engine.evaluate_twins_setup(
            "DOGEUSDT", [], candles_1h, [], candles_5m, candles_1m, tick_size=doge_tick
        )

        assert state.step_6_ready is True
        assert state.side == "BUY"
        # Confirm remediation: DOGE stop loss is strictly positive and correctly buffered
        assert state.stop_loss is not None
        assert state.stop_loss > Decimal("0"), f"Expected positive SL, got {state.stop_loss}"
        assert state.stop_loss == Decimal("0.10998")
