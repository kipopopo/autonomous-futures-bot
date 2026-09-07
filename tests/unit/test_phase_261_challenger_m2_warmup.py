"""Phase 261 Milestone 2 Adversarial Stress & Empirical Verification Test Suite.

Authored by challenger_m2_2 to adversarially challenge and stress-test:
1. Timeout & Slow Network Stress:
   - Delayed REST responses exceeding --warmup-timeout (e.g. 10s delay with 0.3s timeout).
   - Asymmetric per-symbol delay where some symbols hang.
   - Bounded execution time verification (no hanging or leaking background tasks).
   - Connection drops, pool timeouts, and network errors mid-warmup.
2. Concurrent Multi-Symbol Warmup:
   - Simultaneous warmup across 4 symbols (BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT) with mixed tiering:
     BTC on REST, ETH on Parquet, SOL on Parquet, DOGE on Synthetic.
   - Verification that all 4 symbols receive exactly 100 bars each.
   - Parquet corruption and truncated history handling.
   - Re-seeding and deduplication idempotence.
3. Feature Evaluation Pipeline Integrity:
   - Feature evaluation on mixed-source bars without `DataQualityError: timestamp gap`.
   - Multi-bar continuous stream feature evaluation and signal emission.
   - WebSocket reconnect replay bar deduplication without corrupting evaluation.
   - Temporal gap detection and self-healing pruning.
4. End-to-End Daemon Startup & Strict Safety Invariants:
   - Daemon startup under slow network timeout with bounded fallback.
   - Verification of zero live orders, zero private keys, and execution authority disabled.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
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
    validate_canonical_dataframe,
)
from autonomous_futures.paper.circuit_breakers import (  # noqa: E402
    HardenedSharedMarginAccount,
)
from autonomous_futures.paper.live_engine import (  # noqa: E402
    DEFAULT_STARTING_CAPITAL,
    LivePaperEngine,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def guard_no_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee zero external socket connections escape during test execution."""
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
    """Fixed reference timestamp: 2026-09-06 15:02:30.000 UTC = 1788706950000 ms."""
    return 1788706950000


@pytest.fixture
def fixed_now(fixed_now_ms: int) -> datetime:
    return datetime.fromtimestamp(fixed_now_ms / 1000, tz=UTC)


@pytest.fixture
def temp_storage_dir(tmp_path: Path) -> Path:
    storage = tmp_path / "paper_live_challenger"
    storage.mkdir(parents=True, exist_ok=True)
    return storage


@pytest.fixture
def initialized_engine(temp_storage_dir: Path) -> LivePaperEngine:
    account = HardenedSharedMarginAccount(
        starting_capital=DEFAULT_STARTING_CAPITAL,
        max_utilization=Decimal("0.80"),
        base_allocation_fraction=Decimal("0.20"),
        min_reserve_buffer=Decimal("0.20"),
    )
    monitor = CircuitBreakerFeedMonitor(
        account=account,
        symbols=SYMBOLS,
        max_queue_size=1000,
        evaluate_on_ticker=True,
    )
    return LivePaperEngine(
        symbols=SYMBOLS,
        starting_capital=DEFAULT_STARTING_CAPITAL,
        ledger_db=temp_storage_dir / "paper-ledger.sqlite3",
        lifecycle_db=temp_storage_dir / "paper-lifecycle.sqlite3",
        observations_db=temp_storage_dir / "paper-observations.sqlite3",
        monitor=monitor,
        account=account,
    )


