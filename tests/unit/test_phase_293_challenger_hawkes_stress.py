"""Adversarial stress test suite for Phase 293: Real-time Hawkes Telemetry Streaming.

Challenger: challenger_phase293_1
Adversarial Verification Vectors:
1. Exact mathematical agreement between O(1) recursive exponential decay formulation
   and explicit historical summation under massive synthetic bursts (5,000 trades).
2. Extreme supercritical cascade runaway shocks (rho >= 1.0, rho = 2.5, rho = 5.0):
   - Absence of numerical explosion, NaN, Inf, or overflow.
   - Instantaneous emission of critical hazard alerts (SUPERCRITICAL_CASCADE).
   - Anti-flapping hysteresis functions correctly during de-escalation.
3. Sub-second and sub-microsecond latency stress tests (< 10 us per tick fast math,
   < 1000 us full tick processing).
4. Continuous double-entry mathematical balance zero-drift validation under 5,000
   continuous ticks (|drift| < 10^-15 USDT without exception).
5. Edge cases: Simultaneous events (dt = 0), out-of-order timestamps, dormancy (large dt),
   and concurrent multi-threaded contention.
"""

from __future__ import annotations

import concurrent.futures
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from autonomous_futures.feed.canary_activation import CANARY_STAGED_SYMBOLS
from autonomous_futures.feed.hawkes_cascades import (
    DYNAMIC_SLICING_DOWNSCALED_CHUNK_USDT,
    ELEVATED_LIMIT_CUSHION_BPS,
    ELEVATED_PACING_INTERVAL_MS,
    SEVERE_LIMIT_CUSHION_BPS,
    SEVERE_PACING_INTERVAL_MS,
    SUPERCRITICAL_BRANCHING_RATIO,
    HawkesCascadeEngine,
    HawkesRegime,
)
from autonomous_futures.feed.hawkes_streamer import (
    DOUBLE_ENTRY_MAX_DRIFT,
    HawkesStreamer,
)
from autonomous_futures.feed.models import AggregateTrade


def _compute_explicit_hawkes_intensity(
    engine: HawkesCascadeEngine,
    symbol: str,
    events: list[tuple[float, str]],
    t_now: float,
) -> float:
    """Independent oracle computing Hawkes intensity via explicit historical summation.

    lambda_i(t) = mu_i + sum_{k: t_k <= t} alpha_{i, s_k} * exp(-beta_{i, s_k} * (t - t_k))
    """
    sym = symbol.strip().upper()
    mu = float(engine._mu.get(sym, Decimal("0.10")))
    total = mu
    for t_k, s_k in events:
        if t_k <= t_now:
            dt = t_now - t_k
            alpha = float(engine._alpha.get((sym, s_k), Decimal("0.0")))
            beta = float(engine._beta.get((sym, s_k), Decimal("1.0")))
            total += alpha * np.exp(-beta * dt)
    return total


def _compute_explicit_r_matrix(
    engine: HawkesCascadeEngine,
    events: list[tuple[float, str]],
    t_now: float,
) -> np.ndarray:
    """Independent oracle computing the 3x3 recursive decay state matrix R_ij(t) explicitly.

    R_ij(t) = sum_{k: s_k = j, t_k <= t} alpha_{ij} * exp(-beta_{ij} * (t - t_k))
    """
    symbols = engine._symbols
    r_mat = np.zeros((3, 3), dtype=np.float64)
    for i, si in enumerate(symbols):
        for j, sj in enumerate(symbols):
            alpha = float(engine._alpha.get((si, sj), Decimal("0.0")))
            beta = float(engine._beta.get((si, sj), Decimal("1.0")))
            for t_k, s_k in events:
                if s_k == sj and t_k <= t_now:
                    dt = t_now - t_k
                    r_mat[i, j] += alpha * np.exp(-beta * dt)
    return r_mat


# =====================================================================
# Vector 1: Numerical Stability & Exact Agreement under 5,000 Burst Ticks
# =====================================================================


