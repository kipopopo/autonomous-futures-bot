"""Unit tests for Strategy Admission contracts, decider, and LivePaperEngine integration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.domain.contracts import (
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.paper.admission import (
    StrategyAdmissionDecider,
    strategy_admission_content_hash,
)
from autonomous_futures.paper.live_engine import ActivePaperTrade, LivePaperEngine
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    QualificationGateResult,
    QualificationMetric,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _build_test_candidate(candidate_id: str = "cand-test-001", symbol: str = "BTCUSDT"):
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("3.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id="run-test-creator-001",
        research_seed=42,
        created_at=NOW,
    )


def _build_test_qualification(
    candidate,
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
    from autonomous_futures.research.qualification_artifacts import (
        _qualification_content_hash,
    )

    return provisional.model_copy(
        update={"qualification_hash": _qualification_content_hash(provisional)}
    )


def test_strategy_admission_decision_content_hash_and_model():
    cand = _build_test_candidate()
    qual = _build_test_qualification(cand, decision="qualified")

    decider = StrategyAdmissionDecider()
    decision = decider.evaluate_admission(
        candidate=cand,
        qualification=qual,
        symbol="BTCUSDT",
        active_trades={},
        evaluated_at=NOW,
    )

    assert decision.decision == "admitted"
    assert decision.candidate_id == cand.candidate_id
    assert decision.candidate_artifact_hash == cand.artifact_hash
    assert decision.qualification_hash == qual.qualification_hash
    assert decision.symbol == "BTCUSDT"
    assert decision.active_trade_retained is False
    assert decision.decision_hash == strategy_admission_content_hash(decision)


@pytest.mark.parametrize("missing_file", [False, True])
def test_epoch_runtime_requires_control_before_outputs(tmp_path: Path, missing_file: bool):
    from autonomous_futures.domain.errors import DomainViolation
    from autonomous_futures.research.creator_epoch import create_creator_epoch

    path = tmp_path / "epoch.sqlite3"
    checkpoint = create_creator_epoch(path, epoch_id="epoch-20261002", policy_hash=HASH_C)
    output = tmp_path / "runtime"
    with pytest.raises(DomainViolation):
        LivePaperEngine(
            symbols=("BTCUSDT",),
            ledger_db=output / "ledger.sqlite3",
            lifecycle_db=output / "lifecycle.sqlite3",
            observations_db=output / "obs.sqlite3",
            epoch_path=path,
            epoch_checkpoint=checkpoint,
            epoch_control=tmp_path / "missing-control.sqlite3" if missing_file else None,
        )
    assert not output.exists()


def test_epoch_engine_quarantines_legacy_despite_valid_qualification(tmp_path: Path):
    from autonomous_futures.research.creator_epoch import (
        create_creator_epoch,
        create_creator_epoch_control,
    )

    path = tmp_path / "epoch.sqlite3"
    checkpoint = create_creator_epoch(path, epoch_id="epoch-20261002", policy_hash=HASH_C)
    candidate = _build_test_candidate()
    qualification = _build_test_qualification(candidate)
    control = tmp_path / "control.sqlite3"
    create_creator_epoch_control(control, path, checkpoint)
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": candidate},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "observations.sqlite3",
        epoch_path=path,
        epoch_checkpoint=checkpoint,
        epoch_control=control,
    )
    decision = engine.admit_candidate(candidate, qualification)
    assert decision.decision == "blocked_invalid_binding"
    assert decision.reason_codes == ("creator_epoch_candidate_quarantined",)
    assert not engine.qualifications
    assert not engine.sqlite_ledger.load().entries


def test_epoch_engine_revalidates_journal_before_entry(tmp_path: Path):
    from autonomous_futures.feed.models import TickerSnapshot
    from autonomous_futures.research.creator_epoch import (
        append_creator_epoch_acceptance,
        create_creator_epoch,
        create_creator_epoch_control,
    )
    from autonomous_futures.research.creator_proposals import (
        build_candidate_from_proposal,
        parse_creator_proposal,
    )

    path = tmp_path / "epoch.sqlite3"
    checkpoint = create_creator_epoch(path, epoch_id="epoch-20261002", policy_hash=HASH_C)
    proposal = parse_creator_proposal(
        {
            "proposal_id": "proposal-epoch-001",
            "research_run_id": "run-epoch-001",
            "hypothesis": "Test-only causal strategy",
            "expected_regime": "test",
            "novelty_reason": "Test-only epoch isolation",
            "strategy": _build_test_candidate().strategy.model_dump(),
        },
        epoch_id=checkpoint.epoch_id,
    )
    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id="run-epoch-001",
        research_seed=42,
        created_at=NOW,
    )
    outcome = proposal.build_outcome(
        decision="accepted",
        candidate_artifact_hash=candidate.artifact_hash,
        reason_codes=("schema_valid",),
        recorded_at=NOW,
    )
    control = tmp_path / "control.sqlite3"
    create_creator_epoch_control(control, path, checkpoint)
    checkpoint = append_creator_epoch_acceptance(
        path,
        checkpoint,
        proposal,
        candidate,
        outcome,
        control_path=control,
    )
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": candidate},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "observations.sqlite3",
        epoch_path=path,
        epoch_checkpoint=checkpoint,
        epoch_control=control,
    )
    assert (
        engine.admit_candidate(candidate, _build_test_qualification(candidate)).decision
        == "admitted"
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
    equity = engine.current_equity()
    path.unlink()
    assert (
        engine.execute_open("BTCUSDT", signal=1, conviction=Decimal("0.8"), event_time=NOW) is None
    )
    assert engine.current_equity() == equity
    assert engine.active_trades == {}
    assert engine.sqlite_ledger.load().entries == ()


def test_strategy_admission_blocks_unqualified():
    cand = _build_test_candidate()
    qual = _build_test_qualification(cand, decision="rejected")

    decider = StrategyAdmissionDecider()
    decision = decider.evaluate_admission(
        candidate=cand,
        qualification=qual,
        symbol="BTCUSDT",
        active_trades={},
        evaluated_at=NOW,
    )

    assert decision.decision == "blocked_unqualified"
    assert "qualification_rejected" in decision.reason_codes


def test_strategy_admission_blocks_hash_mismatch():
    cand = _build_test_candidate()
    qual = _build_test_qualification(cand, decision="qualified", candidate_hash_override="f" * 64)

    decider = StrategyAdmissionDecider()
    decision = decider.evaluate_admission(
        candidate=cand,
        qualification=qual,
        symbol="BTCUSDT",
        active_trades={},
        evaluated_at=NOW,
    )

    assert decision.decision == "blocked_invalid_binding"
    assert "candidate_hash_mismatch" in decision.reason_codes


def test_strategy_admission_deferral_when_strict_flat_required():
    cand = _build_test_candidate()
    qual = _build_test_qualification(cand, decision="qualified")

    mock_trade = ActivePaperTrade(
        trade_id="trade-101",
        candidate_id="cand-old-000",
        candidate_artifact_hash=HASH_C,
        symbol="BTCUSDT",
        side="LONG",
        open_entry=None,  # type: ignore[arg-type]
        quantity=Decimal("0.1"),
        base_margin=Decimal("10"),
        leverage=Decimal("1"),
        watermark=Decimal("50000"),
        peak_pnl=Decimal("0"),
        stop_price=Decimal("49000"),
        target_price=Decimal("52000"),
        trailing_atr_multiplier=Decimal("1.5"),
        current_atr=Decimal("100"),
        opened_at=NOW,
    )

    decider = StrategyAdmissionDecider()
    # When require_flat=True, active trade forces deferral
    deferred_decision = decider.evaluate_admission(
        candidate=cand,
        qualification=qual,
        symbol="BTCUSDT",
        active_trades={"BTCUSDT": mock_trade},
        require_flat=True,
        evaluated_at=NOW,
    )
    assert deferred_decision.decision == "deferred_active_position"
    assert "active_position_open" in deferred_decision.reason_codes

    # When require_flat=False, active trade is retained and candidate admitted for future trades
    admitted_decision = decider.evaluate_admission(
        candidate=cand,
        qualification=qual,
        symbol="BTCUSDT",
        active_trades={"BTCUSDT": mock_trade},
        require_flat=False,
        evaluated_at=NOW,
    )
    assert admitted_decision.decision == "admitted"
    assert admitted_decision.active_trade_retained is True


def test_live_paper_engine_admit_candidate_and_trade_isolation(tmp_path: Path):
    old_cand = _build_test_candidate(candidate_id="cand-old-001", symbol="BTCUSDT")
    new_cand = _build_test_candidate(candidate_id="cand-new-002", symbol="BTCUSDT")
    new_qual = _build_test_qualification(new_cand, decision="qualified")

    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": old_cand},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "obs.sqlite3",
    )

    assert engine.candidates["BTCUSDT"].candidate_id == "cand-old-001"

    # Simulate an active trade opened under old candidate
    active_trade = ActivePaperTrade(
        trade_id="trade-active-1",
        candidate_id=old_cand.candidate_id,
        candidate_artifact_hash=old_cand.artifact_hash,
        symbol="BTCUSDT",
        side="LONG",
        open_entry=None,  # type: ignore[arg-type]
        quantity=Decimal("0.1"),
        base_margin=Decimal("10"),
        leverage=Decimal("1"),
        watermark=Decimal("50000"),
        peak_pnl=Decimal("0"),
        stop_price=Decimal("49000"),
        target_price=Decimal("52000"),
        trailing_atr_multiplier=Decimal("1.5"),
        current_atr=Decimal("100"),
        opened_at=NOW,
        candidate=old_cand,
    )
    engine.active_trades["BTCUSDT"] = active_trade

    # Admit new candidate
    decision = engine.admit_candidate(new_cand, new_qual)
    assert decision.decision == "admitted"
    assert decision.active_trade_retained is True

    # New candidate is now active for future entries
    assert engine.candidates["BTCUSDT"].candidate_id == "cand-new-002"

    # Active trade's candidate remains strictly the old candidate (never mutated!)
    assert engine.active_trades["BTCUSDT"].candidate.candidate_id == "cand-old-001"


def test_live_paper_engine_blocks_hash_only_admission(tmp_path: Path):
    old_cand = _build_test_candidate("cand-old-001")
    new_cand = _build_test_candidate("cand-new-002")
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": old_cand},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "obs.sqlite3",
        qualifications_dir=tmp_path / "qualifications",
        base_dir=tmp_path,
    )

    decision = engine.admit_candidate(new_cand, qualification_hash=HASH_C)

    assert decision.decision == "blocked_unqualified"
    assert decision.paper_activation is False
    assert decision.decision_hash == strategy_admission_content_hash(decision)
    assert engine.candidates == {"BTCUSDT": old_cand}
    assert engine.qualifications == {}


@pytest.mark.parametrize("field", ["bundle_hash", "dataset_registry_hash"])
def test_strategy_admission_blocks_qualification_scope_mismatch(field: str):
    from autonomous_futures.research.qualification_artifacts import _qualification_content_hash

    candidate = _build_test_candidate()
    qualification = _build_test_qualification(candidate).model_copy(update={field: "f" * 64})
    qualification = qualification.model_copy(
        update={"qualification_hash": _qualification_content_hash(qualification)}
    )

    decision = StrategyAdmissionDecider().evaluate_admission(
        candidate=candidate, qualification=qualification, symbol="BTCUSDT", evaluated_at=NOW
    )

    assert decision.decision == "blocked_invalid_binding"
    assert decision.paper_activation is False
