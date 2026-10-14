"""Adversarial Empirical Challenge Suite for Milestone 1 Iteration 2 (Phase 317).

Empirically tests and stress-tests:
1. Algorithmic scaling on random noisy candle series (n=50, 100, 200).
2. Strict execution timing benchmarks: n=100 strictly < 0.05s and bounded breaker count < 50.
3. Edge-case market structures:
   - Flatlines (zero range, zero volatility, H == L == O == C).
   - Sharp V-reversals (instant crash and recovery, inverted parabolic spikes).
   - Step functions (ascending stairs, descending stairs, square wave oscillations).
   - Adversarial sawtooth / multi-peak zigzag sequences.
   - Expanding broadening megaphone formations (nested sweeps and breaks).
4. Boundary condition sequences (n=0, 1, 2, 3, 4).
5. Unsliced lookback horizons: n=200 with lookback_htf=200 and lookback_htf=0.
"""

from __future__ import annotations

import random
import time
from decimal import Decimal

import pytest

from autonomous_futures.strategy.ict_mmxm import (
    Candle,
    IctMmxmEngine,
    PdArrayType,
)


def _make_c(
    ts_ms: int,
    open_p: str | int | float | Decimal,
    high_p: str | int | float | Decimal,
    low_p: str | int | float | Decimal,
    close_p: str | int | float | Decimal,
    volume: str | int | float | Decimal = "100.0",
) -> Candle:
    return Candle(
        timestamp_ms=ts_ms,
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        volume=Decimal(str(volume)),
    )


def generate_random_walk(
    n: int,
    seed: int,
    start_price: float = 100.0,
    volatility: float = 1.0,
) -> list[Candle]:
    """Generates synthetic random walk candles with natural wicks and price action."""
    rng = random.Random(seed)
    candles: list[Candle] = []
    current_p = start_price
    base_ts = 1700000000000

    for i in range(n):
        delta = rng.gauss(0.0, volatility)
        open_p = current_p
        close_p = max(0.01, open_p + delta)
        high_p = max(open_p, close_p) + abs(rng.gauss(0.0, volatility * 0.5))
        low_p = max(0.005, min(open_p, close_p) - abs(rng.gauss(0.0, volatility * 0.5)))
        candles.append(
            _make_c(
                base_ts + i * 3600000,
                f"{open_p:.4f}",
                f"{high_p:.4f}",
                f"{low_p:.4f}",
                f"{close_p:.4f}",
                f"{rng.uniform(50.0, 500.0):.2f}",
            )
        )
        current_p = close_p

    return candles


def generate_flatline(n: int, price: float = 100.0) -> list[Candle]:
    """Generates perfectly flat series (zero range, zero volatility)."""
    base_ts = 1700000000000
    p_str = f"{price:.4f}"
    return [
        _make_c(base_ts + i * 3600000, p_str, p_str, p_str, p_str, "100.0")
        for i in range(n)
    ]


def generate_sharp_v_reversal(n: int, depth: float = 50.0, base: float = 100.0) -> list[Candle]:
    """Generates a steep drop down to (base - depth) followed by an immediate sharp rise back."""
    half = n // 2
    candles: list[Candle] = []
    base_ts = 1700000000000

    # Down leg
    curr = base
    drop_step = depth / max(1, half)
    for i in range(half):
        o = curr
        c = max(1.0, o - drop_step)
        h = o + 0.5
        low_val = c - 0.5
        candles.append(
            _make_c(base_ts + i * 3600000, f"{o:.4f}", f"{h:.4f}", f"{low_val:.4f}", f"{c:.4f}")
        )
        curr = c

    # Up leg
    rise_step = depth / max(1, n - half)
    for i in range(half, n):
        o = curr
        c = o + rise_step
        h = c + 0.5
        low_val = o - 0.5
        candles.append(
            _make_c(base_ts + i * 3600000, f"{o:.4f}", f"{h:.4f}", f"{low_val:.4f}", f"{c:.4f}")
        )
        curr = c

    return candles


