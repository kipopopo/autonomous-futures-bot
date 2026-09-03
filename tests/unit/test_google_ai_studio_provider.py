from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256

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


def test_google_ai_studio_client_disables_gemma4_thinking_for_json() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_proposal("run-provider-001"))}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
            messages=({"role": "user", "content": "return JSON"},),
            temperature=0.0,
            max_output_tokens=256,
        )

    request_body = json.loads(captured[0].content)
    assert request_body["extra_body"] == {
        "google": {
            "thinking_config": {
                "thinking_level": "minimal",
                "include_thoughts": False,
            }
        }
    }


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


def test_google_ai_studio_proposal_transport_preserves_v2_decimal_risk_values() -> None:
    proposal = _proposal("run-provider-v2-001")
    proposal["strategy"] = {
        **proposal["strategy"],  # type: ignore[dict-item]
        "dsl_version": 2,
        "risk": {
            "position_fraction": 0.1,
            "stop_atr_multiplier": 1.5,
            "take_profit_atr_multiplier": 2.0,
            "trailing_atr_multiplier": 0.0,
        },
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(proposal)}}]},
        )

    request = CreatorGenerationRequest(
        research_run_id="run-provider-v2-001",
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
    assert result.proposal.strategy.risk is not None
    assert result.proposal.strategy.risk.position_fraction == Decimal("0.1")


def test_google_ai_studio_proposal_transport_preserves_metadata_on_schema_rejection() -> None:
    content = json.dumps(
        {
            **_proposal("run-provider-001"),
            "strategy": {"unsafe": True},
        }
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
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

    assert result.reason_codes == ("schema_rejected",)
    assert result.provider_metadata == {
        "choice_count": 1,
        "content_kind": "string",
        "content_length": len(content),
        "content_sha256": sha256(content.encode()).hexdigest(),
        "finish_reason": "stop",
        "response_keys": ("choices",),
        "status_code": 200,
    }


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


def test_google_ai_studio_client_extracts_error_and_redacts_credentials_on_http_400() -> None:
    secret_key = "test-secret-not-real"
    secret_prompt = "bounded hypothesis with proprietary signal alpha = rsi(14) < 30"
    raw_error_payload = {
        "error": {
            "code": 400,
            "message": (
                f"Invalid request with key {secret_key} and prompt '{secret_prompt}' "
                "and Authorization Bearer secret-token-xyz-12345 "
                "AIzaSyDUMMYKEY01234567890123456789012"
            ),
            "status": "INVALID_ARGUMENT",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "API_KEY_INVALID",
                    "domain": "googleapis.com",
                    "metadata": {"service": "generativelanguage.googleapis.com"},
                }
            ],
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_error_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as exc_info:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": secret_prompt},),
                temperature=0.2,
                max_output_tokens=100,
            )

    err = exc_info.value
    # 1. Structured attribute & metadata extraction
    assert err.code == "provider_http_error"
    assert err.status_code == 400
    assert err.error_status == "INVALID_ARGUMENT"
    assert err.error_code == 400
    assert err.error_reason == "API_KEY_INVALID"
    assert err.metadata["status_code"] == 400
    assert err.metadata["error_status"] == "INVALID_ARGUMENT"
    assert err.metadata["error_code"] == 400
    assert err.metadata["error_reason"] == "API_KEY_INVALID"

    # 2. Strict credential & prompt redaction
    for target in (str(err), *[str(v) for v in err.metadata.values()]):
        assert secret_key not in target
        assert secret_prompt not in target
        assert "secret-token-xyz-12345" not in target
        assert "AIzaSyDUMMYKEY" not in target

    # 3. Non-leakage of raw response body
    assert "raw_body" not in err.metadata
    assert "raw_response" not in err.metadata
    assert "body" not in err.metadata
    assert json.dumps(raw_error_payload) not in str(err.metadata)


def test_google_ai_studio_client_extracts_openai_format_error_on_http_400() -> None:
    secret_prompt = "user prompt that triggered bad request"
    raw_error_payload = {
        "error": {
            "message": f"Unrecognized request argument in prompt: {secret_prompt}",
            "type": "invalid_request_error",
            "param": "messages",
            "code": "invalid_argument",
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_error_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as exc_info:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": secret_prompt},),
                temperature=0.2,
                max_output_tokens=100,
            )

    err = exc_info.value
    assert err.status_code == 400
    assert err.error_code in ("invalid_argument", "invalid_request_error", 400)
    assert err.metadata["status_code"] == 400
    assert secret_prompt not in str(err)
    assert secret_prompt not in str(err.metadata)


def test_google_ai_studio_proposal_transport_propagates_structured_error_on_http_400() -> None:
    secret_prompt = "run-provider-001 secret research hypothesis"
    raw_error_payload = {
        "error": {
            "code": 400,
            "message": (
                f"Malformed payload for prompt: {secret_prompt} with Bearer token-leak-attempt"
            ),
            "status": "INVALID_ARGUMENT",
            "details": [{"reason": "INVALID_ARGUMENT"}],
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_error_payload)

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
            user_prompt_builder=lambda item: f"run={item.research_run_id} {secret_prompt}",
        )
        result = CreatorGenerator(transport=transport).generate(request)

    # 1. Decision and reason codes
    assert result.decision == "rejected"
    assert result.proposal is None
    assert result.reason_codes == ("provider_http_error",)
    assert result.raw_output is None

    # 2. Structured metadata preservation in provider_metadata
    assert result.provider_metadata["status_code"] == 400
    assert result.provider_metadata["error_status"] == "INVALID_ARGUMENT"
    assert result.provider_metadata["error_reason"] == "INVALID_ARGUMENT"

    # 3. Non-leakage assertions
    assert secret_prompt not in str(result.provider_metadata)
    assert "token-leak-attempt" not in str(result.provider_metadata)
    assert json.dumps(raw_error_payload) not in str(result.provider_metadata)

    # 4. Mandatory offline safety invariants
    assert result.promotion_state == "unpromoted"
    assert result.paper_activation is False
    assert result.execution_authority is False
    assert result.exchange_access is False


def test_google_ai_studio_client_handles_degraded_html_error_on_http_400() -> None:
    html_content = (
        "<!DOCTYPE html><html><body><h1>400 Bad Request</h1>"
        "<p>Invalid URL key=AIzaSySecretKey012345678901234567890</p></body></html>"
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text=html_content,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as exc_info:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    err = exc_info.value
    assert err.status_code == 400
    assert err.error_code == "http_400"
    assert err.error_reason == "http_400_html_error"
    assert "AIzaSySecretKey" not in str(err)
    assert "AIzaSySecretKey" not in str(err.metadata)
    assert "<html" not in str(err.metadata)


def test_google_ai_studio_client_handles_degraded_empty_error_on_http_400() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b"")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as exc_info:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": "return JSON"},),
                temperature=0.2,
                max_output_tokens=100,
            )

    err = exc_info.value
    assert err.status_code == 400
    assert err.error_code == "http_400"
    assert err.error_reason == "http_400_empty_response"
    assert err.metadata["content_kind"] == "empty"


def test_google_ai_studio_client_redacts_credentials_in_message_without_details() -> None:
    """Verifies credential redaction when error.details is omitted (preventing test facade)."""
    secret_key = "AIzaSyDUMMYKEY01234567890123456789012"
    secret_prompt = "bounded proprietary prompt signal"
    raw_error_payload = {
        "error": {
            "code": 400,
            "message": (
                f"Invalid request with key {secret_key} and prompt '{secret_prompt}' "
                "and Authorization Bearer secret-token-xyz-12345"
            ),
            "status": "INVALID_ARGUMENT",
            # Explicitly NO 'details' field
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_error_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as exc_info:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": secret_prompt},),
                temperature=0.2,
                max_output_tokens=100,
            )

    err = exc_info.value
    assert err.status_code == 400
    assert err.error_status == "INVALID_ARGUMENT"
    # Ensure error_reason comes from message and is sanitized
    assert err.error_reason != "API_KEY_INVALID"
    assert secret_key not in str(err.error_reason)
    assert "[REDACTED_API_KEY]" in str(err.error_reason)
    assert secret_prompt not in str(err.error_reason)
    assert "[REDACTED_PROMPT]" in str(err.error_reason)
    assert "secret-token-xyz-12345" not in str(err.error_reason)
    assert "Bearer [REDACTED]" in str(err.error_reason)

    # All metadata values must be free of secrets
    for val in err.metadata.values():
        assert secret_key not in str(val)
        assert secret_prompt not in str(val)
        assert "secret-token-xyz-12345" not in str(val)


@pytest.mark.parametrize(
    "hostile_code",
    [
        "AIzaSyDTESTINGSECRETKEY012345678901234",
        "Bearer ya29.a0AfH6SMSECRET_BEARER_TOKEN",
        "user_prompt_hypothesis_leak",
        "LONG_CODE_" + ("X" * 1000),
    ],
)
def test_google_ai_studio_client_sanitizes_string_error_code(hostile_code: str) -> None:
    """Verifies string error.code values are sanitized and length-bounded."""
    secret_prompt = "user_prompt_hypothesis_leak"
    raw_error_payload = {
        "error": {
            "code": hostile_code,
            "message": "Invalid argument specified",
            "type": "invalid_request_error",
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_error_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as exc_info:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": secret_prompt},),
                temperature=0.2,
                max_output_tokens=100,
            )

    err = exc_info.value
    assert err.status_code == 400
    assert len(str(err.error_code)) <= 64
    assert "AIzaSy" not in str(err.error_code)
    assert "SECRET_BEARER_TOKEN" not in str(err.error_code)
    assert secret_prompt not in str(err.error_code)
    assert json.dumps(err.metadata).find("AIzaSy") == -1


def test_google_ai_studio_client_sanitizes_hostile_response_keys() -> None:
    """Verifies hostile root JSON keys are sanitized and capped in response_keys."""
    secret_key = "AIzaSyDTESTINGSECRETKEY012345678901234"
    secret_prompt = "secret_hypothesis_prompt"
    raw_error_payload = {
        "error": {"code": 400, "message": "error occurred"},
        secret_key: "val1",
        "Authorization_Bearer_ya29.secret_bearer_token": "val2",
        secret_prompt: "val3",
        "?key=AIzaSySecretQueryParam": "val4",
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_error_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(ProviderTransportError, match="provider_http_error") as exc_info:
            GoogleAIStudioJsonClient(_config(), client=http_client).complete_json(
                messages=({"role": "user", "content": secret_prompt},),
                temperature=0.2,
                max_output_tokens=100,
            )

    err = exc_info.value
    meta_dump = json.dumps(err.metadata)
    assert secret_key not in meta_dump
    assert "secret_bearer_token" not in meta_dump
    assert secret_prompt not in meta_dump
    assert "AIzaSySecretQueryParam" not in meta_dump
    assert isinstance(err.metadata["response_keys"], tuple)
    assert len(err.metadata["response_keys"]) <= 32
    for k in err.metadata["response_keys"]:
        assert len(str(k)) <= 64
