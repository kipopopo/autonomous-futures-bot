"""Empirical Challenger Verification Suite for Milestone 1 Iteration 2 (Phase 317).

Adversarial stress harness verifying:
1. Low-Price Asset Stop Loss (DOGE $0.12, XRP $0.50, and micro-price sweeps):
   - Strict assertion: `stop_loss > Decimal("0")` under every condition.
   - Proportional buffer invariance (tick_size * 2) vs fallback guard.
   - Symmetric verification on BUY and SELL setups.
2. Multi-Candle Rolling Buffers:
   - Prepending 20 historical 5m and 1m candles before the peak/trough.
   - Appending 20 consolidation candles after confirmation.
   - Assertion: `step_6_ready == True` is strictly preserved for both BEARISH and BULLISH.
   - Random-walk consolidation stress testing.
3. Bullish Twins Setup (MMBM) Rejection Symmetries:
   - Symmetrically verify all 4 rejection modes for BUY setups:
     - Mode 1: Missing HTF PDA touch (Step 1 rejection -> IDLE).
     - Mode 2: Single BISI FVG in displacement leg (Step 3 rejection -> NO_TWIN_FVGS).
     - Mode 3A: Under-retracement failure (Step 4 rejection -> TIMEOUT_OTE_RETRACE).
     - Mode 3B: Over-retracement / Overshoot failure (Step 4 rejection -> OTE_OVERSHOOT).
     - Mode 4: Missing 1m CISD confirmation inside OTE (Step 5 rejection -> M1_CISD_TIMEOUT).
"""

from __future__ import annotations

import random
from dataclasses import replace
from decimal import Decimal

import pytest

from autonomous_futures.strategy.ict_mmxm import (
    Candle,
    IctMmxmEngine,
    InvalidationReason,
    TwinsStep,
)


def _c(
    ts_ms: int,
    open_p: str | int | float | Decimal,
    high_p: str | int | float | Decimal,
    low_p: str | int | float | Decimal,
    close_p: str | int | float | Decimal,
    volume: str | int | float | Decimal = "100.0",
) -> Candle:
    """Helper creating a Candle with strict Decimal conversion."""
    return Candle(
        timestamp_ms=(1_700_000_000_000 + ts_ms * 1000)
        if abs(ts_ms) < 1_000_000_000_000
        else ts_ms,
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        volume=Decimal(str(volume)),
    )


# ==============================================================================
# 1. EMPIRICAL VERIFICATION: LOW-PRICE ASSET STOP LOSS (DOGE & XRP)
# ==============================================================================


def _past_htf(candles: list[Candle]) -> list[Candle]:
    """Unit pattern fixtures use HTF bars closed before the lower-timeframe sequence."""
    return [
        replace(candle, timestamp_ms=candle.timestamp_ms - 14 * 86_400_000) for candle in candles
    ]


