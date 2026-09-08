"""Unit tests verifying open trade immutability during strategy admission and lifecycle events."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader
from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot
from autonomous_futures.paper.ledger import PaperRestartRecoveryError
from autonomous_futures.paper.live_engine import (
    LivePaperEngine,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    QualificationGateResult,
    QualificationMetric,
    _qualification_content_hash,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _build_candidate(
    candidate_id: str,
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    symbol: str = "BTCUSDT",
    features: tuple[FeatureRef, ...] | None = None,
    entry: EntryExit | None = None,
    exit_rules: EntryExit | None = None,
) -> CreatorCandidateArtifact:
    feats = features or (FeatureRef(name="rsi", lookback=14, shift=1),)
    ent = entry or EntryExit(long="rsi <= 30", short="rsi >= 70")
    ex = exit_rules or EntryExit(long="rsi >= 50", short="rsi <= 50")
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=feats,
        entry=ent,
        exit=ex,
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_mult),
            take_profit_atr_multiplier=Decimal(tp_mult),
            trailing_atr_multiplier=Decimal("1.0"),
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


def _build_qualification(
    candidate: CreatorCandidateArtifact,
    decision: str = "qualified",
) -> CreatorCandidateQualificationArtifact:
    gates = (
        QualificationGateResult(
            gate_id="oos_profit_factor_min",
            passed=decision == "qualified",
            observed=Decimal("1.5"),
            threshold=Decimal("1.0"),
            comparator="gte",
            reason_code="oos_profit_factor_acceptable"
            if decision == "qualified"
            else "oos_profit_factor_below_threshold",
        ),
    )
    metrics = (QualificationMetric(metric_id="profit_factor", value=Decimal("1.5")),)
    provisional = CreatorCandidateQualificationArtifact.model_validate(
        {
            "qualification_version": 1,
            "candidate_id": candidate.candidate_id,
            "candidate_artifact_hash": candidate.artifact_hash,
            "bundle_hash": candidate.bundle_hash,
            "dataset_registry_hash": candidate.dataset_registry_hash,
            "evaluator_run_id": "run-test-eval-001",
            "evaluator_version": "1.0.0",
            "decision": decision,
            "metrics": metrics,
            "gates": gates,
            "windows_evaluated": 5,
            "qualification_policy_id": "policy-test-001",
            "oos_aggregation_hash": "d" * 64,
            "source": "walk_forward_oos",
            "evaluated_at": NOW,
            "promotion_state": "unpromoted",
            "execution_authority": False,
            "qualification_hash": "0" * 64,
        }
    )
    return provisional.model_copy(
        update={"qualification_hash": _qualification_content_hash(provisional)}
    )


def _setup_engine(tmp_path: Path, candidate: CreatorCandidateArtifact) -> LivePaperEngine:
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": candidate},
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
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


def test_open_trade_immutability_full_lifecycle(tmp_path: Path) -> None:
    """Verify that candidate B admission while candidate A is in an active trade:

    1. Sets engine.candidates[symbol] to candidate B.
    2. Retains trade.candidate as candidate A.
    3. Persists position state containing candidate A's strategy JSON and artifact hash.
    4. Restores without PaperRestartRecoveryError on restart.
    5. Evaluates candle marks and tick stops with candidate A.
    6. Records candidate A in closed trade ledger upon trade close.
    """
    cand_a = _build_candidate("cand-btc-alpha", stop_mult="1.5", tp_mult="3.0")
    cand_b = _build_candidate("cand-btc-beta", stop_mult="2.0", tp_mult="4.0")
    qual_b = _build_qualification(cand_b, decision="qualified")

    assert cand_a.artifact_hash != cand_b.artifact_hash

    # Step 1: Initialize engine with Candidate A and execute an open trade
    engine = _setup_engine(tmp_path, cand_a)
    opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened is not None
    assert opened.status == "opened"
    assert "BTCUSDT" in engine.active_trades

    active_trade = engine.active_trades["BTCUSDT"]
    assert active_trade.candidate_id == cand_a.candidate_id
    assert active_trade.candidate_artifact_hash == cand_a.artifact_hash
    assert active_trade.candidate is not None
    assert active_trade.candidate.candidate_id == cand_a.candidate_id

    # Step 2: Admit Candidate B with require_flat=False
    decision = engine.admit_candidate(cand_b, qual_b, require_flat=False)
    assert decision.decision == "admitted"
    assert decision.active_trade_retained is True

    # Invariant 1: Engine candidates map is updated to candidate B
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id
    assert engine.candidates["BTCUSDT"].artifact_hash == cand_b.artifact_hash

    # Invariant 2: Active trade still retains candidate A
    assert active_trade.candidate is not None
    assert active_trade.candidate.candidate_id == cand_a.candidate_id
    assert active_trade.candidate.artifact_hash == cand_a.artifact_hash

    # Step 3: Evaluate a candle mark after Candidate B admission
    # This invokes _mark_active_position which persists position state
    mark_time = NOW + timedelta(minutes=5)
    engine._mark_active_position(active_trade, Decimal("50020"), mark_time)

    # Invariant 3: Persisted position state contains Candidate A strategy and hash, NOT Candidate B
    persisted_states = engine.sqlite_ledger.load_position_states()
    assert len(persisted_states) == 1
    state = persisted_states[0]
    assert state["candidate_id"] == cand_a.candidate_id
    assert state["candidate_artifact_hash"] == cand_a.artifact_hash

    persisted_strat = json.loads(str(state["strategy_json"]))
    assert persisted_strat == cand_a.model_dump(mode="json")
    assert persisted_strat != cand_b.model_dump(mode="json")

    # Step 4: Evaluate a non-exit tick stop
    # This invokes _evaluate_tick_stops which also persists position state
    tick_time = mark_time + timedelta(seconds=1)
    non_exit_ticker = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("50050"),
        best_bid_qty=Decimal("1"),
        best_ask_price=Decimal("50051"),
        best_ask_qty=Decimal("1"),
        transaction_time=tick_time,
        event_time=tick_time,
    )
    engine._evaluate_tick_stops("BTCUSDT", non_exit_ticker)

    # Re-verify persisted state still belongs to Candidate A
    persisted_states_after_tick = engine.sqlite_ledger.load_position_states()
    assert len(persisted_states_after_tick) == 1
    state_after_tick = persisted_states_after_tick[0]
    assert state_after_tick["candidate_id"] == cand_a.candidate_id
    assert state_after_tick["candidate_artifact_hash"] == cand_a.artifact_hash
    assert json.loads(str(state_after_tick["strategy_json"])) == cand_a.model_dump(mode="json")

    # Step 5: Engine restart recovery without PaperRestartRecoveryError
    # The restarted engine receives candidate A so require_recoverable_position_states can validate
    restarted_engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": cand_a},
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    assert "BTCUSDT" in restarted_engine.active_trades
    recovered_trade = restarted_engine.active_trades["BTCUSDT"]
    assert recovered_trade.candidate_id == cand_a.candidate_id
    assert recovered_trade.candidate_artifact_hash == cand_a.artifact_hash

    # Step 6: Close the trade and verify Candidate A is recorded in closed trade ledger
    close_time = tick_time + timedelta(minutes=1)
    engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
        symbol="BTCUSDT",
        best_bid_price=Decimal("51000"),
        best_bid_qty=Decimal("1"),
        best_ask_price=Decimal("51001"),
        best_ask_qty=Decimal("1"),
        transaction_time=close_time,
        event_time=close_time,
    )
    engine.execute_close("BTCUSDT", exit_reason="take_profit_hit", event_time=close_time)

    # Invariant: Active trades map is now empty
    assert "BTCUSDT" not in engine.active_trades

    # Invariant: Closed trade in paper ledger belongs to Candidate A
    reader = ReadOnlyLedgerReader(tmp_path)
    closed_trades = reader.read_closed_trades()
    assert len(closed_trades) == 1
    closed = closed_trades[0]
    assert closed.candidate_id == cand_a.candidate_id
    assert closed.candidate_artifact_hash == cand_a.artifact_hash
    assert closed.symbol == "BTCUSDT"


def test_open_trade_admission_deferral_with_require_flat(tmp_path: Path) -> None:
    """Verify that candidate B admission is deferred when require_flat=True and trade is active."""
    cand_a = _build_candidate("cand-btc-alpha")
    cand_b = _build_candidate("cand-btc-beta")
    qual_b = _build_qualification(cand_b, decision="qualified")

    engine = _setup_engine(tmp_path, cand_a)
    opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened is not None and opened.status == "opened"

    # Admission with require_flat=True must defer
    decision = engine.admit_candidate(cand_b, qual_b, require_flat=True)
    assert decision.decision == "deferred_active_position"
    assert "active_position_open" in decision.reason_codes
    assert decision.active_trade_retained is False

    # Engine candidates remains Candidate A
    assert engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id
    assert engine.active_trades["BTCUSDT"].candidate.candidate_id == cand_a.candidate_id


def test_candle_close_exit_with_disjoint_features(tmp_path: Path) -> None:
    """Verify Candidate A strategy exit evaluates its own features even if Candidate B
    has disjoint features.
    """
    cand_a = _build_candidate(
        "cand-a-rsi-exit",
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 95"),
        exit_rules=EntryExit(long="rsi >= 50", short="rsi <= 50"),
    )
    cand_b = _build_candidate(
        "cand-b-adx-only",
        features=(FeatureRef(name="adx", lookback=14, shift=1),),
        entry=EntryExit(long="adx < 20", short="adx >= 25"),
        exit_rules=EntryExit(long="adx <= 20", short="adx >= 30"),
    )
    qual_b = _build_qualification(cand_b)

    engine = _setup_engine(tmp_path, cand_a)
    opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened is not None and opened.status == "opened"

    # Admit Candidate B
    decision = engine.admit_candidate(cand_b, qual_b, require_flat=False)
    assert decision.decision == "admitted"
    assert engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id

    # Feed rising bars so RSI crosses 50
    base_time = NOW
    price = Decimal("50000")
    for i in range(25):
        price += Decimal("50")
        bar_ts = base_time + timedelta(minutes=5 * (i + 1))
        bar = CanonicalBar(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=bar_ts - timedelta(minutes=5),
            close_time=bar_ts,
            open=price - Decimal("20"),
            high=price + Decimal("20"),
            low=price - Decimal("30"),
            close=price,
            volume=Decimal("10"),
            quote_volume=Decimal("500000"),
            trades=100,
            taker_buy_base=Decimal("5"),
            taker_buy_quote=Decimal("250000"),
            is_closed=True,
        )
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=price - Decimal("1"),
            best_bid_qty=Decimal("2"),
            best_ask_price=price,
            best_ask_qty=Decimal("2"),
            transaction_time=bar_ts,
            event_time=bar_ts,
        )
        engine._process_closed_bar(bar)
        if "BTCUSDT" not in engine.active_trades:
            break

    assert "BTCUSDT" not in engine.active_trades
    reader = ReadOnlyLedgerReader(tmp_path)
    closed = reader.read_closed_trades()
    assert len(closed) == 1
    assert closed[0].candidate_id == cand_a.candidate_id
    assert closed[0].exit_reason == "strategy_exit"


def test_candidate_b_opposite_signal_does_not_trigger_reversal(tmp_path: Path) -> None:
    """Verify Candidate B entry signal in opposite direction does not trigger reversal exit
    on Candidate A trade.
    """
    cand_a = _build_candidate(
        "cand-a-never-short",
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 10", short="rsi >= 150"),  # never short
        exit_rules=EntryExit(long="rsi >= 150", short="rsi <= 5"),  # never strategy exit
    )
    cand_b = _build_candidate(
        "cand-b-triggers-short",
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 10", short="rsi >= 60"),  # triggers short at rsi >= 60
        exit_rules=EntryExit(long="rsi >= 150", short="rsi <= 20"),
    )
    qual_b = _build_qualification(cand_b)

    engine = _setup_engine(tmp_path, cand_a)
    opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened is not None and opened.status == "opened"

    engine.admit_candidate(cand_b, qual_b, require_flat=False)

    # 19 flat bars, then price jump so RSI reaches high levels (>= 60)
    price = Decimal("50000")
    for i in range(19):
        bar_ts = NOW + timedelta(minutes=5 * (i + 1))
        bar = CanonicalBar(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=bar_ts - timedelta(minutes=5),
            close_time=bar_ts,
            open=price,
            high=price + Decimal("1"),
            low=price - Decimal("1"),
            close=price,
            volume=Decimal("10"),
            quote_volume=Decimal("500000"),
            trades=100,
            taker_buy_base=Decimal("5"),
            taker_buy_quote=Decimal("250000"),
            is_closed=True,
        )
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=price - Decimal("1"),
            best_bid_qty=Decimal("2"),
            best_ask_price=price,
            best_ask_qty=Decimal("2"),
            transaction_time=bar_ts,
            event_time=bar_ts,
        )
        engine._process_closed_bar(bar)

    for i in range(19, 22):
        price += Decimal("100")
        bar_ts = NOW + timedelta(minutes=5 * (i + 1))
        bar = CanonicalBar(
            symbol="BTCUSDT",
            interval="5m",
            timestamp=bar_ts - timedelta(minutes=5),
            close_time=bar_ts,
            open=price - Decimal("5"),
            high=price + Decimal("5"),
            low=price - Decimal("5"),
            close=price,
            volume=Decimal("10"),
            quote_volume=Decimal("500000"),
            trades=100,
            taker_buy_base=Decimal("5"),
            taker_buy_quote=Decimal("250000"),
            is_closed=True,
        )
        engine.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=price - Decimal("1"),
            best_bid_qty=Decimal("2"),
            best_ask_price=price,
            best_ask_qty=Decimal("2"),
            transaction_time=bar_ts,
            event_time=bar_ts,
        )
        engine._process_closed_bar(bar)

    # Trade must remain open and unaffected by Candidate B's short signal
    assert "BTCUSDT" in engine.active_trades
    active_trade = engine.active_trades["BTCUSDT"]
    assert active_trade.candidate_id == cand_a.candidate_id
    reader = ReadOnlyLedgerReader(tmp_path)
    assert len(reader.read_closed_trades()) == 0


def test_restart_recovery_with_only_admitted_candidate_b(tmp_path: Path) -> None:
    """Verify engine restart recovery when only Candidate B is configured in engine.candidates."""
    cand_a = _build_candidate("cand-a-recovery")
    cand_b = _build_candidate("cand-b-recovery")
    qual_b = _build_qualification(cand_b)

    engine = _setup_engine(tmp_path, cand_a)
    opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened is not None and opened.status == "opened"

    engine.admit_candidate(cand_b, qual_b, require_flat=False)

    # Trigger lifecycle mark so position state is persisted
    engine._mark_active_position(
        engine.active_trades["BTCUSDT"], Decimal("50010"), NOW + timedelta(seconds=10)
    )

    # Restart engine passing ONLY Candidate B for BTCUSDT
    restarted = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": cand_b},
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )

    assert "BTCUSDT" in restarted.active_trades
    recovered_trade = restarted.active_trades["BTCUSDT"]
    assert recovered_trade.candidate_id == cand_a.candidate_id
    assert recovered_trade.candidate_artifact_hash == cand_a.artifact_hash
    assert recovered_trade.candidate is not None
    assert recovered_trade.candidate.candidate_id == cand_a.candidate_id
    assert recovered_trade.candidate.artifact_hash == cand_a.artifact_hash

    # Engine candidate for new entries remains Candidate B
    assert restarted.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id


def test_restart_recovery_rejects_tampered_strategy_json_with_modified_payload(
    tmp_path: Path,
) -> None:
    """Verify that engine restart rejects position state where strategy_json has been
    tampered with, even if candidate_artifact_hash and the inner artifact_hash string match.

    Protects against self-certifying deserialization attacks by requiring cryptographic
    recomputation of the canonical content hash (_artifact_content_hash).
    """
    cand_a = _build_candidate("cand-a-tamper", stop_mult="1.5", tp_mult="3.0")
    cand_b = _build_candidate("cand-b-admitted", stop_mult="2.0", tp_mult="4.0")
    qual_b = _build_qualification(cand_b)

    # Step 1: Initialize engine with Candidate A and execute an open trade
    engine = _setup_engine(tmp_path, cand_a)
    opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened is not None and opened.status == "opened"
    assert "BTCUSDT" in engine.active_trades

    # Step 2: Admit Candidate B with require_flat=False (active trade is retained)
    decision = engine.admit_candidate(cand_b, qual_b, require_flat=False)
    assert decision.decision == "admitted"
    assert decision.active_trade_retained is True

    # Step 3: Trigger mark so position state is durably persisted to SQLite
    mark_time = NOW + timedelta(seconds=10)
    engine._mark_active_position(engine.active_trades["BTCUSDT"], Decimal("50010"), mark_time)

    # Step 4: Verify uncorrupted state in SQLite before tampering
    db_path = tmp_path / "paper-ledger.sqlite3"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT trade_id, state_version, state_json FROM paper_position_state "
            "WHERE trade_id = ?",
            (opened.trade_id,),
        ).fetchone()
        assert row is not None
        trade_id, state_version, raw_state_json = row
        state_payload = json.loads(raw_state_json)

        original_strat_json = state_payload["strategy_json"]
        strat_dict = json.loads(original_strat_json)
        original_artifact_hash = strat_dict["artifact_hash"]
        assert original_artifact_hash == cand_a.artifact_hash
        assert state_payload["candidate_artifact_hash"] == cand_a.artifact_hash

        # Step 5: Tamper with strategy payload: mutate stop_atr_multiplier to 99.0
        # CRITICAL: Leave strat_dict["artifact_hash"] and
        # state_payload["candidate_artifact_hash"] intact!
        strat_dict["strategy"]["risk"]["stop_atr_multiplier"] = "99.0"
        tampered_strat_json = json.dumps(strat_dict, sort_keys=True, separators=(",", ":"))
        state_payload["strategy_json"] = tampered_strat_json

        # Write the tampered payload back to SQLite
        conn.execute(
            "UPDATE paper_position_state SET state_json = ? WHERE trade_id = ?",
            (json.dumps(state_payload, sort_keys=True, separators=(",", ":")), trade_id),
        )
        conn.commit()

    # Step 6: Restart engine passing ONLY Candidate B for BTCUSDT
    # Candidate A must be reconstructed from SQLite strategy_json.
    # Because the payload was tampered with, _artifact_content_hash will not match
    # candidate_artifact_hash, causing reconstruction to be rejected and raising
    # PaperRestartRecoveryError.
    with pytest.raises(PaperRestartRecoveryError) as exc_info:
        LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": cand_b},
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )

    # Verify that the error indicates strategy state failure
    assert "stale or incompatible paper strategy state" in str(exc_info.value) or "mismatch" in str(
        exc_info.value
    )


@pytest.mark.parametrize(
    ("mutation_field", "mutation_value"),
    [
        (("strategy", "risk", "stop_atr_multiplier"), "99.0"),
        (("strategy", "features", 0, "lookback"), 99),
        (("strategy", "exit", "long"), "rsi >= 99"),
    ],
)
def test_restart_recovery_rejects_arbitrary_strategy_json_mutations(
    tmp_path: Path,
    mutation_field: tuple[str | int, ...],
    mutation_value: Any,
) -> None:
    """Verify that tampering with any subfield of strategy_json (risk, features, rules)
    is caught by cryptographic content hash recomputation on engine restart.
    """
    cand_a = _build_candidate("cand-a-multi", stop_mult="1.5", tp_mult="3.0")
    cand_b = _build_candidate("cand-b-multi", stop_mult="2.0", tp_mult="4.0")
    qual_b = _build_qualification(cand_b)

    engine = _setup_engine(tmp_path, cand_a)
    opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
    assert opened is not None

    engine.admit_candidate(cand_b, qual_b, require_flat=False)
    engine._mark_active_position(
        engine.active_trades["BTCUSDT"], Decimal("50010"), NOW + timedelta(seconds=10)
    )

    db_path = tmp_path / "paper-ledger.sqlite3"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT trade_id, state_version, state_json FROM paper_position_state "
            "WHERE trade_id = ?",
            (opened.trade_id,),
        ).fetchone()
        assert row is not None
        trade_id, _, raw_state_json = row
        state_payload = json.loads(raw_state_json)
        strat_dict = json.loads(state_payload["strategy_json"])

        # Navigate and apply nested mutation
        curr: Any = strat_dict
        for p in mutation_field[:-1]:
            curr = curr[p]
        curr[mutation_field[-1]] = mutation_value

        state_payload["strategy_json"] = json.dumps(
            strat_dict, sort_keys=True, separators=(",", ":")
        )
        conn.execute(
            "UPDATE paper_position_state SET state_json = ? WHERE trade_id = ?",
            (json.dumps(state_payload, sort_keys=True, separators=(",", ":")), trade_id),
        )
        conn.commit()

    with pytest.raises(PaperRestartRecoveryError):
        LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": cand_b},
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )
