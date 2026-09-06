"""Phase 258 Milestone M1: Empirical Stress Testing for SQLite Persistence & Decimal Accounting.

Empirical Challenger 2 Test Suite:
1. High volume of sequential simulated paper trades across BTC, ETH, SOL, DOGE (120+ round trips).
2. High volume of concurrent simulated paper trades holding 4 simultaneous positions under 80% cap.
3. Long and short trades with randomized fills, fees, slippage, ATR stop exits, and take profits.
4. Exact Decimal reconciliation: final_cash == starting_capital + sum(net_pnl) to 1e-8 precision.
5. SQLite persistence integrity (PRAGMA integrity_check) and strict string formatting in:
   - paper-ledger.sqlite3
   - paper-lifecycle.sqlite3
   - paper-observations.sqlite3
6. Multi-threaded concurrent SQLite access and transaction isolation.
"""

from __future__ import annotations

import asyncio
import random
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.feed.models import TickerSnapshot
from autonomous_futures.paper.ledger import PaperLedger, PaperLedgerEntry
from autonomous_futures.paper.lifecycle import PaperLifecycleTelemetry, mark_paper_position
from autonomous_futures.paper.live_engine import (
    DEFAULT_SYMBOLS,
    LivePaperEngine,
)
from autonomous_futures.paper.observation import PaperObservation, observe_paper_ledger
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.paper.sqlite_lifecycle import SqlitePaperLifecycle
from autonomous_futures.paper.sqlite_observation import SqlitePaperObservations
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
)

DECIMAL_REGEX = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
ISO_UTC_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\+00:00|Z)?$")


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


