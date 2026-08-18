"""Read-only cohort readiness summary for paper health reports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from ..domain.contracts import DomainModel
from .health import PaperHealthReport
from .observation import PaperObservationBinding


class PaperCohortCandidateStatus(DomainModel):
    candidate_id: str
    candidate_artifact_hash: str
    health_status: Literal["unavailable", "maturing", "healthy", "attention", "blocked"]
    maturity_status: Literal["unavailable", "maturing", "blocked", "mature"]
    accounting_complete: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)


class PaperCohortReadinessReport(DomainModel):
    cohort_status: Literal["unavailable", "not_ready", "blocked", "ready_for_human_review"]
    expected_candidate_count: int = Field(gt=0, strict=True)
    reported_candidate_count: int = Field(ge=0, strict=True)
    healthy_candidate_count: int = Field(ge=0, strict=True)
    mature_candidate_count: int = Field(ge=0, strict=True)
    attention_candidate_count: int = Field(ge=0, strict=True)
    maturing_candidate_count: int = Field(ge=0, strict=True)
    blocked_candidate_count: int = Field(ge=0, strict=True)
    missing_candidate_ids: tuple[str, ...] = ()
    all_mature: bool
    all_accounting_complete: bool
    candidates: tuple[PaperCohortCandidateStatus, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False


def _report(
    *,
    status: Literal["unavailable", "not_ready", "blocked", "ready_for_human_review"],
    expected: tuple[PaperObservationBinding, ...],
    reports: tuple[PaperHealthReport, ...],
    missing: tuple[str, ...],
    reason_codes: tuple[str, ...],
) -> PaperCohortReadinessReport:
    candidates = tuple(
        PaperCohortCandidateStatus(
            candidate_id=report.candidate_id,
            candidate_artifact_hash=report.candidate_artifact_hash,
            health_status=report.health_status,
            maturity_status=report.maturity_status,
            accounting_complete=report.accounting_complete,
            reason_codes=report.reason_codes,
        )
        for report in sorted(reports, key=lambda item: item.candidate_id)
    )
    healthy = sum(report.health_status == "healthy" for report in reports)
    mature = sum(report.maturity_status == "mature" for report in reports)
    attention = sum(report.health_status == "attention" for report in reports)
    maturing = sum(report.health_status == "maturing" for report in reports)
    blocked = sum(report.health_status in ("blocked", "unavailable") for report in reports)
    return PaperCohortReadinessReport(
        cohort_status=status,
        expected_candidate_count=len(expected),
        reported_candidate_count=len(reports),
        healthy_candidate_count=healthy,
        mature_candidate_count=mature,
        attention_candidate_count=attention,
        maturing_candidate_count=maturing,
        blocked_candidate_count=blocked,
        missing_candidate_ids=missing,
        all_mature=len(reports) == len(expected) and mature == len(expected),
        all_accounting_complete=(
            len(reports) == len(expected) and all(report.accounting_complete for report in reports)
        ),
        candidates=candidates,
        reason_codes=reason_codes,
    )


def summarize_paper_cohort(
    reports: Sequence[PaperHealthReport],
    expected_bindings: Sequence[PaperObservationBinding],
) -> PaperCohortReadinessReport:
    """Summarize explicit paper health reports without promotion or mutation."""
    expected = tuple(expected_bindings)
    if not expected:
        raise ValueError("expected cohort cannot be empty")
    expected_keys = tuple(
        (binding.candidate_id, binding.candidate_artifact_hash) for binding in expected
    )
    if len(set(expected_keys)) != len(expected_keys):
        raise ValueError("expected cohort bindings must be unique")
    expected_map = set(expected_keys)
    accepted: list[PaperHealthReport] = []
    seen: set[tuple[str, str]] = set()
    for report in reports:
        key = (report.candidate_id, report.candidate_artifact_hash)
        if key not in expected_map or key in seen:
            return _report(
                status="blocked",
                expected=expected,
                reports=tuple(accepted),
                missing=tuple(
                    binding.candidate_id
                    for binding in expected
                    if (binding.candidate_id, binding.candidate_artifact_hash) not in seen
                ),
                reason_codes=("paper_cohort_report_binding_invalid",),
            )
        seen.add(key)
        accepted.append(report)
    missing = tuple(
        binding.candidate_id
        for binding in expected
        if (binding.candidate_id, binding.candidate_artifact_hash) not in seen
    )
    accepted_tuple = tuple(accepted)
    if not accepted_tuple:
        return _report(
            status="unavailable",
            expected=expected,
            reports=(),
            missing=tuple(binding.candidate_id for binding in expected),
            reason_codes=("paper_cohort_health_unavailable",),
        )
    if any(report.health_status == "blocked" for report in accepted_tuple):
        status: Literal["unavailable", "not_ready", "blocked", "ready_for_human_review"] = "blocked"
        reason_codes = ("paper_cohort_candidate_blocked",)
    elif missing:
        status = "not_ready"
        reason_codes = ("paper_cohort_candidate_missing",)
    elif any(report.health_status == "attention" for report in accepted_tuple):
        status = "not_ready"
        reason_codes = ("paper_cohort_candidate_attention",)
    elif any(
        report.health_status in ("maturing", "unavailable")
        or report.maturity_status != "mature"
        or not report.accounting_complete
        for report in accepted_tuple
    ):
        status = "not_ready"
        reason_codes = ("paper_cohort_candidate_not_mature",)
    else:
        status = "ready_for_human_review"
        reason_codes = ("paper_cohort_ready_for_human_review",)
    return _report(
        status=status,
        expected=expected,
        reports=accepted_tuple,
        missing=missing,
        reason_codes=reason_codes,
    )
