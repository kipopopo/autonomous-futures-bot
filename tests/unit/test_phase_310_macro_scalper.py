"""Autonomous Futures Bot - Phase 310 Unit Tests: Macro Liquidity Scalper & Regime Filter.

Verifies:
- Mathematical correctness of streaming technical indicators (EMA, ATR, SMA, RSI)
- MacroTrendFilter BTC 1h/4h regime alignment (EMA 50 > EMA 200 gate)
- MacroLiquidityDipScalper 15m entry triggers:
    * Distance in ATR < -2.5 (price > 2.5x ATR below 20 EMA)
    * Volume spike > 2.2x 20 SMA
    * RSI 14 < 26.0
- Trade structuring: Maker Limit orders, 1.2x ATR Stop Loss, 2.0x ATR Take Profit (1.66:1 R:R)
- Momentum decay stop: max 8 bars (120 minutes)
- Fail-closed behavior on insufficient historical warmup bars
"""

from __future__ import annotations

from decimal import Decimal

from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
    compute_atr,
    compute_ema,
    compute_rsi,
    compute_sma,
)


def _make_candle(
    ts_ms: int,
    open_p: str | float | Decimal,
    high_p: str | float | Decimal,
    low_p: str | float | Decimal,
    close_p: str | float | Decimal,
    volume: str | float | Decimal,
) -> Candle:
    return Candle(
        timestamp_ms=ts_ms,
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        volume=Decimal(str(volume)),
    )


class TestIndicatorsMath:
    """Verifies precision and behavior of streaming indicator functions."""

    def test_compute_ema_constant_series(self) -> None:
        series = [Decimal("100.00")] * 30
        ema = compute_ema(series, 10)
        assert len(ema) == 30
        assert ema[-1] == Decimal("100.00")

    def test_compute_ema_uptrend_weighting(self) -> None:
        # Step change from 100 to 200
        series = [Decimal("100.00")] * 10 + [Decimal("200.00")] * 10
        ema = compute_ema(series, 5)
        # EMA should react faster than a simple average
        assert ema[-1] > Decimal("180.00")

    def test_compute_sma_correctness(self) -> None:
        series = [Decimal(str(i)) for i in range(1, 11)]  # 1 to 10
        sma = compute_sma(series, 5)
        # Window of last 5: 6, 7, 8, 9, 10 -> average = 8.0
        assert sma[-1] == Decimal("8.0")

    def test_compute_atr_positive_and_consistent(self) -> None:
        candles: list[Candle] = []
        for i in range(25):
            candles.append(
                _make_candle(
                    ts_ms=i * 900000,
                    open_p="100.00",
                    high_p="105.00",
                    low_p="95.00",
                    close_p="102.00",
                    volume="500.0",
                )
            )
        atr = compute_atr(candles, 14)
        # True range for each candle is 105 - 95 = 10
        assert len(atr) == 25
        assert atr[-1] == Decimal("10.0")

    def test_compute_rsi_flat_and_oversold(self) -> None:
        # Flat prices -> RSI 50
        flat_prices = [Decimal("100.00")] * 20
        rsi_flat = compute_rsi(flat_prices, 14)
        assert rsi_flat[-1] == Decimal("50")

        # Monotonically declining prices -> RSI approaching 0
        falling_prices = [Decimal("200.00") - Decimal(str(i * 5)) for i in range(25)]
        rsi_falling = compute_rsi(falling_prices, 14)
        assert rsi_falling[-1] < Decimal("10")


class TestMacroTrendFilter:
    """Verifies BTC 1h/4h regime alignment gate."""

    def test_insufficient_bars_rejects_fail_closed(self) -> None:
        filter_gate = MacroTrendFilter(ema_fast=50, ema_slow=200)
        short_history = [
            _make_candle(i * 3600000, "60000", "60100", "59900", "60000", "10")
            for i in range(100)  # Only 100 bars, need 200
        ]
        assert filter_gate.evaluate(short_history) is False

    def test_bull_regime_accepted(self) -> None:
        filter_gate = MacroTrendFilter(ema_fast=50, ema_slow=200)
        # Upward sloping BTC history for 220 bars
        candles: list[Candle] = []
        for i in range(220):
            p = Decimal("60000") + Decimal(str(i * 50))
            candles.append(
                _make_candle(i * 3600000, p, p + Decimal("100"), p - Decimal("100"), p, "100")
            )
        assert filter_gate.evaluate(candles) is True

    def test_bear_regime_rejected(self) -> None:
        filter_gate = MacroTrendFilter(ema_fast=50, ema_slow=200)
        # Downward sloping BTC history for 220 bars
        candles: list[Candle] = []
        for i in range(220):
            p = Decimal("90000") - Decimal(str(i * 50))
            candles.append(
                _make_candle(i * 3600000, p, p + Decimal("100"), p - Decimal("100"), p, "100")
            )
        assert filter_gate.evaluate(candles) is False

    def test_4h_candles_insufficient_warmup_fails_closed(self) -> None:
        filter_gate = MacroTrendFilter(ema_fast=50, ema_slow=200)
        candles_1h = [
            _make_candle(
                i * 3600000,
                Decimal("60000") + Decimal(str(i * 50)),
                "60100",
                "59900",
                Decimal("60000") + Decimal(str(i * 50)),
                "100",
            )
            for i in range(220)
        ]
        # Only 50 candles on 4h -> must fail closed
        candles_4h = [
            _make_candle(
                i * 14400000,
                Decimal("60000") + Decimal(str(i * 200)),
                "60100",
                "59900",
                Decimal("60000") + Decimal(str(i * 200)),
                "400",
            )
            for i in range(50)
        ]
        assert filter_gate.evaluate(candles_1h, candles_4h) is False


