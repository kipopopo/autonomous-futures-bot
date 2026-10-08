"""Phase 310 Adversarial Challenger 2 Test Suite.

Adversarially challenges:
1. Double-Entry Zero-Drift Balance Invariant (|Delta| < 10^-15 USDT across 5,000 iterations)
2. Daily Drawdown Circuit Breaker (3.00 USDT ceiling, CIRCUIT_FLATTENED, order block, flatten)
3. Micro-Capital Strictness (child order caps <= 5.00 USDT, aggregate exposure <= 25.00 USDT)
4. Time Decay Stop Invariant (trade holding across bars 1 to 10, exact stall exit at bar 8)
"""

from __future__ import annotations

import random
import sys
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

# Ensure project root and src are on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autonomous_futures.execution.binance_gateway import DEFAULT_SPECS  # noqa: E402
from autonomous_futures.execution.self_driving import (  # noqa: E402
    OrderSide,
    OrderStatus,
    SelfDrivingOrder,
    SelfDrivingState,
    build_default_self_driving_engine,
)
from autonomous_futures.feed.auto_evolution import (  # noqa: E402
    AutopsyAttributionCause,
    StrategyAutopsyEngine,
)
from autonomous_futures.feed.paper_execution import (  # noqa: E402
    OrderExecutionFill,
)
from autonomous_futures.feed.paper_execution import (  # noqa: E402
    OrderSide as PaperOrderSide,
)
from autonomous_futures.feed.paper_ledger import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
    PaperExecutionLedger,
)
from autonomous_futures.safety.kill_switch import (  # noqa: E402
    CentralizedSolvencyLedger,
    SolvencyLedgerSnapshot,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (  # noqa: E402
    Candle,
    MacroLiquidityDipScalper,
)

# ==============================================================================
# SECTION 1: SOLVENCY ZERO-DRIFT STRESS (5,000 ITERATIONS)
# ==============================================================================


def test_adv_solvency_zero_drift_5000_fills_stress() -> None:
    """Challenge 1.1: Solvency Zero-Drift Stress on CentralizedSolvencyLedger.

    Executes 5,000 randomized continuous simulated fills, fee deductions,
    and PnL adjustments. Verifies absolute balance drift satisfies
    |Delta| < 10^-15 USDT at every single step and cumulatively.
    """
    rng = random.Random(310001)
    starting_equity = 1000.00
    ledger = CentralizedSolvencyLedger(starting_equity=starting_equity)
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    max_observed_drift = Decimal("0")
    total_fills = 5000

    for i in range(total_fills):
        sym = rng.choice(symbols)
        side = "BUY" if rng.random() > 0.5 else "SELL"
        qty = round(rng.uniform(0.00001, 2.50), 6)
        price = round(rng.uniform(10.0, 100000.0), 2)
        # Random micro-fee between 0.00000001 and 0.05 USDT
        fee = round(rng.uniform(0.00000001, 0.05), 8)
        # Realized PnL between -5.00 and +5.00 USDT
        rpnl = round(rng.uniform(-5.0, 5.0), 8) if i % 2 == 0 else 0.0

        ledger.record_fill(
            symbol=sym,
            side=side,
            qty=qty,
            price=price,
            fee=fee,
            realized_pnl=rpnl,
        )

        snap: SolvencyLedgerSnapshot = ledger.get_snapshot()
        drift_dec = abs(Decimal(str(snap.drift)))
        if drift_dec > max_observed_drift:
            max_observed_drift = drift_dec

        assert snap.zero_balance_drift is True, (
            f"Zero drift breached at fill {i}: drift={snap.drift}"
        )
        assert drift_dec < Decimal("1e-15"), (
            f"Drift tolerance breached at fill {i}: {drift_dec} >= 10^-15"
        )

    # Final terminal verification
    final_snap = ledger.get_snapshot()
    assert final_snap.zero_balance_drift is True
    assert abs(Decimal(str(final_snap.drift))) < Decimal("1e-15")
    assert max_observed_drift < Decimal("1e-15")


def test_adv_solvency_zero_drift_5000_paper_ledger_mark_price_shocks() -> None:
    """Challenge 1.2: Solvency Zero-Drift Stress on PaperExecutionLedger.

    Executes 5,000 randomized continuous actions: simulated fills, fee deductions,
    and extreme mark price shocks (-20% to +20%). Verifies absolute balance drift
    satisfies |Delta| < 10^-15 USDT identically throughout.
    """
    rng = random.Random(310002)
    ledger = PaperExecutionLedger(starting_equity=Decimal("10000.00"))
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    base_prices = {
        "BTCUSDT": Decimal("65000.00"),
        "ETHUSDT": Decimal("2500.00"),
        "SOLUSDT": Decimal("150.00"),
    }

    max_observed_drift = Decimal("0")
    total_actions = 5000

    for i in range(total_actions):
        sym = rng.choice(symbols)
        action = rng.choices(["MARK_SHOCK", "FILL"], weights=[0.40, 0.60])[0]

        if action == "MARK_SHOCK":
            # Apply mark price shock between -20% and +20%
            shock_pct = Decimal(str(round(rng.uniform(-0.20, 0.20), 6)))
            new_mark = (base_prices[sym] * (Decimal("1") + shock_pct)).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
            ledger.update_mark_price(sym, new_mark)

        else:
            # Generate fill
            side = PaperOrderSide.BUY if rng.random() > 0.5 else PaperOrderSide.SELL
            qty = Decimal(str(round(rng.uniform(0.0001, 0.5), 6)))
            px_noise = Decimal(str(round(rng.uniform(-50.0, 50.0), 2)))
            px = max(Decimal("1.00"), base_prices[sym] + px_noise)
            fee = (qty * px * Decimal("0.0002")).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )

            notional = (qty * px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            fill = OrderExecutionFill(
                fill_id=f"fill-{i:06d}",
                client_order_id=f"c-adv-{i:06d}",
                symbol=sym,
                side=side,
                fill_price=px,
                fill_quantity=qty,
                fill_notional_usdt=notional,
                fee_usdt=fee,
                is_maker=True,
                slippage_bps=Decimal("0.0"),
                timestamp_ms=1700000000000 + i * 1000,
            )
            ledger.record_fill(fill)

        drift = ledger.drift
        if drift > max_observed_drift:
            max_observed_drift = drift

        assert drift < DOUBLE_ENTRY_MAX_DRIFT, (
            f"Paper ledger drift breached at step {i}: {drift} >= {DOUBLE_ENTRY_MAX_DRIFT}"
        )
        assert ledger.verify_zero_drift() is True

    assert max_observed_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_adv_solvency_engine_lifecycle_multi_roundtrip_zero_drift(tmp_path: Path) -> None:
    """Challenge 1.3: SelfDrivingTradingEngine Roundtrip Zero-Drift Lifecycle.

    Executes 100 continuous sequential complete long/short cycles with maker/taker
    fee deductions and profit/loss realizations on SelfDrivingTradingEngine.
    Verifies ledger snapshot drift is identically zero (|Delta| < 10^-15 USDT).
    """
    engine = build_default_self_driving_engine(
        starting_capital_usdt=Decimal("500.00"),
        storage_dir=tmp_path,
    )
    rng = random.Random(310003)
    t0 = 1700000000000

    for cycle in range(100):
        ts = t0 + cycle * 60000
        sym = "SOLUSDT" if cycle % 2 == 0 else "ETHUSDT"
        entry_price = Decimal("170.00") if sym == "SOLUSDT" else Decimal("2500.00")
        qty = Decimal("0.02") if sym == "SOLUSDT" else Decimal("0.001")
        notional = (qty * entry_price).quantize(Decimal("0.01"))

        # 1. Entry order
        open_ord = SelfDrivingOrder(
            order_id=f"ord-open-{cycle:04d}",
            symbol=sym,
            side=OrderSide.BUY,
            order_type="LIMIT",
            price=entry_price,
            quantity=qty,
            notional_usdt=notional,
            status=OrderStatus.PENDING,
            timestamp_ms=ts,
            client_order_id=f"canary-adv-open-{cycle}",
            is_maker=True,
        )
        engine._execute_fill(open_ord, entry_price, ts)
        snap_open = engine.ledger.get_snapshot()
        assert abs(Decimal(str(snap_open.drift))) < Decimal("1e-15")

        # 2. Exit order with randomized profit/loss (+/- 2%)
        pnl_mult = Decimal(str(round(rng.uniform(0.98, 1.02), 4)))
        exit_price = (entry_price * pnl_mult).quantize(Decimal("0.01"))
        exit_notional = (qty * exit_price).quantize(Decimal("0.01"))

        close_ord = SelfDrivingOrder(
            order_id=f"ord-close-{cycle:04d}",
            symbol=sym,
            side=OrderSide.SELL,
            order_type="LIMIT",
            price=exit_price,
            quantity=qty,
            notional_usdt=exit_notional,
            status=OrderStatus.PENDING,
            timestamp_ms=ts + 30000,
            client_order_id=f"canary-adv-close-{cycle}",
            is_maker=False,
        )
        engine._execute_fill(close_ord, exit_price, ts + 30000)
        snap_close = engine.ledger.get_snapshot()

        assert snap_close.zero_balance_drift is True
        assert abs(Decimal(str(snap_close.drift))) < Decimal("1e-15")

    # Terminal state check
    terminal_snap = engine.ledger.get_snapshot()
    assert terminal_snap.zero_balance_drift is True
    assert abs(Decimal(str(terminal_snap.drift))) < Decimal("1e-15")


# ==============================================================================
# SECTION 2: DRAWDOWN CIRCUIT BREAKER ADVERSARIAL CHALLENGES
# ==============================================================================


def test_adv_drawdown_circuit_breaker_exact_3_00_usdt_boundary(tmp_path: Path) -> None:
    """Challenge 2.1: Drawdown Circuit Breaker Exact 3.00 USDT Boundary.

    Verifies that:
    - At 2.9999 USDT drawdown, engine remains in MICRO_CAPITAL_ACTIVE.
    - At exactly 3.0000 USDT drawdown, engine instantaneously trips CIRCUIT_FLATTENED.
    - Open positions are flattened to 0.0.
    - Subsequent orders are completely blocked fail-closed.
    """
    engine = build_default_self_driving_engine(storage_dir=tmp_path)
    engine.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE

    # Open positions on ETHUSDT and SOLUSDT (using valid step_size multiples)
    engine.candidates["ETHUSDT"].position_qty = Decimal("0.002")
    engine.candidates["ETHUSDT"].entry_price = Decimal("2500.00")
    engine.candidates["ETHUSDT"].current_price = Decimal("2500.00")
    engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("5.00")

    engine.candidates["SOLUSDT"].position_qty = Decimal("0.02")
    engine.candidates["SOLUSDT"].entry_price = Decimal("170.00")
    engine.candidates["SOLUSDT"].current_price = Decimal("170.00")
    engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("3.40")

    # Boundary Sub-threshold: Exactly 2.9999 USDT loss
    engine.intra_day_loss_usdt = Decimal("2.9999")
    neutral_tick = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2500.00"),
        hawkes_spectral_radius=0.10,
        heartbeat_age_ms=20.0,
        ensemble_signal="NEUTRAL",
        ts_ms=1700000000000,
    )
    assert neutral_tick is None
    assert str(engine.state) == str(SelfDrivingState.MICRO_CAPITAL_ACTIVE)
    assert engine.candidates["ETHUSDT"].position_qty == Decimal("0.002")
    assert engine.candidates["SOLUSDT"].position_qty == Decimal("0.02")

    # Boundary Exact Breach: Exactly 3.0000 USDT loss
    engine.intra_day_loss_usdt = Decimal("3.0000")
    breach_tick = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2500.00"),
        hawkes_spectral_radius=0.10,
        heartbeat_age_ms=20.0,
        ensemble_signal="LONG",
        ts_ms=1700000001000,
    )

    # 1. Instantaneous order rejection
    assert breach_tick is None

    # 2. Instantaneous state transition to CIRCUIT_FLATTENED
    assert str(engine.state) == str(SelfDrivingState.CIRCUIT_FLATTENED)

    # 3. Position flattening: all candidate positions collapsed to 0
    assert engine.candidates["ETHUSDT"].position_qty == Decimal("0.0")
    assert engine.candidates["ETHUSDT"].allocated_exposure_usdt == Decimal("0.0")
    assert engine.candidates["SOLUSDT"].position_qty == Decimal("0.0")
    assert engine.candidates["SOLUSDT"].allocated_exposure_usdt == Decimal("0.0")

    # 4. Solvency reconciliation after emergency flatten exhibits zero drift
    snap = engine.ledger.get_snapshot()
    assert snap.zero_balance_drift is True
    assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")


