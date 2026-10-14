import asyncio
from dataclasses import replace
from decimal import Decimal as D
from unittest.mock import AsyncMock

import pytest
from test_protective_lifecycle import PLAN, actions, entry, stop

from autonomous_futures.execution.exit_invalidation import CausalExitReader, ExitObservation
from autonomous_futures.feed.exchange_clock import ExchangeClock
from autonomous_futures.strategy.ict_mmxm import Candle


@pytest.mark.parametrize(
    "side,close,expected",
    [
        ("BUY", "99", True),
        ("BUY", "100", True),
        ("BUY", "101", False),
        ("SELL", "99", False),
        ("SELL", "100", True),
        ("SELL", "101", True),
    ],
)
def test_completed_close_invalidation_matches_researched_direction(side, close, expected):
    observation = ExitObservation(PLAN.symbol, 120000, D(close))
    assert observation.invalidates(replace(PLAN, side=side), 61000) is expected
    assert not observation.invalidates(PLAN, 120000)
    assert not observation.invalidates(replace(PLAN, family="MACRO_SCALPER"), 61000)


def test_uncertain_boundary_never_reads_forming_candle_and_reuses_observation():
    history = AsyncMock()
    history.read.return_value = (Candle(60000, D(101), D(102), D(99), D(100), D(2)),)
    clock = ExchangeClock(119950, 120050, 120000)
    reader = CausalExitReader(history, lambda: clock)

    async def run():
        first = await reader.read(PLAN, 120051, 61000)
        second = await reader.read(PLAN, 120052, 61000)
        assert first == second
        history.read.assert_awaited_once_with(PLAN.symbol, "1m", 120000)

    asyncio.run(run())
    # At the uncertain boundary the previous minute is the only provably closed bar.
    early_clock = ExchangeClock(119950, 119970, 119960)
    assert early_clock.completed_boundary(120000, 60000) == 60000
    assert early_clock.completed_boundary(120010, 60000) == 120000


def test_missing_clock_or_stale_history_cannot_supply_exit_authority():
    history = AsyncMock()
    reader = CausalExitReader(history, lambda: None)
    with pytest.raises(ValueError, match="clock"):
        asyncio.run(reader.read(PLAN, 120100, 61000))
    history.read.assert_not_awaited()
    history.read.return_value = (Candle(0, D(100), D(101), D(99), D(100), D(1)),)
    reader = CausalExitReader(history, lambda: ExchangeClock(120000, 120000, 120000))
    with pytest.raises(ValueError, match="boundary"):
        asyncio.run(reader.read(PLAN, 120100, 61000))


def test_invalidation_closes_only_owned_partial_fill_and_retains_stop():
    result = actions(entry(".5", "PARTIALLY_FILLED"), (stop(),), ".5", strategy_invalidated=True)
    assert [(action.role, action.operation, action.quantity) for action in result] == [
        ("ENTRY", "CANCEL", D("1.5")),
        ("FLATTEN", "PLACE", D(".5")),
    ]
    assert result[-1].reduce_only
    assert all(action.client_id != "stop" for action in result)
    with pytest.raises(ValueError, match="ownership"):
        actions(entry(".5", "PARTIALLY_FILLED"), (stop(),), "2", strategy_invalidated=True)


def test_recovery_retains_earlier_invalidation_despite_later_rebound():
    history = AsyncMock()
    history.read.return_value = (
        Candle(60000, D(101), D(102), D(99), D(99), D(2)),
        Candle(120000, D(99), D(103), D(99), D(102), D(2)),
    )
    reader = CausalExitReader(history, lambda: ExchangeClock(180000, 180000, 180000))
    observation = asyncio.run(reader.read(PLAN, 180010, 61000))
    assert observation.boundary_ms == 120000
    assert observation.close == 99
    assert observation.invalidates(PLAN, 61000)
    # An older fill with incomplete recovery history must fail instead of assuming no exit.
    with pytest.raises(ValueError, match="first fill"):
        asyncio.run(reader.read(PLAN, 180020, 59999))


def test_cached_history_is_rechecked_for_each_owned_trade_fill_time():
    history = AsyncMock()
    history.read.return_value = (
        Candle(60000, D(101), D(102), D(99), D(99), D(2)),
        Candle(120000, D(99), D(103), D(99), D(102), D(2)),
    )
    reader = CausalExitReader(history, lambda: ExchangeClock(180000, 180000, 180000))
    assert asyncio.run(reader.read(PLAN, 180010, 61000)).invalidates(PLAN, 61000)
    later = asyncio.run(reader.read(PLAN, 180020, 120000))
    assert not later.invalidates(PLAN, 120000)
    assert later.boundary_ms == 180000
    assert history.read.await_count == 1