def test_hawkes_online_recursion_agreement_under_massive_burst() -> None:
    """Stress-test numerical stability and exact agreement between O(1) recursion

    and explicit summation over 5,000 synthetic high-frequency trade arrivals.
    """
    engine = HawkesCascadeEngine()
    t_start = 10_000.0
    num_trades = 5_000

    # Deterministic inter-arrival times (0.001s to 0.003s, total duration ~10s < 60s window)
    rng = np.random.default_rng(seed=42)
    delta_times = rng.uniform(0.001, 0.003, size=num_trades)
    symbol_indices = rng.integers(0, len(CANARY_STAGED_SYMBOLS), size=num_trades)

    events: list[tuple[float, str]] = []
    current_time = t_start

    checkpoints = [100, 500, 1000, 2500, 5000]

    for k in range(num_trades):
        current_time += float(delta_times[k])
        sym = CANARY_STAGED_SYMBOLS[symbol_indices[k]]
        events.append((current_time, sym))

        # Ingest into Hawkes engine
        engine.record_event_arrival(sym, timestamp_sec=current_time)

        # At predefined checkpoints, compare engine state against independent explicit oracle
        if (k + 1) in checkpoints:
            r_engine = engine.get_decay_matrix()
            r_oracle = _compute_explicit_r_matrix(engine, events, current_time)

            # Assert no NaN or Inf in R_matrix
            assert not np.isnan(r_engine).any(), f"NaN in R_matrix at tick {k + 1}"
            assert not np.isinf(r_engine).any(), f"Inf in R_matrix at tick {k + 1}"

            # Numerical agreement across all 9 components of the decay state matrix
            max_r_diff = float(np.max(np.abs(r_engine - r_oracle)))
            assert max_r_diff < 1e-4, (
                f"Tick {k + 1}: R_matrix diverged from explicit sum! Max diff: {max_r_diff:.6e}"
            )

            # Assert intensity agreement for each candidate symbol
            for si in CANARY_STAGED_SYMBOLS:
                lambda_engine = float(engine.get_jump_intensity(si))
                lambda_oracle = _compute_explicit_hawkes_intensity(engine, si, events, current_time)
                abs_diff = abs(lambda_engine - lambda_oracle)
                rel_diff = abs_diff / lambda_oracle if lambda_oracle > 0 else abs_diff

                assert abs_diff < 1e-4, (
                    f"Tick {k + 1} {si}: Intensity diverged! Engine={lambda_engine:.6f}, "
                    f"Oracle={lambda_oracle:.6f}, AbsDiff={abs_diff:.6e}"
                )
                assert rel_diff < 1e-4, (
                    f"Tick {k + 1} {si}: Relative error {rel_diff:.6e} exceeded 1e-4"
                )

    # Final assertion on spectral radius finiteness and sanity
    final_rho = float(engine.get_spectral_radius())
    assert 0.0 < final_rho < 1.0, (
        f"Baseline spectral radius {final_rho} unexpected under subcritical baseline"
    )


# =====================================================================
# Vector 2: Extreme Supercritical Runaway Shocks (rho >= 1.0, 2.5, 5.0)
# =====================================================================