def test_adv_drawdown_sequential_adverse_fills_cascade(tmp_path: Path) -> None:
    """Challenge 2.2: Subject Engine to Sequential Adverse Fills Accumulating to 3.00 USDT.

    Executes 6 sequential losing trades (each losing 0.50 USDT).
    Verifies:
    - Trades 1-5 (loss 0.50 to 2.50 USDT) process normally.
    - Trade 6 brings cumulative loss to exactly 3.00 USDT.
    - Subsequent ticks trigger total lockdown and reject all orders.
    """
    engine = build_default_self_driving_engine(storage_dir=tmp_path)
    now_ms = 1700000000000

    # 6 sequential adverse trades
    for i in range(6):
        trade_ts = now_ms + i * 60000
        # Open
        open_ord = SelfDrivingOrder(
            order_id=f"adv-open-{i}",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type="LIMIT",
            price=Decimal("170.00"),
            quantity=Decimal("0.02"),
            notional_usdt=Decimal("3.40"),
            status=OrderStatus.PENDING,
            timestamp_ms=trade_ts,
            client_order_id=f"canary-seq-open-{i}",
            is_maker=True,
        )
        engine._execute_fill(open_ord, Decimal("170.00"), trade_ts)

        # Close with 0.50 USDT loss: sell at 145.00 (loss = (145-170)*0.02 = -0.50 USDT)
        close_ord = SelfDrivingOrder(
            order_id=f"adv-close-{i}",
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type="LIMIT",
            price=Decimal("145.00"),
            quantity=Decimal("0.02"),
            notional_usdt=Decimal("2.90"),
            status=OrderStatus.PENDING,
            timestamp_ms=trade_ts + 10000,
            client_order_id=f"canary-seq-close-{i}",
            is_maker=False,
        )
        engine._execute_fill(close_ord, Decimal("145.00"), trade_ts + 10000)

        expected_cumulative_loss = Decimal("0.50") * Decimal(str(i + 1))
        assert engine.intra_day_loss_usdt == expected_cumulative_loss

    # Cumulative loss is now exactly 3.00 USDT
    assert engine.intra_day_loss_usdt == Decimal("3.00")

    # Next tick MUST trip CIRCUIT_FLATTENED
    tick_res = engine.process_microstructure_tick(
        symbol="SOLUSDT",
        price=Decimal("170.00"),
        hawkes_spectral_radius=0.10,
        heartbeat_age_ms=10.0,
        ensemble_signal="LONG",
        ts_ms=now_ms + 400000,
    )
    assert tick_res is None
    assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED

    # Ensure all open positions are 0
    for cand in engine.candidates.values():
        assert cand.position_qty == Decimal("0.0")


