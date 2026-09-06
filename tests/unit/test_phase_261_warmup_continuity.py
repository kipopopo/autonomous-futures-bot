"""Phase 261 Milestone 2 Integration Tests: Dynamic Warmup Synchronization & WebSocket Continuity.

Verifies:
1. Dynamic warmup seeding via public REST loads exactly 100 closed 5m bars for all 4 symbols
   (BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT).
2. Developing in-progress candle is strictly excluded from seeded history.
3. Timestamp continuity between the newest seeded warmup bar and the first simulated live
   WebSocket closed bar (T_ws_first - T_seeded_last == 300s) with zero gap and zero duplicates.
4. WebSocket reconnect/replay duplicate closed bars update in-place without duplicate rows.
5. Causal feature evaluation via SignalEvaluator.evaluate executes cleanly
   with zero timestamp gap errors.
6. Multi-symbol continuous evaluation across all 4 symbols concurrently.
7. Multi-tier fallback Tier 1: Local Parquet with aligned timestamps avoids timestamp gap errors.
8. Multi-tier fallback Tier 2: Deterministic synthetic generator when Parquet is absent.
9. End-to-end bounded daemon mock execution with dynamic warmup and clean shutdown.
10. Strict zero-external-network socket blocking and unauthenticated safety invariants.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pandas as pd
import pytest

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.run_phase_259_live_paper_daemon as daemon_mod  # noqa: E402
from autonomous_futures.feed.models import CanonicalBar  # noqa: E402
from autonomous_futures.feed.monitor import CircuitBreakerFeedMonitor  # noqa: E402
from autonomous_futures.feed.rest_client import (  # noqa: E402
    DEFAULT_REST_URL,
    INTERVAL_5M_MS,
    BinancePublicRestClient,
)
from autonomous_futures.paper.circuit_breakers import (  # noqa: E402
    HardenedSharedMarginAccount,
)
from autonomous_futures.paper.live_engine import (  # noqa: E402
    DEFAULT_STARTING_CAPITAL,
    DEFAULT_SYMBOLS,
    LivePaperEngine,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def guard_no_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee zero external socket connections escape during the entire test execution."""
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
        if host in ("127.0.0.1", "localhost", "::1"):
            return real_connect(self, address)
        raise RuntimeError(
            f"SAFETY VIOLATION: Unauthorized external network call attempted to {address}"
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def fixed_now_ms() -> int:
    """Fixed reference timestamp: 2026-09-06 15:02:30.000 UTC."""
    # 2026-09-06 15:02:30 UTC = 1788706950000 ms
    return 1788706950000


@pytest.fixture
def fixed_now(fixed_now_ms: int) -> datetime:
    return datetime.fromtimestamp(fixed_now_ms / 1000, tz=UTC)


def make_mock_kline_payload(
    symbol: str,
    bars_count: int = 105,
    now_ms: int = 1788706950000,
) -> list[list[Any]]:
    """Build mock Binance Futures raw kline arrays terminating at now_ms.

    Includes 100 closed bars + 1 currently developing bar opening at (now_ms // 300_000) * 300_000.
    """
    base_prices = {"BTCUSDT": 85000.0, "ETHUSDT": 3100.0, "SOLUSDT": 180.0, "DOGEUSDT": 0.150}
    base = base_prices.get(symbol, 100.0)

    # Current developing candle start:
    current_open_ms = (now_ms // INTERVAL_5M_MS) * INTERVAL_5M_MS
    # Closed bars start bars_count intervals before current
    start_open_ms = current_open_ms - (bars_count - 1) * INTERVAL_5M_MS

    klines: list[list[Any]] = []
    step = base * 0.001
    for i in range(bars_count):
        open_ms = start_open_ms + i * INTERVAL_5M_MS
        close_ms = open_ms + INTERVAL_5M_MS - 1
        p = base + (i % 20) * step
        o_p = p
        h_p = p + 2 * step
        l_p = max(p - step, step)
        c_p = p + step
        vol = 1000.0
        q_vol = vol * p
        klines.append(
            [
                open_ms,
                f"{o_p:.4f}",
                f"{h_p:.4f}",
                f"{l_p:.4f}",
                f"{c_p:.4f}",
                f"{vol:.1f}",
                close_ms,
                f"{q_vol:.1f}",
                100,
                f"{vol * 0.5:.1f}",
                f"{q_vol * 0.5:.1f}",
                "0",
            ]
        )
    return klines


def make_canonical_bar(
    symbol: str,
    timestamp: datetime,
    open_price: Decimal = Decimal("100.00"),
    close_price: Decimal = Decimal("100.50"),
    high_price: Decimal = Decimal("101.00"),
    low_price: Decimal = Decimal("99.00"),
    volume: Decimal = Decimal("10.0"),
    is_closed: bool = True,
    interval: str = "5m",
) -> CanonicalBar:
    """Helper to instantiate a fully valid CanonicalBar with all required domain fields."""
    close_time = timestamp + timedelta(minutes=5) - timedelta(milliseconds=1)
    quote_volume = volume * close_price
    taker_buy_base = volume * Decimal("0.5")
    taker_buy_quote = quote_volume * Decimal("0.5")
    return CanonicalBar(
        symbol=symbol,
        interval=interval,
        timestamp=timestamp,
        close_time=close_time,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        quote_volume=quote_volume,
        trades=10,
        taker_buy_base=taker_buy_base,
        taker_buy_quote=taker_buy_quote,
        is_closed=is_closed,
    )


class MockRestKlineTransport(httpx.AsyncBaseTransport):
    """Mock HTTP transport returning valid Binance klines with request inspection."""

    def __init__(self, now_ms: int = 1788706950000) -> None:
        self.now_ms = now_ms
        self.requests_received: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests_received.append(request)

        # Inspect unauthenticated invariant
        for k in request.headers:
            if "apikey" in k.lower() or "auth" in k.lower() or "secret" in k.lower():
                return httpx.Response(401, json={"code": -2014, "msg": "API-key format invalid."})

        if request.url.path == "/fapi/v1/klines":
            symbol = request.url.params.get("symbol", "BTCUSDT")
            raw_klines = make_mock_kline_payload(symbol, bars_count=105, now_ms=self.now_ms)
            return httpx.Response(200, json=raw_klines)

        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": self.now_ms})

        return httpx.Response(404, json={"code": -1000, "msg": "Endpoint not found"})


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
            await asyncio.sleep(0.05)
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


@pytest.fixture
def mock_rest_client(fixed_now_ms: int) -> BinancePublicRestClient:
    transport = MockRestKlineTransport(now_ms=fixed_now_ms)
    return BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)


@pytest.fixture
def initialized_engine(tmp_path: Path) -> LivePaperEngine:
    storage_dir = tmp_path / "paper_storage"
    account = HardenedSharedMarginAccount(
        starting_capital=DEFAULT_STARTING_CAPITAL,
        max_utilization=Decimal("0.80"),
        min_reserve_buffer=Decimal("0.20"),
    )
    monitor = CircuitBreakerFeedMonitor(
        account=account,
        symbols=DEFAULT_SYMBOLS,
    )
    return LivePaperEngine(
        symbols=DEFAULT_SYMBOLS,
        account=account,
        monitor=monitor,
        ledger_db=storage_dir / "paper-ledger.sqlite3",
        lifecycle_db=storage_dir / "paper-lifecycle.sqlite3",
        observations_db=storage_dir / "paper-observations.sqlite3",
    )


# ===========================================================================
# Test Suite 1: Dynamic Warmup Seeding
# ===========================================================================


@pytest.mark.anyio
async def test_dynamic_warmup_seeding_loads_100_bars_all_symbols(
    initialized_engine: LivePaperEngine,
    mock_rest_client: BinancePublicRestClient,
    fixed_now: datetime,
) -> None:
    """Verify dynamic warmup seeds exactly 100 closed bars for BTC, ETH, SOL, DOGE."""
    seeded = await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=DEFAULT_SYMBOLS,
        warmup_bars=100,
        rest_client=mock_rest_client,
        now=fixed_now,
    )

    for sym in DEFAULT_SYMBOLS:
        assert seeded[sym] == 100
        assert len(initialized_engine._bar_history[sym]) == 100
        df = initialized_engine.get_bar_dataframe(sym)
        assert len(df) == 100
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        # Monotonic 300s spacing
        diffs = df["timestamp"].diff().dropna()
        assert (diffs == pd.Timedelta(seconds=300)).all()
        # Baseline ATR pre-warmed
        assert sym in initialized_engine.monitor._baseline_atrs
        assert initialized_engine.monitor._baseline_atrs[sym] > Decimal("0")


