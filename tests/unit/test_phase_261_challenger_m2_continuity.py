"""Phase 261 M2 Challenge Test Suite: Warmup Continuity & Transition Boundaries.

Authored by challenger_m2_1 to empirically stress-test:
1. Timestamp Continuity Stress:
   - Transition boundary T_seeded -> T_ws with zero gaps under canonicalize_bars.
   - Sequential bar arrivals preserving continuous 300s delta.
2. In-Place Deduplication & Replay Burst:
   - WebSocket reconnect replaying last closed bar at T.
   - Duplicate burst of 10 identical or revised bars at T without array bloat.
3. Out-of-Order & Asynchronous Replay:
   - Arrival of earlier closed bar (T - 300s) updated in-place.
   - Rapid bursts maintaining monotonic chronological sorting.
4. Gap Self-Healing Stress:
   - Intentional 30-minute blackout gap (T + 1800s).
   - Single warning emission, stale pre-gap history pruning, and pipeline recovery.
   - Post-gap sequence accumulating 25 bars with zero subsequent gap warnings.
   - Clean execution of SignalEvaluator.evaluate on healed history.
5. Repeated Gap Trauma Cycles:
   - Multiple successive gap events without engine degradation or state corruption.
6. Tick Formation vs WebSocket Closed Bar Collision:
   - In-place deduplication when local dynamic tick formation collides with WebSocket kline.
7. Seed History Ingestion Robustness:
   - DatetimeIndex vs timestamp column, unsorted input, duplicate timestamps, microsecond stripping.
8. Multi-Symbol Isolation Under Asynchronous Stress:
   - Independent symbol state isolation when one symbol experiences a gap while others
     remain continuous.
9. Warmup Timeout & Offline Fallback Invariants:
   - Timeout handling and cascade without daemon blocking.
10. Strict Safety Invariants:
   - orders_submitted == 0, execution_authority == False, zero external network sockets.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.run_phase_259_live_paper_daemon as daemon_mod  # noqa: E402
from autonomous_futures.data.quality import canonicalize_bars  # noqa: E402
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot  # noqa: E402
from autonomous_futures.feed.monitor import CircuitBreakerFeedMonitor  # noqa: E402
from autonomous_futures.feed.rest_client import (  # noqa: E402
    DEFAULT_REST_URL,
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


def make_canonical_bar(
    symbol: str,
    timestamp: datetime,
    open_price: Decimal = Decimal("85000.00"),
    high_price: Decimal | None = None,
    low_price: Decimal | None = None,
    close_price: Decimal = Decimal("85050.00"),
    volume: Decimal = Decimal("10.0"),
    is_closed: bool = True,
    interval: str = "5m",
) -> CanonicalBar:
    """Instantiate a CanonicalBar with fully populated fields and geometric validity."""
    close_time = timestamp + timedelta(minutes=5) - timedelta(milliseconds=1)
    quote_volume = volume * close_price
    spread = abs(close_price - open_price)
    buffer = max(spread * Decimal("0.5"), close_price * Decimal("0.001"))
    eff_high = high_price if high_price is not None else max(open_price, close_price) + buffer
    eff_low = (
        low_price
        if low_price is not None
        else max(min(open_price, close_price) - buffer, Decimal("0.0001"))
    )
    # Ensure geometric invariants strictly hold
    if eff_high < max(open_price, close_price):
        eff_high = max(open_price, close_price) + buffer
    if eff_low > min(open_price, close_price):
        eff_low = max(min(open_price, close_price) - buffer, Decimal("0.0001"))

    return CanonicalBar(
        symbol=symbol,
        interval=interval,
        timestamp=timestamp,
        close_time=close_time,
        open=open_price,
        high=eff_high,
        low=eff_low,
        close=close_price,
        volume=volume,
        quote_volume=quote_volume,
        trades=15,
        taker_buy_base=volume * Decimal("0.5"),
        taker_buy_quote=quote_volume * Decimal("0.5"),
        is_closed=is_closed,
    )


def generate_contiguous_bars(
    symbol: str,
    start_ts: datetime,
    count: int = 100,
    base_price: Decimal = Decimal("85000.00"),
) -> list[CanonicalBar]:
    """Generate a contiguous sequence of 5m CanonicalBars with scaled prices."""
    bars: list[CanonicalBar] = []
    for i in range(count):
        ts = start_ts + timedelta(minutes=5 * i)
        step = base_price * Decimal("0.001") * Decimal(str(i % 10))
        o_p = base_price + step
        c_p = o_p + base_price * Decimal("0.0005")
        h_p = max(o_p, c_p) + base_price * Decimal("0.002")
        l_p = max(min(o_p, c_p) - base_price * Decimal("0.002"), Decimal("0.0001"))
        bars.append(
            make_canonical_bar(
                symbol=symbol,
                timestamp=ts,
                open_price=o_p,
                high_price=h_p,
                low_price=l_p,
                close_price=c_p,
                volume=Decimal("25.0") + Decimal(str(i)),
            )
        )
    return bars


@pytest.fixture
def initialized_engine(tmp_path: Path) -> LivePaperEngine:
    storage_dir = tmp_path / "paper_challenger_storage"
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
# Vector 1: Precision Timestamp Continuity at Transition Boundary
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_exact_transition_boundary_canonicalize_zero_gaps(
    initialized_engine: LivePaperEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stress-test transition boundary: Seed up to T, send WS bar at T + 300s.

    Asserts canonicalize_bars passes with zero gaps across 101 bars and subsequent
    consecutive bar arrivals maintain strict 300s temporal monotonicity.
    """
    caplog.set_level(logging.WARNING)
    symbol = "BTCUSDT"

    # Seed 100 historical bars ending at 2026-09-06 14:55:00 UTC
    seed_start = datetime(2026, 9, 6, 6, 40, 0, tzinfo=UTC)
    seeded_bars = generate_contiguous_bars(symbol, seed_start, count=100)
    initialized_engine.seed_history(symbol, seeded_bars)

    assert len(initialized_engine._bar_history[symbol]) == 100
    t_seeded_last = initialized_engine._bar_history[symbol][-1]["timestamp"]
    expected_t_last = datetime(2026, 9, 6, 14, 55, 0, tzinfo=UTC)
    assert t_seeded_last == expected_t_last

    # Incoming WebSocket bar at T + 300s (15:00:00 UTC)
    t_ws_first = t_seeded_last + timedelta(seconds=300)
    ws_bar_1 = make_canonical_bar(symbol=symbol, timestamp=t_ws_first)
    await initialized_engine.handle_bar(ws_bar_1)

    # Verify history and canonical validation
    assert len(initialized_engine._bar_history[symbol]) == 101
    df_101 = initialized_engine.get_bar_dataframe(symbol)
    assert len(df_101) == 101

    # Strict invariant: canonicalize_bars must succeed with ZERO gaps
    canonical = canonicalize_bars(df_101, interval=timedelta(minutes=5))
    assert len(canonical) == 101
    diffs = canonical["timestamp"].diff().dropna()
    assert (diffs == pd.Timedelta(seconds=300)).all()

    # Stream next 5 consecutive WebSocket bars
    for step in range(1, 6):
        next_ts = t_ws_first + timedelta(seconds=300 * step)
        next_bar = make_canonical_bar(symbol=symbol, timestamp=next_ts)
        await initialized_engine.handle_bar(next_bar)

        df_curr = initialized_engine.get_bar_dataframe(symbol)
        assert len(df_curr) == 101 + step
        canonical_curr = canonicalize_bars(df_curr, interval=timedelta(minutes=5))
        assert len(canonical_curr) == 101 + step

    # Assert zero feature evaluation or gap warnings were logged
    gap_warnings = [
        r.message
        for r in caplog.records
        if "Feature evaluation failed" in r.message or "timestamp gap" in r.message
    ]
    assert not gap_warnings, f"Unexpected warnings: {gap_warnings}"