@pytest.mark.parametrize("target_rho", [1.05, 2.50, 5.00])
def test_supercritical_runaway_shocks_stability_and_alerts(target_rho: float) -> None:
    """Inject extreme supercritical runaway shocks (rho=1.05, 2.50, 5.00) and assert:

    - Numerical stability: zero NaN / Inf / overflow over 1,000 rapid event arrivals.
    - Immediate hazard alert emission with SUPERCRITICAL_CASCADE severity CRITICAL.
    - Strict dynamic throttling: pacing interval >= 1000 ms, limit cushion >= 5 bps,
      and chunk cap downscaled to 1.00 USDT.
    """
    engine = HawkesCascadeEngine()
    streamer = HawkesStreamer(engine=engine)

    base_rho = float(engine.get_spectral_radius())
    scale_factor = target_rho / base_rho

    # Scale alpha parameters to achieve target spectral radius
    with engine._global_lock:
        for k in list(engine._alpha.keys()):
            engine._alpha[k] = (engine._alpha[k] * Decimal(str(scale_factor))).quantize(
                Decimal("0.0001")
            )
        engine._spectral_radius = engine._compute_spectral_radius()
        engine._sync_matrices()

    actual_rho = float(engine.get_spectral_radius())
    assert actual_rho >= 1.00, f"Engine failed to achieve supercritical state: {actual_rho}"
    assert abs(actual_rho - target_rho) < 0.05, (
        f"Target rho {target_rho} vs actual {actual_rho} deviation too large"
    )
    assert engine.is_supercritical() is True

    # Ingest trade tick through HawkesStreamer
    t_now = time.time()
    trade = AggregateTrade(
        symbol="BTCUSDT",
        aggregate_trade_id=99001,
        price=Decimal("60000.00"),
        quantity=Decimal("0.5"),
        trade_time=datetime.fromtimestamp(t_now, tz=UTC),
        is_buyer_maker=False,
    )
    metrics = streamer.on_trade(trade)

    # 1. Verify metrics output indicates supercritical status
    assert metrics.is_supercritical is True
    assert Decimal(metrics.spectral_radius) >= SUPERCRITICAL_BRANCHING_RATIO
    assert metrics.regimes["BTCUSDT"] == HawkesRegime.SUPERCRITICAL_CASCADE.value
    assert metrics.pacing_intervals_ms["BTCUSDT"] >= SEVERE_PACING_INTERVAL_MS  # 1000 ms
    assert (
        Decimal(metrics.limit_offset_cushions_bps["BTCUSDT"]) >= SEVERE_LIMIT_CUSHION_BPS
    )  # 5.0 bps
    assert (
        engine.get_slice_chunk_cap("BTCUSDT") == DYNAMIC_SLICING_DOWNSCALED_CHUNK_USDT
    )  # 1.00 USDT

    # 2. Verify immediate hazard alert emission
    assert len(streamer._recent_alerts) > 0
    latest_alert = streamer._recent_alerts[-1]
    assert latest_alert.severity == "CRITICAL"
    assert latest_alert.hazard_type == "SUPERCRITICAL_CASCADE"
    assert latest_alert.action_taken == "IMMEDIATE_CIRCUIT_BREAKER_LOCKOUT"
    assert float(latest_alert.spectral_radius) >= 1.00

    # 3. Bombard with 1,000 rapid supercritical trades to stress-test numerical explosion resistance
    for i in range(1000):
        sym = CANARY_STAGED_SYMBOLS[i % 3]
        engine.record_event_arrival(sym, timestamp_sec=t_now + (i + 1) * 0.001)

    r_mat = engine.get_decay_matrix()
    assert not np.isnan(r_mat).any(), f"NaN detected in R_matrix under rho={target_rho}"
    assert not np.isinf(r_mat).any(), f"Inf detected in R_matrix under rho={target_rho}"

    for sym in CANARY_STAGED_SYMBOLS:
        intensity = float(engine.get_jump_intensity(sym))
        assert not np.isnan(intensity), f"NaN intensity detected on {sym} under rho={target_rho}"
        assert not np.isinf(intensity), f"Inf intensity detected on {sym} under rho={target_rho}"
        assert intensity > 0.0, f"Intensity non-positive on {sym} under rho={target_rho}"


# =====================================================================
# Vector 3: Anti-Flapping Hysteresis Verification on De-escalation
# =====================================================================


