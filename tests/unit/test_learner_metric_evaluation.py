from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

import autonomous_futures.research.learner_metric_quality_decision as metric_quality_decision_module
import autonomous_futures.research.learner_metric_quality_review as metric_quality_review_module
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.learner_artifacts import build_learner_artifact
from autonomous_futures.research.learner_evaluation import (
    LearnerEvaluationWindow,
    LearnerEvaluationWindowSpec,
)
from autonomous_futures.research.learner_metric_evaluation import (
    CachedOnlyLearnerMetricAdapter,
    LearnerMetricWindowEvaluation,
    read_learner_metric_evaluation_run,
    write_learner_metric_evaluation_run,
)
from autonomous_futures.research.learner_metric_quality_decision import (
    LearnerMetricQualityPolicy,
    LearnerMetricQualityPolicyGate,
    build_learner_metric_quality_decision,
    evaluate_persisted_learner_metric_quality,
    learner_metric_quality_decision_content_hash,
    learner_metric_quality_policy_content_hash,
    read_learner_metric_quality_decision,
    write_learner_metric_quality_decision,
)
from autonomous_futures.research.learner_metric_quality_decision_input import (
    load_verified_learner_metric_quality_decision,
)
from autonomous_futures.research.learner_metric_quality_qualification import (
    LearnerMetricQualityQualificationEvidence,
    LearnerMetricQualityQualificationPolicy,
    build_verified_learner_metric_quality_qualification_evidence,
    learner_metric_quality_qualification_content_hash,
    read_learner_metric_quality_qualification_evidence,
    write_learner_metric_quality_qualification_evidence,
)
from autonomous_futures.research.learner_metric_quality_qualification_evidence_input import (
    load_verified_learner_metric_quality_qualification_evidence,
)
from autonomous_futures.research.learner_metric_quality_qualification_input import (
    LearnerMetricQualityQualificationInput,
    build_verified_learner_metric_quality_qualification_input,
)
from autonomous_futures.research.learner_metric_quality_review import (
    LearnerMetricQualityReviewMetric,
    LearnerMetricQualityReviewWindowResult,
    execute_learner_metric_quality_review,
    learner_metric_quality_review_content_hash,
    read_learner_metric_quality_review_evidence,
    write_learner_metric_quality_review_evidence,
)
from autonomous_futures.research.learner_metric_quality_review_input import (
    load_verified_learner_metric_quality_review,
)
from autonomous_futures.research.learner_metric_review_input import (
    load_verified_learner_metric_review_input,
    review_persisted_learner_metric_evaluation,
)
from autonomous_futures.research.trade_simulation import (
    TradeSimulationConfig,
    simulate_cached_signals,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-metric-001"
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=1, shift=1),),
        entry=EntryExit(long="returns > 0", short="returns < 0"),
        exit=EntryExit(long="returns < 0", short="returns > 0"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-learner-metric",
        research_seed=47,
        created_at=START,
    )


def _learner(tmp_path: Path, candidate=None):
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    model_bytes = b"learner-metric-model"
    (model_root / "learner-metric.bin").write_bytes(model_bytes)
    candidate = candidate or _candidate()
    return build_learner_artifact(
        candidate=candidate,
        learner_id="learner-metric-001",
        learner_run_id="learner-run-metric-001",
        learner_version="learner-v1",
        model_family="explicit_cached_signal_callback",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="learner-metric.bin",
        model_artifact_hash=hashlib.sha256(model_bytes).hexdigest(),
        created_at=START,
    )


def _frame(start: datetime = START) -> pd.DataFrame:
    opens = [
        Decimal("100"),
        Decimal("101"),
        Decimal("103"),
        Decimal("102"),
        Decimal("104"),
        Decimal("105"),
    ]
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * index) for index in range(len(opens))],
            "open": opens,
            "high": [value + Decimal("1") for value in opens],
            "low": [value - Decimal("1") for value in opens],
            "close": opens,
        }
    )


def _window(learner, window_id: str, start: datetime = START) -> LearnerEvaluationWindow:
    spec = LearnerEvaluationWindowSpec(
        window_id=window_id,
        learner_id=learner.learner_id,
        candidate_id=learner.candidate_id,
        candidate_artifact_hash=learner.candidate_artifact_hash,
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=start,
        time_end=start + timedelta(minutes=30),
    )
    return LearnerEvaluationWindow(spec=spec, frame=_frame(start))


def _config() -> TradeSimulationConfig:
    return TradeSimulationConfig(
        starting_equity=Decimal("100"),
        position_fraction=Decimal("1"),
        taker_fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )


def test_metric_adapter_runs_explicit_cached_simulation_and_calculates_metrics(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    window = _window(learner, "window-01")
    original = window.frame.copy(deep=True)
    seen_frames: list[pd.DataFrame] = []

    def simulate(received_learner, received_candidate, frame, received_window):
        assert received_learner == learner
        assert received_candidate == candidate
        assert received_window.spec.window_id == "window-01"
        seen_frames.append(frame)
        frame["signal"] = [0, 1, 0, -1, 0, 0]
        return simulate_cached_signals(frame, symbol="BTCUSDT", config=_config())

    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=simulate,
    )
    run = adapter.evaluate((window,), evaluated_at=datetime(2026, 8, 8, 13, tzinfo=UTC))

    assert run.windows[0].window_id == "window-01"
    assert isinstance(run.windows[0], LearnerMetricWindowEvaluation)
    assert run.windows[0].rows_evaluated == 6
    assert run.windows[0].metrics.trade_count == 1
    expected_pnl = Decimal("100") / Decimal("101")
    assert run.windows[0].metrics.net_pnl == expected_pnl
    assert run.windows[0].metrics.final_equity == Decimal("100") + expected_pnl
    assert run.windows[0].metrics.data_source == "cached_only"
    assert run.data_source == "cached_only"
    assert run.exchange_access is False
    assert window.frame.equals(original)
    assert "signal" not in window.frame
    assert all(frame is not window.frame for frame in seen_frames)


