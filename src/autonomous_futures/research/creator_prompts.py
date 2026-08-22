"""Canonical prompt construction for the constrained Creator proposal schema."""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..domain.contracts import ALLOWED_FEATURES
from .creator_generator import CreatorGenerationRequest

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
    f"features must use only {', '.join(sorted(ALLOWED_FEATURES))}; each feature needs "
    'a positive lookback and shift >= 1; universe must use timeframe="5m" and '
    'regime_context_timeframe="15m". proposal_id must start with proposal- and '
    "use lowercase letters, digits, and hyphens only; dsl_version must be the integer 1; "
    "universe must contain a symbols array; entry and exit must each be objects with "
    'string keys "long" and "short", not strings; entry.long and entry.short must be '
    "strings; exit.long and exit.short must be strings; vetoes must be a non-empty array "
    "of strings."
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


__all__ = ["build_creator_proposal_messages"]