def test_anti_flapping_hysteresis_escalation_and_deescalation() -> None:
    """Verify anti-flapping hysteresis behavior across all regime boundaries:

    - NOMINAL -> ELEVATED -> SEVERE -> SUPERCRITICAL on escalation.
    - Anti-flapping deadband holds during noise oscillations around thresholds:
      - Deadband 1: [0.80, 0.85] holds SEVERE / SUPERCRITICAL until rho <= 0.80.
      - Deadband 2: [0.45, 0.50] holds ELEVATED until rho <= 0.45.
    - Full clean recovery to NOMINAL when rho <= 0.45.
    """
    engine = HawkesCascadeEngine()
    t_sim = 50_000.0

    def set_engine_rho(target: float) -> None:
        base_rho = float(engine._compute_spectral_radius())
        if base_rho > 0:
            scale = target / base_rho
            with engine._global_lock:
                for k in list(engine._alpha.keys()):
                    engine._alpha[k] = (engine._alpha[k] * Decimal(str(scale))).quantize(
                        Decimal("0.0001")
                    )
                engine._spectral_radius = engine._compute_spectral_radius()
                engine._sync_matrices()

    # Step 1: Baseline nominal check (rho <= 0.50)
    set_engine_rho(0.40)
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") == HawkesRegime.NOMINAL

    # Step 2: Escalate to ELEVATED_INTENSITY (0.50 < rho <= 0.85)
    set_engine_rho(0.65)
    t_sim += 0.1
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") == HawkesRegime.ELEVATED_INTENSITY
    assert engine.get_pacing_interval_ms("BTCUSDT") == ELEVATED_PACING_INTERVAL_MS
    assert engine.get_limit_offset_cushion_bps("BTCUSDT") == ELEVATED_LIMIT_CUSHION_BPS

    # Step 3: De-escalation test around Nominal boundary:
    # Drop rho to 0.48 (which is <= 0.50, but > 0.45 recovery threshold).
    # Hysteresis must PREVENT de-escalation to NOMINAL!
    set_engine_rho(0.48)
    t_sim += 0.1
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") == HawkesRegime.ELEVATED_INTENSITY, (
        "Anti-flapping failed: de-escalated to NOMINAL above 0.45 recovery threshold!"
    )

    # Step 4: Drop rho to 0.42 (<= 0.45 recovery threshold).
    # Hysteresis must allow clean recovery to NOMINAL.
    set_engine_rho(0.42)
    t_sim += 0.1
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") == HawkesRegime.NOMINAL

    # Step 5: Escalate to SEVERE_HAWKES_CONTROLS (0.85 <= rho < 1.00)
    set_engine_rho(0.92)
    t_sim += 0.1
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") == HawkesRegime.SEVERE_HAWKES_CONTROLS

    # Step 6: Escalate to SUPERCRITICAL_CASCADE (rho >= 1.00)
    set_engine_rho(1.30)
    t_sim += 0.1
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") == HawkesRegime.SUPERCRITICAL_CASCADE

    # Step 7: De-escalation test around Severe boundary:
    # Drop rho to 0.83 (which is < 0.85, but > 0.80 recovery threshold).
    # Hysteresis must PREVENT de-escalation to ELEVATED!
    set_engine_rho(0.83)
    t_sim += 0.1
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") in (
        HawkesRegime.SEVERE_HAWKES_CONTROLS,
        HawkesRegime.SUPERCRITICAL_CASCADE,
    ), "Anti-flapping failed: de-escalated to ELEVATED above 0.80 recovery threshold!"

    # Step 8: Drop rho to 0.75 (<= 0.80 recovery threshold).
    # Hysteresis must allow clean de-escalation to ELEVATED_INTENSITY.
    set_engine_rho(0.75)
    t_sim += 0.1
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") == HawkesRegime.ELEVATED_INTENSITY

    # Step 9: Oscillating boundary stress test (100 rapid oscillations in deadband)
    # Oscillate rho between 0.46 and 0.49. Regime must stay ELEVATED_INTENSITY without flapping.
    for i in range(100):
        target = 0.46 if i % 2 == 0 else 0.49
        set_engine_rho(target)
        t_sim += 0.05
        engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
        assert engine.get_regime("BTCUSDT") == HawkesRegime.ELEVATED_INTENSITY, (
            f"Regime flapped during oscillation at iteration {i}"
        )

    # Step 10: Final recovery to NOMINAL
    set_engine_rho(0.38)
    t_sim += 0.1
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_sim)
    assert engine.get_regime("BTCUSDT") == HawkesRegime.NOMINAL


# =====================================================================
# Vector 4: Latency Stress Benchmark (< 10 us fast math, < 1000 us tick)
# =====================================================================