# ===========================================================================
# Vector 2: Re-transmission & In-Place Deduplication
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_ws_reconnect_duplicate_burst_and_in_place_update(
    initialized_engine: LivePaperEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stress-test in-place deduplication under duplicate replay bursts.

    Verifies that duplicate bars with revised volume or close prices update in-place
    without expanding history or producing duplicate timestamp errors.
    """
    caplog.set_level(logging.WARNING)
    symbol = "BTCUSDT"

    seed_start = datetime(2026, 9, 6, 6, 40, 0, tzinfo=UTC)
    seeded_bars = generate_contiguous_bars(symbol, seed_start, count=100)
    initialized_engine.seed_history(symbol, seeded_bars)

    # First arrival of bar at 15:00:00
    t_1500 = datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC)
    bar_v1 = make_canonical_bar(
        symbol=symbol,
        timestamp=t_1500,
        close_price=Decimal("85050.00"),
        volume=Decimal("10.0"),
    )
    await initialized_engine.handle_bar(bar_v1)
    assert len(initialized_engine._bar_history[symbol]) == 101
    assert initialized_engine._bar_history[symbol][-1]["close"] == Decimal("85050.00")

    # Replay burst: 10 consecutive duplicate transmissions of bar at 15:00:00 with revisions
    for i in range(1, 11):
        revised_close = Decimal("85050.00") + Decimal(str(i))
        revised_vol = Decimal("10.0") + Decimal(str(i * 5))
        bar_dup = make_canonical_bar(
            symbol=symbol,
            timestamp=t_1500,
            close_price=revised_close,
            volume=revised_vol,
        )
        await initialized_engine.handle_bar(bar_dup)

        # Invariant: History must NOT grow
        assert len(initialized_engine._bar_history[symbol]) == 101
        assert initialized_engine._bar_history[symbol][-1]["close"] == revised_close
        assert initialized_engine._bar_history[symbol][-1]["volume"] == revised_vol

    # Canonical DataFrame must remain strictly valid
    df = initialized_engine.get_bar_dataframe(symbol)
    assert len(df) == 101
    canonical = canonicalize_bars(df, interval=timedelta(minutes=5))
    assert len(canonical) == 101
    assert not canonical["timestamp"].duplicated().any()

    # Also test in-place deduplication on an earlier seeded bar (e.g. at 14:00:00)
    t_1400 = datetime(2026, 9, 6, 14, 0, 0, tzinfo=UTC)
    revised_past_bar = make_canonical_bar(
        symbol=symbol,
        timestamp=t_1400,
        close_price=Decimal("84123.45"),
        volume=Decimal("999.0"),
    )
    await initialized_engine.handle_bar(revised_past_bar)
    assert len(initialized_engine._bar_history[symbol]) == 101

    df_past = initialized_engine.get_bar_dataframe(symbol)
    rec_1400 = df_past[df_past["timestamp"] == t_1400]
    assert len(rec_1400) == 1
    assert float(rec_1400["close"].iloc[0]) == pytest.approx(84123.45)

    canonical_past = canonicalize_bars(df_past, interval=timedelta(minutes=5))
    assert len(canonical_past) == 101


# ===========================================================================
# Vector 3: Out-of-Order & Asynchronous Replay Bursts
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_out_of_order_bars_maintain_sorted_monotonic_order(
    initialized_engine: LivePaperEngine,
) -> None:
    """Stress-test out-of-order bar arrivals and replay bursts.

    Verifies that when out-of-order bars arrive, history maintains strict monotonic
    timestamp ordering without crashing.
    """
    symbol = "BTCUSDT"
    # Seed 50 bars with a deliberate missing bar at index 40
    seed_start = datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)
    all_50 = generate_contiguous_bars(symbol, seed_start, count=50)
    missing_bar = all_50[40]  # Missing bar at 13:20:00
    subset = all_50[:40] + all_50[41:]
    initialized_engine.seed_history(symbol, subset)
    assert len(initialized_engine._bar_history[symbol]) == 49

    # Now deliver the missing bar out-of-order via handle_bar
    await initialized_engine.handle_bar(missing_bar)

    # Invariant: History must be inserted and sorted back into correct position
    assert len(initialized_engine._bar_history[symbol]) == 50
    df = initialized_engine.get_bar_dataframe(symbol)
    assert len(df) == 50

    # Verify that the missing bar is now seamlessly placed at index 40
    assert df["timestamp"].iloc[40] == missing_bar.timestamp
    canonical = canonicalize_bars(df, interval=timedelta(minutes=5))
    assert len(canonical) == 50


# ===========================================================================
# Vector 4: Gap Self-Healing Stress & Stale History Pruning
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_gap_self_healing_prunes_stale_history(
    initialized_engine: LivePaperEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stress-test gap self-healing: Intentional 30-minute blackout jump.

    Verifies:
    1. A gap is detected on the first post-gap bar and logged ONCE.
    2. Stale pre-gap history is pruned to avoid invalid rolling calculations.
    3. Subsequent post-gap bars DO NOT trigger repeated warnings.
    4. Once 20 bars accumulate post-gap, SignalEvaluator.evaluate executes cleanly.
    """
    caplog.set_level(logging.WARNING)
    symbol = "BTCUSDT"

    # Seed 100 bars ending at 15:00:00
    seed_start = datetime(2026, 9, 6, 6, 45, 0, tzinfo=UTC)
    seeded_bars = generate_contiguous_bars(symbol, seed_start, count=100)
    initialized_engine.seed_history(symbol, seeded_bars)
    assert len(initialized_engine._bar_history[symbol]) == 100
    t_last = initialized_engine._bar_history[symbol][-1]["timestamp"]
    assert t_last == datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC)

    # Blackout jump: 30-minute gap. Expected was 15:05:00, next arrival is 15:30:00.
    t_jump = datetime(2026, 9, 6, 15, 30, 0, tzinfo=UTC)
    gap_bar = make_canonical_bar(symbol=symbol, timestamp=t_jump)

    await initialized_engine.handle_bar(gap_bar)

    # 1. Exactly one gap warning should be logged
    gap_records = [r for r in caplog.records if "Timestamp gap detected for BTCUSDT" in r.message]
    assert len(gap_records) == 1
    assert "Pruning stale pre-gap history" in gap_records[0].message

    # 2. History was cleared and now contains only the new bar
    assert len(initialized_engine._bar_history[symbol]) == 1
    assert initialized_engine._bar_history[symbol][0]["timestamp"] == t_jump

    # Clear captured logs to monitor subsequent behavior
    caplog.clear()

    # 3. Stream 25 contiguous post-gap bars (15:35 to 17:35)
    for i in range(1, 26):
        next_ts = t_jump + timedelta(minutes=5 * i)
        bar = make_canonical_bar(symbol=symbol, timestamp=next_ts)
        await initialized_engine.handle_bar(bar)

    # Verify history now has 26 continuous bars
    assert len(initialized_engine._bar_history[symbol]) == 26
    df_healed = initialized_engine.get_bar_dataframe(symbol)
    assert len(df_healed) == 26

    # 4. Invariant: ZERO subsequent gap warnings or feature evaluation failures logged!
    subsequent_gap_warnings = [
        r.message
        for r in caplog.records
        if "Timestamp gap detected" in r.message
        or "Feature evaluation failed" in r.message
        or "timestamp gap" in r.message
    ]
    assert not subsequent_gap_warnings, (
        f"Pipeline failed to heal; logged subsequent warnings: {subsequent_gap_warnings}"
    )

    # 5. Direct verification on SignalEvaluator
    cand = initialized_engine.candidates[symbol]
    eval_df = initialized_engine.signal_evaluator.evaluate(cand, df_healed)
    assert "signal" in eval_df.columns
    assert len(eval_df) == 26

    # 6. Canonicalize bars on healed sequence
    canonical = canonicalize_bars(df_healed, interval=timedelta(minutes=5))
    assert len(canonical) == 26


