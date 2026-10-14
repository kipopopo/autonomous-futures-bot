import asyncio
import json
import time

import pytest

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.feed.exchange_clock import ExchangeClock
from autonomous_futures.feed.live_market_feed import LiveMarketFeed
from autonomous_futures.feed.runtime_hawkes_calibration import RuntimeHawkesCalibration
from autonomous_futures.feed.runtime_microstructure import RuntimeMicrostructure

CALIBRATION = RuntimeHawkesCalibration(1.0, "a" * 64, ("b" * 64,), ("SOLUSDT", "ETHUSDT"))
SINGLE_CALIBRATION = RuntimeHawkesCalibration(1.0, "a" * 64, ("b" * 64,), ("SOLUSDT",))


def feed():
    return LiveMarketFeed(
        BinanceFuturesGateway(testnet=True, offline_mode=False),
        RuntimeMicrostructure(("SOLUSDT", "ETHUSDT"), calibration=CALIBRATION),
    )


def test_rollout_refuses_offline_and_mainnet():
    for gateway in (
        BinanceFuturesGateway(testnet=True, offline_mode=True),
        BinanceFuturesGateway(testnet=False, offline_mode=False),
    ):
        with pytest.raises(ValueError, match="Testnet"):
            LiveMarketFeed(
                gateway,
                RuntimeMicrostructure(("SOLUSDT",), calibration=SINGLE_CALIBRATION),
            )


def test_market_and_public_streams_use_their_current_separate_routes():
    assert feed().endpoint == (
        "wss://fstream.binancefuture.com/market/stream?streams=solusdt@aggTrade/ethusdt@aggTrade"
    )


def test_entry_feed_health_requires_both_market_and_depth_connections():
    runtime = feed()

    async def scenario():
        release = asyncio.Event()
        market_started = asyncio.Event()
        public_started = asyncio.Event()

        async def hold(started):
            started.set()
            await release.wait()
            if False:
                yield "unused"

        market = asyncio.create_task(runtime.consume(hold(market_started), "market"))
        await market_started.wait()
        assert runtime.market_connected
        assert not runtime.connected

        public = asyncio.create_task(runtime.consume(hold(public_started), "public"))
        await public_started.wait()
        assert runtime.connected

        release.set()
        await asyncio.gather(market, public)
        assert not runtime.connected

    asyncio.run(scenario())
    assert feed().public_endpoint == (
        "wss://fstream.binancefuture.com/public/stream?streams="
        "solusdt@depth5@100ms/ethusdt@depth5@100ms"
    )


def test_stream_closure_discards_arrivals_and_authority():
    runtime = feed()
    now = time.time_ns() // 1_000_000
    runtime.clock = ExchangeClock(now, now, now)

    async def frames():
        yield json.dumps({"e": "aggTrade", "s": "SOLUSDT", "a": 1, "E": now, "T": now})
        assert runtime.market_connected
        assert not runtime.public_connected
        assert len(runtime.monitor.arrivals) == 1

    asyncio.run(runtime.consume(frames()))
    assert not runtime.connected
    assert not runtime.monitor.arrivals
    assert runtime.monitor.generation == 2
    with pytest.raises(ValueError, match="warmup"):
        runtime.monitor.evidence("SOLUSDT", now)


def test_stale_clock_closes_ingress_instead_of_reusing_old_offset():
    runtime = feed()
    now = time.time_ns() // 1_000_000
    runtime.clock = ExchangeClock(now - 180001, now - 180001, now - 180001)

    async def frames():
        yield json.dumps({"e": "aggTrade", "s": "SOLUSDT", "a": 1, "E": now, "T": now})

    with pytest.raises(ValueError, match="stale"):
        asyncio.run(runtime.consume(frames()))
    assert not runtime.connected
    assert not runtime.monitor.arrivals


def test_task_cancellation_invalidates_ingress():
    runtime = feed()
    now = time.time_ns() // 1_000_000
    runtime.clock = ExchangeClock(now, now, now)

    async def scenario():
        received = asyncio.Event()

        async def frames():
            yield json.dumps({"e": "aggTrade", "s": "SOLUSDT", "a": 1, "E": now, "T": now})
            received.set()
            await asyncio.Future()

        task = asyncio.create_task(runtime.consume(frames()))
        await received.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not runtime.connected
    assert not runtime.monitor.arrivals
