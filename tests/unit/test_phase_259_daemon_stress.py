"""Stress and concurrency tests for Phase 259 24/7 Live Paper Daemon."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.run_phase_259_live_paper_daemon as daemon_mod  # noqa: E402


class StressMockWebSocket:
    """Simulates high-throughput rapid message streams."""

    def __init__(self, message_count: int = 500) -> None:
        self.messages: list[str] = []
        for i in range(message_count):
            price = 85000.0 + (i % 50) * 0.10
            msg = json.dumps(
                {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "e": "bookTicker",
                        "u": 10000000 + i,
                        "s": "BTCUSDT",
                        "b": f"{price:.2f}",
                        "B": "1.000",
                        "a": f"{(price + 0.10):.2f}",
                        "A": "1.000",
                        "T": 1772700000000 + i * 10,
                        "E": 1772700000010 + i * 10,
                    },
                }
            )
            self.messages.append(msg)
        self.closed = False

    def __aiter__(self) -> StressMockWebSocket:
        return self

    async def __anext__(self) -> str:
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True


@pytest.mark.anyio
async def test_live_paper_daemon_high_throughput_stress(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_live_stress"
    stress_ws = StressMockWebSocket(message_count=200)

    class MockConnectContext:
        async def __aenter__(self) -> StressMockWebSocket:
            return stress_ws

        async def __aexit__(self, exc_type: type | None, exc: Exception | None, tb: object) -> None:
            pass

    args = daemon_mod.parse_cli_args(
        [
            "--storage-dir",
            str(storage_dir),
            "--duration",
            "1.0",
            "--checkpoint-interval",
            "0.2",
            "--starting-capital",
            "100.00",
            "--symbols",
            "BTCUSDT",
        ]
    )

    with patch("websockets.connect", return_value=MockConnectContext()):
        summary = await daemon_mod.run_live_paper_daemon(args)

    assert summary["shared_portfolio_margin"]["zero_balance_drift"] is True
    assert summary["shared_portfolio_margin"]["final_cash"] == "100.00"

    health_file = storage_dir / "paper-daemon-health.json"
    assert health_file.exists()
    health = json.loads(health_file.read_text(encoding="utf-8"))
    assert health["daemon_status"] == "SHUTDOWN_CLEAN"
    assert health["feed_messages_received"] >= 100
