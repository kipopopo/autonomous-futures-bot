"""Direct OpenCode-compatible JSON provider transport for Creator research."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, field_validator

from ..domain.contracts import DomainModel
from .creator_generator import CreatorGenerationRequest


class ProviderTransportError(RuntimeError):
    """Stable provider failure without response-body or secret leakage."""

    def __init__(self, code: str, *, metadata: Mapping[str, object] | None = None) -> None:
        self.code = code
        self.metadata = dict(metadata or {})
        super().__init__(code)


class OpenCodeProviderConfig(DomainModel):
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model_id: Literal["deepseek-v4-flash"] = "deepseek-v4-flash"

    @field_validator("base_url")
    @classmethod
    def base_url_is_https_origin(cls, value: str) -> str:
        parsed = urlsplit(value.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("provider base_url must be an HTTPS URL without query or fragment")
        return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class OpenCodeJsonClient:
    config: OpenCodeProviderConfig
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
    ) -> Mapping[str, object]:
        response: httpx.Response | None = None
        for attempt in range(2):
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
                    },
                )
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {500, 502, 503, 504} and attempt == 0:
                    # ponytail: one immediate retry; add backoff only if measured need exists.
                    continue
                raise ProviderTransportError(
                    "provider_http_error", metadata={"status_code": exc.response.status_code}
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderTransportError("provider_transport_error") from exc
        if response is None:
            raise ProviderTransportError("provider_transport_error")

        try:
            body = response.json()
            metadata = self._response_metadata(body, status_code=response.status_code)
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, str):
                normalized = content.strip()
                if normalized.startswith("```json") and normalized.endswith("```"):
                    normalized = normalized[len("```json") : -len("```")].strip()
                payload = json.loads(normalized)
            else:
                payload = content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            metadata = locals().get(
                "metadata",
                {
                    "status_code": response.status_code,
                    "response_keys": (),
                    "choice_count": 0,
                    "finish_reason": None,
                    "content_kind": "invalid_json",
                    "content_length": 0,
                    "content_sha256": None,
                },
            )
            raise ProviderTransportError("provider_payload_invalid", metadata=metadata) from exc
        if not isinstance(payload, Mapping):
            raise ProviderTransportError("provider_payload_invalid")
        return payload


@dataclass(frozen=True, slots=True)
class OpenCodeProposalTransport:
    client: OpenCodeJsonClient
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
    "OpenCodeJsonClient",
    "OpenCodeProposalTransport",
    "OpenCodeProviderConfig",
    "ProviderTransportError",
]
