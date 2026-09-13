"""Typed factory coverage for policy-bound autonomous provider wiring."""

from __future__ import annotations

from decimal import Decimal

import httpx

from autonomous_futures.pipeline.autonomous_base import AutonomousBaseConfig, AutonomousResearchBase
from autonomous_futures.research.autonomy_provider import (
    AuditedGoogleAIStudioFailureLearningTransport,
    AuditedGoogleAIStudioResearchPlanTransport,
    build_google_ai_studio_autonomous_base,
)
from autonomous_futures.research.google_ai_studio_provider import (
    GoogleAIStudioJsonClient,
    GoogleAIStudioProviderConfig,
)
from autonomous_futures.research_lab.model_policy import LLMRolePolicy, build_research_model_policy

HASH_A = "a" * 64
HASH_B = "b" * 64


def _policy():
    return build_research_model_policy(
        policy_id="policy-autonomy-wiring-001",
        policy_version=1,
        roles=(
            LLMRolePolicy(
                role="failure_analyst",
                provider="google_ai_studio",
                model_id="gemma-4-26b-a4b-it",
                temperature=Decimal("0.20"),
                max_output_tokens=2048,
                max_requests_per_batch=1,
                max_retries=0,
            ),
            LLMRolePolicy(
                role="hypothesis_generator",
                provider="google_ai_studio",
                model_id="gemma-4-31b-it",
                temperature=Decimal("0.10"),
                max_output_tokens=1024,
                max_requests_per_batch=1,
                max_retries=0,
            ),
        ),
    )


def _client(model_id: str):
    http_client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    client = GoogleAIStudioJsonClient(
        GoogleAIStudioProviderConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="not-real",
            model_id=model_id,
        ),
        client=http_client,
    )
    return http_client, client


def test_factory_wires_each_role_to_its_pinned_client_and_audit_sink(tmp_path) -> None:
    learner_http, learner_client = _client("gemma-4-26b-a4b-it")
    planner_http, planner_client = _client("gemma-4-31b-it")
    try:
        config = AutonomousBaseConfig(
            base_run_id="base-provider-wiring-001",
            symbol="BTCUSDT",
            bundle_hash=HASH_A,
            dataset_registry_hash=HASH_B,
            artifact_root=tmp_path,
            max_cycles=1,
        )

        def audit_sink(_audit):
            return None

        base = build_google_ai_studio_autonomous_base(
            config=config,
            learner_client=learner_client,
            planner_client=planner_client,
            policy=_policy(),
            audit_sink=audit_sink,
            cycle_runner=lambda _request: None,
        )
    finally:
        learner_http.close()
        planner_http.close()

    assert isinstance(base, AutonomousResearchBase)
    assert isinstance(base.learner.transport, AuditedGoogleAIStudioFailureLearningTransport)
    assert isinstance(base.planner.transport, AuditedGoogleAIStudioResearchPlanTransport)
    assert base.learner.transport.client is learner_client
    assert base.planner.transport.client is planner_client


def test_factory_validates_role_client_binding_without_http(tmp_path) -> None:
    learner_http, learner_client = _client("gemma-4-31b-it")
    planner_http, planner_client = _client("gemma-4-31b-it")
    try:
        config = AutonomousBaseConfig(
            base_run_id="base-provider-wiring-002",
            symbol="BTCUSDT",
            bundle_hash=HASH_A,
            dataset_registry_hash=HASH_B,
            artifact_root=tmp_path,
            max_cycles=1,
        )
        try:
            build_google_ai_studio_autonomous_base(
                config=config,
                learner_client=learner_client,
                planner_client=planner_client,
                policy=_policy(),
                audit_sink=lambda _audit: None,
                cycle_runner=lambda _request: None,
            )
        except ValueError as error:
            assert "model" in str(error)
        else:
            raise AssertionError("factory accepted a mismatched learner model")
    finally:
        learner_http.close()
        planner_http.close()