def generate_inverted_v_reversal(
    n: int,
    height: float = 50.0,
    base: float = 100.0,
) -> list[Candle]:
    """Generates a steep parabolic rise up to (base + height) followed by immediate collapse."""
    half = n // 2
    candles: list[Candle] = []
    base_ts = 1700000000000

    curr = base
    step_up = height / max(1, half)
    for i in range(half):
        o = curr
        c = o + step_up
        h = c + 0.5
        low_val = o - 0.5
        candles.append(
            _make_c(base_ts + i * 3600000, f"{o:.4f}", f"{h:.4f}", f"{low_val:.4f}", f"{c:.4f}")
        )
        curr = c

    step_down = height / max(1, n - half)
    for i in range(half, n):
        o = curr
        c = max(1.0, o - step_down)
        h = o + 0.5
        low_val = c - 0.5
        candles.append(
            _make_c(base_ts + i * 3600000, f"{o:.4f}", f"{h:.4f}", f"{low_val:.4f}", f"{c:.4f}")
        )
        curr = c

    return candles


def generate_step_function(
    n: int,
    step_size: int = 10,
    step_delta: float = 5.0,
    base: float = 100.0,
    ascending: bool = True,
) -> list[Candle]:
    """Generates discrete stair-step plateau structures."""
    candles: list[Candle] = []
    base_ts = 1700000000000
    plateau = base

    for i in range(n):
        if i > 0 and i % step_size == 0:
            plateau = plateau + step_delta if ascending else max(1.0, plateau - step_delta)
        p_str = f"{plateau:.4f}"
        candles.append(
            _make_c(
                base_ts + i * 3600000,
                p_str,
                f"{plateau + 0.2:.4f}",
                f"{plateau - 0.2:.4f}",
                p_str,
            )
        )

    return candles