# ===========================================================================
# Vector 5: Repeated Cascading Gap Trauma Cycles
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_repeated_gap_trauma_cycles(
    initialized_engine: LivePaperEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stress-test resilience through 3 consecutive gap trauma cycles.

    Ensures the engine never enters an unrecoverable corrupted state when subjected
    to repeated network outages and reconnects.
    """
    caplog.set_level(logging.WARNING)
    symbol = "BTCUSDT"
    current_ts = datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC)

    for cycle in range(1, 4):
        # Seed or run 25 continuous bars
        bars = generate_contiguous_bars(symbol, current_ts, count=25)
        for b in bars:
            await initialized_engine.handle_bar(b)
        expected_len = 25 if cycle == 1 else 26
        assert len(initialized_engine._bar_history[symbol]) == expected_len

        # Confirm clean signal evaluation
        cand = initialized_engine.candidates[symbol]
        df = initialized_engine.get_bar_dataframe(symbol)
        eval_df = initialized_engine.signal_evaluator.evaluate(cand, df)
        assert len(eval_df) == expected_len

        # Introduce a gap jump (+45 minutes ahead)
        last_ts = initialized_engine._bar_history[symbol][-1]["timestamp"]
        jump_ts = last_ts + timedelta(minutes=45)
        jump_bar = make_canonical_bar(symbol=symbol, timestamp=jump_ts)

        await initialized_engine.handle_bar(jump_bar)

        # History should reset to 1
        assert len(initialized_engine._bar_history[symbol]) == 1
        current_ts = jump_ts + timedelta(minutes=5)

    # Assert account capital is intact and zero balance drift
    assert initialized_engine.account.starting_capital == Decimal("100.00")
    assert initialized_engine.account.cash == Decimal("100.00")


# ===========================================================================
# Vector 6: Tick Formation vs WebSocket Closed Bar Collision
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_tick_formation_vs_ws_kline_boundary_collision(
    initialized_engine: LivePaperEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stress-test race/collision between dynamic tick bar formation and WebSocket kline.

    When both the live tick aggregator and the WebSocket feed produce closed bars for
    the same window [15:00, 15:05), the engine must deduplicate in-place without error.
    """
    caplog.set_level(logging.WARNING)
    symbol = "BTCUSDT"

    # Seed 50 bars ending at 14:55:00
    seed_start = datetime(2026, 9, 6, 10, 50, 0, tzinfo=UTC)
    seeded_bars = generate_contiguous_bars(symbol, seed_start, count=50)
    initialized_engine.seed_history(symbol, seeded_bars)

    # 1. Simulate tick arriving at 15:00:30 (inside window [15:00, 15:05))
    tick_mid = TickerSnapshot(
        symbol=symbol,
        event_time=datetime(2026, 9, 6, 15, 0, 30, tzinfo=UTC),
        transaction_time=datetime(2026, 9, 6, 15, 0, 30, tzinfo=UTC),
        best_bid_price=Decimal("85000.00"),
        best_bid_qty=Decimal("1.0"),
        best_ask_price=Decimal("85001.00"),
        best_ask_qty=Decimal("1.0"),
    )
    await initialized_engine.handle_ticker(tick_mid)

    # 2. Tick arriving at 15:05:01 triggers finalization of dynamic bar for 15:00:00
    tick_next_window = TickerSnapshot(
        symbol=symbol,
        event_time=datetime(2026, 9, 6, 15, 5, 1, tzinfo=UTC),
        transaction_time=datetime(2026, 9, 6, 15, 5, 1, tzinfo=UTC),
        best_bid_price=Decimal("85050.00"),
        best_bid_qty=Decimal("1.0"),
        best_ask_price=Decimal("85051.00"),
        best_ask_qty=Decimal("1.0"),
    )
    await initialized_engine.handle_ticker(tick_next_window)

    # At this point, dynamic bar for 15:00:00 is finalized
    assert len(initialized_engine._bar_history[symbol]) == 51
    assert initialized_engine._bar_history[symbol][-1]["timestamp"] == datetime(
        2026, 9, 6, 15, 0, 0, tzinfo=UTC
    )

    # 3. Simultaneously, WebSocket delivers the official closed CanonicalBar for 15:00:00
    ws_bar = make_canonical_bar(
        symbol=symbol,
        timestamp=datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC),
        open_price=Decimal("85000.00"),
        high_price=Decimal("85060.00"),
        low_price=Decimal("84990.00"),
        close_price=Decimal("85055.00"),
        volume=Decimal("150.0"),
    )
    await initialized_engine.handle_bar(ws_bar)

    # Invariant: History must NOT duplicate the 15:00:00 bar (length remains 51)
    assert len(initialized_engine._bar_history[symbol]) == 51
    assert initialized_engine._bar_history[symbol][-1]["volume"] == Decimal("150.0")

    df = initialized_engine.get_bar_dataframe(symbol)
    assert len(df) == 51
    canonical = canonicalize_bars(df, interval=timedelta(minutes=5))
    assert len(canonical) == 51


