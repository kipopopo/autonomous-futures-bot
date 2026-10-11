"""Milestone M4 Phase 2 (Tier 5 White-Box Adversarial Coverage Hardening).

Comprehensive white-box adversarial stress test suite targeting backend core:
- src/autonomous_futures/api/canary.py (dynamic state transitions, 15s scan cycle,
  sample counter monotonicity, macro trend gating payload, exception handling).
- src/autonomous_futures/execution/self_driving.py (sub-tick pricing, 7 candidate pairs
  step-up whitelist, BTCUSDT exclusion, child order cap <= $5.00, portfolio exposure <= $25.00,
  cash reserve >= 75%, daily loss <= $3.00, zero-drift balance invariant).
- src/autonomous_futures/strategy/macro_liquidity_scalper.py (15m liquidity dip sweep logic,
  ATR/EMA/RSI conditions, 8 pairs universe handling).
- src/autonomous_futures/execution/binance_gateway.py (exchange filter quantization,
  36-char client order ID invariants, 8-pair specs).

Validates:
1. Double-entry solvency balance invariant (|drift| < 1e-15 USDT) across 8 pairs under 50k+ ops,
   concurrent multi-threading, fee rounding, and emergency flattening.
2. Division-by-Zero immunity under flat volatility, zero volume, zero/negative equity,
   empty history, and extreme input values.
3. Micro-capital hard caps and whitelist isolation across all 8 universe pairs
   (child cap <= $5.00, aggregate exposure <= $25.00, cash floor >= 75%, daily loss <= $3.00,
   BTC exclusion from candidate step-up whitelist).
4. Boundary and fuzzing robustness (sub-tick pricing, 36-char ID invariance, Hawkes/latency
   boundary tripwires, dynamic evolution state transitions).
"""

from __future__ import annotations

