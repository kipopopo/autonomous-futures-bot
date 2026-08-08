from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
    build_creator_candidate_qualification_artifact,
    read_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)

CREATED_AT = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _candidate():
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id="cand-qualification-001",
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id="cand-qualification-001",
        strategy=strategy,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-run-qualification",
        research_seed=29,
        created_at=CREATED_AT,
    )


def _metrics() -> tuple[QualificationMetric, ...]:
    return (
        QualificationMetric(metric_id="oos_sharpe", value=Decimal("1.2500")),
        QualificationMetric(metric_id="oos_trades", value=Decimal("42")),
    )


def _gates(*, sharpe_passed: bool = True) -> tuple[QualificationGateResult, ...]:
    return (
        QualificationGateResult(
            gate_id="oos_sharpe_min",
            passed=sharpe_passed,
            observed=Decimal("1.2500"),
            threshold=Decimal("1.0000"),
            comparator="gte",
            reason_code="oos_sharpe_passed" if sharpe_passed else "oos_sharpe_below_threshold",
        ),
        QualificationGateResult(
            gate_id="oos_windows_present",
            passed=True,
            observed=Decimal("3"),
            threshold=Decimal("3"),
            comparator="gte",
            reason_code="oos_windows_present",
        ),
    )


def _artifact(*, decision: str = "qualified", evaluated_at: datetime = CREATED_AT):
    return build_creator_candidate_qualification_artifact(
        candidate=_candidate(),
        evaluator_run_id="evaluator-run-qualification",
        evaluator_version="evaluator-v1",
        decision=decision,
        metrics=_metrics(),
        gates=_gates(sharpe_passed=decision == "qualified"),
        windows_evaluated=3 if decision == "qualified" else 0,
        evaluated_at=evaluated_at,
    )


def test_qualification_artifact_is_deterministic_and_never_promoted() -> None:
    first = _artifact()
    second = _artifact(evaluated_at=CREATED_AT + timedelta(hours=1))

    assert first.qualification_hash == second.qualification_hash
    assert first.decision == "qualified"
    assert first.candidate_id == "cand-qualification-001"
    assert first.candidate_artifact_hash == _candidate().artifact_hash
    assert first.bundle_hash == "a" * 64
    assert first.dataset_registry_hash == "b" * 64
    assert first.promotion_state == "unpromoted"
    assert first.execution_authority is False
    assert all(gate.passed for gate in first.gates)


def test_qualified_artifact_rejects_failed_gate() -> None:
    with pytest.raises(DataQualityError, match="qualified decision requires every gate to pass"):
        build_creator_candidate_qualification_artifact(
            candidate=_candidate(),
            evaluator_run_id="evaluator-run-qualification",
            evaluator_version="evaluator-v1",
            decision="qualified",
            metrics=_metrics(),
            gates=_gates(sharpe_passed=False),
            windows_evaluated=3,
            evaluated_at=CREATED_AT,
        )


def test_qualified_artifact_requires_positive_walk_forward_windows() -> None:
    with pytest.raises(DataQualityError, match="qualified decision requires at least one"):
        build_creator_candidate_qualification_artifact(
            candidate=_candidate(),
            evaluator_run_id="evaluator-run-qualification",
            evaluator_version="evaluator-v1",
            decision="qualified",
            metrics=_metrics(),
            gates=_gates(),
            windows_evaluated=0,
            evaluated_at=CREATED_AT,
        )


def test_rejected_artifact_preserves_failed_evidence_and_sorts_inputs() -> None:
    candidate = _candidate()
    metrics = tuple(reversed(_metrics()))
    gates = tuple(reversed(_gates(sharpe_passed=False)))

    artifact = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="evaluator-run-qualification",
        evaluator_version="evaluator-v1",
        decision="rejected",
        metrics=metrics,
        gates=gates,
        windows_evaluated=0,
        evaluated_at=CREATED_AT,
    )

    assert artifact.decision == "rejected"
    assert artifact.metrics[0].metric_id == "oos_sharpe"
    assert artifact.gates[0].gate_id == "oos_sharpe_min"
    assert artifact.gates[0].passed is False
    assert artifact.windows_evaluated == 0


def test_qualification_artifact_preserves_decimal_json_and_is_write_once(tmp_path: Path) -> None:
    artifact = _artifact()
    path = tmp_path / "qualifications" / "cand-qualification-001.json"

    write_creator_candidate_qualification_artifact(path, artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["metrics"][0]["value"] == "1.2500"
    assert read_creator_candidate_qualification_artifact(path) == artifact
    assert write_creator_candidate_qualification_artifact(path, artifact) == artifact

    path.write_text(
        path.read_text(encoding="utf-8").replace("evaluator-v1", "evaluator-v2"),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_creator_candidate_qualification_artifact(path)


def test_qualification_artifact_rejects_non_finite_metrics() -> None:
    with pytest.raises(ValidationError, match="value"):
        QualificationMetric(metric_id="oos_sharpe", value=Decimal("NaN"))


def test_legacy_qualification_json_without_oos_binding_fields_remains_readable(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    payload = artifact.model_dump(mode="json")
    payload.pop("qualification_policy_id")
    payload.pop("oos_aggregation_hash")
    payload_without_hash = {
        key: value
        for key, value in payload.items()
        if key not in {"evaluated_at", "qualification_hash"}
    }
    canonical = json.dumps(payload_without_hash, sort_keys=True, separators=(",", ":")).encode()
    payload["qualification_hash"] = sha256(canonical).hexdigest()
    path = tmp_path / "legacy-qualification.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_creator_candidate_qualification_artifact(path) == artifact
