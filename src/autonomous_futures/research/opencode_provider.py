"""Direct OpenCode-compatible JSON provider transport for Creator research."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, field_validator

from ..domain.contracts import DomainModel
from .creator_generator import CreatorGenerationRequest


class ProviderTransportError(RuntimeError):
    """Stable provider failure without response-body or secret leakage."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OpenCodeProviderConfig(DomainModel):
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model_id: Literal["x-preview-f-free"] = "x-preview-f-free"

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

    def complete_json(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> Mapping[str, object]:
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
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderTransportError("provider_http_error") from exc
        except httpx.HTTPError as exc:
            raise ProviderTransportError("provider_transport_error") from exc

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            payload = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderTransportError("provider_payload_invalid") from exc
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