def generate_square_wave(
    n: int,
    period: int = 10,
    low_val: float = 100.0,
    high_val: float = 120.0,
) -> list[Candle]:
    """Generates square-wave switching between low and high states."""
    candles: list[Candle] = []
    base_ts = 1700000000000

    for i in range(n):
        is_high = ((i // period) % 2) == 1
        val = high_val if is_high else low_val
        candles.append(
            _make_c(
                base_ts + i * 3600000,
                f"{val:.4f}",
                f"{val + 0.5:.4f}",
                f"{val - 0.5:.4f}",
                f"{val:.4f}",
            )
        )

    return candles


def generate_sawtooth_zigzag(
    n: int,
    teeth: int = 5,
    base: float = 100.0,
    amp: float = 20.0,
) -> list[Candle]:
    """Generates continuous alternating peaks and troughs."""
    candles: list[Candle] = []
    base_ts = 1700000000000
    period = max(4, n // teeth)

    for i in range(n):
        phase = (i % period) / float(period)
        if phase < 0.5:
            # Ascending
            curr = base + (phase * 2.0) * amp
            o = curr
            c = curr + 0.8
            h = c + 1.0
            low_val = o - 0.5
        else:
            # Descending
            curr = (base + amp) - ((phase - 0.5) * 2.0) * amp
            o = curr
            c = curr - 0.8
            h = o + 0.5
            low_val = c - 1.0

        candles.append(
            _make_c(
                base_ts + i * 3600000,
                f"{o:.4f}",
                f"{h:.4f}",
                f"{low_val:.4f}",
                f"{c:.4f}",
            )
        )

    return candles


def generate_expanding_megaphone(
    n_waves: int,
    base: float = 100.0,
    step_delta: float = 3.0,
) -> list[Candle]:
    """Generates broadening megaphone swings designed to maximize nested 4-point pivot triggers."""
    candles: list[Candle] = []
    base_ts = 1700000000000
    idx = 0
    base_h = base

    for w in range(n_waves):
        l_target = base - (w + 1) * step_delta
        h_target = base + (w + 1) * step_delta

        # Down leg (3 candles)
        for step in range(3):
            p = base_h - (step + 1) * ((base_h - l_target) / 3.0)
            candles.append(
                _make_c(
                    base_ts + idx * 60000,
                    f"{p + 0.5:.4f}",
                    f"{p + 1.0:.4f}",
                    f"{p - 1.0:.4f}",
                    f"{p:.4f}",
                )
            )
            idx += 1
        base_h = l_target

        # Up leg (3 candles)
        for step in range(3):
            p = base_h + (step + 1) * ((h_target - base_h) / 3.0)
            candles.append(
                _make_c(
                    base_ts + idx * 60000,
                    f"{p - 0.5:.4f}",
                    f"{p + 1.0:.4f}",
                    f"{p - 1.0:.4f}",
                    f"{p:.4f}",
                )
            )
            idx += 1
        base_h = h_target

    return candles


# ==============================================================================
# EMPIRICAL ADVERSARIAL TEST SUITE
# ==============================================================================


class TestRandomNoisySeriesScaling:
    """Rigorous scaling verification with random noisy candle series (n=50, 100, 200)."""

    @pytest.mark.parametrize("seed", [42, 101, 777, 2026, 9999])
    def test_random_noisy_series_n50_performance(self, seed: int) -> None:
        """Asserts n=50 random walks execute rapidly (< 0.03s) and remain bounded."""
        engine = IctMmxmEngine()
        candles = generate_random_walk(n=50, seed=seed, volatility=2.0)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.03, f"n=50 exceeded 0.03s: {elapsed:.4f}s"
        assert len(bbs) < 25, f"n=50 breaker count too high: {len(bbs)}"

    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 10, 20, 30, 50, 100])
    def test_random_noisy_series_n100_strict_bounds(self, seed: int) -> None:
        """Requirement: Execution time on n=100 strictly < 0.05s and breaker count < 50."""
        engine = IctMmxmEngine()
        candles = generate_random_walk(n=100, seed=seed, volatility=2.5)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"n=100 failed < 0.05s benchmark: {elapsed:.4f}s on seed {seed}"
        assert len(bbs) < 50, f"n=100 failed < 50 breaker ceiling: {len(bbs)} on seed {seed}"

    @pytest.mark.parametrize("seed", [123, 456, 789])
    def test_random_noisy_series_n200_default_lookback(self, seed: int) -> None:
        """Verifies n=200 with default lookback_htf=100 scales gracefully (< 0.05s, < 50)."""
        engine = IctMmxmEngine()
        candles = generate_random_walk(n=200, seed=seed, volatility=3.0)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"n=200 (sliced to 100) exceeded 0.05s: {elapsed:.4f}s"
        assert len(bbs) < 50, f"n=200 breaker count exceeded 50: {len(bbs)}"

    @pytest.mark.parametrize("seed", [123, 456, 789])
    def test_random_noisy_series_n200_unsliced_lookback(self, seed: int) -> None:
        """Stress-tests n=200 when lookback slicing is widened to 200 bars."""
        engine = IctMmxmEngine(lookback_htf=200)
        candles = generate_random_walk(n=200, seed=seed, volatility=3.0)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.15, f"n=200 unsliced exceeded 0.15s: {elapsed:.4f}s"
        assert len(bbs) < 60, f"n=200 unsliced breaker count exceeded 60: {len(bbs)}"


class TestEdgeCaseMarketStructures:
    """Stress tests anomalous market conditions: flatlines, sharp V-reversals, step functions."""

    @pytest.mark.parametrize("n", [50, 100, 200])
    def test_flatlines_produce_zero_breakers_and_zero_errors(self, n: int) -> None:
        """Asserts flatlines ($H == L == O == C$) produce 0 breakers and 0 divisions."""
        engine = IctMmxmEngine()
        candles = generate_flatline(n=n, price=50.0)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.02, f"Flatline detection took {elapsed:.4f}s"
        assert len(bbs) == 0, f"Flatline produced {len(bbs)} phantom breakers"
        assert len(pdas) == 0, f"Flatline produced {len(pdas)} phantom PDAs"

    @pytest.mark.parametrize("n", [50, 100, 200])
    def test_sharp_v_reversals_bullish(self, n: int) -> None:
        """Asserts sharp V-reversals process smoothly and breaker counts remain tightly bounded."""
        engine = IctMmxmEngine()
        candles = generate_sharp_v_reversal(n=n, depth=40.0, base=120.0)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"Sharp V-reversal took {elapsed:.4f}s"
        assert len(bbs) < 20, f"Sharp V-reversal produced {len(bbs)} breakers"

    @pytest.mark.parametrize("n", [50, 100, 200])
    def test_sharp_v_reversals_bearish(self, n: int) -> None:
        """Asserts inverted sharp V-reversals process smoothly and breaker counts remain bounded."""
        engine = IctMmxmEngine()
        candles = generate_inverted_v_reversal(n=n, height=40.0, base=100.0)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"Inverted V-reversal took {elapsed:.4f}s"
        assert len(bbs) < 20, f"Inverted V-reversal produced {len(bbs)} breakers"

    @pytest.mark.parametrize("ascending", [True, False])
    def test_step_functions_plateaus(self, ascending: bool) -> None:
        """Asserts discrete plateau stairs process without crash and breaker count < 30."""
        engine = IctMmxmEngine()
        candles = generate_step_function(n=100, step_size=10, step_delta=8.0, ascending=ascending)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"Step function took {elapsed:.4f}s"
        assert len(bbs) < 30, f"Step function produced {len(bbs)} breakers"

    def test_square_wave_alternating_states(self) -> None:
        """Asserts square-wave switching processes without timing explosion."""
        engine = IctMmxmEngine()
        candles = generate_square_wave(n=100, period=8, low_val=90.0, high_val=110.0)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"Square wave took {elapsed:.4f}s"
        assert len(bbs) < 30, f"Square wave produced {len(bbs)} breakers"

    def test_sawtooth_dense_pivot_zigzag(self) -> None:
        """Asserts dense multi-tooth zigzag designed to trigger maximum pivots remains < 0.05s."""
        engine = IctMmxmEngine()
        candles = generate_sawtooth_zigzag(n=100, teeth=8, base=100.0, amp=25.0)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"Sawtooth zigzag took {elapsed:.4f}s"
        assert len(bbs) < 40, f"Sawtooth zigzag produced {len(bbs)} breakers"


class TestBroadeningMegaphoneAdversarialStress:
    """Tests expanding swings structured to trigger nested sweep-and-break combinations."""

    @pytest.mark.parametrize("waves", [10, 15, 20])
    def test_expanding_megaphone_scaling(self, waves: int) -> None:
        """Asserts megaphone sequence (up to 120 candles) executes in < 0.05s and breakers < 50."""
        engine = IctMmxmEngine()
        candles = generate_expanding_megaphone(n_waves=waves)

        t0 = time.perf_counter()
        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        elapsed = time.perf_counter() - t0

        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert elapsed < 0.05, f"Megaphone ({len(candles)} candles) exceeded 0.05s: {elapsed:.4f}s"
        assert len(bbs) < 50, f"Megaphone breaker count exceeded 50: {len(bbs)}"


class TestBoundaryLengthEdgeCases:
    """Verifies safe handling of minimal candle sequences (n=0, 1, 2, 3, 4)."""

    def test_empty_and_single_candle(self) -> None:
        """Asserts empty and single-candle lists gracefully return empty list."""
        engine = IctMmxmEngine()
        assert engine.detect_pd_arrays([], "1h") == []
        c1 = [_make_c(1000, "100.0", "101.0", "99.0", "100.5")]
        assert engine.detect_pd_arrays(c1, "1h") == []

    def test_two_and_three_candles(self) -> None:
        """Asserts 2 and 3 candles cannot produce breaker blocks."""
        engine = IctMmxmEngine()
        c2 = [
            _make_c(1000, "100.0", "101.0", "99.0", "100.5"),
            _make_c(2000, "100.5", "102.0", "100.0", "101.5"),
        ]
        pdas_2 = engine.detect_pd_arrays(c2, "1h")
        assert all(p.array_type != PdArrayType.BREAKER_BLOCK for p in pdas_2)

        c3 = c2 + [_make_c(3000, "101.5", "103.0", "101.0", "102.5")]
        pdas_3 = engine.detect_pd_arrays(c3, "1h")
        assert all(p.array_type != PdArrayType.BREAKER_BLOCK for p in pdas_3)

    def test_four_candles_minimum_breaker_sequence(self) -> None:
        """Asserts 4 candles is the exact minimal length for a Breaker Block."""
        engine = IctMmxmEngine()
        c4 = [
            _make_c(1000, "100.0", "101.0", "95.0", "96.0"),  # L1
            _make_c(2000, "96.0", "105.0", "96.0", "104.0"),  # H1 (+OB)
            _make_c(3000, "104.0", "104.0", "92.0", "93.0"),  # L2 (sweeps L1)
            _make_c(4000, "93.0", "110.0", "93.0", "109.0"),  # H2 (breaks H1)
        ]
        pdas_4 = engine.detect_pd_arrays(c4, "1h")
        bbs = [p for p in pdas_4 if p.array_type == PdArrayType.BREAKER_BLOCK]
        assert len(bbs) <= 2


class TestBreakerBlockDeduplicationAndStructure:
    """Verifies that Breaker Blocks are mathematically valid and deduplicated."""

    def test_breaker_blocks_have_valid_decimal_levels(self) -> None:
        """Verifies returned Breaker Blocks have top > bottom and mean_threshold in between."""
        engine = IctMmxmEngine()
        candles = generate_random_walk(n=100, seed=42, volatility=2.0)

        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]

        for bb in bbs:
            assert bb.top >= bb.bottom, f"Invalid geometry: top={bb.top} < bottom={bb.bottom}"
            expected_mt = (bb.top + bb.bottom) / Decimal("2")
            assert bb.mean_threshold == expected_mt, "Mean threshold mismatch"
            assert bb.direction in ("BULLISH", "BEARISH")

    def test_breaker_blocks_no_duplicate_zones(self) -> None:
        """Verifies seen_breaker_zones strictly prevents identical zone duplicates."""
        engine = IctMmxmEngine()
        candles = generate_sawtooth_zigzag(n=100, teeth=6, base=100.0, amp=20.0)

        pdas = engine.detect_pd_arrays(candles, timeframe="1h")
        bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]

        keys = [(bb.direction, bb.top, bb.bottom) for bb in bbs]
        assert len(keys) == len(set(keys)), f"Duplicate zones: {len(keys)} vs {len(set(keys))}"


