"""Phase 269: Operator Human Review Governance CLI & Canary Staging Packaging.

Inspects mature paper trading cohorts (Phase 268 or custom), evaluates candidate performance
breakdowns, enforces prerequisite gates (ready_for_human_review, zero blocked, all
mature/healthy, exact double-entry accounting drift < 1e-15, margin <= 80%, reserve >= 20%),
records cryptographically signed human review decisions, and packages canary-staging
manifests under Candidate Registry Manifest Version 2.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure src/ and repo root are importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)
from autonomous_futures.paper.review_cli import main as review_cli_main  # noqa: E402
from autonomous_futures.paper.staging import (  # noqa: E402
    DEFAULT_PHASE268_COHORT_DIR,
    DEFAULT_PHASE269_OUTPUT_DIR,
)

logger = logging.getLogger("run_phase_269_human_review_staging")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 269 runner."""
    parser = argparse.ArgumentParser(
        description="Phase 269 Operator Human Review Governance & Canary Staging Packaging Runner."
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
        type=str,
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
        help="Operator identifier (default: operator-lead-001 in non-interactive batch)",
    )
    parser.add_argument(
        "--rationale",
        "--review-notes",
        type=str,
        default=None,
        dest="rationale",
        help="Operator review rationale or sign-off notes",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Force interactive operator prompts",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON summary to stdout",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    return parser


def run_phase_269_human_review_staging(
    cohort_dir: Path | str = DEFAULT_PHASE268_COHORT_DIR,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    output_dir: Path | str = DEFAULT_PHASE269_OUTPUT_DIR,
    decision: str | None = None,
    operator: str | None = None,
    rationale: str | None = None,
    interactive: bool = False,
    json_output: bool = False,
) -> int:
    """Execute deterministic Phase 269 review staging workflow."""
    argv: list[str] = [
        "--cohort-dir",
        str(cohort_dir),
        "--registry-path",
        str(registry_path),
        "--output-dir",
        str(output_dir),
    ]
    if decision:
        argv.extend(["--decision", decision])
    if operator:
        argv.extend(["--operator", operator])
    if rationale:
        argv.extend(["--rationale", rationale])
    if interactive:
        argv.append("--interactive")
    if json_output:
        argv.append("--json")

    return review_cli_main(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for Phase 269 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return run_phase_269_human_review_staging(
            cohort_dir=args.cohort_dir,
            registry_path=args.registry_path,
            output_dir=args.output_dir,
            decision=args.decision,
            operator=args.operator,
            rationale=args.rationale,
            interactive=args.interactive,
            json_output=args.json,
        )
    except KeyboardInterrupt:
        logger.info("Human review staging cancelled by operator")
        return 0
    except Exception as exc:
        logger.error("Human review staging failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
