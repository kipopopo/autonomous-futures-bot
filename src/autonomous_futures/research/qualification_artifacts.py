from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .walk_forward import WalkForwardAggregation

QualificationDecision = Literal["rejected", "qualified"]
QualificationComparator = Literal["gte", "lte", "eq", "present", "bool"]
QualificationSource = Literal["creator_evaluator", "walk_forward_oos"]


class QualificationMetric(DomainModel):
    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    value: Decimal

    @field_validator("value")
    @classmethod
    def value_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("qualification metric value must be finite")
        return value


class QualificationGateResult(DomainModel):
    gate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    passed: bool
    observed: Decimal | None = None
    threshold: Decimal | None = None
    comparator: QualificationComparator
    reason_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")

    @field_validator("observed", "threshold")
    @classmethod
    def optional_values_are_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("qualification gate values must be finite")
        return value


class WalkForwardQualificationPolicy(DomainModel):
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    minimum_windows: int = Field(ge=1, strict=True)
    minimum_trades: int = Field(ge=1, strict=True)
    minimum_profit_factor: Decimal
    maximum_drawdown_pct: Decimal
    minimum_average_return_pct: Decimal

    @field_validator(
        "minimum_profit_factor",
        "maximum_drawdown_pct",
        "minimum_average_return_pct",
    )
    @classmethod
    def thresholds_are_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("walk-forward policy thresholds must be finite")
        return value

    @field_validator("minimum_profit_factor", "maximum_drawdown_pct")
    @classmethod
    def non_negative_thresholds(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("walk-forward risk thresholds must be non-negative")
        return value


class CreatorCandidateQualificationArtifact(DomainModel):
    qualification_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    evaluator_version: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    decision: QualificationDecision
    metrics: tuple[QualificationMetric, ...] = Field(min_length=1)
    gates: tuple[QualificationGateResult, ...] = Field(min_length=1)
    windows_evaluated: int = Field(ge=0)
    qualification_policy_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    oos_aggregation_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source: QualificationSource = "creator_evaluator"
    evaluated_at: datetime
    promotion_state: Literal["unpromoted"] = "unpromoted"
    execution_authority: Literal[False] = False
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> CreatorCandidateQualificationArtifact:
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(set(metric_ids)) != len(metric_ids) or metric_ids != tuple(sorted(metric_ids)):
            raise ValueError("qualification metrics must be sorted and unique")
        gate_ids = tuple(gate.gate_id for gate in self.gates)
        if len(set(gate_ids)) != len(gate_ids) or gate_ids != tuple(sorted(gate_ids)):
            raise ValueError("qualification gates must be sorted and unique")
        if self.decision == "qualified":
            if self.windows_evaluated < 1:
                raise ValueError("qualified decision requires at least one evaluated window")
            if not all(gate.passed for gate in self.gates):
                raise ValueError("qualified decision requires every gate to pass")
        if self.source == "walk_forward_oos":
            if self.qualification_policy_id is None:
                raise ValueError("walk-forward qualification requires a policy binding")
            if self.oos_aggregation_hash is None:
                raise ValueError("walk-forward qualification requires aggregation binding")
        return self


def _qualification_content_hash(artifact: CreatorCandidateQualificationArtifact) -> str:
    payload = artifact.model_dump(mode="json", exclude={"evaluated_at", "qualification_hash"})
    for optional_field in ("qualification_policy_id", "oos_aggregation_hash"):
        if payload[optional_field] is None:
            payload.pop(optional_field)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_creator_candidate_qualification_artifact(
    *,
    candidate: CreatorCandidateArtifact,
    evaluator_run_id: str,
    evaluator_version: str,
    decision: QualificationDecision,
    metrics: Sequence[QualificationMetric],
    gates: Sequence[QualificationGateResult],
    windows_evaluated: int,
    evaluated_at: datetime,
    qualification_policy_id: str | None = None,
    oos_aggregation_hash: str | None = None,
    source: QualificationSource = "creator_evaluator",
) -> CreatorCandidateQualificationArtifact:
    if candidate.state != "testing":
        raise DataQualityError("only testing candidates may be qualified")
    try:
        provisional = CreatorCandidateQualificationArtifact(
            candidate_id=candidate.candidate_id,
            candidate_artifact_hash=candidate.artifact_hash,
            bundle_hash=candidate.bundle_hash,
            dataset_registry_hash=candidate.dataset_registry_hash,
            evaluator_run_id=evaluator_run_id,
            evaluator_version=evaluator_version,
            decision=decision,
            metrics=tuple(sorted(metrics, key=lambda metric: metric.metric_id)),
            gates=tuple(sorted(gates, key=lambda gate: gate.gate_id)),
            windows_evaluated=windows_evaluated,
            qualification_policy_id=qualification_policy_id,
            oos_aggregation_hash=oos_aggregation_hash,
            source=source,
            evaluated_at=evaluated_at,
            qualification_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid creator qualification artifact: " + str(exc)) from None
    return provisional.model_copy(
        update={"qualification_hash": _qualification_content_hash(provisional)}
    )


def _walk_forward_aggregation_hash(aggregation: WalkForwardAggregation) -> str:
    payload = aggregation.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _threshold_gate(
    *,
    gate_id: str,
    observed: Decimal | None,
    threshold: Decimal,
    comparator: Literal["gte", "lte"],
    passed_reason: str,
    failed_reason: str,
) -> QualificationGateResult:
    passed = observed is not None and (
        observed >= threshold if comparator == "gte" else observed <= threshold
    )
    return QualificationGateResult(
        gate_id=gate_id,
        passed=passed,
        observed=observed,
        threshold=threshold,
        comparator=comparator,
        reason_code=passed_reason if passed else failed_reason,
    )


def build_walk_forward_qualification_artifact(
    *,
    candidate: CreatorCandidateArtifact,
    aggregation: WalkForwardAggregation,
    policy: WalkForwardQualificationPolicy,
    evaluator_run_id: str,
    evaluator_version: str,
    evaluated_at: datetime,
) -> CreatorCandidateQualificationArtifact:
    """Build strict OOS qualification evidence without changing candidate state."""
    if candidate.strategy.universe.symbols != aggregation.required_symbols:
        raise DataQualityError("walk-forward candidate universe does not match aggregation")

    metrics = [
        QualificationMetric(
            metric_id="oos_average_return_pct", value=aggregation.average_return_pct
        ),
        QualificationMetric(metric_id="oos_pooled_net_pnl", value=aggregation.pooled_net_pnl),
        QualificationMetric(
            metric_id="oos_total_trades", value=Decimal(aggregation.total_trade_count)
        ),
        QualificationMetric(
            metric_id="oos_worst_drawdown_pct", value=aggregation.worst_max_drawdown_pct
        ),
        QualificationMetric(metric_id="oos_window_count", value=Decimal(aggregation.window_count)),
    ]
    if aggregation.pooled_profit_factor is not None:
        metrics.append(
            QualificationMetric(
                metric_id="oos_pooled_profit_factor",
                value=aggregation.pooled_profit_factor,
            )
        )

    gates = [
        _threshold_gate(
            gate_id="oos_windows_min",
            observed=Decimal(aggregation.window_count),
            threshold=Decimal(policy.minimum_windows),
            comparator="gte",
            passed_reason="oos_windows_passed",
            failed_reason="oos_windows_below_threshold",
        ),
        _threshold_gate(
            gate_id="oos_trades_min",
            observed=Decimal(aggregation.total_trade_count),
            threshold=Decimal(policy.minimum_trades),
            comparator="gte",
            passed_reason="oos_trades_passed",
            failed_reason="oos_trades_below_threshold",
        ),
        _threshold_gate(
            gate_id="oos_profit_factor_min",
            observed=aggregation.pooled_profit_factor,
            threshold=policy.minimum_profit_factor,
            comparator="gte",
            passed_reason="oos_profit_factor_passed",
            failed_reason=(
                "oos_profit_factor_missing"
                if aggregation.pooled_profit_factor is None
                else "oos_profit_factor_below_threshold"
            ),
        ),
        _threshold_gate(
            gate_id="oos_drawdown_max",
            observed=aggregation.worst_max_drawdown_pct,
            threshold=policy.maximum_drawdown_pct,
            comparator="lte",
            passed_reason="oos_drawdown_passed",
            failed_reason="oos_drawdown_above_threshold",
        ),
        _threshold_gate(
            gate_id="oos_average_return_min",
            observed=aggregation.average_return_pct,
            threshold=policy.minimum_average_return_pct,
            comparator="gte",
            passed_reason="oos_average_return_passed",
            failed_reason="oos_average_return_below_threshold",
        ),
    ]
    for summary in aggregation.per_symbol:
        symbol_key = summary.symbol.lower()
        metrics.extend(
            (
                QualificationMetric(
                    metric_id=f"oos_{symbol_key}_average_return_pct",
                    value=summary.average_return_pct,
                ),
                QualificationMetric(
                    metric_id=f"oos_{symbol_key}_net_pnl",
                    value=summary.net_pnl,
                ),
                QualificationMetric(
                    metric_id=f"oos_{symbol_key}_total_trades",
                    value=Decimal(summary.total_trade_count),
                ),
                QualificationMetric(
                    metric_id=f"oos_{symbol_key}_worst_drawdown_pct",
                    value=summary.worst_max_drawdown_pct,
                ),
                QualificationMetric(
                    metric_id=f"oos_{symbol_key}_window_count",
                    value=Decimal(summary.window_count),
                ),
            )
        )
        if summary.pooled_profit_factor is not None:
            metrics.append(
                QualificationMetric(
                    metric_id=f"oos_{symbol_key}_profit_factor",
                    value=summary.pooled_profit_factor,
                )
            )
        gates.extend(
            (
                _threshold_gate(
                    gate_id=f"oos_{symbol_key}_windows_min",
                    observed=Decimal(summary.window_count),
                    threshold=Decimal(policy.minimum_windows),
                    comparator="gte",
                    passed_reason="oos_symbol_windows_passed",
                    failed_reason="oos_symbol_windows_below_threshold",
                ),
                _threshold_gate(
                    gate_id=f"oos_{symbol_key}_trades_min",
                    observed=Decimal(summary.total_trade_count),
                    threshold=Decimal(policy.minimum_trades),
                    comparator="gte",
                    passed_reason="oos_symbol_trades_passed",
                    failed_reason="oos_symbol_trades_below_threshold",
                ),
                _threshold_gate(
                    gate_id=f"oos_{symbol_key}_profit_factor_min",
                    observed=summary.pooled_profit_factor,
                    threshold=policy.minimum_profit_factor,
                    comparator="gte",
                    passed_reason="oos_symbol_profit_factor_passed",
                    failed_reason=(
                        "oos_symbol_profit_factor_missing"
                        if summary.pooled_profit_factor is None
                        else "oos_symbol_profit_factor_below_threshold"
                    ),
                ),
                _threshold_gate(
                    gate_id=f"oos_{symbol_key}_drawdown_max",
                    observed=summary.worst_max_drawdown_pct,
                    threshold=policy.maximum_drawdown_pct,
                    comparator="lte",
                    passed_reason="oos_symbol_drawdown_passed",
                    failed_reason="oos_symbol_drawdown_above_threshold",
                ),
                _threshold_gate(
                    gate_id=f"oos_{symbol_key}_average_return_min",
                    observed=summary.average_return_pct,
                    threshold=policy.minimum_average_return_pct,
                    comparator="gte",
                    passed_reason="oos_symbol_average_return_passed",
                    failed_reason="oos_symbol_average_return_below_threshold",
                ),
            )
        )

    decision: QualificationDecision = (
        "qualified" if all(gate.passed for gate in gates) else "rejected"
    )
    return build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id=evaluator_run_id,
        evaluator_version=evaluator_version,
        decision=decision,
        metrics=metrics,
        gates=gates,
        windows_evaluated=aggregation.window_count,
        evaluated_at=evaluated_at,
        qualification_policy_id=policy.policy_id,
        oos_aggregation_hash=_walk_forward_aggregation_hash(aggregation),
        source="walk_forward_oos",
    )


def read_creator_candidate_qualification_artifact(
    path: Path,
) -> CreatorCandidateQualificationArtifact:
    artifact = CreatorCandidateQualificationArtifact.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if _qualification_content_hash(artifact) != artifact.qualification_hash:
        raise DomainViolation(f"creator qualification artifact hash mismatch: {path}")
    return artifact


def write_creator_candidate_qualification_artifact(
    path: Path, artifact: CreatorCandidateQualificationArtifact
) -> CreatorCandidateQualificationArtifact:
    if path.exists():
        existing = read_creator_candidate_qualification_artifact(path)
        if existing != artifact:
            raise DomainViolation(f"creator qualification artifact path is immutable: {path}")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)
    return artifact


__all__ = [
    "CreatorCandidateQualificationArtifact",
    "QualificationComparator",
    "QualificationDecision",
    "QualificationGateResult",
    "QualificationMetric",
    "QualificationSource",
    "WalkForwardQualificationPolicy",
    "build_creator_candidate_qualification_artifact",
    "build_walk_forward_qualification_artifact",
    "read_creator_candidate_qualification_artifact",
    "write_creator_candidate_qualification_artifact",
]
