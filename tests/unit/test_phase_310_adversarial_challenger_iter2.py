"""Phase 310 Iteration 2 Adversarial Challenger Test Suite.

Adversarially stresses and verifies:
1. Child order sizing non-deadlock across 1,000 synthetic price levels ($10 to $100,000)
   on SOLUSDT and ETHUSDT (actual notional >= MIN_NOTIONAL, within micro-capital step tolerance,
   0% deadlocked rejections).
2. Fail-closed 4h warmup logic in MacroTrendFilter: returns False for 0, 1, 50, 199 bars,
   and only evaluates EMA when >= 200 bars.
3. Strict symbol gating: unallowed symbols (XRPUSDT, DOGEUSDT, BTCUSDT) are rejected
   in MacroLiquidityDipScalper.evaluate_15m_bar.
4. Telemetry database population: canary-production-telemetry.sqlite3 contains non-zero
   record counts for orders, trade_autopsies, candidate_health, and solvency_snapshots.
"""

from __future__ import annotations

import math
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.execution.binance_gateway import DEFAULT_SPECS
from autonomous_futures.execution.self_driving import build_default_self_driving_engine
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TELEMETRY_DB = (
    _REPO_ROOT / "artifacts" / "research" / "phase310" / "canary-production-telemetry.sqlite3"
)
_SUMMARY_JSON = _REPO_ROOT / "artifacts" / "research" / "phase310" / "production-summary.json"


def _make_candle(
    ts_ms: int,
    open_p: str | float | Decimal,
    high_p: str | float | Decimal,
    low_p: str | float | Decimal,
    close_p: str | float | Decimal,
    volume: str | float | Decimal,
) -> Candle:
    """Helper to construct a Candle instance."""
    return Candle(
        timestamp_ms=ts_ms,
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        volume=Decimal(str(volume)),
    )


def _build_synthetic_bull_candles(count: int, interval_ms: int = 14400000) -> list[Candle]:
    """Builds upward-trending candle series where EMA 50 > EMA 200 and close > EMA 200."""
    candles: list[Candle] = []
    base_price = Decimal("50000.00")
    for i in range(count):
        # Monotonically increasing price
        price = base_price + Decimal(str(i * 100))
        candles.append(
            _make_candle(
                ts_ms=i * interval_ms,
                open_p=price,
                high_p=price + Decimal("50.00"),
                low_p=price - Decimal("50.00"),
                close_p=price,
                volume="100.0",
            )
        )
    return candles


def _build_synthetic_bear_candles(count: int, interval_ms: int = 14400000) -> list[Candle]:
    """Builds downward-trending candle series where EMA 50 < EMA 200."""
    candles: list[Candle] = []
    base_price = Decimal("100000.00")
    for i in range(count):
        # Monotonically decreasing price
        price = base_price - Decimal(str(i * 100))
        candles.append(
            _make_candle(
                ts_ms=i * interval_ms,
                open_p=price,
                high_p=price + Decimal("50.00"),
                low_p=price - Decimal("50.00"),
                close_p=price,
                volume="100.0",
            )
        )
    return candles


# ==============================================================================
# SECTION 1: ORDER SIZING NON-DEADLOCK STRESS (1,000 PRICE LEVELS PER SYMBOL)
# ==============================================================================


