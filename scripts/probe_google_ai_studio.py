"""Bounded Google AI Studio single diagnostic probe for Phase 243."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import httpx  # noqa: E402

from autonomous_futures.research.creator_batch import run_creator_batch  # noqa: E402
from autonomous_futures.research.creator_batch_persistence import (  # noqa: E402
    persist_creator_batch_trials,
)
from autonomous_futures.research.creator_generator import (  # noqa: E402
    CreatorGenerationRequest,
    CreatorGenerator,
)
from autonomous_futures.research.creator_prompts import (  # noqa: E402
    build_creator_proposal_messages,
)
from autonomous_futures.research.google_ai_studio_provider import (  # noqa: E402
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    GoogleAIStudioJsonClient,
    GoogleAIStudioModelId,
    GoogleAIStudioProposalTransport,
    GoogleAIStudioProviderConfig,
)

BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
SYMBOL = "DOGEUSDT"
CAMPAIGN_ID = "creator-batch-20260903-012"
RUN_ID = "run-doge-google-gemma-20260903-012"
MODEL_ID: GoogleAIStudioModelId = "gemma-4-31b-it"


def resolve_credential() -> str:
    """Resolve Google AI Studio / Gemini API credential from environment or user profile."""
    # 1. Process environment variables
    for var in ("GEMINI_API_KEY", "GOOGLE_AI_STUDIO_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()

    # 2. Local repository .env
    repo_env = Path(".env")
    if repo_env.is_file():
        for line in repo_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for var in ("GEMINI_API_KEY", "GOOGLE_AI_STUDIO_API_KEY", "GOOGLE_API_KEY"):
                if line.startswith(f"{var}="):
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val:
                        return val

    # 3. User home directory .env
    home_env = Path.home() / ".env"
    if home_env.is_file():
        for line in home_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for var in ("GEMINI_API_KEY", "GOOGLE_AI_STUDIO_API_KEY", "GOOGLE_API_KEY"):
                if line.startswith(f"{var}="):
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val:
                        return val

    # 4. User profile OAuth credentials in ~/.gemini
    gemini_oauth = Path.home() / ".gemini" / "oauth_creds.json"
    if gemini_oauth.is_file():
        try:
            creds = json.loads(gemini_oauth.read_text(encoding="utf-8"))
            token = creds.get("access_token")
            if token and isinstance(token, str) and token.strip():
                return token.strip()
        except Exception:
            pass

    raise RuntimeError(
        "No Google AI Studio / Gemini credential found in environment, .env, or user profile."
    )


def main() -> int:
    try:
        api_key = resolve_credential()
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "missing_api_key",
                    "message": str(exc),
                }
            )
        )
        return 1

    # Historical forbidden candidate IDs (from Phase 241 and prior campaigns)
    forbidden_ids = (
        "cand-148b5e15c0985f8e513f20636d8330822198c63759f95a946e866c90723291ad",
        "cand-38c598ba88be7141cc2a361daedc3f68fc30ce2ceeceee7e181f3e77b3190f38",
        "cand-d1955931522fe61c0c45052b17bbb1b1afebe92af6b7bddf887fa47f8953f744",
        "cand-febf9237c4a904eda69fb122083bc2f1297640d2094cd7844bb5caa906d014f4",
    )

    request = CreatorGenerationRequest(
        research_run_id=RUN_ID,
        input_evidence_refs=(f"bundle/{BUNDLE_HASH}",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
        forbidden_candidate_ids=forbidden_ids,
    )

    system_msg, user_msg = build_creator_proposal_messages(
        request, bundle_hash=BUNDLE_HASH, symbol=SYMBOL
    )

    config = GoogleAIStudioProviderConfig(
        base_url=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        api_key=api_key,
        model_id=MODEL_ID,
    )

    evidence_root = Path("artifacts/research/phase243")
    evidence_root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)

    # Execute single bounded probe (max_retries=0, fallback_provider=false)
    with httpx.Client(timeout=30.0) as http_client:
        json_client = GoogleAIStudioJsonClient(config=config, client=http_client)
        transport = GoogleAIStudioProposalTransport(
            client=json_client,
            system_prompt=str(system_msg["content"]),
            user_prompt_builder=lambda _: str(user_msg["content"]),
            temperature=0.2,
            max_output_tokens=2048,
        )
        generator = CreatorGenerator(transport=transport)
        result = run_creator_batch(
            (request,),
            generator=generator,
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=REGISTRY_HASH,
            creator_run_id=CAMPAIGN_ID,
            research_seed=20260903,
            created_at=now,
        )

    # Persist immutable evidence
    persisted = persist_creator_batch_trials(result, root=evidence_root / "trials", recorded_at=now)
    trial = result.trials[0]

    summary: dict[str, object] = {
        "campaign_id": CAMPAIGN_ID,
        "research_run_id": RUN_ID,
        "model_id": MODEL_ID,
        "request_count": 1,
        "max_retries": 0,
        "fallback_provider": False,
        "decision": trial.decision,
        "reason_codes": trial.reason_codes,
        "schema_diagnostics": trial.schema_diagnostics,
        "provider_metadata": trial.provider_metadata,
        "candidate_id": trial.candidate_id,
        "candidate_artifact_hash": trial.candidate_artifact_hash,
        "persisted_evidence_hash": persisted[0].evidence_hash if persisted else None,
        "safety_state": {
            "promotion_state": result.promotion_state,
            "paper_activation": result.paper_activation,
            "execution_authority": result.execution_authority,
            "exchange_access": result.exchange_access,
            "orders": 0,
        },
    }

    summary_path = evidence_root / "campaign-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
