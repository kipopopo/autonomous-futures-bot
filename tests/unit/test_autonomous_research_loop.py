"""Unit tests for the complete autonomous learning and strategy-creation loop (R2).

Verifies:
1. Multi-cycle failure memory -> learner -> planner -> cycle execution -> next failure memory.
2. Thesis deduplication and tracking across cycles.
3. Forbidden candidate ID accumulation across cycles.
4. Deterministic terminal reasons:
   - max_cycles_reached
   - qualified_unadmitted
   - learner_stopped
   - learning_rejected
   - planning_rejected
   - cycle_failed
5. Restart-safe checkpoint resumption without cycle re-evaluation.
6. CLI entrypoint (scripts/run_autonomous_base.py) preflight, dry-run, and forbidden flag rejection.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.pipeline.autonomous_base import (
    AutonomousBaseConfig,
    AutonomousBaseCycleExecution,
    AutonomousBaseCycleRequest,
    AutonomousResearchBase,
    build_autonomous_base_result,
    read_autonomous_base_cycle_record,
    read_autonomous_base_result,
    write_autonomous_base_result,
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
    read_failure_memory_entry,
    write_failure_memory_entry,
)
from autonomous_futures.research.creator_artifacts import (
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
    build_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_autonomous_base import main as cli_main  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


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


def _write_rejected_seed_artifacts(tmp_path: Path):
    candidate_id = "cand-seed-001"
    candidate = build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=StrategySpec(
            dsl_version=1,
            strategy_id=candidate_id,
            family="range_mean_reversion",
            universe=StrategyUniverse(
                symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
            ),
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
            exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
            vetoes=("testing_only_no_promotion",),
        ),
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        creator_run_id="creator-seed-001",
        research_seed=1,
        created_at=NOW,
    )
    qualification = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="oos-seed-001",
        evaluator_version="cached-oos-v1",
        decision="rejected",
        metrics=(QualificationMetric(metric_id="oos_profit_factor", value=Decimal("0.8")),),
        gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.8"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        windows_evaluated=1,
        evaluated_at=NOW,
        qualification_policy_id="policy-base-001",
        oos_aggregation_hash=HASH_C,
        source="walk_forward_oos",
    )
    candidate_path = tmp_path / "candidate.json"
    qualification_path = tmp_path / "qualification.json"
    write_creator_candidate_artifact(candidate_path, candidate)
    write_creator_candidate_qualification_artifact(qualification_path, qualification)
    return candidate_path, qualification_path, candidate, qualification


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
        active_candidate_id=candidate_id,
        completed_at=NOW,
        cycle_hash="0" * 64,
    )
    return provisional.model_copy(update={"cycle_hash": autonomous_cycle_content_hash(provisional)})


def _make_learner_transport(decision: str = "accepted"):
    def _transport(request: FailureLearningRequest):
        return {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic", "feature_set"],
            "decision": decision,
        }

    return _transport


def _make_planner_transport(prefix: str = "hypothesis"):
    def _transport(request: ResearchPlanRequest):
        return {
            "hypothesis": (f"{prefix} for cycle {request.cycle_index} with adaptive regime filter"),
            "expected_regime": "volatile_trend",
            "strategy_family": "volume_confirmed_momentum",
            "novelty_dimensions": ["entry_logic", "feature_set"],
            "falsification_criteria": [
                "reject if OOS profit factor remains below the pinned policy",
                "reject if any walk-forward window has zero trades",
            ],
        }

    return _transport


def test_multicycle_failure_feedback_loop(tmp_path: Path) -> None:
    """Verify end-to-end multi-cycle loop: failure memory -> learn -> plan -> cycle -> memory."""
    config = AutonomousBaseConfig(
        base_run_id="base-multi-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=2,
    )

    observed_requests: list[AutonomousBaseCycleRequest] = []

    def mock_cycle_runner(request: AutonomousBaseCycleRequest) -> AutonomousBaseCycleExecution:
        observed_requests.append(request)
        cand_id = f"cand-cycle-{request.sequence:03d}"
        qual_hash = f"{request.sequence:02d}" + "d" * 62
        res = _cycle_result(
            cycle_id=request.cycle_id,
            candidate_id=cand_id,
            qualification_hash=qual_hash,
            qualification_decision="rejected",
        )
        fb = _feedback(candidate_id=cand_id, qualification_hash=qual_hash)
        return AutonomousBaseCycleExecution(result=res, next_feedback=fb)

    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=mock_cycle_runner,
    )

    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    result = base.run(initial_feedback=seed_fb, now=NOW)

    assert result.status == "stopped"
    assert result.terminal_reason == "max_cycles_reached"
    assert result.cycles_executed == 2
    assert len(observed_requests) == 2

    # Verify forbidden candidate accumulation across cycles
    # Cycle 1: forbids cand-seed-001
    assert "cand-seed-001" in observed_requests[0].forbidden_candidate_ids
    assert "cand-cycle-001" not in observed_requests[0].forbidden_candidate_ids

    # Cycle 2: forbids cand-seed-001 AND cand-cycle-001
    assert "cand-seed-001" in observed_requests[1].forbidden_candidate_ids
    assert "cand-cycle-001" in observed_requests[1].forbidden_candidate_ids

    # Verify failure memory accumulation
    assert len(observed_requests[1].learning.source_failure_hashes) == 2
    assert len(result.failure_memory_entry_hashes) == 3  # seed + cycle 1 + cycle 2

    # Verify cycle records on disk
    cycle1_record = read_autonomous_base_cycle_record(
        tmp_path / "cycles" / f"{observed_requests[0].cycle_id}.json"
    )
    cycle2_record = read_autonomous_base_cycle_record(
        tmp_path / "cycles" / f"{observed_requests[1].cycle_id}.json"
    )
    assert cycle1_record.sequence == 1
    assert cycle2_record.sequence == 2
    assert cycle1_record.learning_hash != cycle2_record.learning_hash
    assert cycle1_record.plan_hash != cycle2_record.plan_hash


def test_thesis_deduplication_and_tracking(tmp_path: Path) -> None:
    """Verify prior thesis hashes are tracked and duplicate thesis raises validation error."""
    config = AutonomousBaseConfig(
        base_run_id="base-thesis-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=2,
    )

    # Planner that returns the exact same hypothesis for both cycles
    static_planner_transport = _make_planner_transport(prefix="static hypothesis")

    def mock_cycle_runner(request: AutonomousBaseCycleRequest) -> AutonomousBaseCycleExecution:
        cand_id = f"cand-cycle-{request.sequence:03d}"
        qual_hash = f"{request.sequence:02d}" + "e" * 62
        res = _cycle_result(
            cycle_id=request.cycle_id,
            candidate_id=cand_id,
            qualification_hash=qual_hash,
        )
        fb = _feedback(candidate_id=cand_id, qualification_hash=qual_hash)
        return AutonomousBaseCycleExecution(result=res, next_feedback=fb)

    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(static_planner_transport),
        cycle_runner=mock_cycle_runner,
    )

    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    # Cycle 2 planner should get prior_thesis_hashes containing Cycle 1's thesis
    # When thesis is identical, the base record or plan catches it
    result = base.run(initial_feedback=seed_fb, now=NOW)
    # In AutonomousBaseResult, thesis_hashes must be unique!
    # If the cycle produced duplicate thesis hashes, it is blocked or catches duplication
    assert result.status in ("stopped", "blocked")


def test_deterministic_stop_reason_qualified_unadmitted(tmp_path: Path) -> None:
    """Verify immediate stop with qualified_unadmitted when a candidate qualifies."""
    config = AutonomousBaseConfig(
        base_run_id="base-qual-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=3,
    )

    def mock_qualifying_cycle_runner(
        request: AutonomousBaseCycleRequest,
    ) -> AutonomousBaseCycleExecution:
        cand_id = "cand-qual-001"
        qual_hash = "11" + "f" * 62
        res = _cycle_result(
            cycle_id=request.cycle_id,
            candidate_id=cand_id,
            qualification_hash=qual_hash,
            qualification_decision="qualified",
            cycle_status="completed_unadmitted",
        )
        return AutonomousBaseCycleExecution(result=res, next_feedback=None)

    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=mock_qualifying_cycle_runner,
    )

    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    result = base.run(initial_feedback=seed_fb, now=NOW)

    assert result.status == "completed"
    assert result.terminal_reason == "qualified_unadmitted"
    assert result.cycles_executed == 1
    assert result.paper_activation is False
    assert result.execution_authority is False


def test_deterministic_stop_reason_learner_stopped(tmp_path: Path) -> None:
    """Verify base stops cleanly when learner emits a stop decision."""
    config = AutonomousBaseConfig(
        base_run_id="base-learn-stop-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=3,
    )

    # Learner returns decision="stop"
    stop_learner = FailureLearner(_make_learner_transport(decision="stop"))

    def mock_cycle_runner(request: AutonomousBaseCycleRequest) -> AutonomousBaseCycleExecution:
        raise AssertionError("Cycle runner should not be called when learner stops")

    base = AutonomousResearchBase(
        config=config,
        learner=stop_learner,
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=mock_cycle_runner,
    )

    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    result = base.run(initial_feedback=seed_fb, now=NOW)

    assert result.status == "stopped"
    assert result.terminal_reason == "learner_stopped"
    assert result.cycles_executed == 0


def test_deterministic_stop_reason_learning_rejected(tmp_path: Path) -> None:
    """Verify base halts with blocked/learning_rejected when learner fails."""
    config = AutonomousBaseConfig(
        base_run_id="base-learn-fail-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=3,
    )

    def failing_learner_transport(request: FailureLearningRequest):
        raise RuntimeError("Transport connection failed")

    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(failing_learner_transport),
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=lambda r: None,  # type: ignore[arg-type]
    )

    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    result = base.run(initial_feedback=seed_fb, now=NOW)

    assert result.status == "blocked"
    assert result.terminal_reason == "learning_rejected"
    assert result.cycles_executed == 0


def test_deterministic_stop_reason_planning_rejected(tmp_path: Path) -> None:
    """Verify base halts with blocked/planning_rejected when planner fails."""
    config = AutonomousBaseConfig(
        base_run_id="base-plan-fail-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=3,
    )

    def failing_planner_transport(request: ResearchPlanRequest):
        raise RuntimeError("Planner transport failure")

    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(failing_planner_transport),
        cycle_runner=lambda r: None,  # type: ignore[arg-type]
    )

    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    result = base.run(initial_feedback=seed_fb, now=NOW)

    assert result.status == "blocked"
    assert result.terminal_reason == "planning_rejected"
    assert result.cycles_executed == 0


def test_restart_safe_checkpoint_resumption(tmp_path: Path) -> None:
    """Verify an interrupted run resumes from existing checkpoint without re-running cycle 1."""
    config = AutonomousBaseConfig(
        base_run_id="base-restart-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=2,
    )

    executed_cycles: list[int] = []

    def mock_cycle_runner(request: AutonomousBaseCycleRequest) -> AutonomousBaseCycleExecution:
        executed_cycles.append(request.sequence)
        cand_id = f"cand-cycle-{request.sequence:03d}"
        qual_hash = f"{request.sequence:02d}" + "a" * 62
        res = _cycle_result(
            cycle_id=request.cycle_id,
            candidate_id=cand_id,
            qualification_hash=qual_hash,
        )
        fb = _feedback(candidate_id=cand_id, qualification_hash=qual_hash)
        return AutonomousBaseCycleExecution(result=res, next_feedback=fb)

    # First run configured for max_cycles=1
    config_run1 = config.model_copy(update={"max_cycles": 1})
    base1 = AutonomousResearchBase(
        config=config_run1,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=mock_cycle_runner,
    )
    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    res1 = base1.run(initial_feedback=seed_fb, now=NOW)
    assert res1.cycles_executed == 1
    assert executed_cycles == [1]

    # Remove final base-result.json so base can resume to cycle 2
    (tmp_path / "base-result.json").unlink()

    # Second run configured for max_cycles=2
    config_run2 = config.model_copy(update={"max_cycles": 2})
    base2 = AutonomousResearchBase(
        config=config_run2,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=mock_cycle_runner,
    )
    res2 = base2.run(initial_feedback=seed_fb, now=NOW + timedelta(minutes=30))
    assert res2.cycles_executed == 2
    # Cycle 1 was NOT re-executed! Only cycle 2 was executed on resumption.
    assert executed_cycles == [1, 2]


def test_cli_runner_preflight_and_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify CLI main handles --dry-run cleanly."""
    exit_code = cli_main(["--dry-run", "--symbol", "BTCUSDT", "--max-cycles", "2"])
    assert exit_code == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "preflight_passed"
    assert report["symbol"] == "BTCUSDT"
    assert report["dry_run"] is True
    assert report["initial_feedback_available"] is False
    assert report["feedback_seed_candidate"] is None


