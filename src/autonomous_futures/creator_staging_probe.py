"""Bounded Creator diagnostic probe for staging environment (Phase 249).

Executes exactly one finite, bounded Creator diagnostic probe against Google AI Studio
using pinned model gemma-4-31b-it under strict single-probe parameters (max_retries=0,
fallback_provider=False) and offline safety invariants (orders=0, exchange_access=False).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .research.creator_batch import run_creator_batch
from .research.creator_batch_persistence import (
    persist_creator_batch_trials,
)
from .research.creator_generator import (
    CreatorGenerationRequest,
    CreatorGenerator,
    ProposalTransport,
)
from .research.creator_prompts import build_creator_proposal_messages
from .research.google_ai_studio_provider import (
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    GoogleAIStudioJsonClient,
    GoogleAIStudioModelId,
    GoogleAIStudioProposalTransport,
    GoogleAIStudioProviderConfig,
)
from .staging_preflight import (
    ALLOWED_GEMMA_MODELS,
    RUNTIME_CREDENTIAL_NAME,
    validate_offline_safety,
)

DEFAULT_BUNDLE_HASH: str = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
DEFAULT_REGISTRY_HASH: str = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"
DEFAULT_SYMBOL: str = "DOGEUSDT"
DEFAULT_CAMPAIGN_ID: str = "creator-batch-20260903-phase249"
DEFAULT_RUN_ID: str = "run-doge-google-gemma-20260903-phase249"
DEFAULT_PINNED_MODEL_ID: GoogleAIStudioModelId = "gemma-4-31b-it"

FORBIDDEN_CANDIDATE_IDS: tuple[str, ...] = (
    "cand-148b5e15c0985f8e513f20636d8330822198c63759f95a946e866c90723291ad",
    "cand-38c598ba88be7141cc2a361daedc3f68fc30ce2ceeceee7e181f3e77b3190f38",
    "cand-d1955931522fe61c0c45052b17bbb1b1afebe92af6b7bddf887fa47f8953f744",
    "cand-febf9237c4a904eda69fb122083bc2f1297640d2094cd7844bb5caa906d014f4",
)

_SECRET_PATTERN = re.compile(
    r"(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|Bearer\s+[A-Za-z0-9\-._~+/]+=*)",
    re.IGNORECASE,
)


def resolve_staging_credential(
    credential_dir: Path | None = None,
    credential_name: str = RUNTIME_CREDENTIAL_NAME,
    explicit_key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve Google AI Studio API credential with primary lookup in $CREDENTIALS_DIRECTORY."""
    if explicit_key and explicit_key.strip():
        key = explicit_key.strip()
        if len(key) < 20 or any(c.isspace() for c in key):
            raise ValueError("explicit_key has invalid format (must be >=20 non-whitespace chars)")
        return key

    environ = env if env is not None else os.environ

    # 1. Primary: credential_dir or $CREDENTIALS_DIRECTORY
    cred_dir = credential_dir
    if cred_dir is None and "CREDENTIALS_DIRECTORY" in environ:
        cred_dir = Path(environ["CREDENTIALS_DIRECTORY"])

    if cred_dir is not None:
        cred_file = cred_dir / credential_name
        if cred_file.is_file() and not cred_file.is_symlink():
            raw_key = cred_file.read_text(encoding="utf-8").strip()
            if not raw_key:
                raise ValueError("runtime credential file in CREDENTIALS_DIRECTORY is empty")
            if len(raw_key) < 20 or any(c.isspace() for c in raw_key):
                raise ValueError("runtime credential in CREDENTIALS_DIRECTORY has invalid format")
            return raw_key

    # 2. Secondary: Environment variables
    for var in ("GOOGLE_AI_STUDIO_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = environ.get(var)
        if val and val.strip():
            key = val.strip()
            if len(key) < 20 or any(c.isspace() for c in key):
                raise ValueError(f"{var} has invalid format")
            return key

    raise RuntimeError(
        "No valid Google AI Studio credential found in CREDENTIALS_DIRECTORY or environment."
    )


def validate_probe_parameters(
    *,
    base_url: str = GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    model_id: str = DEFAULT_PINNED_MODEL_ID,
    max_retries: int = 0,
    fallback_provider: bool = False,
) -> None:
    """Enforce strict single-probe parameters."""
    if max_retries != 0:
        raise ValueError(f"max_retries must be 0 for single probe, got {max_retries}")
    if fallback_provider:
        raise ValueError("fallback_provider must be False for single probe")
    if base_url.rstrip("/") != GOOGLE_AI_STUDIO_OPENAI_BASE_URL:
        raise ValueError(f"base_url must be {GOOGLE_AI_STUDIO_OPENAI_BASE_URL}, got {base_url}")
    if model_id not in ALLOWED_GEMMA_MODELS:
        raise ValueError(f"model_id must be in {ALLOWED_GEMMA_MODELS}, got {model_id}")


def assert_offline_safety_invariants(
    credential_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Assert zero Binance credentials or market execution authority before probe execution."""
    safety = validate_offline_safety(credential_dir=credential_dir, env=env)
    if safety.validation_error or safety.binance_keys_detected:
        raise RuntimeError(
            f"Offline safety violation: {safety.validation_error or 'Binance credentials detected'}"
        )


def execute_creator_staging_probe(
    *,
    credential_dir: Path | None = None,
    api_key: str | None = None,
    base_url: str = GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    model_id: GoogleAIStudioModelId = DEFAULT_PINNED_MODEL_ID,
    max_retries: int = 0,
    fallback_provider: bool = False,
    evidence_root: Path = Path("artifacts/research/phase249"),
    campaign_id: str = DEFAULT_CAMPAIGN_ID,
    run_id: str = DEFAULT_RUN_ID,
    bundle_hash: str = DEFAULT_BUNDLE_HASH,
    dataset_registry_hash: str = DEFAULT_REGISTRY_HASH,
    symbol: str = DEFAULT_SYMBOL,
    forbidden_ids: Sequence[str] = FORBIDDEN_CANDIDATE_IDS,
    http_client: httpx.Client | None = None,
    transport_override: ProposalTransport | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a single bounded Creator diagnostic probe and persist safe outcome evidence."""
    # 1. Enforce strict single-probe parameter bounds
    validate_probe_parameters(
        base_url=base_url,
        model_id=model_id,
        max_retries=max_retries,
        fallback_provider=fallback_provider,
    )

    # 2. Enforce offline safety invariants (zero Binance credentials, zero execution authority)
    assert_offline_safety_invariants(credential_dir=credential_dir, env=env)

    # 3. Resolve credential in memory
    resolved_api_key = resolve_staging_credential(
        credential_dir=credential_dir,
        explicit_key=api_key,
        env=env,
    )

    # 4. Construct generation request
    request = CreatorGenerationRequest(
        research_run_id=run_id,
        input_evidence_refs=(f"bundle/{bundle_hash}",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
        forbidden_candidate_ids=tuple(sorted(set(forbidden_ids))),
    )

    # 5. Build transport and generator
    owns_client = False
    client = http_client
    now = datetime.now(UTC)

    try:
        if transport_override is not None:
            transport = transport_override
        else:
            config = GoogleAIStudioProviderConfig(
                base_url=base_url,
                api_key=resolved_api_key,
                model_id=model_id,
            )
            if client is None:
                client = httpx.Client(timeout=30.0)
                owns_client = True

            system_msg, user_msg = build_creator_proposal_messages(
                request, bundle_hash=bundle_hash, symbol=symbol
            )
            json_client = GoogleAIStudioJsonClient(config=config, client=client)
            transport = GoogleAIStudioProposalTransport(
                client=json_client,
                system_prompt=str(system_msg["content"]),
                user_prompt_builder=lambda _: str(user_msg["content"]),
                temperature=0.2,
                max_output_tokens=2048,
            )

        # Immediate credential scrubbing from local scope
        del resolved_api_key

        generator = CreatorGenerator(transport=transport)

        # 6. Execute bounded single request
        result = run_creator_batch(
            (request,),
            generator=generator,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id=campaign_id,
            research_seed=20260903,
            created_at=now,
        )
    finally:
        if owns_client and client is not None:
            client.close()

    # 7. Persist immutable trial evidence
    persisted_trials = None
    persisted_evidence_hash = None
    persistence_error = None

    try:
        trials_dir = evidence_root / "trials"
        trials_dir.mkdir(parents=True, exist_ok=True)
        persisted_trials = persist_creator_batch_trials(result, root=trials_dir, recorded_at=now)
        if persisted_trials:
            persisted_evidence_hash = persisted_trials[0].evidence_hash
    except OSError as exc:
        if exc.errno == 30 or "Read-only file system" in str(exc):
            persistence_error = "read_only_filesystem_sandboxed"
        else:
            raise

    trial = result.trials[0]

    # 8. Compile structured campaign summary
    summary: dict[str, Any] = {
        "campaign_id": campaign_id,
        "research_run_id": run_id,
        "model_id": model_id,
        "request_count": 1,
        "max_retries": 0,
        "fallback_provider": False,
        "decision": trial.decision,
        "reason_codes": list(trial.reason_codes),
        "schema_diagnostics": list(trial.schema_diagnostics),
        "provider_metadata": trial.provider_metadata,
        "candidate_id": trial.candidate_id,
        "candidate_artifact_hash": trial.candidate_artifact_hash,
        "persisted_evidence_hash": persisted_evidence_hash,
        "persistence_status": (
            "persisted" if persistence_error is None else "read_only_filesystem_skipped"
        ),
        "safety_state": {
            "promotion_state": result.promotion_state,
            "paper_activation": result.paper_activation,
            "execution_authority": result.execution_authority,
            "exchange_access": result.exchange_access,
            "orders": 0,
        },
    }

    # 9. Verify zero secret leakage before disk persistence / return
    summary_serialized = json.dumps(summary, indent=2, sort_keys=True)
    if _SECRET_PATTERN.search(summary_serialized):
        raise RuntimeError("Secret pattern detected in campaign summary output")

    if persistence_error is None:
        try:
            summary_path = evidence_root / "campaign-summary.json"
            summary_path.write_text(summary_serialized + "\n", encoding="utf-8")
        except OSError as exc:
            if exc.errno == 30 or "Read-only file system" in str(exc):
                summary["persistence_status"] = "read_only_filesystem_skipped"
            else:
                raise

    return summary


__all__ = [
    "DEFAULT_BUNDLE_HASH",
    "DEFAULT_CAMPAIGN_ID",
    "DEFAULT_PINNED_MODEL_ID",
    "DEFAULT_REGISTRY_HASH",
    "DEFAULT_RUN_ID",
    "DEFAULT_SYMBOL",
    "FORBIDDEN_CANDIDATE_IDS",
    "assert_offline_safety_invariants",
    "execute_creator_staging_probe",
    "resolve_staging_credential",
    "validate_probe_parameters",
]
