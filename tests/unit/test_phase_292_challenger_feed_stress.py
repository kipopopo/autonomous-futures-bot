"""Adversarial challenger stress tests for Phase 292: Live Public Market Ingress.

Empirically tests and stress-tests:
1. Wire parsing resilience: crossed-book prices, malformed JSON, negative prices/quantities,
   extreme float inputs, out-of-order timestamps, non-finite values, and the P=0.00000000 bug.
2. Exponential backoff & jitter behavior: progression formula (0.5s -> 1.0s -> 2.0s -> ...),
   jitter statistical bounds (+0.1..0.4s), and reset after 30s.
3. Sequence deduplication & gap tracking: duplicate depth updates (u <= last_u),
   gap jumps (pu != last_u), duplicate trade IDs (a <= last_a), out-of-order mark prices,
   and multi-symbol isolation.
4. Stream consumer fault tolerance: corrupted JSON, primitives, RPC envelopes, and latency.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.client import (  # noqa: E402
    BinancePublicFeedClient,
    PublicMarketStreamSequencer,
)
from autonomous_futures.feed.models import (  # noqa: E402
    OrderBookDepthSnapshot,
    OrderBookLevel,
    _ensure_strict_decimal,
    ms_to_utc_datetime,
    parse_binance_agg_trade,
    parse_binance_depth5,
    parse_binance_mark_price,
)
from autonomous_futures.feed.telemetry import FeedTelemetryAccumulator  # noqa: E402

# =====================================================================
# 1. Wire Parsing Resilience & Invariant Stress Tests
# =====================================================================


def test_wire_parser_crossed_book_rejection() -> None:
    """Best bid strictly greater than best ask must be rejected with ValueError."""
    crossed_payload = {
        "s": "BTCUSDT",
        "u": 1005,
        "b": [["65005.00", "1.000"], ["65000.00", "2.000"]],
        "a": [["65001.00", "1.000"], ["65002.00", "2.000"]],
        "E": 1726912800000,
    }
    with pytest.raises(ValueError, match="crossed book detected"):
        parse_binance_depth5(crossed_payload)


def test_wire_parser_locked_book_acceptance() -> None:
    """Locked book (best_bid == best_ask) must be accepted with spread == 0 and spread_bps == 0."""
    locked_payload = {
        "s": "BTCUSDT",
        "u": 1005,
        "b": [["65000.00", "1.000"]],
        "a": [["65000.00", "1.000"]],
        "E": 1726912800000,
    }
    snap = parse_binance_depth5(locked_payload)
    assert snap.best_bid_price == Decimal("65000.00")
    assert snap.best_ask_price == Decimal("65000.00")
    assert snap.spread == Decimal("0.00")
    assert snap.spread_bps == Decimal("0")


def test_wire_parser_negative_and_zero_values_stress() -> None:
    """Negative prices/quantities and zero prices must be rejected."""
    # Negative bid price in depth
    with pytest.raises((ValueError, ValidationError)):
        parse_binance_depth5(
            {
                "s": "BTCUSDT",
                "u": 1,
                "b": [["-100.0", "1.0"]],
                "a": [["105.0", "1.0"]],
                "E": 1000,
            }
        )

    # Zero bid price in depth (price must be strictly positive)
    with pytest.raises((ValueError, ValidationError)):
        parse_binance_depth5(
            {
                "s": "BTCUSDT",
                "u": 1,
                "b": [["0.00", "1.0"]],
                "a": [["105.0", "1.0"]],
                "E": 1000,
            }
        )

    # Negative quantity in depth
    with pytest.raises((ValueError, ValidationError)):
        parse_binance_depth5(
            {
                "s": "BTCUSDT",
                "u": 1,
                "b": [["100.0", "-1.0"]],
                "a": [["105.0", "1.0"]],
                "E": 1000,
            }
        )

    # Zero quantity in depth is ALLOWED (level removal semantics in depth orderbooks)
    snap = parse_binance_depth5(
        {
            "s": "BTCUSDT",
            "u": 1,
            "b": [["100.0", "0.0"]],
            "a": [["105.0", "1.0"]],
            "E": 1000,
        }
    )
    assert snap.bids[0].quantity == Decimal("0.0")

    # Zero quantity in AggregateTrade must be REJECTED (a real trade cannot have 0 size)
    with pytest.raises((ValueError, ValidationError)):
        parse_binance_agg_trade(
            {
                "s": "BTCUSDT",
                "a": 1,
                "p": "65000.00",
                "q": "0.000",
                "T": 1000,
                "m": True,
            }
        )

    # Zero price in AggregateTrade must be REJECTED
    with pytest.raises((ValueError, ValidationError)):
        parse_binance_agg_trade(
            {
                "s": "BTCUSDT",
                "a": 1,
                "p": "0.00",
                "q": "1.000",
                "T": 1000,
                "m": True,
            }
        )

    # Negative funding rate in MarkPriceSnapshot is ALLOWED (funding rates can be negative)
    mark_neg_funding = parse_binance_mark_price(
        {
            "s": "BTCUSDT",
            "p": "65000.00",
            "i": "65000.00",
            "r": "-0.00037500",
            "T": 1726934400000,
            "E": 1726912800000,
        }
    )
    assert mark_neg_funding.funding_rate == Decimal("-0.00037500")


def test_wire_parser_p_zero_flaw_empirical_reproduction() -> None:
    """CRITICAL BUG EMPIRICAL REPRODUCTION:

    On Binance Futures USDⓈ-M, 'P' (Estimated Settle Price) is set to '0.00000000'
    for contracts outside the settlement window (active on over 130 Binance symbols like
    FIOUSDT, RAYUSDT, NTRNUSDT, FTMUSDT).
    Because MarkPriceSnapshot annotates estimated_settle_price as StrictPositiveDecimal | None
    (requiring gt=0) and parse_binance_mark_price does not convert '0.00000000' to None,
    incoming mark price frames fail with ValidationError!
    """
    payload = {
        "e": "markPriceUpdate",
        "E": 1726912800000,
        "s": "RAYUSDT",
        "p": "1.52000000",
        "i": "1.52100000",
        "P": "0.00000000",  # Actual Binance live value
        "r": "0.00010000",
        "T": 1726934400000,
    }

    # EMPIRICAL PROOF: This raises ValidationError due to StrictPositiveDecimal constraint
    with pytest.raises(ValidationError) as exc_info:
        parse_binance_mark_price(payload)

    err = exc_info.value
    assert "estimated_settle_price" in str(err)
    assert "Input should be greater than 0" in str(err)


def test_wire_parser_extreme_numerics_and_float_rejection() -> None:
    """Ensure float primitives and non-finite strings are strictly rejected."""
    # Float rejection in depth
    with pytest.raises(ValueError, match="Float values are strictly forbidden"):
        OrderBookLevel(price=65000.5, quantity=Decimal("1.0"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Float values are strictly forbidden"):
        _ensure_strict_decimal(65000.5, "price")

    # Non-finite strings (NaN, Infinity, -Infinity)
    for bad in ("NaN", "Infinity", "-Infinity", "+Infinity", "sNaN"):
        with pytest.raises(ValueError, match="(Non-finite Decimal|Invalid decimal value)"):
            _ensure_strict_decimal(bad, "price")

    # Boolean values must be rejected
    with pytest.raises(ValueError, match="Boolean values are forbidden"):
        _ensure_strict_decimal(True, "price")

    # High precision decimals (18 decimal places) must be parsed exactly without precision loss
    dec = _ensure_strict_decimal("0.000000000000000001", "quantity")
    assert dec == Decimal("0.000000000000000001")
    assert f"{dec:f}" == "0.000000000000000001"

    # Large values (10^12)
    large_dec = _ensure_strict_decimal("999999999999.9999", "price")
    assert large_dec == Decimal("999999999999.9999")


def test_wire_parser_timestamp_anomalies() -> None:
    """Test negative timestamps, non-integers, and non-UTC timezone awareness."""
    # Negative epoch ms
    with pytest.raises(ValueError, match="timestamp_ms must be non-negative"):
        ms_to_utc_datetime(-1000)

    # Boolean ms
    with pytest.raises(ValueError, match="must be an integer"):
        ms_to_utc_datetime(True)

    # Timezone-naive datetime rejected in OrderBookDepthSnapshot
    naive_dt = datetime(2026, 9, 21, 12, 0, 0)
    with pytest.raises(
        (ValueError, ValidationError), match="timezone-aware UTC timestamp required"
    ):
        OrderBookDepthSnapshot(
            symbol="BTCUSDT",
            bids=(),
            asks=(),
            last_update_id=1,
            event_time=naive_dt,
        )

    # Non-UTC timezone datetime rejected
    plus_5_dt = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone(timedelta(hours=5)))
    with pytest.raises(
        (ValueError, ValidationError), match="timezone-aware UTC timestamp required"
    ):
        OrderBookDepthSnapshot(
            symbol="BTCUSDT",
            bids=(),
            asks=(),
            last_update_id=1,
            event_time=plus_5_dt,
        )


def test_wire_parser_depth_level_structure_anomalies() -> None:
    """Test empty books, level truncation, and invalid level formats."""
    # Empty bids and asks
    snap_empty = parse_binance_depth5(
        {
            "s": "BTCUSDT",
            "u": 1,
            "b": [],
            "a": [],
            "E": 1000,
        }
    )
    assert len(snap_empty.bids) == 0
    assert len(snap_empty.asks) == 0
    assert snap_empty.best_bid_price is None
    assert snap_empty.best_ask_price is None
    assert snap_empty.spread is None
    assert snap_empty.spread_bps is None

    # Truncation to 5 levels when 8 levels provided
    snap_truncated = parse_binance_depth5(
        {
            "s": "BTCUSDT",
            "u": 1,
            "b": [[str(100 - i), "1.0"] for i in range(8)],
            "a": [[str(101 + i), "1.0"] for i in range(8)],
            "E": 1000,
        }
    )
    assert len(snap_truncated.bids) == 5
    assert len(snap_truncated.asks) == 5

    # Malformed level format (item missing quantity)
    with pytest.raises(ValueError, match="Invalid depth level format"):
        parse_binance_depth5(
            {
                "s": "BTCUSDT",
                "u": 1,
                "b": [["100.0"]],
                "a": [["101.0", "1.0"]],
                "E": 1000,
            }
        )

    # Malformed bids container (not list/tuple)
    with pytest.raises(ValueError, match="Invalid format for bids or asks"):
        parse_binance_depth5(
            {
                "s": "BTCUSDT",
                "u": 1,
                "b": "not_a_list",
                "a": [["101.0", "1.0"]],
                "E": 1000,
            }
        )


def test_wire_parser_agg_trade_anomalies() -> None:
    """Test agg trade missing fields and non-boolean maker flag."""
    # Missing required field 'm'
    with pytest.raises(KeyError, match="Missing required field 'm'"):
        parse_binance_agg_trade(
            {
                "s": "BTCUSDT",
                "a": 1,
                "p": "65000.00",
                "q": "1.000",
                "T": 1000,
            }
        )

    # Non-boolean 'm' (string "true" or int 1)
    with pytest.raises(ValueError, match="is_buyer_maker 'm' must be boolean"):
        parse_binance_agg_trade(
            {
                "s": "BTCUSDT",
                "a": 1,
                "p": "65000.00",
                "q": "1.000",
                "T": 1000,
                "m": "true",
            }
        )

    # Negative trade ID
    with pytest.raises((ValueError, ValidationError)):
        parse_binance_agg_trade(
            {
                "s": "BTCUSDT",
                "a": -5,
                "p": "65000.00",
                "q": "1.000",
                "T": 1000,
                "m": False,
            }
        )


def test_wire_parser_mark_price_empty_and_none_settle_price() -> None:
    """Mark price parser handles empty string and None for 'P' properly."""
    # Empty string "P": ""
    mark_empty = parse_binance_mark_price(
        {
            "s": "BTCUSDT",
            "p": "65000.00",
            "i": "65000.00",
            "P": "",
            "r": "0.00010000",
            "T": 1726934400000,
            "E": 1726912800000,
        }
    )
    assert mark_empty.estimated_settle_price is None

    # None "P": None
    mark_none = parse_binance_mark_price(
        {
            "s": "BTCUSDT",
            "p": "65000.00",
            "i": "65000.00",
            "P": None,
            "r": "0.00010000",
            "T": 1726934400000,
            "E": 1726912800000,
        }
    )
    assert mark_none.estimated_settle_price is None


# =====================================================================
# 2. Exponential Backoff & Jitter Behavior
# =====================================================================


def test_exponential_backoff_exact_curve() -> None:
    """Verify base delay progression: 0.5s -> 1.0s -> 2.0s -> 4.0s -> 8.0s (ceiling)."""
    expected_bases = [
        (0, 0.5),
        (1, 0.5),
        (2, 1.0),
        (3, 2.0),
        (4, 4.0),
        (5, 8.0),
        (6, 8.0),
        (7, 8.0),
        (10, 8.0),
        (100, 8.0),
    ]
    for attempt, expected in expected_bases:
        val = BinancePublicFeedClient.compute_backoff_delay(attempt=attempt, jitter=0.0)
        assert val == pytest.approx(expected, abs=1e-6), (
            f"Attempt {attempt} expected {expected}s base delay, got {val}s"
        )


def test_jitter_statistical_distribution() -> None:
    """Verify 5,000 samples of jitter fall strictly within [+0.1, +0.4]s and mean is ~0.25s."""
    samples = [BinancePublicFeedClient.compute_backoff_delay(attempt=1) - 0.5 for _ in range(5000)]
    min_j = min(samples)
    max_j = max(samples)
    mean_j = sum(samples) / len(samples)

    assert min_j >= 0.1000, f"Jitter {min_j} breached lower bound 0.1"
    assert max_j <= 0.4000, f"Jitter {max_j} breached upper bound 0.4"
    assert 0.24 <= mean_j <= 0.26, f"Jitter mean {mean_j} deviates from expected uniform mean 0.25"


def test_backoff_reset_after_healthy_30s_connection() -> None:
    """Verify backoff attempt counter resets to 0 after healthy connection >= 30.0s."""
    # Simulate connect_and_stream logic directly
    healthy_threshold_seconds = 30.0
    reconnect_attempt = 0

    # Drop 1: after 5s (< 30s)
    conn_duration_1 = 5.0
    if conn_duration_1 >= healthy_threshold_seconds:
        reconnect_attempt = 0
    reconnect_attempt += 1
    assert reconnect_attempt == 1
    delay_1 = BinancePublicFeedClient.compute_backoff_delay(reconnect_attempt, jitter=0.0)
    assert delay_1 == pytest.approx(0.5)

    # Drop 2: after 10s (< 30s)
    conn_duration_2 = 10.0
    if conn_duration_2 >= healthy_threshold_seconds:
        reconnect_attempt = 0
    reconnect_attempt += 1
    assert reconnect_attempt == 2
    delay_2 = BinancePublicFeedClient.compute_backoff_delay(reconnect_attempt, jitter=0.0)
    assert delay_2 == pytest.approx(1.0)

    # Drop 3: after 12s (< 30s) -> attempt 3
    conn_duration_3 = 12.0
    if conn_duration_3 >= healthy_threshold_seconds:
        reconnect_attempt = 0
    reconnect_attempt += 1
    assert reconnect_attempt == 3
    delay_3 = BinancePublicFeedClient.compute_backoff_delay(reconnect_attempt, jitter=0.0)
    assert delay_3 == pytest.approx(2.0)

    # Drop 4: after 35s (>= 30.0s, HEALTHY RESET!)
    conn_duration_4 = 35.0
    if conn_duration_4 >= healthy_threshold_seconds:
        reconnect_attempt = 0  # Reset!
    reconnect_attempt += 1
    assert reconnect_attempt == 1, "Attempt must reset back to 1 after healthy connection >= 30s"
    delay_4 = BinancePublicFeedClient.compute_backoff_delay(reconnect_attempt, jitter=0.0)
    assert delay_4 == pytest.approx(0.5)


# =====================================================================
# 3. Sequence Deduplication & Gap Tracking Matrix
# =====================================================================


def test_sequencer_depth_dedup_and_gap_matrix() -> None:
    """Verify depth sequence tracking under duplicates, out-of-order, and gap jumps."""
    sequencer = PublicMarketStreamSequencer()

    # Packet 1: initial u=100
    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=100, pu=99)
    assert is_dup is False
    assert is_gap is False

    # Packet 2: exact duplicate u=100
    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=100, pu=99)
    assert is_dup is True
    assert is_gap is False
    assert sequencer.duplicate_count == 1

    # Packet 3: stale packet u=95 arrived out of order
    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=95, pu=90)
    assert is_dup is True
    assert is_gap is False
    assert sequencer.duplicate_count == 2

    # Packet 4: clean sequential update u=105, pu=100
    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=105, pu=100)
    assert is_dup is False
    assert is_gap is False

    # Packet 5: gap jump! Last u was 105, but incoming pu is 108 (missed 106, 107)
    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=110, pu=108)
    assert is_dup is False
    assert is_gap is True
    assert sequencer.sequence_gap_count == 1
    assert sequencer.gaps_by_symbol["BTCUSDT"] == 1

    # Packet 6: sequential update with omitted pu=None
    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=115, pu=None)
    assert is_dup is False
    assert is_gap is False


def test_sequencer_agg_trade_dedup_and_monotonicity() -> None:
    """Verify agg trade ID deduplication and out-of-order rejection."""
    sequencer = PublicMarketStreamSequencer()

    assert sequencer.check_agg_trade("ETHUSDT", a=1000) is False
    assert sequencer.check_agg_trade("ETHUSDT", a=1000) is True  # Duplicate
    assert sequencer.check_agg_trade("ETHUSDT", a=999) is True  # Out of order
    assert sequencer.check_agg_trade("ETHUSDT", a=1001) is False  # Sequential
    assert sequencer.duplicate_count == 2


def test_sequencer_mark_price_dedup_and_monotonicity() -> None:
    """Verify mark price event timestamp deduplication and out-of-order rejection."""
    sequencer = PublicMarketStreamSequencer()

    assert sequencer.check_mark_price("SOLUSDT", event_time_ms=100000) is False
    assert sequencer.check_mark_price("SOLUSDT", event_time_ms=100000) is True  # Duplicate
    assert sequencer.check_mark_price("SOLUSDT", event_time_ms=99990) is True  # Out of order
    assert sequencer.check_mark_price("SOLUSDT", event_time_ms=100100) is False  # Sequential
    assert sequencer.duplicate_count == 2


def test_sequencer_multi_symbol_isolation_and_reset() -> None:
    """Ensure symbol streams are fully isolated and case-insensitive."""
    sequencer = PublicMarketStreamSequencer()

    # Seed 3 symbols
    sequencer.check_depth("BTCUSDT", u=100)
    sequencer.check_depth("ETHUSDT", u=200)
    sequencer.check_depth("SOLUSDT", u=300)

    # Incur duplicate on BTC only
    sequencer.check_depth("btcusdt", u=100)  # Lowercase symbol test
    assert sequencer.duplicates_by_symbol.get("BTCUSDT") == 1
    assert sequencer.duplicates_by_symbol.get("ETHUSDT", 0) == 0
    assert sequencer.duplicates_by_symbol.get("SOLUSDT", 0) == 0

    # Incur gap on ETH only
    sequencer.check_depth("ethusdt", u=210, pu=205)
    assert sequencer.gaps_by_symbol.get("ETHUSDT") == 1
    assert sequencer.gaps_by_symbol.get("BTCUSDT", 0) == 0

    # Reset clears everything
    sequencer.reset()
    assert sequencer.duplicate_count == 0
    assert sequencer.sequence_gap_count == 0
    assert len(sequencer.duplicates_by_symbol) == 0
    assert len(sequencer.gaps_by_symbol) == 0


# =====================================================================
# 4. Stream Consumer Fault Tolerance & Edge Cases
# =====================================================================


class _MockAsyncWebSocket:
    """Async iterator simulating WebSocket messages."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = list(messages)
        self._index = 0
        self.closed = False

    def __aiter__(self) -> AsyncIterator[str]:
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self.messages):
            raise StopAsyncIteration
        msg = self.messages[self._index]
        self._index += 1
        return msg

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True


