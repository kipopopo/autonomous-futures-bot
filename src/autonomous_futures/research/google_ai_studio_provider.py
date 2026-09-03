"""Direct Google AI Studio OpenAI-compatible JSON provider transport."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, field_validator

from ..domain.contracts import DomainModel
from .creator_generator import CreatorGenerationRequest

GOOGLE_AI_STUDIO_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GoogleAIStudioModelId = Literal["gemma-4-26b-a4b-it", "gemma-4-31b-it"]


class ProviderTransportError(RuntimeError):
    """Stable provider failure without response-body or secret leakage."""

    code: str
    metadata: dict[str, object]
    _status_code: int | None
    _error_status: str | None
    _error_code: str | int | None
    _error_reason: str | None

    def __init__(
        self,
        code: str,
        *,
        metadata: Mapping[str, object] | None = None,
        status_code: int | None = None,
        error_status: str | None = None,
        error_code: str | int | None = None,
        error_reason: str | None = None,
    ) -> None:
        self.code = code
        merged_metadata = dict(metadata or {})

        sc = status_code if status_code is not None else merged_metadata.get("status_code")
        self._status_code = int(sc) if isinstance(sc, int) else None
        if self._status_code is not None:
            merged_metadata["status_code"] = self._status_code

        es = error_status if error_status is not None else merged_metadata.get("error_status")
        self._error_status = str(es) if isinstance(es, str) else None
        if self._error_status is not None:
            merged_metadata["error_status"] = self._error_status

        ec = error_code if error_code is not None else merged_metadata.get("error_code")
        self._error_code = ec if isinstance(ec, (str, int)) else None
        if self._error_code is not None:
            merged_metadata["error_code"] = self._error_code

        er = error_reason if error_reason is not None else merged_metadata.get("error_reason")
        self._error_reason = str(er) if isinstance(er, str) else None
        if self._error_reason is not None:
            merged_metadata["error_reason"] = self._error_reason

        self.metadata = merged_metadata
        super().__init__(code)

    @property
    def status_code(self) -> int | None:
        val = (
            self._status_code if self._status_code is not None else self.metadata.get("status_code")
        )
        return val if isinstance(val, int) else None

    @property
    def error_status(self) -> str | None:
        val = (
            self._error_status
            if self._error_status is not None
            else self.metadata.get("error_status")
        )
        return val if isinstance(val, str) else None

    @property
    def error_code(self) -> str | int | None:
        val = self._error_code if self._error_code is not None else self.metadata.get("error_code")
        return val if isinstance(val, (str, int)) else None

    @property
    def error_reason(self) -> str | None:
        val = (
            self._error_reason
            if self._error_reason is not None
            else self.metadata.get("error_reason")
        )
        return val if isinstance(val, str) else None

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"ProviderTransportError({self.code!r})"


class ProviderJsonPayload(dict[str, object]):
    """Parsed provider JSON with safe response metadata kept in memory only."""

    metadata: dict[str, object]

    def __init__(self, payload: Mapping[str, object], *, metadata: Mapping[str, object]) -> None:
        super().__init__(payload)
        self.metadata = dict(metadata)


class GoogleAIStudioProviderConfig(DomainModel):
    base_url: str = GOOGLE_AI_STUDIO_OPENAI_BASE_URL
    api_key: str = Field(min_length=1)
    model_id: GoogleAIStudioModelId = "gemma-4-26b-a4b-it"

    @field_validator("base_url")
    @classmethod
    def base_url_is_official_endpoint(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
            or normalized != GOOGLE_AI_STUDIO_OPENAI_BASE_URL
        ):
            raise ValueError("base_url must be the official Google AI Studio OpenAI endpoint")
        return normalized


_RE_API_KEY = re.compile(r"AIza[0-9A-Za-z\-_]{20,}")
_RE_GOOGLE_OAUTH = re.compile(r"ya29\.[0-9A-Za-z\-_]+")
_RE_BEARER_HEADER = re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s\"';]+")
_RE_BEARER_TOKEN = re.compile(r"(?i)\bbearer[_\s:=]+[A-Za-z0-9\-._~+/]+=*")
_RE_URL_KEY_PARAM = re.compile(r"([?&]key=)[^&\s\"'\`]+")
_RE_GENERIC_CREDENTIAL = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|auth|authorization)\s*[:=]\s*[\"']?([A-Za-z0-9\-._~+/]{8,})[\"']?"
)
_RE_PROMPT_ECHO = re.compile(r"(messages\[\d+\]\.content['\":\s]+)[^,}\]]+")


def _sanitize_error_text(
    text: str,
    *,
    api_key: str | None = None,
    prompts: Sequence[str] = (),
    max_length: int = 256,
) -> str:
    if not text:
        return ""
    result = text
    if api_key:
        result = result.replace(api_key, "[REDACTED_API_KEY]")
    result = _RE_API_KEY.sub("[REDACTED_API_KEY]", result)
    result = _RE_URL_KEY_PARAM.sub(r"\1[REDACTED]", result)
    result = _RE_BEARER_HEADER.sub(r"\1[REDACTED]", result)
    result = _RE_BEARER_TOKEN.sub("Bearer [REDACTED]", result)
    result = _RE_GOOGLE_OAUTH.sub("Bearer [REDACTED]", result)
    result = _RE_GENERIC_CREDENTIAL.sub(r"\1=[REDACTED]", result)
    for prompt in prompts:
        if prompt:
            p_strip = prompt.strip()
            if p_strip and p_strip in result:
                result = result.replace(p_strip, "[REDACTED_PROMPT]")
            if prompt in result:
                result = result.replace(prompt, "[REDACTED_PROMPT]")
    result = _RE_PROMPT_ECHO.sub(r"\1[REDACTED_PROMPT]", result)
    normalized = " ".join(result.split())
    if len(normalized) > max_length:
        return normalized[: max_length - 3] + "..."
    return normalized


def _extract_http_error_metadata(
    exc: httpx.HTTPStatusError,
    *,
    api_key: str,
    prompts: Sequence[str] = (),
) -> dict[str, object]:
    status_code = exc.response.status_code
    try:
        content_bytes = exc.response.content
    except Exception:
        content_bytes = b""
    content_length = len(content_bytes)
    content_sha256 = sha256(content_bytes).hexdigest() if content_bytes else None

    # Handle empty response
    if content_length == 0:
        return {
            "status_code": status_code,
            "error_code": f"http_{status_code}",
            "error_reason": f"http_{status_code}_empty_response",
            "content_kind": "empty",
            "content_length": 0,
            "content_sha256": None,
            "response_keys": (),
        }

    # Detect HTML response
    content_type = exc.response.headers.get("content-type", "").lower()
    raw_start = content_bytes.strip()[:64].lower()
    if (
        "text/html" in content_type
        or raw_start.startswith(b"<!doctype html")
        or raw_start.startswith(b"<html")
    ):
        return {
            "status_code": status_code,
            "error_code": f"http_{status_code}",
            "error_reason": f"http_{status_code}_html_error",
            "content_kind": "html",
            "content_length": content_length,
            "content_sha256": content_sha256,
            "response_keys": (),
        }

    # Attempt JSON parsing
    try:
        body = exc.response.json()
    except Exception:
        return {
            "status_code": status_code,
            "error_code": f"http_{status_code}",
            "error_reason": f"http_{status_code}_text_error",
            "content_kind": "text",
            "content_length": content_length,
            "content_sha256": content_sha256,
            "response_keys": (),
        }

    if not isinstance(body, Mapping):
        return {
            "status_code": status_code,
            "error_code": f"http_{status_code}",
            "error_reason": f"http_{status_code}_non_mapping_json",
            "content_kind": "invalid_payload",
            "content_length": content_length,
            "content_sha256": content_sha256,
            "response_keys": (),
        }

    response_keys = tuple(
        sorted(
            _sanitize_error_text(str(k), api_key=api_key, prompts=prompts, max_length=64)
            for k in tuple(body.keys())[:32]
        )
    )
    error_obj = body.get("error")

    error_status: str | None = None
    error_code: str | int | None = None
    error_reason: str | None = None

    if isinstance(error_obj, Mapping):
        raw_status = error_obj.get("status") or error_obj.get("type")
        if isinstance(raw_status, str) and raw_status.strip():
            error_status = _sanitize_error_text(
                raw_status.strip(), api_key=api_key, prompts=prompts, max_length=64
            )

        raw_code = error_obj.get("code")
        if isinstance(raw_code, int) and not isinstance(raw_code, bool):
            error_code = raw_code
        elif isinstance(raw_code, str) and raw_code.strip():
            error_code = _sanitize_error_text(
                raw_code.strip(), api_key=api_key, prompts=prompts, max_length=64
            )
        elif error_status:
            error_code = error_status

        details = error_obj.get("details")
        if isinstance(details, Sequence) and not isinstance(details, (str, bytes)):
            for item in details:
                if isinstance(item, Mapping):
                    reason_val = item.get("reason")
                    if isinstance(reason_val, str) and reason_val.strip():
                        error_reason = _sanitize_error_text(
                            reason_val.strip(), api_key=api_key, prompts=prompts
                        )
                        break

        if not error_reason:
            raw_msg = error_obj.get("message")
            if isinstance(raw_msg, str) and raw_msg.strip():
                error_reason = _sanitize_error_text(raw_msg, api_key=api_key, prompts=prompts)
    elif isinstance(error_obj, str) and error_obj.strip():
        error_reason = _sanitize_error_text(error_obj, api_key=api_key, prompts=prompts)
    elif "message" in body and isinstance(body["message"], str) and body["message"].strip():
        error_reason = _sanitize_error_text(body["message"], api_key=api_key, prompts=prompts)

    final_error_code = error_code if error_code is not None else f"http_{status_code}"
    final_error_reason = error_reason if error_reason is not None else f"http_{status_code}_error"

    result_meta: dict[str, object] = {
        "status_code": status_code,
        "error_code": final_error_code,
        "error_reason": final_error_reason,
        "content_kind": "json",
        "content_length": content_length,
        "content_sha256": content_sha256,
        "response_keys": response_keys,
    }
    if error_status is not None:
        result_meta["error_status"] = error_status

    return result_meta


@dataclass(frozen=True, slots=True)
class GoogleAIStudioJsonClient:
    config: GoogleAIStudioProviderConfig
    client: httpx.Client

    @staticmethod
    def _response_metadata(body: object, *, status_code: int) -> dict[str, object]:
        metadata: dict[str, object] = {
            "status_code": status_code,
            "response_keys": tuple(sorted(body)) if isinstance(body, Mapping) else (),
            "choice_count": 0,
            "finish_reason": None,
            "content_kind": "missing",
            "content_length": 0,
            "content_sha256": None,
        }
        if not isinstance(body, Mapping) or not isinstance(body.get("choices"), list):
            return metadata
        choices = body["choices"]
        metadata["choice_count"] = len(choices)
        if not choices or not isinstance(choices[0], Mapping):
            return metadata
        first_choice = choices[0]
        metadata["finish_reason"] = first_choice.get("finish_reason")
        message = first_choice.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        metadata["content_kind"] = (
            "string"
            if isinstance(content, str)
            else "object"
            if isinstance(content, Mapping)
            else "null"
            if content is None
            else type(content).__name__
        )
        if isinstance(content, str):
            metadata["content_length"] = len(content)
            metadata["content_sha256"] = sha256(content.encode()).hexdigest()
        return metadata

    def complete_json(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> ProviderJsonPayload:
        try:
            response = self.client.post(
                f"{self.config.base_url}/chat/completions",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.model_id,
                    "messages": list(messages),
                    "temperature": temperature,
                    "max_tokens": max_output_tokens,
                    "response_format": {"type": "json_object"},
                    "extra_body": {
                        "google": {
                            "thinking_config": {
                                "thinking_level": "minimal",
                                "include_thoughts": False,
                            }
                        }
                    },
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            prompts = [
                msg["content"]
                for msg in messages
                if isinstance(msg, Mapping) and isinstance(msg.get("content"), str)
            ]
            error_metadata = _extract_http_error_metadata(
                exc, api_key=self.config.api_key, prompts=prompts
            )
            raise ProviderTransportError("provider_http_error", metadata=error_metadata) from exc
        except httpx.HTTPError as exc:
            raise ProviderTransportError(
                "provider_transport_error",
                metadata={"transport_error_type": type(exc).__name__},
            ) from exc

        metadata: dict[str, object] = {
            "status_code": response.status_code,
            "response_keys": (),
            "choice_count": 0,
            "finish_reason": None,
            "content_kind": "invalid_json",
            "content_length": 0,
            "content_sha256": None,
        }
        try:
            body = response.json()
            metadata = self._response_metadata(body, status_code=response.status_code)
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, str):
                normalized = content.strip()
                if normalized.startswith("```json") and normalized.endswith("```"):
                    normalized = normalized[len("```json") : -len("```")].strip()
                payload = json.loads(normalized, parse_float=Decimal)
            else:
                payload = content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderTransportError("provider_payload_invalid", metadata=metadata) from exc
        if not isinstance(payload, Mapping):
            raise ProviderTransportError("provider_payload_invalid", metadata=metadata)
        return ProviderJsonPayload(payload, metadata=metadata)


@dataclass(frozen=True, slots=True)
class GoogleAIStudioProposalTransport:
    client: GoogleAIStudioJsonClient
    system_prompt: str
    user_prompt_builder: Callable[[CreatorGenerationRequest], str]
    temperature: float = 0.2
    max_output_tokens: int = 2048

    def __call__(self, request: CreatorGenerationRequest) -> Mapping[str, object]:
        return self.client.complete_json(
            messages=(
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt_builder(request)},
            ),
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )


__all__ = [
    "GOOGLE_AI_STUDIO_OPENAI_BASE_URL",
    "GoogleAIStudioJsonClient",
    "GoogleAIStudioModelId",
    "GoogleAIStudioProposalTransport",
    "GoogleAIStudioProviderConfig",
    "ProviderJsonPayload",
    "ProviderTransportError",
]