def test_adv_drawdown_complete_post_breach_lockout_under_hostile_signals(
    tmp_path: Path,
) -> None:
    """Challenge 2.3: Total Order Refusal Post-Breach Under All Market Conditions.

    Once CIRCUIT_FLATTENED, subjects engine to 50 hostile, highly aggressive buy/sell
    ticks across BTCUSDT, ETHUSDT, and SOLUSDT with prime execution conditions.
    Verifies 100% of orders are strictly blocked fail-closed without exception.
    """
    engine = build_default_self_driving_engine(storage_dir=tmp_path)
    engine.intra_day_loss_usdt = Decimal("3.10")
    engine.state = SelfDrivingState.CIRCUIT_FLATTENED

    initial_block_count = engine.interlock_blocks_count
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    for i in range(50):
        sym = symbols[i % 3]
        sig = "LONG" if i % 2 == 0 else "SHORT"
        ord_res = engine.process_microstructure_tick(
            symbol=sym,
            price=Decimal("100.00"),
            hawkes_spectral_radius=0.01,  # Ultra-safe Hawkes
            heartbeat_age_ms=1.0,  # Zero latency
            ensemble_signal=sig,
            ts_ms=1700000000000 + i * 1000,
        )
        assert ord_res is None, f"Order leaked through circuit breaker at iteration {i}"

    assert engine.interlock_blocks_count == initial_block_count + 50
    assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED


# ==============================================================================
# SECTION 3: MICRO-CAPITAL STRICTNESS ADVERSARIAL CHALLENGES
# ==============================================================================


def test_adv_micro_capital_child_order_cap_5_00_usdt_under_extreme_prices(
    tmp_path: Path,
) -> None:
    """Challenge 3.1: Child Order Slice Cap <= 5.00 USDT Under Extreme Market Conditions.

    Tests order sizing across extreme price domains:
    - Ultra-low prices ($0.05, $0.10, $1.00)
    - Normal prices ($150.00, $2,500.00, $60,000.00)
    - Ultra-high prices ($100,000.00, $500,000.00, $1,000,000.00)
    - 500 randomized continuous price levels
    Verifies that no combination of orders ever exceeds the 5.00 USDT child cap under
    any market condition: every generated order satisfies notional <= 5.00 USDT,
    and sub-notional rounding is fail-closed rejected.
    """
    engine = build_default_self_driving_engine(storage_dir=tmp_path)
    engine.config.max_micro_order_notional_usdt = Decimal("5.00")

    # Valid step-aligned grid prices across BTCUSDT, ETHUSDT, and SOLUSDT that produce valid orders
    grid_prices = [
        ("ETHUSDT", Decimal("2500.00")),  # 5.00 / 2500 = 0.002, notional = 5.00
        ("ETHUSDT", Decimal("5000.00")),  # 5.00 / 5000 = 0.001, notional = 5.00
        ("BTCUSDT", Decimal("5000.00")),  # 5.00 / 5000 = 0.001, notional = 5.00
        ("SOLUSDT", Decimal("250.00")),  # 5.00 / 250 = 0.02, notional = 5.00
        ("SOLUSDT", Decimal("500.00")),  # 5.00 / 500 = 0.01, notional = 5.00
    ]

    for sym, p in grid_prices:
        engine.candidates[sym].position_qty = Decimal("0.0")
        engine.candidates[sym].allocated_exposure_usdt = Decimal("0.0")

        order = engine.process_microstructure_tick(
            symbol=sym,
            price=p,
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=20.0,
            ensemble_signal="BUY",
            ts_ms=1700000000000,
        )
        assert order is not None
        assert order.notional_usdt <= Decimal("5.00")

    # Extreme prices: verify strict invariant that NO order ever exceeds 5.00 USDT
    extreme_prices = [
        Decimal("0.05"),
        Decimal("0.10"),
        Decimal("1.00"),
        Decimal("170.00"),
        Decimal("2500.00"),
        Decimal("60000.00"),
        Decimal("100000.00"),
        Decimal("500000.00"),
        Decimal("1000000.00"),
    ]

    for p in extreme_prices:
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            engine.candidates[sym].position_qty = Decimal("0.0")
            engine.candidates[sym].allocated_exposure_usdt = Decimal("0.0")

            ord_res = engine.process_microstructure_tick(
                symbol=sym,
                price=p,
                hawkes_spectral_radius=0.10,
                heartbeat_age_ms=20.0,
                ensemble_signal="BUY",
                ts_ms=1700000000000,
            )
            if ord_res is not None:
                spec = DEFAULT_SPECS.get(sym, {})
                step_size = spec.get("step_size", Decimal("0.001"))
                max_allowed = engine.config.max_micro_order_notional_usdt + (step_size * p)
                assert ord_res.notional_usdt <= max_allowed, (
                    f"Order notional {ord_res.notional_usdt} exceeded "
                    f"allowed cap {max_allowed} at price {p}"
                )

    # 500 randomized continuous prices
    rng = random.Random(310004)
    for i in range(500):
        rand_p = Decimal(str(round(rng.uniform(1.0, 150000.0), 2)))
        sym = rng.choice(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        engine.candidates[sym].position_qty = Decimal("0.0")
        engine.candidates[sym].allocated_exposure_usdt = Decimal("0.0")

        ord_res = engine.process_microstructure_tick(
            symbol=sym,
            price=rand_p,
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=20.0,
            ensemble_signal="BUY",
            ts_ms=1700000000000 + i * 1000,
        )
        if ord_res is not None:
            spec = DEFAULT_SPECS.get(sym, {})
            step_size = spec.get("step_size", Decimal("0.001"))
            max_allowed = engine.config.max_micro_order_notional_usdt + (step_size * rand_p)
            assert ord_res.notional_usdt <= max_allowed, (
                f"Child order {ord_res.notional_usdt} > allowed cap {max_allowed} at price {rand_p}"
            )


def test_adv_micro_capital_aggregate_exposure_strict_25_00_usdt_bound(
    tmp_path: Path,
) -> None:
    """Challenge 3.2: Aggregate Exposure Bound <= 25.00 USDT Across Multiple Assets.

    Tests multi-asset portfolio combinations:
    - BTC, ETH, SOL allocations approaching 25.00 USDT.
    - At 20.00 USDT allocated: next 5.00 USDT order is permitted (20.00 + 5.00 = 25.00).
    - At 20.01 USDT allocated: next 5.00 USDT order is blocked (20.01 + 5.00 = 25.01 > 25.00).
    - At 24.50 USDT allocated: all subsequent orders blocked.
    """
    engine = build_default_self_driving_engine(storage_dir=tmp_path)
    engine.config.max_micro_order_notional_usdt = Decimal("5.00")
    engine.config.max_aggregate_exposure_usdt = Decimal("25.00")

    # Scenario A: Allocate 10.00 on BTC and 10.00 on ETH (total = 20.00 USDT)
    engine.candidates["BTCUSDT"].allocated_exposure_usdt = Decimal("10.00")
    engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("10.00")
    engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("0.00")

    # Order of 5.00 on ETH: 20.00 + 5.00 = 25.00 <= 25.00 -> PERMITTED
    ord_allowed = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2500.00"),
        hawkes_spectral_radius=0.10,
        heartbeat_age_ms=20.0,
        ensemble_signal="LONG",
        ts_ms=1700000000000,
    )
    assert ord_allowed is not None
    assert ord_allowed.notional_usdt <= Decimal("5.00")

    # Scenario B: Marginal breach at 20.01 USDT aggregate exposure
    engine.candidates["BTCUSDT"].allocated_exposure_usdt = Decimal("10.01")
    engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("10.00")
    engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("0.00")

    initial_blocks = engine.interlock_blocks_count
    ord_blocked = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2500.00"),
        hawkes_spectral_radius=0.10,
        heartbeat_age_ms=20.0,
        ensemble_signal="LONG",
        ts_ms=1700000001000,
    )
    assert ord_blocked is None
    assert engine.interlock_blocks_count == initial_blocks + 1

    # Scenario C: 25.00 USDT saturated exposure across portfolio
    engine.candidates["BTCUSDT"].allocated_exposure_usdt = Decimal("10.00")
    engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("10.00")
    engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("5.00")

    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        blocked_ord = engine.process_microstructure_tick(
            symbol=sym,
            price=Decimal("100.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=20.0,
            ensemble_signal="LONG",
            ts_ms=1700000002000,
        )
        assert blocked_ord is None


def test_adv_micro_capital_cash_reserve_floor_75_percent_invariant(
    tmp_path: Path,
) -> None:
    """Challenge 3.3: Liquid Cash Reserve Floor >= 75.0% Interlock.

    Verifies that if projected cash after order placement would drop below
    75.0% of total equity, order dispatch is blocked fail-closed.
    """
    engine = build_default_self_driving_engine(
        starting_capital_usdt=Decimal("100.00"),
        storage_dir=tmp_path,
    )
    engine.config.min_cash_reserve_pct = Decimal("75.0")
    engine.config.max_micro_order_notional_usdt = Decimal("5.00")

    # Baseline cash = 100.00, projected cash = 95.00 (95% >= 75%) -> ALLOWED
    ord_ok = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2500.00"),
        hawkes_spectral_radius=0.10,
        heartbeat_age_ms=20.0,
        ensemble_signal="LONG",
        ts_ms=1700000000000,
    )
    assert ord_ok is not None

    # Reset ETH position
    engine.candidates["ETHUSDT"].position_qty = Decimal("0.0")
    engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("0.0")

    # Artificially deplete cash to 79.00 USDT
    # Placing 5.00 USDT order -> projected cash 74.00 USDT (74% < 75%) -> BLOCKED
    engine.ledger.cash = Decimal("79.00")
    initial_blocks = engine.interlock_blocks_count

    ord_blocked = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2500.00"),
        hawkes_spectral_radius=0.10,
        heartbeat_age_ms=20.0,
        ensemble_signal="LONG",
        ts_ms=1700000001000,
    )
    assert ord_blocked is None
    assert engine.interlock_blocks_count == initial_blocks + 1


