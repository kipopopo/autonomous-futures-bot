"""Phase 257: Unit Test Suite for Live Feed Ingestion, Telemetry, and Circuit Breaker Integration.

Covers CanonicalBar, TickerSnapshot, parsers, BinancePublicFeedClient,
CircuitBreakerFeedMonitor, FeedTelemetryAccumulator, and Kainode probe CLI.
Executed synchronously via standard def test_...(): asyncio.run(...) pattern.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autonomous_futures.feed.client import BinancePublicFeedClient
from autonomous_futures.feed.models import (
    CanonicalBar,
    TickerSnapshot,
    ms_to_utc_datetime,
    parse_binance_book_ticker,
    parse_binance_kline,
)
from autonomous_futures.feed.monitor import CircuitBreakerFeedMonitor
from autonomous_futures.feed.telemetry import (
    FeedTelemetryAccumulator,
    _compute_decimal_percentile,
    _compute_float_percentile,
)
from autonomous_futures.paper.circuit_breakers import (
    CircuitBreakerConfig,
    HardenedSharedMarginAccount,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.probe_kainode_live_feed import (  # noqa: E402
    build_probe_arg_parser,
    generate_mock_probe_summary,
    parse_probe_cli_args,
    verify_strict_safety_invariants,
)


class TestCanonicalBarModel:
    """Validates CanonicalBar domain model invariants, UTC dates, and Decimal precision."""

    def test_canonical_bar_nominal_instantiation(self) -> None:
        """Verify nominal instantiation with strict Decimals, UTC datetimes, and boolean flags."""
        bar = CanonicalBar(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
            close_time=datetime(2026, 9, 6, 0, 4, 59, 999000, tzinfo=UTC),
            open=Decimal("79699.90"),
            high=Decimal("79750.00"),
            low=Decimal("79690.00"),
            close=Decimal("79710.50"),
            volume=Decimal("36.213"),
            quote_volume=Decimal("2885994.49840"),
            trades=2998,
            taker_buy_base=Decimal("15.006"),
            taker_buy_quote=Decimal("1195904.70880"),
            is_closed=False,
        )
        assert bar.symbol == "BTCUSDT"
        assert bar.interval == "5m"
        assert isinstance(bar.open, Decimal)
        assert bar.timestamp.tzinfo is UTC
        assert bar.close_time.tzinfo is UTC
        assert bar.is_closed is False

    def test_canonical_bar_rejects_naive_datetimes(self) -> None:
        """Verify rejection of timezone-naive datetimes for timestamp and close_time."""
        with pytest.raises(ValidationError, match="timezone-aware"):
            CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=datetime(2026, 9, 6, 0, 0),  # Naive
                close_time=datetime(2026, 9, 6, 0, 4, 59, 999000, tzinfo=UTC),
                open=Decimal("100.0"),
                high=Decimal("110.0"),
                low=Decimal("90.0"),
                close=Decimal("105.0"),
                volume=Decimal("10.0"),
                quote_volume=Decimal("1000.0"),
                trades=10,
                taker_buy_base=Decimal("5.0"),
                taker_buy_quote=Decimal("500.0"),
                is_closed=True,
            )

    def test_canonical_bar_rejects_float_types(self) -> None:
        """Verify strict forbidding of Python float types (Decimal required)."""
        with pytest.raises(ValidationError):
            CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
                close_time=datetime(2026, 9, 6, 0, 5, tzinfo=UTC),
                open=79699.90,  # float prohibited
                high=Decimal("79750.00"),
                low=Decimal("79690.00"),
                close=Decimal("79710.50"),
                volume=Decimal("36.213"),
                quote_volume=Decimal("2885994.49840"),
                trades=2998,
                taker_buy_base=Decimal("15.006"),
                taker_buy_quote=Decimal("1195904.70880"),
                is_closed=True,
            )

    def test_canonical_bar_geometry_validation(self) -> None:
        """Verify candlestick geometry: High >= max(Open, Close) and Low <= min(Open, Close)."""
        # High lower than Open
        with pytest.raises(ValidationError, match="high"):
            CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
                close_time=datetime(2026, 9, 6, 0, 5, tzinfo=UTC),
                open=Decimal("100.0"),
                high=Decimal("95.0"),  # Invalid: high < open
                low=Decimal("90.0"),
                close=Decimal("92.0"),
                volume=Decimal("1.0"),
                quote_volume=Decimal("100.0"),
                trades=1,
                taker_buy_base=Decimal("0.5"),
                taker_buy_quote=Decimal("50.0"),
                is_closed=True,
            )

        # Low higher than Close
        with pytest.raises(ValidationError, match="low"):
            CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
                close_time=datetime(2026, 9, 6, 0, 5, tzinfo=UTC),
                open=Decimal("100.0"),
                high=Decimal("105.0"),
                low=Decimal("98.0"),  # Invalid: low > close
                close=Decimal("95.0"),
                volume=Decimal("1.0"),
                quote_volume=Decimal("100.0"),
                trades=1,
                taker_buy_base=Decimal("0.5"),
                taker_buy_quote=Decimal("50.0"),
                is_closed=True,
            )

    def test_canonical_bar_forbids_extra_fields(self) -> None:
        """Verify extra='forbid' prevents unmodeled wire fields."""
        with pytest.raises(ValidationError):
            CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
                close_time=datetime(2026, 9, 6, 0, 5, tzinfo=UTC),
                open=Decimal("100.0"),
                high=Decimal("105.0"),
                low=Decimal("95.0"),
                close=Decimal("100.0"),
                volume=Decimal("1.0"),
                quote_volume=Decimal("100.0"),
                trades=1,
                taker_buy_base=Decimal("0.5"),
                taker_buy_quote=Decimal("50.0"),
                is_closed=True,
                unrecognized_field="forbidden",  # type: ignore[call-arg]
            )

    def test_canonical_bar_trades_strict_integer(self) -> None:
        """Verify CanonicalBar.trades strictly enforces integer type and rejects booleans."""
        base_kwargs: dict[str, Any] = dict(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
            close_time=datetime(2026, 9, 6, 0, 4, 59, 999000, tzinfo=UTC),
            open=Decimal("79699.90"),
            high=Decimal("79750.00"),
            low=Decimal("79690.00"),
            close=Decimal("79710.50"),
            volume=Decimal("36.213"),
            quote_volume=Decimal("2885994.49840"),
            taker_buy_base=Decimal("15.006"),
            taker_buy_quote=Decimal("1195904.70880"),
            is_closed=True,
        )

        # 1. Valid non-negative integers must pass cleanly
        bar_zero = CanonicalBar(trades=0, **base_kwargs)
        assert bar_zero.trades == 0
        assert type(bar_zero.trades) is int

        bar_positive = CanonicalBar(trades=42, **base_kwargs)
        assert bar_positive.trades == 42
        assert type(bar_positive.trades) is int

        # 2. Booleans True and False must be strictly rejected (issubclass(bool, int) is True)
        with pytest.raises(ValidationError, match="Input should be a valid integer"):
            CanonicalBar(trades=True, **base_kwargs)

        with pytest.raises(ValidationError, match="Input should be a valid integer"):
            CanonicalBar(trades=False, **base_kwargs)

        # 3. Negative integers must be rejected by ge=0 constraint
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            CanonicalBar(trades=-1, **base_kwargs)

        # 4. Floats and string integers must be rejected by strict=True
        with pytest.raises(ValidationError, match="Input should be a valid integer"):
            CanonicalBar(trades=42.0, **base_kwargs)

        with pytest.raises(ValidationError, match="Input should be a valid integer"):
            CanonicalBar(trades="42", **base_kwargs)

    def test_canonical_bar_is_closed_strict_boolean(self) -> None:
        """Verify CanonicalBar.is_closed strictly enforces boolean type."""
        base_kwargs: dict[str, Any] = dict(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
            close_time=datetime(2026, 9, 6, 0, 4, 59, 999000, tzinfo=UTC),
            open=Decimal("79699.90"),
            high=Decimal("79750.00"),
            low=Decimal("79690.00"),
            close=Decimal("79710.50"),
            volume=Decimal("36.213"),
            quote_volume=Decimal("2885994.49840"),
            trades=10,
            taker_buy_base=Decimal("15.006"),
            taker_buy_quote=Decimal("1195904.70880"),
        )

        bar_true = CanonicalBar(is_closed=True, **base_kwargs)
        assert bar_true.is_closed is True

        bar_false = CanonicalBar(is_closed=False, **base_kwargs)
        assert bar_false.is_closed is False

        for invalid_bool in [1, 0, "true", "false"]:
            with pytest.raises(ValidationError, match="Input should be a valid boolean"):
                CanonicalBar(is_closed=invalid_bool, **base_kwargs)  # type: ignore[arg-type]

    def test_ms_to_utc_datetime(self) -> None:
        """Verify exact microsecond UTC conversion from epoch milliseconds."""
        dt = ms_to_utc_datetime(1788622800123)
        assert dt.tzinfo is UTC
        assert dt.microsecond == 123000

        with pytest.raises(ValueError):
            ms_to_utc_datetime(-1)
        with pytest.raises(ValueError):
            ms_to_utc_datetime("12345")  # type: ignore[arg-type]


class TestTickerSnapshotModel:
    """Validates TickerSnapshot domain model, spread_bps calculation, and crossed book rejection."""

    def test_ticker_snapshot_nominal_and_spread_bps(self) -> None:
        """Verify nominal snapshot, mid_price, spread, and spread_bps calculations."""
        ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("79699.50"),
            best_bid_qty=Decimal("3.955"),
            best_ask_price=Decimal("79699.60"),
            best_ask_qty=Decimal("14.093"),
            transaction_time=datetime(2026, 9, 6, 0, 0, 1, tzinfo=UTC),
            event_time=datetime(2026, 9, 6, 0, 0, 1, 1000, tzinfo=UTC),
        )
        assert ticker.symbol == "BTCUSDT"
        assert ticker.mid_price == Decimal("79699.55")
        assert ticker.spread == Decimal("0.10")
        expected_bps = (Decimal("0.10") / Decimal("79699.55")) * Decimal("10000")
        assert ticker.spread_bps == expected_bps

    def test_ticker_snapshot_rejects_negative_spread(self) -> None:
        """Verify strict rejection of crossed book where best_bid > best_ask."""
        with pytest.raises(ValidationError, match="crossed"):
            TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=Decimal("79700.00"),  # Crossed: Bid > Ask
                best_bid_qty=Decimal("1.0"),
                best_ask_price=Decimal("79695.00"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=datetime(2026, 9, 6, 0, 0, 1, tzinfo=UTC),
                event_time=datetime(2026, 9, 6, 0, 0, 1, 1000, tzinfo=UTC),
            )

    def test_ticker_snapshot_rejects_zero_or_negative_price(self) -> None:
        """Verify rejection of non-positive bid or ask prices."""
        with pytest.raises(ValidationError):
            TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=Decimal("0.0"),
                best_bid_qty=Decimal("1.0"),
                best_ask_price=Decimal("10.0"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=datetime(2026, 9, 6, 0, 0, 1, tzinfo=UTC),
                event_time=datetime(2026, 9, 6, 0, 0, 1, 1000, tzinfo=UTC),
            )

    def test_ticker_snapshot_rejects_naive_datetimes(self) -> None:
        """Verify rejection of timezone-naive transaction or event times."""
        with pytest.raises(ValidationError, match="timezone-aware"):
            TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=Decimal("100.0"),
                best_bid_qty=Decimal("1.0"),
                best_ask_price=Decimal("100.5"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=datetime(2026, 9, 6, 0, 0, 0),  # Naive
                event_time=datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC),
            )

    def test_ticker_snapshot_rejects_floats(self) -> None:
        """Verify rejection of Python float types."""
        with pytest.raises(ValidationError):
            TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=100.0,  # float prohibited
                best_bid_qty=Decimal("1.0"),
                best_ask_price=Decimal("100.5"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC),
                event_time=datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC),
            )


class TestFeedParsers:
    """Validates parse_binance_kline and parse_binance_book_ticker against wire samples."""

    RAW_BOOK_TICKER_WIRE = {
        "e": "bookTicker",
        "u": 11482674816734,
        "s": "BTCUSDT",
        "ps": "BTCUSDT",
        "b": "79699.50",
        "B": "3.955",
        "a": "79699.60",
        "A": "14.093",
        "T": 1788622963943,
        "E": 1788622963944,
        "st": 1,
    }

    COMBINED_BOOK_TICKER_WIRE = {
        "stream": "ethusdt@bookTicker",
        "data": {
            "e": "bookTicker",
            "u": 11482028682229,
            "s": "ETHUSDT",
            "b": "2232.06",
            "B": "18.324",
            "a": "2232.07",
            "A": "82.493",
            "T": 1788623063510,
            "E": 1788623063511,
        },
    }

    RAW_KLINE_WIRE = {
        "e": "kline",
        "E": 1788622995254,
        "s": "BTCUSDT",
        "k": {
            "t": 1788622800000,
            "T": 1788623099999,
            "s": "BTCUSDT",
            "i": "5m",
            "f": 6571597871,
            "L": 6571600868,
            "o": "79699.90",
            "c": "79699.90",
            "h": "79700.00",
            "l": "79690.00",
            "v": "36.213",
            "n": 2998,
            "x": False,
            "q": "2885994.49840",
            "V": "15.006",
            "Q": "1195904.70880",
            "B": "0",
        },
    }

    COMBINED_KLINE_WIRE = {
        "stream": "solusdt@kline_5m",
        "data": {
            "e": "kline",
            "E": 1788622995300,
            "s": "SOLUSDT",
            "k": {
                "t": 1788622800000,
                "T": 1788623099999,
                "s": "SOLUSDT",
                "i": "5m",
                "f": 100,
                "L": 200,
                "o": "135.50",
                "c": "136.20",
                "h": "136.50",
                "l": "135.00",
                "v": "500.0",
                "n": 40,
                "x": True,  # Bar closed
                "q": "68000.0",
                "V": "250.0",
                "Q": "34000.0",
                "B": "0",
            },
        },
    }

    def test_parse_raw_book_ticker(self) -> None:
        """Verify parsing raw unwrapped bookTicker wire message."""
        snapshot = parse_binance_book_ticker(self.RAW_BOOK_TICKER_WIRE)
        assert snapshot is not None
        assert snapshot.symbol == "BTCUSDT"
        assert snapshot.best_bid_price == Decimal("79699.50")
        assert snapshot.best_ask_price == Decimal("79699.60")
        assert snapshot.best_bid_qty == Decimal("3.955")
        assert snapshot.best_ask_qty == Decimal("14.093")
        assert snapshot.transaction_time == ms_to_utc_datetime(1788622963943)
        assert snapshot.event_time == ms_to_utc_datetime(1788622963944)

    def test_parse_combined_envelope_book_ticker(self) -> None:
        """Verify automatic unwrapping of combined stream envelope for bookTicker."""
        snapshot = parse_binance_book_ticker(self.COMBINED_BOOK_TICKER_WIRE)
        assert snapshot is not None
        assert snapshot.symbol == "ETHUSDT"
        assert snapshot.best_bid_price == Decimal("2232.06")
        assert snapshot.best_ask_price == Decimal("2232.07")

    def test_parse_raw_kline(self) -> None:
        """Verify parsing raw unwrapped kline wire message."""
        bar = parse_binance_kline(self.RAW_KLINE_WIRE)
        assert bar is not None
        assert bar.symbol == "BTCUSDT"
        assert bar.interval == "5m"
        assert bar.open == Decimal("79699.90")
        assert bar.high == Decimal("79700.00")
        assert bar.low == Decimal("79690.00")
        assert bar.close == Decimal("79699.90")
        assert bar.volume == Decimal("36.213")
        assert bar.trades == 2998
        assert bar.is_closed is False
        assert bar.timestamp == ms_to_utc_datetime(1788622800000)

    def test_parse_combined_envelope_closed_kline(self) -> None:
        """Verify combined stream envelope and finalized closed bar parsing."""
        bar = parse_binance_kline(self.COMBINED_KLINE_WIRE)
        assert bar is not None
        assert bar.symbol == "SOLUSDT"
        assert bar.is_closed is True
        assert bar.close == Decimal("136.20")

    def test_parsers_handle_rpc_acknowledgment(self) -> None:
        """Verify RPC ack responses (e.g. subscribe result) are handled without raising errors."""
        rpc_ack = {"result": None, "id": 1}
        assert parse_binance_book_ticker(rpc_ack) is None
        assert parse_binance_kline(rpc_ack) is None

    def test_parsers_reject_corrupt_payload(self) -> None:
        """Verify corrupted or empty payload raises explicit error."""
        with pytest.raises((KeyError, ValueError, ValidationError)):
            parse_binance_book_ticker({"e": "bookTicker"})  # Missing b, a, s


class MockWebSocketSession:
    """Deterministic in-memory mock WebSocket protocol for client testing."""

    def __init__(self, incoming_messages: list[str]) -> None:
        self._messages = list(incoming_messages)
        self.sent_messages: list[str] = []
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str = ""

    def __aiter__(self) -> MockWebSocketSession:
        return self

    async def __anext__(self) -> str:
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, data: str) -> None:
        self.sent_messages.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class TestBinancePublicFeedClient:
    """Validates BinancePublicFeedClient protocol, URL, zero-credential, and mock streaming."""

    def test_stream_url_construction(self) -> None:
        """Verify construction of multiplexed combined stream URL across 4 asset pairs."""
        client = BinancePublicFeedClient(
            symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"),
            stream_types=("bookTicker", "kline_5m"),
            base_url="wss://fstream.binance.com",
        )
        url = client.build_stream_url()
        assert url.startswith("wss://fstream.binance.com/stream?streams=")
        query = url.split("?streams=")[1]
        streams = set(query.split("/"))
        expected = {
            "btcusdt@bookTicker",
            "btcusdt@kline_5m",
            "ethusdt@bookTicker",
            "ethusdt@kline_5m",
            "solusdt@bookTicker",
            "solusdt@kline_5m",
            "dogeusdt@bookTicker",
            "dogeusdt@kline_5m",
        }
        assert streams == expected

    def test_zero_credential_invariant_in_client(self) -> None:
        """Verify client explicitly forbids API keys, secrets, or auth headers."""
        with pytest.raises(ValueError, match="Credentials"):
            BinancePublicFeedClient(
                symbols=("BTCUSDT",),
                api_key="forbidden_key",  # type: ignore[call-arg]
            )

        client = BinancePublicFeedClient(
            symbols=("BTCUSDT",),
            stream_types=("bookTicker",),
        )
        assert client.api_key is None
        assert client.api_secret is None
        headers = client.get_connect_headers()
        assert "X-MBX-APIKEY" not in headers
        assert "Authorization" not in headers

    def test_mock_websocket_streaming_and_dispatch(self) -> None:
        """Verify client consumes mock stream, demultiplexes, and invokes typed callbacks."""
        test_messages = [
            json.dumps(TestFeedParsers.COMBINED_BOOK_TICKER_WIRE),
            json.dumps(TestFeedParsers.COMBINED_KLINE_WIRE),
        ]
        mock_ws = MockWebSocketSession(test_messages)

        received_tickers: list[TickerSnapshot] = []
        received_bars: list[CanonicalBar] = []

        async def on_ticker(ticker: TickerSnapshot) -> None:
            received_tickers.append(ticker)

        async def on_bar(bar: CanonicalBar) -> None:
            received_bars.append(bar)

        async def run_test() -> None:
            client = BinancePublicFeedClient(
                symbols=("ETHUSDT", "SOLUSDT"),
                stream_types=("bookTicker", "kline_5m"),
            )
            await client.consume_stream(
                mock_ws,
                on_ticker=on_ticker,
                on_bar=on_bar,
            )

        asyncio.run(run_test())

        assert len(received_tickers) == 1
        assert received_tickers[0].symbol == "ETHUSDT"
        assert len(received_bars) == 1
        assert received_bars[0].symbol == "SOLUSDT"

    def test_bounded_duration_termination(self) -> None:
        """Verify client honors duration_seconds boundary and closes cleanly."""

        async def run_timed_client() -> None:
            client = BinancePublicFeedClient(
                symbols=("BTCUSDT",),
                stream_types=("bookTicker",),
            )

            class InfiniteMockSession:
                async def __aiter__(self) -> Any:
                    while True:
                        yield json.dumps(TestFeedParsers.COMBINED_BOOK_TICKER_WIRE)
                        await asyncio.sleep(0.01)

                async def close(self, code: int = 1000, reason: str = "") -> None:
                    pass

            start_t = time.monotonic()
            await client.consume_stream(
                InfiniteMockSession(),
                duration_seconds=0.1,
            )
            elapsed = time.monotonic() - start_t
            assert elapsed >= 0.08
            assert elapsed < 0.50

        asyncio.run(run_timed_client())

    def test_single_source_of_truth_telemetry_no_metric_inflation(self) -> None:
        """Verify feeding N wire messages through BinancePublicFeedClient with telemetry
        and on_ticker attached records each wire frame exactly once (len == N, counts == N).
        """
        n_messages = 25
        symbol = "BTCUSDT"
        stream = "btcusdt@bookTicker"
        now_ms = 1788622964000

        wire_messages = [
            json.dumps(
                {
                    "stream": stream,
                    "data": {
                        "e": "bookTicker",
                        "u": 1000 + i,
                        "s": symbol,
                        "b": "90000.00",
                        "B": "1.500",
                        "a": "90001.00",
                        "A": "2.000",
                        "T": now_ms + (i * 100),
                        "E": now_ms + (i * 100),
                    },
                }
            )
            for i in range(n_messages)
        ]

        mock_ws = MockWebSocketSession(wire_messages)
        telemetry = FeedTelemetryAccumulator(symbols=(symbol,))

        received_tickers: list[TickerSnapshot] = []

        async def on_ticker(ticker: TickerSnapshot, recv_ns: int) -> None:
            # Decoupled consumer callback: handles only downstream processing
            received_tickers.append(ticker)

        async def run_client() -> None:
            client = BinancePublicFeedClient(
                symbols=(symbol,),
                stream_types=("bookTicker",),
                telemetry=telemetry,
            )
            await client.consume_stream(mock_ws, on_ticker=on_ticker)

        asyncio.run(run_client())

        # Invariants for exact 1:1 single-source-of-truth accounting:
        assert len(telemetry._latencies_overall) == n_messages
        assert telemetry._counts_by_stream[stream] == n_messages
        assert telemetry._counts_by_symbol[symbol] == n_messages
        assert telemetry._book_ticker_counts[symbol] == n_messages
        assert len(telemetry._spreads_by_symbol[symbol]) == n_messages
        assert len(received_tickers) == n_messages

        summary = telemetry.compile_summary(elapsed_seconds=1.0)
        assert summary["total_messages_received"] == n_messages
        assert summary["by_symbol"][symbol]["total_count"] == n_messages
        assert summary["by_symbol"][symbol]["book_ticker_count"] == n_messages

    def test_telemetry_wire_frame_exact_accounting_heterogeneous_streams(self) -> None:
        """Verify bookTicker, kline, and unparsed RPC ack frames are each recorded
        in _latencies_overall exactly once.
        """
        raw_frames = [
            # Frame 1: BTC bookTicker
            json.dumps(
                {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "s": "BTCUSDT",
                        "b": "90000",
                        "B": "1",
                        "a": "90001",
                        "A": "1",
                        "E": 1788622964000,
                        "T": 1788622964000,
                    },
                }
            ),
            # Frame 2: ETH kline
            json.dumps(
                {
                    "stream": "ethusdt@kline_5m",
                    "data": {
                        "e": "kline",
                        "E": 1788622964100,
                        "s": "ETHUSDT",
                        "k": {
                            "t": 1788622800000,
                            "T": 1788623099999,
                            "s": "ETHUSDT",
                            "i": "5m",
                            "o": "2200",
                            "c": "2205",
                            "h": "2210",
                            "l": "2195",
                            "v": "10",
                            "n": 10,
                            "x": True,
                            "q": "22000",
                            "V": "5",
                            "Q": "11000",
                            "B": "0",
                        },
                    },
                }
            ),
            # Frame 3: RPC Ack (no E or T timestamp)
            json.dumps({"result": None, "id": 1}),
        ]

        mock_ws = MockWebSocketSession(raw_frames)
        telemetry = FeedTelemetryAccumulator(symbols=("BTCUSDT", "ETHUSDT"))

        received_tickers: list[TickerSnapshot] = []
        received_bars: list[CanonicalBar] = []

        async def on_ticker(t: TickerSnapshot, ns: int) -> None:
            received_tickers.append(t)

        async def on_bar(b: CanonicalBar, ns: int) -> None:
            received_bars.append(b)

        async def run_client() -> None:
            client = BinancePublicFeedClient(
                symbols=("BTCUSDT", "ETHUSDT"),
                stream_types=("bookTicker", "kline_5m"),
                telemetry=telemetry,
            )
            await client.consume_stream(mock_ws, on_ticker=on_ticker, on_bar=on_bar)

        asyncio.run(run_client())

        # Exactly 3 wire frames received
        assert len(telemetry._latencies_overall) == 3
        assert telemetry.compile_summary(elapsed_seconds=1.0)["total_messages_received"] == 3
        assert telemetry._counts_by_stream["btcusdt@bookTicker"] == 1
        assert telemetry._counts_by_stream["ethusdt@kline_5m"] == 1
        assert telemetry._book_ticker_counts["BTCUSDT"] == 1
        assert telemetry._kline_counts["ETHUSDT"] == 1
        assert len(received_tickers) == 1
        assert len(received_bars) == 1


class TestCircuitBreakerFeedMonitor:
    """Validates decoupled async queueing and feeding into HardenedSharedMarginAccount."""

    def test_monitor_initialization_and_queue(self) -> None:
        """Verify monitor initializes empty queue and binds to shared account."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        monitor = CircuitBreakerFeedMonitor(account=account, symbol="BTCUSDT")
        assert monitor.account is account
        assert monitor.queue.empty()

    def test_push_ticker_does_not_block_producer(self) -> None:
        """Verify pushing 500 high-frequency ticker updates completes instantly (<50ms)."""

        async def run_push() -> None:
            account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
            monitor = CircuitBreakerFeedMonitor(account=account, symbol="BTCUSDT")
            start = time.monotonic()
            for _ in range(500):
                snapshot = TickerSnapshot(
                    symbol="BTCUSDT",
                    best_bid_price=Decimal("79699.50"),
                    best_bid_qty=Decimal("1.0"),
                    best_ask_price=Decimal("79699.60"),
                    best_ask_qty=Decimal("1.0"),
                    transaction_time=datetime(2026, 9, 6, 0, 0, 1, tzinfo=UTC),
                    event_time=datetime(2026, 9, 6, 0, 0, 1, tzinfo=UTC),
                )
                await monitor.push_ticker(snapshot)
            duration = time.monotonic() - start
            assert duration < 0.10
            assert monitor.queue.qsize() == 500

        asyncio.run(run_push())

    def test_monitor_evaluates_slippage_throttle(self) -> None:
        """Verify elevated spread_bps triggers THROTTLED circuit breaker state."""

        async def run_evaluation() -> None:
            account = HardenedSharedMarginAccount(
                starting_capital=Decimal("100.00"),
                config=CircuitBreakerConfig(slippage_throttle_bps=Decimal("10.0")),
            )
            monitor = CircuitBreakerFeedMonitor(account=account, symbol="BTCUSDT")
            stressed_ticker = TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=Decimal("100.00"),
                best_bid_qty=Decimal("1.0"),
                best_ask_price=Decimal("100.16"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=datetime(2026, 9, 6, 0, 0, 1, tzinfo=UTC),
                event_time=datetime(2026, 9, 6, 0, 0, 1, tzinfo=UTC),
            )
            await monitor.push_ticker(stressed_ticker)
            await monitor.process_single_queue_item()
            assert account.current_state == "THROTTLED"

        asyncio.run(run_evaluation())

    def test_closed_bar_triggers_wick_emergency_flat(self) -> None:
        """Verify severe adverse wick on closed bar triggers EMERGENCY_FLAT state."""

        async def run_wick_eval() -> None:
            account = HardenedSharedMarginAccount(
                starting_capital=Decimal("100.00"),
                config=CircuitBreakerConfig(emergency_wick_threshold=Decimal("0.10")),
            )
            monitor = CircuitBreakerFeedMonitor(account=account, symbol="BTCUSDT")
            crash_bar = CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
                close_time=datetime(2026, 9, 6, 0, 5, tzinfo=UTC),
                open=Decimal("100.0"),
                high=Decimal("100.0"),
                low=Decimal("88.0"),
                close=Decimal("88.0"),  # 12% drop
                volume=Decimal("100.0"),
                quote_volume=Decimal("9400.0"),
                trades=500,
                taker_buy_base=Decimal("10.0"),
                taker_buy_quote=Decimal("900.0"),
                is_closed=True,
            )
            await monitor.push_bar(crash_bar)
            await monitor.process_single_queue_item()
            assert account.current_state == "EMERGENCY_FLAT"

        asyncio.run(run_wick_eval())

    def test_inprogress_bar_skips_closed_evaluations(self) -> None:
        """Verify is_closed=False bars do not trigger finalized candle circuit evaluations."""

        async def run_inprogress() -> None:
            account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
            monitor = CircuitBreakerFeedMonitor(account=account, symbol="BTCUSDT")
            bar = CanonicalBar(
                symbol="BTCUSDT",
                interval="5m",
                timestamp=datetime(2026, 9, 6, 0, 0, tzinfo=UTC),
                close_time=datetime(2026, 9, 6, 0, 5, tzinfo=UTC),
                open=Decimal("100.0"),
                high=Decimal("100.0"),
                low=Decimal("85.0"),
                close=Decimal("85.0"),
                volume=Decimal("10.0"),
                quote_volume=Decimal("900.0"),
                trades=50,
                taker_buy_base=Decimal("1.0"),
                taker_buy_quote=Decimal("90.0"),
                is_closed=False,  # Still forming
            )
            await monitor.push_bar(bar)
            await monitor.process_single_queue_item()
            assert account.current_state == "NORMAL"

        asyncio.run(run_inprogress())