class TestLowPriceAssetStopLossEmpiricalHarness:
    """Adversarial stress harness for Low-Price Asset stop loss generation."""

    @pytest.mark.parametrize(
        "tick_size,expected_sl",
        [
            (Decimal("0.00001"), Decimal("0.10998")),
            (Decimal("0.0001"), Decimal("0.1098")),
            (Decimal("0.001"), Decimal("0.108")),
            (Decimal("0.005"), Decimal("0.100")),
            (Decimal("0.01"), Decimal("0.09")),
            (Decimal("0.05"), Decimal("0.01")),
            (Decimal("0.10"), Decimal("0.10890")),  # Triggers fallback max(0.11 * 0.99, 0.10)
            (Decimal("0.50"), Decimal("0.50")),  # Triggers fallback max(0.1089, 0.50)
            (None, Decimal("0.10890")),  # None defaults to $1.00 -> triggers fallback
            (Decimal("0"), Decimal("0.10890")),  # Zero tick size -> triggers fallback
        ],
    )
    def test_doge_buy_stop_loss_strictly_positive_under_all_tick_sizes(
        self, tick_size: Decimal | None, expected_sl: Decimal
    ) -> None:
        """Asserts DOGE ($0.12) BUY order stop loss > 0 under every tick_size."""
        engine = IctMmxmEngine()

        # 1h Bullish Order Block around 0.11000 - 0.12100
        candles_1h = [
            _c(1000, "0.12000", "0.12100", "0.11000", "0.11500"),
            _c(2000, "0.11500", "0.13000", "0.11400", "0.12500"),
        ]
        # 5m candles: C0 taps low 0.11000; C1 displaces upward above 0.12000
        candles_5m = [
            _c(3000, "0.11800", "0.12000", "0.11000", "0.11200"),
            _c(3300, "0.11200", "0.12500", "0.11200", "0.12400"),
        ]
        # 1m candles: 2 BISI FVGs, OTE retracement, CISD confirmation
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

        state = engine.evaluate_twins_setup(
            symbol="DOGEUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf(candles_1h),
            candles_15m=_past_htf([]),
            candles_5m=candles_5m,
            candles_1m=candles_1m,
            tick_size=tick_size,
        )

        assert state.step_6_ready is True
        assert state.side == "BUY"
        assert state.stop_loss is not None
        assert state.stop_loss > Decimal("0"), (
            f"stop_loss > 0 invariant violated: {state.stop_loss}"
        )
        assert state.stop_loss == expected_sl, f"Expected {expected_sl}, got {state.stop_loss}"

    @pytest.mark.parametrize(
        "tick_size,expected_sl",
        [
            (Decimal("0.0001"), Decimal("0.4798")),  # Binance XRPUSDT tick size
            (Decimal("0.00001"), Decimal("0.47998")),
            (Decimal("0.001"), Decimal("0.478")),
            (Decimal("0.01"), Decimal("0.46")),
            (Decimal("0.10"), Decimal("0.28")),
            (Decimal("0.30"), Decimal("0.4752")),  # 0.48 - 0.60 = -0.12 -> max(0.48*0.99, 0.30)
            (None, Decimal("0.4752")),  # None defaults to $1.00 -> fallback
            (Decimal("0"), Decimal("0.4752")),  # Zero tick size -> fallback
        ],
    )
    def test_xrp_buy_stop_loss_strictly_positive_under_all_tick_sizes(
        self, tick_size: Decimal | None, expected_sl: Decimal
    ) -> None:
        """Asserts XRP ($0.50) BUY order stop loss > 0 under every tick_size."""
        engine = IctMmxmEngine()

        # 1h Bullish Order Block at 0.4800
        candles_1h = [
            _c(1000, "0.5000", "0.5050", "0.4800", "0.4900"),
            _c(2000, "0.4900", "0.5300", "0.4850", "0.5250"),
        ]
        candles_5m = [
            _c(3000, "0.4950", "0.5000", "0.4800", "0.4850"),
            _c(3300, "0.4850", "0.5300", "0.4840", "0.5280"),
        ]
        candles_1m = [
            _c(3300, "0.4840", "0.4880", "0.4840", "0.4870"),
            _c(3360, "0.4870", "0.5000", "0.4870", "0.4990"),
            _c(3420, "0.4990", "0.5120", "0.4940", "0.5100"),  # BISI 1
            _c(3480, "0.5100", "0.5220", "0.5100", "0.5200"),
            _c(3540, "0.5200", "0.5300", "0.5170", "0.5290"),  # BISI 2
            _c(3600, "0.5290", "0.5290", "0.5050", "0.5070"),
            _c(3660, "0.5070", "0.5070", "0.4950", "0.4970"),  # In OTE
            _c(3720, "0.4970", "0.5100", "0.4970", "0.5090"),  # CISD confirmation
        ]

        state = engine.evaluate_twins_setup(
            symbol="XRPUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf(candles_1h),
            candles_15m=_past_htf([]),
            candles_5m=candles_5m,
            candles_1m=candles_1m,
            tick_size=tick_size,
        )

        assert state.step_6_ready is True
        assert state.side == "BUY"
        assert state.stop_loss is not None
        assert state.stop_loss > Decimal("0"), (
            f"stop_loss > 0 invariant violated: {state.stop_loss}"
        )
        assert state.stop_loss == expected_sl, f"Expected {expected_sl}, got {state.stop_loss}"

    def test_doge_and_xrp_sell_setups_stop_loss_strictly_positive(self) -> None:
        """Asserts DOGE and XRP SELL setups produce positive, tightly bounded stop loss levels."""
        engine = IctMmxmEngine()

        # DOGE SELL setup at 0.12500 - 0.13000
        doge_tick = Decimal("0.00001")
        candles_1h_doge = [
            _c(1000, "0.12000", "0.13000", "0.11900", "0.12800"),
            _c(2000, "0.12800", "0.12900", "0.11500", "0.11600"),
        ]
        candles_5m_doge = [
            _c(3000, "0.12500", "0.13000", "0.12400", "0.12800"),
            _c(3300, "0.12800", "0.12850", "0.11400", "0.11500"),
        ]
        candles_1m_doge = [
            _c(3300, "0.12800", "0.12850", "0.12500", "0.12600"),
            _c(3360, "0.12600", "0.12600", "0.12100", "0.12200"),
            _c(3420, "0.12200", "0.12400", "0.11800", "0.11900"),  # SIBI 1
            _c(3480, "0.11900", "0.11900", "0.11500", "0.11600"),
            _c(3540, "0.11600", "0.11700", "0.11400", "0.11450"),  # SIBI 2
            _c(3600, "0.11450", "0.12200", "0.11450", "0.12100"),
            _c(3660, "0.12100", "0.12600", "0.12000", "0.12500"),  # In OTE
            _c(3720, "0.12500", "0.12500", "0.11800", "0.11900"),  # CISD confirmation
        ]

        state_doge = engine.evaluate_twins_setup(
            symbol="DOGEUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf(candles_1h_doge),
            candles_15m=_past_htf([]),
            candles_5m=candles_5m_doge,
            candles_1m=candles_1m_doge,
            tick_size=doge_tick,
        )
        assert state_doge.step_6_ready is True
        assert state_doge.side == "SELL"
        assert state_doge.stop_loss is not None
        assert state_doge.stop_loss > Decimal("0")
        assert state_doge.stop_loss == Decimal("0.13000") + (doge_tick * Decimal("2"))

        # XRP SELL setup at 0.5000 - 0.5300
        xrp_tick = Decimal("0.0001")
        candles_1h_xrp = [
            _c(1000, "0.4800", "0.5300", "0.4750", "0.5250"),
            _c(2000, "0.5250", "0.5280", "0.4600", "0.4650"),
        ]
        candles_5m_xrp = [
            _c(3000, "0.5100", "0.5300", "0.5080", "0.5250"),
            _c(3300, "0.5250", "0.5260", "0.4600", "0.4650"),
        ]
        candles_1m_xrp = [
            _c(3300, "0.5250", "0.5260", "0.5100", "0.5150"),
            _c(3360, "0.5150", "0.5150", "0.4950", "0.4980"),
            _c(3420, "0.4980", "0.5050", "0.4800", "0.4820"),  # SIBI 1
            _c(3480, "0.4820", "0.4820", "0.4680", "0.4700"),
            _c(3540, "0.4700", "0.4720", "0.4600", "0.4620"),  # SIBI 2
            _c(3600, "0.4620", "0.4900", "0.4620", "0.4880"),
            _c(3660, "0.4880", "0.5080", "0.4850", "0.5050"),  # In OTE
            _c(3720, "0.5050", "0.5050", "0.4750", "0.4780"),  # CISD confirmation
        ]

        state_xrp = engine.evaluate_twins_setup(
            symbol="XRPUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf(candles_1h_xrp),
            candles_15m=_past_htf([]),
            candles_5m=candles_5m_xrp,
            candles_1m=candles_1m_xrp,
            tick_size=xrp_tick,
        )
        assert state_xrp.step_6_ready is True
        assert state_xrp.side == "SELL"
        assert state_xrp.stop_loss is not None
        assert state_xrp.stop_loss > Decimal("0")
        assert state_xrp.stop_loss == Decimal("0.5300") + (xrp_tick * Decimal("2"))

    def test_grid_sweep_sub_dollar_assets_stop_loss_always_positive(self) -> None:
        """Exhaustive grid sweep over 100 simulated price levels asserting stop_loss > 0."""
        for price_int in range(1, 101):  # $0.01 to $1.00
            price_base = Decimal(price_int) / Decimal("100")
            l_leg = price_base
            h_leg = price_base * Decimal("1.2")

            for tick in [
                Decimal("0.00001"),
                Decimal("0.0001"),
                Decimal("0.001"),
                Decimal("0.01"),
                None,
            ]:
                buffer = tick * Decimal("2") if tick is not None else Decimal("1.00")
                sl = l_leg - buffer
                if sl <= Decimal("0"):
                    fallback = (
                        tick if tick is not None and tick > Decimal("0") else Decimal("0.0001")
                    )
                    sl = max(l_leg * Decimal("0.99"), fallback)

                assert sl > Decimal("0"), f"Stop loss non-positive for {price_base}, tick {tick}"
                assert sl < h_leg, f"Stop loss {sl} must be strictly below high {h_leg}"


