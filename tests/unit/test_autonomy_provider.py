"""Fake-HTTP coverage for autonomous learner/planner provider adapters."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from autonomous_futures.research.autonomy_contracts import (
    FailureLearner,
    FailureLearningRequest,
    ResearchPlanner,
    ResearchPlanRequest,
    build_failure_memory_entry,
)
from autonomous_futures.research.autonomy_provider import (
    GoogleAIStudioFailureLearningTransport,
    GoogleAIStudioResearchPlanTransport,
)
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.google_ai_studio_provider import (
    GoogleAIStudioJsonClient,
    GoogleAIStudioProviderConfig,
)
from autonomous_futures.research.qualification_artifacts import QualificationGateResult

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _feedback() -> CreatorQualificationFailureFeedback:
    return CreatorQualificationFailureFeedback(
        candidate_id="cand-provider-seed-001",
        candidate_artifact_hash=HASH_A,
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        qualification_hash=HASH_C,
        qualification_policy_id="policy-provider-001",
        failed_gates=(
            QualificationGateResult(
                gate_id="oos_profit_factor_min",
                passed=False,
                observed=Decimal("0.8"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="oos_profit_factor_below_threshold",
            ),
        ),
        failure_reason_codes=("oos_profit_factor_below_threshold",),
    )


def _requests() -> tuple[FailureLearningRequest, ResearchPlanRequest]:
    feedback = _feedback()
    memory = build_failure_memory_entry(
        base_run_id="base-provider-001",
        source_type="seed_feedback",
        source_id="seed-provider-001",
        sequence=0,
        feedback=feedback,
        cycle_id=None,
        cycle_hash=None,
        recorded_at=NOW,
    )
    learning_request = FailureLearningRequest(
        research_run_id="run-learning-provider-001",
        base_run_id="base-provider-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        cycle_index=1,
        failure_memory=(memory,),
        forbidden_candidate_ids=(feedback.candidate_id,),
        input_evidence_refs=(f"failure/{memory.memory_hash}",),
    )
    learning = (
        FailureLearner(
            lambda _request: {
                "failure_patterns": ["oos_profit_factor_below_threshold"],
                "learned_constraints": ["preserve_all_qualification_gates"],
                "recommended_novelty_dimensions": ["entry_logic"],
            }
        )
        .learn(learning_request)
        .artifact
    )
    assert learning is not None
    plan_request = ResearchPlanRequest(
        research_run_id="run-creator-cycle-provider-001",
        base_run_id="base-provider-001",
        cycle_id="cycle-provider-001",
        symbol="BTCUSDT",
        bundle_hash=HASH_A,
        dataset_registry_hash=HASH_B,
        cycle_index=1,
        failure_memory=(memory,),
        learning=learning,
        forbidden_candidate_ids=(feedback.candidate_id,),
        input_evidence_refs=(
            f"failure/{memory.memory_hash}",
            f"learning/{learning.learning_hash}",
        ),
    )
    return learning_request, plan_request


def test_google_ai_studio_failure_learning_transport_uses_canonical_prompt() -> None:
    captured: list[httpx.Request] = []
    payload = {
        "failure_patterns": ["oos_profit_factor_below_threshold"],
        "learned_constraints": ["preserve_all_qualification_gates"],
        "recommended_novelty_dimensions": ["entry_logic"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json.loads(request.content)
        assert body["model"] == "gemma-4-26b-a4b-it"
        assert body["max_tokens"] == 2048
        assert "cand-provider-seed-001" in body["messages"][1]["content"]
        assert "failure-learning-v1" in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    learning_request, _ = _requests()
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = GoogleAIStudioJsonClient(
            GoogleAIStudioProviderConfig(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                api_key="not-real",
            ),
            client=http_client,
        )
        result = FailureLearner(GoogleAIStudioFailureLearningTransport(client=client)).learn(
            learning_request
        )

    assert result.decision == "accepted"
    assert result.artifact is not None
    assert result.provider_metadata["choice_count"] == 1
    assert captured


def test_google_ai_studio_research_plan_transport_uses_full_history() -> None:
    captured: list[httpx.Request] = []
    payload = {
        "hypothesis": "Use independent volume confirmation for volatile continuation.",
        "expected_regime": "volatile_trend",
        "strategy_family": "volume_confirmed_momentum",
        "novelty_dimensions": ["entry_logic"],
        "falsification_criteria": ["reject when pinned OOS gates fail"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json.loads(request.content)
        prompt = body["messages"][1]["content"]
        assert body["max_tokens"] == 2048
        assert "failure_memory" in prompt
        assert "recommended_novelty_dimensions" in prompt
        assert "forbidden_candidate_ids" in prompt
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    _, plan_request = _requests()
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = GoogleAIStudioJsonClient(
            GoogleAIStudioProviderConfig(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                api_key="not-real",
            ),
            client=http_client,
        )
        result = ResearchPlanner(GoogleAIStudioResearchPlanTransport(client=client)).plan(
            plan_request
        )

    assert result.decision == "accepted"
    assert result.plan is not None
    assert result.plan.strategy_family == "volume_confirmed_momentum"
    assert captured