class TestOrderSizingNonDeadlockStress:
    """Adversarially stress-tests _calculate_child_order_qty against deadlocks."""

    @pytest.mark.parametrize("symbol", ["SOLUSDT", "ETHUSDT"])
    def test_sizing_non_deadlock_1000_price_levels(self, tmp_path: Path, symbol: str) -> None:
        """Verifies 1,000 synthetic price levels ($10 to $100,000) produce 0% deadlocks.

        For both SOLUSDT and ETHUSDT:
        - actual_notional >= MIN_NOTIONAL (5.00 USDT)
        - actual_notional <= target_notional + (step_size * quantized_price)
        - quantized_qty > 0 (0% deadlocked rejections)
        """
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        spec = DEFAULT_SPECS[symbol]
        step_size = spec["step_size"]
        min_notional = spec["min_notional"]
        target_notional = engine.config.max_micro_order_notional_usdt

        deadlocked_count = 0
        total_levels = 1000

        # Logarithmic distribution spanning $10.00 to $100,000.00
        min_p = 10.0
        max_p = 100000.0

        for i in range(total_levels):
            # Generate log-spaced price
            ratio = i / (total_levels - 1)
            raw_p = min_p * math.exp(ratio * math.log(max_p / min_p))
            price = Decimal(str(round(raw_p, 2)))

            quantized_price, quantized_qty, actual_notional = engine._calculate_child_order_qty(
                symbol, price
            )

            # Invariant 1: No deadlock (quantity must be strictly positive)
            if quantized_qty <= Decimal("0.0"):
                deadlocked_count += 1
                continue

            # Invariant 2: Actual notional satisfies Binance MIN_NOTIONAL
            assert actual_notional >= min_notional, (
                f"[{symbol}] Price {price} resulted in sub-minimum notional: "
                f"{actual_notional} < {min_notional}"
            )

            # Invariant 3: Actual notional stays within micro-capital step tolerance
            max_allowed = target_notional + (step_size * quantized_price)
            assert actual_notional <= max_allowed, (
                f"[{symbol}] Price {price} exceeded micro-capital tolerance: "
                f"{actual_notional} > {max_allowed}"
            )

            # Invariant 4: Precision math consistency
            expected_notional = quantized_qty * quantized_price
            assert actual_notional == expected_notional, (
                f"[{symbol}] Notional mismatch: {actual_notional} != {expected_notional}"
            )

        # Invariant 5: Zero deadlocked rejections across all 1,000 price levels
        assert deadlocked_count == 0, (
            f"[{symbol}] Detected {deadlocked_count}/{total_levels} deadlocked orders!"
        )

    def test_unallowed_symbol_sizing_rejected_when_sub_notional(self, tmp_path: Path) -> None:
        """Verifies unallowed symbols (e.g. BTCUSDT) are rejected without step-up."""
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        # With BTCUSDT at price 65,000, target 5.00 USDT yields raw_qty = 0.0000769
        # With step_size 0.00001, raw_qty is 0.00007 -> notional 4.55 USDT < 5.00 USDT
        quantized_price, quantized_qty, actual_notional = engine._calculate_child_order_qty(
            "BTCUSDT", Decimal("65000.00")
        )
        assert quantized_qty == Decimal("0.0")
        assert actual_notional == Decimal("0.0")


# ==============================================================================
# SECTION 2: 4H WARMUP FAIL-CLOSED LOGIC
# ==============================================================================