class TestMacroLiquidityDipScalper:
    """Verifies 15m volume-backed liquidity capitulation dip triggers and order brackets."""

    def _build_baseline_history(
        self, count: int = 40, base_price: Decimal = Decimal("180.00")
    ) -> list[Candle]:
        history: list[Candle] = []
        for i in range(count):
            p = base_price + Decimal(str((i % 4) * 0.1))
            history.append(
                _make_candle(
                    ts_ms=i * 900000,
                    open_p=p,
                    high_p=p + Decimal("1.00"),
                    low_p=p - Decimal("1.00"),
                    close_p=p,
                    volume=Decimal("1000.0"),
                )
            )
        return history

    def test_scalper_triggers_on_valid_capitulation_dip(self) -> None:
        scalper = MacroLiquidityDipScalper()
        history = self._build_baseline_history(40, Decimal("180.00"))

        # Severe dip bar:
        # Price drops from 180 to 165 (severe > 2.5x ATR drop)
        # Volume spikes to 4000 (> 2.2x 1000 SMA)
        # Close at low -> RSI < 26
        dip_bar = _make_candle(
            ts_ms=40 * 900000,
            open_p="180.00",
            high_p="180.50",
            low_p="164.50",
            close_p="165.00",
            volume="4500.0",
        )

        signal = scalper.evaluate_15m_bar(
            symbol="SOLUSDT",
            bar=dip_bar,
            history=history,
            macro_trend_allowed=True,
        )

        assert signal is not None
        assert signal.symbol == "SOLUSDT"
        assert signal.side == "BUY"
        assert signal.order_type == "LIMIT"
        assert signal.is_maker is True
        assert signal.sweep_price == Decimal("165.00")

        # Protective Brackets check:
        # SL = sweep - 1.2 * ATR
        # TP = sweep + 2.0 * ATR
        assert signal.stop_loss < signal.sweep_price
        assert signal.take_profit > signal.sweep_price
        assert signal.reward_to_risk_ratio == Decimal("1.6667")
        assert signal.max_hold_bars == 8

    def test_scalper_vetoed_when_macro_trend_false(self) -> None:
        scalper = MacroLiquidityDipScalper()
        history = self._build_baseline_history(40, Decimal("180.00"))
        dip_bar = _make_candle(40 * 900000, "180.00", "180.50", "164.50", "165.00", "4500.0")

        # Macro trend not allowed -> returns None immediately
        signal = scalper.evaluate_15m_bar(
            symbol="SOLUSDT",
            bar=dip_bar,
            history=history,
            macro_trend_allowed=False,
        )
        assert signal is None

    def test_scalper_ignores_normal_consolidation(self) -> None:
        scalper = MacroLiquidityDipScalper()
        history = self._build_baseline_history(40, Decimal("180.00"))
        normal_bar = _make_candle(40 * 900000, "180.00", "180.50", "179.50", "180.10", "1100.0")

        signal = scalper.evaluate_15m_bar(
            symbol="SOLUSDT",
            bar=normal_bar,
            history=history,
            macro_trend_allowed=True,
        )
        assert signal is None

    def test_scalper_fails_when_volume_spike_missing(self) -> None:
        scalper = MacroLiquidityDipScalper()
        history = self._build_baseline_history(40, Decimal("180.00"))

        # Price dips but volume is normal (not > 2.2x SMA)
        low_vol_dip = _make_candle(40 * 900000, "180.00", "180.50", "164.50", "165.00", "1200.0")
        signal = scalper.evaluate_15m_bar(
            symbol="SOLUSDT",
            bar=low_vol_dip,
            history=history,
            macro_trend_allowed=True,
        )
        assert signal is None

    def test_scalper_rejects_unallowed_symbol(self) -> None:
        scalper = MacroLiquidityDipScalper()
        history = self._build_baseline_history(40, Decimal("180.00"))
        dip_bar = _make_candle(40 * 900000, "180.00", "180.50", "164.50", "165.00", "4500.0")

        # BTCUSDT is not in ALLOWED_SYMBOLS ("SOLUSDT", "ETHUSDT") -> must return None
        signal = scalper.evaluate_15m_bar(
            symbol="BTCUSDT",
            bar=dip_bar,
            history=history,
            macro_trend_allowed=True,
        )
        assert signal is None