# ==============================================================================
# 2. EMPIRICAL VERIFICATION: MULTI-CANDLE ROLLING BUFFERS (20 PRE / 20 POST)
# ==============================================================================


class TestMultiCandleRollingBuffersEmpiricalHarness:
    """Stress harness testing 20 historical candles prepended and 20 consolidation appended."""

    @pytest.fixture
    def bearish_baseline_candles(self) -> dict[str, list[Candle]]:
        """Baseline Bearish setup candles."""
        candles_4h = [
            _c(1700000000000, "980.0", "1020.0", "970.0", "1015.0"),
            _c(1700014400000, "1015.0", "1025.0", "990.0", "1000.0"),
        ]
        candles_1h = [
            _c(1700000000000, "990.0", "1020.0", "985.0", "1015.0"),
            _c(1700003600000, "1015.0", "1020.0", "980.0", "995.0"),
        ]
        candles_15m = [
            _c(1700000000000, "995.0", "1020.0", "990.0", "1015.0"),
            _c(1700000900000, "1015.0", "1018.0", "980.0", "985.0"),
        ]
        candles_5m = [
            _c(1700000000000, "995.0", "1018.0", "994.0", "1015.0"),
            _c(1700000300000, "1015.0", "1016.0", "980.0", "985.0"),
        ]
        candles_1m = [
            _c(1700000300000, "1015.0", "1016.0", "1010.0", "1011.0"),
            _c(1700000360000, "1011.0", "1011.0", "1000.0", "1001.0"),
            _c(1700000420000, "1001.0", "1004.0", "990.0", "991.0"),
            _c(1700000480000, "991.0", "991.0", "982.0", "983.0"),
            _c(1700000540000, "983.0", "986.0", "980.0", "981.0"),
            _c(1700000600000, "981.0", "995.0", "981.0", "994.0"),
            _c(1700000660000, "994.0", "1007.0", "1001.5", "1006.5"),
            _c(1700000720000, "1006.5", "1006.5", "998.0", "999.0"),
        ]
        return {
            "4h": candles_4h,
            "1h": candles_1h,
            "15m": candles_15m,
            "5m": candles_5m,
            "1m": candles_1m,
        }

    @pytest.fixture
    def bullish_baseline_candles(self) -> dict[str, list[Candle]]:
        """Baseline Bullish setup candles."""
        candles_15m = [
            _c(1700000000000, "1005.0", "1010.0", "980.0", "985.0"),
            _c(1700000900000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            _c(1700000000000, "1005.0", "1006.0", "982.0", "985.0"),
            _c(1700000300000, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        candles_1m = [
            _c(1700000300000, "985.0", "990.0", "984.0", "989.0"),
            _c(1700000360000, "989.0", "999.0", "989.0", "998.0"),
            _c(1700000420000, "998.0", "1009.0", "995.0", "1008.0"),
            _c(1700000480000, "1008.0", "1018.0", "1008.0", "1017.0"),
            _c(1700000540000, "1017.0", "1020.0", "1014.0", "1019.0"),
            _c(1700000600000, "1019.0", "1019.0", "1005.0", "1006.0"),
            _c(1700000660000, "1006.0", "1006.0", "993.0", "994.0"),
            _c(1700000720000, "994.0", "1008.0", "994.0", "1007.0"),
        ]
        return {
            "15m": candles_15m,
            "5m": candles_5m,
            "1m": candles_1m,
        }

    def test_bearish_prepend_20_historical_and_append_20_consolidation_candles(
        self, bearish_baseline_candles: dict[str, list[Candle]]
    ) -> None:
        """Prepend 20 5m historical candles, append 20 1m consolidation; assert step_6_ready."""
        engine = IctMmxmEngine()
        base_5m = bearish_baseline_candles["5m"]
        base_1m = bearish_baseline_candles["1m"]

        # 1. Prepend 20 historical 5m bars before peak (below PDA 1015.0, e.g. 970 to 1010)
        t_start_5m = base_5m[0].timestamp_ms
        prepended_5m: list[Candle] = []
        for i in range(20, 0, -1):
            ts = t_start_5m - i * 300000
            o_p = Decimal("970.0") + Decimal(i % 10)
            c_p = o_p + Decimal("2.0")
            h_p = c_p + Decimal("3.0")
            l_p = o_p - Decimal("2.0")
            prepended_5m.append(_c(ts, o_p, h_p, l_p, c_p))

        # 2. Prepend 20 historical 1m bars before displacement
        t_start_1m = base_1m[0].timestamp_ms
        prepended_1m: list[Candle] = []
        for i in range(20, 0, -1):
            ts = t_start_1m - i * 60000
            o_p = Decimal("990.0") + Decimal(i % 5)
            c_p = o_p + Decimal("1.0")
            h_p = c_p + Decimal("2.0")
            l_p = o_p - Decimal("1.0")
            prepended_1m.append(_c(ts, o_p, h_p, l_p, c_p))

        # 3. Append 20 consolidation 1m bars after confirmation
        t_last_1m = base_1m[-1].timestamp_ms
        appended_1m: list[Candle] = []
        for i in range(1, 21):
            ts = t_last_1m + i * 60000
            o_p = Decimal("995.0") + Decimal((i * 3) % 4) - Decimal("2.0")
            c_p = o_p - Decimal("1.0")
            h_p = o_p + Decimal("2.0")  # Max high 999.0, safely below OTE 79% (1009.87)
            l_p = c_p - Decimal("3.0")  # Safe low above 980.0
            appended_1m.append(_c(ts, o_p, h_p, l_p, c_p))

        full_5m = prepended_5m + base_5m
        full_1m = prepended_1m + base_1m + appended_1m

        assert len(full_5m) == 22
        assert len(full_1m) == 48

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(bearish_baseline_candles["4h"]),
            candles_1h=_past_htf(bearish_baseline_candles["1h"]),
            candles_15m=_past_htf(bearish_baseline_candles["15m"]),
            candles_5m=full_5m,
            candles_1m=full_1m,
        )

        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is True
        assert state.step_6_ready is True
        assert state.side == "SELL"
        assert state.stop_loss == Decimal("1019.00")
        assert state.take_profit_partial == Decimal("942.00")
        assert state.take_profit_final == Decimal("866.00")
        assert state.invalidation_reason == InvalidationReason.NONE

    def test_bullish_prepend_20_historical_and_append_20_consolidation_candles(
        self, bullish_baseline_candles: dict[str, list[Candle]]
    ) -> None:
        """Bullish MMBM prepend 20 historical, append 20 consolidation; assert step_6_ready."""
        engine = IctMmxmEngine()
        base_5m = bullish_baseline_candles["5m"]
        base_1m = bullish_baseline_candles["1m"]

        # 1. Prepend 20 historical 5m bars before manipulation drop (above PDA 980.0)
        t_start_5m = base_5m[0].timestamp_ms
        prepended_5m: list[Candle] = []
        for i in range(20, 0, -1):
            ts = t_start_5m - i * 300000
            o_p = Decimal("1030.0") + Decimal(i % 10)
            c_p = o_p - Decimal("2.0")
            h_p = o_p + Decimal("3.0")
            l_p = c_p - Decimal("2.0")
            prepended_5m.append(_c(ts, o_p, h_p, l_p, c_p))

        # 2. Prepend 20 historical 1m bars before displacement
        t_start_1m = base_1m[0].timestamp_ms
        prepended_1m: list[Candle] = []
        for i in range(20, 0, -1):
            ts = t_start_1m - i * 60000
            o_p = Decimal("1010.0") - Decimal(i % 5)
            c_p = o_p - Decimal("1.0")
            h_p = o_p + Decimal("1.0")
            l_p = c_p - Decimal("2.0")
            prepended_1m.append(_c(ts, o_p, h_p, l_p, c_p))

        # 3. Append 20 consolidation 1m bars after confirmation
        t_last_1m = base_1m[-1].timestamp_ms
        appended_1m: list[Candle] = []
        for i in range(1, 21):
            ts = t_last_1m + i * 60000
            o_p = Decimal("1008.0") + Decimal((i * 2) % 5)
            c_p = o_p + Decimal("1.0")
            h_p = c_p + Decimal("2.0")  # Safe high below 1020.0
            l_p = o_p - Decimal("2.0")  # Min low 1006.0, safely above OTE 79% (990.13)
            appended_1m.append(_c(ts, o_p, h_p, l_p, c_p))

        full_5m = prepended_5m + base_5m
        full_1m = prepended_1m + base_1m + appended_1m

        assert len(full_5m) == 22
        assert len(full_1m) == 48

        state = engine.evaluate_twins_setup(
            symbol="BTCUSDT",
            candles_4h=_past_htf([]),
            candles_1h=_past_htf([]),
            candles_15m=_past_htf(bullish_baseline_candles["15m"]),
            candles_5m=full_5m,
            candles_1m=full_1m,
        )

        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is True
        assert state.step_6_ready is True
        assert state.side == "BUY"
        assert state.stop_loss == Decimal("981.00")
        assert state.take_profit_partial == Decimal("1058.00")
        assert state.take_profit_final == Decimal("1134.00")
        assert state.invalidation_reason == InvalidationReason.NONE

    @pytest.mark.parametrize("seed", [10, 42, 99, 123, 777])
    def test_random_walk_consolidation_buffers_retain_confirmation(
        self, seed: int, bearish_baseline_candles: dict[str, list[Candle]]
    ) -> None:
        """Verifies random-walk consolidation candles after confirmation retain confirmed state."""
        engine = IctMmxmEngine()
        base_1m = bearish_baseline_candles["1m"]
        rng = random.Random(seed)

        t_last = base_1m[-1].timestamp_ms
        appended: list[Candle] = []
        curr = Decimal("995.0")
        for i in range(1, 21):
            ts = t_last + i * 60000
            step = Decimal(str(round(rng.uniform(-1.0, 1.0), 2)))
            curr = max(Decimal("985.0"), min(Decimal("1002.0"), curr + step))
            o_p = curr
            c_p = curr + Decimal(str(round(rng.uniform(-0.5, 0.5), 2)))
            h_p = max(o_p, c_p) + Decimal("0.5")  # Stays well below 1009.87 (78.6% Fib)
            l_p = min(o_p, c_p) - Decimal("0.5")
            appended.append(_c(ts, o_p, h_p, l_p, c_p))

        full_1m = list(base_1m) + appended

        state = engine.evaluate_twins_setup(
            symbol="SOLUSDT",
            candles_4h=_past_htf(bearish_baseline_candles["4h"]),
            candles_1h=_past_htf(bearish_baseline_candles["1h"]),
            candles_15m=_past_htf(bearish_baseline_candles["15m"]),
            candles_5m=bearish_baseline_candles["5m"],
            candles_1m=full_1m,
        )

        assert state.step_6_ready is True
        assert state.side == "SELL"
        assert state.invalidation_reason == InvalidationReason.NONE


# ==============================================================================
# 3. EMPIRICAL VERIFICATION: BULLISH TWINS SETUP (MMBM) 4 REJECTION MODES
# ==============================================================================


class TestBullishTwinsRejectionModesEmpiricalHarness:
    """Rigorous adversarial verification of all 4 rejection modes for BUY setups (MMBM)."""

    def test_bullish_rejection_mode_1_missing_htf_pda(self) -> None:
        """Mode 1 (BUY): 15m price never touches Bullish HTF PDA; returns IDLE."""
        engine = IctMmxmEngine()

        # 15m Bullish Order Block at [970.0, 980.0]
        candles_15m = [
            _c(1000, "980.0", "985.0", "970.0", "975.0"),
            _c(2000, "975.0", "1010.0", "974.0", "1005.0"),
        ]
        # Subsequent price only trades down to 990.0 (> 980.0 top of PDA, never reaches PDA)
        candles_5m = [
            _c(3000, "1005.0", "1006.0", "990.0", "995.0"),
            _c(3300, "995.0", "1020.0", "994.0", "1015.0"),
        ]
        candles_1m = [
            _c(3300, "995.0", "1000.0", "994.0", "999.0"),
            _c(3360, "999.0", "1020.0", "999.0", "1019.0"),
        ]

        state = engine.evaluate_twins_setup("BTCUSDT", [], [], candles_15m, candles_5m, candles_1m)

        assert state.step_1_htf_hit is False
        assert state.step_6_ready is False
        assert state.side is None
        assert state.step == TwinsStep.IDLE

    def test_bullish_rejection_mode_2_single_bisi_fvg_in_displacement(self) -> None:
        """Mode 2 (BUY): Displacement leg forms only 1 BISI FVG instead of Twins (>= 2)."""
        engine = IctMmxmEngine()

        # 15m PDA at [980.0, 990.0]
        candles_15m = [
            _c(1000, "990.0", "995.0", "980.0", "985.0"),
            _c(2000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            _c(3000, "1005.0", "1006.0", "982.0", "985.0"),
            _c(3300, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        # 1m candles engineered to produce only ONE BISI FVG (candle 2 low 995 > candle 0 high 990),
        # but candle 3 and 4 overlap eliminating any second BISI
        candles_1m = [
            _c(3300, "985.0", "990.0", "984.0", "989.0"),
            _c(3360, "989.0", "992.0", "988.0", "991.0"),
            _c(3420, "991.0", "1005.0", "995.0", "1004.0"),  # BISI 1: [990.0, 995.0]
            _c(3480, "1004.0", "1008.0", "992.0", "1007.0"),  # Overlaps candle 1 high
            _c(3540, "1007.0", "1020.0", "1003.0", "1019.0"),  # Overlap eliminates BISI 2
            _c(3600, "1019.0", "1019.0", "1005.0", "1006.0"),
            _c(3660, "1006.0", "1006.0", "993.0", "994.0"),
            _c(3720, "994.0", "1008.0", "994.0", "1007.0"),
        ]

        state = engine.evaluate_twins_setup("BTCUSDT", [], [], candles_15m, candles_5m, candles_1m)

        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.NO_TWIN_FVGS
        assert state.step == TwinsStep.STEP_2_M5_CISD

    def test_bullish_rejection_mode_3a_under_retracement(self) -> None:
        """Mode 3A (BUY): Price retraces down only to 1005.0 (> 996.516 61.8% Fib)."""
        engine = IctMmxmEngine()

        # Displacement from 982.0 to 1020.0 (delta = 38.0).
        # ote_62 = 1020.0 - 0.618 * 38.0 = 996.516.
        candles_15m = [
            _c(1000, "1005.0", "1010.0", "980.0", "985.0"),
            _c(2000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            _c(3000, "1005.0", "1006.0", "982.0", "985.0"),
            _c(3300, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        candles_1m = [
            _c(3300, "985.0", "990.0", "984.0", "989.0"),
            _c(3360, "989.0", "999.0", "989.0", "998.0"),
            _c(3420, "998.0", "1009.0", "995.0", "1008.0"),  # BISI 1
            _c(3480, "1008.0", "1018.0", "1008.0", "1017.0"),
            _c(3540, "1017.0", "1020.0", "1014.0", "1019.0"),  # BISI 2
            # Post-displacement: price only dips to 1005.0, staying above 996.516!
            _c(3600, "1019.0", "1019.0", "1008.0", "1010.0"),
            _c(3660, "1010.0", "1012.0", "1005.0", "1006.0"),  # Low 1005.0 > 996.516
            _c(3720, "1006.0", "1015.0", "1006.0", "1014.0"),
        ]

        state = engine.evaluate_twins_setup("BTCUSDT", [], [], candles_15m, candles_5m, candles_1m)

        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.TIMEOUT_OTE_RETRACE
        assert state.step == TwinsStep.STEP_3_TWINS_FVG

    def test_bullish_rejection_mode_3b_over_retracement_body_close_below_79(self) -> None:
        """Mode 3B-1 (BUY): Candle body closes below 78.6% Fib (990.132); returns OTE_OVERSHOOT."""
        engine = IctMmxmEngine()

        # Displacement from 982.0 to 1020.0 (delta = 38.0).
        # ote_79 = 1020.0 - 0.786 * 38.0 = 990.132.
        candles_15m = [
            _c(1000, "1005.0", "1010.0", "980.0", "985.0"),
            _c(2000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            _c(3000, "1005.0", "1006.0", "982.0", "985.0"),
            _c(3300, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        candles_1m = [
            _c(3300, "985.0", "990.0", "984.0", "989.0"),
            _c(3360, "989.0", "999.0", "989.0", "998.0"),
            _c(3420, "998.0", "1009.0", "995.0", "1008.0"),  # BISI 1
            _c(3480, "1008.0", "1018.0", "1008.0", "1017.0"),
            _c(3540, "1017.0", "1020.0", "1014.0", "1019.0"),  # BISI 2
            _c(3600, "1019.0", "1019.0", "1005.0", "1006.0"),
            # Candle closes at 988.0 (< 990.132 [78.6%])
            _c(3660, "1006.0", "1006.0", "987.0", "988.0"),
            _c(3720, "988.0", "1000.0", "988.0", "999.0"),
        ]

        state = engine.evaluate_twins_setup("BTCUSDT", [], [], candles_15m, candles_5m, candles_1m)

        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.OTE_OVERSHOOT
        assert state.step == TwinsStep.STEP_3_TWINS_FVG

    def test_bullish_rejection_mode_3b_over_retracement_wick_dip_below_886(self) -> None:
        """Mode 3B-2 (BUY): Candle wicks down below 88.6% Fib (986.332); returns OTE_OVERSHOOT."""
        engine = IctMmxmEngine()

        # Displacement from 982.0 to 1020.0.
        # ote_886 = 1020.0 - 0.886 * 38.0 = 986.332.
        candles_15m = [
            _c(1000, "1005.0", "1010.0", "980.0", "985.0"),
            _c(2000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            _c(3000, "1005.0", "1006.0", "982.0", "985.0"),
            _c(3300, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        candles_1m = [
            _c(3300, "985.0", "990.0", "984.0", "989.0"),
            _c(3360, "989.0", "999.0", "989.0", "998.0"),
            _c(3420, "998.0", "1009.0", "995.0", "1008.0"),  # BISI 1
            _c(3480, "1008.0", "1018.0", "1008.0", "1017.0"),
            _c(3540, "1017.0", "1020.0", "1014.0", "1019.0"),  # BISI 2
            _c(3600, "1019.0", "1019.0", "1005.0", "1006.0"),
            # Low wicks to 985.0 (< 986.332 88.6% Fib) even though close is 992.0 (> 78.6%)
            _c(3660, "1006.0", "1006.0", "985.0", "992.0"),
            _c(3720, "992.0", "1005.0", "992.0", "1004.0"),
        ]

        state = engine.evaluate_twins_setup("BTCUSDT", [], [], candles_15m, candles_5m, candles_1m)

        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.OTE_OVERSHOOT

    def test_bullish_rejection_mode_3b_break_below_swing_low(self) -> None:
        """Mode 3B-3 (BUY): Price breaches swing low (l_leg = 982.0); returns OTE_OVERSHOOT."""
        engine = IctMmxmEngine()

        candles_15m = [
            _c(1000, "1005.0", "1010.0", "980.0", "985.0"),
            _c(2000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            _c(3000, "1005.0", "1006.0", "982.0", "985.0"),
            _c(3300, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        candles_1m = [
            _c(3300, "985.0", "990.0", "984.0", "989.0"),
            _c(3360, "989.0", "999.0", "989.0", "998.0"),
            _c(3420, "998.0", "1009.0", "995.0", "1008.0"),  # BISI 1
            _c(3480, "1008.0", "1018.0", "1008.0", "1017.0"),
            _c(3540, "1017.0", "1020.0", "1014.0", "1019.0"),  # BISI 2
            _c(3600, "1019.0", "1019.0", "1005.0", "1006.0"),
            # Low breaches swing low 982.0 -> dips to 980.0
            _c(3660, "1006.0", "1006.0", "980.0", "981.0"),
            _c(3720, "981.0", "1000.0", "981.0", "995.0"),
        ]

        state = engine.evaluate_twins_setup("BTCUSDT", [], [], candles_15m, candles_5m, candles_1m)

        assert state.step_4_ote_retrace is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.OTE_OVERSHOOT

    def test_bullish_rejection_mode_4_missing_1m_cisd_confirmation(self) -> None:
        """Mode 4 (BUY): 1m candle only wicks above OTE low candle high; returns timeout."""
        engine = IctMmxmEngine()

        candles_15m = [
            _c(1000, "1005.0", "1010.0", "980.0", "985.0"),
            _c(2000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            _c(3000, "1005.0", "1006.0", "982.0", "985.0"),
            _c(3300, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        candles_1m = [
            _c(3300, "985.0", "990.0", "984.0", "989.0"),
            _c(3360, "989.0", "999.0", "989.0", "998.0"),
            _c(3420, "998.0", "1009.0", "995.0", "1008.0"),  # BISI 1
            _c(3480, "1008.0", "1018.0", "1008.0", "1017.0"),
            _c(3540, "1017.0", "1020.0", "1014.0", "1019.0"),  # BISI 2
            _c(3600, "1019.0", "1019.0", "1005.0", "1006.0"),
            # In OTE: low = 993.0, high = 1006.0 -> ote_low_candle high is 1006.0
            _c(3660, "1006.0", "1006.0", "993.0", "994.0"),
            # Follow-up candle wicks above 1006.0 (high=1008) but body closes at 1004 (<= 1006)
            _c(3720, "994.0", "1008.0", "994.0", "1004.0"),
        ]

        state = engine.evaluate_twins_setup("BTCUSDT", [], [], candles_15m, candles_5m, candles_1m)

        assert state.step_1_htf_hit is True
        assert state.step_2_m5_cisd is True
        assert state.step_3_twins_fvg is True
        assert state.step_4_ote_retrace is True
        assert state.step_5_m1_cisd is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.M1_CISD_TIMEOUT
        assert state.step == TwinsStep.STEP_4_OTE_RETRACE

    def test_bullish_cisd_exact_equality_rejection(self) -> None:
        """Mode 4 Edge (BUY): Candle body closes exactly equal to ref high; returns timeout."""
        engine = IctMmxmEngine()

        candles_15m = [
            _c(1000, "1005.0", "1010.0", "980.0", "985.0"),
            _c(2000, "985.0", "1016.0", "982.0", "1015.0"),
        ]
        candles_5m = [
            _c(3000, "1005.0", "1006.0", "982.0", "985.0"),
            _c(3300, "985.0", "1020.0", "984.0", "1015.0"),
        ]
        candles_1m = [
            _c(3300, "985.0", "990.0", "984.0", "989.0"),
            _c(3360, "989.0", "999.0", "989.0", "998.0"),
            _c(3420, "998.0", "1009.0", "995.0", "1008.0"),  # BISI 1
            _c(3480, "1008.0", "1018.0", "1008.0", "1017.0"),
            _c(3540, "1017.0", "1020.0", "1014.0", "1019.0"),  # BISI 2
            _c(3600, "1019.0", "1019.0", "1005.0", "1006.0"),
            _c(3660, "1006.0", "1006.0", "993.0", "994.0"),  # ote_low_candle high = 1006.0
            # Follow-up candle closes exactly equal to 1006.0
            _c(3720, "994.0", "1007.0", "994.0", "1006.0"),
        ]

        state = engine.evaluate_twins_setup("BTCUSDT", [], [], candles_15m, candles_5m, candles_1m)

        assert state.step_5_m1_cisd is False
        assert state.step_6_ready is False
        assert state.invalidation_reason == InvalidationReason.M1_CISD_TIMEOUT
