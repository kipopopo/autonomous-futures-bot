from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_proposals import (
    CreatorProposal,
    build_candidate_from_proposal,
    parse_creator_proposal,
    read_creator_proposal_outcome,
    write_creator_proposal_outcome,
)

BUNDLE_HASH = "a" * 64
REGISTRY_HASH = "b" * 64
CREATED_AT = datetime(2026, 8, 22, tzinfo=UTC)


def _payload() -> dict[str, object]:
    return {
        "proposal_id": "proposal-001",
        "research_run_id": "run-creator-001",
        "hypothesis": "Mean reversion after prior-bar RSI extremes",
        "expected_regime": "range",
        "novelty_reason": "Fresh pair-specific hypothesis",
        "strategy": {
            "dsl_version": 1,
            "strategy_id": "cand-doge-proposal-001",
            "family": "range_mean_reversion",
            "universe": {
                "symbols": ["DOGEUSDT"],
                "timeframe": "5m",
                "regime_context_timeframe": "15m",
            },
            "features": [{"name": "rsi", "lookback": 14, "shift": 1}],
            "entry": {"long": "rsi <= 30", "short": "rsi >= 70"},
            "exit": {"long": "rsi >= 50", "short": "rsi <= 50"},
            "vetoes": ["funding_adverse"],
        },
    }


def test_valid_proposal_builds_testing_candidate_without_raw_output() -> None:
    proposal = parse_creator_proposal(_payload())

    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-run-001",
        research_seed=1,
        created_at=CREATED_AT,
    )

    assert isinstance(proposal, CreatorProposal)
    assert candidate.candidate_id == proposal.strategy.strategy_id
    assert candidate.candidate_id != "cand-doge-proposal-001"
    assert candidate.state == "testing"
    assert candidate.bundle_hash == BUNDLE_HASH


def test_invalid_or_unsafe_proposal_is_rejected_before_candidate_build() -> None:
    payload = _payload()
    payload["strategy"] = {
        **payload["strategy"],
        "entry": {"long": "__import__('os')", "short": "rsi >= 70"},
    }

    with pytest.raises(ValueError, match="unsafe expression"):
        parse_creator_proposal(payload)


def test_proposal_outcome_is_write_once_and_read_verified(tmp_path: Path) -> None:
    proposal = parse_creator_proposal(_payload())
    candidate = build_candidate_from_proposal(
        proposal,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-run-001",
        research_seed=1,
        created_at=CREATED_AT,
    )
    outcome = proposal.build_outcome(
        decision="accepted",
        candidate_artifact_hash=candidate.artifact_hash,
        reason_codes=("schema_valid",),
        recorded_at=CREATED_AT,
    )
    path = tmp_path / "proposal-outcome.json"

    assert write_creator_proposal_outcome(path, outcome) == outcome
    assert read_creator_proposal_outcome(path) == outcome

    changed = proposal.build_outcome(
        decision="accepted",
        candidate_artifact_hash=candidate.artifact_hash,
        reason_codes=("changed",),
        recorded_at=CREATED_AT,
    )
    with pytest.raises(DomainViolation, match="immutable"):
        write_creator_proposal_outcome(path, changed)
