import random
from decimal import Decimal as D

import pytest

from autonomous_futures.research.ict_touch_index import (
    touched_pd_arrays as research_touched_pd_arrays,
)
from autonomous_futures.strategy.ict_mmxm import Candle, PdArray
from autonomous_futures.strategy.pd_array_touch_index import touched_pd_arrays


def candle(timestamp: int, low: str, high: str) -> Candle:
    return Candle(timestamp, D(low), D(high), D(low), D(high), D("1"))


def pda(bottom: str, top: str, known_from: int | None) -> PdArray:
    return PdArray(
        "FVG_BISI",
        "1h",
        D(top),
        D(bottom),
        (D(top) + D(bottom)) / 2,
        "BULLISH",
        0,
        False,
        known_from,
    )


def brute_force(pdas: list[PdArray], candles: list[Candle]) -> tuple[bool, ...]:
    return tuple(
        any(
            (pda_.known_from_ms is None or candle_.timestamp_ms >= pda_.known_from_ms)
            and candle_.high >= pda_.bottom
            and candle_.low <= pda_.top
            for candle_ in candles
        )
        for pda_ in pdas
    )


def test_research_import_reexports_strategy_implementation():
    assert research_touched_pd_arrays is touched_pd_arrays


def test_preserves_candle_interval_overlap_without_false_global_range_hits():
    candles = [candle(0, "12", "13"), candle(60_000, "8", "9")]
    pdas = [pda("10", "11", None)]

    assert touched_pd_arrays(pdas, candles) == (False,)
    assert touched_pd_arrays([pda("8.5", "12.5", None)], candles) == (True,)


def test_known_from_boundary_is_inclusive_and_excludes_earlier_touches():
    candles = [candle(0, "9", "10"), candle(60_000, "12", "13")]
    pdas = [pda("9.5", "10.5", 60_000), pda("12", "12.5", 60_000)]

    assert touched_pd_arrays(pdas, candles) == (False, True)


def test_index_matches_brute_force_for_deterministic_random_intervals():
    rng = random.Random(317)
    candles = []
    for index in range(250):
        low = rng.randrange(50, 151)
        high = low + rng.randrange(1, 20)
        candles.append(candle(index * 60_000, str(low), str(high)))
    pdas = []
    for _index in range(400):
        left = rng.randrange(40, 170)
        right = left + rng.randrange(0, 15)
        known = rng.choice([None, rng.randrange(0, 250) * 60_000, 300 * 60_000])
        pdas.append(pda(str(left), str(right), known))

    assert touched_pd_arrays(pdas, candles) == brute_force(pdas, candles)


def test_empty_inputs_and_out_of_order_candles():
    assert touched_pd_arrays([], [candle(0, "1", "2")]) == ()
    assert touched_pd_arrays([pda("1", "2", None)], []) == (False,)
    with pytest.raises(ValueError, match="timestamp ordered"):
        touched_pd_arrays([pda("1", "2", None)], [candle(60_000, "1", "2"), candle(0, "1", "2")])
