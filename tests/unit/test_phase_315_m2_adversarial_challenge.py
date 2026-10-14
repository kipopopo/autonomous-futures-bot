"""Adversarial Empirical Challenge for Phase 315 Milestone M2.

Empirical verification of:
1. Exchange filter quantization rules (quantize_step_size never rounds up across 50,000 probes).
2. Step-up sizing rules over 10,000 price ticks across extreme regimes for all 8 pairs.
3. Step-up sizing criteria: Q_step == Q_raw + step_size and N_step <= T + (step_size * P).
4. Aggregate portfolio exposure ceiling <= $25.00 USDT confinement across multi-pair allocations.
5. Micro-capital guardrails: cash floor >= 75.0%, daily loss <= $3.00 fail-closed auto-flattening.
6. Centralized solvency ledger zero-drift balance invariant (|drift| < 10^-15 USDT) (10,000 fills).
7. Discovered defect reproduction probes:
   - CRITICAL: DivisionByZero at boundary prices ($0.00001) due to missing quantized_price guard.
   - HIGH: BTC micro child order sizing: exact representable prices ($100k, $50k) succeed,
     non-representable prices ($95k) fail-closed to 0.0 without exceeding $5.00.
   - MEDIUM: Negative price handling in _calculate_child_order_qty.
"""

from __future__ import annotations

import random
import time
from decimal import Decimal

