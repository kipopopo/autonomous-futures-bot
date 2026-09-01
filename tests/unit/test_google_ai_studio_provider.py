from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from autonomous_futures.research.creator_generator import CreatorGenerationRequest, CreatorGenerator
from autonomous_futures.research.google_ai_studio_provider import (
    GoogleAIStudioJsonClient,
    GoogleAIStudioProposalTransport,
    GoogleAIStudioProviderConfig,
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


def _config(model_id: str = "gemma-4-26b-a4b-it") -> GoogleAIStudioProviderConfig:
    return GoogleAIStudioProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="test-secret-not-real",
        model_id=model_id,
    )


def test_google_ai_studio_client_posts_exact_model_and_returns_json_object() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_proposal("run-provider-001"))}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        payload = GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
            messages=({"role": "user", "content": "return JSON"},),
            temperature=0.2,
            max_output_tokens=100,
        )

    assert payload["proposal_id"] == "proposal-provider-001"
    assert (
        captured[0].url
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert captured[0].headers["authorization"] == "Bearer test-secret-not-real"
    request_body = json.loads(captured[0].content)
    assert request_body["model"] == "gemma-4-26b-a4b-it"
    assert request_body["response_format"] == {"type": "json_object"}


def test_google_ai_studio_client_hides_http_error_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="SECRET_PROVIDER_RESPONSE")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as error:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    assert "SECRET_PROVIDER_RESPONSE" not in str(error.value)


def test_google_ai_studio_client_exposes_only_transport_error_type() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("SECRET_TRANSPORT_ERROR")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_transport_error") as error:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    assert error.value.metadata == {"transport_error_type": "ReadTimeout"}
    assert "SECRET_TRANSPORT_ERROR" not in str(error.value)


def test_google_ai_studio_client_does_not_retry_transient_server_error() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="SECRET_PROVIDER_RESPONSE")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error"):
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    assert calls == 1


def test_google_ai_studio_client_does_not_retry_truncated_json_payload() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_payload_invalid"):
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    assert calls == 1


def test_google_ai_studio_client_accepts_one_fenced_json_object() -> None:
    content = "```json\n" + json.dumps(_proposal("run-provider-001")) + "\n```"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        payload = GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
            messages=({"role": "user", "content": "return JSON"},),
            temperature=0.2,
            max_output_tokens=100,
        )

    assert payload["proposal_id"] == "proposal-provider-001"


def test_google_ai_studio_client_exposes_safe_metadata_for_non_json_content() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "plain model text"}}]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_payload_invalid") as error:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
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


def test_google_ai_studio_proposal_transport_connects_provider_to_existing_generator() -> None:
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
        transport = GoogleAIStudioProposalTransport(
            client=GoogleAIStudioJsonClient(_config(), client=http_client),
            system_prompt="Return only the declared JSON schema.",
            user_prompt_builder=lambda item: f"run={item.research_run_id}",
        )
        result = CreatorGenerator(transport=transport).generate(request)

    assert result.decision == "accepted"
    assert result.proposal is not None


def test_google_ai_studio_client_accepts_second_pinned_gemma_model() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_proposal("run-provider-001"))}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        GoogleAIStudioJsonClient(_config("gemma-4-31b-it"), client=http_client).complete_json(
            messages=({"role": "user", "content": "return JSON"},),
            temperature=0.2,
            max_output_tokens=100,
        )

    assert json.loads(captured[0].content)["model"] == "gemma-4-31b-it"


def test_google_ai_studio_config_rejects_non_official_base_url() -> None:
    with pytest.raises(ValidationError, match="official"):
        GoogleAIStudioProviderConfig(
            base_url="https://provider.test/v1",
            api_key="test-secret-not-real",
        )
