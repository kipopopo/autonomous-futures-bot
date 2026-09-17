"""Operator Human Review Governance CLI and Candidate Validation Staging (Phase 269).

Provides both interactive and batch CLI execution to inspect paper trading cohorts,
verify prerequisite gates, sign off on human review decisions, and package canary staging
manifests under Candidate Registry Manifest Version 2.
Also maintains backward compatibility for legacy single-report review checkpoints.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from ..domain.errors import DomainViolation
from .candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
)
from .cohort import PaperCohortReadinessReport
from .review import create_paper_review_checkpoint
from .sqlite_review import SqlitePaperReviews
from .staging import (
    DEFAULT_PHASE268_COHORT_DIR,
    DEFAULT_PHASE269_OUTPUT_DIR,
    format_performance_table,
    inspect_cohort,
    save_staging_artifacts,
    stage_canary_candidates,
)

logger = logging.getLogger(__name__)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(errors="backslashreplace")
    except Exception:
        pass


# --- Legacy Review Parser & Logic (for backward compatibility) ---
def _legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a paper human-review checkpoint.")
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--review-path", type=Path, required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument(
        "--decision",
        choices=("accept_paper_observation", "needs_attention", "reject"),
        required=True,
    )
    parser.add_argument("--review-notes", required=True)
    return parser


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid reviewed-at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("reviewed-at must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _load_report(path: Path) -> PaperCohortReadinessReport:
    try:
        return PaperCohortReadinessReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid cohort report") from exc


def _print_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _run_legacy_review(argv: list[str]) -> int:
    args = _legacy_parser().parse_args(argv)
    try:
        report = _load_report(args.report_path)
        decision = args.decision
        checkpoint = create_paper_review_checkpoint(
            report,
            review_id=args.review_id,
            reviewer_id=args.reviewer_id,
            reviewed_at=_parse_utc(args.reviewed_at),
            decision=decision,
            review_notes=args.review_notes,
        )
        SqlitePaperReviews(args.review_path).append(checkpoint)
    except (OSError, ValidationError, ValueError) as exc:
        del exc
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    payload = checkpoint.model_dump(mode="json")
    payload["status"] = "recorded"
    _print_json(payload)
    return 0


def _normalize_decision(val: str) -> str:
    clean = val.strip().lower()
    if clean in ("1", "approved_for_canary", "approved", "approve"):
        return "approved_for_canary"
    elif clean in ("2", "rejected", "reject"):
        return "rejected"
    elif clean in ("3", "held", "hold"):
        return "held"
    raise argparse.ArgumentTypeError(
        f"Invalid decision '{val}'. Choose from: approved_for_canary, rejected, held"
    )


# --- Phase 269 Operator Governance & Staging CLI ---
def _operator_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 269 Operator Human Review Governance & Canary Staging CLI."
    )
    parser.add_argument(
        "--cohort-dir",
        type=Path,
        default=DEFAULT_PHASE268_COHORT_DIR,
        help=f"Path to mature paper cohort directory (default: {DEFAULT_PHASE268_COHORT_DIR})",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_CANDIDATE_REGISTRY_PATH,
        help=f"Path to Candidate Registry Manifest (default: {DEFAULT_CANDIDATE_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE269_OUTPUT_DIR,
        help=f"Path to output canary staging artifacts (default: {DEFAULT_PHASE269_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--decision",
        type=_normalize_decision,
        choices=("approved_for_canary", "rejected", "held"),
        default=None,
        help="Review decision code (approved_for_canary, rejected, held)",
    )
    parser.add_argument(
        "--operator",
        "--operator-id",
        "--reviewer-id",
        type=str,
        default=None,
        dest="operator",
        help="Operator or reviewer identifier (e.g. operator-lead-001)",
    )
    parser.add_argument(
        "--rationale",
        "--review-notes",
        type=str,
        default=None,
        dest="rationale",
        help="Operator review notes or rationale for decision",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Force interactive prompts for operator inputs",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON summary to stdout",
    )
    parser.add_argument(
        "--review-path",
        type=Path,
        default=None,
        help="Optional path to SQLite database to record review checkpoint",
    )
    return parser


def _prompt_operator_interactive(
    inspection: Any,
    operator: str | None,
    decision: str | None,
    rationale: str | None,
) -> tuple[str, Literal["approved_for_canary", "rejected", "held"], str]:
    """Prompt operator interactively for missing fields."""
    sys.stdout.write("\n" + format_performance_table(inspection) + "\n\n")

    # Operator ID
    if not operator:
        while True:
            sys.stdout.write("Enter Operator ID: ")
            sys.stdout.flush()
            line = sys.stdin.readline()
            if not line:
                raise EOFError("Unexpected EOF on stdin while reading Operator ID")
            val = line.strip()
            if val:
                operator = val
                break
            sys.stdout.write("Operator ID cannot be empty.\n")

    # Decision
    if not decision:
        sys.stdout.write("\nSelect Human Review Decision:\n")
        sys.stdout.write("  1) approved_for_canary\n")
        sys.stdout.write("  2) rejected\n")
        sys.stdout.write("  3) held\n")
        while True:
            sys.stdout.write("Choice [1/2/3 or name]: ")
            sys.stdout.flush()
            line = sys.stdin.readline()
            if not line:
                raise EOFError("Unexpected EOF on stdin while reading Decision")
            choice = line.strip()
            choice_clean = choice.lower()
            if choice_clean in ("1", "approved_for_canary", "approved", "approve"):
                decision = "approved_for_canary"
                break
            elif choice_clean in ("2", "rejected", "reject"):
                decision = "rejected"
                break
            elif choice_clean in ("3", "held", "hold"):
                decision = "held"
                break
            sys.stdout.write(
                "Invalid choice. Please select 1 (approved_for_canary), "
                "2 (rejected), or 3 (held).\n"
            )

    typed_decision: Literal["approved_for_canary", "rejected", "held"] = (
        "approved_for_canary"
        if decision == "approved_for_canary"
        else "rejected"
        if decision == "rejected"
        else "held"
    )

    # Rationale
    if not rationale:
        while True:
            sys.stdout.write("\nEnter Review Rationale / Notes: ")
            sys.stdout.flush()
            line = sys.stdin.readline()
            if not line:
                raise EOFError("Unexpected EOF on stdin while reading Rationale")
            val = line.strip()
            if val:
                rationale = val
                break
            sys.stdout.write("Rationale cannot be empty.\n")

    return operator, typed_decision, rationale


def _run_operator_staging_cli(argv: list[str]) -> int:
    parser = _operator_parser()
    args = parser.parse_args(argv)

    try:
        inspection = inspect_cohort(
            cohort_dir=args.cohort_dir,
            registry_path=args.registry_path,
        )
    except (FileNotFoundError, DomainViolation, ValueError) as exc:
        if args.json:
            _print_json(
                {"status": "error", "error_code": "cohort_inspection_failed", "error": str(exc)}
            )
        else:
            sys.stderr.write(f"Error inspecting cohort at {args.cohort_dir}: {exc}\n")
        return 2

    # Load registry manifest if present (fail closed if corrupt or missing)
    reg_manifest = None
    if args.registry_path:
        p_reg = Path(args.registry_path)
        if p_reg.is_file():
            try:
                reg_manifest = read_candidate_registry(p_reg, verify_hash=True)
            except Exception as exc:
                err_msg = f"Candidate registry validation failed at {args.registry_path}: {exc}"
                if args.json:
                    _print_json(
                        {
                            "status": "error",
                            "error_code": "registry_manifest_invalid",
                            "error": err_msg,
                        }
                    )
                else:
                    sys.stderr.write(f"Error: {err_msg}\n")
                return 2
        elif args.registry_path != DEFAULT_CANDIDATE_REGISTRY_PATH:
            err_msg = f"Candidate registry manifest not found at {args.registry_path}"
            if args.json:
                _print_json(
                    {
                        "status": "error",
                        "error_code": "registry_manifest_not_found",
                        "error": err_msg,
                    }
                )
            else:
                sys.stderr.write(f"Error: {err_msg}\n")
            return 2

    operator = args.operator
    decision = args.decision
    rationale = args.rationale

    is_interactive = args.interactive or (
        decision is None and hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
    )

    if is_interactive:
        try:
            operator, typed_decision, rationale = _prompt_operator_interactive(
                inspection, operator, decision, rationale
            )
        except KeyboardInterrupt, EOFError:
            sys.stdout.write("\nReview operation cancelled by operator.\n")
            return 1
    else:
        if decision is None:
            err_payload = {
                "status": "error",
                "error_code": "decision_required_in_non_interactive_mode",
                "message": "--decision is required in batch / non-interactive mode",
            }
            if args.json:
                _print_json(err_payload)
            else:
                sys.stderr.write("Error: --decision is required in batch / non-interactive mode.\n")
            return 2

        typed_decision = (
            "approved_for_canary"
            if decision == "approved_for_canary"
            else "rejected"
            if decision == "rejected"
            else "held"
        )
        if not operator:
            operator = "operator-lead-001"
        if not rationale:
            rationale = (
                f"Batch review sign-off ({typed_decision}) under Candidate Registry Manifest v2"
            )

    # If decision is approved_for_canary, prerequisite gates must pass
    if (
        typed_decision == "approved_for_canary"
        and not inspection.prerequisite_checklist.all_gates_passed
    ):
        err_msg = "Cannot approve for canary staging: prerequisite gates failed: " + ", ".join(
            inspection.prerequisite_checklist.failure_reasons
        )
        if args.json:
            _print_json(
                {
                    "status": "error",
                    "error_code": "prerequisite_gates_failed",
                    "reasons": inspection.prerequisite_checklist.failure_reasons,
                    "message": err_msg,
                }
            )
        else:
            sys.stderr.write(f"Error: {err_msg}\n")
        return 2

    try:
        dec_art, man_art, summary = stage_canary_candidates(
            decision=typed_decision,
            operator_id=operator,
            rationale=rationale,
            inspection=inspection,
            registry_manifest=reg_manifest,
            output_dir=args.output_dir,
        )
        saved_hashes = save_staging_artifacts(args.output_dir, dec_art, man_art, summary)
    except (DomainViolation, ValueError) as exc:
        if args.json:
            _print_json({"status": "error", "error_code": "staging_failed", "error": str(exc)})
        else:
            sys.stderr.write(f"Error executing canary staging: {exc}\n")
        return 2

    # Optional SQLite recording
    if args.review_path:
        try:
            report_p = args.cohort_dir / "paper-cohort-readiness-report.json"
            if not report_p.is_file():
                report_p = args.cohort_dir / "paper-cohort-maturation-report.json"
            readiness_report = _load_report(report_p)
            legacy_checkpoint = create_paper_review_checkpoint(
                readiness_report,
                review_id=dec_art.decision_id,
                reviewer_id=operator,
                reviewed_at=datetime.now(UTC),
                decision="accept_paper_observation"
                if typed_decision == "approved_for_canary"
                else "reject",
                review_notes=rationale,
            )
            SqlitePaperReviews(args.review_path).append(legacy_checkpoint)
        except Exception as exc:
            logger.warning("Could not record review to sqlite at %s: %s", args.review_path, exc)

    if args.json:
        out_data = {
            "status": "success",
            "decision": typed_decision,
            "operator_id": operator,
            "decision_id": dec_art.decision_id,
            "manifest_hash": man_art.manifest_hash,
            "cryptographic_signature": man_art.cryptographic_signature,
            "output_dir": str(args.output_dir),
            "artifact_hashes": saved_hashes,
        }
        _print_json(out_data)
        return 0

    sys.stdout.write("\n=== PHASE 269 OPERATOR REVIEW & CANARY STAGING COMPLETED ===\n")
    sys.stdout.write(f"Decision:               {typed_decision}\n")
    sys.stdout.write(f"Operator ID:            {operator}\n")
    sys.stdout.write(f"Decision ID:            {dec_art.decision_id}\n")
    sys.stdout.write(f"Output Directory:       {args.output_dir}\n")
    sys.stdout.write(f"Staged Manifest Hash:   {man_art.manifest_hash}\n")
    sys.stdout.write(f"Cryptographic Sig:      {man_art.cryptographic_signature}\n\n")
    sys.stdout.write("Generated Artifacts:\n")
    for name, fhash in sorted(saved_hashes.items()):
        sys.stdout.write(f"  {name:<32} {fhash}\n")
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for paper review CLI supporting both legacy and Phase 269 workflows."""
    args_list = sys.argv[1:] if argv is None else list(argv)
    if any(arg in args_list for arg in ("--report-path", "--review-id")):
        return _run_legacy_review(args_list)
    return _run_operator_staging_cli(args_list)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
