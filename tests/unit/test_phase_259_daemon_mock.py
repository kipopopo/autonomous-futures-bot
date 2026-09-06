"""Unit tests for Phase 259 24/7 Live Paper Daemon end-to-end execution with mock WebSocket."""

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


class MockWebSocketSession:
    """Mock WebSocket session simulating Binance public wire frames."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str = ""

    def __aiter__(self) -> MockWebSocketSession:
        return self

    async def __anext__(self) -> str:
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


@pytest.mark.anyio
async def test_live_paper_daemon_mock_run(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_live_test"
    mock_messages = [
        json.dumps(
            {
                "stream": "btcusdt@bookTicker",
                "data": {
                    "e": "bookTicker",
                    "u": 10000001,
                    "s": "BTCUSDT",
                    "b": "85000.10",
                    "B": "1.500",
                    "a": "85000.20",
                    "A": "2.100",
                    "T": 1772700000000,
                    "E": 1772700000050,
                },
            }
        ),
        json.dumps(
            {
                "stream": "ethusdt@bookTicker",
                "data": {
                    "e": "bookTicker",
                    "u": 10000002,
                    "s": "ETHUSDT",
                    "b": "3100.10",
                    "B": "5.000",
                    "a": "3100.20",
                    "A": "4.500",
                    "T": 1772700000010,
                    "E": 1772700000060,
                },
            }
        ),
        json.dumps(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "e": "kline",
                    "E": 1772700300050,
                    "s": "BTCUSDT",
                    "k": {
                        "t": 1772700000000,
                        "T": 1772700299999,
                        "s": "BTCUSDT",
                        "i": "5m",
                        "f": 100,
                        "L": 200,
                        "o": "85000.00",
                        "c": "85050.00",
                        "h": "85100.00",
                        "l": "84950.00",
                        "v": "100.5",
                        "n": 101,
                        "x": True,
                        "q": "8547525.0",
                        "V": "50.2",
                        "Q": "4269512.5",
                    },
                },
            }
        ),
    ]

    mock_ws = MockWebSocketSession(mock_messages)

    class MockConnectContext:
        async def __aenter__(self) -> MockWebSocketSession:
            return mock_ws

        async def __aexit__(self, exc_type: type | None, exc: Exception | None, tb: object) -> None:
            pass

    args = daemon_mod.parse_cli_args(
        [
            "--storage-dir",
            str(storage_dir),
            "--duration",
            "1.5",
            "--checkpoint-interval",
            "0.5",
            "--starting-capital",
            "100.00",
            "--symbols",
            "BTCUSDT,ETHUSDT",
        ]
    )

    with patch("websockets.connect", return_value=MockConnectContext()):
        summary = await daemon_mod.run_live_paper_daemon(args)

    assert summary is not None
    assert summary["run_metadata"]["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert summary["shared_portfolio_margin"]["starting_capital"] == "100.00"
    assert summary["shared_portfolio_margin"]["final_cash"] == "100.00"
    assert summary["shared_portfolio_margin"]["zero_balance_drift"] is True
    assert summary["safety_invariants"]["orders_submitted"] == 0

    health_file = storage_dir / "paper-daemon-health.json"
    assert health_file.exists()
    health = json.loads(health_file.read_text(encoding="utf-8"))
    assert health["daemon_status"] == "SHUTDOWN_CLEAN"
    assert health["starting_capital_usdt"] == "100.00"
    assert health["current_cash_usdt"] == "100.00"
    assert health["feed_messages_received"] == 3
    assert health["zero_order_safety_invariants"]["orders_submitted"] == 0

    # Verify SQLite databases created
    assert (storage_dir / "paper-ledger.sqlite3").is_file()
    assert (storage_dir / "paper-lifecycle.sqlite3").is_file()
    assert (storage_dir / "paper-observations.sqlite3").is_file()
    assert (storage_dir / "live-paper-summary.json").is_file()
