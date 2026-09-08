"""Empirical Challenger Adversarial Tamper Verification Suite for Milestone 2 Iteration 3.

Empirically tests cryptographic tamper resistance and open trade immutability:
1. Mutates strategy risk multipliers, indicator parameters, and entry/exit rules
   in SQLite `strategy_json` while preserving hash strings; verifies engine restart raises
   `PaperRestartRecoveryError`.
2. Passes tampered candidates (mutated risk, indicators, rules) and tampered qualifications
   to `StrategyAdmissionDecider.evaluate_admission`; verifies decision is `blocked_invalid_binding`.
3. Passes tampered candidate paths to `extract_paper_feedback` and `PaperFeedbackExtractor`;
   verifies `DomainViolation` is raised.
"""

from __future__ import annotations

import gc
import json
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.feed.models import TickerSnapshot
from autonomous_futures.paper.admission import (
    StrategyAdmissionDecider,
)
from autonomous_futures.paper.feedback_extractor import (
    PaperFeedbackExtractor,
    extract_paper_feedback,
)
from autonomous_futures.paper.ledger import PaperRestartRecoveryError
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    _artifact_content_hash,
    build_creator_candidate_artifact,
    read_creator_candidate_artifact,
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

passed_count = 0
failed_count = 0
results: list[dict[str, Any]] = []


def record(name: str, passed: bool, details: str = "") -> None:
    global passed_count, failed_count
    status = "PASS" if passed else "FAIL"
    if passed:
        passed_count += 1
    else:
        failed_count += 1
    print(f"[{status}] {name}")
    if details:
        print(f"       {details}")
    results.append({"name": name, "status": status, "details": details})


def build_candidate(
    candidate_id: str = "cand-test-alpha",
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
    trailing_mult: str = "1.0",
    lookback: int = 14,
    symbol: str = "BTCUSDT",
    entry_rule: str = "rsi <= 30",
    exit_rule: str = "rsi >= 50",
) -> CreatorCandidateArtifact:
    feats = (FeatureRef(name="rsi", lookback=lookback, shift=1),)
    ent = EntryExit(long=entry_rule, short="rsi >= 70")
    ex = EntryExit(long=exit_rule, short="rsi <= 50")
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
            trailing_atr_multiplier=Decimal(trailing_mult),
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


def build_qualification(
    candidate: CreatorCandidateArtifact,
    decision: str = "qualified",
    candidate_hash_override: str | None = None,
) -> CreatorCandidateQualificationArtifact:
    cand_hash = candidate_hash_override or candidate.artifact_hash
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
            "candidate_artifact_hash": cand_hash,
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


