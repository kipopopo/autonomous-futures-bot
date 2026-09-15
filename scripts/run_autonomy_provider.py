"""scripts/run_autonomy_provider.py

Supported finite CLI entrypoint for autonomous provider-to-research orchestration (R1).
Replaces disposable smoke scripts with durable evidence capture:
- Preflights credentials safely without exposing secrets.
- Binds run ID, input evidence hashes, failure history, policy, and budget.
- Enforces zero retries and no provider fallback.
- Verifies checkpoints and rejects tampered or replayed checkpoints prior to network.
- Writes durable typed accepted artifacts and sanitized audit envelopes to approved storage.
- Verifies storage integrity on readback.
- Preserves rejected outcomes honestly without schema relaxation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# Ensure src/ is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.data.parquet import DataQualityError  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.research.autonomy_contracts import (  # noqa: E402
    FailureMemoryEntry,
    read_failure_learning_artifact,
    read_failure_memory_entry,
)
from autonomous_futures.research.provider_orchestration import (  # noqa: E402
    ProviderOrchestrationConfig,
    ProviderOrchestrationResult,
    execute_provider_orchestration,
)
from autonomous_futures.research_lab.model_policy import ResearchModelPolicy  # noqa: E402

FORBIDDEN_CREDENTIAL_FLAGS = (
    "--api-key",
    "--api_key",
    "--key",
    "-key",
    "--apikey",
    "--google-api-key",
    "--google_api_key",
    "--gemini-api-key",
    "--gemini_api_key",
    "--google-ai-studio-api-key",
    "--token",
    "--api-token",
    "-k",
)


def _check_forbidden_credential_flags(argv: Sequence[str]) -> bool:
    """Inspect raw CLI arguments for forbidden credential flags."""
    for arg in argv:
        prefix = arg.lower().split("=")[0].strip()
        if prefix in FORBIDDEN_CREDENTIAL_FLAGS:
            return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Autonomous Provider-to-Research Orchestration CLI Runner (R1)."
    )
    parser.add_argument(
        "--policy-file", type=Path, required=True, help="Path to ResearchModelPolicy JSON"
    )
    parser.add_argument(
        "--role",
        choices=("failure_analyst", "hypothesis_generator"),
        required=True,
        help="Embedded research role",
    )
    parser.add_argument("--research-run-id", required=True, help="Unique research run identifier")
    parser.add_argument(
        "--base-run-id", default=None, help="Base run ID (defaults to memory entry base_run_id)"
    )
    parser.add_argument("--symbol", required=True, help="Target market symbol (e.g. BTCUSDT)")
    parser.add_argument(
        "--evidence-root", type=Path, required=True, help="Durable evidence root directory"
    )
    parser.add_argument(
        "--failure-memory-file",
        type=Path,
        action="append",
        required=True,
        help="Path to FailureMemoryEntry JSON (can be specified multiple times)",
    )
    parser.add_argument(
        "--learning-artifact-file",
        type=Path,
        default=None,
        help="Path to FailureLearningArtifact JSON (required for hypothesis_generator)",
    )
    parser.add_argument("--bundle-hash", default=None, help="Pinned bundle SHA-256 hash")
    parser.add_argument(
        "--dataset-registry-hash", default=None, help="Pinned dataset registry SHA-256 hash"
    )
    parser.add_argument("--cycle-index", type=int, default=1, help="Cycle index (default: 1)")
    parser.add_argument(
        "--cycle-id", default=None, help="Cycle identifier (required for hypothesis_generator)"
    )
    parser.add_argument("--budget", type=int, default=1, help="Request budget count (default: 1)")
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Explicitly enable network execution (default is fail-closed dry-run)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if _check_forbidden_credential_flags(raw_argv):
        print(
            json.dumps(
                {
                    "error_code": "forbidden_cli_argument",
                    "status": "blocked",
                    "message": (
                        "Passing credentials via CLI flags is strictly forbidden. "
                        "Resolve credentials through supported environment variables."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    try:
        policy = ResearchModelPolicy.model_validate_json(
            args.policy_file.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error_code": "invalid_policy_file",
                    "status": "blocked",
                    "message": f"Could not load valid policy from {args.policy_file}: {exc}",
                }
            ),
            file=sys.stderr,
        )
        return 2

    # Load failure memory entries
    memory_entries: list[FailureMemoryEntry] = []
    for mem_path in args.failure_memory_file:
        try:
            entry = read_failure_memory_entry(mem_path)
            memory_entries.append(entry)
        except (OSError, DataQualityError, DomainViolation) as exc:
            print(
                json.dumps(
                    {
                        "error_code": "invalid_failure_memory",
                        "status": "blocked",
                        "message": f"Could not load valid failure memory from {mem_path}: {exc}",
                    }
                ),
                file=sys.stderr,
            )
            return 3

    # Load learning artifact if supplied
    learning_artifact = None
    if args.learning_artifact_file:
        try:
            learning_artifact = read_failure_learning_artifact(args.learning_artifact_file)
        except (OSError, DataQualityError, DomainViolation) as exc:
            print(
                json.dumps(
                    {
                        "error_code": "invalid_learning_artifact",
                        "status": "blocked",
                        "message": (
                            f"Could not load valid learning artifact from "
                            f"{args.learning_artifact_file}: {exc}"
                        ),
                    }
                ),
                file=sys.stderr,
            )
            return 3

    # Scope bindings
    base_run_id = args.base_run_id or memory_entries[0].base_run_id
    bundle_hash = args.bundle_hash or memory_entries[0].bundle_hash
    dataset_registry_hash = args.dataset_registry_hash or memory_entries[0].dataset_registry_hash
    cycle_id = args.cycle_id or (
        f"cycle-{args.symbol.lower()}-{args.cycle_index:03d}"
        if args.role == "hypothesis_generator"
        else None
    )

    try:
        config = ProviderOrchestrationConfig(
            research_run_id=args.research_run_id,
            base_run_id=base_run_id,
            role=args.role,
            symbol=args.symbol.upper(),
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            evidence_root=args.evidence_root,
            policy=policy,
            request_budget=args.budget,
            execute=args.execute,
            cycle_index=args.cycle_index,
            cycle_id=cycle_id,
        )
        result: ProviderOrchestrationResult = execute_provider_orchestration(
            config=config,
            failure_memory=memory_entries,
            learning_artifact=learning_artifact,
        )
    except (DataQualityError, DomainViolation) as exc:
        print(
            json.dumps(
                {
                    "error_code": "orchestration_contract_violation",
                    "status": "blocked",
                    "message": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 3
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error_code": "orchestration_error",
                    "status": "blocked",
                    "message": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 3

    summary = {
        "status": result.status,
        "decision": result.decision,
        "research_run_id": result.research_run_id,
        "base_run_id": result.base_run_id,
        "role": result.role,
        "symbol": result.symbol,
        "readback_verified": result.readback_verified,
        "reused_existing": result.reused_existing,
        "requests_consumed": result.requests_consumed,
        "reason_codes": list(result.reason_codes),
        "schema_diagnostics": list(result.schema_diagnostics),
        "learning_id": result.learning_artifact.learning_id if result.learning_artifact else None,
        "plan_id": result.research_plan.plan_id if result.research_plan else None,
        "audit_envelope_hash": result.audit_envelope.envelope_hash
        if result.audit_envelope
        else None,
        "completed_at": result.completed_at.isoformat(),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result.status in ("succeeded", "reused_checkpoint", "prepared") else 3


if __name__ == "__main__":
    sys.exit(main())
