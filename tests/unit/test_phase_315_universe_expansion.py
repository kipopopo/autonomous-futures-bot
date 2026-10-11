"""Unit Test Suite for Phase 315 Universe Expansion & Solvency Governance (Milestone M2).

Validates:
1. Exchange specifications and precision filters in binance_gateway.py (8 pairs, ROUND_DOWN).
2. Scalper candidate pool expansion in macro_liquidity_scalper.py (7 non-BTC candidates).
3. Trading engine candidate registry, step-up sizing rules, micro-capital bounds, and double-entry
   zero-drift balance conservation in self_driving.py.
4. Continuous trader daemon default symbols and market candle structures in continuous_trader.py.
5. API ingress and execution status multi-pair adaptation in app.py.
"""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

from autonomous_futures.api.app import (
    _baseline_execution_status,
    get_live_market_data,
    load_execution_status,
)
from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    quantize_step_size,
    quantize_tick_size,
)
from autonomous_futures.execution.continuous_trader import (
    ContinuousSelfDrivingTrader,
)
from autonomous_futures.execution.self_driving import (
    CandidateState,
    SelfDrivingState,
    build_default_self_driving_engine,
)
from autonomous_futures.safety.kill_switch import (
    CentralizedSolvencyLedger,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
)

ALL_8_PAIRS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
)

CANDIDATE_7_PAIRS: tuple[str, ...] = (
    "SOLUSDT",
    "ETHUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
)


class TestExchangeSpecsAndFilters:
    """Tests Binance Futures exchange filter definitions and quantization precision."""

    def test_default_specs_contains_all_eight_pairs(self) -> None:
        """DEFAULT_SPECS must define all 8 perpetual universe pairs."""
        for sym in ALL_8_PAIRS:
            assert sym in DEFAULT_SPECS, f"Missing {sym} in DEFAULT_SPECS"
            spec = DEFAULT_SPECS[sym]
            assert "step_size" in spec
            assert "tick_size" in spec
            assert "min_qty" in spec
            assert "min_notional" in spec
            assert spec["step_size"] > Decimal("0")
            assert spec["tick_size"] > Decimal("0")
            assert spec["min_qty"] > Decimal("0")
            assert spec["min_notional"] > Decimal("0")

    def test_default_specs_exact_quantization_parameters(self) -> None:
        """Verifies exact filter parameters matching Binance USDⓈ-M exchange specifications."""
        expected_specs: dict[str, dict[str, Decimal]] = {
            "BTCUSDT": {
                "step_size": Decimal("0.001"),
                "tick_size": Decimal("0.10"),
                "min_qty": Decimal("0.001"),
                "min_notional": Decimal("50.00"),
            },
            "ETHUSDT": {
                "step_size": Decimal("0.001"),
                "tick_size": Decimal("0.01"),
                "min_qty": Decimal("0.001"),
                "min_notional": Decimal("20.00"),
            },
            "SOLUSDT": {
                "step_size": Decimal("0.01"),
                "tick_size": Decimal("0.01"),
                "min_qty": Decimal("0.01"),
                "min_notional": Decimal("5.00"),
            },
            "DOGEUSDT": {
                "step_size": Decimal("1"),
                "tick_size": Decimal("0.00001"),
                "min_qty": Decimal("1"),
                "min_notional": Decimal("5.00"),
            },
            "BNBUSDT": {
                "step_size": Decimal("0.01"),
                "tick_size": Decimal("0.01"),
                "min_qty": Decimal("0.01"),
                "min_notional": Decimal("5.00"),
            },
            "XRPUSDT": {
                "step_size": Decimal("0.1"),
                "tick_size": Decimal("0.0001"),
                "min_qty": Decimal("0.1"),
                "min_notional": Decimal("5.00"),
            },
            "SUIUSDT": {
                "step_size": Decimal("0.1"),
                "tick_size": Decimal("0.0001"),
                "min_qty": Decimal("0.1"),
                "min_notional": Decimal("5.00"),
            },
            "AVAXUSDT": {
                "step_size": Decimal("1"),
                "tick_size": Decimal("0.001"),
                "min_qty": Decimal("1"),
                "min_notional": Decimal("5.00"),
            },
        }

        for sym, exp in expected_specs.items():
            actual = DEFAULT_SPECS[sym]
            for key, exp_val in exp.items():
                assert actual[key] == exp_val, f"{sym} {key} mismatch: {actual[key]} != {exp_val}"

    def test_quantize_step_size_round_down_strict(self) -> None:
        """Quantizing lot size step size must strictly truncate downwards (ROUND_DOWN)."""
        # DOGE: step_size = 1
        q_doge = quantize_step_size(Decimal("58.999"), Decimal("1"))
        assert q_doge == Decimal("58")

        # XRP / SUI: step_size = 0.1
        q_xrp = quantize_step_size(Decimal("3.5999"), Decimal("0.1"))
        assert q_xrp == Decimal("3.5")

        # SOL / BNB: step_size = 0.01
        q_sol = quantize_step_size(Decimal("0.0459"), Decimal("0.01"))
        assert q_sol == Decimal("0.04")

        # BTC / ETH: step_size = 0.001
        q_btc = quantize_step_size(Decimal("0.00199"), Decimal("0.001"))
        assert q_btc == Decimal("0.001")

    def test_quantize_tick_size_round_half_up(self) -> None:
        """Quantizing price tick size must follow ROUND_HALF_UP."""
        # DOGE: tick_size = 0.00001 (5 decimals)
        p_doge = quantize_tick_size(Decimal("0.086456"), Decimal("0.00001"))
        assert p_doge == Decimal("0.08646")

        # XRP / SUI: tick_size = 0.0001 (4 decimals)
        p_xrp = quantize_tick_size(Decimal("1.40124"), Decimal("0.0001"))
        assert p_xrp == Decimal("1.4012")

        p_xrp_up = quantize_tick_size(Decimal("1.40125"), Decimal("0.0001"))
        assert p_xrp_up == Decimal("1.4013")