def test_metric_adapter_is_deterministic_and_preserves_window_order(tmp_path: Path) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    first_window = _window(learner, "window-01")
    second_window = _window(learner, "window-02", START + timedelta(minutes=30))

    def simulate(received_learner, received_candidate, frame, received_window):
        frame["signal"] = [0, 1, 0, -1, 0, 0]
        return simulate_cached_signals(frame, symbol=received_window.spec.symbol, config=_config())

    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=simulate,
    )
    first = adapter.evaluate(
        (second_window, first_window), evaluated_at=datetime(2026, 8, 8, 13, tzinfo=UTC)
    )
    second = adapter.evaluate(
        (first_window, second_window), evaluated_at=datetime(2026, 8, 8, 14, tzinfo=UTC)
    )

    assert first.evaluation_hash == second.evaluation_hash
    assert [window.window_id for window in first.windows] == ["window-01", "window-02"]
    assert first.windows[0].metrics == second.windows[0].metrics


def test_metric_adapter_rejects_result_identity_mismatch(tmp_path: Path) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)

    def simulate(received_learner, received_candidate, frame, received_window):
        frame["signal"] = [0, 1, 0, -1, 0, 0]
        return simulate_cached_signals(frame, symbol="ETHUSDT", config=_config())

    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=simulate,
    )

    with pytest.raises(DataQualityError, match="symbol"):
        adapter.evaluate((_window(learner, "window-01"),), evaluated_at=START)


def test_metric_adapter_rejects_empty_run_and_invalid_timestamp(tmp_path: Path) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=lambda received_learner, received_candidate, frame, received_window: (
            simulate_cached_signals(
                frame.assign(signal=[0, 0, 0, 0, 0, 0]),
                symbol=received_window.spec.symbol,
                config=_config(),
            )
        ),
    )

    with pytest.raises(DataQualityError, match="at least one"):
        adapter.evaluate((), evaluated_at=START)
    with pytest.raises(DataQualityError, match="timezone-aware UTC"):
        adapter.evaluate((_window(learner, "window-01"),), evaluated_at=datetime(2026, 8, 8, 13))


def _metric_run(tmp_path: Path, *, evaluated_at: datetime = datetime(2026, 8, 8, 13, tzinfo=UTC)):
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)

    def simulate(received_learner, received_candidate, frame, received_window):
        frame["signal"] = [0, 1, 0, -1, 0, 0]
        return simulate_cached_signals(frame, symbol=received_window.spec.symbol, config=_config())

    adapter = CachedOnlyLearnerMetricAdapter(
        learner=learner,
        candidate=candidate,
        evaluation_run_id="learner-metric-run-001",
        evaluation_version="learner-metric-v1",
        simulator=simulate,
    )
    return adapter.evaluate((_window(learner, "window-01"),), evaluated_at=evaluated_at)


def test_metric_evaluation_persistence_is_verified_and_write_once(tmp_path: Path) -> None:
    run = _metric_run(tmp_path)
    path = tmp_path / "evaluations" / "metric-evaluation.json"

    persisted = write_learner_metric_evaluation_run(path, run)
    assert persisted == run
    assert read_learner_metric_evaluation_run(path) == run
    assert write_learner_metric_evaluation_run(path, run) == run
    assert persisted.data_source == "cached_only"
    assert persisted.exchange_access is False

    changed_audit_time = _metric_run(
        tmp_path / "changed",
        evaluated_at=datetime(2026, 8, 8, 14, tzinfo=UTC),
    )
    assert changed_audit_time.evaluation_hash == run.evaluation_hash
    with pytest.raises(DomainViolation, match="immutable"):
        write_learner_metric_evaluation_run(path, changed_audit_time)


def test_metric_evaluation_persistence_fails_closed_on_tamper_malformed_and_missing(
    tmp_path: Path,
) -> None:
    run = _metric_run(tmp_path)
    path = tmp_path / "metric-evaluation.json"
    write_learner_metric_evaluation_run(path, run)

    tampered = path.read_text(encoding="utf-8").replace(run.evaluation_hash, "0" * 64)
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_learner_metric_evaluation_run(path)

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DataQualityError, match="invalid persisted"):
        read_learner_metric_evaluation_run(malformed_path)

    with pytest.raises(FileNotFoundError):
        read_learner_metric_evaluation_run(tmp_path / "missing.json")


