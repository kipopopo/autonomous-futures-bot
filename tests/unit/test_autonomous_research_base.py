"""TDD coverage for the evidence-first autonomous research base."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.pipeline.autonomous_base import (
    AutonomousBaseConfig,
    AutonomousBaseCycleExecution,
    AutonomousBaseCycleRequest,
    AutonomousResearchBase,
    make_autonomous_cycle_runner,
    read_autonomous_base_result,
)
from autonomous_futures.pipeline.autonomous_cycle import (
    AutonomousCycleResult,
    autonomous_cycle_content_hash,
)
from autonomous_futures.research.autonomy_contracts import (
    FailureLearner,
    FailureLearningRequest,
    ResearchPlanner,
    ResearchPlanRequest,
    build_failure_memory_entry,
    failure_memory_content_hash,
)
from autonomous_futures.research.autonomy_prompts import (
    build_failure_learning_messages,
    build_research_plan_messages,
)
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.creator_generator import CreatorGenerationRequest
from autonomous_futures.research.creator_prompts import build_creator_proposal_messages
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    WalkForwardQualificationPolicy,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _feedback(
    *,
    candidate_id: str = "cand-seed-001",
    qualification_hash: str = HASH_C,
) -> CreatorQualificationFailureFeedback:
    return CreatorQualificationFailureFeedback(
        candidate_id=candidate_id,
        candidate_artifact_hash=HASH_A,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_hash=qualification_hash,
        qualification_policy_id="policy-base-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.8"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )


def _cycle_result(
    *,
    cycle_id: str,
    candidate_id: str,
    qualification_hash: str,
    qualification_decision: str = "rejected",
    cycle_status: str = "completed_unadmitted",
) -> AutonomousCycleResult:
    provisional = AutonomousCycleResult(
        cycle_id=cycle_id,
        symbol="BTCUSDT",
        cycle_status=cycle_status,
        prior_feedback_hash=HASH_C,
        critique_evidence_hash=HASH_A,
        candidate_id=candidate_id,
        candidate_artifact_hash=HASH_A,
        qualification_hash=qualification_hash,
        qualification_decision=qualification_decision,
        admission_decision=(
            "blocked_unqualified"
            if qualification_decision == "rejected"
            else "blocked_invalid_binding"
        ),
        admission_decision_hash=HASH_B,
        stop_reasons=(),
        active_candidate_id="cand-seed-001",
        completed_at=NOW,
        cycle_hash="0" * 64,
    )
    return provisional.model_copy(update={"cycle_hash": autonomous_cycle_content_hash(provisional)})


def _learner_transport(request):
    return {
        "failure_patterns": ["oos_profit_factor_below_threshold"],
        "learned_constraints": ["preserve_all_qualification_gates"],
        "recommended_novelty_dimensions": ["entry_logic", "feature_set"],
    }


def _planner_transport(request):
    return {
        "hypothesis": "Use a materially different entry confirmation with a volatility filter.",
        "expected_regime": "volatile_trend",
        "strategy_family": "volume_confirmed_momentum",
        "novelty_dimensions": ["entry_logic", "feature_set"],
        "falsification_criteria": [
            "reject if OOS profit factor remains below the pinned policy",
            "reject if any walk-forward window has zero trades",
        ],
    }


def _plan_request(*, cycle_id: str, prior_thesis_hashes: tuple[str, ...] = ()):
    entry = build_failure_memory_entry(
        base_run_id="base-prompt-001",
        source_type="seed_feedback",
        source_id="seed-feedback-001",
        sequence=0,
        feedback=_feedback(),
        cycle_id=None,
        cycle_hash=None,
        recorded_at=NOW,
    )
    learning_request = FailureLearningRequest(
        research_run_id="run-learning-prompt-001",
        base_run_id="base-prompt-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        cycle_index=1,
        failure_memory=(entry,),
        forbidden_candidate_ids=("cand-seed-001",),
        input_evidence_refs=(f"failure/{entry.memory_hash}",),
    )
    learning = FailureLearner(_learner_transport).learn(learning_request).artifact
    assert learning is not None
    return ResearchPlanRequest(
        research_run_id=f"run-creator-{cycle_id}",
        base_run_id="base-prompt-001",
        cycle_id=cycle_id,
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        cycle_index=1,
        failure_memory=(entry,),
        learning=learning,
        forbidden_candidate_ids=("cand-seed-001",),
        prior_thesis_hashes=prior_thesis_hashes,
        input_evidence_refs=(
            f"failure/{entry.memory_hash}",
            f"learning/{learning.learning_hash}",
        ),
    )


def test_failure_memory_entry_is_canonically_hashed() -> None:
    entry = build_failure_memory_entry(
        base_run_id="base-demo-001",
        source_type="seed_feedback",
        source_id="seed-feedback-001",
        sequence=0,
        feedback=_feedback(),
        cycle_id=None,
        cycle_hash=None,
        recorded_at=NOW,
    )

    assert entry.entry_id == f"failure-{entry.memory_hash}"
    assert failure_memory_content_hash(entry) == entry.memory_hash
    assert entry.execution_authority is False
    assert entry.paper_activation is False


def test_failure_memory_rejects_hash_tampering() -> None:
    entry = build_failure_memory_entry(
        base_run_id="base-demo-001",
        source_type="seed_feedback",
        source_id="seed-feedback-001",
        sequence=0,
        feedback=_feedback(),
        cycle_id=None,
        cycle_hash=None,
        recorded_at=NOW,
    )

    with pytest.raises(ValidationError, match="hash mismatch"):
        type(entry).model_validate({**entry.model_dump(), "memory_hash": "f" * 64})


def test_planner_rejects_replayed_thesis_even_with_new_cycle_id() -> None:
    first_request = _plan_request(cycle_id="cycle-prompt-001")
    planner = ResearchPlanner(_planner_transport)
    first_result = planner.plan(first_request)
    assert first_result.plan is not None

    replay_request = _plan_request(
        cycle_id="cycle-prompt-002",
        prior_thesis_hashes=(first_result.plan.thesis_hash,),
    )
    replay_result = planner.plan(replay_request)

    assert replay_result.decision == "rejected"
    assert replay_result.reason_codes == ("thesis_replayed",)


def test_approved_plan_is_consumed_by_creator_prompt() -> None:
    plan_result = ResearchPlanner(_planner_transport).plan(
        _plan_request(cycle_id="cycle-prompt-003")
    )
    assert plan_result.plan is not None
    request = CreatorGenerationRequest(
        research_run_id=plan_result.plan.research_run_id,
        input_evidence_refs=("bundle/hash", f"plan/{plan_result.plan.plan_hash}"),
        output_schema_id="creator-proposal-v1",
        attempt=1,
        forbidden_candidate_ids=plan_result.plan.forbidden_candidate_ids,
        research_plan=plan_result.plan,
    )

    messages = build_creator_proposal_messages(
        request,
        bundle_hash=HASH_A,
        symbol="BTCUSDT",
    )

    assert plan_result.plan.plan_hash in messages[1]["content"]
    assert plan_result.plan.hypothesis in messages[1]["content"]
    assert plan_result.plan.falsification_criteria[0] in messages[1]["content"]


def test_base_stops_when_learner_declares_no_new_hypothesis(tmp_path: Path) -> None:
    def stop_learner_transport(_request):
        return {
            "decision": "stop",
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["no_new_material_direction"],
            "recommended_novelty_dimensions": ["entry_logic"],
        }

    base = AutonomousResearchBase(
        config=AutonomousBaseConfig(
            base_run_id="base-stop-001",
            symbol="BTCUSDT",
            bundle_hash=HASH_A,
            dataset_registry_hash=HASH_B,
            artifact_root=tmp_path / "base-artifacts",
            max_cycles=2,
        ),
        learner=FailureLearner(stop_learner_transport),
        planner=ResearchPlanner(_planner_transport),
        cycle_runner=lambda _request: pytest.fail("cycle must not run"),
    )

    result = base.run(initial_feedback=_feedback(), now=NOW)

    assert result.status == "stopped"
    assert result.terminal_reason == "learner_stopped"
    assert result.cycles_executed == 0
    assert len(result.learning_hashes) == 1


def test_existing_cycle_adapter_is_offline_and_stops_before_evaluation(tmp_path: Path) -> None:
    def critic_transport(request):
        return {
            "review_id": "review-base-adapter-001",
            "research_run_id": request.research_run_id,
            "candidate_id": request.candidate_id,
            "decision": "stop",
            "failure_reason_codes": list(request.feedback.failure_reason_codes),
            "revision_actions": ["no_materially_different_direction"],
        }

    def creator_transport(_request):
        raise AssertionError("creator must not run after critic stop")

    cycle_runner = make_autonomous_cycle_runner(
        windows=(),
        qualification_policy=WalkForwardQualificationPolicy(
            policy_id="policy-base-adapter-001",
            minimum_windows=1,
            minimum_trades=1,
            minimum_profit_factor=Decimal("1.0"),
            maximum_drawdown_pct=Decimal("20.0"),
            minimum_average_return_pct=Decimal("0.0"),
        ),
        critic_transport=critic_transport,
        creator_transport=creator_transport,
    )
    base = AutonomousResearchBase(
        config=AutonomousBaseConfig(
            base_run_id="base-adapter-001",
            symbol="BTCUSDT",
            bundle_hash=HASH_A,
            dataset_registry_hash=HASH_B,
            artifact_root=tmp_path / "base-artifacts",
            max_cycles=1,
        ),
        learner=FailureLearner(_learner_transport),
        planner=ResearchPlanner(_planner_transport),
        cycle_runner=cycle_runner,
    )

    result = base.run(initial_feedback=_feedback(), now=NOW)

    assert result.status == "stopped"
    assert result.terminal_reason == "cycle_stopped"
    assert result.cycles_executed == 1
    assert result.paper_activation is False
    assert result.execution_authority is False


def test_autonomy_prompts_include_only_bounded_evidence() -> None:
    plan_request = _plan_request(cycle_id="cycle-prompt-004")
    learning_request = FailureLearningRequest(
        research_run_id="run-learning-prompt-002",
        base_run_id=plan_request.base_run_id,
        symbol=plan_request.symbol,
        bundle_hash=plan_request.bundle_hash,
        dataset_registry_hash=plan_request.dataset_registry_hash,
        cycle_index=plan_request.cycle_index,
        failure_memory=plan_request.failure_memory,
        forbidden_candidate_ids=plan_request.forbidden_candidate_ids,
        input_evidence_refs=tuple(
            ref for ref in plan_request.input_evidence_refs if ref.startswith("failure/")
        ),
    )

    learner_system, learner_user = build_failure_learning_messages(learning_request)
    planner_system, planner_user = build_research_plan_messages(plan_request)

    assert "order" in learner_system["content"].lower()
    assert "threshold" in learner_system["content"].lower()
    assert "failure_memory" in learner_user["content"]
    assert "failure_memory" in planner_user["content"]
    assert "recommended_novelty_dimensions" in planner_user["content"]
    assert "live" in planner_system["content"]


def test_base_rejects_cycle_execution_with_admission() -> None:
    result = _cycle_result(
        cycle_id="cycle-demo-001",
        candidate_id="cand-revision-001",
        qualification_hash=HASH_C,
    ).model_copy(update={"admission_decision": "admitted"})
    with pytest.raises(ValidationError):
        AutonomousBaseCycleExecution(
            result=result,
            next_feedback=_feedback(candidate_id="cand-revision-001", qualification_hash=HASH_C),
        )


def test_base_runs_two_bounded_cycles_and_preserves_full_history(tmp_path: Path) -> None:
    feedbacks = [
        _feedback(),
        _feedback(candidate_id="cand-revision-001", qualification_hash="d" * 64),
    ]
    cycle_calls: list[AutonomousBaseCycleRequest] = []

    learner = FailureLearner(_learner_transport)

    def planner_transport(request):
        payload = _planner_transport(request)
        if len(request.failure_memory) > 1:
            payload["hypothesis"] = (
                "Use an independent confirmation exit for volatile trend continuation."
            )
            payload["strategy_family"] = "experimental"
        return payload

    planner = ResearchPlanner(planner_transport)

    def cycle_runner(request: AutonomousBaseCycleRequest) -> AutonomousBaseCycleExecution:
        cycle_calls.append(request)
        index = request.sequence
        if index == 1:
            result = _cycle_result(
                cycle_id=request.cycle_id,
                candidate_id="cand-revision-001",
                qualification_hash="d" * 64,
            )
            next_feedback = feedbacks[1]
        else:
            result = _cycle_result(
                cycle_id=request.cycle_id,
                candidate_id="cand-revision-002",
                qualification_hash="e" * 64,
                qualification_decision="qualified",
            )
            next_feedback = None
        return AutonomousBaseCycleExecution(result=result, next_feedback=next_feedback)

    base = AutonomousResearchBase(
        config=AutonomousBaseConfig(
            base_run_id="base-demo-001",
            symbol="BTCUSDT",
            bundle_hash=HASH_A,
            dataset_registry_hash=HASH_B,
            artifact_root=tmp_path / "base-artifacts",
            max_cycles=3,
        ),
        learner=learner,
        planner=planner,
        cycle_runner=cycle_runner,
    )

    result = base.run(initial_feedback=feedbacks[0], now=NOW)

    assert result.status == "completed"
    assert result.cycles_executed == 2
    assert result.terminal_reason == "qualified_unadmitted"
    assert len(result.failure_memory_entry_hashes) == 2
    assert cycle_calls[0].forbidden_candidate_ids == ("cand-seed-001",)
    assert cycle_calls[1].forbidden_candidate_ids == (
        "cand-revision-001",
        "cand-seed-001",
    )
    assert len(cycle_calls[1].plan.source_failure_hashes) == 2
    assert cycle_calls[0].plan.source_failure_hashes[0] in cycle_calls[1].plan.source_failure_hashes
    assert cycle_calls[1].plan.learning_hash != cycle_calls[0].learning.learning_hash
    assert result.execution_authority is False
    assert result.paper_activation is False

    persisted = read_autonomous_base_result(tmp_path / "base-artifacts" / "base-result.json")
    assert persisted == result


def test_base_stops_when_learner_rejects_without_running_cycle(tmp_path: Path) -> None:
    calls = {"learner": 0, "planner": 0, "cycle": 0}

    def learner_transport(_request):
        calls["learner"] += 1
        return {"invalid": "schema"}

    def planner_transport(_request):
        calls["planner"] += 1
        return _planner_transport(_request)

    def cycle_runner(_request):
        calls["cycle"] += 1
        raise AssertionError("cycle runner must not be called")

    base = AutonomousResearchBase(
        config=AutonomousBaseConfig(
            base_run_id="base-blocked-001",
            symbol="BTCUSDT",
            bundle_hash=HASH_A,
            dataset_registry_hash=HASH_B,
            artifact_root=tmp_path / "base-artifacts",
            max_cycles=2,
        ),
        learner=FailureLearner(learner_transport),
        planner=ResearchPlanner(planner_transport),
        cycle_runner=cycle_runner,
    )

    result = base.run(initial_feedback=_feedback(), now=NOW)

    assert result.status == "blocked"
    assert result.terminal_reason == "learning_rejected"
    assert result.cycles_executed == 0
    assert calls == {"learner": 1, "planner": 0, "cycle": 0}


def test_base_is_idempotent_after_final_result(tmp_path: Path) -> None:
    calls = {"learner": 0, "planner": 0, "cycle": 0}

    def learner_transport(request):
        calls["learner"] += 1
        return _learner_transport(request)

    def planner_transport(request):
        calls["planner"] += 1
        return _planner_transport(request)

    def cycle_runner(request):
        calls["cycle"] += 1
        return AutonomousBaseCycleExecution(
            result=_cycle_result(
                cycle_id=request.cycle_id,
                candidate_id="cand-revision-001",
                qualification_hash="d" * 64,
                qualification_decision="qualified",
            ),
            next_feedback=None,
        )

    kwargs = dict(
        config=AutonomousBaseConfig(
            base_run_id="base-idempotent-001",
            symbol="BTCUSDT",
            bundle_hash=HASH_A,
            dataset_registry_hash=HASH_B,
            artifact_root=tmp_path / "base-artifacts",
            max_cycles=2,
        ),
        learner=FailureLearner(learner_transport),
        planner=ResearchPlanner(planner_transport),
        cycle_runner=cycle_runner,
    )
    first = AutonomousResearchBase(**kwargs).run(initial_feedback=_feedback(), now=NOW)
    second = AutonomousResearchBase(**kwargs).run(initial_feedback=_feedback(), now=NOW)

    assert second == first
    assert calls == {"learner": 1, "planner": 1, "cycle": 1}


def test_partial_run_reuses_immutable_seed_on_later_resume(tmp_path: Path) -> None:
    class ExplodingLearner:
        def __init__(self) -> None:
            self.calls = 0

        def learn(self, request):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated process interruption")
            return FailureLearner(lambda _request: {}).learn(request)

    exploding = ExplodingLearner()
    config = AutonomousBaseConfig(
        base_run_id="base-resume-seed-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path / "base-artifacts",
        max_cycles=1,
    )
    first = AutonomousResearchBase(
        config=config,
        learner=exploding,
        planner=ResearchPlanner(_planner_transport),
        cycle_runner=lambda _request: pytest.fail("cycle must not run"),
    )

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        first.run(initial_feedback=_feedback(), now=NOW)

    second = AutonomousResearchBase(
        config=config,
        learner=exploding,
        planner=ResearchPlanner(_planner_transport),
        cycle_runner=lambda _request: pytest.fail("cycle must not run"),
    ).run(initial_feedback=_feedback(), now=NOW.replace(minute=1))

    assert second.status == "blocked"
    assert second.terminal_reason == "learning_rejected"
    assert second.cycles_executed == 0


def test_partial_run_does_not_replay_uncheckpointed_provider_artifacts(tmp_path: Path) -> None:
    calls = {"learner": 0, "cycle": 0}

    def learner_transport(request):
        calls["learner"] += 1
        return _learner_transport(request)

    def cycle_runner(_request):
        calls["cycle"] += 1
        raise RuntimeError("simulated checkpoint interruption")

    config = AutonomousBaseConfig(
        base_run_id="base-orphan-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path / "base-artifacts",
        max_cycles=1,
    )
    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(learner_transport),
        planner=ResearchPlanner(_planner_transport),
        cycle_runner=cycle_runner,
    )

    with pytest.raises(RuntimeError, match="checkpoint interruption"):
        base.run(initial_feedback=_feedback(), now=NOW)

    with pytest.raises(DomainViolation, match="uncheckpointed"):
        base.run(initial_feedback=_feedback(), now=NOW.replace(minute=1))

    assert calls == {"learner": 1, "cycle": 1}
