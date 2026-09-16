"""Read-only cohort readiness summary for paper health reports."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    CandidateRegistryManifest,
    compute_registry_hash,
    read_candidate_registry,
    verify_candidate_registry_manifest,
)
from .health import PaperHealthReport, aggregate_paper_health
from .lifecycle import PaperLifecycleTelemetry
from .observation import PaperObservationBinding
from .sqlite_ledger import SqlitePaperLedger
from .sqlite_lifecycle import SqlitePaperLifecycle
from .sqlite_observation import SqlitePaperObservations

if TYPE_CHECKING:
    from ..research.creator_artifacts import CreatorCandidateArtifact

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _assert_zero_secrets(text: str, source_label: str) -> None:
    match = _SECRET_PATTERN.search(text)
    if match:
        raise DomainViolation(f"Secret pattern matched in {source_label}: {match.group(0)[:8]}...")


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


def evaluate_paper_cohort_snapshot(
    ledger_db: Path | str | None = None,
    lifecycle_db: Path | str | None = None,
    observations_db: Path | str | None = None,
    *,
    ledger_path: Path | str | None = None,
    lifecycle_path: Path | str | None = None,
    observations_path: Path | str | None = None,
    manifest: CandidateRegistryManifest | Path | str | None = None,
    candidates: Mapping[str, CreatorCandidateArtifact] | None = None,
    expected_bindings: Sequence[PaperObservationBinding] | None = None,
    as_of: datetime | None = None,
    max_mark_age_seconds: int = 86400,
    required_days: int = 7,
    output_dir: Path | str | None = None,
) -> tuple[dict[str, PaperHealthReport], PaperCohortReadinessReport]:
    """Execute automated cohort readiness snapshot evaluation across isolated SQLite stores.

    Combines aggregate_paper_health per candidate and summarize_paper_cohort
    without external order routing. Optionally serializes paper-cohort-readiness-report.json
    and per-symbol health reports after zero-secret verification.
    """
    ledger_file = Path(ledger_path or ledger_db or "paper-ledger.sqlite3")
    lifecycle_file = Path(lifecycle_path or lifecycle_db or "paper-lifecycle.sqlite3")
    obs_file = Path(observations_path or observations_db or "paper-observations.sqlite3")

    ledger_store = SqlitePaperLedger(ledger_file)
    lifecycle_store = SqlitePaperLifecycle(lifecycle_file)
    obs_store = SqlitePaperObservations(obs_file)

    # Resolve candidate targets (symbol, candidate_id, candidate_artifact_hash)
    entries: list[tuple[str, str, str]] = []
    if candidates is not None:
        entries = [
            (sym, cand.candidate_id, cand.artifact_hash) for sym, cand in sorted(candidates.items())
        ]
    elif manifest is not None:
        if isinstance(manifest, (str, Path)):
            manifest_obj = read_candidate_registry(manifest, verify_hash=True)
        else:
            manifest_obj = manifest
            if not verify_candidate_registry_manifest(manifest_obj):
                exp_h = manifest_obj.registry_hash
                comp_h = compute_registry_hash(manifest_obj)
                raise DomainViolation(
                    f"CandidateRegistryManifest registry_hash mismatch: "
                    f"expected {exp_h}, computed {comp_h}"
                )
        entries = [
            (sym, entry.candidate_id, entry.candidate_artifact_hash)
            for sym, entry in sorted(manifest_obj.symbols.items())
        ]
    elif expected_bindings is not None:
        entries = [
            (b.candidate_id, b.candidate_id, b.candidate_artifact_hash) for b in expected_bindings
        ]
    elif obs_file.is_file():
        try:
            conn = obs_store._connect()
            try:
                cursor = conn.execute(
                    "SELECT DISTINCT candidate_id, candidate_artifact_hash "
                    "FROM paper_observations ORDER BY candidate_id ASC"
                )
                for row in cursor.fetchall():
                    entries.append((row[0], row[0], row[1]))
            finally:
                conn.close()
        except sqlite3.Error:
            pass
        if not entries and Path(DEFAULT_CANDIDATE_REGISTRY_PATH).is_file():
            manifest_obj = read_candidate_registry(
                DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True
            )
            entries = [
                (sym, entry.candidate_id, entry.candidate_artifact_hash)
                for sym, entry in sorted(manifest_obj.symbols.items())
            ]
    elif Path(DEFAULT_CANDIDATE_REGISTRY_PATH).is_file():
        manifest_obj = read_candidate_registry(DEFAULT_CANDIDATE_REGISTRY_PATH, verify_hash=True)
        entries = [
            (sym, entry.candidate_id, entry.candidate_artifact_hash)
            for sym, entry in sorted(manifest_obj.symbols.items())
        ]

    if not entries:
        placeholder = PaperObservationBinding(
            candidate_id="cand-unavailable-placeholder",
            candidate_artifact_hash="0" * 64,
        )
        target_b = tuple(expected_bindings) if expected_bindings else (placeholder,)
        empty_rep = summarize_paper_cohort([], target_b)
        if output_dir is not None:
            out_p = Path(output_dir)
            out_p.mkdir(parents=True, exist_ok=True)
            cohort_path = out_p / "paper-cohort-readiness-report.json"
            cohort_json = (
                json.dumps(empty_rep.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            )
            _assert_zero_secrets(cohort_json, str(cohort_path))
            cohort_path.write_text(cohort_json, encoding="utf-8")
        return {}, empty_rep

    # Deduplicate unique candidate bindings for cohort evaluation
    if expected_bindings is not None:
        target_bindings = tuple(expected_bindings)
    else:
        seen_bindings: set[tuple[str, str]] = set()
        unique_bindings: list[PaperObservationBinding] = []
        for _, c_id, c_hash in entries:
            key = (c_id, c_hash)
            if key not in seen_bindings:
                seen_bindings.add(key)
                unique_bindings.append(
                    PaperObservationBinding(candidate_id=c_id, candidate_artifact_hash=c_hash)
                )
        target_bindings = tuple(unique_bindings)

    # Load active open positions from ledger
    final_ledger = ledger_store.load()
    open_positions = final_ledger.open_positions()

    # Determine reference as_of timestamp with whole-second precision
    if as_of is not None:
        if as_of.tzinfo is None or as_of.utcoffset() != UTC.utcoffset(as_of):
            raise ValueError("as_of must be timezone-aware UTC")
        if as_of.microsecond > 0:
            observed_at = (as_of + timedelta(seconds=1)).astimezone(UTC).replace(microsecond=0)
        else:
            observed_at = as_of.astimezone(UTC).replace(microsecond=0)
    else:
        latest_ts: datetime | None = None
        for _, c_id, c_hash in entries:
            c_obs = obs_store.read(c_id, c_hash)
            for o in c_obs:
                if latest_ts is None or o.observed_at > latest_ts:
                    latest_ts = o.observed_at
        if lifecycle_file.is_file():
            try:
                conn = sqlite3.connect(lifecycle_file)
                try:
                    cursor = conn.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'paper_lifecycle_marks'"
                    )
                    if cursor.fetchone() is not None:
                        row = conn.execute(
                            "SELECT MAX(marked_at) FROM paper_lifecycle_marks"
                        ).fetchone()
                        if row and row[0]:
                            raw_ts = row[0].replace("Z", "+00:00")
                            ts = datetime.fromisoformat(raw_ts).astimezone(UTC)
                            if latest_ts is None or ts > latest_ts:
                                latest_ts = ts
                finally:
                    conn.close()
            except sqlite3.Error, ValueError:
                pass
        for e in final_ledger.entries:
            if latest_ts is None or e.occurred_at > latest_ts:
                latest_ts = e.occurred_at
        if latest_ts is not None:
            if latest_ts.microsecond > 0:
                observed_at = (
                    (latest_ts + timedelta(seconds=1)).astimezone(UTC).replace(microsecond=0)
                )
            else:
                observed_at = latest_ts.astimezone(UTC).replace(microsecond=0)
        else:
            observed_at = datetime.now(UTC).astimezone(UTC).replace(microsecond=0)

    # Aggregate health per candidate
    health_reports: dict[str, PaperHealthReport] = {}
    for sym, c_id, c_hash in entries:
        cand_obs = obs_store.read(c_id, c_hash)
        active_marks: list[PaperLifecycleTelemetry] = []
        for pos in open_positions:
            if pos.candidate_id == c_id and (sym == c_id or pos.symbol.upper() == sym.upper()):
                mark = lifecycle_store.latest(
                    candidate_id=c_id,
                    candidate_artifact_hash=c_hash,
                    trade_id=pos.trade_id,
                )
                if mark is not None:
                    active_marks.append(mark)

        health_rep = aggregate_paper_health(
            cand_obs,
            tuple(active_marks),
            candidate_id=c_id,
            candidate_artifact_hash=c_hash,
            as_of=observed_at,
            max_mark_age_seconds=max_mark_age_seconds,
            required_days=required_days,
        )
        health_reports[sym] = health_rep

    # Deduplicate candidate reports for cohort summary
    seen_rep_keys: set[tuple[str, str]] = set()
    unique_reports: list[PaperHealthReport] = []
    for rep in health_reports.values():
        rep_key = (rep.candidate_id, rep.candidate_artifact_hash)
        if rep_key not in seen_rep_keys:
            seen_rep_keys.add(rep_key)
            unique_reports.append(rep)

    cohort_rep = summarize_paper_cohort(unique_reports, target_bindings)

    # Persist serialized reports if output directory requested
    if output_dir is not None:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        cohort_path = out_p / "paper-cohort-readiness-report.json"
        cohort_json = (
            json.dumps(cohort_rep.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )
        _assert_zero_secrets(cohort_json, str(cohort_path))
        cohort_path.write_text(cohort_json, encoding="utf-8")

        for sym, h_rep in health_reports.items():
            health_path = out_p / f"paper-health-report-{sym}.json"
            health_json = json.dumps(h_rep.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            _assert_zero_secrets(health_json, str(health_path))
            health_path.write_text(health_json, encoding="utf-8")

    return health_reports, cohort_rep


__all__ = [
    "PaperCohortCandidateStatus",
    "PaperCohortReadinessReport",
    "evaluate_paper_cohort_snapshot",
    "summarize_paper_cohort",
]