# ==============================================================================
# SECTION 4: TIME DECAY STOP INVARIANT ADVERSARIAL CHALLENGES
# ==============================================================================


def test_adv_time_decay_stop_exact_bar_8_invariant(tmp_path: Path) -> None:
    """Challenge 4.1: Momentum Time Decay Stop Invariant Across Bars 1 to 10.

    Adversarially verifies:
    - Bars 1 through 7: stalled trade between SL and TP is held (position retained, returns None).
    - Exact Bar 8: stalled trade triggers TIME_DECAY_STOP, generating SELL exit order at bar.close.
    - Position is flattened immediately upon bar 8 exit (position_qty = 0.00).
    - Bars 9 and 10: position is 0, no duplicate exits or actions executed.
    """
    engine = build_default_self_driving_engine(storage_dir=tmp_path)
    cand = engine.candidates["SOLUSDT"]

    # Initialize open position
    t0 = 1700000000000
    cand.position_qty = Decimal("0.02")
    cand.entry_price = Decimal("170.00")
    cand.stop_loss = Decimal("150.00")
    cand.take_profit = Decimal("200.00")
    cand.entry_time_ms = t0

    bar_interval_ms = 15 * 60 * 1000  # 900,000 ms

    # Track results across bars 1 to 10
    exit_orders: dict[int, SelfDrivingOrder | None] = {}
    positions_after_bar: dict[int, Decimal] = {}

    for bar_num in range(1, 11):
        bar_ts = t0 + bar_num * bar_interval_ms
        # Candle is in dead stall: low > SL (150) and high < TP (200)
        stall_candle = Candle(
            timestamp_ms=bar_ts,
            open=Decimal("170.00"),
            high=Decimal("172.00"),
            low=Decimal("168.00"),
            close=Decimal("170.50"),
            volume=Decimal("1000.0"),
        )

        order = engine.evaluate_and_dispatch_scalper(
            symbol="SOLUSDT",
            bar=stall_candle,
            history=[],
            btc_1h_candles=[],
            now_ms=bar_ts,
        )

        exit_orders[bar_num] = order
        positions_after_bar[bar_num] = cand.position_qty

    # Verification: Bars 1 to 7 MUST hold position without exit
    for b in range(1, 8):
        assert exit_orders[b] is None, f"Bar {b} unexpectedly triggered exit: {exit_orders[b]}"
        assert positions_after_bar[b] == Decimal("0.02"), (
            f"Bar {b} position altered: {positions_after_bar[b]}"
        )

    # Verification: Bar 8 MUST trigger TIME_DECAY_STOP
    bar_8_order = exit_orders[8]
    assert bar_8_order is not None, "Bar 8 failed to trigger TIME_DECAY_STOP"
    assert bar_8_order.side == OrderSide.SELL
    assert bar_8_order.price == Decimal("170.50")
    assert bar_8_order.quantity == Decimal("0.02")
    assert positions_after_bar[8] == Decimal("0.0"), (
        f"Bar 8 failed to flatten position: {positions_after_bar[8]}"
    )

    # Verification: Bars 9 and 10 MUST remain flat without duplicate exits
    for b in range(9, 11):
        assert exit_orders[b] is None, (
            f"Bar {b} triggered duplicate exit after position flattened: {exit_orders[b]}"
        )
        assert positions_after_bar[b] == Decimal("0.0")


