"""Bounded Multi-Asset Strategy Generation Batch Campaign for Phase 252.

Orchestrates strategy proposal generation across 4 major asset pairs (BTCUSDT,
ETHUSDT, SOLUSDT, DOGEUSDT) specifically tailored for a 100 USDT starting equity base
with confidence-scaled dynamic leverage rules, under strict bounded single-shot probe
parameters (max_retries=0, fallback_provider=False, model gemma-4-31b-it), tmpfs credential
resolution, read-only filesystem resilience, and offline safety invariants (orders=0,
exchange_access=False, execution_authority=False, promotion_state='unpromoted').
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from .creator_staging_probe import (
    _SECRET_PATTERN,
    DEFAULT_BUNDLE_HASH,
    DEFAULT_REGISTRY_HASH,
    FORBIDDEN_CANDIDATE_IDS,
    assert_offline_safety_invariants,
    resolve_staging_credential,
    validate_probe_parameters,
)
from .research.creator_artifacts import (
    write_creator_candidate_artifact,
)
from .research.creator_batch import (
    CreatorBatchResult,
    run_creator_batch,
)
from .research.creator_batch_persistence import (
    persist_creator_batch_trials,
)
from .research.creator_generator import (
    CreatorGenerationRequest,
    CreatorGenerator,
    ProposalTransport,
)
from .research.creator_prompts import (
    CAPITAL_AND_LEVERAGE_GUIDELINES,
    build_phase_252_proposal_messages,
)
from .research.google_ai_studio_provider import (
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    GoogleAIStudioJsonClient,
    GoogleAIStudioModelId,
    GoogleAIStudioProposalTransport,
    GoogleAIStudioProviderConfig,
)

PHASE_252_DEFAULT_ASSETS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
)
PHASE_252_DEFAULT_CAPITAL_USD: Decimal = Decimal("100")
PHASE_252_DEFAULT_CAMPAIGN_ID: str = "creator-batch-20260904-phase252"
PHASE_252_DEFAULT_MODEL_ID: GoogleAIStudioModelId = "gemma-4-31b-it"
PHASE_252_DEFAULT_BUNDLE_HASH: str = DEFAULT_BUNDLE_HASH
PHASE_252_DEFAULT_REGISTRY_HASH: str = DEFAULT_REGISTRY_HASH

_SYMBOL_RE = re.compile(r"^[A-Z0-9]+$")


def make_phase_252_run_id(symbol: str, campaign_id: str) -> str:
    """Derive a deterministic, valid research_run_id conforming to domain contracts."""
    cleaned_sym = re.sub(r"[^a-z0-9]", "", symbol.lower())
    cleaned_camp = re.sub(r"[^a-z0-9-]", "-", campaign_id.lower().strip()).strip("-")
    # Contract: ^run-[a-z0-9][a-z0-9-]{0,63}$
    suffix = f"{cleaned_sym}-{cleaned_camp}"[:60].strip("-")
    return f"run-{suffix}"


def build_phase_252_batch_requests(
    assets: Sequence[str] = PHASE_252_DEFAULT_ASSETS,
    *,
    campaign_id: str = PHASE_252_DEFAULT_CAMPAIGN_ID,
    bundle_hash: str = PHASE_252_DEFAULT_BUNDLE_HASH,
    forbidden_ids: Sequence[str] = FORBIDDEN_CANDIDATE_IDS,
) -> tuple[tuple[CreatorGenerationRequest, ...], dict[str, str]]:
    """Build bounded generation requests for each asset and return (requests, symbol_by_run_id)."""
    if not assets:
        raise ValueError("assets sequence cannot be empty")
    seen_symbols: set[str] = set()
    requests: list[CreatorGenerationRequest] = []
    symbol_by_run_id: dict[str, str] = {}
    forbidden_tuple = tuple(sorted(set(forbidden_ids)))

    for asset in assets:
        sym = asset.strip().upper()
        if not _SYMBOL_RE.fullmatch(sym):
            raise ValueError(f"Invalid asset symbol: {asset!r}")
        if sym in seen_symbols:
            raise ValueError(f"Duplicate asset symbol in batch: {sym}")
        seen_symbols.add(sym)

        run_id = make_phase_252_run_id(sym, campaign_id)
        req = CreatorGenerationRequest(
            research_run_id=run_id,
            input_evidence_refs=(f"bundle/{bundle_hash}",),
            output_schema_id="creator-proposal-v1",
            attempt=1,
            forbidden_candidate_ids=forbidden_tuple,
        )
        requests.append(req)
        symbol_by_run_id[run_id] = sym

    return tuple(requests), symbol_by_run_id


def execute_phase_252_batch_campaign(
    *,
    credential_dir: Path | None = None,
    api_key: str | None = None,
    base_url: str = GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    model_id: GoogleAIStudioModelId = PHASE_252_DEFAULT_MODEL_ID,
    assets: Sequence[str] = PHASE_252_DEFAULT_ASSETS,
    starting_capital_usd: Decimal | float | int | str = PHASE_252_DEFAULT_CAPITAL_USD,
    max_retries: int = 0,
    fallback_provider: bool = False,
    evidence_root: Path = Path("artifacts/research/phase252"),
    campaign_id: str = PHASE_252_DEFAULT_CAMPAIGN_ID,
    bundle_hash: str = PHASE_252_DEFAULT_BUNDLE_HASH,
    dataset_registry_hash: str = PHASE_252_DEFAULT_REGISTRY_HASH,
    forbidden_ids: Sequence[str] = FORBIDDEN_CANDIDATE_IDS,
    http_client: httpx.Client | None = None,
    transport_override: ProposalTransport | None = None,
    env: Mapping[str, str] | None = None,
    inter_request_sleep_seconds: float = 0.0,
) -> dict[str, Any]:
    """Execute the bounded Phase 252 4-asset batch campaign and return structured summary."""
    # 1. Enforce strict single-probe parameter bounds
    validate_probe_parameters(
        base_url=base_url,
        model_id=model_id,
        max_retries=max_retries,
        fallback_provider=fallback_provider,
    )

    # 2. Validate capital baseline
    try:
        capital_dec = Decimal(str(starting_capital_usd))
    except Exception as exc:
        raise ValueError(
            f"starting_capital_usd must be a valid numeric amount: {starting_capital_usd!r}"
        ) from exc
    if capital_dec <= 0:
        raise ValueError(f"starting_capital_usd must be positive, got {capital_dec}")

    # 3. Enforce offline safety invariants (zero Binance credentials, zero execution authority)
    assert_offline_safety_invariants(credential_dir=credential_dir, env=env)

    # 4. Construct generation requests and dynamic run_id -> symbol mapping
    requests, symbol_by_run_id = build_phase_252_batch_requests(
        assets=assets,
        campaign_id=campaign_id,
        bundle_hash=bundle_hash,
        forbidden_ids=forbidden_ids,
    )

    # 5. Resolve credentials in memory (unless transport_override provided)
    owns_client = False
    client = http_client
    now = datetime.now(UTC)

    try:
        if transport_override is not None:
            transport: ProposalTransport = transport_override
        else:
            resolved_api_key = resolve_staging_credential(
                credential_dir=credential_dir,
                explicit_key=api_key,
                env=env,
            )

            config = GoogleAIStudioProviderConfig(
                base_url=base_url,
                api_key=resolved_api_key,
                model_id=model_id,
            )
            if client is None:
                client = httpx.Client(timeout=30.0)
                owns_client = True

            json_client = GoogleAIStudioJsonClient(config=config, client=client)

            # Scrub raw API key from local function scope immediately
            del resolved_api_key

            # Get system prompt from representative proposal messages
            sample_system_msg, _ = build_phase_252_proposal_messages(
                requests[0],
                bundle_hash=bundle_hash,
                symbol=symbol_by_run_id[requests[0].research_run_id],
                starting_capital_usd=capital_dec,
            )
            system_prompt_str = str(sample_system_msg["content"])

            # Build user prompt builder with dynamic run_id -> symbol mapping
            def dynamic_user_prompt_builder(req: CreatorGenerationRequest) -> str:
                target_symbol = symbol_by_run_id.get(req.research_run_id, "BTCUSDT")
                _, user_msg = build_phase_252_proposal_messages(
                    req,
                    bundle_hash=bundle_hash,
                    symbol=target_symbol,
                    starting_capital_usd=capital_dec,
                )
                return str(user_msg["content"])

            base_transport = GoogleAIStudioProposalTransport(
                client=json_client,
                system_prompt=system_prompt_str,
                user_prompt_builder=dynamic_user_prompt_builder,
                temperature=0.2,
                max_output_tokens=2048,
            )

            if inter_request_sleep_seconds > 0:
                first_call = True

                def paced_transport(req: CreatorGenerationRequest) -> Mapping[str, object]:
                    nonlocal first_call
                    if not first_call and inter_request_sleep_seconds > 0:
                        time.sleep(inter_request_sleep_seconds)
                    first_call = False
                    return base_transport(req)

                transport = paced_transport
            else:
                transport = base_transport

        generator = CreatorGenerator(transport=transport)

        # 6. Execute bounded batch across the target assets
        result: CreatorBatchResult = run_creator_batch(
            requests,
            generator=generator,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id=campaign_id,
            research_seed=20260904,
            created_at=now,
        )
    finally:
        if owns_client and client is not None:
            client.close()

    # 7. Persist candidate artifacts and trials (with read-only filesystem handling)
    persistence_error: str | None = None
    persisted_evidence_hashes: dict[str, str] = {}

    try:
        # Check / create base directory
        evidence_root.mkdir(parents=True, exist_ok=True)

        # Persist accepted candidate artifacts
        if result.accepted_candidates:
            candidates_dir = evidence_root / "candidates"
            candidates_dir.mkdir(parents=True, exist_ok=True)
            for candidate in result.accepted_candidates:
                candidate_path = candidates_dir / f"{candidate.candidate_id}.json"
                write_creator_candidate_artifact(candidate_path, candidate)

        # Persist batch trial evidence
        trials_dir = evidence_root / "trials"
        trials_dir.mkdir(parents=True, exist_ok=True)
        persisted_trials = persist_creator_batch_trials(result, root=trials_dir, recorded_at=now)
        for trial_ev in persisted_trials:
            persisted_evidence_hashes[trial_ev.trial.research_run_id] = trial_ev.evidence_hash

    except OSError as exc:
        if exc.errno == 30 or "Read-only file system" in str(exc):
            persistence_error = "read_only_filesystem_sandboxed"
        else:
            raise

    # 8. Compile structured campaign summary
    trials_summary: list[dict[str, Any]] = []
    for trial in result.trials:
        target_asset = symbol_by_run_id.get(trial.research_run_id, "UNKNOWN")
        trials_summary.append(
            {
                "asset": target_asset,
                "research_run_id": trial.research_run_id,
                "proposal_id": trial.proposal_id,
                "candidate_id": trial.candidate_id,
                "decision": trial.decision,
                "reason_codes": list(trial.reason_codes),
                "schema_diagnostics": list(trial.schema_diagnostics),
                "candidate_artifact_hash": trial.candidate_artifact_hash,
                "persisted_evidence_hash": persisted_evidence_hashes.get(trial.research_run_id),
                "provider_metadata": trial.provider_metadata,
            }
        )

    summary: dict[str, Any] = {
        "campaign_id": campaign_id,
        "model_id": model_id,
        "assets": list(assets),
        "starting_capital_usd": str(capital_dec),
        "bundle_hash": bundle_hash,
        "dataset_registry_hash": dataset_registry_hash,
        "request_count": len(requests),
        "max_retries": max_retries,
        "fallback_provider": fallback_provider,
        "total_trials": len(result.trials),
        "total_accepted": len(result.accepted_candidates),
        "accepted_candidate_ids": [cand.candidate_id for cand in result.accepted_candidates],
        "trials": trials_summary,
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
    "CAPITAL_AND_LEVERAGE_GUIDELINES",
    "PHASE_252_DEFAULT_ASSETS",
    "PHASE_252_DEFAULT_BUNDLE_HASH",
    "PHASE_252_DEFAULT_CAMPAIGN_ID",
    "PHASE_252_DEFAULT_CAPITAL_USD",
    "PHASE_252_DEFAULT_MODEL_ID",
    "PHASE_252_DEFAULT_REGISTRY_HASH",
    "build_phase_252_batch_requests",
    "execute_phase_252_batch_campaign",
    "make_phase_252_run_id",
]
