"""Autonomous Futures Bot - Phase 317 Milestone 3 Empirical Adversarial Challenge Suite.

Adversarially probes:
1. Double-entry balance conservation & solvency drift invariant:
   - 50,000 randomized state transitions (order entries, large mark swings -50% to +300%,
     partial closes, emergency flattening).
   - Multi-asset concurrent mark swings across all 8 pairs.
   - Extreme starting capital bounds ($0.01 to $1,000,000.00 USDT).
   - Strict assertion: balance drift |Delta| < 10^-15 USDT in 100% of cases.
2. Continuous trader latency under full multi-timeframe market load:
   - 50 consecutive cycles of run_single_cycle() with full multi-timeframe candle streams
     across all 8 active pairs and 5 horizons (4h, 1h, 15m, 5m, 1m).
   - Strict assertion: Average latency < 15.0 ms AND P99 latency < 15.0 ms.
3. Micro-capital boundary stress & fail-closed risk interlocks:
   - Child order cap <= 5.00 USDT under extreme price dynamics (0.001 to 100,000 USDT).
   - Aggregate portfolio exposure ceiling <= 25.00 USDT.
   - Liquid cash reserve floor >= 75.0%.
   - Daily loss limit <= 3.00 USDT fail-closed circuit breaker.
4. Client order ID tagging & burst collision resistance (length <= 36 chars, 0 collisions).
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock

import pytest

from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    BinanceFuturesGateway,
    generate_p317_ict_client_order_id,
)
from autonomous_futures.execution.continuous_trader import (
    ContinuousSelfDrivingTrader,
)
from autonomous_futures.execution.self_driving import (
    OrderSide,
    OrderStatus,
    Phase317SolvencyLedger,
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
    TwinsSetupState,
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


# =============================================================================
# Challenge 1: Solvency Drift Invariant (50,000 State Transitions)
# =============================================================================


class TestEmpiricalSolvencyDriftInvariant:
    """Empirically stress-tests double-entry balance conservation across 50,000 transitions."""

    def test_solvency_drift_50000_randomized_state_transitions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates 50,000 randomized state transitions:

        - Order entries (BUY/SELL maker orders)
        - Mark-to-market swings (-50% to +300%)
        - Partial position closes (10% to 90% liquidation)
        - Emergency position flattening
        Asserts |Delta| < 10^-15 USDT in 100% of cases.
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        # Suppress synchronous SQLite disk operations during fast stress simulation
        monkeypatch.setattr(engine, "_record_order_in_db", lambda order: None)
        monkeypatch.setattr(engine, "_record_solvency_snapshot", lambda ts: None)
        monkeypatch.setattr(engine, "_record_event", lambda *args, **kwargs: None)
        monkeypatch.setattr(engine, "_trigger_autopsy", lambda *args, **kwargs: None)

        symbols = list(engine.candidates.keys())
        rng = random.Random(31742)

        max_drift_observed = Decimal("0")
        total_transitions = 50_000
        op_counts: dict[str, int] = {
            "entry": 0,
            "mark_swing": 0,
            "partial_close": 0,
            "flatten": 0,
        }

        t0 = time.perf_counter()

        for step in range(total_transitions):
            op = rng.choice(["entry", "mark_swing", "partial_close", "flatten"])
            sym = rng.choice(symbols)
            cand = engine.candidates[sym]
            now_ms = 1700000000000 + step * 1000

            if op == "entry":
                op_counts["entry"] += 1
                if cand.position_qty == Decimal("0"):
                    entry_p = cand.current_price
                    side: Literal["BUY", "SELL"] = "BUY" if rng.random() > 0.5 else "SELL"
                    sl = entry_p * Decimal("0.98") if side == "BUY" else entry_p * Decimal("1.02")
                    tp = entry_p * Decimal("1.03") if side == "BUY" else entry_p * Decimal("0.97")
                    setup = TwinsSetupState(
                        symbol=sym,
                        step_6_ready=True,
                        side=side,
                        m1_cisd_price=entry_p,
                        stop_loss=sl,
                        take_profit_partial=tp,
                    )
                    # Reset circuit breaker if needed to test state machine transitions
                    if engine.state == SelfDrivingState.CIRCUIT_FLATTENED:
                        engine.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE
                        engine.intra_day_loss_usdt = Decimal("0.0")

                    engine.dispatch_ict_intention(setup, now_ms=now_ms)

            elif op == "mark_swing":
                op_counts["mark_swing"] += 1
                if cand.position_qty != Decimal("0"):
                    # Large mark swings from -50% to +300% (multiplier 0.50 to 4.00)
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

            elif op == "partial_close":
                op_counts["partial_close"] += 1
                if cand.position_qty != Decimal("0"):
                    # Partial close: liquidating 10% to 90% of open position
                    frac = Decimal(str(round(rng.uniform(0.10, 0.90), 2)))
                    close_qty = engine._round_step_size(cand.position_qty * frac, Decimal("0.001"))
                    if close_qty > Decimal("0") and close_qty < abs(cand.position_qty):
                        exit_side = OrderSide.SELL if cand.position_qty > 0 else OrderSide.BUY
                        exit_order = SelfDrivingOrder(
                            order_id=f"test-partial-{step}",
                            symbol=sym,
                            side=exit_side,
                            order_type="LIMIT",
                            price=cand.current_price,
                            quantity=close_qty,
                            notional_usdt=close_qty * cand.current_price,
                            status=OrderStatus.PENDING,
                            timestamp_ms=now_ms,
                            client_order_id=f"test-cid-{step}",
                            is_maker=True,
                        )
                        engine._execute_fill(exit_order, cand.current_price, now_ms)

            elif op == "flatten":
                op_counts["flatten"] += 1
                engine._flatten_all_positions(now_ms=now_ms, reason="Randomized test flatten")
                if engine.state == SelfDrivingState.CIRCUIT_FLATTENED:
                    engine.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE
                    engine.intra_day_loss_usdt = Decimal("0.0")

            # Check snapshot at EVERY state transition
            snapshot = engine.ledger.get_snapshot()
            drift_dec = abs(Decimal(str(snapshot.drift)))
            if drift_dec > max_drift_observed:
                max_drift_observed = drift_dec

            assert drift_dec < Decimal("1e-15"), (
                f"Solvency balance drift failure at transition #{step} ({op}): "
                f"drift = {drift_dec} USDT >= 1e-15 USDT limit (Cash={snapshot.cash}, "
                f"AllocatedMargin={snapshot.allocated_margin}, UPnL={snapshot.unrealized_pnl}, "
                f"RPnL={snapshot.realized_pnl}, TotalEquity={snapshot.total_equity})"
            )
            assert snapshot.zero_balance_drift is True

        elapsed_sec = time.perf_counter() - t0
        print(
            f"\n[EMPIRICAL PROOF] 50,000 transitions verified in {elapsed_sec:.2f}s "
            f"({total_transitions / elapsed_sec:.0f} ops/sec): "
            f"Entries={op_counts['entry']}, Swings={op_counts['mark_swing']}, "
            f"Partials={op_counts['partial_close']}, Flattens={op_counts['flatten']}. "
            f"Max observed drift: {max_drift_observed} USDT (< 1e-15)."
        )
        assert max_drift_observed < Decimal("1e-15")

    def test_solvency_drift_under_extreme_starting_equities(self, tmp_path: Path) -> None:
        """Verifies zero drift holds across extreme capital scales (0.01 to 1,000,000 USDT)."""
        scales = [
            Decimal("0.01"),
            Decimal("1.00"),
            Decimal("10.00"),
            Decimal("100.00"),
            Decimal("10000.00"),
            Decimal("1000000.00"),
        ]
        for capital in scales:
            ledger = Phase317SolvencyLedger(starting_equity=float(capital))
            # Entry fill with fee
            ledger.record_fill("SOLUSDT", "BUY", 0.05, 150.0, fee=0.003, realized_pnl=0.0)
            # +300% swing
            ledger.unrealized_pnl = Decimal("15.00")
            snap1 = ledger.get_snapshot()
            assert abs(Decimal(str(snap1.drift))) < Decimal("1e-15")

            # -50% swing
            ledger.unrealized_pnl = Decimal("-2.50")
            snap2 = ledger.get_snapshot()
            assert abs(Decimal(str(snap2.drift))) < Decimal("1e-15")

            # Flatten
            ledger.flatten_position("SOLUSDT", 7.50, fee=0.002)
            snap3 = ledger.get_snapshot()
            assert abs(Decimal(str(snap3.drift))) < Decimal("1e-15")

    def test_multi_asset_concurrent_asymmetric_mark_swings(self, tmp_path: Path) -> None:
        """Verifies multi-asset portfolio under concurrent opposing mark swings (-50% and +300%)."""
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()
        now_ms = 1700000000000

        # Open positions on SOLUSDT, ETHUSDT, DOGEUSDT, XRPUSDT
        for sym, price in [
            ("SOLUSDT", Decimal("170.00")),
            ("ETHUSDT", Decimal("2500.00")),
            ("DOGEUSDT", Decimal("0.086")),
            ("XRPUSDT", Decimal("1.40")),
        ]:
            setup = TwinsSetupState(
                symbol=sym,
                step_6_ready=True,
                side="BUY",
                m1_cisd_price=price,
                stop_loss=price * Decimal("0.98"),
                take_profit_partial=price * Decimal("1.04"),
            )
            order = engine.dispatch_ict_intention(setup, now_ms=now_ms)
            assert order is not None

        # Apply asymmetric swings: SOL +300%, ETH -50%, DOGE +150%, XRP -30%
        engine.candidates["SOLUSDT"].current_price = Decimal("170.00") * Decimal("4.00")
        engine.candidates["SOLUSDT"].unrealized_pnl_usdt = (
            engine.candidates["SOLUSDT"].current_price - Decimal("170.00")
        ) * engine.candidates["SOLUSDT"].position_qty

        engine.candidates["ETHUSDT"].current_price = Decimal("2500.00") * Decimal("0.50")
        engine.candidates["ETHUSDT"].unrealized_pnl_usdt = (
            engine.candidates["ETHUSDT"].current_price - Decimal("2500.00")
        ) * engine.candidates["ETHUSDT"].position_qty

        engine.candidates["DOGEUSDT"].current_price = Decimal("0.086") * Decimal("2.50")
        engine.candidates["DOGEUSDT"].unrealized_pnl_usdt = (
            engine.candidates["DOGEUSDT"].current_price - Decimal("0.086")
        ) * engine.candidates["DOGEUSDT"].position_qty

        engine.candidates["XRPUSDT"].current_price = Decimal("1.40") * Decimal("0.70")
        engine.candidates["XRPUSDT"].unrealized_pnl_usdt = (
            engine.candidates["XRPUSDT"].current_price - Decimal("1.40")
        ) * engine.candidates["XRPUSDT"].position_qty

        engine.ledger.unrealized_pnl = sum(
            (c.unrealized_pnl_usdt for c in engine.candidates.values()), Decimal("0.0")
        )

        snap = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")

        # Emergency flatten
        engine._flatten_all_positions(now_ms=now_ms + 1000, reason="Asymmetric stress flatten")
        snap_flat = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap_flat.drift))) < Decimal("1e-15")


# =============================================================================
# Challenge 2: Continuous Trader Latency (50 Cycles Across 8 Pairs x 5 Horizons)
# =============================================================================


class TestEmpiricalContinuousTraderLatency50Cycles:
    """Empirically measures 50 cycles of run_single_cycle() across 8 pairs and 5 horizons."""

    @pytest.mark.anyio
    async def test_continuous_trader_50_cycles_latency_distribution(self, tmp_path: Path) -> None:
        """Measures 50 consecutive cycles of run_single_cycle() with full multi-timeframe feeds:

        - 8 active pairs: BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX.
        - 5 horizons: 4h, 1h, 15m, 5m, 1m.
        - Verifies that Average Latency < 15.0 ms AND P99 Latency < 15.0 ms.
        """
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

        # Warm up multi-timeframe buffers across all 8 pairs and 5 horizons
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
        num_cycles = 50

        for _ in range(num_cycles):
            now_tick = time.time()
            trader.last_candle_fetch_ts = now_tick
            for sym in ACTIVE_PAIRS:
                for tf in ACTIVE_TIMEFRAMES:
                    trader.sequencer.last_fetch_ts[(sym, tf)] = now_tick

            t_start = time.perf_counter()
            await trader.run_single_cycle()
            cycle_duration_ms = (time.perf_counter() - t_start) * 1000.0
            latencies_ms.append(cycle_duration_ms)

        sorted_latencies = sorted(latencies_ms)
        avg_latency = sum(latencies_ms) / len(latencies_ms)
        p50_latency = sorted_latencies[int(len(sorted_latencies) * 0.50)]
        p90_latency = sorted_latencies[int(len(sorted_latencies) * 0.90)]
        p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)]
        p99_latency = sorted_latencies[int(len(sorted_latencies) * 0.99)]
        max_latency = sorted_latencies[-1]

        print(
            f"\n[EMPIRICAL LATENCY REPORT] {num_cycles} Cycles across 8 pairs x 5 timeframes:\n"
            f"  - Average Latency: {avg_latency:.3f} ms (ceiling: < 15.0 ms)\n"
            f"  - P50 Latency:     {p50_latency:.3f} ms\n"
            f"  - P90 Latency:     {p90_latency:.3f} ms\n"
            f"  - P95 Latency:     {p95_latency:.3f} ms\n"
            f"  - P99 Latency:     {p99_latency:.3f} ms (ceiling: < 15.0 ms)\n"
            f"  - Max Latency:     {max_latency:.3f} ms"
        )

        assert avg_latency < 15.0, (
            f"Average continuous cycle latency {avg_latency:.3f} ms exceeded 15.0 ms ceiling!"
        )
        assert p99_latency < 15.0, (
            f"P99 continuous cycle latency {p99_latency:.3f} ms exceeded 15.0 ms ceiling!"
        )

    @pytest.mark.anyio
    async def test_continuous_trader_latency_with_deep_candle_buffers(self, tmp_path: Path) -> None:
        """Verifies cycle latency remains < 15ms even when ring buffers are at capacity."""
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
                for i in range(120):
                    buf.append(_build_test_candle(1700000000000 + i * 60000, "150.0"))
                trader.sequencer.last_fetch_ts[(sym, tf)] = now

        trader.btc_1h_history = [
            _build_test_macro_candle(1700000000000 + i * 3600000, "82600.0") for i in range(250)
        ]
        trader.last_candle_fetch_ts = now

        for _ in range(3):
            await trader.run_single_cycle()

        t_start = time.perf_counter()
        await trader.run_single_cycle()
        lat_ms = (time.perf_counter() - t_start) * 1000.0

        assert lat_ms < 15.0, f"Deep buffer cycle latency {lat_ms:.3f} ms exceeded 15.0 ms!"


# =============================================================================
# Challenge 3: Adversarial Micro-Capital Governance & Fail-Closed Boundaries
# =============================================================================


class TestAdversarialMicroCapitalGovernance:
    """Stress-tests micro-capital boundaries and fail-closed interlocks."""

    @pytest.mark.parametrize(
        "symbol,extreme_price",
        [
            ("BTCUSDT", "150000.00"),
            ("BTCUSDT", "12000.00"),
            ("ETHUSDT", "5000.00"),
            ("ETHUSDT", "500.00"),
            ("SOLUSDT", "600.00"),
            ("SOLUSDT", "15.00"),
            ("DOGEUSDT", "0.00500"),
            ("DOGEUSDT", "0.75000"),
            ("XRPUSDT", "5.0000"),
            ("XRPUSDT", "0.2000"),
            ("SUIUSDT", "10.0000"),
            ("SUIUSDT", "0.1000"),
            ("BNBUSDT", "1500.00"),
            ("AVAXUSDT", "150.00"),
        ],
    )
    def test_child_order_cap_strict_boundary_across_extreme_prices(
        self, tmp_path: Path, symbol: str, extreme_price: str
    ) -> None:
        """Verifies child order sizing never exceeds 5.00 USDT + 1 step buffer."""
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        p = Decimal(extreme_price)
        spec = DEFAULT_SPECS.get(symbol, {})
        step_size = spec.get("step_size", Decimal("0.001"))
        if getattr(engine.gateway, "testnet", True) and symbol == "BTCUSDT":
            step_size = Decimal("0.00001")

        q_price, q_qty, notional = engine._calculate_child_order_qty(symbol, p)

        max_allowed = engine.config.max_micro_order_notional_usdt + (step_size * q_price)
        assert notional <= max_allowed, (
            f"{symbol} at price {p}: notional {notional} exceeded max allowed {max_allowed}"
        )

    def test_aggregate_portfolio_exposure_boundary_confinement(self, tmp_path: Path) -> None:
        """Verifies that 5 positions of $5.00 fill the $25.00 cap, and any 6th order is blocked."""
        engine = build_default_self_driving_engine(storage_dir=tmp_path)
        engine.perform_preflight_checks()

        # Allocate 5 x $5.00 = $25.00
        active_syms = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "XRPUSDT", "BNBUSDT"]
        for sym in active_syms:
            engine.candidates[sym].allocated_exposure_usdt = Decimal("5.00")

        total_exposure = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert total_exposure == Decimal("25.00")

        # Attempt 6th order on SUIUSDT
        setup_sui = TwinsSetupState(
            symbol="SUIUSDT",
            step_6_ready=True,
            side="BUY",
            m1_cisd_price=Decimal("1.20"),
            stop_loss=Decimal("1.15"),
            take_profit_partial=Decimal("1.30"),
        )
        blocks_before = engine.interlock_blocks_count
        order = engine.dispatch_ict_intention(setup_sui)
        assert order is None
        assert engine.interlock_blocks_count == blocks_before + 1

    def test_liquid_cash_floor_fail_closed_under_depleted_equity(self, tmp_path: Path) -> None:
        """Verifies order is rejected when projected cash would fall below 75% of equity."""
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        # Simulate cash reduced to 78.00 USDT (close to 75% floor)
        engine.ledger.cash = Decimal("78.00")

        # An order of $5.00 would reduce cash to $73.00 (73% < 75%)
        setup = TwinsSetupState(
            symbol="SOLUSDT",
            step_6_ready=True,
            side="BUY",
            m1_cisd_price=Decimal("170.00"),
            stop_loss=Decimal("165.00"),
            take_profit_partial=Decimal("185.00"),
        )
        blocks_before = engine.interlock_blocks_count
        order = engine.dispatch_ict_intention(setup)
        assert order is None
        assert engine.interlock_blocks_count == blocks_before + 1

    def test_daily_loss_circuit_breaker_lockout_and_flattening(self, tmp_path: Path) -> None:
        """Verifies 3.00 loss triggers CIRCUIT_FLATTENED and blocks all subsequent orders."""
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        # Open SOL position
        setup_sol = TwinsSetupState(
            symbol="SOLUSDT",
            step_6_ready=True,
            side="BUY",
            m1_cisd_price=Decimal("170.00"),
            stop_loss=Decimal("165.00"),
            take_profit_partial=Decimal("185.00"),
        )
        order_sol = engine.dispatch_ict_intention(setup_sol, now_ms=1700000000000)
        assert order_sol is not None
        assert engine.candidates["SOLUSDT"].position_qty > Decimal("0")

        # Set loss to $3.05 (breaches $3.00 ceiling)
        engine.intra_day_loss_usdt = Decimal("3.05")

        # Attempt to dispatch next intention
        setup_eth = TwinsSetupState(
            symbol="ETHUSDT",
            step_6_ready=True,
            side="BUY",
            m1_cisd_price=Decimal("2500.00"),
            stop_loss=Decimal("2450.00"),
            take_profit_partial=Decimal("2600.00"),
        )
        order_eth = engine.dispatch_ict_intention(setup_eth, now_ms=1700000060000)
        assert order_eth is None
        assert engine.state.value == SelfDrivingState.CIRCUIT_FLATTENED.value
        # All positions must be flattened
        assert engine.candidates["SOLUSDT"].position_qty == Decimal("0.0")


# =============================================================================
# Challenge 4: Client Order ID Format & Collision Freedom
# =============================================================================


class TestAdversarialClientOrderIdGeneration:
    """Stress-tests client order ID formatting, character constraints, and collision resistance."""

    def test_burst_client_order_ids_across_all_roles(self) -> None:
        """Generates 5,000 order IDs across roles, asserting len <= 36 and 0 collisions."""
        symbols = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "DOGEUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "SUIUSDT",
            "AVAXUSDT",
        ]
        roles = ["ict", "tp", "sl", "cl"]
        generated: list[str] = []

        now_fixed = 1700000000000

        for i in range(5000):
            sym = symbols[i % len(symbols)]
            role = roles[i % len(roles)]
            # Call with fixed timestamp to simulate high-frequency burst
            cid = generate_p317_ict_client_order_id(symbol=sym, ts_ms=now_fixed, role=role)
            assert len(cid) <= 36, f"Order ID {cid} length {len(cid)} exceeded 36 characters!"
            assert cid.startswith(f"canary-p317-{role}-")
            generated.append(cid)

        # Assert 100% collision-free
        unique_cids = set(generated)
        assert len(unique_cids) == len(generated), (
            f"Collisions detected in burst ID generation: "
            f"{len(generated) - len(unique_cids)} duplicates!"
        )

    def test_timestamp_monotonicity_under_fixed_clock_burst(self) -> None:
        """Verifies embedded timestamps advance strictly monotonically when clock is fixed."""
        fixed_ts = 1700000000000
        timestamps: list[int] = []

        for _ in range(1000):
            cid = generate_p317_ict_client_order_id("BTCUSDT", ts_ms=fixed_ts, role="ict")
            # Format: canary-p317-ict-btc-{ts:013d}-{suffix}
            parts = cid.split("-")
            ts_str = parts[4]
            assert len(ts_str) == 13, f"Timestamp part '{ts_str}' is not 13 digits!"
            timestamps.append(int(ts_str))

        # Assert strict monotonicity: ts[i] < ts[i+1]
        for i in range(len(timestamps) - 1):
            assert timestamps[i + 1] > timestamps[i], (
                f"Timestamp did not advance monotonically at index {i}: "
                f"{timestamps[i]} >= {timestamps[i + 1]}"
            )

        assert timestamps[0] >= fixed_ts
        assert timestamps[-1] == timestamps[0] + 999

    def test_clock_skew_regression_monotonic_recovery(self) -> None:
        """Verifies monotonic counter protects against backwards time drift (clock skew)."""
        cid1 = generate_p317_ict_client_order_id("SOLUSDT", ts_ms=1700000050000, role="ict")
        ts1 = int(cid1.split("-")[4])

        cid2 = generate_p317_ict_client_order_id("SOLUSDT", ts_ms=1700000000000, role="ict")
        ts2 = int(cid2.split("-")[4])

        cid3 = generate_p317_ict_client_order_id("SOLUSDT", ts_ms=1699999000000, role="ict")
        ts3 = int(cid3.split("-")[4])

        assert ts2 > ts1, f"Clock regression failed to advance: ts2={ts2} <= ts1={ts1}"
        assert ts3 > ts2, f"Clock regression failed to advance: ts3={ts3} <= ts2={ts2}"
        assert cid1 != cid2 != cid3

    def test_multithreaded_burst_generation_concurrency_safety(self) -> None:
        """Verifies 16 concurrent threads generating 5,000 order IDs suffer zero collisions."""
        num_workers = 16
        total_orders = 5000
        fixed_ts = 1700000000000
        symbols = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "DOGEUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "SUIUSDT",
            "AVAXUSDT",
        ]
        roles = ["ict", "tp", "sl", "cl"]

        def _worker_task(idx: int) -> str:
            sym = symbols[idx % len(symbols)]
            role = roles[idx % len(roles)]
            return generate_p317_ict_client_order_id(symbol=sym, ts_ms=fixed_ts, role=role)

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            generated_cids = list(executor.map(_worker_task, range(total_orders)))

        assert len(generated_cids) == total_orders
        unique_cids = set(generated_cids)
        assert len(unique_cids) == total_orders, (
            f"Concurrent multi-threaded generation produced "
            f"{total_orders - len(unique_cids)} collisions!"
        )
        for cid in generated_cids:
            assert len(cid) <= 36

    @pytest.mark.parametrize(
        "symbol",
        [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "DOGEUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "SUIUSDT",
            "AVAXUSDT",
        ],
    )
    @pytest.mark.parametrize("role", ["ict", "tp", "sl", "cl"])
    def test_all_roles_all_8_pairs_matrix_grid(self, symbol: str, role: str) -> None:
        """Verifies all 32 pair/role combinations produce tags <= 36 chars."""
        cid = generate_p317_ict_client_order_id(symbol=symbol, ts_ms=1700000000000, role=role)
        assert len(cid) <= 36, f"Order ID '{cid}' exceeds 36 chars (len={len(cid)})"
        if role == "ict":
            assert len(cid) == 36, f"Entry tag '{cid}' should be exactly 36 chars"
        else:
            assert len(cid) == 35, f"Bracket tag '{cid}' should be exactly 35 chars"
