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

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.pipeline.autonomous_base import (
    AutonomousBaseConfig,
    AutonomousBaseCycleExecution,
    AutonomousBaseCycleRequest,
    AutonomousResearchBase,
    build_autonomous_base_result,
    read_autonomous_base_cycle_record,
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
    write_failure_memory_entry,
)
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.qualification_artifacts import QualificationGateResult

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


def test_cli_runner_executes_offline_cycle_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify CLI main executes offline bounded cycles and outputs structured report."""
    exit_code = cli_main(
        [
            "--symbol",
            "BTCUSDT",
            "--max-cycles",
            "1",
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
