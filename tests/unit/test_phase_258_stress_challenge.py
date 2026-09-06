"""Phase 258 Milestone M1: Empirical Stress Testing Suite.

Adversarial stress testing for LivePaperEngine, top-of-book simulated execution,
dynamic leverage boundary conditions, circuit breaker halts, and equity floor invariants:
1. Sudden price gaps:
   - Sudden -20% gap on Long position (ATR stop execution, zero balance drift, equity > 0).
   - Sudden +20% gap on Short position (ATR stop execution, zero balance drift, equity > 0).
   - Sudden +20% gap on Long position (Take-profit execution, positive PnL).
   - Simultaneous -20% gap across all 4 portfolio positions under 80% maximum margin utilization
     (Equity guaranteed > 0, zero liquidation risk).
2. Crossed bid/ask books:
   - TickerSnapshot strict model-level rejection of crossed books (best_bid > best_ask).
   - Wire parser parse_binance_book_ticker rejection of crossed books.
3. Massive spread blowouts (>= 50 bps):
   - Entry order rejection on spread >= 20 bps and >= 50 bps.
   - Circuit breaker transition to HALTED state on 50 bps spread blowout.
   - Permanent inhibition of new entries in HALTED state (no auto-resume).
4. Dynamic leverage boundary conditions:
   - Conviction < 0.50 (clamped floor to 1.0x).
   - Conviction = 0.50 (1.0x).
   - Conviction = 0.75 (2.0x).
   - Conviction = 1.00 (3.0x).
   - Conviction > 1.00 (clamped ceiling to 3.0x).
   - Stress de-escalation: volatility surge, slippage surge, THROTTLED, HALTED.
5. Rapid tick update stress:
   - Ingestion of 5,000+ rapid ticks across candidate universe with zero unhandled exceptions.
   - Non-blocking queue behavior and graceful shutdown.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonomous_futures.feed.models import (
    CanonicalBar,
    TickerSnapshot,
    parse_binance_book_ticker,
)
from autonomous_futures.paper.circuit_breakers import (
    HardenedSharedMarginAccount,
)
from autonomous_futures.paper.live_engine import (
    LivePaperEngine,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
)


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


class TestSuddenPriceGapsAndEquityFloor:
    """Stress tests sudden price gaps (down 20%, up 20%) and verifies equity floor > 0."""

    def test_long_position_sudden_down_20_percent_gap(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """Sudden -20% gap on Long at 3.0x leverage triggers stop; equity remains strictly > 0."""
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger_gap_down.sqlite3",
            lifecycle_db=tmp_path / "lifecycle_gap_down.sqlite3",
            observations_db=tmp_path / "obs_gap_down.sqlite3",
            candidates=candidates_all,
        )
        t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t0,
            event_time=t0,
        )

        # Open Long at 3.0x leverage (conviction = 1.00)
        open_res = engine.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("1.00"), event_time=t0
        )
        assert open_res is not None and open_res.status == "opened"
        trade = engine.active_trades["BTCUSDT"]
        assert trade.leverage == Decimal("3.0")
        assert trade.base_margin == Decimal("20.00")  # 20% of 100 USDT

        # Sudden price gap down 20%: from 60,000 to 48,000
        t1 = datetime(2026, 9, 6, 12, 0, 1, tzinfo=UTC)
        crash_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("48000.00"),
            best_bid_qty=Decimal("2.0"),
            best_ask_price=Decimal("48002.00"),
            best_ask_qty=Decimal("2.0"),
            transaction_time=t1,
            event_time=t1,
        )

        asyncio.run(engine.handle_ticker(crash_ticker))

        # Position must be closed by stop loss immediately
        assert "BTCUSDT" not in engine.active_trades
        assert engine.total_closed_trades == 1

        # Assert equity never drops <= 0
        current_eq = engine.current_equity()
        assert current_eq > Decimal("0"), f"Equity must be strictly positive, got {current_eq}"
        assert engine.account.cash > Decimal("0"), (
            f"Cash must be positive, got {engine.account.cash}"
        )
        assert engine.account.cash > Decimal("80.00")  # Loss is ~12 USDT on 60 USDT notional

        # Assert exact zero balance drift
        reconciliation = engine.reconcile_balances()
        assert reconciliation["zero_balance_drift"] is True
        assert Decimal(reconciliation["drift"]) <= Decimal("0.0001")

    def test_short_position_sudden_up_20_percent_gap(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """Sudden +20% gap on Short at 3.0x leverage triggers stop; equity remains strictly > 0."""
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger_gap_up.sqlite3",
            lifecycle_db=tmp_path / "lifecycle_gap_up.sqlite3",
            observations_db=tmp_path / "obs_gap_up.sqlite3",
            candidates=candidates_all,
        )
        t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t0,
            event_time=t0,
        )

        # Open Short at 3.0x leverage (conviction = 1.00)
        open_res = engine.execute_open(
            "BTCUSDT", signal=-1, conviction=Decimal("1.00"), event_time=t0
        )
        assert open_res is not None and open_res.status == "opened"
        trade = engine.active_trades["BTCUSDT"]
        assert trade.side == "SHORT"
        assert trade.leverage == Decimal("3.0")

        # Sudden price gap up 20%: from 60,000 to 72,000
        t1 = datetime(2026, 9, 6, 12, 0, 1, tzinfo=UTC)
        surge_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("71998.00"),
            best_bid_qty=Decimal("1.5"),
            best_ask_price=Decimal("72000.00"),
            best_ask_qty=Decimal("1.5"),
            transaction_time=t1,
            event_time=t1,
        )

        asyncio.run(engine.handle_ticker(surge_ticker))

        # Position must be closed by stop loss immediately
        assert "BTCUSDT" not in engine.active_trades
        assert engine.total_closed_trades == 1

        # Assert equity never drops <= 0
        current_eq = engine.current_equity()
        assert current_eq > Decimal("0")
        assert engine.account.cash > Decimal("0")
        assert engine.account.cash > Decimal("80.00")

        # Assert exact zero balance drift
        reconciliation = engine.reconcile_balances()
        assert reconciliation["zero_balance_drift"] is True

    def test_long_position_sudden_up_20_percent_gap_take_profit(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """Sudden +20% favorable gap on Long triggers take-profit; cash reconciles with profit."""
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger_tp.sqlite3",
            lifecycle_db=tmp_path / "lifecycle_tp.sqlite3",
            observations_db=tmp_path / "obs_tp.sqlite3",
            candidates=candidates_all,
        )
        t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t0,
            event_time=t0,
        )

        open_res = engine.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("1.00"), event_time=t0
        )
        assert open_res is not None and open_res.status == "opened"

        # Sudden price gap UP 20% to 72,000
        t1 = datetime(2026, 9, 6, 12, 0, 1, tzinfo=UTC)
        surge_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("72000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("72002.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t1,
            event_time=t1,
        )

        asyncio.run(engine.handle_ticker(surge_ticker))

        assert "BTCUSDT" not in engine.active_trades
        assert engine.total_closed_trades == 1
        assert engine.winning_trades == 1
        assert engine.account.cash > Decimal("100.00")  # Profit secured
        assert engine.reconcile_balances()["zero_balance_drift"] is True

    def test_simultaneous_down_20_percent_gap_all_four_assets_equity_invariant(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """Simultaneous -20% crash across 4 positions at 3.0x leverage preserves Equity."""
        symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
        engine = LivePaperEngine(
            symbols=symbols,
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger_crash_all.sqlite3",
            lifecycle_db=tmp_path / "lifecycle_crash_all.sqlite3",
            observations_db=tmp_path / "obs_crash_all.sqlite3",
            candidates=candidates_all,
        )
        t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

        nominal_prices = {
            "BTCUSDT": Decimal("60000.00"),
            "ETHUSDT": Decimal("3000.00"),
            "SOLUSDT": Decimal("150.00"),
            "DOGEUSDT": Decimal("0.1500"),
        }

        # Set nominal tickers and open 4 Long positions at 3.0x leverage (80% utilization)
        for sym in symbols:
            p = nominal_prices[sym]
            engine.latest_tickers[sym] = TickerSnapshot(
                symbol=sym,
                best_bid_price=p,
                best_bid_qty=Decimal("100.0"),
                best_ask_price=p * Decimal("1.0001"),
                best_ask_qty=Decimal("100.0"),
                transaction_time=t0,
                event_time=t0,
            )
            res = engine.execute_open(sym, signal=1, conviction=Decimal("1.00"), event_time=t0)
            assert res is not None and res.status == "opened"

        assert len(engine.active_trades) == 4
        # Total locked margin = 4 * 20.00 = 80.00 USDT (80% utilization cap)
        assert engine.account.total_locked_margin() == Decimal("80.00")
        # Entry fees (~0.17 USDT on 3x notional) slightly reduce equity from 100 to ~99.83 USDT
        assert engine.account.margin_utilization(engine.current_equity()) <= Decimal("0.805")

        # Ingest simultaneous -20% gap on all 4 assets
        t1 = datetime(2026, 9, 6, 12, 0, 1, tzinfo=UTC)
        for sym in symbols:
            crashed_p = nominal_prices[sym] * Decimal("0.80")  # -20%
            crash_ticker = TickerSnapshot(
                symbol=sym,
                best_bid_price=crashed_p,
                best_bid_qty=Decimal("50.0"),
                best_ask_price=crashed_p * Decimal("1.0001"),
                best_ask_qty=Decimal("50.0"),
                transaction_time=t1,
                event_time=t1,
            )
            asyncio.run(engine.handle_ticker(crash_ticker))

        # All 4 positions must have triggered ATR stop-loss and closed
        assert len(engine.active_trades) == 0
        assert engine.total_closed_trades == 4

        # Non-negative equity invariant check
        final_equity = engine.current_equity()
        final_cash = engine.account.cash
        assert final_equity > Decimal("0"), f"Equity must be strictly > 0, got {final_equity}"
        assert final_cash > Decimal("0"), f"Cash must be strictly > 0, got {final_cash}"
        # Sizing guarantee: 240 USDT notional * 20% loss = 48 USDT loss. Cash ~ 51.8 USDT.
        assert final_cash > Decimal("50.00"), f"Expected cash > 50 USDT, got {final_cash}"

        # Reconciliation check
        rec = engine.reconcile_balances()
        assert rec["zero_balance_drift"] is True
        assert Decimal(rec["drift"]) <= Decimal("0.0001")


class TestCrossedBidAskBooksHandling:
    """Stress tests crossed bid/ask books (best_bid > best_ask) handling and validation."""

    def test_ticker_snapshot_strictly_rejects_crossed_book(self) -> None:
        """Constructing a TickerSnapshot where best_bid > best_ask raises ValidationError."""
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValidationError, match="crossed book detected"):
            TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=Decimal("60010.00"),  # Crossed: bid > ask
                best_bid_qty=Decimal("1.0"),
                best_ask_price=Decimal("60000.00"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=now,
                event_time=now,
            )

    def test_parse_binance_book_ticker_rejects_crossed_book_wire_frame(self) -> None:
        """Parsing a Binance bookTicker wire payload with crossed prices raises ValidationError."""
        crossed_payload = {
            "stream": "btcusdt@bookTicker",
            "data": {
                "s": "BTCUSDT",
                "b": "60050.00",  # Bid > Ask
                "B": "1.5",
                "a": "60000.00",
                "A": "2.0",
                "T": 1788622800000,
                "E": 1788622800000,
            },
        }
        with pytest.raises(ValidationError, match="crossed book detected"):
            parse_binance_book_ticker(crossed_payload)


class TestMassiveSpreadBlowoutsAndCircuitBreakerHalts:
    """Stress tests massive spread blowouts (>= 50 bps) and automated circuit breaker halts."""

    def test_spread_blowout_50_bps_rejects_new_order_entry(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """Spread >= 50 bps (>> 20 bps halt threshold) immediately rejects new order entry."""
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger_spread.sqlite3",
            lifecycle_db=tmp_path / "lifecycle_spread.sqlite3",
            observations_db=tmp_path / "obs_spread.sqlite3",
            candidates=candidates_all,
        )
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

        # 60 bps spread blowout: bid=60000, ask=60360 (spread=360, mid=60180 -> 59.8 bps)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60360.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=now,
            event_time=now,
        )
        assert engine.latest_tickers["BTCUSDT"].spread_bps >= Decimal("50.0")

        # Order must be rejected immediately by spread safety guard
        res = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("1.00"), event_time=now)
        assert res is None
        assert len(engine.active_trades) == 0

    def test_spread_blowout_50_bps_triggers_circuit_breaker_halt(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """Ingesting 50 bps spread tick transitions CircuitBreakerFeedMonitor to HALTED."""
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger_halt.sqlite3",
            lifecycle_db=tmp_path / "lifecycle_halt.sqlite3",
            observations_db=tmp_path / "obs_halt.sqlite3",
            candidates=candidates_all,
        )
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

        assert str(engine.account.current_state) == "NORMAL"

        blowout_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60360.00"),  # ~59.8 bps
            best_ask_qty=Decimal("1.0"),
            transaction_time=now,
            event_time=now,
        )

        asyncio.run(engine.handle_ticker(blowout_ticker))
        # Drain monitor queue synchronously
        asyncio.run(engine.monitor.process_single_queue_item())

        # Account state must downgrade to HALTED
        assert str(engine.account.current_state) == "HALTED"

        # In HALTED state, allocate_order must return None
        alloc = engine.account.allocate_order(
            symbol="BTCUSDT",
            confidence=Decimal("1.00"),
            mark_price=Decimal("60000.00"),
            current_equity=Decimal("100.00"),
        )
        assert alloc is None, "allocate_order must reject orders in HALTED state"

        # In HALTED state, leverage is clamped to 0.0x
        assert engine.account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("0.0")

        # Subsequent order with normal spread must STILL be rejected due to persistent HALT
        normal_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=now + timedelta(seconds=1),
            event_time=now + timedelta(seconds=1),
        )
        engine.latest_tickers["BTCUSDT"] = normal_ticker
        res = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("1.00"), event_time=now)
        assert res is None, "HALTED state must inhibit entries even under normal spread"


class TestDynamicLeverageBoundaryConditions:
    """Stress tests dynamic leverage scaling across exact conviction boundaries."""

    def test_conviction_below_point_five_boundary(self) -> None:
        """Conviction < 0.50 is clamped to 1.0x minimum leverage floor in margin account."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        assert account.calculate_hardened_leverage(Decimal("0.00")) == Decimal("1.0")
        assert account.calculate_hardened_leverage(Decimal("0.20")) == Decimal("1.0")
        assert account.calculate_hardened_leverage(Decimal("0.40")) == Decimal("1.0")
        assert account.calculate_hardened_leverage(Decimal("0.4999")) == Decimal("1.0")

    def test_conviction_exact_point_five_boundary(self) -> None:
        """Conviction = 0.50 yields exactly 1.0x leverage."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        # 1.0 + 4.0 * (0.50 - 0.50) = 1.0x
        assert account.calculate_hardened_leverage(Decimal("0.50")) == Decimal("1.0")

    def test_conviction_exact_point_seven_five_boundary(self) -> None:
        """Conviction = 0.75 yields exactly 2.0x leverage."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        # 1.0 + 4.0 * (0.75 - 0.50) = 2.0x
        assert account.calculate_hardened_leverage(Decimal("0.75")) == Decimal("2.0")

    def test_conviction_exact_one_point_zero_boundary(self) -> None:
        """Conviction = 1.00 yields exactly 3.0x maximum leverage ceiling."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        # 1.0 + 4.0 * (1.00 - 0.50) = 3.0x
        assert account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("3.0")

    def test_conviction_above_one_point_zero_boundary(self) -> None:
        """Conviction > 1.00 is strictly clamped to 3.0x ceiling."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        assert account.calculate_hardened_leverage(Decimal("1.0001")) == Decimal("3.0")
        assert account.calculate_hardened_leverage(Decimal("1.25")) == Decimal("3.0")
        assert account.calculate_hardened_leverage(Decimal("2.00")) == Decimal("3.0")
        assert account.calculate_hardened_leverage(Decimal("10.00")) == Decimal("3.0")

    def test_dynamic_leverage_stress_de_escalation_rules(self) -> None:
        """Stress factors (volatility surge, slippage surge, throttled) clamp leverage to 1.0x."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))

        # Volatility ratio >= 2.0 clamps to 1.0x even with conviction = 1.00
        assert account.calculate_hardened_leverage(
            confidence=Decimal("1.00"), volatility_ratio=Decimal("2.0")
        ) == Decimal("1.0")
        assert account.calculate_hardened_leverage(
            confidence=Decimal("1.00"), volatility_ratio=Decimal("3.5")
        ) == Decimal("1.0")

        # Slippage ratio >= 5.0 clamps to 1.0x even with conviction = 1.00
        assert account.calculate_hardened_leverage(
            confidence=Decimal("1.00"), slippage_ratio=Decimal("5.0")
        ) == Decimal("1.0")

        # THROTTLED state clamps to 1.0x
        account.current_state = "THROTTLED"
        assert account.calculate_hardened_leverage(confidence=Decimal("1.00")) == Decimal("1.0")

        # HALTED state clamps to 0.0x
        account.current_state = "HALTED"
        assert account.calculate_hardened_leverage(confidence=Decimal("1.00")) == Decimal("0.0")

        # EMERGENCY_FLAT state clamps to 0.0x
        account.current_state = "EMERGENCY_FLAT"
        assert account.calculate_hardened_leverage(confidence=Decimal("1.00")) == Decimal("0.0")


class TestRapidTickBurstsAndQueueResilience:
    """Stress tests high-throughput rapid tick update processing and queue resilience."""

    def test_rapid_tick_burst_processing_clean_pass(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """5,000 rapid sequential tick updates process cleanly without unhandled exceptions."""
        engine = LivePaperEngine(
            symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger_burst.sqlite3",
            lifecycle_db=tmp_path / "lifecycle_burst.sqlite3",
            observations_db=tmp_path / "obs_burst.sqlite3",
            candidates=candidates_all,
        )

        base_time = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

        async def run_burst() -> None:
            symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
            prices = {
                "BTCUSDT": Decimal("60000.00"),
                "ETHUSDT": Decimal("3000.00"),
                "SOLUSDT": Decimal("150.00"),
                "DOGEUSDT": Decimal("0.1500"),
            }

            # Ingest 5,000 rapid ticks (1,250 per symbol)
            for i in range(5000):
                sym = symbols[i % 4]
                p = prices[sym] + Decimal(str((i % 20) - 10)) * Decimal("0.01")
                tick_time = base_time + timedelta(milliseconds=i * 10)
                ticker = TickerSnapshot(
                    symbol=sym,
                    best_bid_price=p,
                    best_bid_qty=Decimal("1.0"),
                    best_ask_price=p + Decimal("0.05"),
                    best_ask_qty=Decimal("1.0"),
                    transaction_time=tick_time,
                    event_time=tick_time,
                )
                await engine.handle_ticker(ticker)

        asyncio.run(run_burst())

        # Verify all 4 symbols have recorded latest tickers
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            assert sym in engine.latest_tickers
            assert engine.latest_tickers[sym].best_bid_price > Decimal("0")

        # Queue enqueued count must match total ticks pushed
        assert engine.monitor.enqueued_count == 5000
        assert engine.monitor.dropped_count == 0

        # Verify zero balance drift and clean shutdown
        rec = engine.reconcile_balances()
        assert rec["zero_balance_drift"] is True
        assert engine.current_equity() == Decimal("100.00")


class TestCircuitBreakerVolatilityAndDrawdownHalts:
    """Stress tests volatility surges and drawdown thresholds triggering circuit breaker halts."""

    def test_volatility_surge_triggers_halt(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """Bar with rolling ATR >= 3.0x baseline triggers CIRCUIT_BREAKER_VOLATILITY_HALT."""
        engine = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_path / "ledger_vol.sqlite3",
            lifecycle_db=tmp_path / "lifecycle_vol.sqlite3",
            observations_db=tmp_path / "obs_vol.sqlite3",
            candidates=candidates_all,
        )

        assert str(engine.account.current_state) == "NORMAL"
        baseline = Decimal("100.00")
        engine.monitor._baseline_atrs["BTCUSDT"] = baseline
        engine.monitor._rolling_atrs["BTCUSDT"] = Decimal("350.00")  # 3.5x baseline (> 3.0x halt)

        # High-volatility bar close (TR >= 3000 -> rolling ATR >= 3.0x baseline)
        t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        bar = CanonicalBar(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=t0,
            close_time=t0 + timedelta(minutes=5),
            open=Decimal("60000.00"),
            high=Decimal("63200.00"),  # High - Low = 3200 -> rolling ATR > 3.0x
            low=Decimal("60000.00"),
            close=Decimal("63100.00"),
            volume=Decimal("100.0"),
            quote_volume=Decimal("6000000.0"),
            trades=500,
            taker_buy_base=Decimal("50.0"),
            taker_buy_quote=Decimal("3000000.0"),
            is_closed=True,
        )

        asyncio.run(engine.handle_bar(bar))
        asyncio.run(engine.monitor.process_single_queue_item())

        assert str(engine.account.current_state) == "HALTED"
        assert engine.account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("0.0")

    def test_drawdown_limit_triggers_halt(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        """Portfolio drawdown >= 8% (drawdown_halt) triggers DRAWDOWN_HALT_LIMIT."""
        account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
        # Starting 100 USDT, peak 100 USDT, cash reduced to 91.50 USDT (8.5% drawdown >= 8% halt)
        account.cash = Decimal("91.50")
        account.peak_portfolio_equity = Decimal("100.00")

        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        eval_res = account.evaluate_circuit_breaker(
            symbol="BTCUSDT",
            current_atr=Decimal("100.0"),
            baseline_atr=Decimal("100.0"),
            current_slippage_bps=Decimal("1.0"),
            current_equity=account.cash,
            peak_equity=account.peak_portfolio_equity,
            bar_ts=now,
        )

        assert eval_res.recommended_state == "HALTED"
        assert account.current_state == "HALTED"
        assert "DRAWDOWN_HALT_LIMIT" in eval_res.reason_codes
        assert eval_res.inhibit_new_entries is True