def test_client_consume_stream_malformed_json_and_primitives() -> None:
    """Verify consumer does not crash on malformed JSON, numbers, lists, or RPC ACKs."""
    telemetry = FeedTelemetryAccumulator()
    client = BinancePublicFeedClient(symbols=("BTCUSDT",), telemetry=telemetry)

    valid_depth = {
        "stream": "btcusdt@depth5@100ms",
        "data": {
            "s": "BTCUSDT",
            "u": 100,
            "b": [["65000.00", "1.0"]],
            "a": [["65001.00", "1.0"]],
            "E": 1726912800000,
        },
    }

    mock_msgs = [
        "{malformed json string",  # Corrupted JSON
        json.dumps("plain string primitive"),  # Non-dict JSON primitive
        json.dumps(12345),  # Integer JSON primitive
        json.dumps([1, 2, 3]),  # JSON list
        json.dumps(None),  # Null JSON
        json.dumps({"result": None, "id": 1}),  # Binance RPC subscription ACK
        json.dumps(valid_depth),  # Valid depth
    ]

    ws = _MockAsyncWebSocket(mock_msgs)
    received_depths: list[OrderBookDepthSnapshot] = []

    async def on_depth(depth: OrderBookDepthSnapshot, recv_ns: int) -> None:
        received_depths.append(depth)

    async def _run() -> None:
        await client.consume_stream(ws, duration_seconds=2.0, on_depth=on_depth)

    asyncio.run(_run())

    # Exactly one valid depth snapshot was processed
    assert len(received_depths) == 1
    assert received_depths[0].symbol == "BTCUSDT"
    # Errors recorded in telemetry for malformed JSON
    assert telemetry.error_count >= 1


