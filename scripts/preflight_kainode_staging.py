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
        description="Verify Kainode staging credential delivery and offline invariants."
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
    return 0 if report.ready else 3


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["main"]