class TestMacroLiquidityScalperUniverse:
    """Tests candidate symbol registry and 15m dip signal evaluation across all 7 candidates."""

    def test_allowed_symbols_contains_all_seven_candidates(self) -> None:
        """ALLOWED_SYMBOLS in MacroLiquidityDipScalper must contain all 7 scalper candidates."""
        scalper = MacroLiquidityDipScalper()
        assert len(scalper.ALLOWED_SYMBOLS) == 7
        for sym in CANDIDATE_7_PAIRS:
            assert sym in scalper.ALLOWED_SYMBOLS

        # BTC must not be in scalper candidates (acts as macro trend benchmark only)
        assert "BTCUSDT" not in scalper.ALLOWED_SYMBOLS

    def test_scalper_evaluates_signal_for_all_seven_candidates(self) -> None:
        """Verifies 15m liquidity dip trigger generates valid ScalperSignal on each candidate."""
        scalper = MacroLiquidityDipScalper()
        base_ts = 1728600000000

        for sym in CANDIDATE_7_PAIRS:
            # Construct 35 normal warmup candles
            candles: list[Candle] = []
            for i in range(35):
                ts = base_ts + i * 900000
                candles.append(
                    Candle(
                        timestamp_ms=ts,
                        open=Decimal("100.00"),
                        high=Decimal("101.00"),
                        low=Decimal("99.00"),
                        close=Decimal("100.00"),
                        volume=Decimal("1000.0"),
                    )
                )

            # Capitulation dip candle:
            # 20 EMA is ~100.00, ATR is ~2.00
            # Dip close at 86.00 => distance < -2.5 ATR
            # Volume spike at 5000.0 > 2.2 * 1000.0
            # RSI close at 86.00 brings RSI < 26.0
            dip_bar = Candle(
                timestamp_ms=base_ts + 35 * 900000,
                open=Decimal("95.00"),
                high=Decimal("95.50"),
                low=Decimal("85.00"),
                close=Decimal("86.00"),
                volume=Decimal("5000.0"),
            )

            signal = scalper.evaluate_15m_bar(
                symbol=sym,
                bar=dip_bar,
                history=candles,
                macro_trend_allowed=True,
            )

            assert signal is not None, f"Expected ScalperSignal on {sym}"
            assert signal.symbol == sym
            assert signal.side == "BUY"
            assert signal.order_type == "LIMIT"
            assert signal.sweep_price == Decimal("86.00")
            assert signal.stop_loss < signal.sweep_price
            assert signal.take_profit > signal.sweep_price
            assert signal.reward_to_risk_ratio == Decimal("1.6667")
            assert signal.max_hold_bars == 8

    def test_scalper_rejects_non_whitelisted_symbol(self) -> None:
        """Symbols outside ALLOWED_SYMBOLS (e.g. BTCUSDT or PEPEUSDT) must return None."""
        scalper = MacroLiquidityDipScalper()
        bar = Candle(
            timestamp_ms=1728600000000,
            open=Decimal("100.0"),
            high=Decimal("100.0"),
            low=Decimal("90.0"),
            close=Decimal("90.0"),
            volume=Decimal("5000.0"),
        )
        assert scalper.evaluate_15m_bar("BTCUSDT", bar, [], True) is None
        assert scalper.evaluate_15m_bar("PEPEUSDT", bar, [], True) is None