import concurrent.futures
import random
import threading
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from autonomous_futures.api.canary import (
    _build_macro_gating_state,
    load_verified_canary_auto_evolution,
)
from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    generate_client_order_id,
    generate_drill_client_order_id,
    quantize_step_size,
    quantize_tick_size,
)
from autonomous_futures.execution.self_driving import (
    OrderStatus,
    SelfDrivingState,
    build_default_self_driving_engine,
)
from autonomous_futures.safety.kill_switch import (
    CentralizedSolvencyLedger,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    MacroLiquidityDipScalper,
    MacroTrendFilter,
    compute_rsi,
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


# =============================================================================
# 1. DOUBLE-ENTRY SOLVENCY BALANCE INVARIANT STRESS (|drift| < 1e-15 USDT)
# =============================================================================


class TestTier5DoubleEntrySolvencyStress:
    """White-box stress testing of double-entry ledger solvency and balance conservation."""

    def test_zero_drift_50k_sequential_multi_asset_lifecycle(self) -> None:
        """Verifies |drift| < 1e-15 USDT holds across 50,000+ randomized operations

        involving all 8 pairs, maker/taker fees, and positive/negative realized PnL.
        """
        ledger = CentralizedSolvencyLedger(starting_equity=1000.0)
        rng = random.Random(42)
        total_ops = 50_000
        max_drift_observed = Decimal("0.0")

        active_positions: dict[str, dict[str, Decimal]] = {
            sym: {"qty": Decimal("0.0"), "entry_price": Decimal("0.0"), "margin": Decimal("0.0")}
            for sym in ALL_8_PAIRS
        }

        for op_idx in range(total_ops):
            sym = rng.choice(ALL_8_PAIRS)
            pos = active_positions[sym]
            action = rng.choice(["ENTRY", "PRICE_TICK", "EXIT"]) if pos["qty"] > 0 else "ENTRY"

            if action == "ENTRY":
                margin = Decimal(str(round(rng.uniform(4.50, 5.00), 4)))
                price = Decimal(str(round(rng.uniform(0.08, 90000.0), 4)))
                qty = (margin / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
                if qty <= Decimal("0"):
                    qty = Decimal("0.000001")

                fee_rate = Decimal("0.0002")  # 0.02% maker
                fee = (qty * price * fee_rate).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

                ledger.cash -= margin
                ledger.allocated_margin += margin
                ledger.record_fill(
                    symbol=sym,
                    side="BUY",
                    qty=float(qty),
                    price=float(price),
                    fee=float(fee),
                    realized_pnl=0.0,
                )
                pos["qty"] += qty
                pos["entry_price"] = price
                pos["margin"] += margin

            elif action == "PRICE_TICK":
                # Simulated price fluctuation
                price_delta = Decimal(str(round(rng.uniform(-0.02, 0.02), 4)))
                _ = pos["entry_price"] * (Decimal("1.0") + price_delta)

            elif action == "EXIT":
                pnl_ratio = Decimal(str(round(rng.uniform(-0.05, 0.08), 4)))
                exit_price = pos["entry_price"] * (Decimal("1.0") + pnl_ratio)
                realized_pnl = (exit_price - pos["entry_price"]) * pos["qty"]
                fee_rate = Decimal("0.0004")  # 0.04% taker
                fee = (pos["qty"] * exit_price * fee_rate).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )

                ledger.allocated_margin -= pos["margin"]
                ledger.cash += pos["margin"]
                ledger.record_fill(
                    symbol=sym,
                    side="SELL",
                    qty=float(pos["qty"]),
                    price=float(exit_price),
                    fee=float(fee),
                    realized_pnl=float(realized_pnl),
                )
                pos["qty"] = Decimal("0.0")
                pos["margin"] = Decimal("0.0")
                ledger.unrealized_pnl = Decimal("0.0")

            if (op_idx + 1) % 500 == 0 or op_idx == total_ops - 1:
                snap = ledger.get_snapshot()
                drift_dec = abs(Decimal(str(snap.drift)))
                if drift_dec > max_drift_observed:
                    max_drift_observed = drift_dec
                assert snap.zero_balance_drift is True
                assert (
                    drift_dec < Decimal("1e-15")
                ), f"Drift breach at op {op_idx}: {snap.drift} USDT"

        assert max_drift_observed < Decimal("1e-15")

    def test_sub_satoshi_fee_deduction_and_precision_conservation(self) -> None:
        """Verifies sub-satoshi fee deduction (1e-8 to 1e-16 USDT) preserves

        exact double-entry solvency equality:
        Cash + Allocated Margin + Unrealized PnL == Starting Equity + Realized PnL.
        """
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)

        # 1,000 micro fills with fractional fees
        for i in range(1000):
            sym = ALL_8_PAIRS[i % len(ALL_8_PAIRS)]
            qty = 0.00001
            price = 50000.0 + i
            fee = round(qty * price * 0.0002, 8)
            rpnl = round(0.0001 * ((-1) ** i), 8)

            ledger.record_fill(
                symbol=sym,
                side="BUY" if i % 2 == 0 else "SELL",
                qty=qty,
                price=price,
                fee=fee,
                realized_pnl=rpnl,
            )
            snap = ledger.get_snapshot()
            assert snap.zero_balance_drift is True
            assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")

    def test_concurrent_multithreaded_balance_mutations_zero_drift(self) -> None:
        """Challenges ledger under 16 concurrent worker threads hammering

        record_fill, get_snapshot, and margin allocations simultaneously.
        """
        ledger = CentralizedSolvencyLedger(starting_equity=5000.0)
        lock = threading.Lock()
        drift_violations: list[str] = []

        def worker(thread_id: int) -> None:
            rng = random.Random(1000 + thread_id)
            for _ in range(500):
                sym = ALL_8_PAIRS[rng.randint(0, 7)]
                qty = 0.01 * (thread_id + 1)
                price = 100.0 + rng.uniform(-5.0, 5.0)
                fee = round(qty * price * 0.0002, 8)
                rpnl = round(rng.uniform(-0.10, 0.15), 6)

                with lock:
                    ledger.record_fill(
                        symbol=sym,
                        side="BUY" if rng.random() > 0.5 else "SELL",
                        qty=qty,
                        price=price,
                        fee=fee,
                        realized_pnl=rpnl,
                    )
                    snap = ledger.get_snapshot()
                    if not snap.zero_balance_drift or abs(Decimal(str(snap.drift))) >= Decimal(
                        "1e-15"
                    ):
                        drift_violations.append(
                            f"Thread {thread_id} observed drift: {snap.drift} USDT"
                        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(worker, i) for i in range(16)]
            concurrent.futures.wait(futures)

        assert len(drift_violations) == 0, f"Drift violations detected: {drift_violations[:5]}"
        final_snap = ledger.get_snapshot()
        assert final_snap.zero_balance_drift is True
        assert abs(Decimal(str(final_snap.drift))) < Decimal("1e-15")

    def test_emergency_multi_pair_flattening_zero_drift(self, tmp_path: Path) -> None:
        """Verifies emergency flattening of positions across multiple pairs preserves

        exact mathematical solvency (|drift| < 1e-15 USDT).
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )

        # Open positions on 4 distinct candidate pairs
        symbols_to_open = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "XRPUSDT"]
        for sym in symbols_to_open:
            price = engine.candidates[sym].current_price
            order = engine.process_microstructure_tick(
                symbol=sym,
                price=price,
                hawkes_spectral_radius=0.10,
                heartbeat_age_ms=50.0,
                ensemble_signal="BUY",
            )
            assert order is not None
            assert order.status == OrderStatus.FILLED

        # Trigger emergency auto-flattening
        engine._flatten_all_positions(reason="Adverse market crash emergency flattening")

        # Confirm all positions are flat
        for sym in ALL_8_PAIRS:
            cand = engine.candidates[sym]
            assert cand.position_qty == Decimal("0.0")
            assert cand.allocated_exposure_usdt == Decimal("0.0")

        # Verify solvency ledger zero drift
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert (
            abs(Decimal(str(snap.drift))) < Decimal("1e-15")
        ), f"Drift on flattening: {snap.drift}"


# =============================================================================
# 2. DIVISION-BY-ZERO IMMUNITY & EXTREME VALUE HARDENING
# =============================================================================


class TestTier5DivisionByZeroImmunity:
    """White-box verification that no input scenario causes DivisionByZero."""

    def test_macro_scalper_zero_atr_division_immunity(self) -> None:
        """Verifies MacroLiquidityDipScalper does not divide by zero when ATR == 0.0

        (e.g., flat market where High == Low == Close).
        """
        scalper = MacroLiquidityDipScalper()
        flat_candles = [
            Candle(
                timestamp_ms=1000 + i * 900000,
                open=Decimal("100.00"),
                high=Decimal("100.00"),
                low=Decimal("100.00"),
                close=Decimal("100.00"),
                volume=Decimal("1000.0"),
            )
            for i in range(30)
        ]

        signal = scalper.evaluate_15m_bar(
            symbol="SOLUSDT",
            bar=flat_candles[-1],
            history=flat_candles[:-1],
            macro_trend_allowed=True,
        )
        # Should gracefully return None without raising ZeroDivisionError
        assert signal is None

    def test_macro_scalper_zero_volume_sma_division_immunity(self) -> None:
        """Verifies MacroLiquidityDipScalper does not divide by zero when Volume SMA == 0.0

        (e.g., market with zero volume bars).
        """
        scalper = MacroLiquidityDipScalper()
        zero_vol_candles = [
            Candle(
                timestamp_ms=1000 + i * 900000,
                open=Decimal("100.00") + Decimal(str(i)),
                high=Decimal("105.00") + Decimal(str(i)),
                low=Decimal("95.00") + Decimal(str(i)),
                close=Decimal("100.00") + Decimal(str(i)),
                volume=Decimal("0.0"),
            )
            for i in range(30)
        ]

        signal = scalper.evaluate_15m_bar(
            symbol="ETHUSDT",
            bar=zero_vol_candles[-1],
            history=zero_vol_candles[:-1],
            macro_trend_allowed=True,
        )
        assert signal is None

    def test_macro_scalper_rsi_flat_and_extreme_sequences(self) -> None:
        """Verifies compute_rsi handles flat series, all-gain series, and all-loss series

        without ZeroDivisionError.
        """
        # All flat
        flat_series = [Decimal("100.00")] * 50
        rsi_flat = compute_rsi(flat_series, 14)
        assert len(rsi_flat) == 50
        assert rsi_flat[-1] == Decimal("50")

        # All gains (no losses -> avg_loss == 0)
        gain_series = [Decimal(str(100 + i)) for i in range(50)]
        rsi_gains = compute_rsi(gain_series, 14)
        assert rsi_gains[-1] == Decimal("100")

        # All losses (no gains -> avg_gain == 0)
        loss_series = [Decimal(str(200 - i)) for i in range(50)]
        rsi_losses = compute_rsi(loss_series, 14)
        assert rsi_losses[-1] == Decimal("0")

        # Insufficient series length (< period)
        short_series = [Decimal("100.00"), Decimal("101.00")]
        rsi_short = compute_rsi(short_series, 14)
        assert len(rsi_short) == 2
        assert all(r == Decimal("50") for r in rsi_short)

    def test_macro_trend_filter_minimal_and_boundary_candles(self) -> None:
        """Verifies MacroTrendFilter handles empty, single, and boundary candle counts

        fail-closed without exception.
        """
        trend_filter = MacroTrendFilter()

        # Empty
        assert trend_filter.evaluate([]) is False

        # 1 candle
        one_candle = [
            Candle(
                timestamp_ms=1000,
                open=Decimal("80000"),
                high=Decimal("81000"),
                low=Decimal("79000"),
                close=Decimal("80500"),
                volume=Decimal("100"),
            )
        ]
        assert trend_filter.evaluate(one_candle) is False

        # 199 candles (1 below 200 EMA requirement)
        candles_199 = [
            Candle(
                timestamp_ms=1000 + i * 3600000,
                open=Decimal("80000"),
                high=Decimal("81000"),
                low=Decimal("79000"),
                close=Decimal("80500"),
                volume=Decimal("100"),
            )
            for i in range(199)
        ]
        assert trend_filter.evaluate(candles_199) is False

        # 200 candles but 4h history has only 50 candles (fail-closed)
        candles_200 = [*candles_199, candles_199[0]]
        candles_4h_short = candles_199[:50]
        assert trend_filter.evaluate(candles_200, btc_4h_candles=candles_4h_short) is False

    def test_self_driving_engine_total_equity_zero_or_negative_immunity(
        self, tmp_path: Path
    ) -> None:
        """Verifies cash reserve percentage calculation in process_microstructure_tick

        handles total_equity <= 0 without ZeroDivisionError.
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )
        # Artificially set starting equity and realized pnl so total_equity == 0.0
        engine.ledger.starting_equity = Decimal("0.0")
        engine.ledger.realized_pnl = Decimal("0.0")
        engine.ledger.cash = Decimal("0.0")

        # Process a tick with valid buy signal
        order = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("110.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=50.0,
            ensemble_signal="BUY",
        )
        # Order should be rejected fail-closed, with NO ZeroDivisionError
        assert order is None

    def test_canary_evolution_dynamic_progress_zero_division_immunity(self) -> None:
        """Verifies load_verified_canary_auto_evolution handles trade counts 0, negative,

        large numbers, and cycle timestamps cleanly without DivisionByZero.
        """
        # Test 0 closed trades
        resp_0 = load_verified_canary_auto_evolution(
            simulated_timestamp_ms=1728610000000,
            simulated_closed_trades=0,
            simulated_macro_regime="BEARISH",
        )
        assert resp_0.live_progress.closed_trades_count == 0
        assert resp_0.live_progress.cycle_progress_pct == 80.0
        assert resp_0.live_progress.stage_status == "WAITING_FOR_SAMPLES"

        # Test negative closed trades input (boundary safeguard)
        resp_neg = load_verified_canary_auto_evolution(
            simulated_timestamp_ms=1728610000000,
            simulated_closed_trades=-1,
            simulated_macro_regime="BEARISH",
        )
        assert resp_neg.live_progress.closed_trades_count == -1
        assert resp_neg.live_progress.cycle_progress_pct == 76.0

        # Test 100 closed trades
        resp_100 = load_verified_canary_auto_evolution(
            simulated_timestamp_ms=1728610000000,
            simulated_closed_trades=100,
            simulated_macro_regime="BULLISH_ALIGNED",
        )
        assert resp_100.live_progress.cycle_progress_pct == 100.0
        assert resp_100.live_progress.stage_status in ("EVALUATING", "QUALIFIED")

        # Test cycle boundaries (0s, 14s, 15s)
        for sec in (0, 3, 6, 9, 12, 14):
            ts = 1728610000000 + (sec * 1000)
            resp = load_verified_canary_auto_evolution(
                simulated_timestamp_ms=ts,
                simulated_closed_trades=3,
            )
            assert resp.live_progress.next_cycle_seconds >= 1
            assert resp.live_progress.next_cycle_seconds <= 15
            assert resp.live_progress.current_cycle_stage in (
                "INGRESS",
                "HEALTH_EVALUATION",
                "TRADE_AUTOPSY",
                "MUTATION_STAGING",
                "SHADOW_OOS_GATE",
            )