@pytest.mark.anyio
async def test_dynamic_warmup_strictly_excludes_developing_candle(
    initialized_engine: LivePaperEngine,
    mock_rest_client: BinancePublicRestClient,
    fixed_now: datetime,
) -> None:
    """Verify that the developing in-progress candle is strictly excluded from seeded history."""
    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=("BTCUSDT",),
        warmup_bars=100,
        rest_client=mock_rest_client,
        now=fixed_now,
    )
    df = initialized_engine.get_bar_dataframe("BTCUSDT")
    last_seeded_ts = df["timestamp"].iloc[-1]

    # At 15:02:30, the developing candle opened at 15:00:00 and closes at 15:05:00.
    # The latest closed candle must open at 14:55:00.
    expected_last_open = datetime(2026, 9, 6, 14, 55, 0, tzinfo=UTC)
    assert last_seeded_ts == expected_last_open


# ===========================================================================
# Test Suite 2: Timestamp Continuity & Deduplication
# ===========================================================================


@pytest.mark.anyio
async def test_seamless_timestamp_continuity_seeded_to_websocket(
    initialized_engine: LivePaperEngine,
    mock_rest_client: BinancePublicRestClient,
    fixed_now: datetime,
) -> None:
    """Verify that the newest seeded bar connects with the first live WebSocket bar without gap."""
    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=("BTCUSDT",),
        warmup_bars=100,
        rest_client=mock_rest_client,
        now=fixed_now,
    )
    last_seeded_ts = initialized_engine._bar_history["BTCUSDT"][-1]["timestamp"]

    # First closed bar from WebSocket arrives at 15:05:00 (for the 15:00:00 interval)
    ws_bar_ts = datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC)
    delta = ws_bar_ts - last_seeded_ts
    assert delta == timedelta(minutes=5), f"Discontinuity detected: delta is {delta}"

    live_bar = make_canonical_bar(
        symbol="BTCUSDT",
        timestamp=ws_bar_ts,
        open_price=Decimal("85020.00"),
        high_price=Decimal("85080.00"),
        low_price=Decimal("84990.00"),
        close_price=Decimal("85050.00"),
        volume=Decimal("15.2"),
    )
    await initialized_engine.handle_bar(live_bar)

    assert len(initialized_engine._bar_history["BTCUSDT"]) == 101
    df = initialized_engine.get_bar_dataframe("BTCUSDT")
    assert df["timestamp"].iloc[-1] == ws_bar_ts
    assert not df["timestamp"].duplicated().any()


