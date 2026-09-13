"""Policy-bound model-call audit tests for autonomous provider transports."""

from __future__ import annotations

import json
from datetime import UTC
from decimal import Decimal
from hashlib import sha256

import httpx
import pytest
from test_autonomy_provider import _requests

from autonomous_futures.research.autonomy_contracts import (
    FailureLearner,
    ResearchPlanner,
)
from autonomous_futures.research.autonomy_provider import (
    AuditedGoogleAIStudioFailureLearningTransport,
    AuditedGoogleAIStudioResearchPlanTransport,
)
from autonomous_futures.research.google_ai_studio_provider import (
    GoogleAIStudioJsonClient,
    GoogleAIStudioProviderConfig,
    ProviderTransportError,
)
from autonomous_futures.research_lab.model_audit import ModelCallAudit
from autonomous_futures.research_lab.model_policy import (
    GemmaModelId,
    LLMRolePolicy,
    ResearchRole,
    build_research_model_policy,
)


def _policy(role: ResearchRole, model_id: GemmaModelId = "gemma-4-26b-a4b-it"):
    return build_research_model_policy(
        policy_id=f"policy-autonomy-{role.replace('_', '-')}",
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role=role,
                provider="google_ai_studio",
                model_id=model_id,
                temperature=Decimal("0.20"),
                max_output_tokens=2048,
                max_requests_per_batch=1,
                max_retries=0,
            ),
        ),
    )


def _client(handler, model_id: GemmaModelId = "gemma-4-26b-a4b-it"):
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = GoogleAIStudioJsonClient(
        GoogleAIStudioProviderConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="not-real",
            model_id=model_id,
        ),
        client=http_client,
    )
    return http_client, client


def test_audited_failure_learning_transport_binds_policy_and_hashes_output() -> None:
    content = json.dumps(
        {
            "failure_patterns": ["oos_profit_factor_below_threshold"],
            "learned_constraints": ["preserve_all_qualification_gates"],
            "recommended_novelty_dimensions": ["entry_logic"],
        }
    )
    audits: list[ModelCallAudit] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gemma-4-26b-a4b-it"
        assert body["max_tokens"] == 2048
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    learning_request, _ = _requests()
    http_client, client = _client(handler)
    try:
        result = FailureLearner(
            AuditedGoogleAIStudioFailureLearningTransport(
                client=client,
                policy=_policy("failure_analyst"),
                audit_sink=audits.append,
            )
        ).learn(learning_request)
    finally:
        http_client.close()

    assert result.decision == "accepted"
    assert len(audits) == 1
    audit = audits[0]
    assert audit.role == "failure_analyst"
    assert audit.provider == "google_ai_studio"
    assert audit.model_id == "gemma-4-26b-a4b-it"
    assert audit.outcome == "succeeded"
    assert audit.output_hash == sha256(content.encode()).hexdigest()
    assert audit.policy_hash == _policy("failure_analyst").policy_hash
    assert audit.input_evidence_refs == learning_request.input_evidence_refs
    assert audit.output_schema_id == learning_request.output_schema_id
    assert audit.retry_count == 0
    assert audit.observed_at.tzinfo == UTC


def test_audited_planner_transport_binds_hypothesis_role() -> None:
    content = json.dumps(
        {
            "hypothesis": "Use independent volume confirmation for volatile continuation.",
            "expected_regime": "volatile_trend",
            "strategy_family": "volume_confirmed_momentum",
            "novelty_dimensions": ["entry_logic"],
            "falsification_criteria": ["reject when pinned OOS gates fail"],
        }
    )
    audits: list[ModelCallAudit] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    _, plan_request = _requests()
    http_client, client = _client(handler)
    try:
        result = ResearchPlanner(
            AuditedGoogleAIStudioResearchPlanTransport(
                client=client,
                policy=_policy("hypothesis_generator"),
                audit_sink=audits.append,
            )
        ).plan(plan_request)
    finally:
        http_client.close()

    assert result.decision == "accepted"
    assert len(audits) == 1
    assert audits[0].role == "hypothesis_generator"
    assert audits[0].output_hash == sha256(content.encode()).hexdigest()
    assert audits[0].research_run_id == plan_request.research_run_id
    assert audits[0].input_evidence_refs == plan_request.input_evidence_refs
    assert audits[0].output_schema_id == plan_request.output_schema_id


def test_audited_transport_rejects_policy_model_mismatch_before_http() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    http_client, client = _client(handler, model_id="gemma-4-31b-it")
    try:
        with pytest.raises(ValueError, match="model"):
            AuditedGoogleAIStudioFailureLearningTransport(
                client=client,
                policy=_policy("failure_analyst"),
                audit_sink=lambda _audit: None,
            )
    finally:
        http_client.close()

    assert called is False


def test_audited_transport_emits_failure_audit_without_response_body() -> None:
    audits: list[ModelCallAudit] = []
    secret_body = "provider-private-body-not-retained"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=secret_body)

    learning_request, _ = _requests()
    http_client, client = _client(handler)
    try:
        transport = AuditedGoogleAIStudioFailureLearningTransport(
            client=client,
            policy=_policy("failure_analyst"),
            audit_sink=audits.append,
        )
        with pytest.raises(ProviderTransportError):
            transport(learning_request)
    finally:
        http_client.close()

    assert len(audits) == 1
    assert audits[0].outcome == "provider_error"
    assert audits[0].output_hash is None
    assert audits[0].error_code == "http_503"
    assert secret_body not in str(audits[0])