# ==============================================================================
# SUITE 1: SQLite Position State strategy_json Tamper Resistance
# ==============================================================================
def run_sqlite_tamper_suite() -> None:
    print("\n" + "=" * 80)
    print("SUITE 1: SQLITE STRATEGY_JSON TAMPER DETECTION & RESTART REJECTION")
    print("=" * 80)

    test_mutations = [
        ("risk_stop_multiplier", ("strategy", "risk", "stop_atr_multiplier"), "99.0"),
        ("risk_tp_multiplier", ("strategy", "risk", "take_profit_atr_multiplier"), "0.1"),
        ("risk_trailing_multiplier", ("strategy", "risk", "trailing_atr_multiplier"), "15.0"),
        ("risk_position_fraction", ("strategy", "risk", "position_fraction"), "0.99"),
        ("indicator_lookback", ("strategy", "features", 0, "lookback"), 99),
        ("indicator_shift", ("strategy", "features", 0, "shift"), 5),
        ("entry_rule", ("strategy", "entry", "long"), "rsi <= 95"),
        ("exit_rule", ("strategy", "exit", "long"), "rsi >= 99"),
        ("strategy_family", ("strategy", "family"), "tampered_family"),
        ("research_seed", ("research_seed",), 9999),
    ]

    for label, path_keys, new_val in test_mutations:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            tmp = Path(td)
            cand_a = build_candidate("cand-a", stop_mult="1.5", tp_mult="3.0")
            cand_b = build_candidate("cand-b", stop_mult="2.0", tp_mult="4.0")
            qual_b = build_qualification(cand_b)

            engine = LivePaperEngine(
                symbols=("BTCUSDT",),
                candidates={"BTCUSDT": cand_a},
                ledger_db=tmp / "paper-ledger.sqlite3",
                lifecycle_db=tmp / "paper-lifecycle.sqlite3",
                observations_db=tmp / "paper-observations.sqlite3",
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
            opened = engine.execute_open("BTCUSDT", 1, Decimal("100"), NOW)
            assert opened is not None

            # Admit candidate B so candidate A is NOT present in engine.candidates upon restart
            engine.admit_candidate(cand_b, qual_b, require_flat=False)
            engine._mark_active_position(
                engine.active_trades["BTCUSDT"], Decimal("50010"), NOW + timedelta(seconds=10)
            )

            # Mutate SQLite state
            db_path = tmp / "paper-ledger.sqlite3"
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT trade_id, state_json FROM paper_position_state WHERE trade_id = ?",
                    (opened.trade_id,),
                ).fetchone()
                assert row is not None
                trade_id, raw_state_json = row
                state_dict = json.loads(raw_state_json)
                strat_dict = json.loads(state_dict["strategy_json"])

                curr: Any = strat_dict
                for k in path_keys[:-1]:
                    curr = curr[k]
                curr[path_keys[-1]] = new_val

                # Preserve hashes intact
                state_dict["strategy_json"] = json.dumps(
                    strat_dict, sort_keys=True, separators=(",", ":")
                )
                conn.execute(
                    "UPDATE paper_position_state SET state_json = ? WHERE trade_id = ?",
                    (json.dumps(state_dict, sort_keys=True, separators=(",", ":")), trade_id),
                )
                conn.commit()

            # Verify LivePaperEngine restart raises PaperRestartRecoveryError
            caught = False
            err_msg = ""
            try:
                LivePaperEngine(
                    symbols=("BTCUSDT",),
                    candidates={"BTCUSDT": cand_b},
                    ledger_db=tmp / "paper-ledger.sqlite3",
                    lifecycle_db=tmp / "paper-lifecycle.sqlite3",
                    observations_db=tmp / "paper-observations.sqlite3",
                )
            except PaperRestartRecoveryError as exc:
                caught = True
                err_msg = str(exc)
            except Exception as exc:
                err_msg = f"Wrong exception: {type(exc).__name__}: {exc}"

            del engine
            gc.collect()

            record(
                f"SQLITE_TAMPER_{label.upper()}",
                caught,
                f"Expected PaperRestartRecoveryError, caught={caught}, msg='{err_msg if caught else ''}'",
            )

    # Test direct SqlitePaperLedger.require_recoverable_position_states check
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        cand_a = build_candidate("cand-a-direct")
        ledger = SqlitePaperLedger(tmp / "ledger.sqlite3")
        state_entry = {
            "state_version": 1,
            "trade_id": "trade-001",
            "candidate_id": cand_a.candidate_id,
            "candidate_artifact_hash": cand_a.artifact_hash,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "quantity": "1.0",
            "base_margin": "100.0",
            "leverage": "1.0",
            "watermark": "50000.0",
            "peak_pnl": "0.0",
            "stop_price": "49000.0",
            "target_price": "52000.0",
            "trailing_atr_multiplier": "1.0",
            "current_atr": "100.0",
            "opened_at": NOW.isoformat(),
            "trailing_stop_price": None,
            "strategy_json": json.dumps(cand_a.model_dump(mode="json")),
        }
        ledger.save_position_state(state_entry)

        # Mutate candidate_a's stop_atr_multiplier while preserving artifact_hash
        tampered_cand = cand_a.model_copy(deep=True)
        object.__setattr__(
            tampered_cand.strategy.risk,
            "stop_atr_multiplier",
            Decimal("99.0"),
        )
        assert _artifact_content_hash(tampered_cand) != tampered_cand.artifact_hash

        direct_caught = False
        direct_msg = ""
        try:
            ledger.require_recoverable_position_states(
                {"trade-001"}, {cand_a.candidate_id: tampered_cand}
            )
        except PaperRestartRecoveryError as exc:
            direct_caught = True
            direct_msg = str(exc)

        del ledger
        gc.collect()

        record(
            "SQLITE_LEDGER_REQUIRE_RECOVERABLE_CONTENT_HASH_CHECK",
            direct_caught,
            f"require_recoverable_position_states raised PaperRestartRecoveryError: {direct_msg if direct_caught else 'FAILED'}",
        )