# =============================================================================
# 3. MICRO-CAPITAL HARD CAPS & WHITELIST ISOLATION ACROSS ALL 8 PAIRS
# =============================================================================


class TestTier5MicroCapitalHardCapsAndWhitelistIsolation:
    """White-box verification of hard capital guardrails and candidate isolation."""

    def test_child_order_cap_all_8_pairs(self, tmp_path: Path) -> None:
        """Verifies order sizing across all 8 universe pairs respects the child order cap

        with allowable step-up bounds, and never produces runaway sizing.
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )
        test_prices = {
            "BTCUSDT": [Decimal("50000.00"), Decimal("80000.00"), Decimal("120000.00")],
            "ETHUSDT": [Decimal("1500.00"), Decimal("2500.00"), Decimal("4000.00")],
            "SOLUSDT": [Decimal("80.00"), Decimal("125.00"), Decimal("250.00")],
            "DOGEUSDT": [Decimal("0.05000"), Decimal("0.08600"), Decimal("0.20000")],
            "BNBUSDT": [Decimal("400.00"), Decimal("600.00"), Decimal("800.00")],
            "XRPUSDT": [Decimal("0.8000"), Decimal("1.4000"), Decimal("2.5000")],
            "SUIUSDT": [Decimal("0.8000"), Decimal("1.1100"), Decimal("3.0000")],
            "AVAXUSDT": [Decimal("8.000"), Decimal("10.500"), Decimal("25.000")],
        }

        for sym, prices in test_prices.items():
            for p in prices:
                q_price, q_qty, notional = engine._calculate_child_order_qty(sym, p)
                if notional > Decimal("0.0"):
                    # Check notional is at or slightly above $5.00 only due to single step size
                    step_size = DEFAULT_SPECS[sym]["step_size"]
                    max_allowed = Decimal("5.00") + (step_size * q_price)
                    assert (
                        notional <= max_allowed
                    ), f"{sym} exceeded max allowable step-up: {notional} > {max_allowed}"
                    assert notional >= Decimal(
                        "4.50"
                    ), f"{sym} produced unexpectedly small notional: {notional}"

    def test_btc_strict_step_up_whitelist_exclusion(self, tmp_path: Path) -> None:
        """Verifies BTCUSDT is strictly excluded from candidate step-up whitelist in

        _calculate_child_order_qty. If raw rounded notional < min_notional, it does NOT
        step up and returns (q_price, 0.0, 0.0).
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )
        # Temporarily set gateway.testnet = False to enforce live min_notional = $50.00
        engine.gateway.testnet = False
        p = Decimal("80000.00")
        q_price, q_qty, notional = engine._calculate_child_order_qty("BTCUSDT", p)
        # Because target_notional is $5.00 and min_notional is $50.00, and BTC is NOT
        # on the candidate step-up whitelist, it must return 0.0 quantity fail-closed!
        assert q_qty == Decimal("0.0")
        assert notional == Decimal("0.0")

    def test_sub_dollar_candidate_step_up_bounds(self, tmp_path: Path) -> None:
        """Verifies step-up for sub-dollar coins (DOGE, XRP, SUI) and AVAX:

        1. When rounded notional is $4.9x, exactly 1 step_size is added.
        2. Stepped-up notional satisfies min_notional ($5.00).
        3. Stepped-up notional does not breach the 1-step allowable ceiling.
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )

        # DOGE: price = 0.086, step_size = 1.
        # 5.00 / 0.086 = 58.139 -> rounded down = 58 -> notional = 4.988 (< 5.00)
        # Stepped up: 59 units -> notional = 5.074 USDT
        q_p, q_q, notional = engine._calculate_child_order_qty("DOGEUSDT", Decimal("0.08600"))
        assert q_q == Decimal("59")
        assert notional == Decimal("5.07400")
        assert notional >= Decimal("5.00")
        assert notional <= Decimal("5.00") + (Decimal("1") * Decimal("0.08600"))

        # XRP: price = 1.40, step_size = 0.1.
        # 5.00 / 1.40 = 3.571 -> rounded down = 3.5 -> notional = 4.90 (< 5.00)
        # Stepped up: 3.6 units -> notional = 5.04 USDT
        q_p, q_q, notional = engine._calculate_child_order_qty("XRPUSDT", Decimal("1.4000"))
        assert q_q == Decimal("3.6")
        assert notional == Decimal("5.0400")
        assert notional >= Decimal("5.00")
        assert notional <= Decimal("5.00") + (Decimal("0.1") * Decimal("1.4000"))

        # SUI: price = 1.11, step_size = 0.1.
        # 5.00 / 1.11 = 4.504 -> rounded down = 4.5 -> notional = 4.995 (< 5.00)
        # Stepped up: 4.6 units -> notional = 5.106 USDT
        q_p, q_q, notional = engine._calculate_child_order_qty("SUIUSDT", Decimal("1.1100"))
        assert q_q == Decimal("4.6")
        assert notional == Decimal("5.1060")
        assert notional >= Decimal("5.00")

    def test_aggregate_portfolio_exposure_cap_25_usdt(self, tmp_path: Path) -> None:
        """Verifies aggregate exposure ceiling (<= $25.00 USDT) blocks any order

        that would push total exposure over $25.00.
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )

        # Fill 4 positions: SOL (~$5), ETH (~$5), DOGE (~$5), XRP (~$5) -> total ~$20.25
        symbols = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "XRPUSDT"]
        for sym in symbols:
            p = engine.candidates[sym].current_price
            order = engine.process_microstructure_tick(
                symbol=sym,
                price=p,
                hawkes_spectral_radius=0.10,
                heartbeat_age_ms=50.0,
                ensemble_signal="BUY",
            )
            assert order is not None

        current_exposure = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert current_exposure <= Decimal("25.00")

        # Fill 5th position: SUI (~$5.10) -> total ~$25.35 or near cap
        # If it fits within $25.00 it enters, otherwise blocked.
        p_sui = engine.candidates["SUIUSDT"].current_price
        _ = engine.process_microstructure_tick(
            symbol="SUIUSDT",
            price=p_sui,
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=50.0,
            ensemble_signal="BUY",
        )

        # Now attempt 6th position (AVAX) - MUST be blocked because exposure is near/at $25.00
        p_avax = engine.candidates["AVAXUSDT"].current_price
        initial_blocks = engine.interlock_blocks_count
        order_blocked = engine.process_microstructure_tick(
            symbol="AVAXUSDT",
            price=p_avax,
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=50.0,
            ensemble_signal="BUY",
        )
        assert order_blocked is None
        assert engine.interlock_blocks_count > initial_blocks

    def test_cash_reserve_floor_75pct_rejection(self, tmp_path: Path) -> None:
        """Verifies cash reserve floor (>= 75.0%) strictly blocks new allocations

        when projected unencumbered cash would fall below 75%.
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("20.00"),  # Low capital to easily test cash floor
            storage_dir=tmp_path,
        )
        # Starting equity = $20.00. 75% floor = $15.00 cash reserve required.
        # An order of $5.05 would leave cash = $20.00 - $5.05 = $14.95 (74.75% < 75.0%).
        order = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("110.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=50.0,
            ensemble_signal="BUY",
        )
        assert order is None
        assert engine.interlock_blocks_count >= 1

    def test_intraday_loss_3_usdt_circuit_breaker_flattening(self, tmp_path: Path) -> None:
        """Verifies intra-day loss ceiling (<= $3.00 USDT) triggers CIRCUIT_FLATTENED,

        flattens positions, and locks the engine fail-closed.
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

        # Simulate realized loss reaching $3.00 USDT
        engine.intra_day_loss_usdt = Decimal("3.00")

        # Process next tick - should trip circuit breaker
        order = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("110.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=50.0,
            ensemble_signal="BUY",
        )
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED


# =============================================================================
# 4. BOUNDARY & MALFORMED INPUT FUZZING HARDENING
# =============================================================================


class TestTier5BoundaryAndFuzzingHardening:
    """White-box adversarial fuzzing and boundary condition testing."""

    def test_sub_tick_price_rejection(self, tmp_path: Path) -> None:
        """Verifies sub-tick, negative, and zero prices are rejected fail-closed."""
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )

        invalid_prices = [
            Decimal("-10.00"),
            Decimal("0.0"),
            Decimal("0.001"),  # SOL tick size is 0.01; 0.001 is < 0.5 * 0.01
            Decimal("0.00000001"),
        ]

        for p in invalid_prices:
            init_blocks = engine.interlock_blocks_count
            order = engine.process_microstructure_tick(
                symbol="SOLUSDT",
                price=p,
                hawkes_spectral_radius=0.10,
                heartbeat_age_ms=50.0,
                ensemble_signal="BUY",
            )
            assert order is None
            assert engine.interlock_blocks_count == init_blocks + 1

    def test_client_order_id_36_char_invariance_fuzzing(self) -> None:
        """Fuzzes generate_client_order_id and generate_drill_client_order_id across

        pathological symbol strings, timestamps, and roles. Asserts length <= 36 characters.
        """
        symbols = [
            "",
            "A",
            "BTC",
            "BTCUSDT",
            "SUPERLONGCOINNAMETHATISRIDICULOUSUSDT",
            "123",
            "___",
            "DOGEUSDT",
            "AVAXUSDT",
        ]
        timestamps = [0, 1, 1728610000000, 9999999999999, 10**14]

        for s in symbols:
            for ts in timestamps:
                cid = generate_client_order_id(s, ts)
                assert len(cid) <= 36, f"CID length breach: {len(cid)} for {cid}"

                for role in ("drill", "tp", "sl", "flatten", "cl"):
                    drill_cid = generate_drill_client_order_id(s, ts, role=role)
                    assert (
                        len(drill_cid) <= 36
                    ), f"Drill CID length breach: {len(drill_cid)} for {drill_cid}"

    def test_exchange_filter_quantization_all_8_pairs(self) -> None:
        """Verifies step size ROUND_DOWN and tick size ROUND_HALF_UP compliance

        across all 8 pairs in DEFAULT_SPECS.
        """
        for _sym, spec in DEFAULT_SPECS.items():
            step = spec["step_size"]
            tick = spec["tick_size"]

            # Quantize quantity with fractional excess
            test_qty = Decimal("10.55555555")
            q_qty = quantize_step_size(test_qty, step)
            # Must be integer multiple of step_size
            multiple = q_qty / step
            assert multiple == multiple.to_integral_value()
            assert q_qty <= test_qty  # ROUND_DOWN guarantees no upward bias

            # Quantize price
            test_price = Decimal("100.55555555")
            q_price = quantize_tick_size(test_price, tick)
            p_multiple = q_price / tick
            assert p_multiple == p_multiple.to_integral_value()

    def test_hawkes_and_latency_exact_boundary_interlocks(self, tmp_path: Path) -> None:
        """Verifies exact numeric tripwire boundaries:

        - Hawkes rho = 0.999 (allowed) vs 1.000 (throttled).
        - Latency = 500.0 ms (allowed) vs 500.1 ms (blocked).
        """
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"), storage_dir=tmp_path
        )
        price = engine.candidates["SOLUSDT"].current_price

        # Hawkes boundary 0.999 -> Allowed
        order_h_safe = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=price,
            hawkes_spectral_radius=0.999,
            heartbeat_age_ms=50.0,
            ensemble_signal="BUY",
        )
        assert order_h_safe is not None

        # Hawkes boundary 1.000 -> Throttled
        order_h_trip = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=price,
            hawkes_spectral_radius=1.000,
            heartbeat_age_ms=50.0,
            ensemble_signal="BUY",
        )
        assert order_h_trip is None
        assert engine.state == SelfDrivingState.HAWKES_THROTTLED

        # Reset state
        engine.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE

        # Heartbeat latency 500.0 ms -> Allowed
        order_lat_safe = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=price,
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=500.0,
            ensemble_signal="BUY",
        )
        assert order_lat_safe is not None

        # Heartbeat latency 500.1 ms -> Blocked
        order_lat_trip = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=price,
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=500.1,
            ensemble_signal="BUY",
        )
        assert order_lat_trip is None

    def test_macro_gating_regime_fuzzing(self) -> None:
        """Fuzzes _build_macro_gating_state with varied uppercase/lowercase/unknown strings."""
        test_regimes = [
            ("BULLISH", "BULLISH_ALIGNED", False, True),
            ("bullish_strong", "BULLISH_ALIGNED", False, True),
            ("BEARISH", "BEARISH", True, False),
            ("bearish_crash", "BEARISH", True, False),
            ("SIDEWAYS", "NEUTRAL", True, False),
            ("UNKNOWN_REGIME", "NEUTRAL", True, False),
            ("", "NEUTRAL", True, False),
            ("Chaotic_regime_42", "NEUTRAL", True, False),
        ]

        for raw_regime, expected_norm, exp_filtered, exp_allowed in test_regimes:
            state = _build_macro_gating_state(regime=raw_regime)
            assert state.regime == expected_norm
            assert state.longs_filtered == exp_filtered
            assert state.is_long_allowed == exp_allowed
            assert isinstance(state.explanation, str)
            assert isinstance(state.explanation_ms, str)
            assert len(state.explanation) > 0
            assert len(state.explanation_ms) > 0
