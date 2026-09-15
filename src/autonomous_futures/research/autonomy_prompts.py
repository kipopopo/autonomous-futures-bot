"""Canonical prompts for the evidence-first autonomous research base."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from .autonomy_contracts import (
    FailureLearningRequest,
    FailureMemoryEntry,
    ResearchPlanRequest,
)

_FAILURE_LEARNER_SYSTEM = (
    "Return exactly one JSON object with keys decision, failure_patterns, "
    "learned_constraints, and recommended_novelty_dimensions. decision must be "
    "accepted or stop. failure_patterns, learned_constraints, and "
    "recommended_novelty_dimensions must each be JSON arrays of unique strings, "
    "sorted lexicographically and unique. "
    "recommended_novelty_dimensions values must be one of entry_logic, exit_logic, "
    "feature_set, regime_filter, risk_design, or strategy_family. Do not return "
    'objects inside any array. A valid shape is {"decision":"accepted", '
    '"failure_patterns":["oos_profit_factor_below_threshold"], '
    '"learned_constraints":["preserve_all_qualification_gates"], '
    '"recommended_novelty_dimensions":["entry_logic"]}. Analyze only the '
    "supplied typed failure memory. Preserve "
    "all qualification gates and never recommend changing thresholds, selecting "
    "a new holdout, promoting a candidate, changing risk authority, or placing "
    "an order. If no materially different falsifiable direction remains, return "
    "stop."
)

_RESEARCH_PLANNER_SYSTEM = (
    "Return exactly one JSON object with keys hypothesis, expected_regime, "
    "strategy_family, novelty_dimensions, and falsification_criteria. "
    "strategy_family must be one of: donchian_channel_breakout, experimental, "
    "range_mean_reversion, regime_gated_breakout, volatility_compression_breakout, "
    "or volume_confirmed_momentum. novelty_dimensions and falsification_criteria "
    "must each be JSON arrays of unique strings, sorted lexicographically and unique. "
    "novelty_dimensions values must be one of: entry_logic, exit_logic, feature_set, "
    "regime_filter, risk_design, or strategy_family. falsification_criteria must be "
    "a JSON array of 1 to 8 strings, sorted lexicographically. "
    'A valid shape is {"expected_regime":"volatile_trend", '
    '"falsification_criteria":["reject if OOS profit factor < 1.0"], '
    '"hypothesis":"Trade volume-confirmed momentum with volatility filter.", '
    '"novelty_dimensions":["entry_logic","feature_set"], '
    '"strategy_family":"volume_confirmed_momentum"}. '
    "Produce one materially different falsifiable research thesis from the complete "
    "failure memory and learned constraints. Do not relax qualification gates, "
    "reuse forbidden candidates or used holdouts, change capital/risk policy, "
    "promote a candidate, activate paper/testnet/live, or place an order."
)


def _failure_memory_payload(
    entries: Sequence[FailureMemoryEntry],
) -> list[Mapping[str, object]]:
    return [
        {
            "memory_hash": entry.memory_hash,
            "source_type": entry.source_type,
            "sequence": entry.sequence,
            "candidate_id": entry.candidate_id,
            "qualification_hash": entry.qualification_hash,
            "failed_gate_ids": [gate.gate_id for gate in entry.failed_gates],
            "failure_reason_codes": entry.failure_reason_codes,
            "source_hashes": entry.source_hashes,
        }
        for entry in entries
    ]


def build_failure_learning_messages(
    request: FailureLearningRequest,
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    """Build a bounded learner prompt from typed failure evidence only."""
    context = {
        "research_run_id": request.research_run_id,
        "base_run_id": request.base_run_id,
        "symbol": request.symbol,
        "bundle_hash": request.bundle_hash,
        "dataset_registry_hash": request.dataset_registry_hash,
        "cycle_index": request.cycle_index,
        "output_schema": request.output_schema_id,
        "forbidden_candidate_ids": request.forbidden_candidate_ids,
        "input_evidence_refs": request.input_evidence_refs,
        "failure_memory": _failure_memory_payload(request.failure_memory),
    }
    return (
        {"role": "system", "content": _FAILURE_LEARNER_SYSTEM},
        {
            "role": "user",
            "content": "Analyze this exact immutable evidence context: "
            + json.dumps(context, sort_keys=True, separators=(",", ":")),
        },
    )


def build_research_plan_messages(
    request: ResearchPlanRequest,
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    """Build a bounded planner prompt from complete failure and learning evidence."""
    learning = request.learning
    context = {
        "research_run_id": request.research_run_id,
        "base_run_id": request.base_run_id,
        "cycle_id": request.cycle_id,
        "symbol": request.symbol,
        "bundle_hash": request.bundle_hash,
        "dataset_registry_hash": request.dataset_registry_hash,
        "cycle_index": request.cycle_index,
        "output_schema": request.output_schema_id,
        "forbidden_candidate_ids": request.forbidden_candidate_ids,
        "prior_plan_hashes": request.prior_plan_hashes,
        "prior_thesis_hashes": request.prior_thesis_hashes,
        "input_evidence_refs": request.input_evidence_refs,
        "failure_memory": _failure_memory_payload(request.failure_memory),
        "learning": {
            "learning_hash": learning.learning_hash,
            "failure_patterns": learning.failure_patterns,
            "learned_constraints": learning.learned_constraints,
            "recommended_novelty_dimensions": learning.recommended_novelty_dimensions,
            "decision": learning.decision,
        },
    }
    return (
        {"role": "system", "content": _RESEARCH_PLANNER_SYSTEM},
        {
            "role": "user",
            "content": "Create one next experiment for this exact immutable evidence context: "
            + json.dumps(context, sort_keys=True, separators=(",", ":")),
        },
    )


__all__ = [
    "build_failure_learning_messages",
    "build_research_plan_messages",
]
