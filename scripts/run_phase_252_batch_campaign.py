"""Standalone CLI runner for Phase 252 Multi-Asset Strategy Generation Batch Campaign."""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.creator_staging_probe import (  # noqa: E402
    DEFAULT_BUNDLE_HASH,
    DEFAULT_REGISTRY_HASH,
)
from autonomous_futures.phase_252_batch import (  # noqa: E402
    PHASE_252_DEFAULT_ASSETS,
    PHASE_252_DEFAULT_CAMPAIGN_ID,
    PHASE_252_DEFAULT_CAPITAL_USD,
    PHASE_252_DEFAULT_MODEL_ID,
    execute_phase_252_batch_campaign,
)
from autonomous_futures.research.google_ai_studio_provider import (  # noqa: E402
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    _sanitize_error_text,
)
from autonomous_futures.staging_preflight import ALLOWED_GEMMA_MODELS  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute Phase 252 bounded multi-asset strategy generation batch campaign."
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
        help="Explicit Google AI Studio API key (in-memory only)",
    )
    parser.add_argument(
        "--base-url",
        default=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        help="Provider base URL",
    )
    parser.add_argument(
        "--model-id",
        default=PHASE_252_DEFAULT_MODEL_ID,
        choices=ALLOWED_GEMMA_MODELS,
        help="Pinned Gemma 4 model ID",
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        default=list(PHASE_252_DEFAULT_ASSETS),
        help="Target asset symbols (default: BTCUSDT ETHUSDT SOLUSDT DOGEUSDT)",
    )
    parser.add_argument(
        "--capital-usd",
        type=Decimal,
        default=PHASE_252_DEFAULT_CAPITAL_USD,
        help="Baseline starting capital in USDT (default: 100)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Must be 0 for bounded campaign",
    )
    parser.add_argument(
        "--fallback-provider",
        action="store_true",
        help="Must not be set",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("artifacts/research/phase252"),
        help="Directory to persist candidate artifacts, trials, and summary",
    )
    parser.add_argument(
        "--campaign-id",
        default=PHASE_252_DEFAULT_CAMPAIGN_ID,
        help="Campaign identifier for batch generation",
    )
    parser.add_argument(
        "--bundle-hash",
        default=DEFAULT_BUNDLE_HASH,
        help="Pinned research bundle hash",
    )
    parser.add_argument(
        "--registry-hash",
        default=DEFAULT_REGISTRY_HASH,
        help="Pinned dataset registry hash",
    )
    parser.add_argument(
        "--inter-request-sleep",
        type=float,
        default=0.0,
        help="Sleep duration in seconds between consecutive requests (default: 0.0)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    try:
        summary = execute_phase_252_batch_campaign(
            credential_dir=args.credential_dir,
            api_key=args.api_key,
            base_url=args.base_url,
            model_id=args.model_id,
            assets=args.assets,
            starting_capital_usd=args.capital_usd,
            max_retries=args.max_retries,
            fallback_provider=args.fallback_provider,
            evidence_root=args.evidence_dir,
            campaign_id=args.campaign_id,
            bundle_hash=args.bundle_hash,
            dataset_registry_hash=args.registry_hash,
            inter_request_sleep_seconds=args.inter_request_sleep,
        )
    except (OSError, ValueError) as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "invalid_input", "message": sanitized}))
        return 2
    except RuntimeError as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "runtime_error", "message": sanitized}))
        return 3
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "batch_execution_failed", "message": sanitized}))
        return 3

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["main"]