def make_mock_kline_payload(
    symbol: str,
    bars_count: int = 105,
    now_ms: int = 1788706950000,
) -> list[list[Any]]:
    """Build mock Binance Futures raw kline arrays."""
    base_prices = {"BTCUSDT": 85000.0, "ETHUSDT": 3100.0, "SOLUSDT": 180.0, "DOGEUSDT": 0.150}
    base = base_prices.get(symbol, 100.0)

    current_open_ms = (now_ms // INTERVAL_5M_MS) * INTERVAL_5M_MS
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
    high_price: Decimal | None = None,
    low_price: Decimal | None = None,
    volume: Decimal = Decimal("10.0"),
    is_closed: bool = True,
    interval: str = "5m",
) -> CanonicalBar:
    """Instantiate a valid CanonicalBar with all required domain fields."""
    close_time = timestamp + timedelta(minutes=5) - timedelta(milliseconds=1)
    base_max = max(open_price, close_price)
    base_min = min(open_price, close_price)
    high_val = max(high_price, base_max) if high_price is not None else base_max + Decimal("0.50")
    low_val = (
        min(low_price, base_min)
        if low_price is not None
        else max(Decimal("0.01"), base_min - Decimal("0.50"))
    )
    quote_volume = volume * close_price
    taker_buy_base = volume * Decimal("0.5")
    taker_buy_quote = quote_volume * Decimal("0.5")
    return CanonicalBar(
        symbol=symbol,
        interval=interval,
        timestamp=timestamp,
        close_time=close_time,
        open=open_price,
        high=high_val,
        low=low_val,
        close=close_price,
        volume=volume,
        quote_volume=quote_volume,
        trades=10,
        taker_buy_base=taker_buy_base,
        taker_buy_quote=taker_buy_quote,
        is_closed=is_closed,
    )


# ===========================================================================
# Vector 1: Timeout & Slow Network Stress
# ===========================================================================


class DelayedRestKlineTransport(httpx.AsyncBaseTransport):
    """Mock HTTP transport simulating slow or hanging REST network."""

    def __init__(
        self,
        delay_seconds: float = 10.0,
        delayed_symbols: tuple[str, ...] | None = None,
        now_ms: int = 1788706950000,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.delayed_symbols = delayed_symbols
        self.now_ms = now_ms
        self.requests_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests_count += 1
        symbol = request.url.params.get("symbol", "")
        should_delay = self.delayed_symbols is None or symbol in self.delayed_symbols

        if should_delay and self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        if request.url.path == "/fapi/v1/klines":
            raw_klines = make_mock_kline_payload(symbol, bars_count=105, now_ms=self.now_ms)
            return httpx.Response(200, json=raw_klines)
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": self.now_ms})
        return httpx.Response(404, json={"code": -1000, "msg": "Not found"})


@pytest.mark.anyio
async def test_timeout_slow_network_triggers_clean_synthetic_fallback(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    temp_storage_dir: Path,
) -> None:
    """Verify daemon cleanly falls back to synthetic data within bounded time.

    Triggers when REST delays 15s.
    """
    delay = 15.0
    timeout = 0.5
    transport = DelayedRestKlineTransport(
        delay_seconds=delay, now_ms=int(fixed_now.timestamp() * 1000)
    )

    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport, timeout=20.0)

    start = time.monotonic()
    seeded_counts = await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        history_dir=temp_storage_dir,  # Empty dir -> falls back to synthetic!
        timeout_seconds=timeout,
        rest_client=client,
        now=fixed_now,
    )
    elapsed = time.monotonic() - start

    # Execution must complete in bounded time (well below the 15.0s mock delay)
    assert elapsed < 3.0, f"Execution took {elapsed:.2f}s, expected < 3.0s bounded fallback"
    assert elapsed >= timeout * 0.8, f"Execution completed too quickly ({elapsed:.2f}s)"

    # All 4 symbols must be seeded with 100 bars each via synthetic fallback cascade
    assert len(seeded_counts) == 4
    for sym in SYMBOLS:
        assert seeded_counts[sym] == 100
        assert len(initialized_engine._bar_history[sym]) == 100
        df = initialized_engine.get_bar_dataframe(sym)
        assert len(df) == 100
        validate_canonical_dataframe(df.set_index("timestamp"))

    await client.aclose()


