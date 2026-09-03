"""Standalone operator CLI preflight check for Kainode staging environment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.creator_staging_probe import execute_creator_staging_probe  # noqa: E402
from autonomous_futures.research.google_ai_studio_provider import (  # noqa: E402
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    _sanitize_error_text,
)
from autonomous_futures.staging_preflight import (  # noqa: E402
    ALLOWED_GEMMA_MODELS,
    DEFAULT_ENCRYPTED_SOURCE_PATH,
    validate_staging_environment,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Kainode staging credentials and execute Creator probe."
    )
    parser.add_argument(
        "--source-credential-path",
        type=Path,
        default=DEFAULT_ENCRYPTED_SOURCE_PATH,
        help="Path to root-encrypted credential file",
    )
    parser.add_argument(
        "--credential-dir",
        type=Path,
        default=(
            Path(os.environ["CREDENTIALS_DIRECTORY"])
            if "CREDENTIALS_DIRECTORY" in os.environ
            else None
        ),
        help="Path to systemd decrypted runtime credentials directory",
    )
    parser.add_argument(
        "--base-url",
        default=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        help="Provider base URL",
    )
    parser.add_argument(
        "--model-id",
        default="gemma-4-31b-it",
        choices=ALLOWED_GEMMA_MODELS,
        help="Pinned Gemma 4 model ID",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Must be 0 for single probe",
    )
    parser.add_argument(
        "--fallback-provider",
        action="store_true",
        help="Must not be set",
    )
    parser.add_argument(
        "--skip-source-check",
        action="store_true",
        help="Skip checking encrypted source store on disk",
    )
    parser.add_argument(
        "--execute-probe",
        dest="execute_probe",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Execute single Creator diagnostic probe following successful preflight",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("artifacts/research/phase249"),
        help="Directory to persist trial evidence and campaign summary",
    )
    parser.add_argument(
        "--campaign-id",
        default="creator-batch-20260903-phase249",
        help="Campaign identifier for probe trial",
    )
    parser.add_argument(
        "--run-id",
        default="run-doge-google-gemma-20260903-phase249",
        help="Research run identifier for probe trial",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    try:
        report = validate_staging_environment(
            source_credential_path=args.source_credential_path,
            credential_dir=args.credential_dir,
            base_url=args.base_url,
            model_id=args.model_id,
            max_retries=args.max_retries,
            fallback_provider=args.fallback_provider,
            skip_source_check=args.skip_source_check,
        )
    except (OSError, ValueError) as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "invalid_input", "message": sanitized}))
        return 2
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "unexpected_error", "message": sanitized}))
        return 2

    # Structured redacted JSON output
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    if not report.ready:
        return 3

    should_execute_probe = False
    if args.execute_probe is True:
        should_execute_probe = True
    elif args.execute_probe is False:
        should_execute_probe = False
    else:
        # Auto-detect staging service execution environment:
        # CREDENTIALS_DIRECTORY must be present in os.environ and contain runtime key,
        # and source credential path must match the default staging path.
        cred_dir_env = os.environ.get("CREDENTIALS_DIRECTORY")
        if (
            cred_dir_env
            and (Path(cred_dir_env) / "google_ai_studio_api_key").is_file()
            and args.source_credential_path == DEFAULT_ENCRYPTED_SOURCE_PATH
        ):
            should_execute_probe = True

    if not should_execute_probe:
        return 0

    try:
        probe_summary = execute_creator_staging_probe(
            credential_dir=args.credential_dir,
            base_url=args.base_url,
            model_id=args.model_id,
            max_retries=args.max_retries,
            fallback_provider=args.fallback_provider,
            evidence_root=args.evidence_dir,
            campaign_id=args.campaign_id,
            run_id=args.run_id,
        )
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "probe_execution_failed", "message": sanitized}))
        return 3

    print(json.dumps(probe_summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["main"]