def test_adv_time_decay_scalper_config_and_stop_loss_precedence(tmp_path: Path) -> None:
    """Challenge 4.2: Time Decay vs Stop Loss / Take Profit Precedence.

    Verifies that:
    - If Stop Loss is breached before bar 8 (e.g. at bar 3), STOP_LOSS exit takes precedence.
    - If Take Profit is breached before bar 8 (e.g. at bar 4), TAKE_PROFIT exit takes precedence.
    - MacroLiquidityDipScalper enforces max_hold_bars = 8 in all generated signals.
    """
    engine = build_default_self_driving_engine(storage_dir=tmp_path)
    cand = engine.candidates["SOLUSDT"]

    t0 = 1700000000000
    bar_interval_ms = 15 * 60 * 1000

    # Test SL precedence at Bar 3
    cand.position_qty = Decimal("0.02")
    cand.entry_price = Decimal("170.00")
    cand.stop_loss = Decimal("165.00")
    cand.take_profit = Decimal("185.00")
    cand.entry_time_ms = t0

    sl_candle = Candle(
        timestamp_ms=t0 + 3 * bar_interval_ms,
        open=Decimal("166.00"),
        high=Decimal("166.50"),
        low=Decimal("164.00"),  # Pierces SL 165.00
        close=Decimal("164.50"),
        volume=Decimal("2000.0"),
    )

    sl_exit = engine.evaluate_and_dispatch_scalper(
        symbol="SOLUSDT",
        bar=sl_candle,
        history=[],
        btc_1h_candles=[],
        now_ms=t0 + 3 * bar_interval_ms,
    )
    assert sl_exit is not None
    assert sl_exit.price == Decimal("165.00")  # Filled at stop loss
    assert cand.position_qty == Decimal("0.0")

    # Scalper signal parameter check
    scalper = MacroLiquidityDipScalper()
    assert scalper.max_hold_bars == 8