@pytest.mark.anyio
async def test_asymmetric_timeout_partial_delay_cascades_all_symbols(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    temp_storage_dir: Path,
) -> None:
    """Verify that if some symbols hang while others succeed, all symbols cascade.

    Ensures bounded execution time.
    """
    # Only ETHUSDT and SOLUSDT hang for 15s; BTCUSDT and DOGEUSDT respond quickly
    transport = DelayedRestKlineTransport(
        delay_seconds=15.0,
        delayed_symbols=("ETHUSDT", "SOLUSDT"),
        now_ms=int(fixed_now.timestamp() * 1000),
    )

    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport, timeout=20.0)

    start = time.monotonic()
    seeded_counts = await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        history_dir=temp_storage_dir,  # Fallback to synthetic
        timeout_seconds=0.5,
        rest_client=client,
        now=fixed_now,
    )
    elapsed = time.monotonic() - start

    assert elapsed < 3.0, f"Execution took {elapsed:.2f}s, expected < 3.0s bounded fallback"
    assert elapsed >= 0.5 * 0.8
    for sym in SYMBOLS:
        assert seeded_counts[sym] == 100
        assert len(initialized_engine._bar_history[sym]) == 100

    await client.aclose()


@pytest.mark.anyio
async def test_ultra_fast_timeout_sub_millisecond(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
) -> None:
    """Verify sub-millisecond timeout triggers immediate fallback without crashing."""
    transport = DelayedRestKlineTransport(
        delay_seconds=1.0, now_ms=int(fixed_now.timestamp() * 1000)
    )
    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

    seeded_counts = await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        timeout_seconds=0.001,  # 1 millisecond
        rest_client=client,
        now=fixed_now,
    )
    for sym in SYMBOLS:
        assert seeded_counts[sym] == 100
        assert len(initialized_engine._bar_history[sym]) == 100

    await client.aclose()


@pytest.mark.anyio
async def test_network_connection_drop_mid_warmup(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
) -> None:
    """Verify network connection errors (ConnectError) trigger fallback cascade without crashing."""

    class ErrorTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused by mock remote peer", request=request)

    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=ErrorTransport())

    seeded_counts = await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )
    for sym in SYMBOLS:
        assert seeded_counts[sym] == 100
        assert len(initialized_engine._bar_history[sym]) == 100

    await client.aclose()


# ===========================================================================
# Vector 2: Concurrent Multi-Symbol Warmup (Heterogeneous Tiers)
# ===========================================================================


class HeterogeneousTierMockTransport(httpx.AsyncBaseTransport):
    """Mock transport configured with heterogeneous behavior per symbol:

    - BTCUSDT: HTTP 200 OK (REST success)
    - ETHUSDT: HTTP 500 Error (REST fails -> falls back to Parquet)
    - SOLUSDT: ConnectError (REST fails -> falls back to Parquet)
    - DOGEUSDT: HTTP 429 Rate Limit (REST fails -> Parquet missing -> falls back to Synthetic)
    """

    def __init__(self, now_ms: int = 1788706950000) -> None:
        self.now_ms = now_ms

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        symbol = request.url.params.get("symbol", "")
        if symbol == "BTCUSDT":
            raw_klines = make_mock_kline_payload(symbol, bars_count=105, now_ms=self.now_ms)
            return httpx.Response(200, json=raw_klines)
        if symbol == "ETHUSDT":
            return httpx.Response(500, json={"code": -1000, "msg": "Internal error"})
        if symbol == "SOLUSDT":
            raise httpx.ConnectError("Network dropped for SOL", request=request)
        if symbol == "DOGEUSDT":
            return httpx.Response(
                429,
                headers={"Retry-After": "1"},
                json={"code": -1003, "msg": "Too many requests"},
            )
        return httpx.Response(404, json={"code": -1000, "msg": "Not found"})


