from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.learner_artifacts import (
    build_learner_artifact,
    write_learner_artifact,
)
from autonomous_futures.research.learner_inputs import (
    LearnerInputWindow,
    LearnerInputWindowSpec,
)
from autonomous_futures.research.learner_metric_quality_critic import (
    LearnerMetricQualityCriticRequest,
    build_learner_metric_quality_critic_evidence,
    learner_metric_quality_critic_content_hash,
    parse_learner_metric_quality_critique,
)
from autonomous_futures.research.learner_metric_quality_critic_training import (
    execute_learner_metric_quality_critic_training_with_evidence,
)
from autonomous_futures.research.learner_metric_quality_decision import (
    LearnerMetricQualityGateResult,
)
from autonomous_futures.research.learner_objectives import (
    fit_next_bar_direction,
    next_bar_direction_signals,
)
from autonomous_futures.research.learner_runs import prepare_learner_run
from autonomous_futures.research.learner_training_evidence import read_learner_training_evidence

START = datetime(2026, 9, 12, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _objective_frame(offset: int = 0) -> pd.DataFrame:
    closes = [
        Decimal(str(value)) for value in (100 + offset, 101 + offset, 100 + offset, 102 + offset)
    ]
    return pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=5 * index) for index in range(4)],
            "close": closes,
            "returns": [Decimal("0.01"), Decimal("-0.01"), Decimal("0.02"), Decimal("0.01")],
        }
    )


def test_next_bar_direction_training_is_deterministic_and_source_safe() -> None:
    first = _objective_frame()
    second = _objective_frame(10)
    first_before = first.copy(deep=True)
    second_before = second.copy(deep=True)

    output_a = fit_next_bar_direction({"ETHUSDT": second, "BTCUSDT": first})
    output_b = fit_next_bar_direction({"BTCUSDT": first, "ETHUSDT": second})

    assert output_a == output_b
    assert output_a.model_family == "next_bar_direction_bucket"
    assert output_a.learner_version == "next-bar-direction-v1"
    assert output_a.model_artifact_ref == "next-bar-direction.json"
    assert b'"objective":"next_bar_direction"' in output_a.model_bytes
    assert b'"target_definition":"close[t+1] > close[t]"' in output_a.model_bytes
    assert b'"feature_ids":["returns"]' in output_a.model_bytes
    assert first.equals(first_before)
    assert second.equals(second_before)


def test_next_bar_direction_training_rejects_missing_or_unusable_labels() -> None:
    with pytest.raises(DataQualityError, match="returns"):
        fit_next_bar_direction({"BTCUSDT": _objective_frame().drop(columns=["returns"])})

    frame = _objective_frame()
    frame["returns"] = None
    with pytest.raises(DataQualityError, match="observations"):
        fit_next_bar_direction({"BTCUSDT": frame})


def test_next_bar_direction_signals_validate_model_and_ignore_future_close() -> None:
    frame = _objective_frame()
    model = fit_next_bar_direction({"BTCUSDT": frame}).model_bytes
    changed = frame.copy(deep=True)
    changed.loc[2, "close"] = Decimal("1000000")

    original_signals = next_bar_direction_signals(model, frame)
    changed_signals = next_bar_direction_signals(model, changed)

    assert original_signals.tolist() == changed_signals.tolist()
    assert set(original_signals.tolist()).issubset({-1, 0, 1})
    with pytest.raises(DataQualityError, match="model"):
        next_bar_direction_signals(b"{}", frame)


def _candidate():
    candidate_id = "cand-critic-training-001"
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=StrategySpec(
            dsl_version=1,
            strategy_id=candidate_id,
            family="experimental",
            universe=StrategyUniverse(
                symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
            ),
            features=(FeatureRef(name="returns", lookback=1, shift=1),),
            entry=EntryExit(long="returns > 0", short="returns < 0"),
            exit=EntryExit(long="returns < 0", short="returns > 0"),
            vetoes=("testing_only_no_promotion",),
        ),
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-critic-training",
        research_seed=11,
        created_at=START,
    )


def _learner(tmp_path: Path, candidate):
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    source_bytes = b"source-learner-model"
    (model_root / "source.bin").write_bytes(source_bytes)
    return build_learner_artifact(
        candidate=candidate,
        learner_id="learner-critic-training-001",
        learner_run_id="learner-run-critic-training-001",
        learner_version="source-v1",
        model_family="linear_next_return",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=1),
        training_window_end=START,
        model_artifact_ref="source.bin",
        model_artifact_hash=hashlib.sha256(source_bytes).hexdigest(),
        created_at=START,
    )


def _input_window(learner, candidate) -> LearnerInputWindow:
    timestamps = [START + timedelta(minutes=5 * index) for index in range(6)]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(100 + index)) for index in range(6)],
            "high": [Decimal(str(101 + index)) for index in range(6)],
            "low": [Decimal(str(99 + index)) for index in range(6)],
            "close": [Decimal(str(100 + index)) for index in range(6)],
            "returns": [
                Decimal("0"),
                Decimal("0.01"),
                Decimal("0.01"),
                Decimal("-0.01"),
                Decimal("0.02"),
                Decimal("0.01"),
            ],
            "context_timestamp": timestamps,
            "context_open": [Decimal("100")] * 6,
            "context_high": [Decimal("101")] * 6,
            "context_low": [Decimal("99")] * 6,
            "context_close": [Decimal("100")] * 6,
            "context_close_time": timestamps,
            "context_available_at": timestamps,
        }
    )
    spec = LearnerInputWindowSpec(
        input_id="input-btcusdt",
        learner_id=learner.learner_id,
        learner_artifact_hash=learner.artifact_hash,
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        feature_ids=("returns",),
        time_start=START,
        time_end=START + timedelta(minutes=30),
        row_count=6,
    )
    return LearnerInputWindow(spec=spec, frame=frame)


def _critic_request_and_evidence(candidate, learner):
    failed_gate = LearnerMetricQualityGateResult(
        gate_id="window_0000_net_pnl",
        window_id="holdout-btcusdt",
        metric_id="net_pnl",
        passed=False,
        observed=Decimal("-1"),
        threshold=Decimal("0"),
        comparator="gte",
        reason_code="metric_below_threshold",
    )
    provisional = LearnerMetricQualityCriticRequest(
        critic_run_id="run-learner-quality-critic-training-001",
        decision_id="metric-quality-decision-critic-training-001",
        decision_hash="c" * 64,
        review_id="metric-quality-review-critic-training-001",
        review_hash="d" * 64,
        metric_evaluation_run_id="learner-quality-critic-metric-001",
        metric_evaluation_hash="e" * 64,
        learner_id=learner.learner_id,
        learner_artifact_hash=learner.artifact_hash,
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        policy_id="learner-quality-policy-001",
        policy_hash="f" * 64,
        failed_gates=(failed_gate,),
        failure_reason_codes=("metric_below_threshold",),
        input_evidence_refs=(
            "decision/metric-quality-decision-critic-training-001",
            "metric/learner-quality-critic-metric-001",
            "review/metric-quality-review-critic-training-001",
        ),
        request_hash="0" * 64,
    )
    request = provisional.model_copy(
        update={"request_hash": learner_metric_quality_critic_content_hash(provisional)}
    )
    critique = parse_learner_metric_quality_critique(
        {
            "review_id": "review-learner-quality-critic-training-001",
            "critic_run_id": request.critic_run_id,
            "decision_id": request.decision_id,
            "candidate_id": request.candidate_id,
            "decision": "revise",
            "failure_reason_codes": list(request.failure_reason_codes),
            "revision_actions": ["change_target_definition"],
        }
    )
    evidence = build_learner_metric_quality_critic_evidence(
        request=request,
        critique=critique,
        evidence_id="learner-quality-critic-evidence-training-001",
        created_at=START + timedelta(hours=1),
    )
    return request, evidence


