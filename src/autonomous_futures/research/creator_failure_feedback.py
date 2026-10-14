"""Structured, evidence-only feedback derived from rejected Creator qualification."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal

from pydantic import Field, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from .qualification_artifacts import CreatorCandidateQualificationArtifact, QualificationGateResult


class CreatorQualificationFailureFeedback(DomainModel):
    feedback_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    failed_gates: tuple[QualificationGateResult, ...] = Field(min_length=1)
    failure_reason_codes: tuple[str, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_feedback(self) -> CreatorQualificationFailureFeedback:
        gate_ids = tuple(gate.gate_id for gate in self.failed_gates)
        if gate_ids != tuple(sorted(set(gate_ids))):
            raise ValueError("feedback gates must be sorted and unique")
        if self.failure_reason_codes != tuple(sorted(set(self.failure_reason_codes))):
            raise ValueError("feedback reason codes must be sorted and unique")
        return self


def build_creator_qualification_failure_feedback(
    qualification: CreatorCandidateQualificationArtifact,
) -> CreatorQualificationFailureFeedback | None:
    """Project rejected qualification gates for a future Learner/critic consumer."""
    if qualification.decision != "rejected":
        return None
    failed_gates = tuple(gate for gate in qualification.gates if not gate.passed)
    if not failed_gates:
        raise DataQualityError("rejected qualification requires failed gates")
    return CreatorQualificationFailureFeedback(
        candidate_id=qualification.candidate_id,
        candidate_artifact_hash=qualification.candidate_artifact_hash,
        bundle_hash=qualification.bundle_hash,
        dataset_registry_hash=qualification.dataset_registry_hash,
        qualification_hash=qualification.qualification_hash,
        qualification_policy_id=qualification.qualification_policy_id or "policy-unbound",
        failed_gates=tuple(sorted(failed_gates, key=lambda gate: gate.gate_id)),
        failure_reason_codes=tuple(sorted({gate.reason_code for gate in failed_gates})),
    )


def _normalize_candidate_id(raw_candidate_id: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw_candidate_id.strip().lower()).strip("-")
    if not cleaned:
        raise DataQualityError("runtime qualification report is missing a valid candidate_id")
    if not cleaned.startswith("cand-"):
        cleaned = f"cand-{cleaned}"
    return cleaned[:68].rstrip("-")


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def build_runtime_qualification_failure_feedback(
    report: Mapping[str, Any],
    *,
    candidate_id: str | None = None,
    candidate_artifact_hash: str | None = None,
    bundle_hash: str | None = None,
    dataset_registry_hash: str | None = None,
    qualification_policy_id: str | None = None,
    autopsy_records: Sequence[Mapping[str, Any]] | None = None,
) -> CreatorQualificationFailureFeedback | None:
    """Project a rejected runtime/holdout/portfolio qualification report into failure feedback."""
    decision = str(report.get("decision", "")).strip().upper()
    if decision != "REJECTED":
        return None

    gates_map = report.get("gates")
    if not isinstance(gates_map, Mapping):
        raise DataQualityError("runtime qualification report requires a gates mapping")

    metrics = _as_mapping(report.get("metrics"))
    policy = _as_mapping(report.get("policy"))

    failed_gates: list[QualificationGateResult] = []
    if gates_map.get("sufficient_oos_samples") is False:
        failed_gates.append(
            QualificationGateResult(
                gate_id="runtime_sufficient_oos_samples",
                passed=False,
                observed=Decimal(str(metrics.get("trade_count", 0))),
                threshold=Decimal(str(policy.get("minimum_trades", 30))),
                comparator="gte",
                reason_code="oos_trades_below_threshold",
            )
        )
    if gates_map.get("window_consistency") is False:
        failed_gates.append(
            QualificationGateResult(
                gate_id="runtime_window_consistency",
                passed=False,
                observed=Decimal(str(metrics.get("profitable_windows", 0))),
                threshold=Decimal(str(policy.get("minimum_profitable_windows", 3))),
                comparator="gte",
                reason_code="oos_profitable_windows_below_threshold",
            )
        )
    if gates_map.get("positive_net_edge") is False:
        failed_gates.append(
            QualificationGateResult(
                gate_id="runtime_positive_net_edge",
                passed=False,
                observed=Decimal(str(metrics.get("net_pnl", "0"))),
                threshold=Decimal("0"),
                comparator="gte",
                reason_code="oos_net_pnl_non_positive",
            )
        )
    if gates_map.get("stress_positive") is False:
        failed_gates.append(
            QualificationGateResult(
                gate_id="runtime_stress_positive",
                passed=False,
                observed=Decimal(str(metrics.get("stress_net_pnl", "0"))),
                threshold=Decimal("0"),
                comparator="gte",
                reason_code="oos_stress_net_pnl_non_positive",
            )
        )
    if gates_map.get("profit_factor") is False:
        raw_pf = metrics.get("profit_factor")
        observed_pf = Decimal(str(raw_pf)) if raw_pf is not None else Decimal("0")
        failed_gates.append(
            QualificationGateResult(
                gate_id="runtime_profit_factor",
                passed=False,
                observed=observed_pf,
                threshold=Decimal(str(policy.get("minimum_profit_factor", "1.10"))),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            )
        )
    if gates_map.get("drawdown") is False:
        raw_dd = metrics.get("drawdown_pct", metrics.get("drawdown_usdt", "0"))
        failed_gates.append(
            QualificationGateResult(
                gate_id="runtime_drawdown_max",
                passed=False,
                observed=Decimal(str(raw_dd)),
                threshold=Decimal(str(policy.get("maximum_drawdown_pct", "5"))),
                comparator="lte",
                reason_code="oos_drawdown_above_threshold",
            )
        )
    if gates_map.get("portfolio_reconciliation") is False:
        failed_gates.append(
            QualificationGateResult(
                gate_id="runtime_portfolio_reconciliation",
                passed=False,
                observed=Decimal(str(metrics.get("max_equity_drift", "1"))),
                threshold=Decimal("0"),
                comparator="eq",
                reason_code="portfolio_reconciliation_drift_detected",
            )
        )

    if autopsy_records:
        from ..execution.trade_autopsy_evidence import summarize_autopsy_feedback

        raw_symbol = report.get("symbol")
        summary = summarize_autopsy_feedback(
            [dict(item) for item in autopsy_records],
            symbol=str(raw_symbol) if isinstance(raw_symbol, str) and raw_symbol else None,
        )
        reason_codes = set(summary.get("failure_reason_codes", []))
        causes = _as_mapping(summary.get("attribution_causes"))
        wins = Decimal(str(summary.get("win_count", 0)))
        if "negative_or_zero_net_pnl" in reason_codes and int(summary.get("trade_count", 0)) > 0:
            failed_gates.append(
                QualificationGateResult(
                    gate_id="autopsy_realized_net_pnl",
                    passed=False,
                    observed=Decimal(str(summary.get("net_pnl_usdt", "0"))),
                    threshold=Decimal("0"),
                    comparator="gte",
                    reason_code="autopsy_realized_net_pnl_negative",
                )
            )
        if "stop_loss_regime_mismatch_cluster" in reason_codes:
            failed_gates.append(
                QualificationGateResult(
                    gate_id="autopsy_stop_loss_cluster",
                    passed=False,
                    observed=Decimal(str(causes.get("STOP_LOSS_REGIME_MISMATCH", 0))),
                    threshold=wins,
                    comparator="lte",
                    reason_code="stop_loss_regime_mismatch_cluster",
                )
            )
        if "time_decay_or_fee_drag_cluster" in reason_codes:
            failed_gates.append(
                QualificationGateResult(
                    gate_id="autopsy_time_decay_or_fee_drag",
                    passed=False,
                    observed=Decimal(str(causes.get("TIME_DECAY_OR_FEE_DRAG", 0))),
                    threshold=wins,
                    comparator="lte",
                    reason_code="time_decay_or_fee_drag_cluster",
                )
            )

    if not failed_gates:
        raise DataQualityError("rejected runtime qualification requires at least one failed gate")

    cand_val = _as_mapping(report.get("candidate_validation"))
    sources = _as_mapping(report.get("sources"))
    exec_src = _as_mapping(sources.get("execution"))
    mkt_src = _as_mapping(sources.get("market"))
    exec_manifest = _as_mapping(exec_src.get("manifest"))
    mkt_manifest = _as_mapping(mkt_src.get("manifest"))

    raw_cand_id = (
        candidate_id
        or cand_val.get("candidate_id")
        or report.get("candidate_id")
        or f"runtime-{str(report.get('symbol', 'portfolio')).lower()}"
    )
    resolved_candidate_id = _normalize_candidate_id(str(raw_cand_id))

    report_hash = str(report.get("report_hash", "")).strip()
    if len(report_hash) != 64:
        canonical = json.dumps(dict(report), sort_keys=True, default=str).encode("utf-8")
        report_hash = sha256(canonical).hexdigest()

    resolved_artifact_hash = str(
        candidate_artifact_hash or cand_val.get("candidate_manifest_sha256") or report_hash
    ).strip()
    resolved_bundle_hash = str(bundle_hash or exec_manifest.get("sha256") or report_hash).strip()
    resolved_registry_hash = str(
        dataset_registry_hash or mkt_manifest.get("sha256") or report_hash
    ).strip()

    raw_policy_hash = str(report.get("policy_hash", "")).strip()
    default_policy_id = (
        f"runtime-policy-{raw_policy_hash[:16]}"
        if len(raw_policy_hash) >= 16
        else "runtime-policy-v1"
    )
    resolved_policy_id = str(qualification_policy_id or default_policy_id).strip()

    ordered_gates = tuple(sorted(failed_gates, key=lambda gate: gate.gate_id))
    return CreatorQualificationFailureFeedback(
        candidate_id=resolved_candidate_id,
        candidate_artifact_hash=resolved_artifact_hash,
        bundle_hash=resolved_bundle_hash,
        dataset_registry_hash=resolved_registry_hash,
        qualification_hash=report_hash,
        qualification_policy_id=resolved_policy_id,
        failed_gates=ordered_gates,
        failure_reason_codes=tuple(sorted({gate.reason_code for gate in ordered_gates})),
    )


__all__ = [
    "CreatorQualificationFailureFeedback",
    "build_creator_qualification_failure_feedback",
    "build_runtime_qualification_failure_feedback",
]