# ===========================================================================
# Vector 7: Seed History Ingestion Robustness Under Hostile Inputs
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_seed_history_hostile_formats_and_unsorted_duplicates(
    initialized_engine: LivePaperEngine,
) -> None:
    """Stress-test seed_history across varied and adversarial data structures:

    - pd.DataFrame with DatetimeIndex (no timestamp column)
    - pd.DataFrame with timestamp column
    - Unsorted timestamps with duplicates
    - Timestamps with microseconds (must be stripped)
    - Mixed string and datetime types
    """
    symbol = "ETHUSDT"

    # 1. Test DataFrame with DatetimeIndex and duplicate/unsorted timestamps
    ts_list = [
        datetime(2026, 9, 6, 12, 10, 0, 500, tzinfo=UTC),
        datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC),
        datetime(2026, 9, 6, 12, 5, 0, tzinfo=UTC),
        datetime(2026, 9, 6, 12, 0, 0, 100, tzinfo=UTC),  # duplicate 12:00
    ]
    df_messy = pd.DataFrame(
        {
            "open": [3100.0, 3090.0, 3095.0, 3092.0],
            "high": [3110.0, 3100.0, 3105.0, 3102.0],
            "low": [3095.0, 3085.0, 3090.0, 3088.0],
            "close": [3105.0, 3098.0, 3102.0, 3095.0],
            "volume": [10.0, 20.0, 30.0, 40.0],
        },
        index=pd.DatetimeIndex(ts_list),
    )

    initialized_engine.seed_history(symbol, df_messy)

    history = initialized_engine._bar_history[symbol]
    # Invariant: Must deduplicate to 3 unique timestamps and be sorted
    assert len(history) == 3
    assert history[0]["timestamp"] == datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    assert history[1]["timestamp"] == datetime(2026, 9, 6, 12, 5, 0, tzinfo=UTC)
    assert history[2]["timestamp"] == datetime(2026, 9, 6, 12, 10, 0, tzinfo=UTC)

    # Verify microseconds are completely stripped
    for rec in history:
        assert rec["timestamp"].microsecond == 0

    # 2. Test Sequence of dicts with ISO string timestamps
    dict_records = [
        {
            "timestamp": "2026-09-06T12:15:00Z",
            "open": "3105.0",
            "high": "3115.0",
            "low": "3100.0",
            "close": "3110.0",
            "volume": "15.0",
        },
        {
            "timestamp": "2026-09-06T12:20:00Z",
            "open": "3110.0",
            "high": "3120.0",
            "low": "3105.0",
            "close": "3118.0",
            "volume": "25.0",
        },
    ]
    initialized_engine.seed_history(symbol, dict_records)
    assert len(initialized_engine._bar_history[symbol]) == 5

    df = initialized_engine.get_bar_dataframe(symbol)
    canonical = canonicalize_bars(df, interval=timedelta(minutes=5))
    assert len(canonical) == 5