def test_metric_evaluation_writer_rejects_hash_mismatch_before_filesystem_work(
    tmp_path: Path,
) -> None:
    run = _metric_run(tmp_path)
    path = tmp_path / "metric-evaluation.json"
    invalid = run.model_copy(update={"evaluation_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="hash mismatch"):
        write_learner_metric_evaluation_run(path, invalid)
    assert not path.exists()


def test_verified_metric_review_input_binds_persisted_run_before_callback(tmp_path: Path) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path / "expected", candidate)
    run = _metric_run(tmp_path / "persisted")
    path = tmp_path / "metric-evaluation.json"
    write_learner_metric_evaluation_run(path, run)
    received: list[object] = []

    def reviewer(received_run):
        received_run.windows[0].metrics.net_pnl = Decimal("999")
        received.append(received_run)
        return "observed"

    result = review_persisted_learner_metric_evaluation(
        path,
        learner=learner,
        candidate=candidate,
        reviewer=reviewer,
    )

    assert result == "observed"
    assert received[0] != run
    assert (
        load_verified_learner_metric_review_input(
            path,
            learner=learner,
            candidate=candidate,
        )
        == run
    )


def test_verified_metric_review_input_rejects_binding_and_tamper_before_callback(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path / "expected", candidate)
    run = _metric_run(tmp_path / "persisted")
    path = tmp_path / "metric-evaluation.json"
    write_learner_metric_evaluation_run(path, run)
    called = False

    def reviewer(received_run):
        nonlocal called
        called = True
        return received_run

    mismatched_candidate = candidate.model_copy(update={"bundle_hash": "c" * 64})
    with pytest.raises(DomainViolation, match="binding"):
        review_persisted_learner_metric_evaluation(
            path,
            learner=learner,
            candidate=mismatched_candidate,
            reviewer=reviewer,
        )
    assert called is False

    path.write_text(
        path.read_text(encoding="utf-8").replace(run.evaluation_hash, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        review_persisted_learner_metric_evaluation(
            path,
            learner=learner,
            candidate=candidate,
            reviewer=reviewer,
        )
    assert called is False


def test_metric_quality_review_builds_observed_only_evidence_from_verified_input(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path / "expected", candidate)
    run = _metric_run(tmp_path / "persisted")
    path = tmp_path / "metric-evaluation.json"
    write_learner_metric_evaluation_run(path, run)
    calls: list[str] = []

    def reviewer(received_run, received_window):
        calls.append(received_window.window_id)
        received_run.windows[0].metrics.net_pnl = Decimal("999")
        return LearnerMetricQualityReviewWindowResult(
            window_id=received_window.window_id,
            symbol=received_window.symbol,
            metrics=(
                LearnerMetricQualityReviewMetric(
                    metric_id="observed_net_pnl",
                    value=received_window.metrics.net_pnl,
                ),
            ),
        )

    first = execute_learner_metric_quality_review(
        path,
        learner=learner,
        candidate=candidate,
        review_id="metric-quality-review-001",
        review_version="metric-quality-v1",
        reviewer=reviewer,
        reviewed_at=START,
    )
    second = execute_learner_metric_quality_review(
        path,
        learner=learner,
        candidate=candidate,
        review_id="metric-quality-review-001",
        review_version="metric-quality-v1",
        reviewer=reviewer,
        reviewed_at=START + timedelta(hours=1),
    )

    assert calls == ["window-01", "window-01"]
    assert first.metric_evaluation_hash == run.evaluation_hash
    assert first.review_conclusion == "observed_only"
    assert first.status == "completed"
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first.promotion_state == "unpromoted"
    assert first.paper_activation is False
    assert first.execution_authority is False
    assert first.review_hash == learner_metric_quality_review_content_hash(first)
    assert first.review_hash == second.review_hash
    assert (
        load_verified_learner_metric_review_input(
            path,
            learner=learner,
            candidate=candidate,
        )
        == run
    )


def test_metric_quality_review_rejects_callback_identity_and_nonfinite_output(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    learner = _learner(tmp_path / "expected", candidate)
    run = _metric_run(tmp_path / "persisted")
    path = tmp_path / "metric-evaluation.json"
    write_learner_metric_evaluation_run(path, run)

    def wrong_identity(received_run, received_window):
        return LearnerMetricQualityReviewWindowResult(
            window_id="wrong-window",
            symbol=received_window.symbol,
            metrics=(LearnerMetricQualityReviewMetric(metric_id="observed", value=Decimal("1")),),
        )

    with pytest.raises(DataQualityError, match="identity"):
        execute_learner_metric_quality_review(
            path,
            learner=learner,
            candidate=candidate,
            review_id="metric-quality-review-001",
            review_version="metric-quality-v1",
            reviewer=wrong_identity,
            reviewed_at=START,
        )

    def nonfinite_output(received_run, received_window):
        return {
            "window_id": received_window.window_id,
            "symbol": received_window.symbol,
            "metrics": [{"metric_id": "observed", "value": "NaN"}],
        }

    with pytest.raises(DataQualityError, match="invalid quality review result"):
        execute_learner_metric_quality_review(
            path,
            learner=learner,
            candidate=candidate,
            review_id="metric-quality-review-001",
            review_version="metric-quality-v1",
            reviewer=nonfinite_output,
            reviewed_at=START,
        )


def _quality_review_evidence(tmp_path: Path, *, reviewed_at: datetime = START):
    candidate = _candidate()
    learner = _learner(tmp_path / "expected", candidate)
    run = _metric_run(tmp_path / "persisted")
    input_path = tmp_path / "metric-evaluation.json"
    write_learner_metric_evaluation_run(input_path, run)

    def reviewer(received_run, received_window):
        return LearnerMetricQualityReviewWindowResult(
            window_id=received_window.window_id,
            symbol=received_window.symbol,
            metrics=(
                LearnerMetricQualityReviewMetric(
                    metric_id="observed_net_pnl",
                    value=received_window.metrics.net_pnl,
                ),
            ),
        )

    evidence = execute_learner_metric_quality_review(
        input_path,
        learner=learner,
        candidate=candidate,
        review_id="metric-quality-review-001",
        review_version="metric-quality-v1",
        reviewer=reviewer,
        reviewed_at=reviewed_at,
    )
    return evidence


def test_metric_quality_review_persistence_is_verified_and_write_once(tmp_path: Path) -> None:
    evidence = _quality_review_evidence(tmp_path)
    path = tmp_path / "reviews" / "metric-quality-review.json"

    assert write_learner_metric_quality_review_evidence(path, evidence) == evidence
    assert read_learner_metric_quality_review_evidence(path) == evidence
    assert write_learner_metric_quality_review_evidence(path, evidence) == evidence

    changed_audit_time = _quality_review_evidence(
        tmp_path / "changed",
        reviewed_at=START + timedelta(hours=1),
    )
    assert changed_audit_time.review_hash == evidence.review_hash
    with pytest.raises(DomainViolation, match="immutable"):
        write_learner_metric_quality_review_evidence(path, changed_audit_time)


def test_metric_quality_review_persistence_fails_closed_on_missing_malformed_and_tampered(
    tmp_path: Path,
) -> None:
    evidence = _quality_review_evidence(tmp_path)
    path = tmp_path / "metric-quality-review.json"
    write_learner_metric_quality_review_evidence(path, evidence)

    path.write_text(
        path.read_text(encoding="utf-8").replace(evidence.review_hash, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_learner_metric_quality_review_evidence(path)

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DataQualityError, match="invalid persisted"):
        read_learner_metric_quality_review_evidence(malformed_path)

    with pytest.raises(FileNotFoundError):
        read_learner_metric_quality_review_evidence(tmp_path / "missing.json")


def test_metric_quality_review_writer_rejects_hash_mismatch_before_filesystem_work(
    tmp_path: Path,
) -> None:
    evidence = _quality_review_evidence(tmp_path)
    path = tmp_path / "metric-quality-review.json"
    invalid = evidence.model_copy(update={"review_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="hash mismatch"):
        write_learner_metric_quality_review_evidence(path, invalid)
    assert not path.exists()


def test_metric_quality_review_writer_cleans_unique_temp_file_on_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _quality_review_evidence(tmp_path)
    path = tmp_path / "metric-quality-review.json"

    def fail_link(source, destination):
        raise OSError("link failed")

    monkeypatch.setattr(metric_quality_review_module.os, "link", fail_link)
    with pytest.raises(OSError, match="link failed"):
        write_learner_metric_quality_review_evidence(path, evidence)
    assert not path.exists()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def _persisted_quality_review_fixture(tmp_path: Path):
    candidate = _candidate()
    learner = _learner(tmp_path / "expected", candidate)
    run = _metric_run(tmp_path / "persisted")
    metric_path = tmp_path / "metric-evaluation.json"
    write_learner_metric_evaluation_run(metric_path, run)
    evidence = _quality_review_evidence(tmp_path / "review")
    review_path = tmp_path / "review-evidence.json"
    write_learner_metric_quality_review_evidence(review_path, evidence)
    return review_path, metric_path, learner, candidate, run, evidence


def test_verified_persisted_metric_quality_review_loader_binds_full_chain(
    tmp_path: Path,
) -> None:
    review_path, metric_path, learner, candidate, run, evidence = _persisted_quality_review_fixture(
        tmp_path
    )
    metric_bytes = metric_path.read_bytes()
    review_bytes = review_path.read_bytes()

    loaded = load_verified_learner_metric_quality_review(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
    )

    assert loaded == evidence
    assert loaded.metric_evaluation_run_id == run.evaluation_run_id
    assert loaded.metric_evaluation_hash == run.evaluation_hash
    assert metric_path.read_bytes() == metric_bytes
    assert review_path.read_bytes() == review_bytes


def test_verified_persisted_metric_quality_review_loader_rejects_binding_and_tamper(
    tmp_path: Path,
) -> None:
    review_path, metric_path, learner, candidate, run, evidence = _persisted_quality_review_fixture(
        tmp_path
    )
    called_candidate = candidate.model_copy(update={"bundle_hash": "c" * 64})
    with pytest.raises(DomainViolation, match="binding"):
        load_verified_learner_metric_quality_review(
            review_path,
            metric_path,
            learner=learner,
            candidate=called_candidate,
        )

    review_path.write_text(
        review_path.read_text(encoding="utf-8").replace(evidence.review_hash, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        load_verified_learner_metric_quality_review(
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
        )


def test_verified_persisted_metric_quality_review_loader_rejects_review_run_and_window_drift(
    tmp_path: Path,
) -> None:
    review_path, metric_path, learner, candidate, run, evidence = _persisted_quality_review_fixture(
        tmp_path
    )
    drifted = evidence.model_copy(update={"metric_evaluation_hash": "c" * 64})
    drifted = drifted.model_copy(
        update={"review_hash": learner_metric_quality_review_content_hash(drifted)}
    )
    drift_path = tmp_path / "drifted-review.json"
    write_learner_metric_quality_review_evidence(drift_path, drifted)
    with pytest.raises(DomainViolation, match="binding"):
        load_verified_learner_metric_quality_review(
            drift_path,
            metric_path,
            learner=learner,
            candidate=candidate,
        )

    window = evidence.windows[0].model_copy(update={"symbol": "ETHUSDT"})
    window_drift = evidence.model_copy(update={"windows": (window,)})
    window_drift = window_drift.model_copy(
        update={"review_hash": learner_metric_quality_review_content_hash(window_drift)}
    )
    window_path = tmp_path / "window-drift-review.json"
    write_learner_metric_quality_review_evidence(window_path, window_drift)
    with pytest.raises(DomainViolation, match="window"):
        load_verified_learner_metric_quality_review(
            window_path,
            metric_path,
            learner=learner,
            candidate=candidate,
        )


def _quality_policy(metric_id: str, threshold: Decimal) -> LearnerMetricQualityPolicy:
    return LearnerMetricQualityPolicy(
        policy_id="metric-quality-policy-v1",
        minimum_windows=1,
        gates=(
            LearnerMetricQualityPolicyGate(
                metric_id=metric_id,
                comparator="gte",
                threshold=threshold,
            ),
        ),
    )


def test_metric_quality_decision_uses_verified_persisted_review_and_is_observational(
    tmp_path: Path,
) -> None:
    review_path, metric_path, learner, candidate, run, evidence = _persisted_quality_review_fixture(
        tmp_path
    )
    policy = _quality_policy("observed_net_pnl", Decimal("-1"))

    decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        evaluated_at=START,
    )

    assert decision.decision == "passed"
    assert decision.review_id == evidence.review_id
    assert decision.review_hash == evidence.review_hash
    assert decision.metric_evaluation_run_id == run.evaluation_run_id
    assert decision.metric_evaluation_hash == run.evaluation_hash
    assert decision.policy_id == policy.policy_id
    assert decision.policy_hash == learner_metric_quality_policy_content_hash(policy)
    assert all(gate.passed for gate in decision.gates)
    assert decision.data_source == "cached_only"
    assert decision.exchange_access is False
    assert decision.promotion_state == "unpromoted"
    assert decision.paper_activation is False
    assert decision.execution_authority is False


def test_metric_quality_decision_rejects_missing_or_below_threshold_observations(
    tmp_path: Path,
) -> None:
    review_path, metric_path, learner, candidate, run, _ = _persisted_quality_review_fixture(
        tmp_path
    )
    below = _quality_policy("observed_net_pnl", Decimal("999"))
    missing = _quality_policy("missing_observation", Decimal("0"))

    below_decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=below,
        evaluated_at=START,
    )
    missing_decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=missing,
        evaluated_at=START,
    )

    assert below_decision.decision == "failed"
    assert any(gate.reason_code == "metric_below_threshold" for gate in below_decision.gates)
    assert missing_decision.decision == "failed"
    assert any(gate.reason_code == "metric_missing" for gate in missing_decision.gates)


def test_metric_quality_decision_hash_is_deterministic_and_tamper_fails_before_build(
    tmp_path: Path,
) -> None:
    review_path, metric_path, learner, candidate, _, evidence = _persisted_quality_review_fixture(
        tmp_path
    )
    policy = _quality_policy("observed_net_pnl", Decimal("-1"))
    first = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        evaluated_at=START,
    )
    second = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        evaluated_at=START + timedelta(hours=1),
    )
    assert first.decision_hash == second.decision_hash
    assert first.review_hash == evidence.review_hash

    review_path.write_text(
        review_path.read_text(encoding="utf-8").replace(evidence.review_hash, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        evaluate_persisted_learner_metric_quality(
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            policy=policy,
            evaluated_at=START,
        )


def test_metric_quality_decision_builder_rejects_non_utc_and_preserves_policy_contract(
    tmp_path: Path,
) -> None:
    _, _, _, _, _, evidence = _persisted_quality_review_fixture(tmp_path)
    policy = _quality_policy("observed_net_pnl", Decimal("-1"))

    with pytest.raises(DataQualityError, match="UTC"):
        build_learner_metric_quality_decision(
            evidence,
            policy=policy,
            evaluated_at=datetime(2026, 8, 8, 12),
        )


def _metric_quality_decision_evidence(
    tmp_path: Path,
    *,
    evaluated_at: datetime = START,
):
    review_path, metric_path, learner, candidate, _, _ = _persisted_quality_review_fixture(tmp_path)
    policy = _quality_policy("observed_net_pnl", Decimal("-1"))
    return evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        evaluated_at=evaluated_at,
    )


def test_metric_quality_decision_persistence_is_verified_and_write_once(tmp_path: Path) -> None:
    evidence = _metric_quality_decision_evidence(tmp_path)
    path = tmp_path / "decisions" / "metric-quality-decision.json"

    assert write_learner_metric_quality_decision(path, evidence) == evidence
    assert read_learner_metric_quality_decision(path) == evidence
    assert write_learner_metric_quality_decision(path, evidence) == evidence
    assert evidence.decision_hash == learner_metric_quality_decision_content_hash(evidence)

    changed_audit_time = _metric_quality_decision_evidence(
        tmp_path / "changed",
        evaluated_at=START + timedelta(hours=1),
    )
    assert changed_audit_time.decision_hash == evidence.decision_hash
    with pytest.raises(DomainViolation, match="immutable"):
        write_learner_metric_quality_decision(path, changed_audit_time)


def test_metric_quality_decision_persistence_fails_closed_on_missing_malformed_and_tampered(
    tmp_path: Path,
) -> None:
    evidence = _metric_quality_decision_evidence(tmp_path)
    path = tmp_path / "metric-quality-decision.json"
    write_learner_metric_quality_decision(path, evidence)

    path.write_text(
        path.read_text(encoding="utf-8").replace(evidence.decision_hash, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_learner_metric_quality_decision(path)

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DataQualityError, match="invalid persisted"):
        read_learner_metric_quality_decision(malformed_path)

    with pytest.raises(FileNotFoundError):
        read_learner_metric_quality_decision(tmp_path / "missing.json")


def test_metric_quality_decision_writer_rejects_hash_mismatch_before_filesystem_work(
    tmp_path: Path,
) -> None:
    evidence = _metric_quality_decision_evidence(tmp_path)
    path = tmp_path / "metric-quality-decision.json"
    invalid = evidence.model_copy(update={"decision_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="hash mismatch"):
        write_learner_metric_quality_decision(path, invalid)
    assert not path.exists()


def test_metric_quality_decision_writer_cleans_unique_temp_file_on_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _metric_quality_decision_evidence(tmp_path)
    path = tmp_path / "metric-quality-decision.json"

    def fail_link(source, destination):
        raise OSError("link failed")

    monkeypatch.setattr(metric_quality_decision_module.os, "link", fail_link)
    with pytest.raises(OSError, match="link failed"):
        write_learner_metric_quality_decision(path, evidence)
    assert not path.exists()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def _persisted_metric_quality_decision_fixture(tmp_path: Path):
    review_path, metric_path, learner, candidate, _, _ = _persisted_quality_review_fixture(
        tmp_path / "source"
    )
    policy = _quality_policy("observed_net_pnl", Decimal("-1"))
    decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        evaluated_at=START,
    )
    decision_path = tmp_path / "decision.json"
    write_learner_metric_quality_decision(decision_path, decision)
    return decision_path, review_path, metric_path, learner, candidate, policy, decision


def test_verified_metric_quality_decision_loader_binds_full_chain_and_preserves_bytes(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, decision = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    decision_bytes = decision_path.read_bytes()
    review_bytes = review_path.read_bytes()
    metric_bytes = metric_path.read_bytes()

    loaded = load_verified_learner_metric_quality_decision(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
    )

    assert loaded == decision
    assert decision_path.read_bytes() == decision_bytes
    assert review_path.read_bytes() == review_bytes
    assert metric_path.read_bytes() == metric_bytes


def test_verified_metric_quality_decision_loader_rejects_policy_drift(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    drifted_policy = _quality_policy("observed_net_pnl", Decimal("-2"))
    assert drifted_policy.policy_id == policy.policy_id

    with pytest.raises(DomainViolation, match="policy"):
        load_verified_learner_metric_quality_decision(
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            policy=drifted_policy,
        )


def test_verified_metric_quality_decision_loader_recomputes_valid_hash_semantics(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, decision = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    semantically_drifted = decision.model_copy(update={"decision": "failed"})
    semantically_drifted = semantically_drifted.model_copy(
        update={"decision_hash": learner_metric_quality_decision_content_hash(semantically_drifted)}
    )
    drifted_decision_path = tmp_path / "drifted-decision.json"
    write_learner_metric_quality_decision(drifted_decision_path, semantically_drifted)

    with pytest.raises(DomainViolation, match="decision"):
        load_verified_learner_metric_quality_decision(
            drifted_decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            policy=policy,
        )


def test_metric_quality_qualification_input_preserves_passed_decision_without_qualifying(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    decision_bytes = decision_path.read_bytes()
    review_bytes = review_path.read_bytes()
    metric_bytes = metric_path.read_bytes()

    first = build_verified_learner_metric_quality_qualification_input(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        prepared_at=START,
    )
    second = build_verified_learner_metric_quality_qualification_input(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        prepared_at=START + timedelta(hours=1),
    )

    assert isinstance(first, LearnerMetricQualityQualificationInput)
    assert first.decision == "passed"
    assert first.qualification_status == "not_evaluated"
    assert first.input_hash == second.input_hash
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first.promotion_state == "unpromoted"
    assert first.paper_activation is False
    assert first.execution_authority is False
    assert decision_path.read_bytes() == decision_bytes
    assert review_path.read_bytes() == review_bytes
    assert metric_path.read_bytes() == metric_bytes


def test_metric_quality_qualification_input_preserves_failed_decision(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, _, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    failed_policy = _quality_policy("observed_net_pnl", Decimal("999"))
    failed_decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=failed_policy,
        evaluated_at=START,
    )
    failed_path = tmp_path / "failed-decision.json"
    write_learner_metric_quality_decision(failed_path, failed_decision)

    handoff = build_verified_learner_metric_quality_qualification_input(
        failed_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=failed_policy,
        prepared_at=START,
    )

    assert handoff.decision == "failed"
    assert handoff.qualification_status == "not_evaluated"
    assert handoff.promotion_state == "unpromoted"
    assert handoff.execution_authority is False


def test_metric_quality_qualification_input_rejects_non_utc_prepared_at(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )

    with pytest.raises(DataQualityError, match="prepared_at"):
        build_verified_learner_metric_quality_qualification_input(
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            policy=policy,
            prepared_at=START.replace(tzinfo=None),
        )


def _metric_quality_qualification_policy(
    source_policy: LearnerMetricQualityPolicy,
    *,
    minimum_windows: int = 1,
) -> LearnerMetricQualityQualificationPolicy:
    return LearnerMetricQualityQualificationPolicy(
        policy_id="metric-quality-qualification-policy-v1",
        required_metric_quality_policy_id=source_policy.policy_id,
        required_metric_quality_policy_hash=learner_metric_quality_policy_content_hash(
            source_policy
        ),
        minimum_windows=minimum_windows,
    )


def test_verified_metric_quality_qualification_evidence_is_deterministic_and_unpromoted(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    qualification_policy = _metric_quality_qualification_policy(source_policy)
    decision_bytes = decision_path.read_bytes()
    review_bytes = review_path.read_bytes()
    metric_bytes = metric_path.read_bytes()

    first = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
        evaluated_at=START,
    )
    second = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
        evaluated_at=START + timedelta(hours=1),
    )

    assert isinstance(first, LearnerMetricQualityQualificationEvidence)
    assert first.decision == "qualified"
    assert first.source_decision == "passed"
    assert first.qualification_hash == second.qualification_hash
    assert first.qualification_policy_id == qualification_policy.policy_id
    assert all(gate.passed for gate in first.gates)
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first.promotion_state == "unpromoted"
    assert first.paper_activation is False
    assert first.execution_authority is False
    assert decision_path.read_bytes() == decision_bytes
    assert review_path.read_bytes() == review_bytes
    assert metric_path.read_bytes() == metric_bytes


def test_verified_metric_quality_qualification_evidence_rejects_failed_source_decision(
    tmp_path: Path,
) -> None:
    fixture = _persisted_metric_quality_decision_fixture(tmp_path)
    _, review_path, metric_path, learner, candidate, _, _ = fixture
    failed_source_policy = _quality_policy("observed_net_pnl", Decimal("999"))
    failed_source_decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=failed_source_policy,
        evaluated_at=START,
    )
    failed_decision_path = tmp_path / "failed-decision.json"
    write_learner_metric_quality_decision(failed_decision_path, failed_source_decision)

    evidence = build_verified_learner_metric_quality_qualification_evidence(
        failed_decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=failed_source_policy,
        qualification_policy=_metric_quality_qualification_policy(failed_source_policy),
        evaluated_at=START,
    )

    assert evidence.decision == "rejected"
    assert evidence.source_decision == "failed"
    assert any(gate.reason_code == "metric_quality_decision_not_passed" for gate in evidence.gates)
    assert evidence.promotion_state == "unpromoted"
    assert evidence.execution_authority is False


def test_verified_metric_quality_qualification_evidence_rejects_insufficient_windows(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )

    evidence = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=_metric_quality_qualification_policy(source_policy, minimum_windows=2),
        evaluated_at=START,
    )

    assert evidence.source_decision == "passed"
    assert evidence.decision == "rejected"
    assert any(gate.reason_code == "minimum_windows_below_threshold" for gate in evidence.gates)
    assert evidence.promotion_state == "unpromoted"
    assert evidence.execution_authority is False


def test_verified_metric_quality_qualification_evidence_rejects_source_policy_binding_drift(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    drifted_qualification_policy = LearnerMetricQualityQualificationPolicy(
        policy_id="metric-quality-qualification-policy-v1",
        required_metric_quality_policy_id=source_policy.policy_id,
        required_metric_quality_policy_hash="c" * 64,
        minimum_windows=1,
    )

    with pytest.raises(DomainViolation, match="source policy"):
        build_verified_learner_metric_quality_qualification_evidence(
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            source_policy=source_policy,
            qualification_policy=drifted_qualification_policy,
            evaluated_at=START,
        )


def test_verified_metric_quality_qualification_evidence_rejects_non_utc_audit_time(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )

    with pytest.raises(DataQualityError, match="evaluated_at"):
        build_verified_learner_metric_quality_qualification_evidence(
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            source_policy=source_policy,
            qualification_policy=_metric_quality_qualification_policy(source_policy),
            evaluated_at=START.replace(tzinfo=None),
        )


def _metric_quality_qualification_evidence(tmp_path: Path):
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    evidence = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=_metric_quality_qualification_policy(source_policy),
        evaluated_at=START,
    )
    return evidence


def test_metric_quality_qualification_evidence_persistence_round_trips_verified_evidence(
    tmp_path: Path,
) -> None:
    evidence = _metric_quality_qualification_evidence(tmp_path)
    path = tmp_path / "qualifications" / "metric-quality-qualification.json"

    assert write_learner_metric_quality_qualification_evidence(path, evidence) == evidence
    assert read_learner_metric_quality_qualification_evidence(path) == evidence


def test_metric_quality_qualification_evidence_persistence_is_idempotent_and_write_once(
    tmp_path: Path,
) -> None:
    evidence = _metric_quality_qualification_evidence(tmp_path)
    path = tmp_path / "metric-quality-qualification.json"

    assert write_learner_metric_quality_qualification_evidence(path, evidence) == evidence
    assert write_learner_metric_quality_qualification_evidence(path, evidence) == evidence

    changed_audit_time = evidence.model_copy(update={"evaluated_at": START + timedelta(hours=1)})
    assert changed_audit_time.qualification_hash == evidence.qualification_hash
    with pytest.raises(DomainViolation, match="immutable"):
        write_learner_metric_quality_qualification_evidence(path, changed_audit_time)


def test_metric_quality_qualification_persistence_fails_closed_for_bad_files(
    tmp_path: Path,
) -> None:
    evidence = _metric_quality_qualification_evidence(tmp_path)
    path = tmp_path / "metric-quality-qualification.json"
    write_learner_metric_quality_qualification_evidence(path, evidence)

    path.write_text(
        path.read_text(encoding="utf-8").replace(evidence.qualification_hash, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_learner_metric_quality_qualification_evidence(path)

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DataQualityError, match="invalid persisted"):
        read_learner_metric_quality_qualification_evidence(malformed_path)

    with pytest.raises(FileNotFoundError):
        read_learner_metric_quality_qualification_evidence(tmp_path / "missing.json")


def test_metric_quality_qualification_writer_rejects_hash_mismatch_before_filesystem_work(
    tmp_path: Path,
) -> None:
    evidence = _metric_quality_qualification_evidence(tmp_path)
    path = tmp_path / "new" / "metric-quality-qualification.json"
    invalid = evidence.model_copy(update={"qualification_hash": "0" * 64})

    with pytest.raises(DomainViolation, match="hash mismatch"):
        write_learner_metric_quality_qualification_evidence(path, invalid)
    assert not path.parent.exists()


def test_metric_quality_qualification_writer_cleans_temp_file_on_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _metric_quality_qualification_evidence(tmp_path)
    path = tmp_path / "metric-quality-qualification.json"

    def fail_link(source, destination):
        raise OSError("link failed")

    monkeypatch.setattr(
        "autonomous_futures.research.learner_metric_quality_qualification.os.link",
        fail_link,
    )
    with pytest.raises(OSError, match="link failed"):
        write_learner_metric_quality_qualification_evidence(path, evidence)
    assert not path.exists()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_metric_quality_qualification_persistence_preserves_rejected_evidence(
    tmp_path: Path,
) -> None:
    fixture = _persisted_metric_quality_decision_fixture(tmp_path)
    _, review_path, metric_path, learner, candidate, _, _ = fixture
    source_policy = _quality_policy("observed_net_pnl", Decimal("999"))
    source_decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=source_policy,
        evaluated_at=START,
    )
    decision_path = tmp_path / "rejected-decision.json"
    write_learner_metric_quality_decision(decision_path, source_decision)
    rejected = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=_metric_quality_qualification_policy(source_policy),
        evaluated_at=START,
    )
    path = tmp_path / "rejected-qualification.json"

    assert rejected.decision == "rejected"
    assert write_learner_metric_quality_qualification_evidence(path, rejected) == rejected
    assert read_learner_metric_quality_qualification_evidence(path).decision == "rejected"


def test_verified_persisted_metric_quality_qualification_loader_returns_full_chain_evidence(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    qualification_policy = _metric_quality_qualification_policy(source_policy)
    evidence = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
        evaluated_at=START,
    )
    qualification_path = tmp_path / "metric-quality-qualification.json"
    write_learner_metric_quality_qualification_evidence(qualification_path, evidence)
    qualification_bytes = qualification_path.read_bytes()
    decision_bytes = decision_path.read_bytes()
    review_bytes = review_path.read_bytes()
    metric_bytes = metric_path.read_bytes()

    loaded = load_verified_learner_metric_quality_qualification_evidence(
        qualification_path,
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
    )

    assert loaded == evidence
    assert qualification_path.read_bytes() == qualification_bytes
    assert decision_path.read_bytes() == decision_bytes
    assert review_path.read_bytes() == review_bytes
    assert metric_path.read_bytes() == metric_bytes


def test_verified_persisted_metric_quality_qualification_loader_rejects_policy_drift(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    qualification_policy = _metric_quality_qualification_policy(source_policy)
    evidence = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
        evaluated_at=START,
    )
    qualification_path = tmp_path / "metric-quality-qualification.json"
    write_learner_metric_quality_qualification_evidence(qualification_path, evidence)
    drifted_policy = _metric_quality_qualification_policy(source_policy, minimum_windows=2)
    assert drifted_policy.policy_id == qualification_policy.policy_id

    with pytest.raises(DomainViolation, match="qualification policy binding"):
        load_verified_learner_metric_quality_qualification_evidence(
            qualification_path,
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            source_policy=source_policy,
            qualification_policy=drifted_policy,
        )


def test_verified_persisted_metric_quality_qualification_loader_rejects_valid_hash_semantic_drift(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    qualification_policy = _metric_quality_qualification_policy(source_policy)
    evidence = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
        evaluated_at=START,
    )
    semantic_drift = evidence.model_copy(update={"windows_evaluated": 2})
    semantic_drift = semantic_drift.model_copy(
        update={
            "qualification_hash": learner_metric_quality_qualification_content_hash(semantic_drift)
        }
    )
    drifted_path = tmp_path / "semantic-drift-qualification.json"
    write_learner_metric_quality_qualification_evidence(drifted_path, semantic_drift)

    with pytest.raises(DomainViolation, match="qualification evidence binding"):
        load_verified_learner_metric_quality_qualification_evidence(
            drifted_path,
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            source_policy=source_policy,
            qualification_policy=qualification_policy,
        )


def test_verified_persisted_metric_quality_qualification_loader_rejects_source_policy_drift(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, _ = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    qualification_policy = _metric_quality_qualification_policy(source_policy)
    evidence = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
        evaluated_at=START,
    )
    qualification_path = tmp_path / "metric-quality-qualification.json"
    write_learner_metric_quality_qualification_evidence(qualification_path, evidence)
    drifted_source_policy = _quality_policy("observed_net_pnl", Decimal("-2"))
    assert drifted_source_policy.policy_id == source_policy.policy_id

    with pytest.raises(DomainViolation, match="decision policy binding"):
        load_verified_learner_metric_quality_qualification_evidence(
            qualification_path,
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            source_policy=drifted_source_policy,
            qualification_policy=qualification_policy,
        )


def test_verified_persisted_metric_quality_qualification_loader_rejects_tampered_decision(
    tmp_path: Path,
) -> None:
    decision_path, review_path, metric_path, learner, candidate, source_policy, decision = (
        _persisted_metric_quality_decision_fixture(tmp_path)
    )
    qualification_policy = _metric_quality_qualification_policy(source_policy)
    evidence = build_verified_learner_metric_quality_qualification_evidence(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        source_policy=source_policy,
        qualification_policy=qualification_policy,
        evaluated_at=START,
    )
    qualification_path = tmp_path / "metric-quality-qualification.json"
    write_learner_metric_quality_qualification_evidence(qualification_path, evidence)
    decision_path.write_text(
        decision_path.read_text(encoding="utf-8").replace(decision.decision_hash, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(DomainViolation, match="hash mismatch"):
        load_verified_learner_metric_quality_qualification_evidence(
            qualification_path,
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            source_policy=source_policy,
            qualification_policy=qualification_policy,
        )