def test_client_gateway_health_and_latency_tracking() -> None:
    """Verify heartbeat age and health thresholds."""
    client = BinancePublicFeedClient(symbols=("BTCUSDT",))

    # Fresh client has last_heartbeat_time_ms == 0
    assert client.last_heartbeat_time_ms == 0.0
    assert client.heartbeat_age_ms == 0.0
    assert client.is_heartbeat_healthy is True

    # Simulate message arrival
    now_ms = time.time_ns() / 1_000_000.0
    client.last_heartbeat_time_ms = now_ms - 200.0  # 200ms ago
    assert client.heartbeat_age_ms >= 190.0
    assert client.is_heartbeat_healthy is True

    # Stale heartbeat: 600ms ago (> 500ms threshold)
    client.last_heartbeat_time_ms = now_ms - 600.0
    assert client.heartbeat_age_ms >= 590.0
    assert client.is_heartbeat_healthy is False


def test_client_clock_skew_synchronization_scenarios() -> None:
    """Verify clock skew calculation relative to Binance REST /fapi/v1/time."""
    client = BinancePublicFeedClient(symbols=("BTCUSDT",))

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.json = lambda: {"serverTime": 1726912800250}

    with (
        patch("httpx.AsyncClient.get", return_value=mock_response),
        patch("time.time", return_value=1726912800.0),
        patch("time.perf_counter", side_effect=[10.0, 10.010]),  # 10ms RTT
    ):
        skew = asyncio.run(client.sync_server_time())
        assert client.clock_skew_ms == skew
        # Expected: 1726912800250 - (1726912800000.0 + 5.0) = 245.0 ms
        assert skew == pytest.approx(245.0, abs=0.1)

    # Mock invalid response missing serverTime
    mock_invalid = AsyncMock()
    mock_invalid.status_code = 200
    mock_invalid.raise_for_status = lambda: None
    mock_invalid.json = lambda: {"status": "ok"}

    with patch("httpx.AsyncClient.get", return_value=mock_invalid):
        with pytest.raises(ValueError, match="Invalid response from Binance /fapi/v1/time"):
            asyncio.run(client.sync_server_time())


