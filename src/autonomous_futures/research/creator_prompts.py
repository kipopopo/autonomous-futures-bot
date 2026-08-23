"""Canonical prompt construction for the constrained Creator proposal schema."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from .creator_failure_feedback import CreatorQualificationFailureFeedback
from .creator_generator import CreatorGenerationRequest
from .feature_signals import SUPPORTED_FEATURES
from .learner_critic_evidence import LearnerCritiqueEvidence

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^[A-Z0-9]+$")
_SYSTEM_PROMPT = (
    "Return exactly one JSON object with keys proposal_id, research_run_id, hypothesis, "
    "expected_regime, novelty_reason, and strategy. The strategy object must contain "
    "dsl_version, strategy_id, family, universe, features, entry, exit, and vetoes. "
    "Use only approved StrategySpec features and bounded expressions. Never return "
    "markdown, code fences, prose, URLs, secrets, tools, or orders. strategy_id must "
    "start with cand- and research_run_id must match the supplied run. "
    "family must be one of regime_gated_breakout, range_mean_reversion, experimental; "
    f"features must use only {', '.join(sorted(SUPPORTED_FEATURES))}; each feature needs "
    'a positive lookback and shift >= 1; universe must use timeframe="5m" and '
    'regime_context_timeframe="15m". proposal_id must start with proposal- and '
    "use lowercase letters, digits, and hyphens only; dsl_version must be the integer 1; "
    "features must be a JSON array of objects; universe must contain a symbols array; "
    "entry and exit must each be objects with "
    'string keys "long" and "short", not strings; entry.long and entry.short must be '
    "strings; exit.long and exit.short must be strings; vetoes must be a non-empty array "
    "of strings. each condition must be feature_name operator numeric_threshold; join "
    "conditions only with and or; feature-to-feature comparisons are not allowed. "
    "expressions must reference the exact feature name declared in features; do not "
    "append lookback or shift."
)


def build_creator_proposal_messages(
    request: CreatorGenerationRequest, *, bundle_hash: str, symbol: str
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    if not _HASH.fullmatch(bundle_hash):
        raise ValueError("bundle_hash must be a lowercase SHA-256")
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("symbol must be uppercase alphanumeric")
    user_prompt = (
        f"research_run_id={request.research_run_id}; symbol={symbol}; "
        f"bundle_hash={bundle_hash}; output_schema={request.output_schema_id}; "
        f"input_evidence_refs={','.join(request.input_evidence_refs)}. "
        "Create one falsifiable strategy hypothesis for this exact evidence scope."
    )
    return (
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    )


def build_creator_revision_messages(
    request: CreatorGenerationRequest,
    *,
    bundle_hash: str,
    symbol: str,
    feedback: CreatorQualificationFailureFeedback,
    critique_evidence: LearnerCritiqueEvidence | None = None,
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    if feedback.bundle_hash != bundle_hash:
        raise ValueError("failure feedback bundle does not match prompt bundle")
    if critique_evidence is not None and (
        critique_evidence.bundle_hash != bundle_hash
        or critique_evidence.candidate_id != feedback.candidate_id
        or critique_evidence.candidate_artifact_hash != feedback.candidate_artifact_hash
        or critique_evidence.qualification_hash != feedback.qualification_hash
    ):
        raise ValueError("critic evidence does not match revision feedback")
    system, base_user = build_creator_proposal_messages(
        request, bundle_hash=bundle_hash, symbol=symbol
    )
    failed_gates = [
        {
            "gate_id": gate.gate_id,
            "reason_code": gate.reason_code,
            "observed": str(gate.observed) if gate.observed is not None else None,
            "threshold": str(gate.threshold) if gate.threshold is not None else None,
            "comparator": gate.comparator,
        }
        for gate in feedback.failed_gates
    ]
    feedback_payload = json.dumps(
        {
            "candidate_id": feedback.candidate_id,
            "qualification_hash": feedback.qualification_hash,
            "failed_gates": failed_gates,
            "failure_reason_codes": feedback.failure_reason_codes,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    revision_user = (
        f"{base_user['content']} Previous candidate feedback={feedback_payload}. "
        "Create a new candidate strategy_id; do not repeat the previous candidate. "
        "Address the failed gates. Do not relax qualification gates."
    )
    if critique_evidence is not None:
        critique_payload = json.dumps(
            {
                "review_hash": critique_evidence.review_hash,
                "critique_decision": critique_evidence.critique_decision,
                "revision_actions": critique_evidence.revision_actions,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        revision_user += (
            f" Persisted critic evidence={critique_payload}. "
            "Treat critic revision_actions as advisory guidance; preserve all qualification gates."
        )
    return system, {"role": "user", "content": revision_user}


__all__ = ["build_creator_proposal_messages", "build_creator_revision_messages"]
