"""Empirical Adversarial Stress Harness: Multi-Candidate Transitions & Restart Recovery.

Adversarial Challenge Scenarios for Milestone 2 Iteration 2:
ADV_01: Multi-candidate transition chain (A -> B -> C -> D) while trade A is active.
ADV_02: Double restart recovery (Open A -> Admit B -> Restart 1 -> Tick Mark -> Restart 2).
ADV_03: Short trade reversal insulation (Cand A SHORT vs Cand B LONG entry signal).
ADV_04: Post-restart closed bar strategy exit with disjoint features (ADX on Cand B, RSI on Cand A).
ADV_05: Multi-symbol concurrent transition & recovery (BTCUSDT + ETHUSDT).
ADV_06: Tamper detection on corrupted strategy_json in SQLite.
ADV_07: Tamper detection on strategy_json artifact_hash mismatch.
ADV_08: Clean post-close restart (no phantom trades).
ADV_09: Subsequent trade after A close uses newly admitted Candidate B.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader  # noqa: E402
from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot  # noqa: E402
from autonomous_futures.paper.ledger import PaperRestartRecoveryError  # noqa: E402
from autonomous_futures.paper.live_engine import LivePaperEngine  # noqa: E402
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    CreatorCandidateQualificationArtifact,
    QualificationGateResult,
    QualificationMetric,
    _qualification_content_hash,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def build_candidate(
    candidate_id: str,
    features: tuple[FeatureRef, ...] | None = None,
    entry: EntryExit | None = None,
    exit_rules: EntryExit | None = None,
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trail_mult: str = "1.0",
    symbol: str = "BTCUSDT",
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
            trailing_atr_multiplier=Decimal(trail_mult),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=NOW,
    )


def build_qualification(
    candidate: CreatorCandidateArtifact, decision: str = "qualified"
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


def setup_engine(
    tmp_path: Path,
    candidates: dict[str, CreatorCandidateArtifact],
    symbols: tuple[str, ...] = ("BTCUSDT",),
) -> LivePaperEngine:
    engine = LivePaperEngine(
        symbols=symbols,
        candidates=candidates,
        ledger_db=tmp_path / "paper-ledger.sqlite3",
        lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
        observations_db=tmp_path / "paper-observations.sqlite3",
    )
    for sym in symbols:
        engine.latest_tickers[sym] = TickerSnapshot(
            symbol=sym,
            best_bid_price=Decimal("50000"),
            best_bid_qty=Decimal("2"),
            best_ask_price=Decimal("50001"),
            best_ask_qty=Decimal("2"),
            transaction_time=NOW,
            event_time=NOW,
        )
    return engine


@dataclass
class AdversarialResult:
    scenario_id: str
    description: str
    passed: bool
    details: str


def run_all_adversarial_tests() -> list[AdversarialResult]:
    results: list[AdversarialResult] = []

    # -------------------------------------------------------------------------
    # ADV_01: Multi-candidate chain (A -> B -> C -> D)
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-01")
        cand_b = build_candidate("cand-b-01")
        cand_c = build_candidate("cand-c-01")
        cand_d = build_candidate("cand-d-01")

        engine = setup_engine(tmp_path, {"BTCUSDT": cand_a})
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)

        d_b = engine.admit_candidate(cand_b, build_qualification(cand_b), require_flat=False)
        d_c = engine.admit_candidate(cand_c, build_qualification(cand_c), require_flat=False)
        d_d = engine.admit_candidate(cand_d, build_qualification(cand_d), require_flat=False)

        trade = engine.active_trades.get("BTCUSDT")
        states = engine.sqlite_ledger.load_position_states()
        persisted_strat = json.loads(str(states[0]["strategy_json"]))

        adv_01_passed = (
            d_b.decision == "admitted"
            and d_c.decision == "admitted"
            and d_d.decision == "admitted"
            and engine.candidates["BTCUSDT"].candidate_id == cand_d.candidate_id
            and trade is not None
            and trade.candidate_id == cand_a.candidate_id
            and trade.candidate_artifact_hash == cand_a.artifact_hash
            and trade.candidate.candidate_id == cand_a.candidate_id
            and len(states) == 1
            and states[0]["candidate_id"] == cand_a.candidate_id
            and persisted_strat["candidate_id"] == cand_a.candidate_id
        )
        results.append(
            AdversarialResult(
                scenario_id="ADV_01_MULTI_CANDIDATE_CHAIN_A_B_C_D",
                description="Chain admissions A -> B -> C -> D keeps active trade bound to A",
                passed=adv_01_passed,
                details=(
                    f"engine.candidate={engine.candidates['BTCUSDT'].candidate_id}, "
                    f"trade.candidate={trade.candidate_id if trade else 'None'}, "
                    f"persisted_candidate={states[0]['candidate_id'] if states else 'None'}"
                ),
            )
        )

    # -------------------------------------------------------------------------
    # ADV_02: Double Restart Recovery
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-02")
        cand_b = build_candidate("cand-b-02")

        engine = setup_engine(tmp_path, {"BTCUSDT": cand_a})
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, build_qualification(cand_b), require_flat=False)

        # First restart with only Candidate B configured
        engine_r1 = LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": cand_b},
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )
        t_r1 = engine_r1.active_trades.get("BTCUSDT")

        # In engine_r1, tick update moves watermark and triggers re-persistence
        tick_time = NOW + timedelta(minutes=1)
        ticker_up = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("50200"),
            best_bid_qty=Decimal("2"),
            best_ask_price=Decimal("50201"),
            best_ask_qty=Decimal("2"),
            transaction_time=tick_time,
            event_time=tick_time,
        )
        engine_r1.latest_tickers["BTCUSDT"] = ticker_up
        engine_r1._evaluate_tick_stops("BTCUSDT", ticker_up)

        # Second restart with only Candidate B configured
        engine_r2 = LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": cand_b},
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )
        t_r2 = engine_r2.active_trades.get("BTCUSDT")

        adv_02_passed = (
            t_r1 is not None
            and t_r1.candidate_id == cand_a.candidate_id
            and t_r2 is not None
            and t_r2.candidate_id == cand_a.candidate_id
            and t_r2.candidate.candidate_id == cand_a.candidate_id
            and t_r2.watermark == Decimal("50200")
        )
        results.append(
            AdversarialResult(
                scenario_id="ADV_02_DOUBLE_RESTART_RECOVERY",
                description=(
                    "Trade survives multiple sequential engine restarts across state updates"
                ),
                passed=adv_02_passed,
                details=(
                    f"R1 trade cand={t_r1.candidate_id if t_r1 else None}, "
                    f"R2 trade cand={t_r2.candidate_id if t_r2 else None}, "
                    f"R2 watermark={t_r2.watermark if t_r2 else None}"
                ),
            )
        )

    # -------------------------------------------------------------------------
    # ADV_03: Short Trade Reversal Insulation
    # Cand A is SHORT. Cand B fires LONG signal. Cand A trade must stay open.
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate(
            "cand-a-short",
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi >= 150", short="rsi <= 10"),  # never enter long
            exit_rules=EntryExit(
                long="rsi <= 10", short="rsi >= 150"
            ),  # never strategy exit on high rsi
        )
        cand_b = build_candidate(
            "cand-b-long-trigger",
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi >= 60", short="rsi <= 10"),  # fires long at rsi >= 60
            exit_rules=EntryExit(long="rsi <= 10", short="rsi >= 150"),
        )
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, {"BTCUSDT": cand_a})
        # Open SHORT trade
        engine.execute_open("BTCUSDT", -1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, qual_b, require_flat=False)

        # Feed 19 flat bars, then price jump on bar 20/21 so RSI reaches 100.0
        # Cand B triggers LONG signal (rsi >= 60). Cand A entry long is rsi >= 150 (not triggered).
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

        reader = ReadOnlyLedgerReader(tmp_path)
        closed_trades = reader.read_closed_trades()
        adv_03_passed = (
            "BTCUSDT" in engine.active_trades
            and engine.active_trades["BTCUSDT"].side == "SHORT"
            and len(closed_trades) == 0
        )
        results.append(
            AdversarialResult(
                scenario_id="ADV_03_SHORT_TRADE_REVERSAL_INSULATION",
                description="Active SHORT trade insulated from Candidate B LONG entry signal",
                passed=adv_03_passed,
                details=(
                    f"active_trade_present={'BTCUSDT' in engine.active_trades}, "
                    f"closed_trades_count={len(closed_trades)}"
                ),
            )
        )

    # -------------------------------------------------------------------------
    # ADV_04: Post-Restart Closed Bar Strategy Exit with Disjoint Features
    # Open Cand A (RSI exit) -> Admit Cand B (ADX only) -> Restart engine with only Cand B ->
    # Feed closed bars driving RSI up -> Restored Cand A trade must exit via strategy_exit!
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate(
            "cand-a-rsi-exit",
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 30", short="rsi >= 95"),
            exit_rules=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        )
        cand_b = build_candidate(
            "cand-b-adx-features",
            features=(FeatureRef(name="adx", lookback=14, shift=1),),
            entry=EntryExit(long="adx < 20", short="adx >= 25"),
            exit_rules=EntryExit(long="adx <= 20", short="adx >= 30"),
        )
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, {"BTCUSDT": cand_a})
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, qual_b, require_flat=False)

        # Restart engine with ONLY Cand B
        restarted = LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": cand_b},
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )
        assert "BTCUSDT" in restarted.active_trades

        # Feed 25 bars with rising price -> RSI reaches 100
        price = Decimal("50000")
        for i in range(25):
            price += Decimal("50")
            bar_ts = NOW + timedelta(minutes=5 * (i + 1))
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
            restarted.latest_tickers["BTCUSDT"] = TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=price - Decimal("1"),
                best_bid_qty=Decimal("2"),
                best_ask_price=price,
                best_ask_qty=Decimal("2"),
                transaction_time=bar_ts,
                event_time=bar_ts,
            )
            restarted._process_closed_bar(bar)
            if "BTCUSDT" not in restarted.active_trades:
                break

        reader = ReadOnlyLedgerReader(tmp_path)
        closed = reader.read_closed_trades()
        adv_04_passed = (
            "BTCUSDT" not in restarted.active_trades
            and len(closed) == 1
            and closed[0].candidate_id == cand_a.candidate_id
            and closed[0].exit_reason == "strategy_exit"
        )
        results.append(
            AdversarialResult(
                scenario_id="ADV_04_POST_RESTART_CLOSED_BAR_STRATEGY_EXIT",
                description=(
                    "Restored trade evaluates original candidate features and exits on closed bar"
                ),
                passed=adv_04_passed,
                details=(
                    f"trade_closed={'BTCUSDT' not in restarted.active_trades}, "
                    f"exit_reason={closed[0].exit_reason if closed else 'None'}, "
                    f"closed_cand_id={closed[0].candidate_id if closed else 'None'}"
                ),
            )
        )

    # -------------------------------------------------------------------------
    # ADV_05: Multi-Symbol Concurrent Transition & Recovery
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        symbols = ("BTCUSDT", "ETHUSDT")
        cand_a_btc = build_candidate("cand-a-btc", symbol="BTCUSDT", stop_mult="1.0", tp_mult="2.0")
        cand_a_eth = build_candidate("cand-a-eth", symbol="ETHUSDT", stop_mult="1.0", tp_mult="2.0")
        cand_b_btc = build_candidate("cand-b-btc", symbol="BTCUSDT", stop_mult="3.0", tp_mult="5.0")
        cand_b_eth = build_candidate("cand-b-eth", symbol="ETHUSDT", stop_mult="3.0", tp_mult="5.0")

        engine = setup_engine(
            tmp_path,
            {"BTCUSDT": cand_a_btc, "ETHUSDT": cand_a_eth},
            symbols=symbols,
        )
        engine.latest_tickers["ETHUSDT"] = TickerSnapshot(
            symbol="ETHUSDT",
            best_bid_price=Decimal("3000"),
            best_bid_qty=Decimal("10"),
            best_ask_price=Decimal("3001"),
            best_ask_qty=Decimal("10"),
            transaction_time=NOW,
            event_time=NOW,
        )

        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.execute_open("ETHUSDT", 1, Decimal("100"), NOW)

        engine.admit_candidate(cand_b_btc, build_qualification(cand_b_btc), require_flat=False)
        engine.admit_candidate(cand_b_eth, build_qualification(cand_b_eth), require_flat=False)

        # Restart with only B candidates
        restarted = LivePaperEngine(
            symbols=symbols,
            candidates={"BTCUSDT": cand_b_btc, "ETHUSDT": cand_b_eth},
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )
        restarted.latest_tickers["BTCUSDT"] = engine.latest_tickers["BTCUSDT"]
        restarted.latest_tickers["ETHUSDT"] = engine.latest_tickers["ETHUSDT"]

        # Close BTC with TP and ETH with SL
        t_btc = restarted.active_trades["BTCUSDT"]
        t_eth = restarted.active_trades["ETHUSDT"]
        assert t_btc.candidate_id == cand_a_btc.candidate_id
        assert t_eth.candidate_id == cand_a_eth.candidate_id

        restarted.execute_close("BTCUSDT", "take_profit_hit", NOW + timedelta(minutes=1))
        restarted.execute_close("ETHUSDT", "stop_loss_hit", NOW + timedelta(minutes=1))

        recon = restarted.reconcile_balances()
        reader = ReadOnlyLedgerReader(tmp_path)
        closed = reader.read_closed_trades()

        adv_05_passed = (
            len(restarted.active_trades) == 0
            and len(closed) == 2
            and recon["zero_balance_drift"] is True
            and Decimal(recon["drift"]) == Decimal("0")
            and {c.candidate_id for c in closed}
            == {cand_a_btc.candidate_id, cand_a_eth.candidate_id}
        )
        results.append(
            AdversarialResult(
                scenario_id="ADV_05_MULTI_SYMBOL_CONCURRENT_RECOVERY",
                description=(
                    "Concurrent multi-symbol recovery preserves both original candidate bindings "
                    "and zero balance drift"
                ),
                passed=adv_05_passed,
                details=(
                    f"closed_candidates={[c.candidate_id for c in closed]}, "
                    f"balance_drift={recon['drift']}"
                ),
            )
        )

    # -------------------------------------------------------------------------
    # ADV_06: Tamper Detection - Strategy JSON Corrupted in SQLite
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-tamper")
        cand_b = build_candidate("cand-b-tamper")

        engine = setup_engine(tmp_path, {"BTCUSDT": cand_a})
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, build_qualification(cand_b), require_flat=False)

        # Corrupt strategy_json inside state_json in SQLite ledger
        db_path = tmp_path / "paper-ledger.sqlite3"
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("SELECT state_json FROM paper_position_state")
            row = cur.fetchone()
            state_dict = json.loads(row[0])
            state_dict["strategy_json"] = "{invalid-json;"
            conn.execute(
                "UPDATE paper_position_state SET state_json = ?",
                (json.dumps(state_dict),),
            )
            conn.commit()

        # Restart should raise PaperRestartRecoveryError
        try:
            LivePaperEngine(
                symbols=("BTCUSDT",),
                candidates={"BTCUSDT": cand_b},
                ledger_db=db_path,
                lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
                observations_db=tmp_path / "paper-observations.sqlite3",
            )
            adv_06_passed = False
            details_06 = "FAIL: Engine started despite corrupt strategy_json!"
        except PaperRestartRecoveryError:
            adv_06_passed = True
            details_06 = "PASS: Engine correctly rejected restart with corrupt strategy_json."

        results.append(
            AdversarialResult(
                scenario_id="ADV_06_TAMPER_DETECTION_CORRUPT_JSON",
                description=(
                    "Engine refuses startup on corrupt strategy_json in SQLite position state"
                ),
                passed=adv_06_passed,
                details=details_06,
            )
        )

    # -------------------------------------------------------------------------
    # ADV_07: Tamper Detection - Strategy Hash Mismatch
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-tamper-hash")
        cand_b = build_candidate("cand-b-tamper-hash")

        engine = setup_engine(tmp_path, {"BTCUSDT": cand_a})
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, build_qualification(cand_b), require_flat=False)

        # Modify strategy_json slightly (e.g. alter seed or family) so hash mismatches
        db_path = tmp_path / "paper-ledger.sqlite3"
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("SELECT state_json FROM paper_position_state")
            row = cur.fetchone()
            state_dict = json.loads(row[0])
            strat_dict = json.loads(state_dict["strategy_json"])
            strat_dict["artifact_hash"] = "f" * 64  # deliberate hash mismatch
            state_dict["strategy_json"] = json.dumps(strat_dict)
            conn.execute(
                "UPDATE paper_position_state SET state_json = ?",
                (json.dumps(state_dict),),
            )
            conn.commit()

        # Restart should fail fast because reconstructed hash != candidate_artifact_hash
        try:
            LivePaperEngine(
                symbols=("BTCUSDT",),
                candidates={"BTCUSDT": cand_b},
                ledger_db=db_path,
                lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
                observations_db=tmp_path / "paper-observations.sqlite3",
            )
            adv_07_passed = False
            details_07 = "FAIL: Engine started with tampered strategy_json hash!"
        except PaperRestartRecoveryError:
            adv_07_passed = True
            details_07 = (
                "PASS: Engine correctly rejected tampered strategy_json with hash mismatch."
            )

        results.append(
            AdversarialResult(
                scenario_id="ADV_07_TAMPER_DETECTION_HASH_MISMATCH",
                description=(
                    "Engine rejects startup when persisted strategy_json hash mismatches "
                    "candidate_artifact_hash"
                ),
                passed=adv_07_passed,
                details=details_07,
            )
        )

    # -------------------------------------------------------------------------
    # ADV_08: Clean Post-Close Restart (No Phantom Trades)
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-post-close")
        cand_b = build_candidate("cand-b-post-close")

        engine = setup_engine(tmp_path, {"BTCUSDT": cand_a})
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, build_qualification(cand_b), require_flat=False)
        engine.execute_close("BTCUSDT", "take_profit_hit", NOW + timedelta(minutes=5))

        # Restart engine with Cand B
        restarted = LivePaperEngine(
            symbols=("BTCUSDT",),
            candidates={"BTCUSDT": cand_b},
            ledger_db=tmp_path / "paper-ledger.sqlite3",
            lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
            observations_db=tmp_path / "paper-observations.sqlite3",
        )
        recon = restarted.reconcile_balances()
        adv_08_passed = (
            len(restarted.active_trades) == 0
            and len(restarted.sqlite_ledger.load_position_states()) == 0
            and recon["zero_balance_drift"] is True
            and Decimal(recon["drift"]) == Decimal("0")
        )
        results.append(
            AdversarialResult(
                scenario_id="ADV_08_CLEAN_POST_CLOSE_RESTART",
                description=(
                    "Restart after trade close starts cleanly with 0 active trades and 0 position "
                    "states"
                ),
                passed=adv_08_passed,
                details=(
                    f"active_trades_count={len(restarted.active_trades)}, "
                    f"states_count={len(restarted.sqlite_ledger.load_position_states())}"
                ),
            )
        )

    # -------------------------------------------------------------------------
    # ADV_09: Subsequent Trade Uses Newly Admitted Candidate B
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-cycle")
        cand_b = build_candidate(
            "cand-b-cycle",
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
            exit_rules=EntryExit(long="rsi >= 50", short="rsi <= 50"),
            stop_mult="2.5",
        )

        engine = setup_engine(tmp_path, {"BTCUSDT": cand_a})
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, build_qualification(cand_b), require_flat=False)

        # Close trade A
        engine.execute_close("BTCUSDT", "take_profit_hit", NOW + timedelta(minutes=5))
        assert "BTCUSDT" not in engine.active_trades

        # Open trade 2 on BTCUSDT
        t2_time = NOW + timedelta(minutes=10)
        opened_b = engine.execute_open("BTCUSDT", 1, Decimal("100"), t2_time)

        trade_b = engine.active_trades.get("BTCUSDT")
        states = engine.sqlite_ledger.load_position_states()
        persisted_b = json.loads(str(states[0]["strategy_json"]))

        adv_09_passed = (
            opened_b is not None
            and trade_b is not None
            and trade_b.candidate_id == cand_b.candidate_id
            and trade_b.candidate_artifact_hash == cand_b.artifact_hash
            and trade_b.candidate.candidate_id == cand_b.candidate_id
            and persisted_b["candidate_id"] == cand_b.candidate_id
        )
        results.append(
            AdversarialResult(
                scenario_id="ADV_09_SUBSEQUENT_TRADE_USES_CANDIDATE_B",
                description=(
                    "Subsequent trade opened after Candidate A close correctly adopts Candidate B"
                ),
                passed=adv_09_passed,
                details=(
                    f"new_trade_candidate={trade_b.candidate_id if trade_b else 'None'}, "
                    f"persisted_candidate={persisted_b['candidate_id'] if persisted_b else 'None'}"
                ),
            )
        )

    return results


def main() -> int:
    print("=" * 80)
    print("ADVERSARIAL STRESS TEST SUITE: MULTI-CANDIDATE TRANSITIONS & RECOVERY")
    print("=" * 80)

    results = run_all_adversarial_tests()
    all_passed = True

    for r in results:
        status_str = "[PASS]" if r.passed else "[FAIL]"
        print(f"\n{status_str} {r.scenario_id}: {r.description}")
        print(f"       {r.details}")
        if not r.passed:
            all_passed = False

    print("\n" + "=" * 80)
    print("ADVERSARIAL SUITE SUMMARY:")
    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    print(f"Passed: {passed_count}/{total_count} ({passed_count / total_count * 100:.1f}%)")
    print(f"Verdict: {'APPROVE' if all_passed else 'REQUEST_CHANGES'}")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