@pytest.mark.anyio
async def test_websocket_reconnect_duplicate_bar_deduplication(
    initialized_engine: LivePaperEngine,
    mock_rest_client: BinancePublicRestClient,
    fixed_now: datetime,
) -> None:
    """Verify that replayed/duplicate WebSocket closed bars do not create duplicate entries."""
    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=("BTCUSDT",),
        warmup_bars=100,
        rest_client=mock_rest_client,
        now=fixed_now,
    )
    ws_bar_ts = datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC)
    live_bar = make_canonical_bar(
        symbol="BTCUSDT",
        timestamp=ws_bar_ts,
        open_price=Decimal("85020.00"),
        high_price=Decimal("85080.00"),
        low_price=Decimal("84990.00"),
        close_price=Decimal("85050.00"),
        volume=Decimal("15.2"),
    )
    await initialized_engine.handle_bar(live_bar)
    assert len(initialized_engine._bar_history["BTCUSDT"]) == 101

    # Simulate duplicate bar delivery
    await initialized_engine.handle_bar(live_bar)
    assert len(initialized_engine._bar_history["BTCUSDT"]) == 101
    df = initialized_engine.get_bar_dataframe("BTCUSDT")
    assert not df["timestamp"].duplicated().any()


# ===========================================================================
# Test Suite 3: Causal Feature Evaluation Execution
# ===========================================================================


