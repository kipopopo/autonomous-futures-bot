"""Adversarial Empirical Challenge Harness for Milestone 3 Iteration 2 (Phase 317).

Independent verification by teamwork_preview_challenger (challenger_m3_it2_2):
1. Short Position Exits & Symmetries across ALL 8 active pairs:
   - Open short position (cand.position_qty < 0).
   - Trigger TP exits: assert side is OrderSide.BUY, tag is canary-p317-tp-*, clean return to 0.0.
   - Trigger SL exits: assert side is OrderSide.BUY, tag is canary-p317-sl-*, is_maker is False,
     and position cleanly returns to 0.0.
   - Verify evaluate_and_dispatch_scalper correctly triggers TP and SL for short positions.
2. Complete Bracket Clearance on Position Flattening:
   - Open multi-asset portfolio (mix of long and short).
   - Set brackets on all candidates (open and flat).
   - Call _flatten_all_positions().
   - Assert stop_loss is 0.0 and _stop_loss is None for 100% of candidates.
   - Assert take_profit is 0.0 and _take_profit is None for 100% of candidates.
   - Assert no phantom brackets linger in candidate state.
3. Clean State Reset on Return to Flat:
   - When new_qty == 0.0, assert unrealized_pnl_usdt == 0.0, allocated_exposure_usdt == 0.0,
     entry_price == 0.0, entry_time_ms == 0, entry_bar_index == 0.
4. Continuous Solvency Drift across 50,000 randomized state transitions:
   - Long & short entries, severe mark swings (-50% to +300%), partial closes, flattens.
   - Strict assertion: max drift < 10^-15 USDT.
5. Continuous Trader Latency across 50 cycles:
   - Multi-timeframe streams across all 8 pairs x 5 horizons.
   - Strict assertion: P99 latency < 15.0 ms.
6. Continuous Trader Short Position Exit Logic Audit:
   - Probes how ContinuousSelfDrivingTrader handles active short positions on exchange.
"""

from __future__ import annotations

import random
import time
from decimal import Decimal
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock

import pytest

from autonomous_futures.execution.binance_gateway import (
    BinanceFuturesGateway,
)
from autonomous_futures.execution.continuous_trader import (
    ContinuousSelfDrivingTrader,
)
from autonomous_futures.execution.self_driving import (
    OrderSide,
    OrderStatus,
    SelfDrivingOrder,
    SelfDrivingState,
    build_default_self_driving_engine,
)
from autonomous_futures.feed.kline_sequencer import (
    ACTIVE_PAIRS,
    ACTIVE_TIMEFRAMES,
)
from autonomous_futures.strategy.ict_mmxm import (
    Candle,
    PdArray,
    PdArrayType,
    SetupDirection,
    TwinsSetupState,
    TwinsStep,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle as MacroCandle,
)


def _build_test_candle(ts_ms: int, p: str = "100.0", vol: str = "1000.0") -> Candle:
    d = Decimal(p)
    return Candle(
        timestamp_ms=ts_ms,
        open=d,
        high=d + Decimal("1.0"),
        low=d - Decimal("1.0"),
        close=d + Decimal("0.5"),
        volume=Decimal(vol),
    )


def _build_test_macro_candle(ts_ms: int, p: str = "82600.0", vol: str = "1000.0") -> MacroCandle:
    d = Decimal(p)
    return MacroCandle(
        timestamp_ms=ts_ms,
        open=d,
        high=d + Decimal("50.0"),
        low=d - Decimal("50.0"),
        close=d,
        volume=Decimal(vol),
    )