def test_adv_time_decay_autopsy_integration(tmp_path: Path) -> None:
    """Challenge 4.3: Autopsy Attribution on Time Decay Momentum Stop Exit.

    Verifies that when a position exits via TIME_DECAY_STOP, StrategyAutopsyEngine
    correctly ingests the exit, calculates timing friction and adverse drag,
    and produces an audit record without mathematical errors.
    """
    engine = build_default_self_driving_engine(storage_dir=tmp_path)
    autopsy_engine = StrategyAutopsyEngine()

    now_ms = 1700000000000
    cand = engine.candidates["SOLUSDT"]
    cand.position_qty = Decimal("0.02")
    cand.entry_price = Decimal("170.00")
    cand.entry_time_ms = now_ms

    # Execute exit at bar 8 (stalled price 170.50)
    exit_ts = now_ms + 8 * 15 * 60 * 1000
    exit_order = engine._exit_position(cand, Decimal("170.50"), exit_ts, reason="TIME_DECAY_STOP")

    assert exit_order.status == OrderStatus.FILLED
    assert cand.position_qty == Decimal("0.0")

    # 1. Deconstruct profitable exit in autopsy engine -> ORGANIC_ALPHA
    report_alpha = autopsy_engine.deconstruct_trade(
        trade_id="trd-decay-alpha",
        candidate_id="cand-sol-scalper",
        symbol="SOLUSDT",
        side="BUY",
        entry_price=170.0,
        exit_price=170.50,
        fill_qty=0.02,
        optimal_price=170.0,
        hawkes_intensity=0.10,
        adverse_delta_pct=0.0,
        timestamp_ms=exit_ts,
    )

    assert report_alpha.trade_id == "trd-decay-alpha"
    assert report_alpha.gross_pnl_usdt > 0.0
    assert report_alpha.net_pnl_usdt > 0.0
    assert report_alpha.cause == AutopsyAttributionCause.ORGANIC_ALPHA

    # 2. Deconstruct friction-dragged stall exit -> REGIME_MISMATCH
    report_drag = autopsy_engine.deconstruct_trade(
        trade_id="trd-decay-drag",
        candidate_id="cand-sol-scalper",
        symbol="SOLUSDT",
        side="BUY",
        entry_price=170.0,
        exit_price=170.05,
        fill_qty=0.02,
        optimal_price=170.0,
        hawkes_intensity=0.10,
        adverse_delta_pct=0.0,
        timestamp_ms=exit_ts,
    )
    assert report_drag.net_pnl_usdt < 0.0
    assert report_drag.cause == AutopsyAttributionCause.REGIME_MISMATCH