@pytest.mark.anyio
async def test_signal_evaluator_executes_cleanly_on_incoming_closed_bars(
    initialized_engine: LivePaperEngine,
    mock_rest_client: BinancePublicRestClient,
    fixed_now: datetime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that incoming closed bars evaluate features with ZERO timestamp gap warnings."""
    caplog.set_level(logging.WARNING)

    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=("BTCUSDT",),
        warmup_bars=100,
        rest_client=mock_rest_client,
        now=fixed_now,
    )

    # Ingest 2 consecutive closed live bars
    for i in range(2):
        ts = datetime(2026, 9, 6, 15, 0 + i * 5, 0, tzinfo=UTC)
        bar = make_canonical_bar(
            symbol="BTCUSDT",
            timestamp=ts,
            open_price=Decimal("85000.00"),
            high_price=Decimal("85100.00"),
            low_price=Decimal("84950.00"),
            close_price=Decimal("85050.00"),
            volume=Decimal("20.0"),
        )
        await initialized_engine.handle_bar(bar)

    # Strict assertion: ZERO feature evaluation warnings or timestamp gaps logged
    gap_warnings = [
        r.message
        for r in caplog.records
        if "Feature evaluation failed" in r.message or "timestamp gap" in r.message
    ]
    assert not gap_warnings, f"Unexpected feature evaluation failures: {gap_warnings}"

    # Direct assertion on signal evaluator
    cand = initialized_engine.candidates["BTCUSDT"]
    df = initialized_engine.get_bar_dataframe("BTCUSDT")
    evaluated_df = initialized_engine.signal_evaluator.evaluate(cand, df)
    assert "signal" in evaluated_df.columns
    assert "long_entry" in evaluated_df.columns
    assert "short_entry" in evaluated_df.columns
    assert int(evaluated_df["signal"].iloc[-1]) in (-1, 0, 1)


@pytest.mark.anyio
async def test_signal_evaluator_multi_symbol_continuous_execution(
    initialized_engine: LivePaperEngine,
    mock_rest_client: BinancePublicRestClient,
    fixed_now: datetime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify clean feature evaluation across all 4 active portfolio symbols concurrently."""
    caplog.set_level(logging.WARNING)

    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=DEFAULT_SYMBOLS,
        warmup_bars=100,
        rest_client=mock_rest_client,
        now=fixed_now,
    )

    base_prices = {
        "BTCUSDT": Decimal("85000"),
        "ETHUSDT": Decimal("3100"),
        "SOLUSDT": Decimal("180"),
        "DOGEUSDT": Decimal("0.15"),
    }
    ws_ts = datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC)
    for sym in DEFAULT_SYMBOLS:
        bp = base_prices.get(sym, Decimal("100"))
        bar = make_canonical_bar(
            symbol=sym,
            timestamp=ws_ts,
            open_price=bp,
            high_price=bp * Decimal("1.01"),
            low_price=bp * Decimal("0.99"),
            close_price=bp * Decimal("1.005"),
            volume=Decimal("50.0"),
        )
        await initialized_engine.handle_bar(bar)

    gap_warnings = [r.message for r in caplog.records if "Feature evaluation failed" in r.message]
    assert not gap_warnings, f"Multi-symbol evaluation failed: {gap_warnings}"


# ===========================================================================
# Test Suite 4: Multi-Tier Offline Fallback & Resilience
# ===========================================================================


@pytest.mark.anyio
async def test_offline_fallback_tier1_parquet_aligned_continuity(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify fallback to local Parquet aligns timestamps and avoids timestamp gap errors."""
    caplog.set_level(logging.WARNING)

    history_dir = _REPO_ROOT / "research" / "immutable-data" / "5m" / "canonical"
    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=("BTCUSDT",),
        warmup_bars=100,
        history_dir=history_dir,
        offline=True,
        now=fixed_now,
    )

    df = initialized_engine.get_bar_dataframe("BTCUSDT")
    assert len(df) == 100
    assert df["timestamp"].iloc[-1] == datetime(2026, 9, 6, 14, 55, 0, tzinfo=UTC)

    # Ingest live bar at 15:00:00
    live_bar = make_canonical_bar(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC),
        open_price=Decimal("85000"),
        high_price=Decimal("85100"),
        low_price=Decimal("84900"),
        close_price=Decimal("85050"),
        volume=Decimal("10"),
    )
    await initialized_engine.handle_bar(live_bar)
    assert not any("Feature evaluation failed" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_offline_fallback_tier2_synthetic_generator_continuity(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify fallback to deterministic synthetic generator when Parquet is absent."""
    caplog.set_level(logging.WARNING)

    empty_history_dir = tmp_path / "empty_canonical"
    empty_history_dir.mkdir()

    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=DEFAULT_SYMBOLS,
        warmup_bars=100,
        history_dir=empty_history_dir,
        offline=True,
        now=fixed_now,
    )

    base_prices = {
        "BTCUSDT": Decimal("85000"),
        "ETHUSDT": Decimal("3100"),
        "SOLUSDT": Decimal("180"),
        "DOGEUSDT": Decimal("0.15"),
    }
    for sym in DEFAULT_SYMBOLS:
        assert len(initialized_engine._bar_history[sym]) == 100
        bp = base_prices.get(sym, Decimal("100"))
        live_bar = make_canonical_bar(
            symbol=sym,
            timestamp=datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC),
            open_price=bp,
            high_price=bp * Decimal("1.01"),
            low_price=bp * Decimal("0.99"),
            close_price=bp * Decimal("1.005"),
            volume=Decimal("10"),
        )
        await initialized_engine.handle_bar(live_bar)

    assert not any("Feature evaluation failed" in r.message for r in caplog.records)