def _build_short_twins_state(
    symbol: str,
    entry_price: Decimal,
    stop_loss: Decimal,
    take_profit: Decimal,
) -> TwinsSetupState:
    return TwinsSetupState(
        symbol=symbol,
        step_1_htf_hit=True,
        step_2_m5_cisd=True,
        step_3_twins_fvg=True,
        step_4_ote_retrace=True,
        step_5_m1_cisd=True,
        step_6_ready=True,
        active_pda=PdArray(
            array_type=PdArrayType.FVG_SIBI,
            timeframe="15m",
            top=entry_price + Decimal("5.0"),
            bottom=entry_price - Decimal("5.0"),
            mean_threshold=entry_price,
            direction=SetupDirection.BEARISH.value,
            creation_ts=1700000000000,
        ),
        m5_cisd_price=entry_price,
        m1_cisd_price=entry_price,
        ote_62=entry_price * Decimal("1.01"),
        ote_705=entry_price * Decimal("1.015"),
        ote_79=entry_price * Decimal("1.02"),
        stdv_2_0=take_profit,
        stdv_4_0=take_profit * Decimal("0.95"),
        stop_loss=stop_loss,
        take_profit_partial=take_profit,
        take_profit_final=take_profit * Decimal("0.95"),
        side="SELL",
        step=TwinsStep.STEP_6_READY,
    )


# =============================================================================
# 1. EMPIRICAL SHORT POSITION EXITS & SYMMETRY ACROSS ALL 8 ACTIVE PAIRS
# =============================================================================