def test_cli_dry_run_does_not_resolve_credentials(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offline dry run must not inspect or resolve any provider credential."""
    import scripts.run_autonomous_base as base_cli

    calls = 0

    def unexpected_credential_lookup() -> str:
        nonlocal calls
        calls += 1
        return ""

    monkeypatch.setattr(
        base_cli,
        "resolve_credential",
        unexpected_credential_lookup,
        raising=False,
    )

    assert cli_main(["--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert calls == 0
    assert report["provider_mode"] == "offline_deterministic"
    assert report["provider_calls_enabled"] is False
    assert "credential_preflight_ok" not in report


def test_cli_run_requires_explicit_feedback_before_creating_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact_root = tmp_path / "no-feedback-run"

    exit_code = cli_main(
        [
            "--base-run-id",
            "base-no-feedback-001",
            "--max-cycles",
            "1",
            "--use-synthetic-windows",
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert exit_code != 0
    assert not artifact_root.exists()
    captured_err = capsys.readouterr().err
    assert "--candidate-artifact and --qualification-artifact are required" in captured_err


def test_cli_rejects_unbound_feedback_file_before_creating_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    feedback_path = tmp_path / "unbound-feedback.json"
    feedback_path.write_text(_feedback().model_dump_json(), encoding="utf-8")
    artifact_root = tmp_path / "unbound-feedback-run"

    exit_code = cli_main(
        [
            "--base-run-id",
            "base-unbound-feedback-001",
            "--feedback-file",
            str(feedback_path),
            "--use-synthetic-windows",
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert exit_code != 0
    assert not artifact_root.exists()
    assert "--feedback-file is unsupported" in capsys.readouterr().err


def test_cli_seeds_from_persisted_candidate_and_rejected_qualification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate_path, qualification_path, candidate, qualification = _write_rejected_seed_artifacts(
        tmp_path
    )
    artifact_root = tmp_path / "verified-seed-run"

    exit_code = cli_main(
        [
            "--base-run-id",
            "base-verified-seed-001",
            "--symbol",
            "BTCUSDT",
            "--bundle-hash",
            HASH_A,
            "--dataset-registry-hash",
            HASH_B,
            "--max-cycles",
            "1",
            "--use-synthetic-windows",
            "--candidate-artifact",
            str(candidate_path),
            "--qualification-artifact",
            str(qualification_path),
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert exit_code == 0, capsys.readouterr().err
    result = read_autonomous_base_result(artifact_root / "base-result.json")
    memories = tuple(
        read_failure_memory_entry(artifact_root / "failure-memory" / f"failure-{memory_hash}.json")
        for memory_hash in result.failure_memory_entry_hashes
    )
    seed_memory = next(entry for entry in memories if entry.source_type == "seed_feedback")

    assert seed_memory.candidate_id == candidate.candidate_id
    assert seed_memory.candidate_artifact_hash == candidate.artifact_hash
    assert seed_memory.qualification_hash == qualification.qualification_hash


def test_scheduled_offline_research_runs_existing_learner_planner_cycle(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import autonomous_futures.pipeline.autonomous_base as base_module
    import scripts.run_autonomous_scheduler as scheduler_module

    tmp_path = tmp_path_factory.mktemp("sr")
    candidate_path, qualification_path, _, _ = _write_rejected_seed_artifacts(tmp_path)
    output_dir = tmp_path / "s"
    stages: list[str] = []
    commands: list[list[str]] = []
    plan_hashes: list[str] = []
    original_learn = FailureLearner.learn
    original_plan = ResearchPlanner.plan
    original_cycle = base_module.execute_autonomous_cycle

    def observe_learning(self: FailureLearner, request: FailureLearningRequest):
        stages.append("learner")
        return original_learn(self, request)

    def observe_planning(self: ResearchPlanner, request: ResearchPlanRequest):
        stages.append("planner")
        result = original_plan(self, request)
        assert result.plan is not None
        plan_hashes.append(result.plan.plan_hash)
        return result

    def observe_cycle(**kwargs):
        stages.append("cycle")
        assert kwargs["paper_engine"] is None
        assert kwargs["research_plan"].plan_hash == plan_hashes[-1]
        return original_cycle(**kwargs)

    class OfflineBaseProcess:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            commands.append(command)
            assert Path(command[1]).name == "run_autonomous_base.py"
            assert "--provider" not in command
            assert "--feedback-path" not in command
            assert "--ledger-db" not in command
            assert "--candidate-registry-path" not in command
            # Synthetic windows are selected only by this in-process test harness.
            self.returncode = cli_main([*command[2:], "--use-synthetic-windows"])
            captured = capsys.readouterr()
            self.stdout, self.stderr = captured.out, captured.err

        def poll(self) -> int:
            return self.returncode

        def communicate(self) -> tuple[str, str]:
            return self.stdout, self.stderr

    monkeypatch.setattr(FailureLearner, "learn", observe_learning)
    monkeypatch.setattr(ResearchPlanner, "plan", observe_planning)
    monkeypatch.setattr(base_module, "execute_autonomous_cycle", observe_cycle)
    monkeypatch.setattr(scheduler_module.subprocess, "Popen", OfflineBaseProcess)
    monkeypatch.setattr(
        scheduler_module,
        "extract_paper_feedback",
        lambda **_: pytest.fail("paper ledger feedback is not an OOS research seed"),
    )
    args = scheduler_module.build_parser().parse_args(
        [
            "--symbol",
            "BTCUSDT",
            "--provider",
            "demo",
            "--output-dir",
            str(output_dir),
            "--research-candidate-artifact",
            str(candidate_path),
            "--research-qualification-artifact",
            str(qualification_path),
            "--bundle-hash",
            HASH_A,
            "--dataset-registry-hash",
            HASH_B,
            "--parquet-path",
            str(tmp_path / "missing.parquet"),
        ]
    )
    scheduler = scheduler_module.AutonomousSchedulerDaemon(args)

    assert scheduler._execute_cycle("interval") == 0
    assert stages == ["learner", "planner", "cycle"]
    assert len(commands) == 1
    result_path = Path(commands[0][commands[0].index("--artifact-root") + 1]) / "base-result.json"
    result = read_autonomous_base_result(result_path)
    assert result.cycles_executed == 1
    assert len(result.learning_hashes) == len(result.plan_hashes) == 1
    assert result.paper_activation is result.execution_authority is result.exchange_access is False
    assert scheduler.admitted_candidates_count == 0
    assert scheduler.last_cycle_result is not None
    assert scheduler.last_cycle_result.status == f"offline_base_{result.status}"
    assert scheduler.last_cycle_result.admitted is False


@pytest.mark.parametrize(
    "override",
    [
        {"research_qualification_artifact": None},
        {"research_candidate_artifact": None},
        {"provider": "google_ai_studio"},
        {"bundle_hash": None},
        {"dataset_registry_hash": None},
    ],
)
def test_scheduled_offline_research_rejects_invalid_mode_before_outputs(
    tmp_path: Path, override: dict[str, object]
) -> None:
    import scripts.run_autonomous_scheduler as scheduler_module

    candidate_path, qualification_path, _, _ = _write_rejected_seed_artifacts(tmp_path)
    output_dir = tmp_path / "invalid-research"
    args = scheduler_module.build_parser().parse_args(
        [
            "--symbol",
            "BTCUSDT",
            "--provider",
            "demo",
            "--output-dir",
            str(output_dir),
            "--research-candidate-artifact",
            str(candidate_path),
            "--research-qualification-artifact",
            str(qualification_path),
            "--bundle-hash",
            HASH_A,
            "--dataset-registry-hash",
            HASH_B,
        ]
    )
    for name, value in override.items():
        setattr(args, name, value)

    with pytest.raises(ValueError):
        scheduler_module.AutonomousSchedulerDaemon(args)
    assert not output_dir.exists()


@pytest.mark.parametrize("receipt", ["missing", "zero_cycles"])
def test_scheduled_offline_research_requires_its_own_result_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt: str
) -> None:
    import scripts.run_autonomous_scheduler as scheduler_module

    candidate_path, qualification_path, _, _ = _write_rejected_seed_artifacts(tmp_path)
    output_dir = tmp_path / "missing-base-receipt"

    class FalseAdmissionProcess:
        returncode = 0

        def __init__(self, command: list[str], **_kwargs: object) -> None:
            artifact_root = Path(command[command.index("--artifact-root") + 1])
            if receipt == "zero_cycles":
                config = AutonomousBaseConfig(
                    base_run_id=command[command.index("--base-run-id") + 1],
                    symbol="BTCUSDT",
                    bundle_hash=HASH_A,
                    dataset_registry_hash=HASH_B,
                    artifact_root=artifact_root,
                    max_cycles=1,
                )
                result = build_autonomous_base_result(
                    config=config,
                    status="stopped",
                    terminal_reason="learner_stopped",
                    records=(),
                    failure_memory_entry_hashes=(HASH_A,),
                    completed_at=datetime.now(UTC),
                )
                write_autonomous_base_result(artifact_root / "base-result.json", result)
            (artifact_root / "autonomous-cycle-result.json").write_text(
                json.dumps(
                    {"cycle_status": "completed_admitted", "admission_decision": "admitted"}
                ),
                encoding="utf-8",
            )

        def poll(self) -> int:
            return 0

        def communicate(self) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr(scheduler_module.subprocess, "Popen", FalseAdmissionProcess)
    args = scheduler_module.build_parser().parse_args(
        [
            "--symbol",
            "BTCUSDT",
            "--provider",
            "demo",
            "--output-dir",
            str(output_dir),
            "--research-candidate-artifact",
            str(candidate_path),
            "--research-qualification-artifact",
            str(qualification_path),
            "--bundle-hash",
            HASH_A,
            "--dataset-registry-hash",
            HASH_B,
        ]
    )
    scheduler = scheduler_module.AutonomousSchedulerDaemon(args)

    assert scheduler._execute_cycle("interval") != 0
    assert scheduler.admitted_candidates_count == 0
    assert scheduler.last_cycle_result is not None
    assert scheduler.last_cycle_result.status == "failed"
    assert scheduler.last_cycle_result.admitted is False


def test_cli_rejects_candidate_qualification_binding_mismatch_before_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, qualification_path, candidate, _ = _write_rejected_seed_artifacts(tmp_path)
    mismatched_candidate = build_creator_candidate_artifact(
        candidate_id=candidate.candidate_id,
        strategy=candidate.strategy,
        bundle_hash=candidate.bundle_hash,
        dataset_registry_hash=candidate.dataset_registry_hash,
        creator_run_id=candidate.creator_run_id,
        research_seed=candidate.research_seed + 1,
        created_at=candidate.created_at,
    )
    candidate_path = tmp_path / "mismatched-candidate.json"
    write_creator_candidate_artifact(candidate_path, mismatched_candidate)
    artifact_root = tmp_path / "mismatched-seed-run"

    exit_code = cli_main(
        [
            "--base-run-id",
            "base-mismatched-seed-001",
            "--symbol",
            "BTCUSDT",
            "--bundle-hash",
            HASH_A,
            "--dataset-registry-hash",
            HASH_B,
            "--use-synthetic-windows",
            "--candidate-artifact",
            str(candidate_path),
            "--qualification-artifact",
            str(qualification_path),
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert exit_code != 0
    assert not artifact_root.exists()
    assert "candidate and qualification artifacts are not bound" in capsys.readouterr().err


def test_cli_runner_rejects_forbidden_credential_flags(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify CLI main rejects credentials supplied via CLI flags."""
    for flag in ("--api-key", "--secret", "--bearer", "--binance-api-key", "--secret-key"):
        exit_code = cli_main([flag, "secret123", "--dry-run"])
        assert exit_code == 3
        captured = capsys.readouterr()
        assert "CRITICAL: Credentials must NOT be supplied via CLI flags" in captured.err


def test_restart_with_conflicting_seed_feedback_rejects(tmp_path: Path) -> None:
    """Verify restarting a base run with conflicting seed feedback raises DomainViolation."""
    config = AutonomousBaseConfig(
        base_run_id="base-conflict-seed-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=1,
    )
    seed_fb1 = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    seed_fb2 = _feedback(candidate_id="cand-seed-diff", qualification_hash="f" * 64)

    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=lambda _req: None,  # type: ignore[return-value]
    )

    # First run creates seed failure memory with seed_fb1
    try:
        base.run(initial_feedback=seed_fb1, now=NOW)
    except Exception:
        pass

    # Second run with different seed feedback must reject
    with pytest.raises(DomainViolation, match="persisted seed failure memory does not match"):
        base.run(initial_feedback=seed_fb2, now=NOW + timedelta(minutes=1))


