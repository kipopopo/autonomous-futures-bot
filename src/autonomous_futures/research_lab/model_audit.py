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
from .model_policy import ResearchRole

ModelCallOutcome = Literal[
    "succeeded",
    "schema_rejected",
    "provider_model_unavailable",
    "provider_error",
    "budget_rejected",
]


class ModelCallAudit(DomainModel):
    """In-memory, non-authoritative audit record for one embedded model call."""

    audit_version: Literal[1] = 1
    research_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    call_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    role: ResearchRole
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: Literal["opencode"]
    model_id: Literal["deepseek-v4-flash-free"]
    prompt_template_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_policy_version: str = Field(min_length=1, max_length=64)
    input_evidence_refs: tuple[str, ...] = Field(min_length=1)
    output_schema_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    outcome: ModelCallOutcome
    output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    declared_price_tier: str = Field(min_length=1, max_length=64)
    rate_limit_delay_ms: int = Field(ge=0, strict=True)
    retry_count: int = Field(ge=0, strict=True)
    error_code: str | None = Field(default=None, min_length=1, max_length=128)
    observed_at: datetime
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("model call audit observed_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def outcome_and_hash_are_valid(self) -> ModelCallAudit:
        if self.input_evidence_refs != tuple(sorted(self.input_evidence_refs)) or len(
            set(self.input_evidence_refs)
        ) != len(self.input_evidence_refs):
            raise ValueError("model call audit input evidence references must be sorted and unique")
        if self.outcome == "succeeded":
            if self.output_hash is None:
                raise ValueError("successful model call audit requires an output hash")
            if self.error_code is not None:
                raise ValueError("successful model call audit cannot carry an error code")
        else:
            if self.output_hash is not None:
                raise ValueError("unsuccessful model call audit cannot carry an output hash")
            if self.error_code is None:
                raise ValueError("unsuccessful model call audit requires an error code")
        if self.outcome in {"budget_rejected", "provider_model_unavailable"} and (
            self.input_tokens is not None or self.output_tokens is not None
        ):
            raise ValueError(f"{self.outcome} cannot report token usage")
        if model_call_audit_content_hash(self) != self.audit_hash:
            raise ValueError("model call audit hash mismatch")
        return self

    @classmethod
    def build(
        cls,
        *,
        research_run_id: str,
        call_id: str,
        role: ResearchRole,
        policy_id: str,
        policy_hash: str,
        provider: Literal["opencode"],
        model_id: Literal["deepseek-v4-flash-free"],
        prompt_template_hash: str,
        system_policy_version: str,
        input_evidence_refs: tuple[str, ...],
        output_schema_id: str,
        outcome: ModelCallOutcome,
        output_hash: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        declared_price_tier: str,
        rate_limit_delay_ms: int,
        retry_count: int,
        error_code: str | None,
        observed_at: datetime,
    ) -> ModelCallAudit:
        """Build a hash-bound audit record without calling or storing a provider."""
        payload = {
            "audit_version": 1,
            "research_run_id": research_run_id,
            "call_id": call_id,
            "role": role,
            "policy_id": policy_id,
            "policy_hash": policy_hash,
            "provider": provider,
            "model_id": model_id,
            "prompt_template_hash": prompt_template_hash,
            "system_policy_version": system_policy_version,
            "input_evidence_refs": input_evidence_refs,
            "output_schema_id": output_schema_id,
            "outcome": outcome,
            "output_hash": output_hash,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "declared_price_tier": declared_price_tier,
            "rate_limit_delay_ms": rate_limit_delay_ms,
            "retry_count": retry_count,
            "error_code": error_code,
            "observed_at": observed_at,
        }
        canonical_payload = {key: value for key, value in payload.items() if key != "observed_at"}
        canonical = json.dumps(
            canonical_payload, default=str, sort_keys=True, separators=(",", ":")
        ).encode()
        return cls.model_validate({**payload, "audit_hash": sha256(canonical).hexdigest()})


def model_call_audit_content_hash(audit: ModelCallAudit) -> str:
    payload = audit.model_dump(mode="json", exclude={"observed_at", "audit_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def read_model_call_audit(path: Path) -> ModelCallAudit:
    """Read and hash-verify one persisted non-authoritative model-call audit."""
    try:
        audit = ModelCallAudit.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except ValidationError as exc:
        if any("model call audit hash mismatch" in error["msg"] for error in exc.errors()):
            raise DomainViolation(f"model call audit hash mismatch: {path}") from None
        raise DataQualityError("invalid persisted model call audit") from exc
    except ValueError as exc:
        raise DataQualityError("invalid persisted model call audit") from exc
    if model_call_audit_content_hash(audit) != audit.audit_hash:
        raise DomainViolation(f"model call audit hash mismatch: {path}")
    return audit


def write_model_call_audit(path: Path, audit: ModelCallAudit) -> ModelCallAudit:
    """Persist a model-call audit atomically and write-once without provider interaction."""
    if model_call_audit_content_hash(audit) != audit.audit_hash:
        raise DomainViolation("model call audit hash mismatch")
    if path.exists():
        existing = read_model_call_audit(path)
        if existing != audit:
            raise DomainViolation(f"model call audit path is immutable: {path}")
        return existing

    payload = json.dumps(audit.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_model_call_audit(path)
        if existing != audit:
            raise DomainViolation(f"model call audit path is immutable: {path}") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_model_call_audit(path)


__all__ = [
    "ModelCallAudit",
    "ModelCallOutcome",
    "model_call_audit_content_hash",
    "read_model_call_audit",
    "write_model_call_audit",
]