# =====================================================================
# 5. Advanced Adversarial Stress Tests & Edge Case Failures
# =====================================================================


def test_backoff_overflow_on_large_attempts_empirical_reproduction() -> None:
    """EMPIRICAL REPRODUCTION:

    In compute_backoff_delay:
        exp = max(0, attempt - 1)
        base = min(8.0, 0.5 * (2.0**exp))
    Because 2.0**exp is computed before min(8.0, ...), when attempt >= 1025
    (e.g. during an extended network outage lasting > 2.2 hours),
    2.0**1024 raises OverflowError and crashes the client!
    """
    # Attempt 100 works (2^99 is within float limits)
    delay_100 = BinancePublicFeedClient.compute_backoff_delay(attempt=100, jitter=0.0)
    assert delay_100 == pytest.approx(8.0)

    # Attempt 1025 overflows IEEE 754 double precision
    with pytest.raises(OverflowError, match=r"(Result too large|Numerical result out of range)"):
        BinancePublicFeedClient.compute_backoff_delay(attempt=1025, jitter=0.0)


def test_client_consume_stream_unhandled_exception_on_p_zero() -> None:
    """EMPIRICAL REPRODUCTION:

    When Binance sends P='0.00000000' (standard for ~130 symbols outside settlement),
    parse_binance_mark_price raises ValidationError.
    Because consume_stream has no error guard around model parsing, the exception
    propagates out of consume_stream, aborting the stream consumption!
    """
    client = BinancePublicFeedClient(symbols=("RAYUSDT",))

    mark_msg = {
        "stream": "rayusdt@markPrice@1s",
        "data": {
            "e": "markPriceUpdate",
            "E": 1726912800000,
            "s": "RAYUSDT",
            "p": "1.52000000",
            "i": "1.52100000",
            "P": "0.00000000",
            "r": "0.00010000",
            "T": 1726934400000,
        },
    }

    ws = _MockAsyncWebSocket([json.dumps(mark_msg)])

    async def _run() -> None:
        await client.consume_stream(ws, duration_seconds=1.0)

    with pytest.raises(ValidationError):
        asyncio.run(_run())


def test_client_connect_and_stream_reconnection_loop_simulation() -> None:
    """Simulate connect_and_stream handling drops and backoff sleep."""
    client = BinancePublicFeedClient(symbols=("BTCUSDT",))

    call_count = 0

    class _DroppingWS:
        def __init__(self) -> None:
            nonlocal call_count
            call_count += 1

        async def __aenter__(self) -> _DroppingWS:
            # Drop immediately on connection
            raise ConnectionResetError("Simulated TCP drop")

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    async def mock_sleep_impl(delay: float) -> None:
        if call_count >= 5:
            await client.close()

    with (
        patch("websockets.connect", side_effect=lambda *args, **kwargs: _DroppingWS()),
        patch("asyncio.sleep", side_effect=mock_sleep_impl),
    ):

        async def _run() -> None:
            await client.connect_and_stream(duration_seconds=10.0)

        asyncio.run(_run())

        assert call_count >= 5
        assert client.reconnect_count >= 5
