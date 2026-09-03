"""Adversarial stress-test harness for Google AI Studio provider error handling."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from autonomous_futures.research.creator_generator import (
    CreatorGenerationRequest,
    CreatorGenerator,
)
from autonomous_futures.research.google_ai_studio_provider import (
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    GoogleAIStudioJsonClient,
    GoogleAIStudioProposalTransport,
    GoogleAIStudioProviderConfig,
    ProviderTransportError,
)

SECRET_API_KEY = "AIzaSyDTESTINGSECRETKEY012345678901234"
SECRET_USER_PROMPT = "TOP_SECRET_ALPHA_SIGNAL = macd(12, 26, 9) > 0"
SECRET_SYSTEM_PROMPT = "SYSTEM_SECRET_DIRECTIVE = strictly classify market regimes"
SECRET_BEARER_TOKEN = "ya29.a0AfH6SMADVERSARIAL_BEARER_TOKEN_VALUE"


def _make_client(handler: Any) -> GoogleAIStudioJsonClient:
    config = GoogleAIStudioProviderConfig(
        base_url=GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
        api_key=SECRET_API_KEY,
        model_id="gemma-4-26b-a4b-it",
    )
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return GoogleAIStudioJsonClient(config, client=http_client)


def _assert_no_secret_leaks(
    err: ProviderTransportError, *, raw_payload_str: str | None = None
) -> None:
    # 1. str(err) must be exactly the error code ("provider_http_error")
    assert str(err) == "provider_http_error", f"str(err) leaked: {str(err)}"

    # 2. String representation of all metadata values and keys
    metadata_dump = json.dumps(err.metadata, default=str)
    assert SECRET_API_KEY not in metadata_dump, f"API key leaked in metadata: {metadata_dump}"
    assert SECRET_USER_PROMPT not in metadata_dump, (
        f"User prompt leaked in metadata: {metadata_dump}"
    )
    assert SECRET_SYSTEM_PROMPT not in metadata_dump, (
        f"System prompt leaked in metadata: {metadata_dump}"
    )
    assert SECRET_BEARER_TOKEN not in metadata_dump, (
        f"Bearer token leaked in metadata: {metadata_dump}"
    )

    # 3. Check typed attributes on err
    for attr in ("status_code", "error_status", "error_code", "error_reason"):
        val = getattr(err, attr)
        if val is not None:
            val_str = str(val)
            assert SECRET_API_KEY not in val_str, f"API key leaked in {attr}: {val_str}"
            assert SECRET_USER_PROMPT not in val_str, f"User prompt leaked in {attr}: {val_str}"
            assert SECRET_SYSTEM_PROMPT not in val_str, f"System prompt leaked in {attr}: {val_str}"
            assert SECRET_BEARER_TOKEN not in val_str, f"Bearer token leaked in {attr}: {val_str}"

    # 4. Raw response body must not be in metadata
    assert "raw_body" not in err.metadata
    assert "raw_response" not in err.metadata
    assert "body" not in err.metadata
    if raw_payload_str and len(raw_payload_str) > 10:
        assert raw_payload_str not in metadata_dump


# =========================================================================
# 1. Malformed / truncated JSON on HTTP 400
# =========================================================================


@pytest.mark.parametrize(
    "truncated_raw",
    [
        b'{"error": {"code": 400, "message": "trunca',
        b'{"error": {',
        b'{"error":',
        b"{",
        b'{"error": {"message": "unclosed string',
        b'{"error": {"details": [{"reason": "SOME_REASON"',
    ],
)
def test_malformed_truncated_json_on_http_400(truncated_raw: bytes) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, content=truncated_raw, headers={"Content-Type": "application/json"}
        )

    client = _make_client(handler)
    with pytest.raises(ProviderTransportError) as exc_info:
        client.complete_json(
            messages=(
                {"role": "system", "content": SECRET_SYSTEM_PROMPT},
                {"role": "user", "content": SECRET_USER_PROMPT},
            ),
            temperature=0.2,
            max_output_tokens=100,
        )

    err = exc_info.value
    assert err.code == "provider_http_error"
    assert err.status_code == 400
    assert err.metadata["content_kind"] == "text"
    assert err.error_code == "http_400"
    assert err.error_reason == "http_400_text_error"
    _assert_no_secret_leaks(err, raw_payload_str=truncated_raw.decode("latin1"))


# =========================================================================
# 2. JSON root is list or primitive rather than dict
# =========================================================================


@pytest.mark.parametrize(
    "non_dict_content",
    [
        b'[{"error": "inside a list"}]',
        b'["item1", "item2"]',
        b'"just a string root"',
        b"12345",
        b"-99.5",
        b"true",
        b"false",
        b"null",
    ],
)
def test_json_root_is_not_a_mapping_on_http_400(non_dict_content: bytes) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, content=non_dict_content, headers={"Content-Type": "application/json"}
        )

    client = _make_client(handler)
    with pytest.raises(ProviderTransportError) as exc_info:
        client.complete_json(
            messages=(
                {"role": "system", "content": SECRET_SYSTEM_PROMPT},
                {"role": "user", "content": SECRET_USER_PROMPT},
            ),
            temperature=0.2,
            max_output_tokens=100,
        )

    err = exc_info.value
    assert err.code == "provider_http_error"
    assert err.status_code == 400
    assert err.metadata["content_kind"] == "invalid_payload"
    assert err.error_code == "http_400"
    assert err.error_reason == "http_400_non_mapping_json"
    _assert_no_secret_leaks(err, raw_payload_str=non_dict_content.decode("latin1"))


# =========================================================================
# 3. Weird nested types (e.g. status is int or dict, details is string or dict)
# =========================================================================


@pytest.mark.parametrize(
    "weird_payload",
    [
        # status is int or dict or list or bool
        {"error": {"status": 500, "message": "status was an int"}},
        {"error": {"status": {"nested": "dict_status"}, "message": "status was a dict"}},
        {"error": {"status": ["list_item"], "message": "status was a list"}},
        {"error": {"status": False, "message": "status was a bool"}},
        # details is string, dict, int, or mixed list
        {"error": {"details": "details was a string", "message": "fallback msg"}},
        {"error": {"details": {"reason": "details was a dict"}, "message": "fallback msg"}},
        {"error": {"details": 12345, "message": "fallback msg"}},
        {
            "error": {
                "details": [
                    123,
                    None,
                    "str",
                    {"reason": 999},
                    {"reason": "VALID_REASON"},
                ],
                "message": "fallback msg",
            }
        },
        {"error": {"details": [{"reason": None}, {"reason": ""}], "message": "fallback msg"}},
        # code is dict, list, bool, None
        {"error": {"code": {"complex": "code"}, "message": "code was a dict"}},
        {"error": {"code": [400], "message": "code was a list"}},
        {"error": {"code": None, "message": "code was None"}},
        # error itself is primitive or list
        {"error": 404},
        {"error": "direct error string"},
        {"error": ["error", "in", "array"]},
        {"error": None},
        # empty dict or dict with unexpected fields
        {},
        {"message": "top-level message without error key"},
        {"unknown_key": "some value"},
    ],
)
def test_weird_nested_types_on_http_400(weird_payload: dict[str, Any]) -> None:
    raw_str = json.dumps(weird_payload)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=weird_payload)

    client = _make_client(handler)
    with pytest.raises(ProviderTransportError) as exc_info:
        client.complete_json(
            messages=(
                {"role": "system", "content": SECRET_SYSTEM_PROMPT},
                {"role": "user", "content": SECRET_USER_PROMPT},
            ),
            temperature=0.2,
            max_output_tokens=100,
        )

    err = exc_info.value
    assert err.code == "provider_http_error"
    assert err.status_code == 400
    assert err.error_code is not None
    assert err.error_reason is not None
    _assert_no_secret_leaks(err, raw_payload_str=raw_str)


# =========================================================================
# 4. Hostile payload attempting to leak API key or bearer token
# =========================================================================


@pytest.mark.parametrize(
    "hostile_error_obj",
    [
        # API key in message with varied wrapping
        {"message": f"Error with key {SECRET_API_KEY}"},
        {"message": f"Check parameter ?key={SECRET_API_KEY}&mode=strict"},
        {"message": f"Check parameter &key={SECRET_API_KEY}"},
        {"message": f"Authorization: Bearer {SECRET_BEARER_TOKEN}"},
        {"message": f"bearer {SECRET_BEARER_TOKEN}"},
        {"message": f"api_key='{SECRET_API_KEY}'"},
        {"message": f"token: {SECRET_BEARER_TOKEN}"},
        {"message": f"messages[0].content: '{SECRET_USER_PROMPT}'"},
        {"message": f"messages[1].content: '{SECRET_SYSTEM_PROMPT}'"},
        # API key in reason
        {"details": [{"reason": f"KEY_INVALID_{SECRET_API_KEY}"}]},
        {"details": [{"reason": f"Bearer {SECRET_BEARER_TOKEN}"}]},
        # API key in status
        {"status": f"FAIL_{SECRET_API_KEY}"},
        {"status": f"Bearer {SECRET_BEARER_TOKEN}"},
    ],
)
def test_hostile_payload_credential_leak_attempts_in_message_reason_status(
    hostile_error_obj: dict[str, Any],
) -> None:
    raw_payload = {"error": hostile_error_obj}
    raw_str = json.dumps(raw_payload)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_payload)

    client = _make_client(handler)
    with pytest.raises(ProviderTransportError) as exc_info:
        client.complete_json(
            messages=(
                {"role": "system", "content": SECRET_SYSTEM_PROMPT},
                {"role": "user", "content": SECRET_USER_PROMPT},
            ),
            temperature=0.2,
            max_output_tokens=100,
        )

    err = exc_info.value
    assert err.code == "provider_http_error"
    assert err.status_code == 400
    _assert_no_secret_leaks(err, raw_payload_str=raw_str)


# =========================================================================
# 4b. Vulnerability Demonstration: Secret & Prompt Leaks in error.code
# =========================================================================


@pytest.mark.parametrize(
    "vulnerable_code_value",
    [
        SECRET_API_KEY,
        f"Bearer {SECRET_BEARER_TOKEN}",
        SECRET_USER_PROMPT,
        "MASSIVE_CODE_STRING_" + ("Z" * 10_000),
    ],
)
def test_vulnerability_hostile_leak_in_error_code(vulnerable_code_value: str) -> None:
    """Demonstrates whether error.code sanitizes strings and bounds length."""
    raw_payload = {"error": {"code": vulnerable_code_value, "message": "error occurred"}}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_payload)

    client = _make_client(handler)
    with pytest.raises(ProviderTransportError) as exc_info:
        client.complete_json(
            messages=(
                {"role": "system", "content": SECRET_SYSTEM_PROMPT},
                {"role": "user", "content": SECRET_USER_PROMPT},
            ),
            temperature=0.2,
            max_output_tokens=100,
        )

    err = exc_info.value
    _assert_no_secret_leaks(err)
    if len(vulnerable_code_value) > 256:
        assert len(str(err.error_code)) <= 256, (
            f"error_code not bounded: {len(str(err.error_code))}"
        )


# =========================================================================
# 4c. Vulnerability Demonstration: Secret Leaks in JSON root keys (response_keys)
# =========================================================================


@pytest.mark.parametrize(
    "hostile_key",
    [
        SECRET_API_KEY,
        f"Authorization_Bearer_{SECRET_BEARER_TOKEN}",
        SECRET_USER_PROMPT,
    ],
)
def test_vulnerability_hostile_leak_in_response_keys(hostile_key: str) -> None:
    """Demonstrates whether response_keys sanitizes keys or leaks secrets."""
    raw_payload = {"error": {"code": 400, "message": "error"}, hostile_key: "hostile_value"}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_payload)

    client = _make_client(handler)
    with pytest.raises(ProviderTransportError) as exc_info:
        client.complete_json(
            messages=(
                {"role": "system", "content": SECRET_SYSTEM_PROMPT},
                {"role": "user", "content": SECRET_USER_PROMPT},
            ),
            temperature=0.2,
            max_output_tokens=100,
        )

    err = exc_info.value
    _assert_no_secret_leaks(err)


# =========================================================================
# 5. Massive prompt echo (e.g. 20KB) to test truncation and memory bounding
# =========================================================================


def test_massive_prompt_echo_truncation_and_memory_bounding() -> None:
    massive_echo = f"Error prefix: {SECRET_USER_PROMPT} " + ("X" * 20_000)
    raw_payload = {
        "error": {
            "code": 400,
            "message": massive_echo,
            "status": "INVALID_ARGUMENT",
            "details": [{"reason": "MASSIVE_REASON_" + ("Y" * 10_000)}],
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=raw_payload)

    client = _make_client(handler)
    with pytest.raises(ProviderTransportError) as exc_info:
        client.complete_json(
            messages=(
                {"role": "system", "content": SECRET_SYSTEM_PROMPT},
                {"role": "user", "content": SECRET_USER_PROMPT},
            ),
            temperature=0.2,
            max_output_tokens=100,
        )

    err = exc_info.value
    assert err.code == "provider_http_error"
    assert err.status_code == 400
    assert err.error_reason is not None
    # Truncated to <= 256 characters!
    assert len(err.error_reason) <= 256, f"error_reason exceeded 256 chars: {len(err.error_reason)}"
    assert err.error_reason.endswith("...")
    # Secrets strictly absent
    _assert_no_secret_leaks(err)


# =========================================================================
# 6. Degraded responses: HTML error page, plain text, zero bytes, binary garbage
# =========================================================================


@pytest.mark.parametrize(
    ("content", "headers", "expected_kind", "expected_reason"),
    [
        (
            b"<!DOCTYPE html><html><body>Error 400</body></html>",
            {"Content-Type": "text/html"},
            "html",
            "http_400_html_error",
        ),
        (
            b"<HTML><BODY>UPPERCASE HTML ERROR</BODY></HTML>",
            {"Content-Type": "application/octet-stream"},
            "html",
            "http_400_html_error",
        ),
        (
            b"Plain text error message from upstream reverse proxy",
            {"Content-Type": "text/plain"},
            "text",
            "http_400_text_error",
        ),
        (
            b"",
            {"Content-Type": "application/json"},
            "empty",
            "http_400_empty_response",
        ),
        (
            b"\x80\x81\xff\xfe\x00\x01\x02\x03\xaa\xbb\xcc\xdd",
            {"Content-Type": "application/octet-stream"},
            "text",
            "http_400_text_error",
        ),
    ],
)
def test_degraded_responses_on_http_400(
    content: bytes,
    headers: dict[str, str],
    expected_kind: str,
    expected_reason: str,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=content, headers=headers)

    client = _make_client(handler)
    with pytest.raises(ProviderTransportError) as exc_info:
        client.complete_json(
            messages=(
                {"role": "system", "content": SECRET_SYSTEM_PROMPT},
                {"role": "user", "content": SECRET_USER_PROMPT},
            ),
            temperature=0.2,
            max_output_tokens=100,
        )

    err = exc_info.value
    assert err.code == "provider_http_error"
    assert err.status_code == 400
    assert err.metadata["content_kind"] == expected_kind
    assert err.error_reason == expected_reason
    _assert_no_secret_leaks(err)


# =========================================================================
# 7. CreatorGenerator pipeline integration & offline safety invariants
# =========================================================================


def test_creator_generator_safely_handles_all_adversarial_scenarios() -> None:
    hostile_payload = {
        "error": {
            "code": 400,
            "message": f"Hostile echo of {SECRET_USER_PROMPT} and key {SECRET_API_KEY}",
            "status": "INVALID_ARGUMENT",
            "details": [{"reason": "KEY_REJECTED"}],
        }
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=hostile_payload)

    client = _make_client(handler)
    transport = GoogleAIStudioProposalTransport(
        client=client,
        system_prompt=SECRET_SYSTEM_PROMPT,
        user_prompt_builder=lambda _: SECRET_USER_PROMPT,
    )
    generator = CreatorGenerator(transport=transport)
    result = generator.generate(
        CreatorGenerationRequest(
            research_run_id="run-adv-001",
            input_evidence_refs=("bundle/adv",),
            output_schema_id="creator-proposal-v1",
            attempt=1,
        )
    )

    assert result.decision == "rejected"
    assert result.reason_codes == ("provider_http_error",)
    assert result.proposal is None
    assert result.raw_output is None
    assert result.provider_metadata["status_code"] == 400
    assert result.provider_metadata["error_status"] == "INVALID_ARGUMENT"
    assert result.provider_metadata["error_reason"] == "KEY_REJECTED"

    # Redaction checks on provider_metadata
    metadata_dump = json.dumps(result.provider_metadata, default=str)
    assert SECRET_API_KEY not in metadata_dump
    assert SECRET_USER_PROMPT not in metadata_dump
    assert SECRET_SYSTEM_PROMPT not in metadata_dump
    assert SECRET_BEARER_TOKEN not in metadata_dump

    # Safety invariants
    assert result.promotion_state == "unpromoted"
    assert result.paper_activation is False
    assert result.execution_authority is False
    assert result.exchange_access is False
