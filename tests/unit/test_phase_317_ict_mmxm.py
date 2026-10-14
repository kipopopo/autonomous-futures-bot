"""Autonomous Futures Bot - Phase 317 Unit Tests: ICT Market Maker Model & Twins Reversal.

Verifies:
- Detection of Bullish and Bearish Order Blocks with displacement
- Detection of Bullish and Bearish Breaker Blocks across 4-point swing sequences
- Detection of BISI and SIBI Fair Value Gaps and Consequent Encroachment (CE)
- Inversion Fair Value Gap (IFVG) polarity inversion on candle body closes
- Change in State of Delivery (CISD) body close vs wick sweep rejection
- The Twins Reversal 6-step mechanical sequence and all 4 rejection modes:
    * Full valid execution
    * Rejection when Step 3 has only 1 FVG
    * Rejection when Step 4 under-retraces or exceeds 88.6%
    * Rejection when Step 5 lacks 1m CISD confirmation
- Standard Deviation projections (1.0, 1.5, 2.0, 2.5, 4.0 STDV)
- Opposite HTF PDA terminus capping
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from autonomous_futures.strategy.ict_mmxm import (
    Candle,
    IctMmxmEngine,
    InvalidationReason,
    PdArrayType,
)


def _make_candle(
    ts_ms: int,
    open_p: str | float | Decimal,
    high_p: str | float | Decimal,
    low_p: str | float | Decimal,
    close_p: str | float | Decimal,
    volume: str | float | Decimal = "100.0",
) -> Candle:
    return Candle(
        timestamp_ms=ts_ms,
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        volume=Decimal(str(volume)),
    )


def _past_htf(candles: list[Candle]) -> list[Candle]:
    """Unit pattern fixtures use HTF bars closed before the lower-timeframe sequence."""
    return [
        replace(candle, timestamp_ms=candle.timestamp_ms - 14 * 86_400_000) for candle in candles
    ]


class TestIctPdArrayDetection:
    """Verifies Higher Time Frame PD Array identification: OB, BB, FVG, IFVG."""

    def test_bullish_order_block_detection(self) -> None:
        """Verifies +OB detection on lowest down candle followed by displacement and BISI."""
        engine = IctMmxmEngine()
        candles = [
            _make_candle(1700000000000, "102.0", "103.0", "100.5", "101.5", "100.0"),
            _make_candle(1700003600000, "101.5", "102.0", "98.0", "99.0", "150.0"),  # +OB
            _make_candle(1700007200000, "99.0", "106.0", "98.5", "105.0", "800.0"),  # Displacement
            _make_candle(1700010800000, "105.0", "112.0", "103.0", "110.0", "950.0"),  # BISI
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        obs = [
            p for p in pdas if p.array_type == PdArrayType.ORDER_BLOCK and p.direction == "BULLISH"
        ]
        assert len(obs) >= 1
        ob = obs[0]
        assert ob.top == Decimal("102.0")
        assert ob.bottom == Decimal("98.0")
        assert ob.mean_threshold == Decimal("100.0")
        assert ob.is_mitigated is False

    def test_bearish_order_block_detection(self) -> None:
        """Verifies -OB detection on highest up candle followed by displacement and SIBI."""
        engine = IctMmxmEngine()
        candles = [
            _make_candle(1700000000000, "98.0", "99.5", "97.0", "98.5", "100.0"),
            _make_candle(1700003600000, "98.5", "102.0", "98.0", "101.0", "150.0"),  # -OB
            _make_candle(1700007200000, "101.0", "101.5", "94.0", "95.0", "850.0"),  # Displacement
            _make_candle(1700010800000, "95.0", "97.0", "88.0", "90.0", "900.0"),  # SIBI
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        obs = [
            p for p in pdas if p.array_type == PdArrayType.ORDER_BLOCK and p.direction == "BEARISH"
        ]
        assert len(obs) >= 1
        ob = obs[0]
        assert ob.top == Decimal("102.0")
        assert ob.bottom == Decimal("98.0")
        assert ob.mean_threshold == Decimal("100.0")

    def test_order_block_mitigation_and_invalidation(self) -> None:
        """Verifies that an OB is marked mitigated on touch, and invalidated on close beyond."""
        engine = IctMmxmEngine()
        base_candles = [
            _make_candle(1700000000000, "102.0", "103.0", "100.5", "101.5"),
            _make_candle(1700003600000, "101.5", "102.0", "98.0", "99.0"),
            _make_candle(1700007200000, "99.0", "106.0", "98.5", "105.0"),
            _make_candle(1700010800000, "105.0", "112.0", "103.0", "110.0"),
        ]
        # Test mitigation: touches 100.5 without closing below 98.0
        mitigation_candles = base_candles + [
            _make_candle(1700014400000, "110.0", "110.5", "100.5", "104.0")
        ]
        pdas_mit = engine.detect_pd_arrays(mitigation_candles, timeframe="1h")
        obs_mit = [
            p
            for p in pdas_mit
            if p.array_type == PdArrayType.ORDER_BLOCK and p.direction == "BULLISH"
        ]
        assert len(obs_mit) >= 1
        assert obs_mit[0].is_mitigated is True

        # Test invalidation: close at 97.0 < 98.0
        invalidation_candles = base_candles + [
            _make_candle(1700014400000, "105.0", "105.0", "96.0", "97.0")
        ]
        pdas_inv = engine.detect_pd_arrays(invalidation_candles, timeframe="1h")
        obs_inv = [
            p
            for p in pdas_inv
            if p.array_type == PdArrayType.ORDER_BLOCK
            and p.direction == "BULLISH"
            and not p.is_mitigated
        ]
        assert len(obs_inv) == 0

    def test_bullish_breaker_block_4point_sequence(self) -> None:
        """Verifies +BB detection from L1 -> H1 -> L2 (sweep) -> H2 (break)."""
        engine = IctMmxmEngine()
        candles = [
            _make_candle(1700000000000, "105.0", "105.5", "100.0", "101.0"),  # L1 = 100.0
            _make_candle(1700000900000, "101.0", "110.0", "101.0", "109.0"),  # H1 = 110.0 (+BB)
            _make_candle(1700001800000, "109.0", "109.5", "102.0", "103.0"),
            _make_candle(1700002700000, "103.0", "103.5", "95.0", "96.0"),  # L2 = 95.0 (< 100.0)
            _make_candle(1700003600000, "96.0", "108.0", "95.5", "107.0"),
            _make_candle(1700004500000, "107.0", "115.0", "106.0", "114.0"),  # H2 = 115.0 (> 110.0)
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="15m")
        bbs = [
            p
            for p in pdas
            if p.array_type == PdArrayType.BREAKER_BLOCK and p.direction == "BULLISH"
        ]
        assert len(bbs) >= 1
        bb = bbs[0]
        assert bb.top == Decimal("110.0")
        assert bb.bottom == Decimal("101.0")
        assert bb.mean_threshold == Decimal("105.5")

    def test_bearish_breaker_block_4point_sequence(self) -> None:
        """Verifies -BB detection from H1 -> L1 -> H2 (sweep) -> L2 (break)."""
        engine = IctMmxmEngine()
        candles = [
            _make_candle(1700000000000, "95.0", "100.0", "94.5", "99.0"),  # H1 = 100.0
            _make_candle(1700000900000, "99.0", "99.0", "90.0", "91.0"),  # L1 = 90.0 (-BB)
            _make_candle(1700001800000, "91.0", "98.0", "90.5", "97.0"),
            _make_candle(1700002700000, "97.0", "105.0", "96.5", "103.0"),  # H2 = 105.0 (> 100.0)
            _make_candle(1700003600000, "103.0", "103.5", "92.0", "93.0"),
            _make_candle(1700004500000, "93.0", "93.0", "85.0", "86.0"),  # L2 = 85.0 (< 90.0)
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="15m")
        bbs = [
            p
            for p in pdas
            if p.array_type == PdArrayType.BREAKER_BLOCK and p.direction == "BEARISH"
        ]
        assert len(bbs) >= 1
        bb = bbs[0]
        assert bb.top == Decimal("99.0")
        assert bb.bottom == Decimal("90.0")
        assert bb.mean_threshold == Decimal("94.5")

    def test_breaker_block_invalid_sequence_rejection(self) -> None:
        """Verifies that sequences lacking sweep (L2 >= L1) or break (H2 <= H1) reject."""
        engine = IctMmxmEngine()
        # L2 fails to sweep (L2 = 101.0 >= L1 = 100.0)
        candles_no_sweep = [
            _make_candle(1700000000000, "105.0", "105.5", "100.0", "101.0"),
            _make_candle(1700000900000, "101.0", "110.0", "101.0", "109.0"),
            _make_candle(1700001800000, "109.0", "109.5", "102.0", "103.0"),
            _make_candle(1700002700000, "103.0", "103.5", "101.0", "102.0"),  # L2 = 101.0
            _make_candle(1700003600000, "102.0", "108.0", "102.0", "107.0"),
            _make_candle(1700004500000, "107.0", "115.0", "106.0", "114.0"),
        ]
        pdas = engine.detect_pd_arrays(candles_no_sweep, timeframe="15m")
        bbs = [
            p
            for p in pdas
            if p.array_type == PdArrayType.BREAKER_BLOCK and p.direction == "BULLISH"
        ]
        assert len(bbs) == 0

    def test_bisi_fair_value_gap_and_consequent_encroachment(self) -> None:
        """Verifies BISI FVG detection and exact 50% Consequent Encroachment (CE)."""
        engine = IctMmxmEngine()
        candles = [
            _make_candle(1700000000000, "100.0", "102.0", "99.0", "101.0"),
            _make_candle(1700000060000, "101.0", "110.0", "101.0", "109.0"),
            _make_candle(1700000120000, "109.0", "112.0", "105.0", "111.0"),
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="1m")
        fvg = [p for p in pdas if p.array_type == PdArrayType.FVG_BISI]
        assert len(fvg) == 1
        assert fvg[0].bottom == Decimal("102.0")
        assert fvg[0].top == Decimal("105.0")
        assert fvg[0].mean_threshold == Decimal("103.5")  # (102.0 + 105.0) / 2

    def test_sibi_fair_value_gap_and_consequent_encroachment(self) -> None:
        """Verifies SIBI FVG detection and exact 50% Consequent Encroachment (CE)."""
        engine = IctMmxmEngine()
        candles = [
            _make_candle(1700000000000, "110.0", "111.0", "108.0", "109.0"),
            _make_candle(1700000060000, "109.0", "109.0", "98.0", "99.0"),
            _make_candle(1700000120000, "99.0", "104.0", "97.0", "98.0"),
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="1m")
        fvg = [p for p in pdas if p.array_type == PdArrayType.FVG_SIBI]
        assert len(fvg) == 1
        assert fvg[0].bottom == Decimal("104.0")
        assert fvg[0].top == Decimal("108.0")
        assert fvg[0].mean_threshold == Decimal("106.0")  # (104.0 + 108.0) / 2

    def test_inversion_fvg_polarity_flip(self) -> None:
        """Verifies SIBI inverting to Bullish IFVG when candle body closes above top."""
        engine = IctMmxmEngine()
        candles = [
            _make_candle(1700000000000, "110.0", "111.0", "108.0", "109.0"),
            _make_candle(1700000060000, "109.0", "109.0", "98.0", "99.0"),
            _make_candle(1700000120000, "99.0", "104.0", "97.0", "98.0"),  # SIBI [104, 108]
            _make_candle(1700000180000, "98.0", "105.0", "97.5", "104.5"),
            _make_candle(1700000240000, "104.5", "112.0", "104.0", "110.5"),  # Close 110.5 > 108.0
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="1m")
        ifvgs = [
            p
            for p in pdas
            if p.array_type == PdArrayType.INVERSION_FVG and p.direction == "BULLISH"
        ]
        assert len(ifvgs) >= 1
        ifvg = ifvgs[0]
        assert ifvg.top == Decimal("108.0")
        assert ifvg.bottom == Decimal("104.0")
        assert ifvg.mean_threshold == Decimal("106.0")

    def test_fvg_wick_penetration_no_inversion(self) -> None:
        """Verifies that a wick above FVG top without a body close does NOT invert the FVG."""
        engine = IctMmxmEngine()
        candles = [
            _make_candle(1700000000000, "110.0", "111.0", "108.0", "109.0"),
            _make_candle(1700000060000, "109.0", "109.0", "98.0", "99.0"),
            _make_candle(1700000120000, "99.0", "104.0", "97.0", "98.0"),
            _make_candle(1700000180000, "98.0", "105.0", "97.5", "104.5"),
            _make_candle(
                1700000240000, "104.5", "109.0", "104.0", "107.5"
            ),  # High 109.0 > 108, Close 107.5 <= 108
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="1m")
        ifvgs = [p for p in pdas if p.array_type == PdArrayType.INVERSION_FVG]
        assert len(ifvgs) == 0

    def test_old_highs_and_lows_fractal_detection(self) -> None:
        """Verifies Feature 8: 5-bar fractal swing highs (BSL) and lows (SSL) detection.

        Validates:
        - 5-bar fractal high generates OLD_HIGH with direction == 'BEARISH' (BSL pool)
        - 5-bar fractal low generates OLD_LOW with direction == 'BULLISH' (SSL pool)
        - Attributes: top, bottom, mean_threshold, creation_ts, is_mitigated == False
        - Timeframe assignment correctly reflects input timeframe ('1h', '4h')
        """
        engine = IctMmxmEngine()
        # 7-candle sequence:
        # Bar 2 (ts 3000): High 115.0 > (105.0, 108.0, 109.0, 103.0) -> OLD_HIGH
        # Bar 4 (ts 5000): Low 85.0 < (99.0, 93.0, 89.0, 92.0) -> OLD_LOW
        candles = [
            _make_candle(1000, "100.0", "105.0", "95.0", "102.0"),
            _make_candle(2000, "102.0", "108.0", "97.0", "106.0"),
            _make_candle(3000, "106.0", "115.0", "99.0", "110.0"),  # Fractal swing high (BSL)
            _make_candle(4000, "110.0", "109.0", "93.0", "94.0"),
            _make_candle(5000, "94.0", "103.0", "85.0", "90.0"),  # Fractal swing low (SSL)
            _make_candle(6000, "90.0", "96.0", "89.0", "95.0"),
            _make_candle(7000, "95.0", "102.0", "92.0", "100.0"),
        ]
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")

        old_highs = [p for p in pdas if p.array_type == PdArrayType.OLD_HIGH]
        old_lows = [p for p in pdas if p.array_type == PdArrayType.OLD_LOW]

        assert len(old_highs) == 1
        assert len(old_lows) == 1

        high_pda = old_highs[0]
        assert high_pda.timeframe == "1h"
        assert high_pda.top == Decimal("115.0")
        assert high_pda.bottom == Decimal("115.0")
        assert high_pda.mean_threshold == Decimal("115.0")
        assert high_pda.direction == "BEARISH"  # BSL target pool
        assert high_pda.creation_ts == 3000
        assert high_pda.is_mitigated is False

        low_pda = old_lows[0]
        assert low_pda.timeframe == "1h"
        assert low_pda.top == Decimal("85.0")
        assert low_pda.bottom == Decimal("85.0")
        assert low_pda.mean_threshold == Decimal("85.0")
        assert low_pda.direction == "BULLISH"  # SSL target pool
        assert low_pda.creation_ts == 5000
        assert low_pda.is_mitigated is False

    def test_old_highs_and_lows_boundary_conditions(self) -> None:
        """Verifies that sequences with < 5 candles or flat highs/lows do not produce fractals."""
        engine = IctMmxmEngine()
        # Less than 5 candles: cannot form 5-bar fractal
        short_candles = [
            _make_candle(1000, "100.0", "110.0", "90.0", "105.0"),
            _make_candle(2000, "105.0", "120.0", "95.0", "115.0"),
            _make_candle(3000, "115.0", "105.0", "85.0", "90.0"),
            _make_candle(4000, "90.0", "95.0", "80.0", "85.0"),
        ]
        pdas_short = engine.detect_pd_arrays(short_candles, timeframe="4h")
        fractals = [
            p for p in pdas_short if p.array_type in (PdArrayType.OLD_HIGH, PdArrayType.OLD_LOW)
        ]
        assert len(fractals) == 0

        # Flat equal highs: strict '>' rejects individual fractal
        flat_high_candles = [
            _make_candle(1000, "100.0", "105.0", "95.0", "100.0"),
            _make_candle(2000, "100.0", "108.0", "96.0", "105.0"),
            _make_candle(3000, "105.0", "110.0", "98.0", "108.0"),  # High 110.0
            _make_candle(4000, "108.0", "110.0", "97.0", "106.0"),  # High 110.0 (equal)
            _make_candle(5000, "106.0", "104.0", "95.0", "98.0"),
            _make_candle(6000, "98.0", "102.0", "94.0", "96.0"),
        ]
        pdas_flat = engine.detect_pd_arrays(flat_high_candles, timeframe="1h")
        assert len([p for p in pdas_flat if p.array_type == PdArrayType.OLD_HIGH]) == 0


class TestCisdOrderDelivery:
    """Verifies Change in State of Delivery (CISD) body close vs wick sweep rules."""

    @pytest.mark.parametrize(
        ("has_bearish", "has_bullish", "bearish_ms", "bullish_ms", "expected"),
        [
            (True, True, 30, 20, "BEARISH"),
            (True, True, 20, 30, "BULLISH"),
            (True, True, 30, 30, None),
            (True, False, None, None, "BEARISH"),
            (False, True, None, None, "BULLISH"),
            (True, True, None, None, None),
        ],
    )
    def test_opposing_5m_candidates_use_confirmation_time_without_bearish_tie_break(
        self,
        has_bearish: bool,
        has_bullish: bool,
        bearish_ms: int | None,
        bullish_ms: int | None,
        expected: str | None,
    ) -> None:
        engine = IctMmxmEngine()

        assert (
            engine._resolve_setup_direction(
                has_bearish_pda=has_bearish,
                has_bullish_pda=has_bullish,
                bearish_confirmation_ms=bearish_ms,
                bullish_confirmation_ms=bullish_ms,
            )
            == expected
        )

    def test_cisd_body_close_confirmation_bearish(self) -> None:
        """Verifies Bearish CISD triggers on candle close strictly below reference low."""
        engine = IctMmxmEngine()
        candles = [_make_candle(1700000000000, "150.0", "150.5", "142.0", "143.0")]
        ref_price = Decimal("144.0")
        confirmed, trigger_price = engine.detect_cisd(
            candles, reference_price=ref_price, direction="BEARISH"
        )
        assert confirmed is True
        assert trigger_price == ref_price

    def test_cisd_wick_sweep_only_rejection_bearish(self) -> None:
        """Verifies Bearish CISD rejects when low < ref but close >= ref (wick sweep only)."""
        engine = IctMmxmEngine()
        candles = [_make_candle(1700000000000, "150.0", "150.5", "141.0", "145.0")]
        ref_price = Decimal("144.0")
        confirmed, trigger_price = engine.detect_cisd(
            candles, reference_price=ref_price, direction="BEARISH"
        )
        assert confirmed is False
        assert trigger_price is None

    def test_cisd_exact_equality_rejection(self) -> None:
        """Verifies CISD rejects when candle close exactly equals reference price."""
        engine = IctMmxmEngine()
        candles = [_make_candle(1700000000000, "150.0", "150.5", "142.0", "144.0")]
        ref_price = Decimal("144.0")
        confirmed, trigger_price = engine.detect_cisd(
            candles, reference_price=ref_price, direction="BEARISH"
        )
        assert confirmed is False
        assert trigger_price is None

    def test_cisd_body_close_confirmation_bullish(self) -> None:
        """Verifies Bullish CISD triggers on candle close strictly above reference high."""
        engine = IctMmxmEngine()
        candles = [_make_candle(1700000000000, "50.0", "58.0", "49.5", "57.5")]
        ref_price = Decimal("56.0")
        confirmed, trigger_price = engine.detect_cisd(
            candles, reference_price=ref_price, direction="BULLISH"
        )
        assert confirmed is True
        assert trigger_price == ref_price


class TestTwinsReversalSequence:
    """Verifies the complete 6-step mechanical sequence and all 4 rejection modes."""

    @pytest.fixture
    def base_multi_tf_candles(self) -> dict[str, list[Candle]]:
        """Generates standard aligned multi-timeframe candles with Bearish HTF PDA."""
        candles_4h = [
            _make_candle(1700000000000, "980.0", "1020.0", "970.0", "1015.0"),
            _make_candle(1700014400000, "1015.0", "1025.0", "990.0", "1000.0"),
        ]
        candles_1h = [
            _make_candle(1700000000000, "990.0", "1020.0", "985.0", "1015.0"),
            _make_candle(1700003600000, "1015.0", "1020.0", "980.0", "995.0"),
        ]
        candles_15m = [
            _make_candle(1700000000000, "995.0", "1020.0", "990.0", "1015.0"),
            _make_candle(1700000900000, "1015.0", "1018.0", "980.0", "985.0"),
        ]
        candles_5m = [
            _make_candle(1700000000000, "995.0", "1018.0", "994.0", "1015.0"),  # High taps PDA
            _make_candle(1700000300000, "1015.0", "1016.0", "980.0", "985.0"),  # Close 985 < 994
        ]
        candles_1m = [
            # 5m C1 sub-candles (creates Twin SIBIs)
            _make_candle(1700000300000, "1015.0", "1016.0", "1010.0", "1011.0"),
            _make_candle(1700000360000, "1011.0", "1011.0", "1000.0", "1001.0"),
            _make_candle(
                1700000420000, "1001.0", "1004.0", "990.0", "991.0"
            ),  # SIBI 1 [1004, 1010]
            _make_candle(1700000480000, "991.0", "991.0", "982.0", "983.0"),
            _make_candle(1700000540000, "983.0", "986.0", "980.0", "981.0"),  # SIBI 2 [986, 990]
            # OTE retracement into [1003.484, 1009.868]
            _make_candle(1700000600000, "981.0", "995.0", "981.0", "994.0"),
            _make_candle(1700000660000, "994.0", "1007.0", "1001.5", "1006.5"),  # Taps 1007.0 (OTE)
            # 1m CISD confirmation (Close 999.0 < 1001.5)
            _make_candle(1700000720000, "1006.5", "1006.5", "998.0", "999.0"),
        ]
        return {
            "4h": candles_4h,
            "1h": candles_1h,
            "15m": candles_15m,
            "5m": candles_5m,
            "1m": candles_1m,
        }

    def test_twins_setup_full_6step_valid_execution(
        self, base_multi_tf_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies that all 6 steps transition to True and calculate exact brackets."""
        engine = IctMmxmEngine()
        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(base_multi_tf_candles["4h"]),
            candles_1h=_past_htf(base_multi_tf_candles["1h"]),
            candles_15m=_past_htf(base_multi_tf_candles["15m"]),
            candles_5m=base_multi_tf_candles["5m"],
            candles_1m=base_multi_tf_candles["1m"],
        )
        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is True
        assert state.step_6_ready is True
        assert state.side == "SELL"
        assert state.stop_loss == Decimal("1019.00")
        assert state.take_profit_partial == Decimal("942.00")  # 2.0 STDV
        assert state.take_profit_final == Decimal("866.00")  # 4.0 STDV

    def test_twins_setup_rejection_single_fvg_in_step3(
        self, base_multi_tf_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies rejection when Step 3 forms only 1 FVG instead of Twins (>= 2)."""
        engine = IctMmxmEngine()
        candles_1m = list(base_multi_tf_candles["1m"])
        # Eliminate second SIBI by raising C4 low/high to overlap
        candles_1m[3] = _make_candle(1700000480000, "991.0", "1016.0", "989.0", "990.0")
        candles_1m[4] = _make_candle(1700000540000, "990.0", "991.0", "980.0", "981.0")

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(base_multi_tf_candles["4h"]),
            candles_1h=_past_htf(base_multi_tf_candles["1h"]),
            candles_15m=_past_htf(base_multi_tf_candles["15m"]),
            candles_5m=base_multi_tf_candles["5m"],
            candles_1m=candles_1m,
        )
        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is False
        assert state.step_6_ready is False

    def test_twins_setup_rejection_ote_under_retracement(
        self, base_multi_tf_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies rejection when Step 4 retracement fails to reach 62% OTE."""
        engine = IctMmxmEngine()
        candles_1m = list(base_multi_tf_candles["1m"])
        # Retrace only to 998.0 (< 1003.484 62% Fib)
        candles_1m[6] = _make_candle(1700000660000, "994.0", "998.0", "993.0", "997.0")
        candles_1m[7] = _make_candle(1700000720000, "997.0", "997.0", "988.0", "989.0")

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(base_multi_tf_candles["4h"]),
            candles_1h=_past_htf(base_multi_tf_candles["1h"]),
            candles_15m=_past_htf(base_multi_tf_candles["15m"]),
            candles_5m=base_multi_tf_candles["5m"],
            candles_1m=candles_1m,
        )
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False

    def test_twins_setup_50_pct_equilibrium_retracement(
        self, base_multi_tf_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies that 50% Equilibrium retracement (999.0) passes Step 4 with ote_lower=0.50."""
        engine = IctMmxmEngine(ote_lower=Decimal("0.50"))
        candles_1m = list(base_multi_tf_candles["1m"])
        # Retrace to 1000.0 (> 999.0 50% Fib, but < 1003.484 62% Fib)
        candles_1m[6] = _make_candle(1700000660000, "994.0", "1000.0", "993.0", "999.5")
        # 1m CISD confirmation (Close 991.0 < 993.0)
        candles_1m[7] = _make_candle(1700000720000, "999.5", "999.5", "990.0", "991.0")

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(base_multi_tf_candles["4h"]),
            candles_1h=_past_htf(base_multi_tf_candles["1h"]),
            candles_15m=_past_htf(base_multi_tf_candles["15m"]),
            candles_5m=base_multi_tf_candles["5m"],
            candles_1m=candles_1m,
        )
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is True
        assert state.step_6_ready is True

    def test_twins_setup_rejection_ote_over_retracement_886(
        self, base_multi_tf_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies invalidation when Step 4 over-retraces beyond 88.6% / manipulation high."""
        engine = IctMmxmEngine()
        candles_1m = list(base_multi_tf_candles["1m"])
        # Candle blows past manipulation high 1018.0 and 88.6% Fib 1013.67
        candles_1m[6] = _make_candle(1700000660000, "994.0", "1022.0", "993.0", "1021.0")

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(base_multi_tf_candles["4h"]),
            candles_1h=_past_htf(base_multi_tf_candles["1h"]),
            candles_15m=_past_htf(base_multi_tf_candles["15m"]),
            candles_5m=base_multi_tf_candles["5m"],
            candles_1m=candles_1m,
        )
        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False

    def test_twins_setup_rejection_step5_missing_m1_cisd(
        self, base_multi_tf_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies that reaching OTE without 1m CISD confirmation blocks order dispatch."""
        engine = IctMmxmEngine()
        candles_1m = list(base_multi_tf_candles["1m"])
        # C7 wicks to 1000.0 but closes at 1004.0 (above ref low 1001.5)
        candles_1m[7] = _make_candle(1700000720000, "1006.5", "1006.5", "1000.0", "1004.0")

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(base_multi_tf_candles["4h"]),
            candles_1h=_past_htf(base_multi_tf_candles["1h"]),
            candles_15m=_past_htf(base_multi_tf_candles["15m"]),
            candles_5m=base_multi_tf_candles["5m"],
            candles_1m=candles_1m,
        )
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is False
        assert state.step_6_ready is False

    def test_twins_setup_full_6step_valid_execution_bullish(self) -> None:
        """Verifies complete 6-step mechanical progression for Bullish Twins Setup (MMBM).

        Validates:
        - Step 1: 5m low taps HTF Bullish PDA (15m +OB [980.0, 1005.0] or BISI)
        - Step 2: 5m candle breaks above reference high (close 1015.0 > 1006.0), confirming CISD
        - Step 3: Displacement leg contains >= 2 distinct 1m BISI FVGs ([990, 995] and [1009, 1014])
        - Step 4: Retracement reaches into 62%-79% OTE ([990.132, 996.516]) without violating 88.6%
        - Step 5: 1m Bullish CISD confirms with body close above reference high (1007.0 > 1006.0)
        - Step 6: Emits side == 'BUY', stop_loss == 981.00, tp1_partial == 1058.00 (2.0 STDV),
                  tp2_terminus == 1134.00 (4.0 STDV).
        """
        engine = IctMmxmEngine()

        # 15m HTF: Bullish Order Block (+OB) created at [980.0, 1005.0]
        candles_15m = [
            _make_candle(1700000000000, "1005.0", "1010.0", "980.0", "985.0"),
            _make_candle(1700000900000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        # 5m candles: C0 taps PDA at low 982.0; C1 displaces upward (close 1015.0 > ref high 1006.0)
        candles_5m = [
            _make_candle(1700000000000, "1005.0", "1006.0", "982.0", "985.0"),
            _make_candle(1700000300000, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        # 1m candles:
        # Displacement leg (C0..C4) prints 2 distinct BISI FVGs
        # Retracement leg (C5..C6) taps 993.0 in OTE [990.132, 996.516]
        # Confirmation candle (C7) closes at 1007.0 > 1006.0 (1m Bullish CISD)
        candles_1m = [
            _make_candle(1700000300000, "985.0", "990.0", "984.0", "989.0"),
            _make_candle(1700000360000, "989.0", "999.0", "989.0", "998.0"),
            _make_candle(1700000420000, "998.0", "1009.0", "995.0", "1008.0"),  # BISI 1
            _make_candle(1700000480000, "1008.0", "1018.0", "1008.0", "1017.0"),
            _make_candle(1700000540000, "1017.0", "1020.0", "1014.0", "1019.0"),  # BISI 2
            _make_candle(1700000600000, "1019.0", "1019.0", "1005.0", "1006.0"),
            _make_candle(1700000660000, "1006.0", "1006.0", "993.0", "994.0"),  # In OTE
            _make_candle(1700000720000, "994.0", "1008.0", "994.0", "1007.0"),  # Close 1007 > 1006
        ]

        state = engine.evaluate_twins_setup(
            symbol="BTCUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf([]),
            candles_15m=_past_htf(candles_15m),
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
        assert state.stop_loss == Decimal("981.00")  # l_leg 982.00 - 1.00 default buffer
        assert state.take_profit_partial == Decimal("1058.00")  # 2.0 STDV = 982 + 2 * 38
        assert state.take_profit_final == Decimal("1134.00")  # 4.0 STDV = 982 + 4 * 38
        assert state.invalidation_reason == InvalidationReason.NONE


class TestStdvProjectionsAndOppositePdaCapping:
    """Verifies Fibonacci Standard Deviation projections and opposing PDA capping."""

    def test_fibonacci_stdv_extensions_bearish(self) -> None:
        """Verifies exact Decimal values for 1.0, 1.5, 2.0, 2.5, 4.0 STDV extensions."""
        engine = IctMmxmEngine()
        high = Decimal("100.00")
        low = Decimal("80.00")
        # Range = 20.00
        targets = engine.compute_stdv_targets(high=high, low=low, direction="BEARISH")
        assert targets["1.0"] == Decimal("80.00")
        assert targets["1.5"] == Decimal("70.00")
        assert targets["2.0"] == Decimal("60.00")
        assert targets["2.5"] == Decimal("50.00")
        assert targets["4.0"] == Decimal("20.00")

    def test_fibonacci_stdv_extensions_bullish(self) -> None:
        """Verifies exact Decimal values for bullish STDV extensions."""
        engine = IctMmxmEngine()
        high = Decimal("100.00")
        low = Decimal("80.00")
        targets = engine.compute_stdv_targets(high=high, low=low, direction="BULLISH")
        assert targets["1.0"] == Decimal("100.00")
        assert targets["1.5"] == Decimal("110.00")
        assert targets["2.0"] == Decimal("120.00")
        assert targets["2.5"] == Decimal("130.00")
        assert targets["4.0"] == Decimal("160.00")

    def test_stdv_terminus_capping_at_opposite_htf_pda(self) -> None:
        """Verifies that final terminus caps at opposite PDA when proximal to 4.0 STDV."""
        engine = IctMmxmEngine()
        # Case 1: Bearish setup. 4.0 STDV is 20.0. Opposite Bullish OB top is 35.0.
        # Price falls into 35.0 first -> Terminus = 35.0.
        tp_final_bearish = engine.resolve_terminus_target(
            raw_target=Decimal("20.00"),
            opposing_pda_boundary=Decimal("35.00"),
            direction="BEARISH",
        )
        assert tp_final_bearish == Decimal("35.00")

        # Case 2: Bearish setup. 4.0 STDV is 20.0.
        # Opposite Bullish OB top is 10.0 (beyond 4.0 STDV).
        # Terminus remains 20.0.
        tp_final_uncapped = engine.resolve_terminus_target(
            raw_target=Decimal("20.00"),
            opposing_pda_boundary=Decimal("10.00"),
            direction="BEARISH",
        )
        assert tp_final_uncapped == Decimal("20.00")

        # Case 3: Bullish setup. 4.0 STDV is 160.0. Opposite Bearish OB bottom is 145.0.
        # Price rises into 145.0 first -> Terminus = 145.0.
        tp_final_bullish = engine.resolve_terminus_target(
            raw_target=Decimal("160.00"),
            opposing_pda_boundary=Decimal("145.00"),
            direction="BULLISH",
        )
        assert tp_final_bullish == Decimal("145.00")

    def test_dealing_range_zero_flatline_guard(self) -> None:
        """Verifies that zero dealing range (high == low) does not raise ZeroDivisionError."""
        engine = IctMmxmEngine()
        targets = engine.compute_stdv_targets(
            high=Decimal("100.00"),
            low=Decimal("100.00"),
            direction="BEARISH",
        )
        assert targets["2.0"] == Decimal("100.00")
        assert targets["4.0"] == Decimal("100.00")


class TestAlgorithmicPerformanceBenchmarks:
    """Verifies execution time and memory bounds on medium/large candle series.

    Guarantees:
    - detect_pd_arrays on 100 candles executes in < 0.05s
    - Total detected PDAs on 100 candles is < 50 (eliminates 792,000 combinatorial explosion)
    - Total detected Breaker Blocks on 100 candles is < 20
    """

    def test_breaker_block_detection_algorithmic_scaling_benchmark(self) -> None:
        """Verifies detect_pd_arrays on 100 candles runs in < 0.05s and generates < 50 PDAs.

        Protects against O(n^4) combinatorial explosion regressions where 100 candles
        previously generated 792,000 duplicate Breaker Blocks and blocked the thread for > 3.3s.
        """
        import time

        engine = IctMmxmEngine()
        candles = [
            _make_candle(
                ts_ms=1700000000000 + i * 3600000,
                open_p=100 + (i % 7) * 2,
                high_p=105 + (i % 7) * 2,
                low_p=95 + (i % 7) * 2,
                close_p=102 + (i % 7) * 2,
                volume="500.0",
            )
            for i in range(100)
        ]

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"Execution too slow: {elapsed:.4f}s >= 0.05s benchmark ceiling"
        assert len(pdas) < 50, f"Combinatorial explosion: {len(pdas)} PDAs >= 50"
        assert len(bbs) < 20, f"Too many breaker blocks: {len(bbs)} >= 20"

    test_breaker_block_algorithmic_scaling_benchmark = (
        test_breaker_block_detection_algorithmic_scaling_benchmark
    )


class TestSubDollarAssetProtection:
    """Verifies stop loss protection and proportional tick buffers on sub-$1.00 assets.

    Guarantees:
    - Stop loss is strictly positive (stop_loss > Decimal('0')) on assets like DOGEUSDT ($0.12)
      and XRPUSDT ($0.50).
    - Buffer calculation uses proportional tick_size * TWO rather than hardcoded $1.00 floor.
    """

    def test_doge_sub_dollar_buy_stop_loss_strictly_positive(self) -> None:
        """Verifies DOGE ($0.12) BUY stop loss is strictly positive with proportional buffer."""
        engine = IctMmxmEngine()
        doge_tick = Decimal("0.00001")

        # 1h Bullish Order Block around 0.11000 - 0.12100
        candles_1h = [
            _make_candle(1000000, "0.12000", "0.12100", "0.11000", "0.11500"),
            _make_candle(2000000, "0.11500", "0.13000", "0.11400", "0.12500"),
        ]
        # 5m candles: C0 taps low 0.11000; C1 displaces upward above 0.12000
        candles_5m = [
            _make_candle(3000000, "0.11800", "0.12000", "0.11000", "0.11200"),
            _make_candle(3300000, "0.11200", "0.12500", "0.11200", "0.12400"),
        ]
        # 1m candles: 2 BISI FVGs, OTE retracement, CISD confirmation
        candles_1m = [
            _make_candle(3300000, "0.11000", "0.11200", "0.11000", "0.11100"),
            _make_candle(3360000, "0.11100", "0.11600", "0.11100", "0.11500"),
            _make_candle(3420000, "0.11500", "0.11900", "0.11300", "0.11800"),  # BISI 1
            _make_candle(3480000, "0.11800", "0.12300", "0.11800", "0.12200"),
            _make_candle(3540000, "0.12200", "0.12500", "0.12000", "0.12400"),  # BISI 2
            _make_candle(3600000, "0.12400", "0.12400", "0.11700", "0.11800"),
            _make_candle(3660000, "0.11800", "0.11800", "0.11500", "0.11600"),  # In OTE
            _make_candle(3720000, "0.11600", "0.12000", "0.11600", "0.11900"),  # CISD confirmation
        ]

        state = engine.evaluate_twins_setup(
            symbol="DOGEUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf(candles_1h),
            candles_15m=_past_htf([]),
            candles_5m=candles_5m,
            candles_1m=candles_1m,
            tick_size=doge_tick,
        )

        assert state.step_6_ready is True
        assert state.side == "BUY"
        assert state.stop_loss is not None
        assert state.stop_loss > Decimal("0"), f"Stop loss must be > 0, got {state.stop_loss}"
        # Expected buffer = 2 * 0.00001 = 0.00002; l_leg = 0.11000 -> SL = 0.10998
        expected_sl = Decimal("0.11000") - (doge_tick * Decimal("2"))
        assert state.stop_loss == expected_sl

    def test_xrpusdt_sub_dollar_buy_stop_loss_strictly_positive(self) -> None:
        """Verifies XRP ($0.50) BUY stop loss is strictly positive with proportional buffer."""
        engine = IctMmxmEngine()
        xrp_tick = Decimal("0.0001")

        # 1h Bullish Order Block at 0.4800
        candles_1h = [
            _make_candle(1000000, "0.5000", "0.5050", "0.4800", "0.4900"),
            _make_candle(2000000, "0.4900", "0.5300", "0.4850", "0.5250"),
        ]
        candles_5m = [
            _make_candle(3000000, "0.4950", "0.5000", "0.4800", "0.4850"),
            _make_candle(3300000, "0.4850", "0.5300", "0.4840", "0.5280"),
        ]
        candles_1m = [
            _make_candle(3300000, "0.4840", "0.4880", "0.4840", "0.4870"),
            _make_candle(3360000, "0.4870", "0.5000", "0.4870", "0.4990"),
            _make_candle(3420000, "0.4990", "0.5120", "0.4940", "0.5100"),  # BISI 1
            _make_candle(3480000, "0.5100", "0.5220", "0.5100", "0.5200"),
            _make_candle(3540000, "0.5200", "0.5300", "0.5170", "0.5290"),  # BISI 2
            _make_candle(3600000, "0.5290", "0.5290", "0.5050", "0.5070"),
            _make_candle(3660000, "0.5070", "0.5070", "0.4950", "0.4970"),  # In OTE
            _make_candle(3720000, "0.4970", "0.5100", "0.4970", "0.5090"),  # CISD confirmation
        ]

        state = engine.evaluate_twins_setup(
            symbol="XRPUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf(candles_1h),
            candles_15m=_past_htf([]),
            candles_5m=candles_5m,
            candles_1m=candles_1m,
            tick_size=xrp_tick,
        )

        assert state.step_6_ready is True
        assert state.side == "BUY"
        assert state.stop_loss is not None
        assert state.stop_loss > Decimal("0"), f"Stop loss must be > 0, got {state.stop_loss}"
        # Expected buffer = 2 * 0.0001 = 0.0002; l_leg = 0.4800 -> SL = 0.4798
        expected_sl = Decimal("0.4800") - (xrp_tick * Decimal("2"))
        assert state.stop_loss == expected_sl

    def test_sub_dollar_sell_stop_loss_tight_buffer(self) -> None:
        """Verifies sub-$1.00 SELL stop loss does not inflate by $1.00, preserving tight risk."""
        engine = IctMmxmEngine()
        doge_tick = Decimal("0.00001")

        candles_1h = [
            _make_candle(1000000, "0.12000", "0.13000", "0.11900", "0.12800"),
            _make_candle(2000000, "0.12800", "0.12900", "0.11500", "0.11600"),
        ]
        candles_5m = [
            _make_candle(3000000, "0.12500", "0.13000", "0.12400", "0.12800"),
            _make_candle(3300000, "0.12800", "0.12850", "0.11400", "0.11500"),
        ]
        candles_1m = [
            _make_candle(3300000, "0.12800", "0.12850", "0.12500", "0.12600"),
            _make_candle(3360000, "0.12600", "0.12600", "0.12100", "0.12200"),
            _make_candle(3420000, "0.12200", "0.12400", "0.11800", "0.11900"),  # SIBI 1
            _make_candle(3480000, "0.11900", "0.11900", "0.11500", "0.11600"),
            _make_candle(3540000, "0.11600", "0.11700", "0.11400", "0.11450"),  # SIBI 2
            _make_candle(3600000, "0.11450", "0.12200", "0.11450", "0.12100"),
            _make_candle(3660000, "0.12100", "0.12600", "0.12000", "0.12500"),  # In OTE
            _make_candle(3720000, "0.12500", "0.12500", "0.11800", "0.11900"),  # CISD confirmation
        ]

        state = engine.evaluate_twins_setup(
            symbol="DOGEUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf(candles_1h),
            candles_15m=_past_htf([]),
            candles_5m=candles_5m,
            candles_1m=candles_1m,
            tick_size=doge_tick,
        )

        assert state.step_6_ready is True
        assert state.side == "SELL"
        expected_sl = Decimal("0.13000") + (doge_tick * Decimal("2"))
        assert state.stop_loss == expected_sl
        assert state.stop_loss < Decimal("0.15000"), "Stop loss was inflated abnormally"

    def test_low_priced_asset_stop_loss_positive_buffer_doge_xrp(self) -> None:
        """Verifies DOGE and XRP positive stop loss buffers in a single unified test."""
        self.test_doge_sub_dollar_buy_stop_loss_strictly_positive()
        self.test_xrpusdt_sub_dollar_buy_stop_loss_strictly_positive()
        self.test_sub_dollar_sell_stop_loss_tight_buffer()


class TestMultiCandleBufferRobustness:
    """Verifies that sliding historical buffers and follow-through bars preserve detection.

    Guarantees:
    - Prepending historical 5m candles before the manipulation peak does not corrupt l_leg / h_leg.
    - Appending follow-through 1m candles after confirmation retains step_6_ready == True.
    - Rolling window buffers (20x 5m bars, 50x 1m bars) correctly isolate the active setup.
    """

    @pytest.fixture
    def baseline_setup_candles(self) -> dict[str, list[Candle]]:
        """Provides baseline valid 6-step Bearish setup candles."""
        candles_4h = [
            _make_candle(1700000000000, "980.0", "1020.0", "970.0", "1015.0"),
            _make_candle(1700014400000, "1015.0", "1025.0", "990.0", "1000.0"),
        ]
        candles_1h = [
            _make_candle(1700000000000, "990.0", "1020.0", "985.0", "1015.0"),
            _make_candle(1700003600000, "1015.0", "1020.0", "980.0", "995.0"),
        ]
        candles_15m = [
            _make_candle(1700000000000, "995.0", "1020.0", "990.0", "1015.0"),
            _make_candle(1700000900000, "1015.0", "1018.0", "980.0", "985.0"),
        ]
        candles_5m = [
            _make_candle(1700000000000, "995.0", "1018.0", "994.0", "1015.0"),
            _make_candle(1700000300000, "1015.0", "1016.0", "980.0", "985.0"),
        ]
        candles_1m = [
            _make_candle(1700000300000, "1015.0", "1016.0", "1010.0", "1011.0"),
            _make_candle(1700000360000, "1011.0", "1011.0", "1000.0", "1001.0"),
            _make_candle(1700000420000, "1001.0", "1004.0", "990.0", "991.0"),
            _make_candle(1700000480000, "991.0", "991.0", "982.0", "983.0"),
            _make_candle(1700000540000, "983.0", "986.0", "980.0", "981.0"),
            _make_candle(1700000600000, "981.0", "995.0", "981.0", "994.0"),
            _make_candle(1700000660000, "994.0", "1007.0", "1001.5", "1006.5"),
            _make_candle(1700000720000, "1006.5", "1006.5", "998.0", "999.0"),
        ]
        return {
            "4h": candles_4h,
            "1h": candles_1h,
            "15m": candles_15m,
            "5m": candles_5m,
            "1m": candles_1m,
        }

    def test_preceding_historical_candles_do_not_distort_dealing_range(
        self, baseline_setup_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies that prepending earlier historical 5m and 1m candles preserves dealing range."""
        engine = IctMmxmEngine()
        c5_base = baseline_setup_candles["5m"]
        c1_base = baseline_setup_candles["1m"]

        # Prepend historical 5m bars with lower lows (e.g. 950.0) prior to the manipulation peak
        prepended_5m = [
            _make_candle(1700000000000 - 900000, "960.0", "975.0", "950.0", "970.0"),
            _make_candle(1700000000000 - 600000, "970.0", "985.0", "965.0", "980.0"),
            _make_candle(1700000000000 - 300000, "980.0", "998.0", "975.0", "995.0"),
        ] + c5_base

        # Prepend historical 1m bars prior to displacement
        prepended_1m = [
            _make_candle(1700000300000 - 180000, "995.0", "998.0", "990.0", "995.0"),
            _make_candle(1700000300000 - 120000, "995.0", "1005.0", "994.0", "1002.0"),
            _make_candle(1700000300000 - 60000, "1002.0", "1015.0", "1000.0", "1014.0"),
        ] + c1_base

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(baseline_setup_candles["4h"]),
            candles_1h=_past_htf(baseline_setup_candles["1h"]),
            candles_15m=_past_htf(baseline_setup_candles["15m"]),
            candles_5m=prepended_5m,
            candles_1m=prepended_1m,
        )

        assert state.step_6_ready is True
        assert state.side == "SELL"
        # Dealing range must remain anchored to the displacement leg (1018.0 - 980.0 = 38.0)
        assert state.stop_loss == Decimal("1019.00")
        assert state.take_profit_partial == Decimal("942.00")
        assert state.take_profit_final == Decimal("866.00")

    def test_following_candles_do_not_drop_confirmed_state(
        self, baseline_setup_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies appending follow-through 1m candles retains setup readiness."""
        engine = IctMmxmEngine()
        c1_base = baseline_setup_candles["1m"]

        # Append 3 follow-through candles (consolidating or moving downward without breaking SL)
        appended_1m = list(c1_base) + [
            _make_candle(1700000720000 + 60000, "999.0", "1004.0", "996.0", "1003.0"),
            _make_candle(1700000720000 + 120000, "1003.0", "1003.0", "990.0", "992.0"),
            _make_candle(1700000720000 + 180000, "992.0", "995.0", "988.0", "989.0"),
        ]

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(baseline_setup_candles["4h"]),
            candles_1h=_past_htf(baseline_setup_candles["1h"]),
            candles_15m=_past_htf(baseline_setup_candles["15m"]),
            candles_5m=baseline_setup_candles["5m"],
            candles_1m=appended_1m,
        )

        assert state.step_6_ready is True
        assert state.side == "SELL"
        assert state.invalidation_reason == InvalidationReason.NONE

    def test_bullish_rolling_window_robustness(self) -> None:
        """Verifies Bullish MMBM setup inside a realistic multi-candle rolling buffer."""
        engine = IctMmxmEngine()

        # Prepend 5m historical bars with higher highs (e.g. 1050.0) before the manipulation drop
        candles_5m = [
            _make_candle(1700000000000 - 600000, "1040.0", "1055.0", "1035.0", "1045.0"),
            _make_candle(1700000000000 - 300000, "1045.0", "1045.0", "1010.0", "1015.0"),
            # Active setup: C0 taps low 982.0; C1 displaces to 1020.0
            _make_candle(1700000000000, "1005.0", "1006.0", "982.0", "985.0"),
            _make_candle(1700000300000, "985.0", "1020.0", "984.0", "1015.0"),
        ]

        candles_1m = [
            # Prepend historical 1m
            _make_candle(1700000300000 - 120000, "1015.0", "1018.0", "1010.0", "1012.0"),
            _make_candle(1700000300000 - 60000, "1012.0", "1012.0", "990.0", "992.0"),
            # Active displacement & Twins BISIs
            _make_candle(1700000300000, "985.0", "990.0", "984.0", "989.0"),
            _make_candle(1700000360000, "989.0", "999.0", "989.0", "998.0"),
            _make_candle(1700000420000, "998.0", "1009.0", "995.0", "1008.0"),
            _make_candle(1700000480000, "1008.0", "1018.0", "1008.0", "1017.0"),
            _make_candle(1700000540000, "1017.0", "1020.0", "1014.0", "1019.0"),
            # OTE retracement
            _make_candle(1700000600000, "1019.0", "1019.0", "1005.0", "1006.0"),
            _make_candle(1700000660000, "1006.0", "1006.0", "993.0", "994.0"),
            # Confirmation
            _make_candle(1700000720000, "994.0", "1008.0", "994.0", "1007.0"),
            # Follow-through candle
            _make_candle(1700000720000 + 60000, "1007.0", "1015.0", "1005.0", "1014.0"),
        ]

        candles_15m = [
            _make_candle(1700000000000, "1005.0", "1010.0", "980.0", "985.0"),
            _make_candle(1700000900000, "985.0", "1016.0", "982.0", "1015.0"),
        ]

        state = engine.evaluate_twins_setup(
            symbol="BTCUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf([]),
            candles_15m=_past_htf(candles_15m),
            candles_5m=candles_5m,
            candles_1m=candles_1m,
        )

        assert state.step_6_ready is True
        assert state.side == "BUY"
        assert state.stop_loss == Decimal("981.00")
        assert state.take_profit_partial == Decimal("1058.00")
        assert state.take_profit_final == Decimal("1134.00")

    def test_twins_setup_multi_candle_buffer_robustness(
        self, baseline_setup_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies multi-candle buffer robustness across pre-peak and post-confirmation bars."""
        self.test_preceding_historical_candles_do_not_distort_dealing_range(baseline_setup_candles)
        self.test_following_candles_do_not_drop_confirmed_state(baseline_setup_candles)
        self.test_bullish_rolling_window_robustness()