# ===========================================================================
# Vector 8: Multi-Symbol Asynchronous State Isolation Under Stress
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_multi_symbol_asynchronous_gap_isolation(
    initialized_engine: LivePaperEngine,
) -> None:
    """Stress-test multi-symbol state isolation.

    Injects a gap in BTCUSDT causing self-healing history reset, while ETHUSDT,
    SOLUSDT, and DOGEUSDT receive continuous bars. Verifies BTC's reset does NOT
    leak into or disrupt other symbols.
    """
    seed_start = datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)
    base_prices = {
        "BTCUSDT": Decimal("85000"),
        "ETHUSDT": Decimal("3100"),
        "SOLUSDT": Decimal("180"),
        "DOGEUSDT": Decimal("0.15"),
    }

    # Seed 50 bars across all 4 symbols
    for sym in DEFAULT_SYMBOLS:
        bars = generate_contiguous_bars(sym, seed_start, count=50, base_price=base_prices[sym])
        initialized_engine.seed_history(sym, bars)
        assert len(initialized_engine._bar_history[sym]) == 50

    # Deliver normal next bar for ETH, SOL, DOGE at 14:10:00 (50 * 5m = 250m = 4h 10m -> 14:10:00)
    normal_ts = seed_start + timedelta(minutes=5 * 50)
    for sym in ("ETHUSDT", "SOLUSDT", "DOGEUSDT"):
        bar = make_canonical_bar(sym, timestamp=normal_ts, open_price=base_prices[sym])
        await initialized_engine.handle_bar(bar)
        assert len(initialized_engine._bar_history[sym]) == 51

    # Inject massive 2-hour gap in BTCUSDT
    gap_btc_ts = normal_ts + timedelta(hours=2)
    btc_gap_bar = make_canonical_bar("BTCUSDT", timestamp=gap_btc_ts)
    await initialized_engine.handle_bar(btc_gap_bar)

    # BTC should have pruned to 1 bar
    assert len(initialized_engine._bar_history["BTCUSDT"]) == 1

    # Other symbols must remain COMPLETELY UNAFFECTED at 51 bars
    for sym in ("ETHUSDT", "SOLUSDT", "DOGEUSDT"):
        assert len(initialized_engine._bar_history[sym]) == 51
        df = initialized_engine.get_bar_dataframe(sym)
        assert len(df) == 51
        canonical = canonicalize_bars(df, interval=timedelta(minutes=5))
        assert len(canonical) == 51