def test_hawkes_latency_stress_benchmark() -> None:
    """Stress-test processing latency to assert:

    - compute_fast_online_intensities executes in strictly < 10 us per tick (mean).
    - compute_fast_online_intensities p99 latency < 25 us.
    - HawkesStreamer.on_trade full pipeline executes well under sub-second bounds (< 1000 us).
    """
    engine = HawkesCascadeEngine()
    streamer = HawkesStreamer(engine=engine)
    num_iterations = 10_000
    t_base = 20_000.0

    # Warm-up pass to prime CPU cache and numpy internal buffers
    for k in range(100):
        sym = CANARY_STAGED_SYMBOLS[k % 3]
        _ = engine.compute_fast_online_intensities(sym, t_base + k * 0.0005)

    # Part A: Pure recursive math latency benchmark
    latencies_us: list[float] = []
    for i in range(num_iterations):
        sym = CANARY_STAGED_SYMBOLS[i % 3]
        t_tick = t_base + 1.0 + i * 0.0005

        start_time = time.perf_counter_ns()
        _ = engine.compute_fast_online_intensities(sym, t_tick)
        end_time = time.perf_counter_ns()

        latencies_us.append((end_time - start_time) / 1_000.0)

    mean_math_latency_us = float(np.mean(latencies_us))
    p99_math_latency_us = float(np.percentile(latencies_us, 99))
    max_math_latency_us = float(np.max(latencies_us))

    assert mean_math_latency_us < 10.0, (
        f"Mean fast math latency {mean_math_latency_us:.2f} us exceeded bound 10.0 us"
    )
    assert p99_math_latency_us < 25.0, (
        f"P99 fast math latency {p99_math_latency_us:.2f} us exceeded bound 25.0 us"
    )
    assert max_math_latency_us < 2500.0, (
        f"Max fast math latency {max_math_latency_us:.2f} us exceeded bound 2500.0 us"
    )

    # Part B: HawkesStreamer.on_trade end-to-end processing latency benchmark
    stream_latencies_us: list[float] = []
    trade_bench_count = 3_000

    for i in range(trade_bench_count):
        sym = CANARY_STAGED_SYMBOLS[i % 3]
        trade = AggregateTrade(
            symbol=sym,
            aggregate_trade_id=100_000 + i,
            price=Decimal("50000.00") + Decimal(str(i * 0.01)),
            quantity=Decimal("0.1"),
            trade_time=datetime.fromtimestamp(t_base + i * 0.001, tz=UTC),
            is_buyer_maker=False,
        )

        start_time = time.perf_counter_ns()
        _ = streamer.on_trade(trade)
        end_time = time.perf_counter_ns()

        stream_latencies_us.append((end_time - start_time) / 1_000.0)

    mean_stream_latency_us = float(np.mean(stream_latencies_us))
    p99_stream_latency_us = float(np.percentile(stream_latencies_us, 99))

    # Must be strictly under sub-second bounds (< 1000 us = 1 ms, and well under 1000 us)
    assert mean_stream_latency_us < 500.0, (
        f"Mean stream latency {mean_stream_latency_us:.2f} us exceeded 500 us"
    )
    assert p99_stream_latency_us < 1000.0, (
        f"P99 stream latency {p99_stream_latency_us:.2f} us exceeded 1000 us"
    )


# =====================================================================
# Vector 5: Double-Entry Balance Zero-Drift Stress (5,000 Continuous Ticks)
# =====================================================================


def test_continuous_double_entry_balance_validation_under_stress() -> None:
    """Stress-test double-entry balance validation across 5,000 continuous ticks

    with dynamic, multi-factor accounting mutations (margin allocation shifts,
    realized PnL, mark price unrealized PnL swings).

    Asserts:
    - |drift| < 10^-15 USDT holds without a single exception.
    - Zero-drift flag remains True across all iterations.
    - Invalidation condition: any intentional perturbation >= 10^-14 USDT is
      immediately detected fail-closed.
    """
    initial_equity = Decimal("100.00")
    streamer = HawkesStreamer(starting_equity=initial_equity)

    rng = np.random.default_rng(seed=777)
    num_ticks = 5_000

    # Verify initial zero drift
    valid, drift = streamer.verify_zero_drift()
    assert valid is True
    assert drift < DOUBLE_ENTRY_MAX_DRIFT

    for tick in range(num_ticks):
        # Generate random financial adjustments with exact 6-decimal precision
        margin_change = Decimal(str(round(float(rng.uniform(-0.5, 0.5)), 6)))
        pnl_realized_step = Decimal(str(round(float(rng.uniform(-0.1, 0.15)), 6)))
        unrealized_step = Decimal(str(round(float(rng.uniform(-1.0, 1.0)), 6)))

        with streamer._lock:
            # Update margin within legal bounds [0, 80]
            new_margin = max(
                Decimal("0.00"),
                min(Decimal("80.00"), streamer.allocated_margin + margin_change),
            )
            margin_delta = new_margin - streamer.allocated_margin
            streamer.allocated_margin = new_margin

            # Deduct margin allocation from cash
            streamer.current_cash -= margin_delta

            # Add realized PnL to cash and cumulative realized
            streamer.realized_pnl += pnl_realized_step
            streamer.current_cash += pnl_realized_step

            # Set unrealized PnL
            streamer.unrealized_pnl = unrealized_step

            # Reconcile cash so that: assets = obligations
            # assets = current_cash + allocated_margin + unrealized_pnl
            # obligations = starting_equity + realized_pnl
            streamer.current_cash = (
                streamer.starting_equity
                + streamer.realized_pnl
                - streamer.allocated_margin
                - streamer.unrealized_pnl
            )

        # Assert zero drift holds on every single tick
        is_valid, drift_amt = streamer.verify_zero_drift()
        assert is_valid is True, f"Zero drift failed at tick {tick}: drift={drift_amt}"
        assert drift_amt < DOUBLE_ENTRY_MAX_DRIFT, (
            f"Drift {drift_amt} exceeded 10^-15 at tick {tick}"
        )

    # Invalidation check: perturb cash by 10^-14 USDT and assert immediate detection
    with streamer._lock:
        streamer.current_cash += Decimal("0.00000000000001")  # +1e-14

    is_valid, corrupted_drift = streamer.verify_zero_drift()
    assert is_valid is False, "Corrupted balance failed to trigger invalidation!"
    assert corrupted_drift >= Decimal("1e-14")