class TestHighVolumeSequentialTradesReconciliation:
    """Stress tests sequential trades across BTC, ETH, SOL, DOGE with exact reconciliation."""

    def test_high_volume_sequential_trades_reconciliation(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        random.seed(42)
        symbols = DEFAULT_SYMBOLS  # ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")

        ledger_db = tmp_path / "paper-ledger.sqlite3"
        lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
        observations_db = tmp_path / "paper-observations.sqlite3"

        starting_capital = Decimal("100.00")
        engine = LivePaperEngine(
            symbols=symbols,
            starting_capital=starting_capital,
            ledger_db=ledger_db,
            lifecycle_db=lifecycle_db,
            observations_db=observations_db,
            candidates=candidates_all,
        )

        # Baseline prices and ATRs for all 4 assets
        base_configs: dict[str, dict[str, Decimal]] = {
            "BTCUSDT": {"price": Decimal("60000.00"), "atr": Decimal("400.00")},
            "ETHUSDT": {"price": Decimal("3000.00"), "atr": Decimal("25.00")},
            "SOLUSDT": {"price": Decimal("150.00"), "atr": Decimal("2.00")},
            "DOGEUSDT": {"price": Decimal("0.150000"), "atr": Decimal("0.002500")},
        }

        for sym, cfg in base_configs.items():
            engine.monitor._rolling_atrs[sym] = cfg["atr"]
            engine.monitor._baseline_atrs[sym] = cfg["atr"]

        total_trades_target = 120
        start_time = datetime(2026, 9, 6, 8, 0, 0, tzinfo=UTC)
        current_time = start_time

        exit_type_counts: dict[str, int] = {
            "take_profit_hit": 0,
            "stop_loss_hit": 0,
            "trailing_stop_hit": 0,
            "strategy_exit": 0,
        }

        for i in range(total_trades_target):
            sym = symbols[i % len(symbols)]
            cfg = base_configs[sym]
            base_price = cfg["price"]
            atr = cfg["atr"]

            # Randomize entry side and conviction
            side_signal = 1 if (i % 2 == 0) else -1
            conviction = Decimal(str(round(random.uniform(0.50, 0.95), 4)))

            # Varied spread within nominal limit (0.5 to 8.0 bps)
            spread_bps = Decimal(str(round(random.uniform(0.5, 8.0), 2)))
            half_spread = base_price * (spread_bps / Decimal("20000"))
            best_bid = base_price - half_spread
            best_ask = base_price + half_spread

            current_time += timedelta(seconds=15)
            engine.latest_tickers[sym] = TickerSnapshot(
                symbol=sym,
                best_bid_price=best_bid,
                best_bid_qty=Decimal("10.0"),
                best_ask_price=best_ask,
                best_ask_qty=Decimal("10.0"),
                transaction_time=current_time,
                event_time=current_time,
            )

            # Open trade
            open_res = engine.execute_open(
                symbol=sym,
                signal=side_signal,
                conviction=conviction,
                event_time=current_time,
            )
            assert open_res is not None and open_res.status == "opened"
            active_trade = engine.active_trades[sym]

            # Choose exit mechanism: TP (35%), SL (35%), Trailing (15%), Strategy (15%)
            exit_dice = i % 20
            current_time += timedelta(seconds=10)

            if exit_dice < 7:
                # 1. Take profit exit
                exit_type = "take_profit_hit"
                if active_trade.side == "LONG":
                    # Best bid reaches or exceeds target price
                    assert active_trade.target_price is not None
                    tp_price = active_trade.target_price + Decimal("1.0") * (
                        Decimal("0.0001") if sym == "DOGEUSDT" else Decimal("1.0")
                    )
                    tp_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=tp_price,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=tp_price + half_spread,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                else:
                    assert active_trade.target_price is not None
                    tp_price = active_trade.target_price - Decimal("1.0") * (
                        Decimal("0.0001") if sym == "DOGEUSDT" else Decimal("1.0")
                    )
                    tp_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=tp_price - half_spread,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=tp_price,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                asyncio.run(engine.handle_ticker(tp_ticker))

            elif exit_dice < 14:
                # 2. Stop loss exit
                exit_type = "stop_loss_hit"
                if active_trade.side == "LONG":
                    # Best bid drops below stop price
                    sl_price = active_trade.stop_price - Decimal("1.0") * (
                        Decimal("0.0001") if sym == "DOGEUSDT" else Decimal("1.0")
                    )
                    sl_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=sl_price,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=sl_price + half_spread,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                else:
                    # Best ask rises above stop price
                    sl_price = active_trade.stop_price + Decimal("1.0") * (
                        Decimal("0.0001") if sym == "DOGEUSDT" else Decimal("1.0")
                    )
                    sl_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=sl_price - half_spread,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=sl_price,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                asyncio.run(engine.handle_ticker(sl_ticker))

            elif exit_dice < 17:
                # 3. Trailing stop ratchet followed by trigger
                exit_type = "trailing_stop_hit"
                if active_trade.side == "LONG":
                    # First favorable move
                    favorable_price = active_trade.open_entry.fill_price + atr * Decimal("1.2")
                    fav_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=favorable_price,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=favorable_price + half_spread,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                    asyncio.run(engine.handle_ticker(fav_ticker))
                    assert active_trade.trailing_stop_price is not None
                    ratcheted_stop = active_trade.trailing_stop_price

                    # Reverse and hit ratcheted trailing stop
                    current_time += timedelta(seconds=5)
                    hit_price = ratcheted_stop - Decimal("1.0") * (
                        Decimal("0.0001") if sym == "DOGEUSDT" else Decimal("1.0")
                    )
                    hit_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=hit_price,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=hit_price + half_spread,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                    asyncio.run(engine.handle_ticker(hit_ticker))
                else:
                    # Short favorable move
                    favorable_price = active_trade.open_entry.fill_price - atr * Decimal("1.2")
                    fav_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=favorable_price - half_spread,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=favorable_price,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                    asyncio.run(engine.handle_ticker(fav_ticker))
                    assert active_trade.trailing_stop_price is not None
                    ratcheted_stop = active_trade.trailing_stop_price

                    # Reverse and hit ratcheted trailing stop
                    current_time += timedelta(seconds=5)
                    hit_price = ratcheted_stop + Decimal("1.0") * (
                        Decimal("0.0001") if sym == "DOGEUSDT" else Decimal("1.0")
                    )
                    hit_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=hit_price - half_spread,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=hit_price,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                    asyncio.run(engine.handle_ticker(hit_ticker))

            else:
                # 4. Explicit strategy close
                exit_type = "strategy_exit"
                close_res = engine.execute_close(
                    sym, exit_reason="strategy_exit", event_time=current_time
                )
                assert close_res is not None and close_res.status == "closed"

            exit_type_counts[exit_type] += 1
            assert sym not in engine.active_trades

            # Intermittent reconciliation check after every trade
            rec = engine.reconcile_balances()
            assert rec["zero_balance_drift"] is True
            assert Decimal(rec["drift"]) == Decimal("0")

        # Post-run asserts
        assert engine.total_closed_trades == total_trades_target
        assert len(engine.active_trades) == 0

        # Verify diverse exit coverage
        assert exit_type_counts["take_profit_hit"] > 30
        assert exit_type_counts["stop_loss_hit"] > 30
        assert exit_type_counts["trailing_stop_hit"] > 10
        assert exit_type_counts["strategy_exit"] > 10

        # Exact Decimal Reconciliation Assertion: final_cash == starting_capital + sum(net_pnl)
        ledger = engine.sqlite_ledger.load()
        closed_entries = [e for e in ledger.entries if e.event == "close"]
        assert len(closed_entries) == total_trades_target

        sum_net_pnl = sum(
            (e.net_pnl for e in closed_entries if e.net_pnl is not None), Decimal("0")
        )
        final_cash = engine.account.cash
        expected_cash = starting_capital + sum_net_pnl

        # Down to 0.00000001 precision
        abs_diff = abs(final_cash - expected_cash)
        assert abs_diff < Decimal("0.00000001"), (
            f"Drift exceeded 1e-8: diff={abs_diff}, final={final_cash}, exp={expected_cash}"
        )
        # Exact Decimal equality
        assert final_cash == expected_cash

        # Verify SQLite row count
        with sqlite3.connect(ledger_db) as conn:
            row_count = conn.execute("SELECT COUNT(*) FROM paper_ledger_events").fetchone()[0]
            assert row_count == total_trades_target * 2  # Each trade has 1 open and 1 close


class TestConcurrentPortfolioTradesReconciliation:
    """Stress tests concurrent trades across BTC, ETH, SOL, DOGE under 80% ceiling."""

    def test_concurrent_portfolio_trades_reconciliation(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        random.seed(1337)
        symbols = DEFAULT_SYMBOLS

        ledger_db = tmp_path / "paper-ledger.sqlite3"
        lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
        observations_db = tmp_path / "paper-observations.sqlite3"

        starting_capital = Decimal("100.00")
        engine = LivePaperEngine(
            symbols=symbols,
            starting_capital=starting_capital,
            ledger_db=ledger_db,
            lifecycle_db=lifecycle_db,
            observations_db=observations_db,
            candidates=candidates_all,
        )

        base_configs: dict[str, dict[str, Decimal]] = {
            "BTCUSDT": {"price": Decimal("62000.00"), "atr": Decimal("450.00")},
            "ETHUSDT": {"price": Decimal("3100.00"), "atr": Decimal("28.00")},
            "SOLUSDT": {"price": Decimal("145.00"), "atr": Decimal("2.10")},
            "DOGEUSDT": {"price": Decimal("0.145000"), "atr": Decimal("0.002200")},
        }

        for sym, cfg in base_configs.items():
            engine.monitor._rolling_atrs[sym] = cfg["atr"]
            engine.monitor._baseline_atrs[sym] = cfg["atr"]

        current_time = datetime(2026, 9, 6, 9, 0, 0, tzinfo=UTC)

        # Helper to set nominal ticker
        def set_nominal_ticker(sym: str, t: datetime) -> None:
            p = base_configs[sym]["price"]
            engine.latest_tickers[sym] = TickerSnapshot(
                symbol=sym,
                best_bid_price=p * Decimal("0.9999"),
                best_bid_qty=Decimal("10.0"),
                best_ask_price=p * Decimal("1.0001"),
                best_ask_qty=Decimal("10.0"),
                transaction_time=t,
                event_time=t,
            )

        # Run 20 cycles of 4 concurrent positions
        cycles = 20
        total_opened = 0

        for cycle in range(cycles):
            # 1. Open positions on all symbols currently not active
            for sym in symbols:
                if sym not in engine.active_trades:
                    current_time += timedelta(seconds=2)
                    set_nominal_ticker(sym, current_time)
                    signal = 1 if ((cycle + symbols.index(sym)) % 2 == 0) else -1
                    res = engine.execute_open(
                        sym, signal=signal, conviction=Decimal("0.50"), event_time=current_time
                    )
                    assert res is not None and res.status == "opened"
                    total_opened += 1

            # Assert all 4 assets are actively held concurrently
            assert len(engine.active_trades) == 4
            # Sizing uses max(current_equity, starting_capital) to prevent fee lockouts
            ref_equity = max(engine.current_equity(), starting_capital)
            assert engine.account.total_locked_margin() <= ref_equity * Decimal("0.800001")
            assert engine.account.margin_utilization(engine.current_equity()) <= Decimal("0.805")
            assert engine.account.unencumbered_reserve_buffer(engine.current_equity()) >= Decimal(
                "0.194"
            )

            # Assert 5th allocation is strictly rejected
            fifth_alloc = engine.account.allocate_order(
                symbol="BTCUSDT",
                confidence=Decimal("1.0"),
                mark_price=Decimal("60000"),
                current_equity=engine.current_equity(),
            )
            assert fifth_alloc is None

            # 2. Trigger exit on 2 selected symbols via tick stops or strategy close
            exit_syms = [symbols[cycle % 4], symbols[(cycle + 1) % 4]]
            for sym in exit_syms:
                current_time += timedelta(seconds=5)
                active = engine.active_trades[sym]
                if cycle % 2 == 0:
                    # Take profit trigger
                    step = Decimal("0.0001") if sym == "DOGEUSDT" else Decimal("1.0")
                    tp_target = (
                        active.target_price
                        if active.target_price is not None
                        else (
                            active.open_entry.fill_price * Decimal("1.02")
                            if active.side == "LONG"
                            else active.open_entry.fill_price * Decimal("0.98")
                        )
                    )
                    tp_price = tp_target + step if active.side == "LONG" else tp_target - step
                    tp_ticker = TickerSnapshot(
                        symbol=sym,
                        best_bid_price=tp_price,
                        best_bid_qty=Decimal("10.0"),
                        best_ask_price=tp_price,
                        best_ask_qty=Decimal("10.0"),
                        transaction_time=current_time,
                        event_time=current_time,
                    )
                    asyncio.run(engine.handle_ticker(tp_ticker))
                else:
                    # Strategy exit
                    engine.execute_close(sym, exit_reason="cycle_exit", event_time=current_time)

                assert sym not in engine.active_trades

            # Intermediate reconciliation: open entry fees accounted for
            rec = engine.reconcile_balances()
            assert rec["zero_balance_drift"] is True
            assert Decimal(rec["drift"]) == Decimal("0")

        # Close all remaining active positions
        for sym in list(engine.active_trades.keys()):
            current_time += timedelta(seconds=5)
            set_nominal_ticker(sym, current_time)
            engine.execute_close(sym, exit_reason="final_flush", event_time=current_time)

        assert len(engine.active_trades) == 0
        assert engine.total_closed_trades == total_opened

        # Final reconciliation: final_cash == starting_capital + sum(net_pnl)
        ledger = engine.sqlite_ledger.load()
        closed_entries = [e for e in ledger.entries if e.event == "close"]
        sum_net_pnl = sum(
            (e.net_pnl for e in closed_entries if e.net_pnl is not None), Decimal("0")
        )

        final_cash = engine.account.cash
        expected_cash = starting_capital + sum_net_pnl

        # Exact Decimal equality and precision check
        diff = abs(final_cash - expected_cash)
        assert diff < Decimal("0.00000001")
        assert final_cash == expected_cash


class TestRandomizedFillsFeesSlippageAndExits:
    """Property-based randomized stress testing comparing runtime against mathematical oracle."""

    def test_randomized_math_oracle(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        random.seed(999)
        symbols = DEFAULT_SYMBOLS

        ledger_db = tmp_path / "paper-ledger.sqlite3"
        lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
        observations_db = tmp_path / "paper-observations.sqlite3"

        engine = LivePaperEngine(
            symbols=symbols,
            starting_capital=Decimal("500.00"),  # Adequate buffer for varied iterations
            fee_rate=Decimal("0.0004"),
            slippage_bps=Decimal("2.0"),
            ledger_db=ledger_db,
            lifecycle_db=lifecycle_db,
            observations_db=observations_db,
            candidates=candidates_all,
        )

        current_time = datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)

        for iteration in range(50):
            sym = symbols[iteration % len(symbols)]
            side_signal = 1 if (random.random() > 0.5) else -1
            conviction = Decimal(str(round(random.uniform(0.50, 1.00), 4)))

            # Randomized price with high fractional precision
            if sym == "BTCUSDT":
                raw_price = Decimal(str(round(random.uniform(55000.123456, 68000.987654), 6)))
            elif sym == "ETHUSDT":
                raw_price = Decimal(str(round(random.uniform(2800.123456, 3800.987654), 6)))
            elif sym == "SOLUSDT":
                raw_price = Decimal(str(round(random.uniform(120.123456, 180.987654), 6)))
            else:
                raw_price = Decimal(str(round(random.uniform(0.100123, 0.250987), 6)))

            current_time += timedelta(seconds=10)
            engine.latest_tickers[sym] = TickerSnapshot(
                symbol=sym,
                best_bid_price=raw_price,
                best_bid_qty=Decimal("10.0"),
                best_ask_price=raw_price,
                best_ask_qty=Decimal("10.0"),
                transaction_time=current_time,
                event_time=current_time,
            )

            # Execute open
            open_res = engine.execute_open(
                symbol=sym,
                signal=side_signal,
                conviction=conviction,
                event_time=current_time,
            )
            assert open_res is not None and open_res.status == "opened"

            open_entry = engine.active_trades[sym].open_entry
            fill_price = open_res.fill_price
            assert fill_price is not None
            quantity = open_entry.quantity

            # Mathematical Oracle Check on Open Fill:
            expected_open_fill = (
                raw_price * (Decimal("1") + Decimal("0.0002"))
                if side_signal == 1
                else raw_price * (Decimal("1") - Decimal("0.0002"))
            )
            assert fill_price == expected_open_fill

            expected_entry_fee = fill_price * quantity * Decimal("0.0004")
            assert open_res.entry_fee == expected_entry_fee

            # Randomized exit price
            pnl_pct = Decimal(str(round(random.uniform(-0.03, 0.05), 6)))
            exit_mark = raw_price * (Decimal("1") + pnl_pct)

            current_time += timedelta(seconds=15)
            engine.latest_tickers[sym] = TickerSnapshot(
                symbol=sym,
                best_bid_price=exit_mark,
                best_bid_qty=Decimal("10.0"),
                best_ask_price=exit_mark,
                best_ask_qty=Decimal("10.0"),
                transaction_time=current_time,
                event_time=current_time,
            )

            close_res = engine.execute_close(
                symbol=sym,
                exit_reason="oracle_eval",
                event_time=current_time,
            )
            assert close_res is not None and close_res.status == "closed"

            # Mathematical Oracle Check on Close Fill & Net PnL:
            expected_exit_fill = (
                exit_mark * (Decimal("1") - Decimal("0.0002"))
                if side_signal == 1
                else exit_mark * (Decimal("1") + Decimal("0.0002"))
            )
            assert close_res.fill_price == expected_exit_fill

            expected_gross_pnl = (
                (expected_exit_fill - expected_open_fill) * quantity
                if side_signal == 1
                else (expected_open_fill - expected_exit_fill) * quantity
            )
            assert close_res.gross_pnl == expected_gross_pnl

            expected_exit_fee = expected_exit_fill * quantity * Decimal("0.0004")
            assert close_res.exit_fee == expected_exit_fee

            expected_net_pnl = expected_gross_pnl - expected_entry_fee - expected_exit_fee
            assert close_res.net_pnl == expected_net_pnl

            # Invariant: net_pnl must equal gross_pnl - entry_fee - exit_fee
            assert (
                close_res.net_pnl == close_res.gross_pnl - close_res.entry_fee - close_res.exit_fee
            )


class TestSqlitePersistenceIntegrityAndStringFormatting:
    """Verifies PRAGMA integrity_check, schema types, strict string formatting, and rehydration."""

    def test_sqlite_persistence_and_formatting(
        self, tmp_path: Path, candidates_all: dict[str, CreatorCandidateArtifact]
    ) -> None:
        ledger_db = tmp_path / "paper-ledger.sqlite3"
        lifecycle_db = tmp_path / "paper-lifecycle.sqlite3"
        observations_db = tmp_path / "paper-observations.sqlite3"

        engine = LivePaperEngine(
            symbols=("BTCUSDT", "ETHUSDT"),
            starting_capital=Decimal("100.00"),
            ledger_db=ledger_db,
            lifecycle_db=lifecycle_db,
            observations_db=observations_db,
            candidates=candidates_all,
        )

        now = datetime(2026, 9, 6, 11, 0, 0, tzinfo=UTC)
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=now,
            event_time=now,
        )

        # Open and close trade
        engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.75"), event_time=now)
        trade = engine.active_trades["BTCUSDT"]

        # Record multiple lifecycle marks with whole-second precision
        engine._mark_active_position(trade, Decimal("60500.00"), now + timedelta(seconds=10))
        engine._mark_active_position(trade, Decimal("61000.00"), now + timedelta(seconds=20))

        # Record observation
        engine._record_observation(
            "BTCUSDT", candidates_all["BTCUSDT"], now + timedelta(seconds=20)
        )

        # Close trade
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("61000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("61001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=now + timedelta(seconds=30),
            event_time=now + timedelta(seconds=30),
        )
        engine.execute_close(
            "BTCUSDT", exit_reason="profit", event_time=now + timedelta(seconds=30)
        )

        # 1. PRAGMA integrity_check on all 3 databases
        for db_path in (ledger_db, lifecycle_db, observations_db):
            with sqlite3.connect(db_path) as conn:
                res = conn.execute("PRAGMA integrity_check").fetchall()
                assert res == [("ok",)], f"Integrity check failed for {db_path}: {res}"

        # 2. String Formatting Verification on paper_ledger_events
        with sqlite3.connect(ledger_db) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT sequence, event, trade_id, candidate_id, candidate_artifact_hash,
                       symbol, side, quantity, fill_price, occurred_at, approval_id,
                       entry_fee, exit_fee, slippage_cost, gross_pnl, net_pnl
                FROM paper_ledger_events
                ORDER BY sequence
                """
            ).fetchall()

            assert len(rows) == 2  # 1 open, 1 close
            for row in rows:
                seq, ev, t_id, c_id, c_hash, sym, side, qty, fill, occ, app_id = row[:11]
                entry_f, exit_f, slip, gross, net = row[11:]

                assert isinstance(seq, int) and seq >= 1
                assert ev in ("open", "close")
                assert side in ("LONG", "SHORT")
                assert sym == "BTCUSDT"

                # Check ISO-8601 UTC with zero microseconds
                assert ISO_UTC_REGEX.match(occ), f"occurred_at '{occ}' invalid ISO UTC format"
                dt = datetime.fromisoformat(occ)
                assert dt.microsecond == 0

                # Strict Decimal string regex checks (no scientific notation, no float drift)
                for name, val in [
                    ("quantity", qty),
                    ("fill_price", fill),
                ]:
                    assert DECIMAL_REGEX.match(val), (
                        f"Field {name} '{val}' not valid Decimal string"
                    )
                    assert "e" not in val.lower()
                    assert str(Decimal(val)) == val

                if ev == "open":
                    assert entry_f is not None and DECIMAL_REGEX.match(entry_f)
                    assert slip is not None and DECIMAL_REGEX.match(slip)
                    assert exit_f is None
                    assert gross is None
                    assert net is None
                else:  # close
                    for name, val in [
                        ("entry_fee", entry_f),
                        ("exit_fee", exit_f),
                        ("slippage_cost", slip),
                        ("gross_pnl", gross),
                        ("net_pnl", net),
                    ]:
                        assert val is not None
                        assert DECIMAL_REGEX.match(val), (
                            f"Field {name} '{val}' not valid Decimal string"
                        )
                        assert "e" not in val.lower()

        # 3. String Formatting & Schema Verification on paper_lifecycle_marks
        with sqlite3.connect(lifecycle_db) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT sequence, candidate_id, candidate_artifact_hash, trade_id, marked_at, payload
                FROM paper_lifecycle_marks
                ORDER BY sequence
                """
            ).fetchall()

            assert len(rows) >= 3  # Open mark + 2 intermediate marks + close mark
            for row in rows:
                seq, c_id, c_hash, t_id, marked_at, payload = row
                assert isinstance(seq, int)
                assert ISO_UTC_REGEX.match(marked_at)
                dt = datetime.fromisoformat(marked_at)
                assert dt.microsecond == 0

                # Payload must deserialize into PaperLifecycleTelemetry without error
                telemetry = PaperLifecycleTelemetry.model_validate_json(payload)
                assert telemetry.candidate_id == c_id
                assert telemetry.trade_id == t_id
                assert telemetry.marked_at == dt
                assert telemetry.mark_price > Decimal("0")

        # 4. String Formatting & Schema Verification on paper_observations
        with sqlite3.connect(observations_db) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT sequence, candidate_id, candidate_artifact_hash, observed_at, payload
                FROM paper_observations
                ORDER BY sequence
                """
            ).fetchall()

            assert len(rows) >= 1
            for row in rows:
                seq, c_id, c_hash, obs_at, payload = row
                assert isinstance(seq, int)
                assert ISO_UTC_REGEX.match(obs_at)
                dt = datetime.fromisoformat(obs_at)
                assert dt.microsecond == 0

                # Payload must deserialize into PaperObservation without error
                obs = PaperObservation.model_validate_json(payload)
                assert obs.candidate_id == c_id
                assert obs.observed_at == dt
                assert obs.equity > Decimal("0")
                assert obs.realized_pnl is not None
                assert obs.accounting_complete is True

        # 5. Round-trip rehydration
        rehydrated_ledger = SqlitePaperLedger(ledger_db).load()
        assert len(rehydrated_ledger.entries) == 2
        assert len(rehydrated_ledger.open_positions()) == 0


class TestConcurrentSqliteAccessAndTransactions:
    """Stress tests concurrent SQLite writes to verify locking and transaction isolation."""

    def test_multithreaded_concurrent_lifecycle_and_observation_writes(
        self, tmp_path: Path
    ) -> None:
        lifecycle_db = tmp_path / "concurrent-lifecycle.sqlite3"
        observations_db = tmp_path / "concurrent-obs.sqlite3"

        lifecycle_store = SqlitePaperLifecycle(lifecycle_db)
        obs_store = SqlitePaperObservations(observations_db)

        # Baseline template entry
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        open_entry = PaperLedgerEntry(
            event="open",
            trade_id="trade-concurrent-001",
            candidate_id="cand-concurrent-test",
            candidate_artifact_hash="a" * 64,
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("0.001"),
            fill_price=Decimal("60000.00"),
            occurred_at=now,
            approval_id="appr-001",
            entry_fee=Decimal("0.024"),
            slippage_cost=Decimal("0.012"),
        )

        num_threads = 8
        writes_per_thread = 20

        def write_worker(thread_id: int) -> None:
            for w in range(writes_per_thread):
                ts = now + timedelta(seconds=thread_id * 1000 + w)
                # 1. Lifecycle write
                mark = mark_paper_position(
                    open_entry,
                    mark_price=Decimal("60000.00") + Decimal(str(thread_id * 10 + w)),
                    marked_at=ts,
                    previous_peak_pnl=Decimal("0"),
                )
                lifecycle_store.append(mark)

                # 2. Observation write
                obs = observe_paper_ledger(
                    PaperLedger((open_entry,)),
                    candidate_id="cand-concurrent-test",
                    candidate_artifact_hash="a" * 64,
                    starting_equity=Decimal("100.00"),
                    previous_peak_equity=Decimal("100.00"),
                    mark_prices={"BTCUSDT": Decimal("60000.00")},
                    observed_at=ts,
                )
                obs_store.append(obs)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(write_worker, tid) for tid in range(num_threads)]
            for fut in futures:
                fut.result()

        total_expected = num_threads * writes_per_thread

        # Verify integrity and row count
        with sqlite3.connect(lifecycle_db) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            count = conn.execute("SELECT COUNT(*) FROM paper_lifecycle_marks").fetchone()[0]
            assert count == total_expected

        with sqlite3.connect(observations_db) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            count = conn.execute("SELECT COUNT(*) FROM paper_observations").fetchone()[0]
            assert count == total_expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