@pytest.mark.anyio
async def test_concurrent_multi_symbol_heterogeneous_mixed_tier_warmup(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    fixed_now_ms: int,
) -> None:
    """Verify simultaneous warmup with mixed tiers across all 4 symbols.

    BTC on REST, ETH/SOL on Parquet, DOGE on Synthetic.
    """
    transport = HeterogeneousTierMockTransport(now_ms=fixed_now_ms)
    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

    seeded_counts = await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )

    # 1. Verify all 4 symbols seeded with exactly 100 bars
    assert seeded_counts == {
        "BTCUSDT": 100,
        "ETHUSDT": 100,
        "SOLUSDT": 100,
        "DOGEUSDT": 100,
    }

    # 2. Verify timestamp boundaries match across all 4 symbols despite different sources
    # Expected newest closed bar: (fixed_now_ms // 300_000 - 1) * 300
    expected_newest_epoch_s = ((fixed_now_ms // INTERVAL_5M_MS) - 1) * (INTERVAL_5M_MS // 1000)
    expected_oldest_epoch_s = expected_newest_epoch_s - 99 * 300

    for sym in SYMBOLS:
        history = initialized_engine._bar_history[sym]
        assert len(history) == 100
        oldest_ts = history[0]["timestamp"]
        newest_ts = history[-1]["timestamp"]

        assert int(oldest_ts.timestamp()) == expected_oldest_epoch_s
        assert int(newest_ts.timestamp()) == expected_newest_epoch_s

        # Validate canonical schema and cleanliness
        df = initialized_engine.get_bar_dataframe(sym)
        assert len(df) == 100
        validate_canonical_dataframe(df.set_index("timestamp"))

    await client.aclose()


@pytest.mark.anyio
async def test_concurrent_warmup_with_corrupted_parquet(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
) -> None:
    """Verify that if Parquet is corrupted or missing columns, it falls back to Synthetic."""

    # Mock REST client to always fail
    class FailingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"code": -1000, "msg": "Unavailable"})

    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=FailingTransport())

    # Mock load_parquet_warmup_bars to return None (simulating corrupted file)
    with patch(
        "autonomous_futures.feed.rest_client.load_parquet_warmup_bars",
        return_value=None,
    ):
        seeded_counts = await daemon_mod.seed_historical_warmup_bars(
            engine=initialized_engine,
            symbols=SYMBOLS,
            warmup_bars=100,
            rest_client=client,
            now=fixed_now,
        )

    for sym in SYMBOLS:
        assert seeded_counts[sym] == 100
        history = initialized_engine._bar_history[sym]
        assert len(history) == 100

    await client.aclose()


@pytest.mark.anyio
async def test_repeated_warmup_reseeding_idempotence(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    fixed_now_ms: int,
) -> None:
    """Verify that calling seed_historical_warmup_bars repeatedly does not duplicate bars."""
    transport = HeterogeneousTierMockTransport(now_ms=fixed_now_ms)
    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

    # Initial seeding
    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )
    for sym in SYMBOLS:
        assert len(initialized_engine._bar_history[sym]) == 100

    # Second seeding with same timestamps
    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )
    for sym in SYMBOLS:
        assert len(initialized_engine._bar_history[sym]) == 100

    await client.aclose()


# ===========================================================================
# Vector 3: Feature Evaluation Pipeline Integrity
# ===========================================================================


