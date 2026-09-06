"""Phase 258: Unit & Integration Test Suite for Live Paper Engine and Controlled Runner.

Validates:
- Live feed paper engine initialization and zero-credential boundary.
- Top-of-book simulated fills with 2 bps adverse slippage and 0.04% taker fees.
- Single shared 100 USDT margin pool, 80% utilization ceiling, >=20% reserve buffer.
- Dynamic leverage scaling (1.0x to 3.0x) and stress de-escalation.
- Tick-level ATR stop-loss, trailing stops, spread blowout halts (>=20 bps).
- Whole-second timestamp truncation (microsecond=0) preserving lifecycle invariants.
- Exact Decimal cash balance reconciliation with zero balance drift.
- Mock WebSocket feed streaming for bookTicker and kline_5m messages.
- Runner CLI argument parsing and structured summary JSON generation.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.client import BinancePublicFeedClient
from autonomous_futures.feed.models import (
    TickerSnapshot,
)
from autonomous_futures.paper.circuit_breakers import (
    HardenedSharedMarginAccount,
)
from autonomous_futures.paper.live_engine import (
    DEFAULT_SYMBOLS,
    LivePaperEngine,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
)

# Repo root for scripts
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_phase_258_live_paper import (  # noqa: E402
    generate_deterministic_doge_warmup,
    parse_cli_args,
    verify_strict_safety_invariants,
)


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


@pytest.fixture
def candidate_btc() -> CreatorCandidateArtifact:
    cand_path = Path(
        "artifacts/research/phase252/candidates/cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json"
    )
    if cand_path.is_file():
        return read_creator_candidate_artifact(cand_path)
    pytest.skip("Candidate file not found")


@pytest.fixture
def candidates_all() -> dict[str, CreatorCandidateArtifact]:
    cand_dir = Path("artifacts/research/phase252/candidates")
    if not cand_dir.is_dir():
        pytest.skip("Candidates directory not found")
    cands: dict[str, CreatorCandidateArtifact] = {}
    for p in cand_dir.glob("cand-*.json"):
        c = read_creator_candidate_artifact(p)
        cands[c.strategy.universe.symbols[0]] = c
    return cands


@pytest.fixture
def sample_ticker_btc() -> TickerSnapshot:
    now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    return TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("60000.00"),
        best_bid_qty=Decimal("2.5"),
        best_ask_price=Decimal("60001.00"),
        best_ask_qty=Decimal("3.0"),
        transaction_time=now,
        event_time=now,
    )


class TestLivePaperEngineInitialization:
    """Validates engine initialization, shared margin defaults, and safety boundaries."""

    def test_nominal_initialization(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        ledger_db = tmp_path / "test-ledger.sqlite3"
        lifecycle_db = tmp_path / "test-lifecycle.sqlite3"
        observations_db = tmp_path / "test-observations.sqlite3"

        engine = LivePaperEngine(
            symbols=DEFAULT_SYMBOLS,
            starting_capital=Decimal("100.00"),
            ledger_db=ledger_db,
            lifecycle_db=lifecycle_db,
            observations_db=observations_db,
            candidates=candidates_all,
        )

        assert engine.account.cash == Decimal("100.00")
        assert engine.account.starting_capital == Decimal("100.00")
        assert engine.account.max_utilization == Decimal("0.80")
        assert engine.account.min_reserve_buffer == Decimal("0.20")
        assert len(engine.active_trades) == 0
        assert engine.total_closed_trades == 0
        assert engine.current_equity() == Decimal("100.00")
        assert engine.feed_client.api_key is None
        assert engine.feed_client.api_secret is None

    def test_zero_credential_guardrail_rejection(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="strictly forbidden"):
            BinancePublicFeedClient(
                symbols=("BTCUSDT",),
                api_key="secret-key-that-must-be-rejected",  # Forbidden
            )


class TestTopOfBookPricingAndAdverseExecution:
    """Validates top-of-book simulated fills, 2 bps slippage, and 0.04% taker fees."""

    def test_long_entry_fill_pricing(
        self,
        tmp_path: Path,
        candidates_all: dict[str, CreatorCandidateArtifact],
        sample_ticker_btc: TickerSnapshot,
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )
        engine.latest_tickers["BTCUSDT"] = sample_ticker_btc

        # Execute LONG entry
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        res = engine.execute_open(
            symbol="BTCUSDT",
            signal=1,  # LONG
            conviction=Decimal("0.75"),
            event_time=now,
        )
        assert res is not None
        assert res.status == "opened"

        # Long lifts the ask: mark_price is best_ask_price (60001.00)
        expected_fill = Decimal("60001.00") * (Decimal("1") + Decimal("0.0002"))
        assert res.fill_price == expected_fill

        # Taker fee is 0.04%
        open_entry = next(iter(engine.active_trades.values())).open_entry
        expected_fee = expected_fill * open_entry.quantity * Decimal("0.0004")
        assert res.entry_fee == expected_fee

        # Entry slippage friction
        expected_slip = abs(expected_fill - Decimal("60001.00")) * open_entry.quantity
        assert open_entry.slippage_cost == expected_slip

        # Cash debited by entry fee
        assert engine.account.cash == Decimal("100.00") - expected_fee

    def test_short_entry_fill_pricing(
        self,
        tmp_path: Path,
        candidates_all: dict[str, CreatorCandidateArtifact],
        sample_ticker_btc: TickerSnapshot,
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )
        engine.latest_tickers["BTCUSDT"] = sample_ticker_btc

        # Execute SHORT entry
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        res = engine.execute_open(
            symbol="BTCUSDT",
            signal=-1,  # SHORT
            conviction=Decimal("0.50"),
            event_time=now,
        )
        assert res is not None
        assert res.status == "opened"

        # Short hits the bid: mark_price is best_bid_price (60000.00)
        expected_fill = Decimal("60000.00") * (Decimal("1") - Decimal("0.0002"))
        assert res.fill_price == expected_fill

    def test_round_trip_exit_pricing_and_exact_pnl(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )
        # Entry quote
        t1 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("50000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("50000.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t1,
            event_time=t1,
        )
        open_res = engine.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("0.50"), event_time=t1
        )
        assert open_res is not None and open_res.status == "opened"
        entry_fill = open_res.fill_price
        entry_fee = open_res.entry_fee
        assert entry_fee > Decimal("0")
        assert entry_fill == Decimal("50000.00") * Decimal("1.0002")

        # Exit quote: Market price rises to 52000.00
        t2 = datetime(2026, 9, 6, 12, 5, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("52000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("52001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t2,
            event_time=t2,
        )
        close_res = engine.execute_close("BTCUSDT", exit_reason="take_profit", event_time=t2)
        assert close_res is not None and close_res.status == "closed"

        # Long exit hits the bid (52000.00) with adverse slippage (-2 bps)
        expected_exit_fill = Decimal("52000.00") * (Decimal("1") - Decimal("0.0002"))
        assert close_res.fill_price == expected_exit_fill

        # Assert net PnL invariant: net_pnl == gross_pnl - entry_fee - exit_fee
        assert close_res.net_pnl == close_res.gross_pnl - close_res.entry_fee - close_res.exit_fee


class TestSharedMarginAndDynamicLeverage:
    """Validates shared 100 USDT cash pool, dynamic leverage, and 80% ceiling rejection."""

    def test_dynamic_leverage_scaling(self, tmp_path: Path) -> None:
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))

        # In NORMAL state: leverage = 1.0 + 4.0 * (conviction - 0.50)
        assert account.calculate_hardened_leverage(Decimal("0.50")) == Decimal("1.0")
        assert account.calculate_hardened_leverage(Decimal("0.625")) == Decimal("1.5")
        assert account.calculate_hardened_leverage(Decimal("0.75")) == Decimal("2.0")
        assert account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("3.0")

        # Volatility surge de-escalation: clamped to 1.0x
        assert account.calculate_hardened_leverage(
            Decimal("1.00"), volatility_ratio=Decimal("2.5")
        ) == Decimal("1.0")

        # Throttled state de-escalation: clamped to 1.0x
        account.current_state = "THROTTLED"
        assert account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("1.0")

        # Halted state: clamped to 0.0x
        account.current_state = "HALTED"
        assert account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("0.0")

    def test_80_percent_utilization_ceiling_rejection(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
        engine = LivePaperEngine(
            symbols=symbols,
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

        # Set nominal tickers for all 4 symbols
        for sym, price in [
            ("BTCUSDT", Decimal("60000")),
            ("ETHUSDT", Decimal("3000")),
            ("SOLUSDT", Decimal("150")),
            ("DOGEUSDT", Decimal("0.15")),
        ]:
            engine.latest_tickers[sym] = TickerSnapshot(
                symbol=sym,
                best_bid_price=price,
                best_bid_qty=Decimal("10"),
                best_ask_price=price * Decimal("1.0001"),
                best_ask_qty=Decimal("10"),
                transaction_time=now,
                event_time=now,
            )

        # Open 4 concurrent positions of 20% each (total 80% locked margin)
        for sym in symbols:
            res = engine.execute_open(sym, signal=1, conviction=Decimal("0.50"), event_time=now)
            assert res is not None and res.status == "opened"

        assert len(engine.active_trades) == 4
        # Total locked margin = 4 * 20 USDT = 80 USDT (80.00% utilization)
        assert engine.account.total_locked_margin() == Decimal("80.00")
        assert engine.account.margin_utilization(engine.current_equity()) <= Decimal("0.801")

        # Attempting a 5th trade allocation MUST be rejected
        alloc = engine.account.allocate_order(
            symbol="BTCUSDT",
            confidence=Decimal("1.0"),
            mark_price=Decimal("60000"),
            current_equity=engine.current_equity(),
        )
        assert alloc is None, "5th allocation must be rejected by 80% utilization ceiling"


class TestCircuitBreakersAndTickStops:
    """Validates spread blowout halts, intra-tick stop loss, and trailing stops."""

    def test_spread_blowout_halt_rejection(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

        # Ticker with 25 bps spread (> 20 bps threshold)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60150.00"),  # Spread = 150 -> 25 bps
            best_ask_qty=Decimal("1.0"),
            transaction_time=now,
            event_time=now,
        )
        assert engine.latest_tickers["BTCUSDT"].spread_bps > Decimal("20.0")

        # Entry MUST be halted/rejected
        res = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=now)
        assert res is None

    def test_intra_tick_atr_stop_loss_trigger(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )
        t1 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t1,
            event_time=t1,
        )
        engine.monitor._rolling_atrs["BTCUSDT"] = Decimal("500.0")  # ATR = 500

        # Open Long: stop_loss = fill_price - 1.5 * ATR ~= 60013 - 750 = 59263
        open_res = engine.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("0.50"), event_time=t1
        )
        assert open_res is not None and open_res.status == "opened"
        trade = engine.active_trades["BTCUSDT"]
        stop_price = trade.stop_price
        assert stop_price < Decimal("60000.00")

        # Ingest a severe tick crashing below the stop loss
        t2 = datetime(2026, 9, 6, 12, 0, 5, tzinfo=UTC)
        crash_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=stop_price - Decimal("10.00"),  # Below stop
            best_bid_qty=Decimal("1.0"),
            best_ask_price=stop_price - Decimal("9.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t2,
            event_time=t2,
        )
        asyncio.run(engine.handle_ticker(crash_ticker))

        # Trade must be closed immediately
        assert "BTCUSDT" not in engine.active_trades
        assert engine.total_closed_trades == 1

    def test_intra_tick_trailing_stop_ratchet(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )
        t1 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t1,
            event_time=t1,
        )
        engine.monitor._rolling_atrs["BTCUSDT"] = Decimal("200.0")  # ATR = 200

        engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.50"), event_time=t1)
        initial_stop = engine.active_trades["BTCUSDT"].stop_price

        # Ingest higher prices (rally to 60400, below 60613 target)
        t2 = datetime(2026, 9, 6, 12, 1, 0, tzinfo=UTC)
        rally_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60400.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60401.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t2,
            event_time=t2,
        )
        asyncio.run(engine.handle_ticker(rally_ticker))

        # Trailing stop price must have ratcheted up (trailing stop = 60400 - 1.0 * 200 = 60200)
        ratcheted_stop = engine.active_trades["BTCUSDT"].trailing_stop_price
        assert ratcheted_stop is not None and ratcheted_stop > initial_stop

    def test_whole_second_timestamp_truncation(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )
        # Timestamp with microseconds
        ts_with_ms = datetime(2026, 9, 6, 12, 30, 45, 987654, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=ts_with_ms,
            event_time=ts_with_ms,
        )

        res = engine.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("0.50"), event_time=ts_with_ms
        )
        assert res is not None and res.status == "opened"

        # Check recorded occurred_at has microsecond == 0
        trade = engine.active_trades["BTCUSDT"]
        assert trade.opened_at.microsecond == 0
        assert trade.open_entry.occurred_at.microsecond == 0

        # Mark position with another timestamp having microseconds
        ts2_with_ms = ts_with_ms + timedelta(seconds=10, microseconds=123456)
        engine._mark_active_position(trade, Decimal("60050.00"), ts2_with_ms)

        # Check marks in lifecycle DB: must have succeeded with zero ValueError
        marks = engine.lifecycle_store.read(
            candidate_id=trade.candidate_id,
            candidate_artifact_hash=trade.candidate_artifact_hash,
            trade_id=trade.trade_id,
        )
        assert len(marks) >= 1
        assert marks[-1].marked_at.microsecond == 0


class TestZeroBalanceDriftReconciliation:
    """Validates exact Decimal cash reconciliation and zero drift across multiple trades."""

    def test_exact_balance_reconciliation(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT", "ETHUSDT"),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )

        # Trade 1: BTCUSDT Winning Long Trade
        t1 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("50000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("50000.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t1,
            event_time=t1,
        )
        engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.50"), event_time=t1)

        t2 = datetime(2026, 9, 6, 12, 5, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("51000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("51001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t2,
            event_time=t2,
        )
        engine.execute_close("BTCUSDT", exit_reason="profit", event_time=t2)

        # Trade 2: ETHUSDT Losing Short Trade
        t3 = datetime(2026, 9, 6, 12, 10, 0, tzinfo=UTC)
        engine.latest_tickers["ETHUSDT"] = TickerSnapshot(
            symbol="ETHUSDT",
            best_bid_price=Decimal("3000.00"),
            best_bid_qty=Decimal("5.0"),
            best_ask_price=Decimal("3000.00"),
            best_ask_qty=Decimal("5.0"),
            transaction_time=t3,
            event_time=t3,
        )
        engine.execute_open("ETHUSDT", signal=-1, conviction=Decimal("0.75"), event_time=t3)

        t4 = datetime(2026, 9, 6, 12, 15, 0, tzinfo=UTC)
        engine.latest_tickers["ETHUSDT"] = TickerSnapshot(
            symbol="ETHUSDT",
            best_bid_price=Decimal("3050.00"),
            best_bid_qty=Decimal("5.0"),
            best_ask_price=Decimal("3050.00"),
            best_ask_qty=Decimal("5.0"),
            transaction_time=t4,
            event_time=t4,
        )
        engine.execute_close("ETHUSDT", exit_reason="stop", event_time=t4)

        # Perform reconciliation
        rec = engine.reconcile_balances()
        assert rec["zero_balance_drift"] is True
        assert Decimal(rec["drift"]) == Decimal("0")
        assert rec["closed_trades_count"] == 2
        assert rec["open_positions_count"] == 0

        # Verify summary output artifact
        summary = engine.build_summary(duration_target=600.0, output_path=tmp_path / "summary.json")
        assert summary["shared_portfolio_margin"]["zero_balance_drift"] is True
        assert summary["portfolio_summary"]["total_trades"] == 2
        assert summary["safety_invariants"]["orders_submitted"] == 0


class TestMockWebSocketFeedStreaming:
    """Validates client streaming from mock WebSocket session into LivePaperEngine."""

    def test_mock_websocket_ingestion(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger.sqlite3",
            lifecycle_db=tmp_path / "lifecycle.sqlite3",
            observations_db=tmp_path / "obs.sqlite3",
            candidates=candidates_all,
        )

        now_ms = int(datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)

        # Mock bookTicker and kline_5m messages
        book_ticker_msg = json.dumps(
            {
                "stream": "btcusdt@bookTicker",
                "data": {
                    "e": "bookTicker",
                    "u": 1234567,
                    "s": "BTCUSDT",
                    "b": "60000.00",
                    "B": "2.5",
                    "a": "60001.00",
                    "A": "3.0",
                    "T": now_ms,
                    "E": now_ms,
                },
            }
        )
        kline_msg = json.dumps(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "e": "kline",
                    "E": now_ms,
                    "s": "BTCUSDT",
                    "k": {
                        "t": now_ms,
                        "T": now_ms + 299999,
                        "s": "BTCUSDT",
                        "i": "5m",
                        "o": "59950.00",
                        "c": "60000.50",
                        "h": "60020.00",
                        "l": "59940.00",
                        "v": "50.0",
                        "n": 120,
                        "x": True,  # Closed bar
                        "q": "3000000.0",
                        "V": "25.0",
                        "Q": "1500000.0",
                    },
                },
            }
        )

        mock_ws = MockWebSocketSession([book_ticker_msg, kline_msg])

        async def run_consume() -> None:
            await engine.feed_client.consume_stream(
                mock_ws,
                duration_seconds=10.0,
                on_bar=engine.handle_bar,
                on_ticker=engine.handle_ticker,
            )

        asyncio.run(run_consume())

        # Verify ticker snapshot was processed
        assert "BTCUSDT" in engine.latest_tickers
        assert engine.latest_tickers["BTCUSDT"].best_bid_price == Decimal("60000.00")

        # Verify bar was finalized in history
        assert len(engine._bar_history["BTCUSDT"]) == 1
        assert engine._bar_history["BTCUSDT"][0]["close"] == Decimal("60000.50")


class TestLivePaperRunnerCLIAndSummary:
    """Validates CLI argument parsing, safety invariants, and helper functions."""

    def test_cli_argument_parsing(self) -> None:
        args = parse_cli_args(["--duration", "900.0", "--starting-capital", "150.00"])
        assert args.duration == 900.0
        assert args.starting_capital == Decimal("150.00")

    def test_cli_argument_validation_errors(self) -> None:
        with pytest.raises(SystemExit):
            parse_cli_args(["--duration", "-10.0"])
        with pytest.raises(SystemExit):
            parse_cli_args(["--starting-capital", "0.00"])

    def test_strict_safety_invariants_verification(self) -> None:
        # Nominal: should pass
        inv = verify_strict_safety_invariants(orders_submitted=0)
        assert inv["orders_submitted"] == 0
        assert inv["execution_authority"] is False
        assert inv["live_trading_activation"] is False

        # Invariant breach: orders submitted > 0
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION"):
            verify_strict_safety_invariants(orders_submitted=1)

    def test_deterministic_doge_warmup_generation(self) -> None:
        df = generate_deterministic_doge_warmup(bars_count=50)
        assert len(df) == 50
        assert "open" in df.columns
        assert "close" in df.columns
        assert (df["high"] >= df["low"]).all()
