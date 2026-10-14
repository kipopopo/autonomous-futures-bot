from decimal import Decimal as D

from autonomous_futures.strategy.ict_mmxm import Candle, IctMmxmEngine, PdArrayType


def candle(ts, open_, high, low, close):
    return Candle(ts, D(open_), D(high), D(low), D(close), D("10"))


def test_order_block_is_known_after_displacement_close_not_origin():
    bars = [candle(0, "10", "11", "8", "9"), candle(3600000, "9", "13", "9", "12")]
    arrays = IctMmxmEngine().detect_pd_arrays(bars, "1h")
    block = next(pda for pda in arrays if pda.array_type == PdArrayType.ORDER_BLOCK)
    assert block.creation_ts == 0
    assert block.known_from_ms == 7200000


def test_fvg_is_known_only_after_third_candle_closes():
    bars = [
        candle(0, "10", "11", "9", "10"),
        candle(3600000, "10", "14", "10", "13"),
        candle(7200000, "13", "15", "12", "14"),
    ]
    gap = next(
        pda
        for pda in IctMmxmEngine().detect_pd_arrays(bars, "1h")
        if pda.array_type == PdArrayType.FVG_BISI
    )
    assert gap.known_from_ms == 10800000


def test_tap_before_array_confirmation_cannot_start_a_setup():
    bars = [candle(0, "10", "11", "8", "9"), candle(3600000, "9", "13", "9", "12")]
    lower = [candle(300000, "9", "10", "8", "9"), candle(600000, "9", "10", "8", "9")]
    setup = IctMmxmEngine().evaluate_twins_setup("SOLUSDT", [], bars, [], lower, lower)
    assert not setup.step_1_htf_hit


def test_cached_pdas_are_not_mutable_shared_state():
    engine = IctMmxmEngine()
    bars = [candle(0, "10", "11", "8", "9"), candle(3600000, "9", "13", "9", "12")]
    first = engine.detect_pd_arrays(bars, "1h")
    first.clear()
    assert engine.detect_pd_arrays(bars, "1h")


def test_canonical_ote_bounds_are_exactly_62_and_79_percent():
    engine = IctMmxmEngine()
    assert engine.ote_lower == D(".62")
    assert engine.ote_upper == D(".79")
