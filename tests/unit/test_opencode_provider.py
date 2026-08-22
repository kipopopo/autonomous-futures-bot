from __future__ import annotations

import json

import httpx
import pytest

from autonomous_futures.research.creator_generator import CreatorGenerationRequest, CreatorGenerator
from autonomous_futures.research.opencode_provider import (
    OpenCodeJsonClient,
    OpenCodeProposalTransport,
    OpenCodeProviderConfig,
    ProviderTransportError,
)


def _proposal(run_id: str) -> dict[str, object]:
    return {
        "proposal_id": "proposal-provider-001",
        "research_run_id": run_id,
        "hypothesis": "A provider-backed bounded hypothesis",
        "expected_regime": "range",
        "novelty_reason": "Provider adapter smoke",
        "strategy": {
            "dsl_version": 1,
            "strategy_id": "cand-provider-001",
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


def _config() -> OpenCodeProviderConfig:
    return OpenCodeProviderConfig(
        base_url="https://provider.test/v1",
        api_key="test-secret-not-real",
    )


def test_opencode_client_posts_exact_model_and_returns_json_object() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_proposal("run-provider-001"))}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        payload = OpenCodeJsonClient(_config(), client=http_client).complete_json(
            messages=({"role": "user", "content": "return JSON"},),
            temperature=0.2,
            max_output_tokens=100,
        )

    assert payload["proposal_id"] == "proposal-provider-001"
    assert captured[0].url == "https://provider.test/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer test-secret-not-real"
    assert json.loads(captured[0].content)["model"] == "x-preview-f-free"


def test_opencode_client_hides_http_error_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="SECRET_PROVIDER_RESPONSE")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as error:
            OpenCodeJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    assert "SECRET_PROVIDER_RESPONSE" not in str(error.value)


def test_proposal_transport_connects_provider_to_existing_generator() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_proposal("run-provider-001"))}}]},
        )

    request = CreatorGenerationRequest(
        research_run_id="run-provider-001",
        input_evidence_refs=("bundle/hash",),
        output_schema_id="creator-proposal-v1",
        attempt=1,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        transport = OpenCodeProposalTransport(
            client=OpenCodeJsonClient(_config(), client=http_client),
            system_prompt="Return only the declared JSON schema.",
            user_prompt_builder=lambda item: f"run={item.research_run_id}",
        )
        result = CreatorGenerator(transport=transport).generate(request)

    assert result.decision == "accepted"
    assert result.proposal is not None
