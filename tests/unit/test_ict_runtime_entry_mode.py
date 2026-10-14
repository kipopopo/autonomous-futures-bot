from decimal import Decimal as D
from typing import Literal

from autonomous_futures.execution.trade_plan import SymbolFilters, build_plan
from autonomous_futures.research.ict_runtime_qualification import (
    has_close_reclaim,
    has_post_reclaim_limit_fill,
)
from autonomous_futures.strategy.ict_mmxm import Candle

FILTERS = SymbolFilters(D(".01"), D(".01"), D(".01"), D("1000"), D("5"))


def trade_plan(side: Literal["BUY", "SELL"]):
    return build_plan(
        family="ICT_TWINS",
        symbol="ETHUSDT",
        side=side,
        entry=D("100"),
        stop=D("90") if side == "BUY" else D("110"),
        tp1=D("115") if side == "BUY" else D("85"),
        tp2=D("120") if side == "BUY" else D("80"),
        decision_ms=60_000,
        hold_ms=900_000,
        setup_key="observed-signal",
        filters=FILTERS,
        equity=D("1000"),
        available_margin=D("1000"),
    )


def candle(open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(120_000, D(open_), D(high), D(low), D(close), D("20"))


def test_long_close_reclaim_requires_touch_and_favorable_close() -> None:
    plan = trade_plan("BUY")

    assert has_close_reclaim(candle("99", "103", "98", "102"), plan)
    assert not has_close_reclaim(candle("99", "103", "98", "99.99"), plan)
    assert not has_close_reclaim(candle("101", "103", "100", "102"), plan)


def test_short_close_reclaim_requires_touch_and_favorable_close() -> None:
    plan = trade_plan("SELL")

    assert has_close_reclaim(candle("101", "102", "97", "98"), plan)
    assert not has_close_reclaim(candle("101", "102", "97", "100.01"), plan)
    assert not has_close_reclaim(candle("99", "100", "97", "98"), plan)


def test_maker_retest_requires_a_separate_non_marketable_trade_through() -> None:
    long_plan = trade_plan("BUY")
    short_plan = trade_plan("SELL")

    assert has_post_reclaim_limit_fill(candle("101", "102", "99", "100.5"), long_plan)
    assert not has_post_reclaim_limit_fill(candle("99", "102", "98", "100.5"), long_plan)
    assert has_post_reclaim_limit_fill(candle("99", "102", "98", "99.5"), short_plan)
    assert not has_post_reclaim_limit_fill(candle("101", "102", "98", "99.5"), short_plan)
