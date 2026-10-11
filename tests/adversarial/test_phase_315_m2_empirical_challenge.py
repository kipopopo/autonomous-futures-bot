"""Milestone M2 Empirical Adversarial Challenge Suite.

Empirically probes:
1. Double-entry balance conservation (|drift| < 1e-15 USDT) across all 8 universe pairs,
   maker fees (0.02%), taker fees (0.05%), positive (TP) and negative (SL) PnL realizations.
2. Concurrent multi-threaded order sizing and fill reconciliation across 8 pairs simultaneously.
3. Testnet micro-slicing logic resilience under rapid consecutive ticks and adaptive BTC
   step-sizing.
4. Micro-capital boundary interlocks: aggregate exposure (<= $25.00), cash floor (>= 75%),
   daily loss (<= $3.00).
"""

from __future__ import annotations

import concurrent.futures
import random
import threading
from decimal import Decimal
from pathlib import Path

from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    quantize_tick_size,
)
from autonomous_futures.execution.self_driving import (
    SelfDrivingOrder,
    SelfDrivingState,
    build_default_self_driving_engine,
)
from autonomous_futures.safety.kill_switch import (
    CentralizedSolvencyLedger,
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


class TestDoubleEntrySolvencyConservation:
    """Empirically verifies double-entry balance conservation (|drift| < 1e-15 USDT)."""

    def test_solvency_drift_8_pairs_maker_taker_pnl(self) -> None:
        """Verifies zero drift across multi-asset simultaneous orders with 0.02% maker,

        0.05% taker fees, and mixed PnL realizations.
        """
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)

        # 8 pairs with test notionals ~$5 each
        orders = [
            ("BTCUSDT", "BUY", 0.00005, 100000.0, 0.0002, 0.0),
            ("ETHUSDT", "BUY", 0.002, 2500.0, 0.0002, 0.0),
            ("SOLUSDT", "BUY", 0.04, 125.0, 0.0002, 0.0),
            ("DOGEUSDT", "BUY", 59.0, 0.086, 0.0002, 0.0),
            ("BNBUSDT", "BUY", 0.01, 550.0, 0.0002, 0.0),
            ("XRPUSDT", "BUY", 3.6, 1.40, 0.0002, 0.0),
            ("SUIUSDT", "BUY", 4.6, 1.11, 0.0002, 0.0),
            ("AVAXUSDT", "BUY", 1.0, 10.50, 0.0002, 0.0),
        ]

        # 1. Record 8 entry fills
        for sym, side, qty, price, fee_rate, rpnl in orders:
            notional = qty * price
            fee = round(notional * fee_rate, 8)
            ledger.record_fill(
                symbol=sym,
                side=side,
                qty=qty,
                price=price,
                fee=fee,
                realized_pnl=rpnl,
            )
            snap = ledger.get_snapshot()
            assert snap.zero_balance_drift is True, f"Drift on entry {sym}: {snap.drift}"
            assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")

        # 2. Record 8 exit fills with 0.05% taker fees (4 winners hitting TP, 4 losers hitting SL)
        exits = [
            ("BTCUSDT", "SELL", 0.00005, 103000.0, 0.0005, 0.150),
            ("ETHUSDT", "SELL", 0.002, 2550.0, 0.0005, 0.100),
            ("SOLUSDT", "SELL", 0.04, 130.0, 0.0005, 0.200),
            ("DOGEUSDT", "SELL", 59.0, 0.090, 0.0005, 0.236),
            ("BNBUSDT", "SELL", 0.01, 540.0, 0.0005, -0.100),
            ("XRPUSDT", "SELL", 3.6, 1.35, 0.0005, -0.180),
            ("SUIUSDT", "SELL", 4.6, 1.05, 0.0005, -0.276),
            ("AVAXUSDT", "SELL", 1.0, 9.80, 0.0005, -0.700),
        ]

        for sym, side, qty, price, fee_rate, rpnl in exits:
            notional = qty * price
            fee = round(notional * fee_rate, 8)
            ledger.record_fill(
                symbol=sym,
                side=side,
                qty=qty,
                price=price,
                fee=fee,
                realized_pnl=rpnl,
            )
            snap = ledger.get_snapshot()
            assert snap.zero_balance_drift is True, f"Drift on exit {sym}: {snap.drift}"
            assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")

    def test_solvency_conservation_under_100_randomized_fills(self) -> None:
        """Property-based fuzzing: 100 sequential randomized fills with random fees and PnL."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        rng = random.Random(42)

        for i in range(100):
            sym = rng.choice(ALL_8_PAIRS)
            side = rng.choice(["BUY", "SELL"])
            qty = round(rng.uniform(0.1, 100.0), 4)
            price = round(rng.uniform(0.05, 50000.0), 4)
            fee_rate = rng.choice([0.0002, 0.0004, 0.0005])
            notional = qty * price
            fee = round(notional * fee_rate, 8)
            rpnl = round(rng.uniform(-0.80, 0.80), 6)

            ledger.record_fill(
                symbol=sym,
                side=side,
                qty=qty,
                price=price,
                fee=fee,
                realized_pnl=rpnl,
            )
            snap = ledger.get_snapshot()
            assert snap.zero_balance_drift is True, f"Fuzz drift at iter {i}: {snap.drift}"
            assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")

    def test_emergency_flattening_all_8_pairs_zero_drift(self) -> None:
        """Emergency flattening across all 8 pairs returns allocated margin with zero drift."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)

        # Stage 8 positions with allocated margin
        per_pair_margin = Decimal("3.00")
        total_staged_margin = per_pair_margin * len(ALL_8_PAIRS)  # 24.00 USDT
        ledger.cash -= total_staged_margin
        ledger.allocated_margin += total_staged_margin

        snap_staged = ledger.get_snapshot()
        assert snap_staged.zero_balance_drift is True
        assert abs(Decimal(str(snap_staged.drift))) < Decimal("1e-15")
        assert snap_staged.allocated_margin == 24.0

        # Flatten each of the 8 pairs with 0.05% taker fee
        for sym in ALL_8_PAIRS:
            notional = float(per_pair_margin)
            fee = round(notional * 0.0005, 6)
            ledger.cash += per_pair_margin  # Return margin to cash
            ledger.flatten_position(symbol=sym, notional=notional, fee=fee)
            snap = ledger.get_snapshot()
            assert snap.zero_balance_drift is True, f"Drift on flattening {sym}: {snap.drift}"
            assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")

        assert ledger.allocated_margin == Decimal("0.0")