class TestMacroTrendFilterWarmupFailClosed:
    """Verifies fail-closed behavior of MacroTrendFilter on incomplete 4h history."""

    @pytest.mark.parametrize("bar_count", [0, 1, 50, 199])
    def test_4h_candles_insufficient_bars_fails_closed(self, bar_count: int) -> None:
        """Verifies MacroTrendFilter returns False when 4h history has < 200 bars."""
        trend_filter = MacroTrendFilter(ema_fast=50, ema_slow=200)

        # 1h series is fully warmed up and in clear bull regime (250 bars)
        candles_1h = _build_synthetic_bull_candles(250, interval_ms=3600000)

        # 4h series has insufficient bars (< 200)
        candles_4h = _build_synthetic_bull_candles(bar_count, interval_ms=14400000)

        # Must fail closed: False
        is_bull = trend_filter.evaluate(candles_1h, candles_4h)
        assert is_bull is False, (
            f"Expected fail-closed (False) for {bar_count} 4h bars, but got {is_bull}"
        )

    def test_4h_candles_evaluates_only_when_ge_200_bars(self) -> None:
        """Verifies MacroTrendFilter evaluates 4h EMA when >= 200 bars are present."""
        trend_filter = MacroTrendFilter(ema_fast=50, ema_slow=200)
        candles_1h = _build_synthetic_bull_candles(250, interval_ms=3600000)

        # Test at exact boundary: 200 bars (bullish)
        candles_4h_bull_200 = _build_synthetic_bull_candles(200, interval_ms=14400000)
        assert trend_filter.evaluate(candles_1h, candles_4h_bull_200) is True

        # Test at exact boundary: 200 bars (bearish)
        candles_4h_bear_200 = _build_synthetic_bear_candles(200, interval_ms=14400000)
        assert trend_filter.evaluate(candles_1h, candles_4h_bear_200) is False

        # Test above boundary: 250 bars (bullish)
        candles_4h_bull_250 = _build_synthetic_bull_candles(250, interval_ms=14400000)
        assert trend_filter.evaluate(candles_1h, candles_4h_bull_250) is True

        # Test above boundary: 250 bars (bearish)
        candles_4h_bear_250 = _build_synthetic_bear_candles(250, interval_ms=14400000)
        assert trend_filter.evaluate(candles_1h, candles_4h_bear_250) is False

    @pytest.mark.parametrize("bar_count_1h", [0, 1, 50, 199])
    def test_1h_candles_insufficient_bars_fails_closed(self, bar_count_1h: int) -> None:
        """Verifies MacroTrendFilter returns False when 1h history has < 200 bars."""
        trend_filter = MacroTrendFilter(ema_fast=50, ema_slow=200)
        candles_1h = _build_synthetic_bull_candles(bar_count_1h, interval_ms=3600000)
        assert trend_filter.evaluate(candles_1h) is False


# ==============================================================================
# SECTION 3: SYMBOL GATING IN EVALUATE_15M_BAR
# ==============================================================================


class TestMacroScalperSymbolGating:
    """Verifies strict symbol gating in MacroLiquidityDipScalper.evaluate_15m_bar."""

    @pytest.fixture
    def setup_dip_conditions(self) -> tuple[Candle, list[Candle]]:
        """Sets up 15m candle conditions that satisfy all dip entry criteria."""
        history: list[Candle] = []
        base_price = Decimal("180.00")
        for i in range(40):
            history.append(
                _make_candle(
                    ts_ms=i * 900000,
                    open_p=base_price,
                    high_p=base_price + Decimal("0.50"),
                    low_p=base_price - Decimal("0.50"),
                    close_p=base_price,
                    volume="1000.0",
                )
            )

        # Severe dip candle meeting all entry rules:
        # Distance > 2.5x ATR below 20 EMA, Volume > 2.2x SMA, RSI < 26
        dip_bar = _make_candle(
            ts_ms=40 * 900000,
            open_p="180.00",
            high_p="180.50",
            low_p="164.50",
            close_p="165.00",
            volume="4500.0",
        )
        return dip_bar, history

    @pytest.mark.parametrize(
        "unallowed_symbol",
        [
            "XRPUSDT",
            "DOGEUSDT",
            "BTCUSDT",
            "ADAUSDT",
            "PEPEUSDT",
            "xrpusdt",
            "dogeusdt",
            "btcusdt",
            "INVALID",
            "",
        ],
    )
    def test_unallowed_symbols_strictly_rejected(
        self,
        setup_dip_conditions: tuple[Candle, list[Candle]],
        unallowed_symbol: str,
    ) -> None:
        """Verifies that unallowed symbols return None even during valid dips."""
        dip_bar, history = setup_dip_conditions
        scalper = MacroLiquidityDipScalper()

        signal = scalper.evaluate_15m_bar(
            symbol=unallowed_symbol,
            bar=dip_bar,
            history=history,
            macro_trend_allowed=True,
        )
        assert signal is None, f"Expected None for unallowed symbol '{unallowed_symbol}'"

    @pytest.mark.parametrize("allowed_symbol", ["SOLUSDT", "ETHUSDT", "solusdt", "ethusdt"])
    def test_allowed_symbols_generate_valid_signals(
        self,
        setup_dip_conditions: tuple[Candle, list[Candle]],
        allowed_symbol: str,
    ) -> None:
        """Verifies allowed symbols (SOLUSDT, ETHUSDT) generate valid ScalperSignal."""
        dip_bar, history = setup_dip_conditions
        scalper = MacroLiquidityDipScalper()

        signal = scalper.evaluate_15m_bar(
            symbol=allowed_symbol,
            bar=dip_bar,
            history=history,
            macro_trend_allowed=True,
        )
        assert signal is not None, f"Expected valid signal for allowed symbol '{allowed_symbol}'"
        assert signal.side == "BUY"
        assert signal.order_type == "LIMIT"
        assert signal.stop_loss < signal.sweep_price
        assert signal.take_profit > signal.sweep_price