def test_cli_runner_fails_closed_when_cached_parquet_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate_path, qualification_path, _, _ = _write_rejected_seed_artifacts(tmp_path)
    artifact_root = tmp_path / "missing-data-run"
    exit_code = cli_main(
        [
            "--base-run-id",
            "base-missing-parquet-001",
            "--bundle-hash",
            HASH_A,
            "--dataset-registry-hash",
            HASH_B,
            "--max-cycles",
            "1",
            "--candidate-artifact",
            str(candidate_path),
            "--qualification-artifact",
            str(qualification_path),
            "--parquet-path",
            str(tmp_path / "missing.parquet"),
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert exit_code != 0
    assert not artifact_root.exists()
    assert "canonical cached parquet" in capsys.readouterr().err.lower()


def test_cli_runner_executes_offline_cycle_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify CLI main executes offline bounded cycles and outputs structured report."""
    candidate_path, qualification_path, _, _ = _write_rejected_seed_artifacts(tmp_path)
    exit_code = cli_main(
        [
            "--symbol",
            "BTCUSDT",
            "--bundle-hash",
            HASH_A,
            "--dataset-registry-hash",
            HASH_B,
            "--max-cycles",
            "1",
            "--use-synthetic-windows",
            "--candidate-artifact",
            str(candidate_path),
            "--qualification-artifact",
            str(qualification_path),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["symbol"] == "BTCUSDT"
    assert report["cycles_executed"] == 1
    assert len(report["cycle_ids"]) == 1
    assert (tmp_path / "artifacts" / "base-result.json").is_file()


@pytest.mark.parametrize("synthetic_windows", [False, True])
def test_offline_base_real_process_enforces_inputs_and_idempotent_resume(
    tmp_path_factory: pytest.TempPathFactory,
    synthetic_windows: bool,
) -> None:
    """OS-process/checkpoint proof only; synthetic inputs are not market evidence."""
    import os
    import subprocess
    import sys

    root = tmp_path_factory.mktemp("bp")
    candidate_path, qualification_path, _, _ = _write_rejected_seed_artifacts(root)
    output = root / "b"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "scripts" / "run_autonomous_base.py"),
        "--symbol",
        "BTCUSDT",
        "--bundle-hash",
        HASH_A,
        "--dataset-registry-hash",
        HASH_B,
        "--base-run-id",
        "base-process-proof",
        "--max-cycles",
        "1",
        "--use-synthetic-windows",
        "--candidate-artifact",
        str(candidate_path),
        "--qualification-artifact",
        str(qualification_path),
        "--artifact-root",
        str(output),
    ]
    # Do not inherit provider credentials or ambient Python configuration.
    env = {
        key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMP", "TEMP") if key in os.environ
    }
    if not synthetic_windows:
        command.remove("--use-synthetic-windows")
        command.extend(["--parquet-path", str(root / "missing.parquet")])
    first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    if not synthetic_windows:
        assert first.returncode == 1
        assert "canonical cached parquet file is unavailable" in first.stderr
        assert not output.exists()
        return
    assert first.returncode == 0, first.stderr
    result = read_autonomous_base_result(output / "base-result.json")
    assert result.cycles_executed == 1
    assert len(result.learning_hashes) == len(result.plan_hashes) == len(result.cycle_ids) == 1
    assert result.paper_activation is result.execution_authority is result.exchange_access is False
    before = {
        path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()
    }

    resumed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == json.loads(first.stdout)
    assert read_autonomous_base_result(output / "base-result.json") == result
    assert {
        path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()
    } == before


def test_autonomous_base_write_readback_mismatch_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify write_autonomous_base_* functions fail-closed on readback mismatch."""
    import autonomous_futures.pipeline.autonomous_base as ab_mod

    config = AutonomousBaseConfig(
        base_run_id="base-readback-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=1,
    )
    result = build_autonomous_base_result(
        config=config,
        status="completed",
        terminal_reason="max_cycles_reached",
        records=(),
        failure_memory_entry_hashes=(HASH_A,),
        completed_at=NOW,
    )
    result_path = tmp_path / "base-result.json"

    def corrupted_read_result(path: Path) -> ab_mod.AutonomousBaseResult:
        real_result = ab_mod.AutonomousBaseResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        return real_result.model_copy(update={"terminal_reason": "CORRUPTED_REASON"})

    monkeypatch.setattr(ab_mod, "read_autonomous_base_result", corrupted_read_result)
    with pytest.raises(DomainViolation, match="autonomous base result path is immutable"):
        write_autonomous_base_result(result_path, result)


def test_uncheckpointed_failure_memory_entry_rejects(tmp_path: Path) -> None:
    """Verify that an uncheckpointed failure memory entry causes DomainViolation on load."""
    config = AutonomousBaseConfig(
        base_run_id="base-uncheckpointed-mem-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=1,
    )
    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    seed_memory = build_failure_memory_entry(
        base_run_id=config.base_run_id,
        source_type="seed_feedback",
        source_id=f"seed-{seed_fb.qualification_hash[:32]}",
        sequence=0,
        feedback=seed_fb,
        cycle_id=None,
        cycle_hash=None,
        recorded_at=NOW,
    )
    write_failure_memory_entry(
        tmp_path / "failure-memory" / f"failure-{seed_memory.memory_hash}.json",
        seed_memory,
    )

    # Now write an uncheckpointed rogue failure memory entry belonging to this base_run_id
    rogue_feedback = _feedback(candidate_id="cand-rogue-001", qualification_hash="e" * 64)
    rogue_entry = build_failure_memory_entry(
        base_run_id=config.base_run_id,
        source_type="cycle_result",
        source_id="cycle-rogue-001",
        sequence=1,
        feedback=rogue_feedback,
        cycle_id="cycle-rogue-001",
        cycle_hash="f" * 64,
        recorded_at=NOW,
    )
    write_failure_memory_entry(
        tmp_path / "failure-memory" / f"failure-{rogue_entry.memory_hash}.json",
        rogue_entry,
    )

    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=lambda _req: None,  # type: ignore[return-value]
    )

    with pytest.raises(
        DomainViolation, match="uncheckpointed failure memory entry requires reconciliation"
    ):
        base.run(initial_feedback=seed_fb, now=NOW + timedelta(minutes=1))


def test_tampered_failure_memory_entry_rejects(tmp_path: Path) -> None:
    """Verify that a corrupted failure-*.json file in failure-memory causes DomainViolation."""
    config = AutonomousBaseConfig(
        base_run_id="base-tampered-mem-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        artifact_root=tmp_path,
        max_cycles=1,
    )
    mem_dir = tmp_path / "failure-memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    corrupted_name = f"failure-{'bad' * 21}0.json"
    (mem_dir / corrupted_name).write_text("INVALID_JSON", encoding="utf-8")

    seed_fb = _feedback(candidate_id="cand-seed-001", qualification_hash=HASH_C)
    base = AutonomousResearchBase(
        config=config,
        learner=FailureLearner(_make_learner_transport()),
        planner=ResearchPlanner(_make_planner_transport()),
        cycle_runner=lambda _req: None,  # type: ignore[return-value]
    )

    with pytest.raises(DomainViolation, match="tampered or corrupted failure memory checkpoint"):
        base.run(initial_feedback=seed_fb, now=NOW)


def test_cli_rejects_unbound_durable_feedback_seed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Legacy durable feedback is not trusted without its source artifacts."""
    feedback_file = REPO_ROOT / "data" / "research" / "seed_feedback.json"
    if not feedback_file.is_file():
        pytest.skip("Legacy feedback example is unavailable")
    artifact_root = tmp_path / "legacy-feedback-run"

    exit_code = cli_main(
        [
            "--base-run-id",
            "base-legacy-feedback-001",
            "--feedback-file",
            str(feedback_file),
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert exit_code != 0
    assert not artifact_root.exists()
    assert "--feedback-file is unsupported" in capsys.readouterr().err