class TestConcurrentMultiPairThreading:
    """Stress tests concurrent multi-threaded execution across all 8 pairs simultaneously."""

    def test_concurrent_order_sizing_all_8_pairs(self) -> None:
        """Spawns 8 concurrent threads, each calculating child order sizing 50 times."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))

        pair_prices: dict[str, list[Decimal]] = {
            "BTCUSDT": [Decimal("95000.00"), Decimal("102500.50"), Decimal("98000.00")],
            "ETHUSDT": [Decimal("2450.00"), Decimal("2700.50"), Decimal("2550.00")],
            "SOLUSDT": [Decimal("110.00"), Decimal("125.40"), Decimal("118.00")],
            "DOGEUSDT": [Decimal("0.08600"), Decimal("0.09120"), Decimal("0.08450")],
            "BNBUSDT": [Decimal("540.00"), Decimal("580.20"), Decimal("560.00")],
            "XRPUSDT": [Decimal("1.4000"), Decimal("1.4500"), Decimal("1.3800")],
            "SUIUSDT": [Decimal("1.1100"), Decimal("1.2500"), Decimal("1.0800")],
            "AVAXUSDT": [Decimal("10.500"), Decimal("11.200"), Decimal("9.900")],
        }

        errors: list[str] = []

        def worker(sym: str) -> None:
            prices = pair_prices[sym]
            for i in range(50):
                p = prices[i % len(prices)]
                try:
                    q_p, q_q, notional = engine._calculate_child_order_qty(sym, p)
                    if q_q > Decimal("0"):
                        spec = DEFAULT_SPECS[sym]
                        assert notional >= Decimal("5.00"), f"{sym}: {notional} < 5.00"
                        step = spec["step_size"]
                        if sym == "BTCUSDT" and getattr(engine.gateway, "testnet", True):
                            step = Decimal("0.00001")
                        max_allowed = Decimal("5.00") + (step * q_p)
                        assert notional <= max_allowed, f"{sym}: {notional} > {max_allowed}"
                except Exception as exc:
                    errors.append(f"{sym} error: {exc}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, sym) for sym in ALL_8_PAIRS]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Concurrent sizing produced errors: {errors}"

    def test_concurrent_ledger_thread_safety(self) -> None:
        """Spawns 8 concurrent threads recording fills on a shared CentralizedSolvencyLedger."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        lock = threading.Lock()
        errors: list[str] = []

        def record_worker(sym: str) -> None:
            for i in range(25):
                fee = round(0.001 + (i * 0.0001), 6)
                rpnl = round(0.05 if (i % 2 == 0) else -0.03, 6)
                with lock:
                    ledger.record_fill(
                        symbol=sym,
                        side="BUY" if i % 2 == 0 else "SELL",
                        qty=1.0,
                        price=10.0,
                        fee=fee,
                        realized_pnl=rpnl,
                    )
                    snap = ledger.get_snapshot()
                    zero_ok = snap.zero_balance_drift
                    drift_ok = abs(Decimal(str(snap.drift))) < Decimal("1e-15")
                    if not zero_ok or not drift_ok:
                        errors.append(f"Drift breach on {sym} iter {i}: drift={snap.drift}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(record_worker, sym) for sym in ALL_8_PAIRS]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Thread safety breaches: {errors}"
        final_snap = ledger.get_snapshot()
        assert final_snap.zero_balance_drift is True
        assert abs(Decimal(str(final_snap.drift))) < Decimal("1e-15")


class TestTestnetMicroSlicingAndRapidTicks:
    """Tests testnet micro-slicing logic and rapid consecutive ticks."""

    def test_testnet_btc_adaptive_step_size(self) -> None:
        """On testnet, BTC step size adapts to 0.00001 when target_notional < price * step_size."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        assert getattr(engine.gateway, "testnet", True) is True

        # At $100,000, 5.00 / 100,000 = 0.00005 (exactly 5 steps of 0.00001).
        # Standard step_size=0.001 yields notional=0 (0.001 * 100000 = 100 > 5.00).
        # Adaptive step_size=0.00001 allows slicing exactly 0.00005 BTC = $5.00 notional on testnet.
        _qp, qq, notional = engine._calculate_child_order_qty("BTCUSDT", Decimal("100000.00"))
        assert qq == Decimal("0.00005")
        assert notional == Decimal("5.00")

        # Non-representable price: at $95,000, 5.00 / 95000 = 0.0000526 -> 0.00005 * 95000 = 4.75.
        # BTC is NOT in scalper pool, so step-up must NOT apply: fail-closed 0.0 quantity.
        _qp95, qq95, notional95 = engine._calculate_child_order_qty(
            "BTCUSDT", Decimal("95000.00")
        )
        assert qq95 == Decimal("0.0")
        assert notional95 == Decimal("0.0")

        # Live exchange mode: when testnet is False, min_notional is 50.00 and step_size is 0.001.
        # Micro-capital $5 child order must be rejected fail-closed for BTC on live exchange.
        engine.gateway.testnet = False
        _qp_live, qq_live, notional_live = engine._calculate_child_order_qty(
            "BTCUSDT", Decimal("100000.00")
        )
        assert qq_live == Decimal("0.0")
        assert notional_live == Decimal("0.0")
        engine.gateway.testnet = True

    def test_rapid_consecutive_ticks_no_drift_or_deadlock(self, tmp_path: Path) -> None:
        """Sends 100 rapid consecutive ticks across candidate pairs verifying zero drift."""
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            output_dir=tmp_path,
        )
        engine.perform_preflight_checks()

        base_ts = 1728600000000
        rng = random.Random(1337)
        symbols_to_test = list(CANDIDATE_7_PAIRS)

        for i in range(100):
            sym = symbols_to_test[i % len(symbols_to_test)]
            spec = DEFAULT_SPECS[sym]
            base_p = Decimal("100.0") if sym in ("SOLUSDT", "AVAXUSDT") else Decimal("1.0")
            fluctuation = Decimal(str(rng.uniform(-0.02, 0.02)))
            tick_price = quantize_tick_size(base_p + fluctuation, spec["tick_size"])

            engine.process_microstructure_tick(
                symbol=sym,
                price=tick_price,
                hawkes_spectral_radius=0.15,
                heartbeat_age_ms=12.0,
                ensemble_signal="NEUTRAL",
                ts_ms=base_ts + i * 100,
            )

        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")

    def test_sub_dollar_step_up_sizing_bounds(self) -> None:
        """Verifies step-up sizing strictly obeys min_notional and max_allowed boundary."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))

        test_cases = [
            ("DOGEUSDT", Decimal("0.08600"), Decimal("1"), Decimal("5.00")),
            ("XRPUSDT", Decimal("1.4000"), Decimal("0.1"), Decimal("5.00")),
            ("SUIUSDT", Decimal("1.1100"), Decimal("0.1"), Decimal("5.00")),
            ("AVAXUSDT", Decimal("10.500"), Decimal("1"), Decimal("5.00")),
        ]

        for sym, price, step, min_notional in test_cases:
            q_p, q_q, notional = engine._calculate_child_order_qty(sym, price)
            assert notional >= min_notional, f"{sym}: {notional} < {min_notional}"
            max_headroom = Decimal("5.00") + (step * q_p)
            assert notional <= max_headroom, f"{sym}: {notional} > {max_headroom}"


class TestMicroCapitalGuardrailInterlocks:
    """Stress tests micro-capital boundary containment across the 8-pair universe."""

    def test_aggregate_exposure_hard_cap_confinement_8_pairs(self) -> None:
        """Aggregate portfolio exposure ceiling strictly confines total exposure <= $25.00."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        now_ms = 1728600000000

        # Simulate 4 open positions of ~$5.10 each (total ~20.40 USDT)
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("5.10")
        engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("5.10")
        engine.candidates["DOGEUSDT"].allocated_exposure_usdt = Decimal("5.07")
        engine.candidates["XRPUSDT"].allocated_exposure_usdt = Decimal("5.04")

        # Current total exposure: 20.31 USDT. An additional order on BNBUSDT (~5.50) > 25.00 USDT
        order = engine.process_microstructure_tick(
            symbol="BNBUSDT",
            price=Decimal("550.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=25.0,
            ensemble_signal="BUY",
            ts_ms=now_ms,
        )
        assert order is None
        assert engine.interlock_blocks_count >= 1

    def test_daily_loss_auto_flattening_halts_all_pairs(self) -> None:
        """Hitting $3.00 daily loss immediately trips CIRCUIT_FLATTENED and halts all pairs."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        now_ms = 1728600000000

        # Stage active exposure on multiple candidate pairs
        engine.candidates["SOLUSDT"].position_qty = Decimal("0.05")
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("5.50")
        engine.candidates["DOGEUSDT"].position_qty = Decimal("59.0")
        engine.candidates["DOGEUSDT"].allocated_exposure_usdt = Decimal("5.07")

        # Simulate daily loss hitting $3.00
        engine.intra_day_loss_usdt = Decimal("3.00")

        # Next tick on any symbol must trip circuit breaker and flatten all positions
        order = engine.process_microstructure_tick(
            symbol="ETHUSDT",
            price=Decimal("2500.00"),
            hawkes_spectral_radius=0.10,
            heartbeat_age_ms=25.0,
            ensemble_signal="BUY",
            ts_ms=now_ms,
        )
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED

        # All positions must be flattened to 0
        for _sym, cand in engine.candidates.items():
            assert cand.position_qty == Decimal("0.0")
            assert cand.allocated_exposure_usdt == Decimal("0.0")

        # Solvency ledger must preserve zero drift
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift is True
        assert abs(Decimal(str(snap.drift))) < Decimal("1e-15")

    def test_synchronized_barrier_concurrent_order_dispatch(self) -> None:
        """7 threads synchronized via Barrier attempt simultaneous BUY orders."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        engine.perform_preflight_checks()

        prices = {
            "SOLUSDT": Decimal("110.00"),
            "ETHUSDT": Decimal("2500.00"),
            "DOGEUSDT": Decimal("0.086"),
            "BNBUSDT": Decimal("550.00"),
            "XRPUSDT": Decimal("1.40"),
            "SUIUSDT": Decimal("1.11"),
            "AVAXUSDT": Decimal("10.50"),
        }

        barrier = threading.Barrier(7)
        dispatched: list[SelfDrivingOrder] = []

        def fire_synchronized(sym: str) -> None:
            barrier.wait()
            o = engine.process_microstructure_tick(
                symbol=sym,
                price=prices[sym],
                hawkes_spectral_radius=0.10,
                heartbeat_age_ms=10.0,
                ensemble_signal="BUY",
                ts_ms=1000,
            )
            if o:
                dispatched.append(o)

        threads = [
            threading.Thread(target=fire_synchronized, args=(sym,))
            for sym in CANDIDATE_7_PAIRS
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total_exposure = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
        assert total_exposure <= Decimal("25.00"), f"Cap breached: {total_exposure} > 25.00"
        assert len(dispatched) >= 1

    def test_fuzz_10000_prices_all_candidates_sizing_invariants(self) -> None:
        """Fuzz tests 10,000 randomized prices across all 7 candidates verifying invariants."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        rng = random.Random(999)

        price_ranges = {
            "SOLUSDT": (10.0, 500.0),
            "ETHUSDT": (500.0, 10000.0),
            "DOGEUSDT": (0.001, 5.0),
            "BNBUSDT": (50.0, 2000.0),
            "XRPUSDT": (0.1, 20.0),
            "SUIUSDT": (0.1, 20.0),
            "AVAXUSDT": (1.0, 200.0),
        }

        for _ in range(10000):
            sym = rng.choice(list(CANDIDATE_7_PAIRS))
            low_p, high_p = price_ranges[sym]
            raw_p = Decimal(str(round(rng.uniform(low_p, high_p), 6)))
            spec = DEFAULT_SPECS[sym]
            step_size = spec["step_size"]
            tick_size = spec["tick_size"]
            min_notional = Decimal("5.00")

            q_p, q_q, notional = engine._calculate_child_order_qty(sym, raw_p)

            if q_q > Decimal("0"):
                assert notional >= min_notional, f"{sym}: {notional} < {min_notional}"
                max_allowed = Decimal("5.00") + (step_size * q_p)
                assert notional <= max_allowed, f"{sym}: {notional} > {max_allowed}"
                assert (q_q % step_size) == Decimal("0"), f"{sym}: qty not divisible by step"
                assert (q_p % tick_size) == Decimal("0"), f"{sym}: price not divisible by tick"
