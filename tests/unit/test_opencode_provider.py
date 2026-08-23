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
    request_body = json.loads(captured[0].content)
    assert request_body["model"] == "deepseek-v4-flash"
    assert request_body["response_format"] == {"type": "json_object"}


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


def test_opencode_client_retries_one_transient_server_error() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, text="SECRET_PROVIDER_RESPONSE")
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

    assert calls == 2
    assert payload["proposal_id"] == "proposal-provider-001"


def test_opencode_client_retries_one_truncated_json_payload() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
            )
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

    assert calls == 2
    assert payload["proposal_id"] == "proposal-provider-001"


def test_opencode_client_accepts_one_fenced_json_object() -> None:
    content = "```json\n" + json.dumps(_proposal("run-provider-001")) + "\n```"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        payload = OpenCodeJsonClient(_config(), client=http_client).complete_json(
            messages=({"role": "user", "content": "return JSON"},),
            temperature=0.2,
            max_output_tokens=100,
        )

    assert payload["proposal_id"] == "proposal-provider-001"


def test_opencode_client_exposes_safe_metadata_for_non_json_content() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "plain model text"}}]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_payload_invalid") as error:
            OpenCodeJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    assert error.value.metadata == {
        "status_code": 200,
        "response_keys": ("choices",),
        "choice_count": 1,
        "finish_reason": "stop",
        "content_kind": "string",
        "content_length": 16,
        "content_sha256": "71f15fcc98b0323a09898de7569cff1cd21db29beeed1c78aa49749df1562668",
    }


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
