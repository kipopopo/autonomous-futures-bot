"""Dedicated operator CLI probe runner for Kainode staging Creator diagnostic probe."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.creator_staging_probe import (  # noqa: E402
    DEFAULT_CAMPAIGN_ID,
    DEFAULT_PINNED_MODEL_ID,
    DEFAULT_RUN_ID,
    execute_creator_staging_probe,
)
from autonomous_futures.research.google_ai_studio_provider import (  # noqa: E402
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    _sanitize_error_text,
)
from autonomous_futures.staging_preflight import ALLOWED_GEMMA_MODELS  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute single bounded Creator diagnostic probe on Kainode staging."
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
        "--api-key",
        default=None,
        help="Explicit Google AI Studio API key (kept in memory only)",
    )
    parser.add_argument(
        "--base-url",
        default=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        help="Provider base URL",
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_PINNED_MODEL_ID,
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
        "--evidence-dir",
        type=Path,
        default=Path("artifacts/research/phase249"),
        help="Directory to persist trial evidence and campaign summary",
    )
    parser.add_argument(
        "--campaign-id",
        default=DEFAULT_CAMPAIGN_ID,
        help="Campaign identifier for probe trial",
    )
    parser.add_argument(
        "--run-id",
        default=DEFAULT_RUN_ID,
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
        summary = execute_creator_staging_probe(
            credential_dir=args.credential_dir,
            api_key=args.api_key,
            base_url=args.base_url,
            model_id=args.model_id,
            max_retries=args.max_retries,
            fallback_provider=args.fallback_provider,
            evidence_root=args.evidence_dir,
            campaign_id=args.campaign_id,
            run_id=args.run_id,
        )
    except (OSError, ValueError) as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "invalid_input", "message": sanitized}))
        return 2
    except RuntimeError as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "probe_blocked", "message": sanitized}))
        return 3
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "unexpected_error", "message": sanitized}))
        return 3

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["main"]
