import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.feed.authenticated_user_stream import AuthenticatedUserDataStream


class FakeSocket:
    def __init__(self, payloads):
        self.payloads = payloads
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def __aiter__(self):
        for payload in self.payloads:
            yield json.dumps(payload)
        await asyncio.Future()

    async def close(self):
        self.closed = True


def test_private_endpoint_encodes_listen_key_and_subscribed_event_types():
    gateway = BinanceFuturesGateway(
        api_key="key", api_secret="secret", testnet=True, offline_mode=False
    )
    stream = AuthenticatedUserDataStream(gateway)
    stream.listen_key = "test/key value"

    assert stream.endpoint.startswith("wss://fstream.binancefuture.com/private/ws?")
    assert "listenKey=test%2Fkey%20value" in stream.endpoint
    assert "events=ACCOUNT_UPDATE/ACCOUNT_CONFIG_UPDATE/ORDER_TRADE_UPDATE/ALGO_UPDATE" in (
        stream.endpoint
    )


def test_decode_event_accepts_combined_wrapper_and_rejects_malformed_payloads():
    payload = {"e": "ALGO_UPDATE", "E": 1234, "o": {"algoStatus": "REJECTED"}}
    assert (
        AuthenticatedUserDataStream.decode_event(json.dumps({"stream": "private", "data": payload}))
        == payload
    )

    for wire in ("not-json", "[]", '{"data":[]}'):
        with pytest.raises(ValueError, match="(?i)user-data WebSocket"):
            AuthenticatedUserDataStream.decode_event(wire)


def test_entry_health_stays_blocked_until_ordered_event_state_is_reconciled():
    gateway = BinanceFuturesGateway(
        api_key="key", api_secret="secret", testnet=True, offline_mode=False
    )
    stream = AuthenticatedUserDataStream(gateway)
    stream.connected = True
    stream.event_count = 2

    with pytest.raises(ValueError, match="awaiting REST reconciliation"):
        stream.assert_entry_ready()
    assert not stream.mark_reconciled(1)
    assert stream.reconciliation_required
    assert stream.mark_reconciled(2)
    stream.assert_entry_ready()

    stream.block_entries("MARGIN_CALL")
    with pytest.raises(ValueError):
        stream.assert_entry_ready()
    stream.clear_entry_block("MARGIN_CALL")
    stream.assert_entry_ready()


def test_expiry_rotates_listen_key_and_resynchronizes_before_events():
    async def scenario():
        gateway = BinanceFuturesGateway(
            api_key="key", api_secret="secret", testnet=True, offline_mode=False
        )
        gateway.create_listen_key = AsyncMock(side_effect=("first-key", "second-key"))
        gateway.keepalive_user_data_stream = AsyncMock(return_value=True)
        gateway.close_user_data_stream = AsyncMock(return_value=True)
        sockets = [
            FakeSocket([{"e": "listenKeyExpired", "E": 1000}]),
            FakeSocket([{"e": "ACCOUNT_UPDATE", "E": 1001}]),
        ]
        order = []
        stream = AuthenticatedUserDataStream(
            gateway,
            connector=lambda *_args, **_kwargs: sockets.pop(0),
            keepalive_interval_seconds=3600 - 1,
            max_connection_age_seconds=60,
            reconnect_delay_seconds=0,
        )

        async def resynchronize():
            assert not stream.connected
            order.append("resynchronize")

        async def on_event(event):
            assert stream.connected
            order.append(event["e"])
            if event["e"] == "ACCOUNT_UPDATE":
                ready.set()

        ready = asyncio.Event()
        stream.on_reconnect = resynchronize
        stream.on_event = on_event
        stream.on_disconnect = lambda: _append_async(order, "disconnect")
        task = asyncio.create_task(stream.run())
        await asyncio.wait_for(ready.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert order[:5] == [
            "resynchronize",
            "listenKeyExpired",
            "disconnect",
            "resynchronize",
            "ACCOUNT_UPDATE",
        ]
        assert gateway.create_listen_key.await_count == 2
        gateway.close_user_data_stream.assert_awaited_once_with("second-key")
        assert not stream.connected

    asyncio.run(scenario())


async def _append_async(values, value):
    values.append(value)
