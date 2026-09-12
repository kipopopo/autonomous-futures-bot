from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.google_ai_studio_provider import (
    GoogleAIStudioJsonClient,
    GoogleAIStudioProviderConfig,
)
from autonomous_futures.research.learner_artifacts import build_learner_artifact
from autonomous_futures.research.learner_metric_evaluation import (
    LearnerMetricEvaluationRun,
    LearnerMetricWindowEvaluation,
    learner_metric_evaluation_content_hash,
    write_learner_metric_evaluation_run,
)
from autonomous_futures.research.learner_metric_quality_critic import (
    LearnerMetricQualityCritic,
    LearnerMetricQualityCritiqueEvidence,
    build_learner_metric_quality_critic_evidence,
    build_verified_learner_metric_quality_critic_request,
    learner_metric_quality_critic_content_hash,
    learner_metric_quality_critic_evidence_content_hash,
    parse_learner_metric_quality_critique,
    persist_learner_metric_quality_critic_evidence,
    read_learner_metric_quality_critic_evidence,
)
from autonomous_futures.research.learner_metric_quality_critic_provider import (
    GoogleAIStudioLearnerMetricQualityCriticTransport,
    build_learner_metric_quality_critic_messages,
)
from autonomous_futures.research.learner_metric_quality_decision import (
    LearnerMetricQualityPolicy,
    LearnerMetricQualityPolicyGate,
    evaluate_persisted_learner_metric_quality,
    write_learner_metric_quality_decision,
)
from autonomous_futures.research.learner_metric_quality_review import (
    LearnerMetricQualityReviewMetric,
    LearnerMetricQualityReviewWindowResult,
    execute_learner_metric_quality_review,
    write_learner_metric_quality_review_evidence,
)
from autonomous_futures.research.performance_metrics import TradePerformanceMetrics

START = datetime(2026, 9, 12, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-quality-critic-001"
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
        creator_run_id="creator-run-learner-quality-critic",
        research_seed=7,
        created_at=START,
    )


def _learner(tmp_path: Path, candidate):
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    model_bytes = b"learner-quality-critic-source"
    model_path = model_root / "source.bin"
    model_path.write_bytes(model_bytes)
    return build_learner_artifact(
        candidate=candidate,
        learner_id="learner-quality-critic-001",
        learner_run_id="learner-run-quality-critic-001",
        learner_version="learner-v1",
        model_family="linear_next_return",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="source.bin",
        model_artifact_hash=hashlib.sha256(model_bytes).hexdigest(),
        created_at=START,
    )


def _metric_run(learner, candidate):
    metrics = TradePerformanceMetrics(
        symbol="BTCUSDT",
        starting_equity=Decimal("100"),
        final_equity=Decimal("99"),
        trade_count=1,
        winning_trades=0,
        losing_trades=1,
        breakeven_trades=0,
        win_rate=Decimal("0"),
        gross_profit=Decimal("0"),
        gross_loss=Decimal("1"),
        net_pnl=Decimal("-1"),
        average_trade_pnl=Decimal("-1"),
        return_pct=Decimal("-1"),
        profit_factor=Decimal("0"),
        max_drawdown=Decimal("1"),
        max_drawdown_pct=Decimal("1"),
        peak_equity=Decimal("100"),
    )
    window = LearnerMetricWindowEvaluation(
        window_id="holdout-btcusdt",
        learner_id=learner.learner_id,
        candidate_id=candidate.candidate_id,
        symbol="BTCUSDT",
        time_start=START,
        time_end=START + timedelta(minutes=30),
        rows_evaluated=6,
        metrics=metrics,
    )
    run = LearnerMetricEvaluationRun(
        learner_id=learner.learner_id,
        learner_artifact_hash=learner.artifact_hash,
        candidate_id=candidate.candidate_id,
        candidate_artifact_hash=candidate.artifact_hash,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        evaluation_run_id="learner-quality-critic-metric-001",
        evaluation_version_name="learner-quality-critic-v1",
        windows=(window,),
        evaluated_at=START + timedelta(hours=1),
        evaluation_hash="0" * 64,
    )
    return run.model_copy(update={"evaluation_hash": learner_metric_evaluation_content_hash(run)})


