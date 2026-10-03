"""Synthetic cycle regression: runtime quarantine must remain visible in its receipt."""

import sqlite3
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import autonomous_futures.pipeline.autonomous_cycle as cycle_module
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.paper.admission import StrategyAdmissionDecider
from autonomous_futures.paper.live_engine import LivePaperEngine
from autonomous_futures.pipeline.autonomous_cycle import (
    AutonomousCycleConfig,
    execute_autonomous_cycle,
)
from autonomous_futures.research.creator_epoch import (
    create_creator_epoch,
    create_creator_epoch_control,
    read_creator_epoch_control,
    require_creator_epoch_candidate,
)
from autonomous_futures.research.creator_failure_feedback import CreatorQualificationFailureFeedback
from autonomous_futures.research.qualification_artifacts import QualificationGateResult
from autonomous_futures.research.trade_simulation import (
    EquityPoint,
    SimulatedTrade,
    TradeSimulationResult,
)
from tests.unit.test_autonomous_cycle import (
    HASH_A,
    HASH_B,
    NOW,
    _build_test_candidate,
    _make_cached_window,
    _policy,
)


@pytest.mark.parametrize(
    "phase",
    ["initial", "adoption", "reserve", "research_only", "missing_control", "control_failure"],
)
def test_cycle_receipt_cannot_claim_adoption_rejected_by_epoch_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    initial = _build_test_candidate("cand-initial-epoch")
    journal = tmp_path / "epoch.sqlite3"
    control = tmp_path / "control.sqlite3"
    checkpoint = create_creator_epoch(journal, epoch_id="epoch-cycle", policy_hash="c" * 64)
    create_creator_epoch_control(control, journal, checkpoint)
    epoch_options = {
        "epoch_path": journal,
        "epoch_checkpoint": checkpoint,
        "epoch_control": control,
    }
    engine = LivePaperEngine(
        symbols=("BTCUSDT",),
        candidates={"BTCUSDT": initial},
        ledger_db=tmp_path / "ledger.sqlite3",
        lifecycle_db=tmp_path / "lifecycle.sqlite3",
        observations_db=tmp_path / "obs.sqlite3",
        **(epoch_options if phase != "adoption" else {}),
    )
    if phase == "adoption":
        original_admit = engine.admit_candidate

        def revoke_before_adoption(candidate, qualification, **kwargs):
            engine.admission_decider = StrategyAdmissionDecider(**epoch_options)
            return original_admit(candidate, qualification, **kwargs)

        monkeypatch.setattr(engine, "admit_candidate", revoke_before_adoption)
    feedback = CreatorQualificationFailureFeedback(
        candidate_id=initial.candidate_id,
        candidate_artifact_hash=initial.artifact_hash,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_hash="1" * 64,
        qualification_policy_id="policy-cycle-001",
        failure_reason_codes=("oos_profit_factor_below_threshold",),
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.5"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
    )

    calls = []

    def critic(request):
        calls.append("critic")
        return {
            "review_id": "review-epoch-cycle",
            "research_run_id": request.research_run_id,
            "candidate_id": request.candidate_id,
            "decision": "revise",
            "failure_reason_codes": list(request.feedback.failure_reason_codes),
            "revision_actions": ["adjust_stop_multiplier"],
        }

    def creator(request):
        calls.append("creator")
        return {
            "proposal_id": "proposal-epoch-cycle",
            "research_run_id": request.research_run_id,
            "hypothesis": "Test-only revised strategy",
            "expected_regime": "test",
            "novelty_reason": "Test-only quarantine receipt",
            "strategy": _build_test_candidate(
                "cand-revised-epoch", stop_atr="2.0"
            ).strategy.model_dump(),
        }

    def simulator(candidate, frame, window):
        timestamp = frame["timestamp"].iloc[-1].to_pydatetime()
        trades = tuple(
            SimulatedTrade(
                trade_id=f"t{index}",
                symbol=window.spec.symbol,
                side="LONG",
                entry_timestamp=timestamp - timedelta(hours=2),
                exit_timestamp=timestamp - timedelta(hours=1),
                quantity=Decimal("1"),
                entry_price=Decimal("100"),
                exit_price=Decimal("100") + pnl,
                entry_notional=Decimal("100"),
                exit_notional=Decimal("100") + pnl,
                entry_fee=Decimal("0"),
                exit_fee=Decimal("0"),
                fees=Decimal("0"),
                slippage_cost=Decimal("0"),
                gross_pnl=pnl,
                net_pnl=pnl,
                exit_reason="signal_exit",
            )
            for index, pnl in enumerate((Decimal("1"), Decimal("-0.5")))
        )
        equity = Decimal("100") + sum(trade.net_pnl for trade in trades)
        return TradeSimulationResult(
            symbol=window.spec.symbol,
            starting_equity=Decimal("100"),
            final_equity=equity,
            total_fees=Decimal("0"),
            total_slippage_cost=Decimal("0"),
            trades=trades,
            equity_curve=(EquityPoint(timestamp=timestamp, equity=equity),),
        )

    if phase == "missing_control":
        control.unlink()
    if phase == "control_failure":
        with sqlite3.connect(control) as conn:
            conn.execute(
                "CREATE TRIGGER reject_head BEFORE UPDATE ON epoch_control "
                "BEGIN SELECT RAISE(ABORT, 'checkpoint rejected'); END"
            )
    if phase == "reserve":
        original_write = cycle_module.write_creator_candidate_artifact

        def verify_before_persistence(path, candidate):
            assert not path.exists()
            current = read_creator_epoch_control(control, journal, checkpoint)
            assert current.sequence == 1
            require_creator_epoch_candidate(journal, current, candidate)
            return original_write(path, candidate)

        monkeypatch.setattr(
            cycle_module, "write_creator_candidate_artifact", verify_before_persistence
        )

    def run():
        return execute_autonomous_cycle(
            config=AutonomousCycleConfig(
                cycle_id="cycle-epoch-receipt",
                symbol="BTCUSDT",
                bundle_hash=HASH_A,
                dataset_registry_hash=HASH_B,
                qualification_policy=_policy(),
                artifact_root=tmp_path / "cycle",
                **({"research_only": True} if phase == "research_only" else {}),
            ),
            windows=(_make_cached_window(),),
            prior_feedback=feedback,
            critic_transport=critic,
            creator_transport=creator,
            paper_engine=engine,
            simulator=simulator,
            now=NOW,
            **(
                {"reserve_creator_epoch": True}
                if phase in ("reserve", "research_only", "missing_control", "control_failure")
                else {}
            ),
        )

    if phase in ("missing_control", "control_failure"):
        with pytest.raises(DomainViolation):
            run()
        assert not (tmp_path / "cycle" / "candidates").exists()
        assert not (tmp_path / "cycle" / "evidence" / "creator").exists()
        if phase == "missing_control":
            assert calls == []
            assert not (tmp_path / "cycle").exists()
        else:
            assert calls == ["critic", "creator"]
            assert read_creator_epoch_control(control, journal, checkpoint) == checkpoint
        return
    result = run()
    assert result.qualification_decision == "qualified"
    if phase == "research_only":
        assert result.cycle_status == "completed_unadmitted"
        assert result.admission_decision is None
        assert result.stop_reasons == ("paper_admission_not_authorized",)
        assert result.active_candidate_id == initial.candidate_id
        assert engine.candidates == {"BTCUSDT": initial}
        assert engine.qualifications == {}
        assert engine.sqlite_ledger.load().entries == ()
        assert read_creator_epoch_control(control, journal, checkpoint).sequence == 1
        return
    if phase == "reserve":
        assert result.cycle_status == "completed_admitted"
        candidate = engine.candidates["BTCUSDT"]
        current = read_creator_epoch_control(control, journal, checkpoint)
        assert current.sequence == 1
        require_creator_epoch_candidate(journal, current, candidate)
        assert result.active_candidate_id == candidate.candidate_id
        assert engine.sqlite_ledger.load().entries == ()
        second = run()
        assert second.cycle_status == "failed"
        assert second.stop_reasons == ("candidate_id_forbidden",)
        assert read_creator_epoch_control(control, journal, checkpoint) == current
        return
    assert result.cycle_status == "completed_unadmitted"
    assert result.admission_decision == "blocked_invalid_binding"
    assert result.stop_reasons == ("creator_epoch_candidate_quarantined",)
    assert result.active_candidate_id == initial.candidate_id
    assert engine.candidates == {"BTCUSDT": initial}
    assert engine.qualifications == {}
    assert engine.sqlite_ledger.load().entries == ()
    if phase == "adoption":
        assert result.admission_decision_hash == engine.admission_decisions["BTCUSDT"].decision_hash