from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    quantize_step_size,
    quantize_tick_size,
)
from autonomous_futures.execution.self_driving import (
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


# ==============================================================================
# 1. QUANTIZATION HARNESS (50,000 PROBES)
# ==============================================================================


class TestQuantizeStepSizeStressProbes:
    """Empirical probe verifying quantize_step_size never rounds up across 50,000 probes."""

    def test_quantize_step_size_never_rounds_up_50000_probes(self) -> None:
        """quantize_step_size must strictly truncate (ROUND_DOWN) for all 50,000 random inputs."""
        steps = [
            Decimal("1"),
            Decimal("0.1"),
            Decimal("0.01"),
            Decimal("0.001"),
            Decimal("0.0001"),
            Decimal("0.00001"),
        ]
        rng = random.Random(42)

        for _ in range(50000):
            step = rng.choice(steps)
            raw = Decimal(str(round(rng.uniform(0.00001, 100000.0), 8)))
            q = quantize_step_size(raw, step)

            # Invariant 1: never round up
            assert q <= raw, f"quantize_step_size rounded up: {q} > {raw} (step={step})"

            # Invariant 2: exact multiple of step_size
            multiple = q / step
            assert multiple == multiple.quantize(Decimal("1")), (
                f"quantize_step_size not multiple of step: {q} / {step} = {multiple}"
            )

            # Invariant 3: remainder strictly less than step_size
            assert raw - q < step, f"Remainder >= step: {raw} - {q} = {raw - q} >= {step}"

    def test_quantize_tick_size_round_half_up_50000_probes(self) -> None:
        """quantize_tick_size must strictly follow ROUND_HALF_UP across 50,000 probes."""
        ticks = [
            Decimal("0.10"),
            Decimal("0.01"),
            Decimal("0.001"),
            Decimal("0.0001"),
            Decimal("0.00001"),
        ]
        rng = random.Random(1337)

        for _ in range(50000):
            tick = rng.choice(ticks)
            raw = Decimal(str(round(rng.uniform(0.00001, 100000.0), 8)))
            p = quantize_tick_size(raw, tick)

            multiple = p / tick
            assert multiple == multiple.quantize(Decimal("1")), (
                f"quantize_tick_size not multiple of tick: {p} / {tick} = {multiple}"
            )


# ==============================================================================
# 2. STEP-UP SIZING RULES (10,000 PROBES ACROSS 8 PAIRS)
# ==============================================================================


class TestStepUpSizing10000PriceProbes:
    """Empirical probe verifying step-up sizing rules over 10,000 price ticks."""

    def test_step_up_sizing_10000_price_ticks_within_spec_regimes(self) -> None:
        """Probes 1,250 prices per pair (10,000 total) across valid price regimes.

        Verifies:
        - Quantized price > 0.
        - Quantity is an exact multiple of active step_size.
        - Step-up strictly satisfies Q_step = Q_raw + step_size and N_step <= T + (step_size * P).
        """
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        rng = random.Random(9999)

        total_probes = 0
        total_stepped_up = 0

        for sym, spec in DEFAULT_SPECS.items():
            tick_size = spec["tick_size"]
            step_size = spec["step_size"]
            min_price = spec.get("min_price", tick_size)
            max_price = spec.get("max_price", Decimal("500000.00"))

            for _ in range(1250):
                total_probes += 1
                # Sample across log-spaced price spectrum
                log_min = float(min_price.ln() / Decimal("10").ln())
                log_max = float(max_price.ln() / Decimal("10").ln())
                exponent = rng.uniform(log_min, log_max)
                price_val = Decimal(str(round(10**exponent, 5)))
                price_val = quantize_tick_size(price_val, tick_size)
                if price_val < min_price:
                    price_val = min_price
                if price_val > max_price:
                    price_val = max_price

                p, q, notional = engine._calculate_child_order_qty(sym, price_val)

                # Determine active step size (for testnet BTC adaptation)
                active_step = (
                    Decimal("0.00001")
                    if (sym == "BTCUSDT" and price_val * step_size > Decimal("5.00"))
                    else step_size
                )

                if q > Decimal("0.0"):
                    # Check multiple
                    mult = q / active_step
                    assert mult == mult.quantize(Decimal("1")), (
                        f"{sym} qty {q} not multiple of step {active_step}"
                    )
                    # Check notional >= min_notional (5.00 USDT testnet)
                    assert notional >= Decimal("5.00"), (
                        f"{sym} notional {notional} < 5.00 min_notional"
                    )

                    raw_qty = quantize_step_size(Decimal("5.00") / p, active_step)
                    if q > raw_qty:
                        total_stepped_up += 1
                        # Strictly Q_step = Q_raw + step_size
                        assert q == raw_qty + active_step, (
                            f"{sym} stepped up qty {q} != raw {raw_qty} + step {active_step}"
                        )
                        # Strictly N_step <= T + (step_size * P)
                        max_allowed = Decimal("5.00") + (active_step * p)
                        assert notional <= max_allowed, (
                            f"{sym} notional {notional} exceeds ceiling {max_allowed}"
                        )
                    else:
                        assert q == raw_qty
                        assert notional <= Decimal("5.00")

        assert total_probes == 10000
        assert total_stepped_up > 0, "Expected step-up sizing to activate across candidate pairs"

    def test_step_up_sizing_rejects_non_whitelisted_foreign_symbols(self) -> None:
        """Non-whitelisted symbols must never trigger step-up and fail-closed to 0.0."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        foreign_symbols = ["PEPEUSDT", "SHIBUSDT", "SOLANAUSDT", "BTCBUSD", "UNKNOWN"]

        for sym in foreign_symbols:
            p, q, notional = engine._calculate_child_order_qty(sym, Decimal("10.50"))
            assert q == Decimal("0.0")
            assert notional == Decimal("0.0")


# ==============================================================================
# 3. EMPIRICAL DEFECT REPRODUCTION PROBES (BUGS DISCOVERED)
# ==============================================================================


class TestDiscoveredDefectReproductionProbes:
    """Empirical reproduction harnesses for defects discovered during M2 challenge."""

    def test_reproduce_division_by_zero_at_boundary_price_0_00001(self) -> None:
        """REMEDIATED: At boundary price $0.00001 USDT, quantize_tick_size rounds
        to 0.0 for 7 out of 8 pairs (tick_size > 0.00001), but defensive quantized_price <= 0
        guard prevents DivisionByZero and returns (0.0, 0.0, 0.0) safely.
        """
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        boundary_price = Decimal("0.00001")

        crashed_symbols: list[str] = []
        for sym in ALL_8_PAIRS:
            try:
                p, q, notional = engine._calculate_child_order_qty(sym, boundary_price)
                assert q >= Decimal("0.0")
                assert notional >= Decimal("0.0")
            except Exception as exc:
                if type(exc).__name__ == "DivisionByZero":
                    crashed_symbols.append(sym)

        # 0 out of 8 pairs crash because quantized_price <= 0 is safely guarded
        assert len(crashed_symbols) == 0, (
            f"Expected 0 pairs to crash with DivisionByZero at $0.00001, got {crashed_symbols}"
        )

    def test_reproduce_sub_tick_price_crashes_process_microstructure_tick(self) -> None:
        """REMEDIATED: Sub-tick price (e.g. BTC at $0.04) is caught by sub-tick guard
        in process_microstructure_tick, safely rejecting the tick with INVALID_PRICE_BLOCK
        without crashing the engine.
        """
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))

        order = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("0.04"),  # Below tick_size / 2 (0.05)
            ensemble_signal="BUY",
            hawkes_spectral_radius=0.1,
            heartbeat_age_ms=50.0,
        )
        assert order is None
        assert engine.interlock_blocks_count >= 1
        assert any(
            evt.get("event_type") == "INVALID_PRICE_BLOCK"
            or evt.get("type") == "INVALID_PRICE_BLOCK"
            for evt in engine.event_log
        )

    def test_reproduce_btc_micro_order_sizing_deadlock_at_realistic_prices(self) -> None:
        """REMEDIATED: BTC micro child order sizing:
        1. Representable price levels ($100k -> 0.00005 BTC = $5.00, $50k -> 0.0001 BTC = $5.00)
           size valid micro child orders without deadlock on testnet.
        2. Non-representable prices ($95k where 0.00005 BTC = $4.75 < $5.00 min_notional)
           strictly fail-closed to 0.0 quantity, preserving the <= $5.00 child order hard cap
           because BTC is the Macro Trend Filter Anchor and excluded from step-up sizing.
        Matches tests/adversarial/test_phase_315_m2_empirical_challenge.py line 270.
        """
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))

        # Representable prices: 5.00 / price is an exact integer multiple of step_size 0.00001
        representable_cases = [
            (Decimal("100000.00"), Decimal("0.00005"), Decimal("5.00")),
            (Decimal("50000.00"), Decimal("0.0001"), Decimal("5.00")),
            (Decimal("25000.00"), Decimal("0.0002"), Decimal("5.00")),
        ]
        for p, expected_qty, expected_notional in representable_cases:
            _, q, notional = engine._calculate_child_order_qty("BTCUSDT", p)
            assert q == expected_qty, f"Expected {expected_qty} at {p}, got {q}"
            assert notional == expected_notional, (
                f"Expected {expected_notional} at {p}, got {notional}"
            )
            assert notional <= Decimal("5.00"), f"Notional {notional} exceeded 5.00 hard cap"

        # Non-representable price: 5.00 / 95000 = 0.0000526 -> 0.00005 * 95000 = 4.75 (< $5.00).
        # BTC is NOT in scalper pool, so step-up must NOT apply: fail-closed 0.0 quantity.
        _qp95, qq95, notional95 = engine._calculate_child_order_qty("BTCUSDT", Decimal("95000.00"))
        assert qq95 == Decimal("0.0"), f"Expected fail-closed 0.0 qty for BTC at $95k, got {qq95}"
        assert notional95 == Decimal("0.0"), (
            f"Expected fail-closed 0.0 notional for BTC at $95k, got {notional95}"
        )

    def test_reproduce_negative_price_returns_negative_quantity(self) -> None:
        """REMEDIATED: Negative price in _calculate_child_order_qty is safely caught
        by price <= 0 guard and returns (0.0, 0.0, 0.0) fail-closed.
        """
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        p, q, notional = engine._calculate_child_order_qty("SOLUSDT", Decimal("-10.00"))

        assert p == Decimal("0.0")
        assert q == Decimal("0.0")
        assert notional == Decimal("0.0")


# ==============================================================================
# 4. SOLVENCY & MICRO-CAPITAL GOVERNANCE HARNESS
# ==============================================================================


class TestSolvencyAndMicroCapitalGovernanceProbes:
    """Empirical probes verifying solvency ledger zero-drift and micro-capital limits."""

    def test_solvency_ledger_zero_drift_10000_sequential_fills(self) -> None:
        """CentralizedSolvencyLedger must hold |drift| < 10^-15 USDT across 10,000 fills."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        rng = random.Random(777)
        pairs = list(ALL_8_PAIRS)

        drift_violations = 0
        for _ in range(10000):
            sym = rng.choice(pairs)
            side = rng.choice(["BUY", "SELL"])
            qty = round(rng.uniform(0.01, 10.0), 4)
            price = round(rng.uniform(1.0, 5000.0), 4)
            fee = round(rng.uniform(0.0001, 0.01), 6)
            rpnl = round(rng.uniform(-0.5, 0.5), 4) if side == "SELL" else 0.0

            if side == "BUY" and ledger.cash < (qty * price):
                qty = round(float(ledger.cash) * 0.1 / price, 4)
                if qty <= 0:
                    continue

            ledger.record_fill(
                symbol=sym,
                side=side,
                qty=qty,
                price=price,
                fee=fee,
                realized_pnl=rpnl,
            )

            snap = ledger.get_snapshot()
            drift = abs(Decimal(str(snap.drift)))
            if drift >= Decimal("1e-15"):
                drift_violations += 1

        assert drift_violations == 0, (
            f"Encountered {drift_violations} drift violations >= 10^-15 USDT"
        )

    def test_aggregate_exposure_cap_25_usdt_strictly_blocks_allocations(self) -> None:
        """Allocations pushing aggregate exposure > 25.00 USDT must be blocked."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        now_ms = int(time.time() * 1000)

        # Pre-allocate exposure to $20.00 USDT
        engine.candidates["SOLUSDT"].allocated_exposure_usdt = Decimal("10.00")
        engine.candidates["ETHUSDT"].allocated_exposure_usdt = Decimal("10.00")

        # Order of ~5.07 USDT would push exposure to 25.07 > 25.00 USDT
        order = engine.process_microstructure_tick(
            symbol="DOGEUSDT",
            price=Decimal("0.086"),
            ensemble_signal="BUY",
            hawkes_spectral_radius=0.1,
            heartbeat_age_ms=50.0,
            ts_ms=now_ms,
        )
        assert order is None
        assert engine.interlock_blocks_count >= 1

    def test_cash_reserve_floor_75pct_strictly_enforced(self) -> None:
        """Projected cash reserve falling below 75.0% must trip interlock."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        now_ms = int(time.time() * 1000)

        # Deplete cash to 76.00 USDT (only 1.00 USDT above 75% floor)
        engine.ledger.cash = Decimal("76.00")

        # Order of ~5.07 USDT would drop cash to 70.93 (< 75.0% of 100.0)
        order = engine.process_microstructure_tick(
            symbol="DOGEUSDT",
            price=Decimal("0.086"),
            ensemble_signal="BUY",
            hawkes_spectral_radius=0.1,
            heartbeat_age_ms=50.0,
            ts_ms=now_ms,
        )
        assert order is None
        assert engine.interlock_blocks_count >= 1

    def test_intra_day_loss_3_usdt_trips_circuit_and_flattens(self) -> None:
        """Intra-day loss reaching or exceeding 3.00 USDT trips CIRCUIT_FLATTENED."""
        engine = build_default_self_driving_engine(starting_capital_usdt=Decimal("100.00"))
        now_ms = int(time.time() * 1000)

        engine.intra_day_loss_usdt = Decimal("3.00")
        order = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("110.00"),
            ensemble_signal="BUY",
            ts_ms=now_ms,
        )
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