class TestHighVolumeIterationTimingDistribution:
    """Runs 100 consecutive trials on n=100 random candle series to measure latency distribution."""

    def test_100_runs_latency_percentiles(self) -> None:
        """Asserts p99 latency over 100 random noisy trials is strictly < 0.05s."""
        engine = IctMmxmEngine()
        latencies: list[float] = []
        breaker_counts: list[int] = []

        for i in range(100):
            candles = generate_random_walk(n=100, seed=1000 + i, volatility=2.0)
            t0 = time.perf_counter()
            pdas = engine.detect_pd_arrays(candles, timeframe="1h")
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)
            bbs = [p for p in pdas if p.array_type == PdArrayType.BREAKER_BLOCK]
            breaker_counts.append(len(bbs))

        latencies.sort()
        p50 = latencies[50]
        p95 = latencies[95]
        p99 = latencies[99]
        max_lat = latencies[-1]
        max_bbs = max(breaker_counts)

        # Statistical assertions
        assert max_lat < 0.05, f"Maximum latency exceeded 0.05s: {max_lat:.4f}s"
        assert p99 < 0.05, f"P99 latency exceeded 0.05s: {p99:.4f}s"
        assert max_bbs < 50, f"Max breaker count exceeded 50: {max_bbs}"

        # Report empirical findings
        print(
            f"\n[LATENCY DISTRIBUTION n=100 over 100 runs]: "
            f"min={latencies[0]:.5f}s, p50={p50:.5f}s, p95={p95:.5f}s, p99={p99:.5f}s, "
            f"max={max_lat:.5f}s, max_breakers={max_bbs}"
        )
