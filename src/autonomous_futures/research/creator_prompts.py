"""Canonical prompt construction for the constrained Creator proposal schema."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .creator_generator import CreatorGenerationRequest

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^[A-Z0-9]+$")
_SYSTEM_PROMPT = (
    "Return exactly one JSON object with keys proposal_id, research_run_id, hypothesis, "
    "expected_regime, novelty_reason, and strategy. The strategy object must contain "
    "dsl_version, strategy_id, family, universe, features, entry, exit, and vetoes. "
    "Use only approved StrategySpec features and bounded expressions. Never return "
    "markdown, code fences, prose, URLs, secrets, tools, or orders. strategy_id must "
    "start with cand- and research_run_id must match the supplied run."
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
