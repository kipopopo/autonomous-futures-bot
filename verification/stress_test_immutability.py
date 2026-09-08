"""Empirical Stress Test: Open Trade Immutability and Restart Recovery in LivePaperEngine.

Milestone 2 Empirical Challenge Suite:
1. Candidate B admission while Candidate A trade is active (require_flat=False).
2. Multiple candle closes, marks, and tick stops on active trade -> verify Candidate A rules.
3. Engine restart from paper_position_state -> verify clean recovery.
4. Trade close -> verify Candidate A ID and artifact hash in SQLite ledger.
5. require_flat=True -> verify candidate admission is deferred (deferred_active_position).
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# Ensure src/ is on sys.path
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


def setup_engine(tmp_path: Path, candidate: CreatorCandidateArtifact) -> LivePaperEngine:
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


@dataclass
class TestResult:
    test_id: str
    description: str
    passed: bool
    details: str


def run_all_stress_tests() -> list[TestResult]:
    results: list[TestResult] = []

    # -------------------------------------------------------------------------
    # TEST 1: Candidate B admission while Candidate A trade active (require_flat=False)
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-001")
        cand_b = build_candidate("cand-b-001")
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, cand_a)
        opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        assert opened and opened.status == "opened"

        decision = engine.admit_candidate(cand_b, qual_b, require_flat=False)
        active_t = engine.active_trades["BTCUSDT"]
        cand_prop = active_t.candidate.candidate_id if active_t.candidate else "None"
        t1_passed = (
            decision.decision == "admitted"
            and decision.active_trade_retained is True
            and engine.candidates["BTCUSDT"].candidate_id == cand_b.candidate_id
            and cand_prop == cand_a.candidate_id
            and active_t.candidate_id == cand_a.candidate_id
            and active_t.candidate_artifact_hash == cand_a.artifact_hash
        )
        results.append(
            TestResult(
                test_id="T1_ADMISSION_REQUIRE_FLAT_FALSE",
                description="Admit Candidate B while Candidate A trade active (require_flat=False)",
                passed=t1_passed,
                details=(
                    f"decision={decision.decision}, "
                    f"engine.candidate={engine.candidates['BTCUSDT'].candidate_id}, "
                    f"active_trade.candidate={cand_prop}"
                ),
            )
        )

    # -------------------------------------------------------------------------
    # TEST 2A: Candle close on active trade - Feature Blindness
    # Candidate A exits on rsi >= 50. Candidate B only defines adx.
    # Candidate A's exit rules must execute when RSI reaches 100.
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate(
            "cand-a-exit-rsi",
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 30", short="rsi >= 95"),
            exit_rules=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        )
        cand_b = build_candidate(
            "cand-b-adx-only",
            features=(FeatureRef(name="adx", lookback=14, shift=1),),
            entry=EntryExit(long="adx < 20", short="adx >= 25"),
            exit_rules=EntryExit(long="adx <= 20", short="adx >= 30"),
        )
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, cand_a)
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, qual_b, require_flat=False)

        # Feed 25 bars with rising price -> RSI reaches 100.0 (well above >= 50)
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

        # If Candidate A rules were executed, trade MUST have closed via strategy_exit
        t2a_passed = "BTCUSDT" not in engine.active_trades
        results.append(
            TestResult(
                test_id="T2A_CANDLE_CLOSE_FEATURE_BLINDNESS",
                description="Candle close evaluates Candidate A exit when Candidate B differs",
                passed=t2a_passed,
                details=(
                    "FAIL: Candidate A exit condition (rsi >= 50) was ignored because "
                    "Candidate B's features were evaluated in _process_closed_bar; "
                    "trade remained open after 25 bars!"
                    if not t2a_passed
                    else "PASS: Candidate A strategy exit triggered."
                ),
            )
        )

    # -------------------------------------------------------------------------
    # TEST 2B: Candle close on active trade - Cross-Candidate Signal Reversal
    # Candidate A LONG trade must NOT be closed by Candidate B's short signal.
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate(
            "cand-a-never-short",
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 10", short="rsi >= 150"),  # never short
            exit_rules=EntryExit(long="rsi >= 150", short="rsi <= 5"),  # never strategy exit
        )
        cand_b = build_candidate(
            "cand-b-triggers-short",
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 10", short="rsi >= 60"),  # triggers short at rsi >= 60
            exit_rules=EntryExit(long="rsi >= 150", short="rsi <= 20"),
        )
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, cand_a)
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, qual_b, require_flat=False)

        # Feed 19 flat bars, then price jump on bar 20/21 so RSI transitions to 100.0
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
        # Candidate A trade SHOULD REMAIN OPEN because Candidate A never enters short
        t2b_passed = len(closed_trades) == 0 and "BTCUSDT" in engine.active_trades
        exit_r = closed_trades[0].exit_reason if closed_trades else "none"
        results.append(
            TestResult(
                test_id="T2B_CANDLE_CLOSE_SIGNAL_REVERSAL_HIJACK",
                description="Active trade insulated from Candidate B entry reversal signal",
                passed=t2b_passed,
                details=(
                    f"FAIL: Candidate A trade closed with exit_reason='{exit_r}' "
                    "triggered by Candidate B's short signal!"
                    if not t2b_passed
                    else "PASS: Trade remained open, unaffected by Candidate B's entry signal."
                ),
            )
        )

    # -------------------------------------------------------------------------
    # TEST 2C: Tick stops & Marks execution
    # Verify Candidate A risk params, watermark, trailing stop, and position state persistence.
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-tick", stop_mult="2.0", tp_mult="4.0", trail_mult="1.5")
        cand_b = build_candidate("cand-b-tick", stop_mult="1.0", tp_mult="2.0", trail_mult="0.5")
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, cand_a)
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, qual_b, require_flat=False)

        active = engine.active_trades["BTCUSDT"]
        initial_trail_mult = active.trailing_atr_multiplier

        # Update tick with higher price to move watermark
        tick_time = NOW + timedelta(minutes=1)
        high_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("50100"),
            best_bid_qty=Decimal("2"),
            best_ask_price=Decimal("50101"),
            best_ask_qty=Decimal("2"),
            transaction_time=tick_time,
            event_time=tick_time,
        )
        engine._evaluate_tick_stops("BTCUSDT", high_ticker)

        # Mark lifecycle
        engine._mark_active_position(active, Decimal("50100"), tick_time)

        # Verify persisted position state in sqlite ledger matches Candidate A
        states = engine.sqlite_ledger.load_position_states()
        persisted_strat = json.loads(str(states[0]["strategy_json"]))

        t2c_passed = (
            initial_trail_mult == Decimal("1.5")
            and states[0]["candidate_id"] == cand_a.candidate_id
            and states[0]["candidate_artifact_hash"] == cand_a.artifact_hash
            and persisted_strat == cand_a.model_dump(mode="json")
            and persisted_strat != cand_b.model_dump(mode="json")
        )
        results.append(
            TestResult(
                test_id="T2C_TICK_STOPS_AND_MARKS_PERSISTENCE",
                description="Tick stops and marks persist Candidate A state and risk params",
                passed=t2c_passed,
                details=(
                    f"persisted_cand_id={states[0]['candidate_id']}, "
                    f"trail_mult={initial_trail_mult}"
                ),
            )
        )

    # -------------------------------------------------------------------------
    # TEST 3A: Engine restart recovery with Candidate A
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-rec")
        cand_b = build_candidate("cand-b-rec")
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, cand_a)
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, qual_b, require_flat=False)

        engine._mark_active_position(
            engine.active_trades["BTCUSDT"], Decimal("50010"), NOW + timedelta(seconds=10)
        )

        try:
            restarted_a = LivePaperEngine(
                symbols=("BTCUSDT",),
                candidates={"BTCUSDT": cand_a},
                ledger_db=tmp_path / "paper-ledger.sqlite3",
                lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
                observations_db=tmp_path / "paper-observations.sqlite3",
            )
            t3a_passed = (
                "BTCUSDT" in restarted_a.active_trades
                and restarted_a.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id
            )
            details_3a = "PASS: Clean recovery with Candidate A passed."
        except PaperRestartRecoveryError as exc:
            t3a_passed = False
            details_3a = f"FAIL: {exc}"

        results.append(
            TestResult(
                test_id="T3A_RESTART_RECOVERY_CANDIDATE_A",
                description="Engine restart recovery with Candidate A restores active trade",
                passed=t3a_passed,
                details=details_3a,
            )
        )

    # -------------------------------------------------------------------------
    # TEST 3B: Engine restart recovery with Admitted Candidate B
    # In production, after Candidate B is admitted, the current candidate config is Candidate B.
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-rec-b")
        cand_b = build_candidate("cand-b-rec-b")
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, cand_a)
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, qual_b, require_flat=False)

        engine._mark_active_position(
            engine.active_trades["BTCUSDT"], Decimal("50010"), NOW + timedelta(seconds=10)
        )

        try:
            restarted_b = LivePaperEngine(
                symbols=("BTCUSDT",),
                candidates={"BTCUSDT": cand_b},
                ledger_db=tmp_path / "paper-ledger.sqlite3",
                lifecycle_db=tmp_path / "paper-lifecycle.sqlite3",
                observations_db=tmp_path / "paper-observations.sqlite3",
            )
            t3b_passed = (
                "BTCUSDT" in restarted_b.active_trades
                and restarted_b.active_trades["BTCUSDT"].candidate_id == cand_a.candidate_id
            )
            details_3b = "PASS: Clean recovery with Candidate B."
        except PaperRestartRecoveryError as exc:
            t3b_passed = False
            details_3b = (
                f"FAIL: Crashed with PaperRestartRecoveryError('{exc}') "
                "because candidate_by_id lacks Candidate A."
            )

        results.append(
            TestResult(
                test_id="T3B_RESTART_RECOVERY_ADMITTED_CANDIDATE_B",
                description="Engine restart recovery when admitted Candidate B is configured",
                passed=t3b_passed,
                details=details_3b,
            )
        )

    # -------------------------------------------------------------------------
    # TEST 4: Trade close records Candidate A in SQLite paper ledger
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-close")
        cand_b = build_candidate("cand-b-close")
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, cand_a)
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
        engine.admit_candidate(cand_b, qual_b, require_flat=False)

        close_time = NOW + timedelta(minutes=5)
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

        reader = ReadOnlyLedgerReader(tmp_path)
        closed_trades = reader.read_closed_trades()
        states_after_close = engine.sqlite_ledger.load_position_states()

        t4_passed = (
            "BTCUSDT" not in engine.active_trades
            and len(states_after_close) == 0
            and len(closed_trades) == 1
            and closed_trades[0].candidate_id == cand_a.candidate_id
            and closed_trades[0].candidate_artifact_hash == cand_a.artifact_hash
            and closed_trades[0].exit_reason == "take_profit_hit"
        )
        cid = closed_trades[0].candidate_id if closed_trades else None
        results.append(
            TestResult(
                test_id="T4_TRADE_CLOSE_LEDGER_INTEGRITY",
                description="Trade close records Candidate A ID and artifact hash in SQLite ledger",
                passed=t4_passed,
                details=f"closed_candidate_id={cid}, states_remaining={len(states_after_close)}",
            )
        )

    # -------------------------------------------------------------------------
    # TEST 5: require_flat=True defers candidate admission
    # -------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp_path = Path(td)
        cand_a = build_candidate("cand-a-flat")
        cand_b = build_candidate("cand-b-flat")
        qual_b = build_qualification(cand_b)

        engine = setup_engine(tmp_path, cand_a)
        engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)

        decision = engine.admit_candidate(cand_b, qual_b, require_flat=True)

        t5_passed = (
            decision.decision == "deferred_active_position"
            and "active_position_open" in decision.reason_codes
            and decision.active_trade_retained is False
            and engine.candidates["BTCUSDT"].candidate_id == cand_a.candidate_id
            and engine.active_trades["BTCUSDT"].candidate.candidate_id == cand_a.candidate_id
        )
        results.append(
            TestResult(
                test_id="T5_ADMISSION_DEFERRAL_REQUIRE_FLAT_TRUE",
                description="Candidate admission deferred when require_flat=True and trade active",
                passed=t5_passed,
                details=(
                    f"decision={decision.decision}, reason_codes={decision.reason_codes}, "
                    f"engine.candidate={engine.candidates['BTCUSDT'].candidate_id}"
                ),
            )
        )

    return results


def main() -> int:
    print("=" * 80)
    print("EMPIRICAL STRESS TEST SUITE: OPEN TRADE IMMUTABILITY & RECOVERY")
    print("=" * 80)

    results = run_all_stress_tests()
    all_passed = True

    for r in results:
        status_str = "[PASS]" if r.passed else "[FAIL]"
        print(f"\n{status_str} {r.test_id}: {r.description}")
        print(f"       {r.details}")
        if not r.passed:
            all_passed = False

    print("\n" + "=" * 80)
    print("TEST SUMMARY:")
    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    print(f"Passed: {passed_count}/{total_count} ({passed_count / total_count * 100:.1f}%)")
    print(f"Verdict: {'APPROVE' if all_passed else 'REQUEST_CHANGES'}")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