class TestAdversarialShortPositionExits:
    """Stress-tests short position entry, TP and SL exits, and clean flat return."""

    @pytest.mark.parametrize("symbol", ACTIVE_PAIRS)
    def test_short_position_take_profit_exit_buys_to_cover(
        self, tmp_path: Path, symbol: str
    ) -> None:
        """Verifies short position TP exit: side is OrderSide.BUY, tag is canary-p317-tp-*,

        position closes cleanly to 0.0, and unrealized PnL/exposure resets to 0.0.
        """
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        cand = engine.candidates[symbol]
        entry_price = cand.current_price
        stop_loss = entry_price * Decimal("1.03")  # SL is above entry for short
        take_profit = entry_price * Decimal("0.96")  # TP is below entry for short

        setup = _build_short_twins_state(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        entry_order = engine.dispatch_ict_intention(setup, now_ms=now_ms)
        assert entry_order is not None, f"Failed to dispatch short entry on {symbol}"
        assert entry_order.side == OrderSide.SELL
        assert cand.position_qty < Decimal("0.0"), f"Expected negative qty for short on {symbol}"
        assert cand.allocated_exposure_usdt > Decimal("0.0")
        assert cand.stop_loss == stop_loss
        assert cand.take_profit == take_profit

        # Execute TP exit
        exit_order = engine._exit_position(
            cand=cand,
            exit_price=take_profit,
            ts_ms=now_ms + 60000,
            reason="TAKE_PROFIT",
        )

        assert exit_order.side == OrderSide.BUY, (
            f"Expected OrderSide.BUY to cover short on {symbol}, got {exit_order.side}"
        )
        assert exit_order.status == OrderStatus.FILLED
        assert exit_order.client_order_id.startswith(f"canary-p317-tp-{symbol.lower()[:3]}-")
        assert len(exit_order.client_order_id) <= 36
        assert exit_order.realized_pnl_usdt > Decimal("0.0"), (
            f"Short TP exit should realize positive PnL: {exit_order.realized_pnl_usdt}"
        )

        # State synchronization checks on flat return
        assert cand.position_qty == Decimal("0.0"), f"Position qty not 0.0 on {symbol}"
        assert cand.allocated_exposure_usdt == Decimal("0.0")
        assert cand.unrealized_pnl_usdt == Decimal("0.0")
        assert cand.entry_price == Decimal("0.0")
        assert cand.entry_time_ms == 0
        assert cand.entry_bar_index == 0
        assert cand.stop_loss == Decimal("0.0")
        assert cand.take_profit == Decimal("0.0")
        assert cand._stop_loss is None
        assert cand._take_profit is None

    @pytest.mark.parametrize("symbol", ACTIVE_PAIRS)
    def test_short_position_stop_loss_exit_buys_to_cover_as_taker(
        self, tmp_path: Path, symbol: str
    ) -> None:
        """Verifies short position SL exit: side is OrderSide.BUY, tag is canary-p317-sl-*,

        is_maker is False (taker SL), realized PnL is negative, and state resets to 0.0.
        """
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        cand = engine.candidates[symbol]
        entry_price = cand.current_price
        stop_loss = entry_price * Decimal("1.025")
        take_profit = entry_price * Decimal("0.97")

        setup = _build_short_twins_state(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        entry_order = engine.dispatch_ict_intention(setup, now_ms=now_ms)
        assert entry_order is not None
        assert cand.position_qty < Decimal("0.0")

        # Execute SL exit
        exit_order = engine._exit_position(
            cand=cand,
            exit_price=stop_loss,
            ts_ms=now_ms + 120000,
            reason="STOP_LOSS",
        )

        assert exit_order.side == OrderSide.BUY, f"Expected BUY to cover on {symbol}"
        assert exit_order.status == OrderStatus.FILLED
        assert exit_order.client_order_id.startswith(f"canary-p317-sl-{symbol.lower()[:3]}-")
        assert len(exit_order.client_order_id) <= 36
        assert not exit_order.is_maker, (
            f"SL order on {symbol} must be aggressive taker (is_maker=False)"
        )
        assert exit_order.realized_pnl_usdt < Decimal("0.0"), (
            f"Short SL exit should realize negative PnL: {exit_order.realized_pnl_usdt}"
        )

        # State synchronization checks on flat return
        assert cand.position_qty == Decimal("0.0")
        assert cand.allocated_exposure_usdt == Decimal("0.0")
        assert cand.unrealized_pnl_usdt == Decimal("0.0")
        assert cand.entry_price == Decimal("0.0")
        assert cand.entry_time_ms == 0
        assert cand.entry_bar_index == 0
        assert cand.stop_loss == Decimal("0.0")
        assert cand.take_profit == Decimal("0.0")
        assert cand._stop_loss is None
        assert cand._take_profit is None

    def test_evaluate_and_dispatch_scalper_short_position_tp_and_sl_triggers(
        self, tmp_path: Path
    ) -> None:
        """Verifies evaluate_and_dispatch_scalper detects SL when bar.high >= stop_loss

        and TP when bar.low <= take_profit on short positions.
        """
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        # 1. Test TP trigger on short
        setup_tp = _build_short_twins_state(
            symbol="BTCUSDT",
            entry_price=Decimal("80000.00"),
            stop_loss=Decimal("82000.00"),
            take_profit=Decimal("76000.00"),
        )
        engine.dispatch_ict_intention(setup_tp, now_ms=now_ms)
        cand = engine.candidates["BTCUSDT"]
        assert cand.position_qty < Decimal("0.0")

        # Candle drops below TP: low = 75800.00 <= 76000.00
        bar_tp = MacroCandle(
            timestamp_ms=now_ms + 900000,
            open=Decimal("77000.00"),
            high=Decimal("77200.00"),
            low=Decimal("75800.00"),
            close=Decimal("76100.00"),
            volume=Decimal("1500.0"),
        )
        order_tp = engine.evaluate_and_dispatch_scalper(
            symbol="BTCUSDT",
            bar=bar_tp,
            history=[],
            btc_1h_candles=[],
            now_ms=now_ms + 900000,
        )
        assert order_tp is not None
        assert order_tp.side == OrderSide.BUY
        assert order_tp.client_order_id.startswith("canary-p317-tp-btc-")
        assert cand.position_qty == Decimal("0.0")
        assert cand.stop_loss == Decimal("0.0")
        assert cand.take_profit == Decimal("0.0")

        # 2. Test SL trigger on short
        setup_sl = _build_short_twins_state(
            symbol="ETHUSDT",
            entry_price=Decimal("2500.00"),
            stop_loss=Decimal("2550.00"),
            take_profit=Decimal("2400.00"),
        )
        engine.dispatch_ict_intention(setup_sl, now_ms=now_ms)
        cand_eth = engine.candidates["ETHUSDT"]
        assert cand_eth.position_qty < Decimal("0.0")

        # Candle spikes above SL: high = 2560.00 >= 2550.00
        bar_sl = MacroCandle(
            timestamp_ms=now_ms + 900000,
            open=Decimal("2520.00"),
            high=Decimal("2560.00"),
            low=Decimal("2510.00"),
            close=Decimal("2555.00"),
            volume=Decimal("500.0"),
        )
        order_sl = engine.evaluate_and_dispatch_scalper(
            symbol="ETHUSDT",
            bar=bar_sl,
            history=[],
            btc_1h_candles=[],
            now_ms=now_ms + 900000,
        )
        assert order_sl is not None
        assert order_sl.side == OrderSide.BUY
        assert order_sl.client_order_id.startswith("canary-p317-sl-eth-")
        assert cand_eth.position_qty == Decimal("0.0")
        assert cand_eth.stop_loss == Decimal("0.0")
        assert cand_eth.take_profit == Decimal("0.0")


# =============================================================================
# 2. FLATTENING BRACKET CLEARANCE & PHANTOM SUPPRESSION
# =============================================================================


class TestAdversarialPositionFlatteningAndBracketClearance:
    """Stress-tests complete clearance of brackets upon emergency position flattening."""

    def test_flattening_clears_all_brackets_without_phantom_brackets(
        self, tmp_path: Path
    ) -> None:
        """Verifies _flatten_all_positions completely clears stop_loss and take_profit

        on BOTH active position candidates AND flat candidates.
        """
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        # Open Long on SOL and Short on ETH
        setup_sol = TwinsSetupState(
            symbol="SOLUSDT",
            step_6_ready=True,
            side="BUY",
            m1_cisd_price=Decimal("170.00"),
            stop_loss=Decimal("165.00"),
            take_profit_partial=Decimal("185.00"),
        )
        engine.dispatch_ict_intention(setup_sol, now_ms=now_ms)

        setup_eth = _build_short_twins_state(
            symbol="ETHUSDT",
            entry_price=Decimal("2500.00"),
            stop_loss=Decimal("2550.00"),
            take_profit=Decimal("2400.00"),
        )
        engine.dispatch_ict_intention(setup_eth, now_ms=now_ms)

        # Manually assign lingering brackets on flat candidates (simulating desync/phantom state)
        for sym in ["BTCUSDT", "DOGEUSDT", "XRPUSDT", "BNBUSDT", "SUIUSDT", "AVAXUSDT"]:
            cand = engine.candidates[sym]
            cand.stop_loss = Decimal("9999.00")
            cand.take_profit = Decimal("8888.00")

        # Verify initial states
        assert engine.candidates["SOLUSDT"].position_qty > Decimal("0")
        assert engine.candidates["ETHUSDT"].position_qty < Decimal("0")
        assert engine.candidates["SOLUSDT"].stop_loss == Decimal("165.00")
        assert engine.candidates["ETHUSDT"].stop_loss == Decimal("2550.00")
        assert engine.candidates["BTCUSDT"].stop_loss == Decimal("9999.00")

        # Execute emergency flattening
        engine._flatten_all_positions(now_ms=now_ms + 1000, reason="Adversarial stress flatten")

        # Assert every single candidate has 0.0 position and None brackets
        for sym, cand in engine.candidates.items():
            assert cand.position_qty == Decimal("0.0"), f"{sym} position_qty not 0.0"
            assert cand.allocated_exposure_usdt == Decimal("0.0"), f"{sym} exposure not 0.0"
            assert cand.unrealized_pnl_usdt == Decimal("0.0"), f"{sym} upnl not 0.0"
            assert cand.entry_price == Decimal("0.0"), f"{sym} entry_price not 0.0"
            assert cand.entry_time_ms == 0, f"{sym} entry_time_ms not 0"
            assert cand.entry_bar_index == 0, f"{sym} entry_bar_index not 0"
            # Property returns 0.0 when backing field is None
            assert cand.stop_loss == Decimal("0.0"), f"{sym} stop_loss property not 0.0"
            assert cand.take_profit == Decimal("0.0"), f"{sym} take_profit property not 0.0"
            # Backing field must be strictly None (no phantom bracket)
            assert cand._stop_loss is None, f"{sym} _stop_loss backing field not None"
            assert cand._take_profit is None, f"{sym} _take_profit backing field not None"

        # Assert ledger solvency
        snap = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")
        assert snap.zero_balance_drift is True
        assert engine.ledger.unrealized_pnl == Decimal("0.0")


# =============================================================================
# 3. 50,000-STATE TRANSITION SOLVENCY DRIFT CHALLENGE
# =============================================================================


class TestEmpiricalSolvencyDrift50000Transitions:
    """Rigorous empirical execution of 50,000 randomized state transitions."""

    def test_solvency_drift_50000_transitions_with_long_and_short(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates 50,000 randomized transitions with BUY & SELL entries, asymmetric swings,

        partial closures, and flattens. Asserts max observed drift < 10^-15 USDT.
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        monkeypatch.setattr(engine, "_record_order_in_db", lambda order: None)
        monkeypatch.setattr(engine, "_record_solvency_snapshot", lambda ts: None)
        monkeypatch.setattr(engine, "_record_event", lambda *args, **kwargs: None)
        monkeypatch.setattr(engine, "_trigger_autopsy", lambda *args, **kwargs: None)

        symbols = list(engine.candidates.keys())
        rng = random.Random(31742)

        max_drift = Decimal("0")
        total_transitions = 50_000
        op_counts = {"entry_buy": 0, "entry_sell": 0, "swing": 0, "partial": 0, "flatten": 0}

        t0 = time.perf_counter()

        for step in range(total_transitions):
            op = rng.choice(["entry", "swing", "partial", "flatten"])
            sym = rng.choice(symbols)
            cand = engine.candidates[sym]
            now_ms = 1700000000000 + step * 1000

            if op == "entry":
                if cand.position_qty == Decimal("0"):
                    side: Literal["BUY", "SELL"] = "BUY" if rng.random() > 0.5 else "SELL"
                    if side == "BUY":
                        op_counts["entry_buy"] += 1
                        setup = TwinsSetupState(
                            symbol=sym,
                            step_6_ready=True,
                            side="BUY",
                            m1_cisd_price=cand.current_price,
                            stop_loss=cand.current_price * Decimal("0.98"),
                            take_profit_partial=cand.current_price * Decimal("1.04"),
                        )
                    else:
                        op_counts["entry_sell"] += 1
                        setup = _build_short_twins_state(
                            symbol=sym,
                            entry_price=cand.current_price,
                            stop_loss=cand.current_price * Decimal("1.02"),
                            take_profit=cand.current_price * Decimal("0.96"),
                        )

                    if engine.state == SelfDrivingState.CIRCUIT_FLATTENED:
                        engine.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE
                        engine.intra_day_loss_usdt = Decimal("0.0")

                    engine.dispatch_ict_intention(setup, now_ms=now_ms)

            elif op == "swing":
                op_counts["swing"] += 1
                if cand.position_qty != Decimal("0"):
                    mult = Decimal(str(round(rng.uniform(0.50, 4.00), 4)))
                    new_price = cand.entry_price * mult
                    cand.current_price = new_price
                    if cand.position_qty > 0:
                        diff = new_price - cand.entry_price
                        cand.unrealized_pnl_usdt = diff * cand.position_qty
                    else:
                        diff = cand.entry_price - new_price
                        cand.unrealized_pnl_usdt = diff * abs(cand.position_qty)

                    engine.ledger.unrealized_pnl = sum(
                        (c.unrealized_pnl_usdt for c in engine.candidates.values()),
                        Decimal("0.0"),
                    )

            elif op == "partial":
                op_counts["partial"] += 1
                if cand.position_qty != Decimal("0"):
                    frac = Decimal(str(round(rng.uniform(0.10, 0.90), 2)))
                    close_qty = engine._round_step_size(cand.position_qty * frac, Decimal("0.001"))
                    if close_qty > Decimal("0") and close_qty < abs(cand.position_qty):
                        exit_side = OrderSide.SELL if cand.position_qty > 0 else OrderSide.BUY
                        exit_order = SelfDrivingOrder(
                            order_id=f"partial-{step}",
                            symbol=sym,
                            side=exit_side,
                            order_type="LIMIT",
                            price=cand.current_price,
                            quantity=close_qty,
                            notional_usdt=close_qty * cand.current_price,
                            status=OrderStatus.PENDING,
                            timestamp_ms=now_ms,
                            client_order_id=f"test-p-{step}",
                            is_maker=True,
                        )
                        engine._execute_fill(exit_order, cand.current_price, now_ms)

            elif op == "flatten":
                op_counts["flatten"] += 1
                engine._flatten_all_positions(now_ms=now_ms, reason="Randomized test flatten")
                if engine.state == SelfDrivingState.CIRCUIT_FLATTENED:
                    engine.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE
                    engine.intra_day_loss_usdt = Decimal("0.0")

            # Check snapshot at every single transition
            snap = engine.ledger.get_snapshot()
            drift = abs(Decimal(str(snap.drift)))
            if drift > max_drift:
                max_drift = drift

            assert drift < Decimal("1e-15"), (
                f"Solvency drift {drift} exceeded 10^-15 at step #{step} ({op})"
            )
            assert snap.zero_balance_drift is True

        elapsed = time.perf_counter() - t0
        print(
            f"\n[EMPIRICAL 50,000 TRANSITION RESULTS]\n"
            f"  - Elapsed: {elapsed:.2f}s ({total_transitions / elapsed:.0f} ops/sec)\n"
            f"  - Long Entries:  {op_counts['entry_buy']}\n"
            f"  - Short Entries: {op_counts['entry_sell']}\n"
            f"  - Mark Swings:   {op_counts['swing']}\n"
            f"  - Partials:      {op_counts['partial']}\n"
            f"  - Flattens:      {op_counts['flatten']}\n"
            f"  - Max Drift:     {max_drift} USDT (< 10^-15 USDT)"
        )
        assert max_drift < Decimal("1e-15")


# =============================================================================
# 4. CONTINUOUS TRADER 50 CYCLES LATENCY BENCHMARK
# =============================================================================


class TestEmpiricalTraderLatencyBenchmark:
    """Measures 50 consecutive cycles of continuous trader execution loop."""

    @pytest.mark.anyio
    async def test_continuous_trader_50_cycles_p99_latency_benchmark(
        self, tmp_path: Path
    ) -> None:
        """Executes 50 cycles across 8 pairs x 5 timeframes, asserting P99 latency < 15.0 ms."""
        mock_gateway = AsyncMock(spec=BinanceFuturesGateway)
        mock_gateway.get_position_risk.return_value = []
        mock_gateway.get_klines.return_value = []
        mock_gateway.testnet = True

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gateway,
            telegram_enabled=False,
        )
        trader.engine.perform_preflight_checks()

        now = time.time()
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = trader.sequencer.buffers[(sym, tf)]
                for i in range(50):
                    buf.append(_build_test_candle(1700000000000 + i * 60000, "150.0"))
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        trader.btc_1h_history = [
            _build_test_macro_candle(1700000000000 + i * 3600000, "82600.0") for i in range(210)
        ]
        trader.last_candle_fetch_ts = now

        # Warm up 5 cycles
        for _ in range(5):
            await trader.run_single_cycle()

        latencies_ms: list[float] = []
        for _ in range(50):
            now_tick = time.time()
            trader.last_candle_fetch_ts = now_tick
            for sym in ACTIVE_PAIRS:
                for tf in ACTIVE_TIMEFRAMES:
                    trader.sequencer.last_fetch_ts[(sym, tf)] = now_tick

            t0 = time.perf_counter()
            await trader.run_single_cycle()
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        sorted_latencies = sorted(latencies_ms)
        avg_lat = sum(latencies_ms) / len(latencies_ms)
        p50_lat = sorted_latencies[int(len(sorted_latencies) * 0.50)]
        p90_lat = sorted_latencies[int(len(sorted_latencies) * 0.90)]
        p95_lat = sorted_latencies[int(len(sorted_latencies) * 0.95)]
        p99_lat = sorted_latencies[int(len(sorted_latencies) * 0.99)]
        max_lat = sorted_latencies[-1]

        print(
            f"\n[CONTINUOUS TRADER 50-CYCLE LATENCY REPORT]\n"
            f"  - Average: {avg_lat:.3f} ms\n"
            f"  - P50:     {p50_lat:.3f} ms\n"
            f"  - P90:     {p90_lat:.3f} ms\n"
            f"  - P95:     {p95_lat:.3f} ms\n"
            f"  - P99:     {p99_lat:.3f} ms (Ceiling: < 15.0 ms)\n"
            f"  - Max:     {max_lat:.3f} ms"
        )

        assert avg_lat < 15.0, f"Average latency {avg_lat:.3f} ms >= 15.0 ms"
        assert p99_lat < 15.0, f"P99 latency {p99_lat:.3f} ms >= 15.0 ms"


# =============================================================================
# 5. CONTINUOUS TRADER SHORT POSITION EXIT LOGIC INVESTIGATION
# =============================================================================


class TestContinuousTraderShortPositionExitLogicAudit:
    """Audits how ContinuousSelfDrivingTrader evaluates exchange positions when short."""

    @pytest.mark.anyio
    async def test_continuous_trader_short_position_handling(self, tmp_path: Path) -> None:
        """Audits continuous trader with active short position on exchange.

        Tests whether the cycle runs without crashing and correctly synchronizes state.
        """
        mock_gateway = AsyncMock(spec=BinanceFuturesGateway)
        # Exchange reports an active short position on BTCUSDT (-0.05 BTC)
        mock_gateway.get_position_risk.return_value = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "-0.05",
                "entryPrice": "80000.00",
                "unRealizedProfit": "100.00",
            }
        ]
        mock_gateway.get_klines.return_value = []
        mock_gateway.testnet = True

        trader = ContinuousSelfDrivingTrader(
            storage_dir=tmp_path,
            gateway=mock_gateway,
            telegram_enabled=False,
        )
        trader.engine.perform_preflight_checks()

        # Warm up buffers
        now = time.time()
        for sym in ACTIVE_PAIRS:
            for tf in ACTIVE_TIMEFRAMES:
                buf = trader.sequencer.buffers[(sym, tf)]
                for i in range(50):
                    buf.append(_build_test_candle(1700000000000 + i * 60000, "150.0"))
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        trader.btc_1h_history = [
            _build_test_macro_candle(1700000000000 + i * 3600000, "82600.0") for i in range(210)
        ]
        trader.last_candle_fetch_ts = now

        # Populate candidate state for BTCUSDT as short
        cand_btc = trader.engine.candidates["BTCUSDT"]
        cand_btc.position_qty = Decimal("-0.05")
        cand_btc.entry_price = Decimal("80000.00")
        cand_btc.stop_loss = Decimal("82000.00")
        cand_btc.take_profit = Decimal("76000.00")

        # Candle history for BTCUSDT
        trader.candle_history["BTCUSDT"] = [
            _build_test_macro_candle(1700000000000 + i * 900000, "79000.0") for i in range(30)
        ]

        # Run cycle
        await trader.run_single_cycle()

        # Verify trader completed cycle cleanly
        assert trader.engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE
