"""Prepare-only contract for one bounded autonomous provider smoke request."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from ..research_lab.model_policy import (
    GemmaModelId,
    ResearchModelPolicy,
    ResearchProvider,
    research_model_policy_content_hash,
)

ProviderSmokeRole = Literal["failure_analyst", "hypothesis_generator"]
ProviderSmokeOutputSchema = Literal["failure-learning-v1", "research-plan-v1"]


class ProviderSmokePreparation(DomainModel):
    """Hash-bound, non-authorizing preparation for one provider request."""

    preparation_version: Literal[1] = 1
    preparation_id: str = Field(pattern=r"^smoke-prep-[0-9a-f]{64}$")
    research_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    role: ProviderSmokeRole
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: ResearchProvider
    model_id: GemmaModelId
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    output_schema_id: ProviderSmokeOutputSchema
    request_count: Literal[1] = 1
    max_retries: Literal[0] = 0
    fallback_provider: Literal[False] = False
    network_call_allowed: Literal[False] = False
    runtime_mutation: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    exchange_access: Literal[False] = False
    prepared_at: datetime
    preparation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("input_evidence_refs")
    @classmethod
    def evidence_refs_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("provider smoke evidence references must be non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("provider smoke evidence references must be sorted and unique")
        return values

    @field_validator("prepared_at")
    @classmethod
    def prepared_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("provider smoke preparation timestamp must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def preparation_bindings_are_valid(self) -> ProviderSmokePreparation:
        expected_schema: ProviderSmokeOutputSchema = (
            "failure-learning-v1" if self.role == "failure_analyst" else "research-plan-v1"
        )
        if self.output_schema_id != expected_schema:
            raise ValueError("provider smoke output schema does not match role")
        if self.preparation_hash != "0" * 64:
            if provider_smoke_preparation_content_hash(self) != self.preparation_hash:
                raise ValueError("provider smoke preparation hash mismatch")
            if self.preparation_id != f"smoke-prep-{self.preparation_hash}":
                raise ValueError("provider smoke preparation ID must be hash-derived")
        return self


def provider_smoke_preparation_content_hash(preparation: ProviderSmokePreparation) -> str:
    payload = preparation.model_dump(
        mode="json", exclude={"preparation_id", "prepared_at", "preparation_hash"}
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_provider_smoke_preparation(
    *,
    research_run_id: str,
    role: ProviderSmokeRole,
    policy: ResearchModelPolicy,
    input_evidence_refs: tuple[str, ...],
    prepared_at: datetime,
) -> ProviderSmokePreparation:
    """Build a dry-run preparation without resolving credentials or contacting a provider."""
    if research_model_policy_content_hash(policy) != policy.policy_hash:
        raise DomainViolation("research model policy hash mismatch")
    role_policy = next((item for item in policy.roles if item.role == role), None)
    if role_policy is None:
        raise DomainViolation("research model policy has no requested provider role")
    output_schema_id: ProviderSmokeOutputSchema = (
        "failure-learning-v1" if role == "failure_analyst" else "research-plan-v1"
    )
    provisional = ProviderSmokePreparation.model_construct(
        preparation_version=1,
        preparation_id="smoke-prep-" + "0" * 64,
        research_run_id=research_run_id,
        role=role,
        policy_id=policy.policy_id,
        policy_hash=policy.policy_hash,
        provider=role_policy.provider,
        model_id=role_policy.model_id,
        input_evidence_refs=input_evidence_refs,
        output_schema_id=output_schema_id,
        request_count=1,
        max_retries=0,
        fallback_provider=False,
        network_call_allowed=False,
        runtime_mutation=False,
        promotion_state="unpromoted",
        paper_activation=False,
        execution_authority=False,
        exchange_access=False,
        prepared_at=prepared_at,
        preparation_hash="0" * 64,
    )
    preparation_hash = provider_smoke_preparation_content_hash(provisional)
    return ProviderSmokePreparation.model_validate(
        {
            **provisional.model_dump(),
            "preparation_id": f"smoke-prep-{preparation_hash}",
            "preparation_hash": preparation_hash,
        }
    )


def read_provider_smoke_preparation(path: Path) -> ProviderSmokePreparation:
    """Read and independently verify one prepare-only smoke artifact."""
    try:
        preparation = ProviderSmokePreparation.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except ValidationError as exc:
        if any("preparation hash mismatch" in error["msg"] for error in exc.errors()):
            raise DomainViolation(f"provider smoke preparation hash mismatch: {path}") from None
        raise DataQualityError("invalid provider smoke preparation") from exc
    if provider_smoke_preparation_content_hash(preparation) != preparation.preparation_hash:
        raise DomainViolation(f"provider smoke preparation hash mismatch: {path}")
    return preparation


def write_provider_smoke_preparation(
    path: Path, preparation: ProviderSmokePreparation
) -> ProviderSmokePreparation:
    """Persist preparation write-once; this function never resolves credentials or calls HTTP."""
    if provider_smoke_preparation_content_hash(preparation) != preparation.preparation_hash:
        raise DomainViolation("provider smoke preparation hash mismatch")
    if path.exists():
        existing = read_provider_smoke_preparation(path)
        if existing != preparation:
            raise DomainViolation(f"provider smoke preparation path is immutable: {path}")
        return existing

    payload = json.dumps(preparation.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_provider_smoke_preparation(path)
        if existing != preparation:
            raise DomainViolation(f"provider smoke preparation path is immutable: {path}") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_provider_smoke_preparation(path)


__all__ = [
    "ProviderSmokeOutputSchema",
    "ProviderSmokePreparation",
    "ProviderSmokeRole",
    "build_provider_smoke_preparation",
    "provider_smoke_preparation_content_hash",
    "read_provider_smoke_preparation",
    "write_provider_smoke_preparation",
]