# ===========================================================================
# Test Suite 5: End-to-End Daemon Mock Execution & Safety Invariants
# ===========================================================================


@pytest.mark.anyio
async def test_end_to_end_daemon_mock_with_dynamic_warmup(
    tmp_path: Path,
    fixed_now_ms: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify end-to-end daemon execution with mock REST warmup and contiguous WebSocket bar."""
    caplog.set_level(logging.WARNING)
    storage_dir = tmp_path / "paper_daemon_e2e"

    # Reference time: 2026-09-06 15:02:30.000 UTC
    # Developing candle starts at 15:00:00 (1788706800000), latest closed candle at 14:55:00.
    ws_bar_open_ms = 1788706800000  # 15:00:00
    ws_bar_close_ms = ws_bar_open_ms + 300_000 - 1

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
                    "T": ws_bar_open_ms + 1000,
                    "E": ws_bar_open_ms + 1050,
                },
            }
        ),
        json.dumps(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "e": "kline",
                    "E": ws_bar_close_ms + 50,
                    "s": "BTCUSDT",
                    "k": {
                        "t": ws_bar_open_ms,
                        "T": ws_bar_close_ms,
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

    transport = MockRestKlineTransport(now_ms=fixed_now_ms)
    mock_rest_client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

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
            "BTCUSDT",
        ]
    )

    fixed_time_sec = fixed_now_ms / 1000.0
    with (
        patch("websockets.connect", return_value=MockConnectContext()),
        patch(
            "scripts.run_phase_259_live_paper_daemon.BinancePublicRestClient",
            return_value=mock_rest_client,
        ),
        patch("time.time", return_value=fixed_time_sec),
    ):
        summary = await daemon_mod.run_live_paper_daemon(args)

    assert summary is not None
    assert summary["run_metadata"]["symbols"] == ["BTCUSDT"]
    assert summary["safety_invariants"]["orders_submitted"] == 0
    assert summary["shared_portfolio_margin"]["zero_balance_drift"] is True

    gap_warnings = [
        r.message
        for r in caplog.records
        if "Feature evaluation failed" in r.message or "timestamp gap" in r.message
    ]
    assert not gap_warnings, f"Unexpected gap errors in daemon mock: {gap_warnings}"

    health_file = storage_dir / "paper-daemon-health.json"
    assert health_file.exists()
    health = json.loads(health_file.read_text(encoding="utf-8"))
    assert health["daemon_status"] == "SHUTDOWN_CLEAN"


@pytest.mark.anyio
async def test_zero_external_network_calls_and_safety_invariants(
    initialized_engine: LivePaperEngine,
    fixed_now_ms: int,
) -> None:
    """Verify strictly unauthenticated operation and zero external network calls."""
    # 1. Verify that unauthorized raw socket connection is blocked by guard fixture
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
        s = socket.socket()
        s.connect(("fapi.binance.com", 443))

    # 2. Verify unauthenticated client communicates exclusively via mock transport
    transport = MockRestKlineTransport(now_ms=fixed_now_ms)
    async with BinancePublicRestClient(
        base_url=DEFAULT_REST_URL, transport=transport
    ) as rest_client:
        await daemon_mod.seed_historical_warmup_bars(
            engine=initialized_engine,
            symbols=DEFAULT_SYMBOLS,
            warmup_bars=100,
            rest_client=rest_client,
        )

    # Inspect all wire requests recorded
    assert len(transport.requests_received) >= 4
    for req in transport.requests_received:
        assert req.method == "GET"
        assert req.url.host == "fapi.binance.com"
        assert "api-key" not in req.headers
        assert "x-mbx-apikey" not in req.headers
        assert "authorization" not in req.headers
        assert "signature" not in req.url.params

    # Verify strict safety invariants
    invariants = daemon_mod.verify_strict_safety_invariants(orders_submitted=0)
    assert invariants["orders_submitted"] == 0
    assert invariants["execution_authority"] is False
    assert invariants["api_keys_loaded"] == 0
    assert invariants["live_trading_activation"] is False
    assert invariants["paper_activation"] is True