def _chain(tmp_path: Path, *, threshold: str = "0"):
    candidate = _candidate()
    learner = _learner(tmp_path, candidate)
    metric_path = tmp_path / "metric" / "run.json"
    run = _metric_run(learner, candidate)
    write_learner_metric_evaluation_run(metric_path, run)

    def reviewer(_run, window):
        return LearnerMetricQualityReviewWindowResult(
            window_id=window.window_id,
            symbol=window.symbol,
            metrics=(
                LearnerMetricQualityReviewMetric(
                    metric_id="net_pnl",
                    value=window.metrics.net_pnl,
                ),
            ),
        )

    review = execute_learner_metric_quality_review(
        metric_path,
        learner=learner,
        candidate=candidate,
        review_id="metric-quality-review-critic-001",
        review_version="learner-quality-review-v1",
        reviewer=reviewer,
        reviewed_at=START + timedelta(hours=2),
    )
    review_path = tmp_path / "review" / "review.json"
    write_learner_metric_quality_review_evidence(review_path, review)
    policy = LearnerMetricQualityPolicy(
        policy_id="learner-quality-policy-critic-001",
        minimum_windows=1,
        gates=(
            LearnerMetricQualityPolicyGate(
                metric_id="net_pnl",
                comparator="gte",
                threshold=Decimal(threshold),
            ),
        ),
    )
    decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        evaluated_at=START + timedelta(hours=3),
    )
    decision_path = tmp_path / "decision" / "decision.json"
    write_learner_metric_quality_decision(decision_path, decision)
    return decision_path, review_path, metric_path, learner, candidate, policy, decision


def test_builds_verified_request_from_failed_metric_quality_decision(tmp_path: Path) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, decision = _chain(tmp_path)

    request = build_verified_learner_metric_quality_critic_request(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        critic_run_id="run-learner-quality-critic-001",
    )

    assert decision.decision == "failed"
    assert request.source_decision == "failed"
    assert request.decision_id == decision.decision_id
    assert request.decision_hash == decision.decision_hash
    assert request.failed_gates
    assert all(not gate.passed for gate in request.failed_gates)
    assert request.failure_reason_codes == ("metric_below_threshold",)
    assert request.input_evidence_refs == tuple(sorted(request.input_evidence_refs))
    assert request.request_hash == learner_metric_quality_critic_content_hash(request)
    assert request.data_source == "cached_only"
    assert request.exchange_access is False
    assert request.promotion_state == "unpromoted"
    assert request.paper_activation is False
    assert request.execution_authority is False


def test_request_builder_rejects_passed_decision(tmp_path: Path) -> None:
    decision_path, review_path, metric_path, learner, candidate, _, _ = _chain(
        tmp_path, threshold="-2"
    )
    policy = LearnerMetricQualityPolicy(
        policy_id="learner-quality-policy-critic-002",
        minimum_windows=1,
        gates=(
            LearnerMetricQualityPolicyGate(
                metric_id="net_pnl",
                comparator="gte",
                threshold=Decimal("-2"),
            ),
        ),
    )
    decision_path.unlink()
    decision = evaluate_persisted_learner_metric_quality(
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        evaluated_at=START + timedelta(hours=4),
    )
    write_learner_metric_quality_decision(decision_path, decision)

    with pytest.raises(DataQualityError, match="failed"):
        build_verified_learner_metric_quality_critic_request(
            decision_path,
            review_path,
            metric_path,
            learner=learner,
            candidate=candidate,
            policy=policy,
            critic_run_id="run-learner-quality-critic-002",
        )


def _critique_payload(request) -> dict[str, object]:
    return {
        "review_id": "review-learner-quality-critic-001",
        "critic_run_id": request.critic_run_id,
        "decision_id": request.decision_id,
        "candidate_id": request.candidate_id,
        "decision": "revise",
        "failure_reason_codes": list(request.failure_reason_codes),
        "revision_actions": ["add_cross_symbol_validation", "change_target_definition"],
    }


def test_critic_accepts_bound_response_without_authority(tmp_path: Path) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = _chain(tmp_path)
    request = build_verified_learner_metric_quality_critic_request(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        critic_run_id="run-learner-quality-critic-001",
    )

    result = LearnerMetricQualityCritic(
        transport=lambda received: _critique_payload(received)
    ).review(request)

    assert result.decision == "accepted"
    assert result.critique is not None
    assert result.critique.review_hash != "0" * 64
    assert result.raw_output is None
    assert result.promotion_state == "unpromoted"
    assert result.paper_activation is False
    assert result.execution_authority is False
    assert result.exchange_access is False


def test_critic_rejects_binding_drift_and_reports_schema_only(tmp_path: Path) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = _chain(tmp_path)
    request = build_verified_learner_metric_quality_critic_request(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        critic_run_id="run-learner-quality-critic-001",
    )
    bad = _critique_payload(request)
    bad["decision_id"] = "metric-quality-decision-other"
    result = LearnerMetricQualityCritic(transport=lambda _: bad).review(request)
    assert result.decision == "rejected"
    assert result.reason_codes == ("decision_mismatch",)
    assert result.raw_output is None

    diagnostics = LearnerMetricQualityCritic.schema_diagnostics(
        {"decision": "revise", "failure_reason_codes": []}
    )
    assert diagnostics
    assert all("-1" not in item for item in diagnostics)


