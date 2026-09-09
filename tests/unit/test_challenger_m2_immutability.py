"""Adversarial stress tests challenging Open-Trade Immutability Invariant under hot-reload.

Authored by Challenger 1 for Milestone 2 empirical verification.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader
from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot
from autonomous_futures.paper.candidate_registry import (
    CandidateRegistryHotReloader,
    publish_candidate_admission,
)
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def _build_candidate(
    candidate_id: str,
    stop_mult: str = "2.0",
    tp_mult: str = "10.0",
    trail_mult: str = "1.5",
    symbol: str = "BTCUSDT",
    entry_long: str = "rsi <= 30",
    entry_short: str = "rsi >= 70",
    exit_long: str = "rsi >= 75",
    exit_short: str = "rsi <= 25",
) -> CreatorCandidateArtifact:
    feats = (FeatureRef(name="rsi", lookback=14, shift=1),)
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,),
            timeframe="5m",
            regime_context_timeframe="15m",
        ),
        features=feats,
        entry=EntryExit(long=entry_long, short=entry_short),
        exit=EntryExit(long=exit_long, short=exit_short),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_mult),
            take_profit_atr_multiplier=Decimal(tp_mult),
            trailing_atr_multiplier=Decimal(trail_mult),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=NOW,
    )


def _setup_engine(tmp_path: Path, candidate: CreatorCandidateArtifact) -> LivePaperEngine:
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": candidate},
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    engine.monitor._rolling_atrs["BTCUSDT"] = Decimal("100.0")
    engine.monitor._baseline_atrs["BTCUSDT"] = Decimal("100.0")
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50000"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50001"),
        best_ask_qty=Decimal("2"),
        transaction_time=NOW,
        event_time=NOW,
    )
    return engine


def _populate_warmup_bars(
    engine: LivePaperEngine,
    count: int = 25,
    base_price: Decimal = Decimal("50000"),
    step: Decimal = Decimal("0"),
) -> None:
    engine._bar_history["BTCUSDT"].clear()
    current = base_price
    for i in range(count):
        current += step
        bar_time = NOW - timedelta(minutes=5 * (count - i))
        engine._bar_history["BTCUSDT"].append(
            {
                "timestamp": bar_time,
                "open": current,
                "high": current + Decimal("10"),
                "low": current - Decimal("10"),
                "close": current,
                "volume": Decimal("10.0"),
            }
        )


def test_empirical_atr_trailing_stop_multiplier_immutability_under_ticks(tmp_path: Path) -> None:
    """Empirically challenge: Active trade stops must evaluate strictly under Candidate A's

    multiplier (1.5) and not Candidate B's multiplier (4.0) after hot-reload.
    """
    manifest_path = tmp_path / "candidate_registry.json"

    # Candidate A: stop 2.0x ATR, trailing 1.5x ATR
    cand_a = _build_candidate(
        "cand-a-tight-trail",
        stop_mult="2.0",
        tp_mult="10.0",
        trail_mult="1.5",
    )
    # Candidate B: stop 5.0x ATR, trailing 4.0x ATR
    cand_b = _build_candidate(
        "cand-b-wide-trail",
        stop_mult="5.0",
        tp_mult="20.0",
        trail_mult="4.0",
    )
    cand_b_file = tmp_path / "cand-b.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    engine = _setup_engine(tmp_path, cand_a)

    # 1. Open Trade A under Candidate A
    res_a = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=NOW)
    assert res_a is not None and res_a.status == "opened"
    assert "BTCUSDT" in engine.active_trades
    trade_a = engine.active_trades["BTCUSDT"]

    assert trade_a.candidate_id == cand_a.candidate_id
    assert trade_a.trailing_atr_multiplier == Decimal("1.5")
    assert trade_a.current_atr == Decimal("100.0")
    initial_fill = res_a.fill_price
    assert initial_fill is not None
    # Initial stop: fill - 2.0 * 100
    expected_initial_stop = initial_fill - Decimal("200.0")
    assert trade_a.stop_price == expected_initial_stop
    assert trade_a.trailing_stop_price == expected_initial_stop
    assert trade_a.watermark == initial_fill

    # 2. Hot-reload Candidate B via CandidateRegistryHotReloader
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="b" * 64,
        admitted_at=NOW,
    )
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload() is True
    assert reloader.last_reload_status == "RELOADED"

    # Verify engine candidate points to Candidate B
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id

    # Verify Trade A still strictly points to Candidate A
    assert trade_a.candidate_id == cand_a.candidate_id
    assert trade_a.trailing_atr_multiplier == Decimal("1.5")

    # 3. Feed rising tick: price rises to 50500
    tick_time_1 = NOW + timedelta(seconds=10)
    ticker_up = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50500"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50501"),
        best_ask_qty=Decimal("2"),
        transaction_time=tick_time_1,
        event_time=tick_time_1,
    )
    engine._evaluate_tick_stops("BTCUSDT", ticker_up)

    # Watermark should be 50500
    assert trade_a.watermark == Decimal("50500")
    # Expected trailing stop: watermark (50500) - 1.5 * 100 = 50350.0
    # If Candidate B multiplier (4.0) leaked: 50500 - 4.0 * 100 = 50100.0
    assert trade_a.trailing_stop_price == Decimal("50350.0")
    assert trade_a.trailing_atr_multiplier == Decimal("1.5")

    # 4. Feed retracement tick to 50250 (bid=50250, ask=50251)
    # Under Candidate A (multiplier 1.5), 50250 <= 50350: MUST TRIGGER TRAILING STOP HIT!
    # Under Candidate B (multiplier 4.0), 50250 > 50100: WOULD NOT TRIGGER.
    tick_time_2 = NOW + timedelta(seconds=20)
    ticker_retrace = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50250"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50251"),
        best_ask_qty=Decimal("2"),
        transaction_time=tick_time_2,
        event_time=tick_time_2,
    )
    engine.latest_tickers["BTCUSDT"] = ticker_retrace
    engine._evaluate_tick_stops("BTCUSDT", ticker_retrace)

    # Assert Trade A was closed strictly by Candidate A's trailing stop!
    assert "BTCUSDT" not in engine.active_trades

    # 5. Verify exit PnL and ledger events reflect Candidate A attribution
    reader = ReadOnlyLedgerReader(tmp_path)
    closed_trades = reader.read_closed_trades()
    assert len(closed_trades) == 1
    closed_a = closed_trades[0]
    assert closed_a.candidate_id == cand_a.candidate_id
    assert closed_a.candidate_artifact_hash == cand_a.artifact_hash
    assert closed_a.exit_reason == "trailing_stop_hit"
    assert closed_a.exit_price == Decimal("50239.9500")
    assert closed_a.net_pnl is not None

    # 6. Open Trade B on next signal: verify Trade B adopts Candidate B with multiplier 4.0
    tick_time_3 = NOW + timedelta(seconds=30)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50250"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50251"),
        best_ask_qty=Decimal("2"),
        transaction_time=tick_time_3,
        event_time=tick_time_3,
    )
    res_b = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=tick_time_3
    )
    assert res_b is not None and res_b.status == "opened"
    assert "BTCUSDT" in engine.active_trades
    trade_b = engine.active_trades["BTCUSDT"]

    # Verify Trade B adopts Candidate B's parameters
    assert trade_b.candidate_id == cand_b.candidate_id
    assert trade_b.candidate_artifact_hash == cand_b.artifact_hash
    assert trade_b.trailing_atr_multiplier == Decimal("4.0")
    # Stop price uses 5.0x multiplier: fill - 5.0 * 100 = fill - 500
    fill_b = res_b.fill_price
    assert fill_b is not None
    assert trade_b.stop_price == fill_b - Decimal("500.0")

    # Feed tick moves up to 50800, then retraces to 50550:
    # Trade B watermark ratchets to 50800, trailing stop becomes 50800 - 4.0 * 100 = 50400.
    # At 50550, 50550 > 50400 so Trade B stays open (under 1.5 it stops at 50650).
    tick_time_4 = NOW + timedelta(seconds=40)
    ticker_b_up = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50800"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50801"),
        best_ask_qty=Decimal("2"),
        transaction_time=tick_time_4,
        event_time=tick_time_4,
    )
    engine.latest_tickers["BTCUSDT"] = ticker_b_up
    engine._evaluate_tick_stops("BTCUSDT", ticker_b_up)
    assert trade_b.watermark == Decimal("50800")
    assert trade_b.trailing_stop_price == Decimal("50400.0")

    tick_time_5 = NOW + timedelta(seconds=50)
    ticker_b_retrace = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50550"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50551"),
        best_ask_qty=Decimal("2"),
        transaction_time=tick_time_5,
        event_time=tick_time_5,
    )
    engine.latest_tickers["BTCUSDT"] = ticker_b_retrace
    engine._evaluate_tick_stops("BTCUSDT", ticker_b_retrace)
    # Trade B remains active!
    assert "BTCUSDT" in engine.active_trades


def test_empirical_opposing_signal_isolation_during_hot_reload(tmp_path: Path) -> None:
    """Empirically challenge: An opposing signal emitted by newly reloaded Candidate B

    while Trade A is active must NOT mutate Trade A or trigger reversal exit.
    """
    manifest_path = tmp_path / "candidate_registry.json"

    # Candidate A: Never short entry, never strategy exit (exit_long="rsi >= 999")
    cand_a = _build_candidate(
        "cand-a-long-only",
        entry_long="rsi <= 30",
        entry_short="rsi >= 999",  # impossible short entry
        exit_long="rsi >= 999",  # impossible strategy exit
        exit_short="rsi <= 5",
    )
    # Candidate B: Emits short entry aggressively whenever rsi >= 50
    cand_b = _build_candidate(
        "cand-b-aggressive-short",
        entry_long="rsi <= 20",
        entry_short="rsi >= 50",  # triggers short signal on RSI >= 50!
        exit_long="rsi >= 90",
        exit_short="rsi <= 10",
    )
    cand_b_file = tmp_path / "cand-b-short.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    engine = _setup_engine(tmp_path, cand_a)
    _populate_warmup_bars(engine, count=25, base_price=Decimal("50000"))

    # 1. Open Trade A (LONG)
    res_a = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=NOW)
    assert res_a is not None and res_a.status == "opened"
    assert "BTCUSDT" in engine.active_trades

    # 2. Hot-reload Candidate B via manifest
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="b" * 64,
        admitted_at=NOW,
    )
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload() is True
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id

    # 3. Simulate closed bar where Candidate B would evaluate to SHORT (signal = -1)
    real_evaluate = engine.signal_evaluator.evaluate

    def selective_evaluate(cand: Any, df: Any) -> Any:
        evaluated = real_evaluate(cand, df)
        if cand.candidate_id == cand_b.candidate_id:
            # Candidate B emits opposing SHORT signal (-1)
            evaluated.loc[evaluated.index[-1], "signal"] = -1
        else:
            # Candidate A emits neutral signal (0)
            evaluated.loc[evaluated.index[-1], "signal"] = 0
        return evaluated

    bar_time = NOW + timedelta(minutes=5)
    bar = CanonicalBar(
        symbol="BTCUSDT",
        interval="5m",
        timestamp=bar_time - timedelta(minutes=5),
        close_time=bar_time,
        open=Decimal("50050"),
        high=Decimal("50100"),
        low=Decimal("50040"),
        close=Decimal("50080"),
        volume=Decimal("10"),
        quote_volume=Decimal("500000"),
        trades=100,
        taker_buy_base=Decimal("5"),
        taker_buy_quote=Decimal("250000"),
        is_closed=True,
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50079"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50080"),
        best_ask_qty=Decimal("2"),
        transaction_time=bar_time,
        event_time=bar_time,
    )

    with patch(
        "autonomous_futures.research.feature_signals.CausalFeatureSignalEvaluator.evaluate",
        side_effect=selective_evaluate,
    ):
        engine._process_closed_bar(bar)

    # Invariant: Trade A MUST REMAIN OPEN!
    # Candidate B's opposing signal (-1) must NOT cause reversal or mutation.
    assert "BTCUSDT" in engine.active_trades
    active_trade = engine.active_trades["BTCUSDT"]
    assert active_trade.candidate_id == cand_a.candidate_id
    reader = ReadOnlyLedgerReader(tmp_path)
    assert len(reader.read_closed_trades()) == 0

    # 4. Now simulate closed bar where Candidate A's OWN reversal signal triggers (-1)
    def cand_a_reversal_evaluate(cand: Any, df: Any) -> Any:
        evaluated = real_evaluate(cand, df)
        if cand.candidate_id == cand_a.candidate_id:
            # Candidate A's own signal is now -1
            evaluated.loc[evaluated.index[-1], "signal"] = -1
        return evaluated

    bar_time_2 = bar_time + timedelta(minutes=5)
    bar_2 = CanonicalBar(
        symbol="BTCUSDT",
        interval="5m",
        timestamp=bar_time_2 - timedelta(minutes=5),
        close_time=bar_time_2,
        open=Decimal("50080"),
        high=Decimal("50150"),
        low=Decimal("50070"),
        close=Decimal("50120"),
        volume=Decimal("10"),
        quote_volume=Decimal("500000"),
        trades=100,
        taker_buy_base=Decimal("5"),
        taker_buy_quote=Decimal("250000"),
        is_closed=True,
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50119"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50120"),
        best_ask_qty=Decimal("2"),
        transaction_time=bar_time_2,
        event_time=bar_time_2,
    )

    with patch(
        "autonomous_futures.research.feature_signals.CausalFeatureSignalEvaluator.evaluate",
        side_effect=cand_a_reversal_evaluate,
    ):
        engine._process_closed_bar(bar_2)

    # Candidate A's own reversal rule triggers exit
    assert "BTCUSDT" not in engine.active_trades
    closed_trades = reader.read_closed_trades()
    assert len(closed_trades) == 1
    assert closed_trades[0].candidate_id == cand_a.candidate_id
    assert closed_trades[0].exit_reason == "signal_reversal_exit"


def test_empirical_exit_rule_divergence_isolation(tmp_path: Path) -> None:
    """Empirically challenge: If Candidate B's exit rule evaluates to True on a closed bar,

    Trade A must NOT exit unless Candidate A's own exit rule evaluates to True.
    """
    manifest_path = tmp_path / "candidate_registry.json"

    # Candidate A requires rsi >= 85 to exit
    cand_a = _build_candidate("cand-a-high-exit", exit_long="rsi >= 85")
    # Candidate B exits early at rsi >= 45
    cand_b = _build_candidate("cand-b-low-exit", exit_long="rsi >= 45")
    cand_b_file = tmp_path / "cand-b-low.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    engine = _setup_engine(tmp_path, cand_a)
    _populate_warmup_bars(engine, count=25, base_price=Decimal("50000"))

    # Open Trade A
    res_a = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=NOW)
    assert res_a is not None and res_a.status == "opened"

    # Hot reload Candidate B
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="b" * 64,
        admitted_at=NOW,
    )
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload() is True

    # 1. Feed bar where RSI is 60 (Candidate B rule rsi >= 45 would trigger,
    # but Candidate A rsi >= 85 does NOT)
    bar_time_1 = NOW + timedelta(minutes=5)
    bar_1 = CanonicalBar(
        symbol="BTCUSDT",
        interval="5m",
        timestamp=bar_time_1 - timedelta(minutes=5),
        close_time=bar_time_1,
        open=Decimal("50000"),
        high=Decimal("50050"),
        low=Decimal("49950"),
        close=Decimal("50020"),
        volume=Decimal("10"),
        quote_volume=Decimal("500000"),
        trades=100,
        taker_buy_base=Decimal("5"),
        taker_buy_quote=Decimal("250000"),
        is_closed=True,
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50019"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50020"),
        best_ask_qty=Decimal("2"),
        transaction_time=bar_time_1,
        event_time=bar_time_1,
    )

    # In evaluate_strategy_exit, pass row with rsi = 60
    with patch(
        "autonomous_futures.paper.live_engine.evaluate_strategy_exit",
        side_effect=lambda row, side, long_exit_expr, short_exit_expr: (
            "rsi >= 45" in long_exit_expr and False
        ),  # Candidate A has rsi >= 85, so returns False
    ):
        engine._process_closed_bar(bar_1)

    assert "BTCUSDT" in engine.active_trades

    # 2. Feed bar where Candidate A's rule (rsi >= 85) IS satisfied
    bar_time_2 = bar_time_1 + timedelta(minutes=5)
    bar_2 = CanonicalBar(
        symbol="BTCUSDT",
        interval="5m",
        timestamp=bar_time_2 - timedelta(minutes=5),
        close_time=bar_time_2,
        open=Decimal("50020"),
        high=Decimal("50200"),
        low=Decimal("50010"),
        close=Decimal("50180"),
        volume=Decimal("10"),
        quote_volume=Decimal("500000"),
        trades=100,
        taker_buy_base=Decimal("5"),
        taker_buy_quote=Decimal("250000"),
        is_closed=True,
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50179"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50180"),
        best_ask_qty=Decimal("2"),
        transaction_time=bar_time_2,
        event_time=bar_time_2,
    )

    with patch(
        "autonomous_futures.paper.live_engine.evaluate_strategy_exit",
        side_effect=lambda row, side, long_exit_expr, short_exit_expr: (
            "rsi >= 85" in long_exit_expr
        ),  # Returns True for Candidate A!
    ):
        engine._process_closed_bar(bar_2)

    assert "BTCUSDT" not in engine.active_trades
    reader = ReadOnlyLedgerReader(tmp_path)
    closed_trades = reader.read_closed_trades()
    assert len(closed_trades) == 1
    assert closed_trades[0].candidate_id == cand_a.candidate_id
    assert closed_trades[0].exit_reason == "strategy_exit"


def test_empirical_multiple_consecutive_hot_reloads_immutability(tmp_path: Path) -> None:
    """Empirically challenge: Chaining multiple consecutive hot-reloads (A -> B -> C)

    while Trade A is active must preserve Trade A bound to Candidate A until close,
    after which the subsequent trade adopts Candidate C.
    """
    manifest_path = tmp_path / "candidate_registry.json"

    cand_a = _build_candidate("cand-chain-a", trail_mult="1.5")
    cand_b = _build_candidate("cand-chain-b", trail_mult="3.0")
    cand_c = _build_candidate("cand-chain-c", trail_mult="0.5")

    cand_b_file = tmp_path / "cand-b.json"
    cand_c_file = tmp_path / "cand-c.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)
    write_creator_candidate_artifact(cand_c_file, cand_c)

    engine = _setup_engine(tmp_path, cand_a)
    reloader = CandidateRegistryHotReloader(manifest_path, engine)

    # 1. Open Trade A
    res_a = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=NOW)
    assert res_a is not None and res_a.status == "opened"
    trade_a = engine.active_trades["BTCUSDT"]
    assert trade_a.candidate_id == cand_a.candidate_id
    assert trade_a.trailing_atr_multiplier == Decimal("1.5")

    # 2. Hot reload Candidate B
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="b" * 64,
        admitted_at=NOW,
    )
    assert reloader.check_and_reload() is True
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id
    assert trade_a.candidate_id == cand_a.candidate_id
    assert trade_a.trailing_atr_multiplier == Decimal("1.5")

    # 3. Hot reload Candidate C
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_c.candidate_id,
        candidate_artifact_hash=cand_c.artifact_hash,
        artifact_path=cand_c_file,
        qualification_hash="c" * 64,
        admitted_at=NOW + timedelta(seconds=5),
    )
    assert reloader.check_and_reload() is True
    assert engine.candidates["BTCUSDT"].candidate_id == cand_c.candidate_id

    # Trade A STILL retains Candidate A! (Not B, not C)
    assert trade_a.candidate_id == cand_a.candidate_id
    assert trade_a.trailing_atr_multiplier == Decimal("1.5")

    # 4. Close Trade A
    close_time = NOW + timedelta(minutes=1)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50300"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50301"),
        best_ask_qty=Decimal("2"),
        transaction_time=close_time,
        event_time=close_time,
    )
    engine.execute_close("BTCUSDT", exit_reason="take_profit_hit", event_time=close_time)
    assert "BTCUSDT" not in engine.active_trades

    # Verify closed trade is Candidate A
    reader = ReadOnlyLedgerReader(tmp_path)
    closed = reader.read_closed_trades()
    assert len(closed) == 1
    assert closed[0].candidate_id == cand_a.candidate_id

    # 5. Open next trade: adopts Candidate C (the latest admitted)
    open_time_2 = close_time + timedelta(seconds=10)
    res_c = engine.execute_open(
        "BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=open_time_2
    )
    assert res_c is not None and res_c.status == "opened"
    trade_c = engine.active_trades["BTCUSDT"]
    assert trade_c.candidate_id == cand_c.candidate_id
    assert trade_c.candidate_artifact_hash == cand_c.artifact_hash
    assert trade_c.trailing_atr_multiplier == Decimal("0.5")


def test_empirical_sqlite_persistence_and_recovery_immutability(tmp_path: Path) -> None:
    """Empirically challenge: Persisted SQLite state during hot-reload must preserve Candidate A,

    and engine restart must restore Trade A with Candidate A rules intact.
    """
    manifest_path = tmp_path / "candidate_registry.json"

    cand_a = _build_candidate("cand-persist-a", trail_mult="1.5")
    cand_b = _build_candidate("cand-persist-b", trail_mult="4.0")
    cand_b_file = tmp_path / "cand-b.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    engine = _setup_engine(tmp_path, cand_a)
    res_a = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=NOW)
    assert res_a is not None and res_a.status == "opened"

    # Hot reload Candidate B
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="b" * 64,
        admitted_at=NOW,
    )
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload() is True

    # Persist position state after hot reload
    mark_time = NOW + timedelta(seconds=10)
    engine._mark_active_position(engine.active_trades["BTCUSDT"], Decimal("50010"), mark_time)

    # 1. Directly inspect SQLite database paper_position_state
    db_path = tmp_path / "paper-ledger.sqlite3"
    with sqlite3.connect(db_path) as conn:
        query = (
            "SELECT trade_id, state_version, state_json "
            "FROM paper_position_state WHERE trade_id = ?"
        )
        row = conn.execute(query, (res_a.trade_id,)).fetchone()
        assert row is not None
        trade_id, state_version, state_json_str = row
        assert trade_id == res_a.trade_id

        state_payload = json.loads(state_json_str)
        assert state_payload["candidate_id"] == cand_a.candidate_id
        assert state_payload["candidate_artifact_hash"] == cand_a.artifact_hash
        assert state_payload["trailing_atr_multiplier"] == "1.5"

        strat_in_db = json.loads(state_payload["strategy_json"])
        assert strat_in_db["candidate_id"] == cand_a.candidate_id
        assert strat_in_db["artifact_hash"] == cand_a.artifact_hash

    # 2. Restart engine configured with ONLY Candidate B in candidates map
    restarted_engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": cand_b},
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    assert "BTCUSDT" in restarted_engine.active_trades
    recovered = restarted_engine.active_trades["BTCUSDT"]
    assert recovered.candidate_id == cand_a.candidate_id
    assert recovered.candidate_artifact_hash == cand_a.artifact_hash
    assert recovered.trailing_atr_multiplier == Decimal("1.5")
    assert recovered.candidate is not None
    assert recovered.candidate.candidate_id == cand_a.candidate_id

    # Engine candidates remains Candidate B for future trades
    assert restarted_engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id


def test_empirical_resilient_handling_when_candidate_b_malformed_features(tmp_path: Path) -> None:
    """Empirically challenge: Even if newly admitted Candidate B crashes or fails feature

    evaluation during bar processing, Trade A's exit evaluation must not crash or be blocked.
    """
    manifest_path = tmp_path / "candidate_registry.json"

    cand_a = _build_candidate("cand-a-robust", exit_long="rsi >= 75")
    cand_b = _build_candidate("cand-b-failing", exit_long="rsi >= 40")
    cand_b_file = tmp_path / "cand-b-fail.json"
    write_creator_candidate_artifact(cand_b_file, cand_b)

    engine = _setup_engine(tmp_path, cand_a)
    _populate_warmup_bars(engine, count=25, base_price=Decimal("50000"))

    # Open Trade A
    res_a = engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.80"), event_time=NOW)
    assert res_a is not None and res_a.status == "opened"

    # Hot reload Candidate B
    publish_candidate_admission(
        manifest_path=manifest_path,
        symbol="BTCUSDT",
        candidate_id=cand_b.candidate_id,
        candidate_artifact_hash=cand_b.artifact_hash,
        artifact_path=cand_b_file,
        qualification_hash="b" * 64,
        admitted_at=NOW,
    )
    reloader = CandidateRegistryHotReloader(manifest_path, engine)
    assert reloader.check_and_reload() is True

    # Selective failure: Candidate B raises exception on evaluate, Candidate A works normally
    real_eval = engine.signal_evaluator.evaluate

    def flaky_eval(cand: Any, df: Any) -> Any:
        if cand.candidate_id == cand_b.candidate_id:
            raise RuntimeError("CRITICAL: Candidate B feature calculation crash!")
        return real_eval(cand, df)

    bar_time = NOW + timedelta(minutes=5)
    bar = CanonicalBar(
        symbol="BTCUSDT",
        interval="5m",
        timestamp=bar_time - timedelta(minutes=5),
        close_time=bar_time,
        open=Decimal("50000"),
        high=Decimal("50100"),
        low=Decimal("49900"),
        close=Decimal("50050"),
        volume=Decimal("10"),
        quote_volume=Decimal("500000"),
        trades=100,
        taker_buy_base=Decimal("5"),
        taker_buy_quote=Decimal("250000"),
        is_closed=True,
    )
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50049"),
        best_bid_qty=Decimal("2"),
        best_ask_price=Decimal("50050"),
        best_ask_qty=Decimal("2"),
        transaction_time=bar_time,
        event_time=bar_time,
    )

    with patch(
        "autonomous_futures.research.feature_signals.CausalFeatureSignalEvaluator.evaluate",
        side_effect=flaky_eval,
    ):
        # Bar arrives: must process cleanly without crashing
        engine._process_closed_bar(bar)

    # Trade A remains safely open and managed
    assert "BTCUSDT" in engine.active_trades
    assert engine.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id