class TestProbeKainodeLiveFeed:
    """Validates scripts/probe_kainode_live_feed.py CLI, schema, and safety invariants."""

    def test_cli_argument_defaults(self) -> None:
        """Verify default CLI arguments: 60.0s duration, default output path, 4 pairs."""
        parser = build_probe_arg_parser()
        args = parser.parse_args([])
        assert args.duration == 60.0
        assert args.output == Path("artifacts/research/phase257/live-feed-probe-summary.json")
        assert args.symbols == "BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT"

    def test_cli_argument_overrides(self, tmp_path: Path) -> None:
        """Verify custom CLI argument overrides."""
        out_file = tmp_path / "custom_probe.json"
        parser = build_probe_arg_parser()
        args = parser.parse_args(
            [
                "--duration",
                "15.5",
                "--output",
                str(out_file),
                "--symbols",
                "BTCUSDT,ETHUSDT",
            ]
        )
        assert args.duration == 15.5
        assert args.output == out_file
        assert args.symbols == "BTCUSDT,ETHUSDT"

    def test_cli_rejects_negative_or_zero_duration(self) -> None:
        """Verify CLI parser rejects non-positive duration."""
        with pytest.raises(SystemExit):
            parse_probe_cli_args(["--duration", "-5.0"])
        with pytest.raises(SystemExit):
            parse_probe_cli_args(["--duration", "0.0"])

    def test_summary_schema_validation(self, tmp_path: Path) -> None:
        """Verify generated probe summary matches required JSON schema."""
        summary_path = tmp_path / "summary.json"
        generate_mock_probe_summary(summary_path)

        assert summary_path.exists()
        data = json.loads(summary_path.read_text(encoding="utf-8"))

        assert data["phase"] == "phase_257"
        assert "probe_metadata" in data
        assert "network_telemetry" in data
        assert "spread_stability" in data
        assert "circuit_breaker_telemetry" in data
        assert "safety_invariants" in data

        latency = data["network_telemetry"]["ingestion_latency_ms"]
        assert all(k in latency for k in ("min", "p50", "p95", "p99", "max"))

    def test_zero_order_safety_invariants_asserted(self, tmp_path: Path) -> None:
        """Verify strict assertion of read-only safety invariants."""
        summary_path = tmp_path / "summary.json"
        generate_mock_probe_summary(summary_path)
        data = json.loads(summary_path.read_text(encoding="utf-8"))

        safety = data["safety_invariants"]
        assert safety["orders_submitted"] == 0
        assert safety["execution_authority"] is False
        assert safety["api_keys_loaded"] == 0
        assert safety["authenticated_endpoints_accessed"] is False
        assert safety["read_only_streams_only"] is True
        assert safety["promotion_state"] == "unpromoted"
        assert safety["live_trading_activation"] is False
        assert safety["zero_secret_leakage"] is True

        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            verify_strict_safety_invariants(orders_submitted=1)