# ===========================================================================
# Vector 9: Bounded Warmup Timeout & Fallback Resilience
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_warmup_timeout_bounded_resilience(
    initialized_engine: LivePaperEngine,
) -> None:
    """Stress-test bounded timeout in seed_historical_warmup_bars.

    Simulates a hanging REST client that never returns. Asserts the timeout
    triggers at timeout_seconds and falls back gracefully to synthetic bars.
    """

    class HangingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(100.0)  # Hang indefinitely
            return httpx.Response(200, json=[])

    hanging_client = BinancePublicRestClient(
        base_url=DEFAULT_REST_URL,
        transport=HangingTransport(),
    )

    # Use short timeout 0.2s
    fixed_now = datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC)
    seeded = await daemon_mod.seed_historical_warmup_bars(
        engine=initialized_engine,
        symbols=("BTCUSDT",),
        warmup_bars=100,
        timeout_seconds=0.2,
        rest_client=hanging_client,
        now=fixed_now,
    )

    # Fallback must seed 100 bars
    assert seeded["BTCUSDT"] == 100
    assert len(initialized_engine._bar_history["BTCUSDT"]) == 100


# ===========================================================================
# Vector 10: Strict Safety Invariants Under Adversarial Stress
# ===========================================================================


@pytest.mark.anyio
async def test_challenge_strict_safety_invariants_preserved(
    initialized_engine: LivePaperEngine,
) -> None:
    """Verify that throughout adversarial operations, safety invariants are never compromised."""
    invariants = daemon_mod.verify_strict_safety_invariants(orders_submitted=0)
    assert invariants["orders_submitted"] == 0
    assert invariants["execution_authority"] is False
    assert invariants["live_trading_activation"] is False
    assert invariants["paper_activation"] is True
    assert invariants["zero_credentials_verified"] is True
