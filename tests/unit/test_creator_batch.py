from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from autonomous_futures.research.creator_batch import (
    CreatorBatchResult,
    run_creator_batch,
)
from autonomous_futures.research.creator_generator import (
    CreatorGenerationRequest,
    CreatorGenerator,
)

CREATED_AT = datetime(2026, 8, 22, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
REGISTRY_HASH = "b" * 64


def _proposal(proposal_id: str, candidate_id: str, run_id: str) -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "research_run_id": run_id,
        "hypothesis": "A bounded mean-reversion hypothesis",
        "expected_regime": "range",
        "novelty_reason": "A fresh trial",
        "strategy": {
            "dsl_version": 1,
            "strategy_id": candidate_id,
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


def _request(run_id: str) -> CreatorGenerationRequest:
    return CreatorGenerationRequest(
        research_run_id=run_id,
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )


def test_batch_builds_candidates_and_deduplicates_ids() -> None:
    payloads = {
        "run-a": _proposal("proposal-a", "cand-a", "run-a"),
        "run-b": _proposal("proposal-b", "cand-a", "run-b"),
        "run-c": {
            **_proposal("proposal-c", "cand-c", "run-c"),
            "strategy": {"unsafe": True},
        },
    }

    def transport(request: CreatorGenerationRequest) -> Mapping[str, object]:
        return payloads[request.research_run_id]

    result = run_creator_batch(
        (_request("run-a"), _request("run-b"), _request("run-c")),
        generator=CreatorGenerator(transport=transport),
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-batch-001",
        research_seed=70001,
        created_at=CREATED_AT,
    )

    assert isinstance(result, CreatorBatchResult)
    assert tuple(candidate.candidate_id for candidate in result.accepted_candidates) == ("cand-a",)
    assert tuple(trial.decision for trial in result.trials) == (
        "accepted",
        "rejected",
        "rejected",
    )
    assert result.trials[1].reason_codes == ("duplicate_candidate_id",)
    assert result.trials[2].reason_codes == ("schema_rejected",)
    assert result.trials[2].schema_diagnostics == (
        "strategy.dsl_version:missing",
        "strategy.entry:missing",
        "strategy.exit:missing",
        "strategy.family:missing",
        "strategy.features:missing",
        "strategy.strategy_id:missing",
        "strategy.universe:missing",
        "strategy.unsafe:extra_forbidden",
        "strategy.vetoes:missing",
    )
    assert result.exchange_access is False
    assert result.execution_authority is False


def test_batch_seeds_are_deterministic_and_candidates_are_testing_only() -> None:
    payload = _proposal("proposal-a", "cand-a", "run-a")

    result = run_creator_batch(
        (_request("run-a"),),
        generator=CreatorGenerator(transport=lambda _: payload),
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=REGISTRY_HASH,
        creator_run_id="creator-batch-001",
        research_seed=70001,
        created_at=CREATED_AT,
    )

    candidate = result.accepted_candidates[0]
    assert candidate.research_seed == 70001
    assert candidate.state == "testing"
    assert candidate.bundle_hash == BUNDLE_HASH
    assert result.paper_activation is False
    assert result.promotion_state == "unpromoted"