# ==============================================================================
# SECTION 4: SQLITE TELEMETRY POPULATION VERIFICATION
# ==============================================================================


class TestSQLiteTelemetryPopulation:
    """Verifies that production SQLite telemetry database has non-zero records."""

    def test_telemetry_db_exists(self) -> None:
        """Verifies that canary-production-telemetry.sqlite3 exists and is readable."""
        assert _TELEMETRY_DB.exists(), f"Telemetry DB not found at {_TELEMETRY_DB}"
        assert _TELEMETRY_DB.stat().st_size > 0, "Telemetry DB file is 0 bytes"

    @pytest.mark.parametrize(
        ("table_name", "min_records"),
        [
            ("orders", 2),
            ("trade_autopsies", 1),
            ("candidate_health", 1),
            ("solvency_snapshots", 1),
        ],
    )
    def test_telemetry_tables_have_non_zero_records(
        self, table_name: str, min_records: int
    ) -> None:
        """Verifies orders, autopsies, health, and solvency tables contain records."""
        conn = sqlite3.connect(str(_TELEMETRY_DB))
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cur.fetchone()[0]
        conn.close()

        assert count >= min_records, (
            f"Table '{table_name}' expected at least {min_records} records, found {count}"
        )

    def test_telemetry_orders_contain_genuine_scalper_trades(self) -> None:
        """Verifies orders table contains real BUY and SELL executions."""
        conn = sqlite3.connect(str(_TELEMETRY_DB))
        cur = conn.cursor()
        cur.execute("SELECT symbol, side, order_type, status, price, quantity FROM orders")
        rows = cur.fetchall()
        conn.close()

        assert len(rows) >= 2, f"Expected >= 2 orders, found {len(rows)}"
        symbols = {r[0] for r in rows}
        sides = {r[1] for r in rows}

        assert "SOLUSDT" in symbols or "ETHUSDT" in symbols
        assert "BUY" in sides
        assert "SELL" in sides

    def test_solvency_snapshots_zero_balance_drift_invariant(self) -> None:
        """Verifies solvency snapshots record strictly zero balance drift."""
        conn = sqlite3.connect(str(_TELEMETRY_DB))
        cur = conn.cursor()
        cur.execute(
            "SELECT drift, starting_equity, total_equity, cash, realized_pnl "
            "FROM solvency_snapshots"
        )
        rows = cur.fetchall()
        conn.close()

        assert len(rows) >= 1
        for drift_val, starting_eq, total_eq, _cash, _realized_pnl in rows:
            drift = Decimal(str(drift_val))
            assert abs(drift) < Decimal("1e-15"), f"Drift exceeded zero tolerance: {drift}"
            # Double entry invariant: total_equity stays within daily risk budget
            assert Decimal(str(total_eq)) >= Decimal(str(starting_eq)) - Decimal("3.00")

    def test_sqlite_views_are_queryable(self) -> None:
        """Verifies compatibility views (trades, autopsies, reconciliation, telemetry)."""
        conn = sqlite3.connect(str(_TELEMETRY_DB))
        cur = conn.cursor()
        for view_name in ("trades", "autopsies", "reconciliation", "telemetry"):
            cur.execute(f"SELECT COUNT(*) FROM {view_name}")
            count = cur.fetchone()[0]
            assert count >= 0
        conn.close()