def test_provider_prompt_binds_failure_and_bounded_actions(tmp_path: Path) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = _chain(tmp_path)
    request = build_verified_learner_metric_quality_critic_request(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        critic_run_id="run-learner-quality-critic-001",
    )
    system, user = build_learner_metric_quality_critic_messages(request)

    assert "Return exactly one JSON object" in system["content"]
    assert "failure_reason_codes" in system["content"]
    assert "add_cross_symbol_validation" in system["content"]
    assert "Do not suggest promotion" in system["content"]
    assert request.decision_id in user["content"]
    assert "metric_below_threshold" in user["content"]
    assert "net_pnl" in user["content"]


def test_google_transport_reaches_existing_json_client(tmp_path: Path) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = _chain(tmp_path)
    request = build_verified_learner_metric_quality_critic_request(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        critic_run_id="run-learner-quality-critic-001",
    )
    payload = _critique_payload(request)

    def handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        assert body["model"] == "gemma-4-31b-it"
        assert body["max_tokens"] == 1024
        assert body["temperature"] == 0.0
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    system, user = build_learner_metric_quality_critic_messages(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport = GoogleAIStudioLearnerMetricQualityCriticTransport(
            client=GoogleAIStudioJsonClient(
                GoogleAIStudioProviderConfig(
                    model_id="gemma-4-31b-it",
                    api_key="not-real",
                ),
                client=client,
            ),
            system_prompt=system["content"],
            user_prompt_builder=lambda _: user["content"],
        )
        result = LearnerMetricQualityCritic(transport=transport).review(request)

    assert result.decision == "accepted"
    assert result.critique is not None


def test_critic_provider_failure_keeps_only_safe_metadata(tmp_path: Path) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = _chain(tmp_path)
    request = build_verified_learner_metric_quality_critic_request(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        critic_run_id="run-learner-quality-critic-001",
    )

    class ProviderFailure(RuntimeError):
        code = "provider_payload_invalid"
        metadata = {"status_code": 200, "secret": "must-not-leak"}

    result = LearnerMetricQualityCritic(
        transport=lambda _: (_ for _ in ()).throw(ProviderFailure())
    ).review(request)

    assert result.decision == "rejected"
    assert result.reason_codes == ("provider_payload_invalid",)
    assert result.provider_metadata == {"status_code": 200}


def test_critic_evidence_is_immutable_and_source_files_survive(tmp_path: Path) -> None:
    decision_path, review_path, metric_path, learner, candidate, policy, _ = _chain(tmp_path)
    request = build_verified_learner_metric_quality_critic_request(
        decision_path,
        review_path,
        metric_path,
        learner=learner,
        candidate=candidate,
        policy=policy,
        critic_run_id="run-learner-quality-critic-001",
    )
    critique = parse_learner_metric_quality_critique(_critique_payload(request))
    evidence = build_learner_metric_quality_critic_evidence(
        request=request,
        critique=critique,
        evidence_id="learner-quality-critic-evidence-001",
        created_at=START + timedelta(hours=5),
        provider_metadata={"status_code": 200, "secret": "discard"},
    )
    paths = (decision_path, review_path, metric_path)
    source_bytes = {path: path.read_bytes() for path in paths}
    evidence_path = tmp_path / "critic" / "evidence.json"

    assert isinstance(evidence, LearnerMetricQualityCritiqueEvidence)
    assert evidence.evidence_hash == learner_metric_quality_critic_evidence_content_hash(evidence)
    assert evidence.provider_metadata == {"status_code": 200}
    assert persist_learner_metric_quality_critic_evidence(evidence_path, evidence) == evidence
    assert persist_learner_metric_quality_critic_evidence(evidence_path, evidence) == evidence
    assert read_learner_metric_quality_critic_evidence(evidence_path) == evidence
    assert all(path.read_bytes() == content for path, content in source_bytes.items())

    changed = evidence.model_copy(update={"created_at": START + timedelta(hours=6)})
    with pytest.raises(DomainViolation, match="immutable"):
        persist_learner_metric_quality_critic_evidence(evidence_path, changed)

    tampered = json.loads(evidence_path.read_text(encoding="utf-8"))
    tampered["provider_metadata"]["status_code"] = 201
    evidence_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_learner_metric_quality_critic_evidence(evidence_path)