def test_critic_bound_training_reuses_existing_pipeline_and_records_link(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    source_path = tmp_path / "artifacts" / "source.json"
    write_learner_artifact(source_path, learner, model_root=tmp_path / "models")
    window = _input_window(learner, candidate)
    prepared_run = prepare_learner_run(
        learner=learner,
        windows=(window,),
        run_id="run-critic-training-001",
        prepared_at=START + timedelta(hours=2),
    )
    request, critic_evidence = _critic_request_and_evidence(candidate, learner)
    observed: list[tuple[str, str, tuple[str, ...]]] = []

    def trainer(received_evidence, run, frames):
        observed.append((received_evidence.evidence_id, run.run_id, tuple(frames)))
        return fit_next_bar_direction(frames)

    link = execute_learner_metric_quality_critic_training_with_evidence(
        request=request,
        critic_evidence=critic_evidence,
        objective_id="next_bar_direction",
        prepared_run=prepared_run,
        source_learner=learner,
        candidate=candidate,
        windows=(window,),
        trainer=trainer,
        run_root=tmp_path / "runs",
        prepared_run_ref="prepared.json",
        artifact_root=tmp_path / "artifacts",
        source_learner_artifact_ref="source.json",
        output_artifact_ref="next.json",
        model_root=tmp_path / "models",
        training_evidence_root=tmp_path / "training-evidence",
        training_evidence_ref="training.json",
        link_evidence_path=tmp_path / "links" / "critic-training.json",
        artifact_created_at=START + timedelta(hours=3),
        evidence_created_at=START + timedelta(hours=3),
    )

    assert observed == [(critic_evidence.evidence_id, prepared_run.run_id, ("BTCUSDT",))]
    assert link.objective_id == "next_bar_direction"
    assert link.critic_evidence_hash == critic_evidence.evidence_hash
    assert link.training_evidence_id == "training-evidence-critic-training-001"
    assert link.output_artifact_hash
    assert link.data_source == "cached_only"
    assert link.promotion_state == "unpromoted"
    assert link.execution_authority is False
    training = read_learner_training_evidence(
        tmp_path / "training-evidence" / "training.json",
        run_root=tmp_path / "runs",
        artifact_root=tmp_path / "artifacts",
        model_root=tmp_path / "models",
        candidate=candidate,
    )
    assert training.model_family == "next_bar_direction_bucket"


def test_critic_bound_training_blocks_mismatched_evidence_before_trainer(tmp_path: Path) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    window = _input_window(learner, candidate)
    prepared_run = prepare_learner_run(
        learner=learner,
        windows=(window,),
        run_id="run-critic-training-001",
        prepared_at=START + timedelta(hours=2),
    )
    request, critic_evidence = _critic_request_and_evidence(candidate, learner)
    called = False

    def trainer(*_args):
        nonlocal called
        called = True
        raise AssertionError("trainer must not run")

    bad_request_provisional = request.model_copy(
        update={"candidate_id": "cand-other", "request_hash": "0" * 64}
    )
    bad_request = bad_request_provisional.model_copy(
        update={"request_hash": learner_metric_quality_critic_content_hash(bad_request_provisional)}
    )
    with pytest.raises(DataQualityError, match="binding"):
        execute_learner_metric_quality_critic_training_with_evidence(
            request=bad_request,
            critic_evidence=critic_evidence,
            objective_id="next_bar_direction",
            prepared_run=prepared_run,
            source_learner=learner,
            candidate=candidate,
            windows=(window,),
            trainer=trainer,
            run_root=tmp_path / "runs",
            prepared_run_ref="prepared.json",
            artifact_root=tmp_path / "artifacts",
            source_learner_artifact_ref="source.json",
            output_artifact_ref="next.json",
            model_root=tmp_path / "models",
            training_evidence_root=tmp_path / "training-evidence",
            training_evidence_ref="training.json",
            link_evidence_path=tmp_path / "links" / "critic-training.json",
            artifact_created_at=START + timedelta(hours=3),
            evidence_created_at=START + timedelta(hours=3),
        )
    assert called is False
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "training-evidence").exists()
