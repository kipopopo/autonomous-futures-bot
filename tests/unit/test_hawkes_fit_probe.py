import asyncio

from scripts.probe_hawkes_fit import receive_frame


class IdleStream:
    async def recv(self) -> str:
        await asyncio.Event().wait()
        return "unreachable"


class ImmediateStream:
    async def recv(self) -> str:
        return "frame"


def test_hawkes_probe_receive_ends_when_stream_is_idle() -> None:
    assert asyncio.run(receive_frame(IdleStream(), 0.001)) is None


def test_hawkes_probe_receive_keeps_available_frames() -> None:
    assert asyncio.run(receive_frame(ImmediateStream(), 1)) == "frame"


def test_hawkes_probe_receive_does_not_wait_after_deadline() -> None:
    assert asyncio.run(receive_frame(IdleStream(), 0)) is None
