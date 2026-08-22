from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..domain.contracts import DomainModel

ResearchRole = Literal[
    "hypothesis_generator",
    "strategy_spec_author",
    "economic_critic",
    "failure_analyst",
]


class LLMRolePolicy(DomainModel):
    """Pinned, non-authoritative policy for one embedded research role."""

    role: ResearchRole
    provider: Literal["opencode"]
    model_id: Literal["x-preview-f-free"]
    temperature: Decimal
    max_output_tokens: int = Field(gt=0, strict=True)
    max_requests_per_batch: int = Field(gt=0, strict=True)
    max_retries: int = Field(ge=0, strict=True)

    @field_validator("temperature")
    @classmethod
    def temperature_is_finite_and_bounded(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < Decimal("0") or value > Decimal("2"):
            raise ValueError("temperature must be finite and within [0, 2]")
        return value


class ResearchModelPolicy(DomainModel):
    """Immutable ordered collection of embedded research-role policies."""

    policy_version: Literal[1]
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    roles: tuple[LLMRolePolicy, ...] = Field(min_length=1)
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def roles_are_sorted_unique_and_hashed(self) -> ResearchModelPolicy:
        roles = tuple(role.role for role in self.roles)
        if roles != tuple(sorted(roles)) or len(set(roles)) != len(roles):
            raise ValueError("research model policy roles must be sorted and unique")
        if research_model_policy_content_hash(self) != self.policy_hash:
            raise ValueError("research model policy hash mismatch")
        return self


def research_model_policy_content_hash(policy: ResearchModelPolicy) -> str:
    payload = policy.model_dump(mode="json", exclude={"policy_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_research_model_policy(
    *,
    policy_id: str,
    policy_version: Literal[1],
    roles: tuple[LLMRolePolicy, ...],
) -> ResearchModelPolicy:
    """Build a deterministic policy without contacting a provider."""
    sorted_roles = tuple(sorted(roles, key=lambda role: role.role))
    payload = {
        "policy_id": policy_id,
        "policy_version": policy_version,
        "roles": [role.model_dump(mode="json") for role in sorted_roles],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return ResearchModelPolicy(
        policy_id=policy_id,
        policy_version=policy_version,
        roles=sorted_roles,
        policy_hash=sha256(canonical).hexdigest(),
    )
