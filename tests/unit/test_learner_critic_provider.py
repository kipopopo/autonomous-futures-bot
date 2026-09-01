from __future__ import annotations

import json

import httpx

from autonomous_futures.research.creator_failure_feedback import CreatorQualificationFailureFeedback
from autonomous_futures.research.google_ai_studio_provider import (
    GoogleAIStudioJsonClient,
    GoogleAIStudioProviderConfig,
)
from autonomous_futures.research.learner_critic import LearnerCritic, LearnerCriticRequest
from autonomous_futures.research.learner_critic_provider import (
    GoogleAIStudioCriticTransport,
    build_learner_critic_messages,
)


def _feedback() -> CreatorQualificationFailureFeedback:
    return CreatorQualificationFailureFeedback.model_validate(
        {
            "candidate_id": "cand-critic-001",
            "candidate_artifact_hash": "a" * 64,
            "bundle_hash": "b" * 64,
            "dataset_registry_hash": "c" * 64,
            "qualification_hash": "d" * 64,
            "qualification_policy_id": "policy-creator-001",
            "failed_gates": [
                {
                    "gate_id": "oos_profit_factor_min",
                    "passed": False,
                    "observed": "0.5",
                    "threshold": "1",
                    "comparator": "gte",
                    "reason_code": "oos_profit_factor_below_threshold",
                }
            ],
            "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        }
    )


def _request() -> LearnerCriticRequest:
    feedback = _feedback()
    return LearnerCriticRequest(
        research_run_id="run-critic-provider-001",
        candidate_id=feedback.candidate_id,
        candidate_artifact_hash=feedback.candidate_artifact_hash,
        feedback=feedback,
        input_evidence_refs=("feedback/hash", "qualification/hash"),
        output_schema_id="learner-critic-v1",
        attempt=1,
    )


def test_critic_prompt_binds_failure_evidence_and_exact_output_contract() -> None:
    system, user = build_learner_critic_messages(_request())

    assert "Return exactly one JSON object" in system["content"]
    assert "decision" in system["content"]
    assert "revision_actions" in system["content"]
    assert '"revision_actions": ["change_entry_threshold"]' in system["content"]
    assert "revision_actions must be sorted lexicographically and unique" in system["content"]
    assert "Do not relax qualification gates" in system["content"]
    assert "position_fraction" in system["content"]
    assert "leverage is unsupported" in system["content"]
    assert "oos_profit_factor_min" in user["content"]
    assert "oos_profit_factor_below_threshold" in user["content"]


def test_google_ai_studio_critic_transport_reaches_existing_critic_contract() -> None:
    payload = {
        "review_id": "review-provider-001",
        "research_run_id": "run-critic-provider-001",
        "candidate_id": "cand-critic-001",
        "decision": "revise",
        "failure_reason_codes": ["oos_profit_factor_below_threshold"],
        "revision_actions": ["change_entry_threshold"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gemma-4-26b-a4b-it"
        assert body["max_tokens"] == 4096
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    request = _request()
    system, user = build_learner_critic_messages(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        transport = GoogleAIStudioCriticTransport(
            client=GoogleAIStudioJsonClient(
                GoogleAIStudioProviderConfig(
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                    api_key="not-real",
                ),
                client=http_client,
            ),
            system_prompt=system["content"],
            user_prompt_builder=lambda _: user["content"],
        )
        result = LearnerCritic(transport=transport).review(request)

    assert result.decision == "accepted"
    assert result.critique is not None
    assert result.critique.review_hash != "0" * 64
