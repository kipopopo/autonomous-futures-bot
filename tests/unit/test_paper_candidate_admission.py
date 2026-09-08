"""Unit tests for Strategy Admission contracts, decider, and LivePaperEngine integration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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