class TestTelemetryAccumulatorMetrics:
    """Validates math and percentile calculations in FeedTelemetryAccumulator."""

    def test_percentile_computation(self) -> None:
        """Verify percentile calculation on float and Decimal lists."""
        float_vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert _compute_float_percentile(float_vals, 50.0) == 30.0
        assert _compute_float_percentile(float_vals, 0.0) == 10.0
        assert _compute_float_percentile(float_vals, 100.0) == 50.0

        dec_vals = [Decimal("1.0"), Decimal("2.0"), Decimal("3.0"), Decimal("4.0")]
        p50 = _compute_decimal_percentile(dec_vals, 50.0)
        assert p50 == Decimal("2.5")

    def test_accumulator_snapshot_empty(self) -> None:
        """Verify accumulator returns clean zero-valued snapshot when empty."""
        acc = FeedTelemetryAccumulator(symbols=("BTCUSDT",))
        snap = acc.snapshot()
        assert snap.total_messages == 0
        assert snap.latency_overall.count == 0
        assert snap.latency_overall.p50_ms == 0.0

    def test_accumulator_record_and_summary(self) -> None:
        """Verify recording messages and compiling summary."""
        acc = FeedTelemetryAccumulator(symbols=("BTCUSDT",))
        acc.start()

        # Add 3 messages with known latencies: 80ms, 90ms, 100ms
        now_ms = 1788622964000.0
        acc.record_message("btcusdt@bookTicker", "BTCUSDT", int(now_ms - 80), now_ms)
        acc.record_message("btcusdt@bookTicker", "BTCUSDT", int(now_ms - 90), now_ms)
        acc.record_message("btcusdt@bookTicker", "BTCUSDT", int(now_ms - 100), now_ms)

        acc.record_spread("BTCUSDT", Decimal("0.0125"))
        acc.record_spread("BTCUSDT", Decimal("0.0135"))

        acc.stop()
        summary = acc.compile_summary(elapsed_seconds=1.0)
        assert summary["total_messages_received"] == 3
        net = summary.get("network_telemetry", summary)
        lat = net["ingestion_latency_ms"]
        assert lat["min"] == 80.0
        assert lat["max"] == 100.0
        assert lat["p50"] == 90.0
        assert "BTCUSDT" in summary["by_symbol"]