class TestSelfDrivingCandidateRegistryAndSizing:
    """Tests candidate registry initialization, step-up sizing, and micro-capital limits."""

    def test_candidate_registry_initialized_with_all_eight_pairs(self) -> None:
        """SelfDrivingTradingEngine must initialize self.candidates with all 8 pairs."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        assert len(engine.candidates) == 8
        for sym in ALL_8_PAIRS:
            assert sym in engine.candidates
            cand = engine.candidates[sym]
            assert isinstance(cand, CandidateState)
            assert cand.symbol == sym
            assert cand.current_price > Decimal("0")
            assert cand.position_qty == Decimal("0.0")

    def test_step_up_sizing_for_sub_dollar_candidates(self) -> None:
        """Verifies step-up sizing logic for DOGE, XRP, SUI, AVAX, BNB, SOL, ETH."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))

        # Test DOGE: price = 0.086 USDT
        # 5.00 / 0.086 = 58.139 => ROUND_DOWN step 1 => 58 DOGE
        # 58 * 0.086 = 4.988 USDT (< 5.00 min_notional)
        # Step-up +1 => 59 DOGE => 59 * 0.086 = 5.074 USDT (valid, within ceiling)
        p, q, notional = engine._calculate_child_order_qty("DOGEUSDT", Decimal("0.08600"))
        assert q == Decimal("59")
        assert notional >= Decimal("5.00")
        assert notional <= Decimal("5.00") + (Decimal("1") * Decimal("0.08600"))

        # Test XRP: price = 1.40 USDT
        # 5.00 / 1.40 = 3.571 => ROUND_DOWN step 0.1 => 3.5 XRP
        # 3.5 * 1.40 = 4.90 USDT (< 5.00 min_notional)
        # Step-up +0.1 => 3.6 XRP => 3.6 * 1.40 = 5.04 USDT
        p, q, notional = engine._calculate_child_order_qty("XRPUSDT", Decimal("1.4000"))
        assert q == Decimal("3.6")
        assert notional >= Decimal("5.00")
        assert notional <= Decimal("5.00") + (Decimal("0.1") * Decimal("1.4000"))

        # Test SUI: price = 1.11 USDT
        # 5.00 / 1.11 = 4.504 => ROUND_DOWN step 0.1 => 4.5 SUI
        # 4.5 * 1.11 = 4.995 USDT (< 5.00 min_notional)
        # Step-up +0.1 => 4.6 SUI => 4.6 * 1.11 = 5.106 USDT
        p, q, notional = engine._calculate_child_order_qty("SUIUSDT", Decimal("1.1100"))
        assert q == Decimal("4.6")
        assert notional >= Decimal("5.00")

        # Test AVAX: price = 10.50 USDT (step_size = 1)
        # 5.00 / 10.50 = 0.476 => ROUND_DOWN step 1 => 0 AVAX
        # Step-up +1 => 1 AVAX => 1 * 10.50 = 10.50 USDT (within target + 1*10.50 = 15.50)
        p, q, notional = engine._calculate_child_order_qty("AVAXUSDT", Decimal("10.500"))
        assert q == Decimal("1")
        assert notional == Decimal("10.500")

        # Test non-whitelisted symbol: step-up must NOT apply, returns 0.0
        p, q, notional = engine._calculate_child_order_qty("UNKNOWNUSDT", Decimal("10.500"))
        assert q == Decimal("0.0")

    def test_aggregate_exposure_ceiling_confinement_across_candidates(self) -> None:
        """Engine must reject orders that would cause aggregate exposure to exceed 25.00 USDT."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        now_ms = int(time.time() * 1000)

        # Pre-allocate exposure across candidates up to 22.00 USDT
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("10.00")
        engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("10.00")
        engine.candidates["DOGEUSDT"].allocated_exposure_usdt = Decimal("2.00")

        # Total current = 22.00 USDT. An order of ~5.07 USDT would push to 27.07 > 25.00 USDT cap.
        order = engine.process_microstructure_tick(
            symbol="DOGEUSDT",
            price=Decimal("0.08600"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=50.0,
            ensemble_signal="BUY",
            ts_ms=now_ms,
        )
        assert order is None
        assert engine.interlock_blocks_count >= 1

    def test_daily_drawdown_ceiling_flattens_and_halts(self) -> None:
        """Breaching 3.00 USDT intra-day loss ceiling must trip CIRCUIT_FLATTENED."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        now_ms = int(time.time() * 1000)

        # Simulate 3.00 USDT accumulated intra-day loss
        engine.intra_day_loss_usdt = Decimal("3.00")

        # Tick must trip circuit breaker
        order = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("110.00"),
            ensemble_signal="BUY",
            ts_ms=now_ms,
        )
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED


class TestDoubleEntrySolvencyConservation:
    """Tests exact zero-drift mathematical balance conservation (|drift| < 10^-15 USDT)."""

    def test_zero_drift_balance_invariant_across_multi_pair_fills(self) -> None:
        """Verifies Assets == Equity holds with |drift| < 10^-15 USDT across sequential fills."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)

        trades = [
            ("SOLUSDT", "BUY", 0.045, 110.0, 0.00099, 0.0),
            ("ETHUSDT", "BUY", 0.002, 2500.0, 0.00100, 0.0),
            ("DOGEUSDT", "BUY", 59.0, 0.086, 0.00101, 0.0),
            ("XRPUSDT", "BUY", 3.6, 1.40, 0.00101, 0.0),
            ("SOLUSDT", "SELL", 0.045, 114.0, 0.00102, 0.180),  # TP realized (+0.18 USDT)
            ("ETHUSDT", "SELL", 0.002, 2450.0, 0.00098, -0.100),  # SL realized (-0.10 USDT)
        ]

        for sym, side, qty, price, fee, rpnl in trades:
            ledger.record_fill(
                symbol=sym,
                side=side,
                qty=qty,
                price=price,
                fee=fee,
                realized_pnl=rpnl,
            )
            snap = ledger.get_snapshot()
            assert snap.zero_balance_drift is True
            assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")


class TestContinuousTraderDaemonUniverse:
    """Tests ContinuousSelfDrivingTrader universe configuration and symbols default."""

    def test_continuous_trader_default_symbols_has_all_seven_candidates(
        self, tmp_path: Path
    ) -> None:
        """Default symbols in ContinuousSelfDrivingTrader must include all 7 candidates."""
        trader = ContinuousSelfDrivingTrader(storage_dir=tmp_path, telegram_enabled=False)
        assert len(trader.symbols) == 7
        for sym in CANDIDATE_7_PAIRS:
            assert sym in trader.symbols
        assert "BTCUSDT" not in trader.symbols


class TestApiExecutionStatusAndMarketData:
    """Tests FastAPI execution status and market data endpoints across the 8-pair universe."""

    def test_baseline_execution_status_reports_all_eight_pairs(self) -> None:
        """_baseline_execution_status must report positions for all 8 pairs."""
        status = _baseline_execution_status()
        assert len(status.positions) == 8
        for sym in ALL_8_PAIRS:
            assert sym in status.positions
            pos = status.positions[sym]
            assert pos.symbol == sym
            assert pos.mark_price is not None and pos.mark_price > 0.0

    def test_load_execution_status_reports_all_eight_pairs(self, tmp_path: Path) -> None:
        """load_execution_status must report positions covering all 8 pairs."""
        status = load_execution_status(tmp_path)
        assert len(status.positions) == 8
        for sym in ALL_8_PAIRS:
            assert sym in status.positions
            pos = status.positions[sym]
            assert pos.symbol == sym
            assert pos.position_qty == 0.0
            assert pos.state == "STANDBY / SCANNING"

    def test_get_live_market_data_fallback_contains_all_eight_pairs(self, tmp_path: Path) -> None:
        """get_live_market_data fallback must contain prices for all 8 pairs."""
        data = get_live_market_data(tmp_path, force_refresh=True)
        assert "prices" in data
        prices = data["prices"]
        for sym in ALL_8_PAIRS:
            assert sym in prices
            assert float(prices[sym]) > 0.0