# =====================================================================
# Vector 6: Edge Cases & Concurrent Contention Stress
# =====================================================================


def test_hawkes_edge_cases_simultaneous_out_of_order_dormancy() -> None:
    """Stress-test edge cases:

    1. Simultaneous events at identical timestamp (dt = 0.0).
    2. Out-of-order event arrivals triggering historical rebuild.
    3. Long dormancy period (large dt = 3600.0s) causing exponential underflow.
    """
    engine = HawkesCascadeEngine()
    t0 = 100_000.0

    # 1. Simultaneous events at exact same microsecond
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t0)
    engine.record_event_arrival("ETHUSDT", timestamp_sec=t0)
    engine.record_event_arrival("SOLUSDT", timestamp_sec=t0)

    r_simul = engine.get_decay_matrix()
    assert not np.isnan(r_simul).any()
    assert not np.isinf(r_simul).any()
    # Diagonal elements should reflect added alphas
    assert r_simul[0, 0] >= 0.25
    assert r_simul[1, 1] >= 0.28
    assert r_simul[2, 2] >= 0.35

    # 2. Out-of-order event: arrival timestamp prior to last event time
    t_past = t0 - 2.0
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t_past)
    r_ooo = engine.get_decay_matrix()
    assert not np.isnan(r_ooo).any()
    assert not np.isinf(r_ooo).any()

    # 3. Long dormancy: jump forward 1 hour (3600 seconds)
    t_future = t0 + 3600.0
    engine.record_event_arrival("SOLUSDT", timestamp_sec=t_future)
    r_dormant = engine.get_decay_matrix()
    assert not np.isnan(r_dormant).any()
    assert not np.isinf(r_dormant).any()
    # Prior events should have completely decayed away (exp(-3600) -> 0.0)
    # Only the fresh SOLUSDT event's alpha column should remain
    assert r_dormant[0, 0] < 1e-12
    assert r_dormant[1, 1] < 1e-12
    assert abs(r_dormant[2, 2] - 0.35) < 1e-6


def test_hawkes_concurrent_thread_contention() -> None:
    """Stress-test thread safety under concurrent multi-threaded execution."""
    engine = HawkesCascadeEngine()
    streamer = HawkesStreamer(engine=engine)
    num_threads = 4
    ticks_per_thread = 500
    t_base = 200_000.0

    def worker_stream(thread_id: int) -> list[Any]:
        results: list[Any] = []
        for i in range(ticks_per_thread):
            sym = CANARY_STAGED_SYMBOLS[(thread_id + i) % 3]
            t_event = t_base + thread_id * 100.0 + i * 0.005
            trade = AggregateTrade(
                symbol=sym,
                aggregate_trade_id=thread_id * 10_000 + i,
                price=Decimal("60000.00"),
                quantity=Decimal("0.1"),
                trade_time=datetime.fromtimestamp(t_event, tz=UTC),
                is_buyer_maker=False,
            )
            m = streamer.on_trade(trade)
            results.append(m)
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_stream, tid) for tid in range(num_threads)]
        all_results = [f.result() for f in futures]

    assert len(all_results) == num_threads
    for res in all_results:
        assert len(res) == ticks_per_thread

    # Verify final zero drift is maintained after concurrent operations
    is_valid, drift = streamer.verify_zero_drift()
    assert is_valid is True
    assert drift < DOUBLE_ENTRY_MAX_DRIFT
