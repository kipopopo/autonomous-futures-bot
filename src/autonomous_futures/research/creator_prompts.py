"""Canonical prompt construction for the constrained Creator proposal schema."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from decimal import Decimal

from .creator_failure_feedback import CreatorQualificationFailureFeedback
from .creator_generator import CreatorGenerationRequest
from .feature_signals import SUPPORTED_FEATURES
from .learner_critic_evidence import LearnerCritiqueEvidence

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^[A-Z0-9]+$")
_SYSTEM_PROMPT = (
    "Return exactly one JSON object with keys proposal_id, research_run_id, hypothesis, "
    "expected_regime, novelty_reason, and strategy. The strategy object must contain "
    "dsl_version, strategy_id, family, universe, features, entry, exit, vetoes, and risk. "
    "Use only approved StrategySpec features and bounded expressions. Never return "
    "markdown, code fences, prose, URLs, secrets, tools, or orders. strategy_id must "
    "start with cand- but is an untrusted placeholder replaced by a local content hash; "
    "research_run_id must match the supplied run. "
    "family must be one of regime_gated_breakout, range_mean_reversion, experimental; "
    f"features must use only {', '.join(sorted(SUPPORTED_FEATURES))}; each feature needs "
    'a positive lookback and shift >= 1; universe must use timeframe="5m" and '
    'regime_context_timeframe="15m". proposal_id must start with proposal- and '
    "use lowercase letters, digits, and hyphens only; dsl_version must be the integer 2; "
    "features must be a JSON array of objects; feature objects must use keys name, lookback, "
    "and shift; universe must contain a symbols array; risk must contain position_fraction, "
    "stop_atr_multiplier, take_profit_atr_multiplier, and trailing_atr_multiplier; "
    "position_fraction must be greater than 0 and at most 0.5; stop_atr_multiplier must be "
    "greater than 0; take_profit_atr_multiplier and trailing_atr_multiplier must be at least 0; "
    "risk values must be unquoted JSON numbers with a decimal point: 0.1, 1.5, 2.0, and 0.0; "
    "leverage is not supported; "
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


CAPITAL_AND_LEVERAGE_GUIDELINES: str = (
    "Capital and Leverage Guidelines: Starting capital baseline is exactly 100 USDT. "
    "Design strategy entry conviction and risk parameters for prudent, confidence-scaled "
    "dynamic leverage: allocate higher effective position sizing and risk only during "
    "high-conviction signals with strict multi-feature confirmation (e.g. alignment across "
    "trend and momentum features); enforce defensive, minimal risk exposure during baseline "
    "or uncertain market regimes to strictly protect the 100 USDT account from liquidation "
    "or severe drawdown. Note: The strategy JSON schema strictly forbids extra keys (such as "
    "'leverage' or 'capital') — describe your dynamic leverage thesis in 'hypothesis' and "
    "'novelty_reason', and calibrate 'position_fraction' (between 0.01 and 0.50) and "
    "'stop_atr_multiplier' accordingly."
)


def build_phase_252_proposal_messages(
    request: CreatorGenerationRequest,
    *,
    bundle_hash: str,
    symbol: str,
    starting_capital_usd: Decimal | float | int | str = Decimal("100"),
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    if not _HASH.fullmatch(bundle_hash):
        raise ValueError("bundle_hash must be a lowercase SHA-256")
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("symbol must be uppercase alphanumeric")
    try:
        capital_dec = Decimal(str(starting_capital_usd))
    except Exception as exc:
        raise ValueError("starting_capital_usd must be a valid numeric amount") from exc
    if capital_dec <= 0:
        raise ValueError("starting_capital_usd must be positive")

    user_prompt = (
        f"research_run_id={request.research_run_id}; symbol={symbol}; "
        f"bundle_hash={bundle_hash}; output_schema={request.output_schema_id}; "
        f"input_evidence_refs={','.join(request.input_evidence_refs)}; "
        f"starting_capital_usd={capital_dec}; "
        f"guidelines={CAPITAL_AND_LEVERAGE_GUIDELINES}. "
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
    if not request.forbidden_candidate_ids:
        raise ValueError("revision request requires forbidden candidate IDs")
    if feedback.candidate_id not in request.forbidden_candidate_ids:
        raise ValueError("revision request must forbid the previous candidate")
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
        "Materially revise the strategy; changing only strategy_id does not create a new "
        "candidate. "
        f"forbidden_candidate_ids={json.dumps(request.forbidden_candidate_ids)}. "
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


__all__ = [
    "CAPITAL_AND_LEVERAGE_GUIDELINES",
    "build_creator_proposal_messages",
    "build_creator_revision_messages",
    "build_phase_252_proposal_messages",
]