# ==============================================================================
# SUITE 2: Strategy Admission Decider Tamper Resistance
# ==============================================================================
def run_admission_tamper_suite() -> None:
    print("\n" + "=" * 80)
    print("SUITE 2: STRATEGY ADMISSION DECIDER ADVERSARIAL TAMPER RESISTANCE")
    print("=" * 80)

    decider = StrategyAdmissionDecider()

    # 2.1: Tamper candidate risk while preserving candidate.artifact_hash
    cand = build_candidate("cand-adm-risk")
    qual = build_qualification(cand)
    tampered_cand = cand.model_copy(deep=True)
    object.__setattr__(
        tampered_cand.strategy.risk,
        "stop_atr_multiplier",
        Decimal("99.0"),
    )
    assert tampered_cand.artifact_hash == cand.artifact_hash
    assert _artifact_content_hash(tampered_cand) != tampered_cand.artifact_hash

    dec = decider.evaluate_admission(
        candidate=tampered_cand,
        qualification=qual,
        symbol="BTCUSDT",
        evaluated_at=NOW,
    )
    record(
        "ADMISSION_TAMPER_CANDIDATE_RISK_MULTIPLIER",
        dec.decision == "blocked_invalid_binding"
        and "candidate_hash_mismatch" in dec.reason_codes,
        f"decision={dec.decision}, reason_codes={dec.reason_codes}",
    )

    # 2.2: Tamper candidate indicator parameters while preserving candidate.artifact_hash
    cand_ind = build_candidate("cand-adm-ind")
    qual_ind = build_qualification(cand_ind)
    tampered_ind = cand_ind.model_copy(deep=True)
    object.__setattr__(tampered_ind.strategy.features[0], "lookback", 999)
    assert tampered_ind.artifact_hash == cand_ind.artifact_hash
    assert _artifact_content_hash(tampered_ind) != tampered_ind.artifact_hash

    dec_ind = decider.evaluate_admission(
        candidate=tampered_ind,
        qualification=qual_ind,
        symbol="BTCUSDT",
        evaluated_at=NOW,
    )
    record(
        "ADMISSION_TAMPER_CANDIDATE_INDICATOR_LOOKBACK",
        dec_ind.decision == "blocked_invalid_binding"
        and "candidate_hash_mismatch" in dec_ind.reason_codes,
        f"decision={dec_ind.decision}, reason_codes={dec_ind.reason_codes}",
    )

    # 2.3: Tamper candidate entry rule expression while preserving candidate.artifact_hash
    cand_rule = build_candidate("cand-adm-rule")
    qual_rule = build_qualification(cand_rule)
    tampered_rule = cand_rule.model_copy(deep=True)
    object.__setattr__(tampered_rule.strategy.entry, "long", "rsi <= 99")
    assert tampered_rule.artifact_hash == cand_rule.artifact_hash
    assert _artifact_content_hash(tampered_rule) != tampered_rule.artifact_hash

    dec_rule = decider.evaluate_admission(
        candidate=tampered_rule,
        qualification=qual_rule,
        symbol="BTCUSDT",
        evaluated_at=NOW,
    )
    record(
        "ADMISSION_TAMPER_CANDIDATE_ENTRY_RULE",
        dec_rule.decision == "blocked_invalid_binding"
        and "candidate_hash_mismatch" in dec_rule.reason_codes,
        f"decision={dec_rule.decision}, reason_codes={dec_rule.reason_codes}",
    )

    # 2.4: Tamper qualification metric/gates while preserving qualification_hash
    cand_q = build_candidate("cand-adm-qual")
    qual_q = build_qualification(cand_q)
    tampered_qual = qual_q.model_copy(deep=True)
    # Mutate observed value in gate without updating qualification_hash
    tampered_gate = QualificationGateResult(
        gate_id=qual_q.gates[0].gate_id,
        passed=True,
        observed=Decimal("99.99"),  # tampered
        threshold=qual_q.gates[0].threshold,
        comparator=qual_q.gates[0].comparator,
        reason_code=qual_q.gates[0].reason_code,
    )
    object.__setattr__(tampered_qual, "gates", (tampered_gate,))
    assert tampered_qual.qualification_hash == qual_q.qualification_hash
    assert _qualification_content_hash(tampered_qual) != tampered_qual.qualification_hash

    dec_qual = decider.evaluate_admission(
        candidate=cand_q,
        qualification=tampered_qual,
        symbol="BTCUSDT",
        evaluated_at=NOW,
    )
    record(
        "ADMISSION_TAMPER_QUALIFICATION_GATE_MUTATION",
        dec_qual.decision == "blocked_invalid_binding"
        and "candidate_hash_mismatch" in dec_qual.reason_codes,
        f"decision={dec_qual.decision}, reason_codes={dec_qual.reason_codes}",
    )

    # 2.5: Untampered authentic candidate & qualification
    dec_clean = decider.evaluate_admission(
        candidate=cand,
        qualification=qual,
        symbol="BTCUSDT",
        evaluated_at=NOW,
    )
    record(
        "ADMISSION_CLEAN_CANDIDATE_ADMITTED",
        dec_clean.decision == "admitted",
        f"decision={dec_clean.decision}, hash={dec_clean.decision_hash[:16]}...",
    )