@pytest.mark.anyio
async def test_causal_feature_evaluation_on_mixed_tier_warmup(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    fixed_now_ms: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify all 4 symbols compute causal features without DataQualityError: timestamp gap."""
    transport = HeterogeneousTierMockTransport(now_ms=fixed_now_ms)
    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )

    caplog.clear()

    # Simulate first incoming WebSocket closed bar at exact next 5m interval
    expected_newest_epoch_s = ((fixed_now_ms // INTERVAL_5M_MS) - 1) * 300
    first_ws_bar_ts = datetime.fromtimestamp(expected_newest_epoch_s + 300, tz=UTC)

    for sym in SYMBOLS:
        cand = initialized_engine.candidates.get(sym)
        assert cand is not None, f"Candidate missing for {sym}"

        # Base price per symbol
        base_p = {"BTCUSDT": 85050.0, "ETHUSDT": 3105.0, "SOLUSDT": 180.5, "DOGEUSDT": 0.1505}[sym]

        step = base_p * 0.001
        ws_bar = make_canonical_bar(
            symbol=sym,
            timestamp=first_ws_bar_ts,
            open_price=Decimal(f"{base_p:.6f}"),
            close_price=Decimal(f"{base_p + step:.6f}"),
            high_price=Decimal(f"{base_p + 2 * step:.6f}"),
            low_price=Decimal(f"{max(0.0001, base_p - step):.6f}"),
            volume=Decimal("150.0"),
            is_closed=True,
        )

        # Ingest finalized candle bar
        initialized_engine._process_closed_bar(ws_bar)

        # History should now have 101 bars
        assert len(initialized_engine._bar_history[sym]) == 101

        # Evaluate feature dataframe directly
        df = initialized_engine.get_bar_dataframe(sym)
        evaluated_df = initialized_engine.signal_evaluator.evaluate(cand, df)

        assert len(evaluated_df) == 101
        last_row = evaluated_df.iloc[-1]
        assert "signal" in last_row
        assert int(last_row["signal"]) in (-1, 0, 1)

    # Verify zero feature evaluation failures or timestamp gap errors in logs
    gap_errors = [
        r.message
        for r in caplog.records
        if "Feature evaluation failed" in r.message or "timestamp gap" in r.message
    ]
    assert not gap_errors, f"Unexpected feature evaluation errors: {gap_errors}"

    await client.aclose()


@pytest.mark.anyio
async def test_multi_bar_continuous_evaluation_without_gaps(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    fixed_now_ms: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify streaming 5 consecutive closed bars across all 4 symbols maintains continuity."""
    transport = HeterogeneousTierMockTransport(now_ms=fixed_now_ms)
    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )

    caplog.clear()
    expected_newest_epoch_s = ((fixed_now_ms // INTERVAL_5M_MS) - 1) * 300

    # Ingest 5 consecutive closed bars
    for step in range(1, 6):
        bar_ts = datetime.fromtimestamp(expected_newest_epoch_s + step * 300, tz=UTC)
        for sym in SYMBOLS:
            ws_bar = make_canonical_bar(
                symbol=sym,
                timestamp=bar_ts,
                open_price=Decimal("100.00"),
                close_price=Decimal(f"{100.00 + step * 0.5:.2f}"),
                is_closed=True,
            )
            initialized_engine._process_closed_bar(ws_bar)
            assert len(initialized_engine._bar_history[sym]) == 100 + step

    gap_errors = [
        r.message
        for r in caplog.records
        if "Feature evaluation failed" in r.message or "timestamp gap" in r.message
    ]
    assert not gap_errors, f"Found unexpected gap errors: {gap_errors}"

    await client.aclose()


@pytest.mark.anyio
async def test_websocket_reconnect_duplicate_bar_preserves_pipeline_integrity(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    fixed_now_ms: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify WebSocket reconnect replaying last closed bar updates in-place without duplicates."""
    transport = HeterogeneousTierMockTransport(now_ms=fixed_now_ms)
    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )

    expected_newest_epoch_s = ((fixed_now_ms // INTERVAL_5M_MS) - 1) * 300
    first_ws_bar_ts = datetime.fromtimestamp(expected_newest_epoch_s + 300, tz=UTC)

    bar1 = make_canonical_bar(
        symbol="BTCUSDT",
        timestamp=first_ws_bar_ts,
        close_price=Decimal("85100.00"),
        is_closed=True,
    )
    initialized_engine._process_closed_bar(bar1)
    assert len(initialized_engine._bar_history["BTCUSDT"]) == 101

    # Simulate WebSocket reconnect replaying the exact same closed bar
    bar1_replay = make_canonical_bar(
        symbol="BTCUSDT",
        timestamp=first_ws_bar_ts,
        close_price=Decimal("85105.00"),  # updated close
        is_closed=True,
    )
    initialized_engine._process_closed_bar(bar1_replay)

    # History count should remain 101, NOT grow to 102
    history = initialized_engine._bar_history["BTCUSDT"]
    assert len(history) == 101
    assert history[-1]["close"] == Decimal("85105.00")

    # Pipeline feature evaluation must succeed cleanly
    cand = initialized_engine.candidates["BTCUSDT"]
    df = initialized_engine.get_bar_dataframe("BTCUSDT")
    evaluated_df = initialized_engine.signal_evaluator.evaluate(cand, df)
    assert len(evaluated_df) == 101

    await client.aclose()


@pytest.mark.anyio
async def test_temporal_gap_detection_and_self_healing(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
    fixed_now_ms: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that a network drop causing a temporal gap triggers self-healing pruning."""
    transport = HeterogeneousTierMockTransport(now_ms=fixed_now_ms)
    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

    await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )

    caplog.clear()
    expected_newest_epoch_s = ((fixed_now_ms // INTERVAL_5M_MS) - 1) * 300

    # Inject a bar that jumps by 20 minutes (4 missing bars)
    discontinuous_bar_ts = datetime.fromtimestamp(expected_newest_epoch_s + 1200, tz=UTC)
    gap_bar = make_canonical_bar(
        symbol="BTCUSDT",
        timestamp=discontinuous_bar_ts,
        is_closed=True,
    )

    initialized_engine._process_closed_bar(gap_bar)

    # History should be pruned of stale pre-gap bars to avoid corrupting indicators
    assert len(initialized_engine._bar_history["BTCUSDT"]) == 1
    assert initialized_engine._bar_history["BTCUSDT"][0]["timestamp"] == discontinuous_bar_ts

    # Verify self-healing warning was logged
    warning_logs = [
        r.message for r in caplog.records if "Timestamp gap detected for BTCUSDT" in r.message
    ]
    assert len(warning_logs) == 1

    await client.aclose()


# ===========================================================================
# Vector 4: Daemon Startup & Strict Safety Invariants
# ===========================================================================


class MockWsMessageSession:
    """Mock WebSocket session providing controlled stream messages."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = list(messages)
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[str]:
        for msg in self.messages:
            if self.closed:
                break
            await asyncio.sleep(0.05)
            yield msg
        # Keep alive until cancelled
        while not self.closed:
            await asyncio.sleep(0.1)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_daemon_startup_with_slow_network_timeout_end_to_end(
    temp_storage_dir: Path,
    fixed_now_ms: int,
    fixed_now: datetime,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify full daemon startup under slow network timeout cascades cleanly to shutdown."""
    ws_bar_open_ms = ((fixed_now_ms // INTERVAL_5M_MS) - 1) * INTERVAL_5M_MS + INTERVAL_5M_MS
    ws_bar_close_ms = ws_bar_open_ms + INTERVAL_5M_MS - 1

    mock_messages = [
        json.dumps(
            {
                "stream": "btcusdt@bookTicker",
                "data": {
                    "u": 1001,
                    "s": "BTCUSDT",
                    "b": "85000.00",
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

    mock_ws = MockWsMessageSession(mock_messages)

    class MockConnectContext:
        async def __aenter__(self) -> MockWsMessageSession:
            return mock_ws

        async def __aexit__(self, *args: object) -> None:
            pass

    # Slow REST transport delaying for 5.0s
    transport = DelayedRestKlineTransport(delay_seconds=5.0, now_ms=fixed_now_ms)
    mock_rest_client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)

    args = daemon_mod.parse_cli_args(
        [
            "--storage-dir",
            str(temp_storage_dir),
            "--duration",
            "1.0",
            "--checkpoint-interval",
            "0.5",
            "--warmup-timeout",
            "0.3",
            "--starting-capital",
            "100.00",
            "--symbols",
            "BTCUSDT",
        ]
    )

    # Align fallback warmup to fixed_now reference time for seamless continuity with ws_bar
    orig_seed = daemon_mod.seed_historical_warmup_bars

    async def seed_with_fixed_now(*args: Any, **kwargs: Any) -> dict[str, int]:
        kwargs.setdefault("now", fixed_now)
        return await orig_seed(*args, **kwargs)

    caplog.clear()
    with (
        patch("websockets.connect", return_value=MockConnectContext()),
        patch(
            "scripts.run_phase_259_live_paper_daemon.BinancePublicRestClient",
            return_value=mock_rest_client,
        ),
        patch(
            "scripts.run_phase_259_live_paper_daemon.seed_historical_warmup_bars",
            side_effect=seed_with_fixed_now,
        ),
        patch("time.time", return_value=fixed_now_ms / 1000.0),
    ):
        summary = await daemon_mod.run_live_paper_daemon(args)

    assert summary is not None
    assert summary["safety_invariants"]["orders_submitted"] == 0
    assert summary["safety_invariants"]["execution_authority"] is False
    assert summary["shared_portfolio_margin"]["zero_balance_drift"] is True

    health_file = temp_storage_dir / "paper-daemon-health.json"
    assert health_file.is_file()
    health = json.loads(health_file.read_text(encoding="utf-8"))
    assert health["daemon_status"] == "SHUTDOWN_CLEAN"
    assert health["zero_order_safety_invariants"]["orders_submitted"] == 0

    gap_errors = [
        r.message
        for r in caplog.records
        if "Feature evaluation failed" in r.message or "timestamp gap" in r.message
    ]
    assert not gap_errors, f"Unexpected gap errors in daemon run: {gap_errors}"


@pytest.mark.anyio
async def test_strict_safety_invariants_during_warmup() -> None:
    """Verify safety assertion rejection when invariants are violated."""
    # Zero orders invariant
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION: orders submitted"):
        daemon_mod.verify_strict_safety_invariants(orders_submitted=1)

    # API key environment pollution
    with patch.dict("os.environ", {"BINANCE_API_KEY": "fake_key_123"}):
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION: private credentials detected"):
            daemon_mod.verify_strict_safety_invariants(orders_submitted=0)


# ===========================================================================
# Vector 5: Additional Adversarial Stress & Edge Case Probing
# ===========================================================================


@pytest.mark.anyio
async def test_boundary_transition_developing_candle_strictly_filtered(
    fixed_now_ms: int,
    fixed_now: datetime,
) -> None:
    """Verify developing candle is strictly stripped out during boundary transition."""
    # Build payload with 100 closed bars + 1 developing candle
    raw_klines = make_mock_kline_payload("BTCUSDT", bars_count=101, now_ms=fixed_now_ms)
    developing_candle_open_ms = (fixed_now_ms // INTERVAL_5M_MS) * INTERVAL_5M_MS
    assert raw_klines[-1][0] == developing_candle_open_ms

    class BoundaryTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=raw_klines)

    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=BoundaryTransport())
    df = await client.fetch_klines("BTCUSDT", limit=100, only_closed=True, now=fixed_now)

    # Must contain only closed bars (newest open_time < developing_candle_open_ms)
    newest_ts = df.index[-1]
    assert int(newest_ts.timestamp() * 1000) < developing_candle_open_ms
    assert len(df) == 100
    await client.aclose()


@pytest.mark.anyio
async def test_corrupted_rest_payload_auto_cascades(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
) -> None:
    """Verify corrupted/NaN REST payload triggers validation failure and cascades to fallback."""

    class CorruptedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            # Kline with negative and NaN prices
            bad_klines = [
                [
                    1788700000000 + i * 300_000,
                    "-100.00",
                    "NaN",
                    "50.00",
                    "0.00",
                    "100.0",
                    1788700000000 + (i + 1) * 300_000 - 1,
                    "0.0",
                    10,
                    "0.0",
                    "0.0",
                    "0",
                ]
                for i in range(100)
            ]
            return httpx.Response(200, json=bad_klines)

    client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=CorruptedTransport())

    # Should cascade to Parquet or Synthetic without crashing
    seeded_counts = await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=SYMBOLS,
        warmup_bars=100,
        rest_client=client,
        now=fixed_now,
    )
    for sym in SYMBOLS:
        assert seeded_counts[sym] == 100
        history = initialized_engine._bar_history[sym]
        assert len(history) == 100
        # Check all values are positive Decimals
        for bar in history:
            assert bar["open"] > Decimal("0")
            assert bar["close"] > Decimal("0")

    await client.aclose()


@pytest.mark.anyio
async def test_high_concurrency_stress_harness_multiple_engines(
    temp_storage_dir: Path,
    fixed_now: datetime,
    fixed_now_ms: int,
) -> None:
    """Run 5 concurrent engines simultaneously seeding history with mixed network latency."""

    async def _run_single_engine(worker_id: int) -> LivePaperEngine:
        engine_storage = temp_storage_dir / f"worker_{worker_id}"
        engine_storage.mkdir(parents=True, exist_ok=True)
        acc = HardenedSharedMarginAccount(starting_capital=DEFAULT_STARTING_CAPITAL)
        mon = CircuitBreakerFeedMonitor(account=acc, symbols=SYMBOLS, max_queue_size=500)
        eng = LivePaperEngine(
            symbols=SYMBOLS,
            starting_capital=DEFAULT_STARTING_CAPITAL,
            ledger_db=engine_storage / "ledger.sqlite3",
            lifecycle_db=engine_storage / "lifecycle.sqlite3",
            observations_db=engine_storage / "obs.sqlite3",
            monitor=mon,
            account=acc,
        )

        transport = HeterogeneousTierMockTransport(now_ms=fixed_now_ms)
        client = BinancePublicRestClient(base_url=DEFAULT_REST_URL, transport=transport)
        counts = await daemon_mod.seed_historical_warmup_bars(
            engine=eng,
            symbols=SYMBOLS,
            warmup_bars=100,
            rest_client=client,
            now=fixed_now,
        )
        assert counts == {s: 100 for s in SYMBOLS}
        await client.aclose()
        return eng

    tasks = [_run_single_engine(i) for i in range(5)]
    engines = await asyncio.gather(*tasks)

    assert len(engines) == 5
    for eng in engines:
        for sym in SYMBOLS:
            assert len(eng._bar_history[sym]) == 100


@pytest.mark.anyio
async def test_unaligned_stale_parquet_self_healing(
    initialized_engine: LivePaperEngine,
    fixed_now: datetime,
) -> None:
    """Verify that stale historical data (from months ago) triggers self-healing on current bar."""
    # Seed 100 bars from 1 year ago (2025-09-06)
    stale_start = datetime(2025, 9, 6, 12, 0, 0, tzinfo=UTC)
    stale_bars = [
        make_canonical_bar(
            symbol="BTCUSDT",
            timestamp=stale_start + timedelta(minutes=5 * i),
            open_price=Decimal("60000.00"),
            close_price=Decimal("60050.00"),
            is_closed=True,
        )
        for i in range(100)
    ]
    initialized_engine.seed_history("BTCUSDT", stale_bars)
    assert len(initialized_engine._bar_history["BTCUSDT"]) == 100

    # Ingest a live bar from today (2026-09-06)
    live_bar = make_canonical_bar(
        symbol="BTCUSDT",
        timestamp=fixed_now.replace(minute=0, second=0, microsecond=0),
        open_price=Decimal("85000.00"),
        close_price=Decimal("85050.00"),
        is_closed=True,
    )

    initialized_engine._process_closed_bar(live_bar)

    # History should have been pruned to prevent computing corrupt indicators across a 1-year gap
    history = initialized_engine._bar_history["BTCUSDT"]
    assert len(history) == 1
    assert history[0]["timestamp"] == live_bar.timestamp