# ==============================================================================
# SUITE 3: Feedback Extractor Adversarial Tamper Resistance
# ==============================================================================
def run_feedback_extractor_tamper_suite() -> None:
    print("\n" + "=" * 80)
    print("SUITE 3: FEEDBACK EXTRACTOR ADVERSARIAL FILE TAMPER RESISTANCE")
    print("=" * 80)

    # Prepare dummy ledger db
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        ledger_path = tmp / "paper-ledger.sqlite3"
        with sqlite3.connect(ledger_path) as conn:
            conn.execute(
                """CREATE TABLE paper_ledger_events (
                    event_id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    candidate_artifact_hash TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    base_margin TEXT NOT NULL,
                    realized_pnl TEXT NOT NULL,
                    net_pnl TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    exit_reason TEXT,
                    timestamp TEXT NOT NULL,
                    balance_after TEXT NOT NULL
                )"""
            )
            conn.commit()

        # Build genuine candidate and write to disk
        cand = build_candidate("cand-feed-tamper", stop_mult="1.5", tp_mult="3.0")
        cand_dict = cand.model_dump(mode="json")

        # 3.1: File tamper - mutate stop_atr_multiplier while leaving artifact_hash string unchanged
        tampered_stop_dict = json.loads(json.dumps(cand_dict))
        tampered_stop_dict["strategy"]["risk"]["stop_atr_multiplier"] = "99.0"
        tampered_stop_path = tmp / "cand_tampered_stop.json"
        tampered_stop_path.write_text(json.dumps(tampered_stop_dict, indent=2), encoding="utf-8")

        caught_extract_stop = False
        msg_stop = ""
        try:
            extract_paper_feedback(
                ledger_path=ledger_path,
                candidate_artifact_path=tampered_stop_path,
            )
        except DomainViolation as exc:
            caught_extract_stop = True
            msg_stop = str(exc)

        record(
            "EXTRACT_FEEDBACK_REJECTS_TAMPERED_RISK_MULTIPLIER",
            caught_extract_stop,
            f"Expected DomainViolation, caught={caught_extract_stop}, msg='{msg_stop if caught_extract_stop else ''}'",
        )

        # 3.2: File tamper - mutate indicator lookback
        tampered_lookback_dict = json.loads(json.dumps(cand_dict))
        tampered_lookback_dict["strategy"]["features"][0]["lookback"] = 99
        tampered_lookback_path = tmp / "cand_tampered_lookback.json"
        tampered_lookback_path.write_text(
            json.dumps(tampered_lookback_dict, indent=2), encoding="utf-8"
        )

        caught_extract_lookback = False
        msg_lb = ""
        try:
            extract_paper_feedback(
                ledger_path=ledger_path,
                candidate_artifact_path=tampered_lookback_path,
            )
        except DomainViolation as exc:
            caught_extract_lookback = True
            msg_lb = str(exc)

        record(
            "EXTRACT_FEEDBACK_REJECTS_TAMPERED_INDICATOR_LOOKBACK",
            caught_extract_lookback,
            f"Expected DomainViolation, caught={caught_extract_lookback}, msg='{msg_lb if caught_extract_lookback else ''}'",
        )

        # 3.3: File tamper - mutate entry rule
        tampered_rule_dict = json.loads(json.dumps(cand_dict))
        tampered_rule_dict["strategy"]["entry"]["long"] = "rsi <= 99"
        tampered_rule_path = tmp / "cand_tampered_rule.json"
        tampered_rule_path.write_text(json.dumps(tampered_rule_dict, indent=2), encoding="utf-8")

        caught_extract_rule = False
        msg_rule = ""
        try:
            extract_paper_feedback(
                ledger_path=ledger_path,
                candidate_artifact_path=tampered_rule_path,
            )
        except DomainViolation as exc:
            caught_extract_rule = True
            msg_rule = str(exc)

        record(
            "EXTRACT_FEEDBACK_REJECTS_TAMPERED_ENTRY_RULE",
            caught_extract_rule,
            f"Expected DomainViolation, caught={caught_extract_rule}, msg='{msg_rule if caught_extract_rule else ''}'",
        )

        # 3.4: Direct read_creator_candidate_artifact on tampered file raises DomainViolation
        caught_read = False
        msg_read = ""
        try:
            read_creator_candidate_artifact(tampered_stop_path)
        except DomainViolation as exc:
            caught_read = True
            msg_read = str(exc)

        record(
            "READ_CREATOR_CANDIDATE_ARTIFACT_RAISES_DOMAIN_VIOLATION",
            caught_read and "artifact hash mismatch" in msg_read,
            f"Expected DomainViolation with 'artifact hash mismatch', msg='{msg_read if caught_read else ''}'",
        )

        # 3.5: PaperFeedbackExtractor.resolve_candidate_metadata raises DomainViolation
        extractor = PaperFeedbackExtractor(storage_path=ledger_path)
        caught_resolve = False
        msg_resolve = ""
        try:
            extractor.resolve_candidate_metadata(candidate_artifact_path=tampered_stop_path)
        except DomainViolation as exc:
            caught_resolve = True
            msg_resolve = str(exc)

        record(
            "RESOLVE_CANDIDATE_METADATA_RAISES_DOMAIN_VIOLATION",
            caught_resolve,
            f"Expected DomainViolation, msg='{msg_resolve if caught_resolve else ''}'",
        )

        # 3.6: Clean untampered candidate path succeeds without DomainViolation
        clean_path = tmp / "cand_clean.json"
        clean_path.write_text(json.dumps(cand_dict, indent=2), encoding="utf-8")
        clean_meta = extractor.resolve_candidate_metadata(candidate_artifact_path=clean_path)
        record(
            "RESOLVE_CANDIDATE_METADATA_CLEAN_PATH_PASSES",
            clean_meta.candidate_id == cand.candidate_id
            and clean_meta.candidate_artifact_hash == cand.artifact_hash,
            f"candidate_id={clean_meta.candidate_id}, hash={clean_meta.candidate_artifact_hash[:16]}...",
        )

        del extractor
        gc.collect()


def main() -> int:
    print("=" * 80)
    print("EMPIRICAL CHALLENGER VERIFICATION: MILESTONE 2 ITERATION 3")
    print("Targeted Adversarial Tamper Suite: LivePaperEngine, Ledger, Decider, Feedback")
    print("=" * 80)

    run_sqlite_tamper_suite()
    run_admission_tamper_suite()
    run_feedback_extractor_tamper_suite()

    total = passed_count + failed_count
    pass_pct = (passed_count / total * 100.0) if total > 0 else 0.0

    print("\n" + "=" * 80)
    print(f"ADVERSARIAL TAMPER SUITE COMPLETE: {passed_count}/{total} PASSED ({pass_pct:.1f}%)")
    verdict = "APPROVE" if failed_count == 0 else "REQUEST_CHANGES"
    print(f"Verdict: {verdict}")
    print("=" * 80)
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
