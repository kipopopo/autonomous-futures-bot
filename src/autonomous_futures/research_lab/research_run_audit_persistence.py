from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from ..data.parquet import DataQualityError
from ..domain.errors import DomainViolation
from .research_run_audit import ResearchRunAuditEnvelope, research_run_audit_content_hash


def read_research_run_audit_envelope(path: Path) -> ResearchRunAuditEnvelope:
    """Read and hash-verify one persisted audit-only research-run envelope."""
    try:
        envelope = ResearchRunAuditEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except ValidationError as exc:
        if any("envelope hash mismatch" in error["msg"] for error in exc.errors()):
            raise DomainViolation(f"research run audit envelope hash mismatch: {path}") from None
        raise DataQualityError("invalid persisted research run audit envelope") from exc
    except ValueError as exc:
        raise DataQualityError("invalid persisted research run audit envelope") from exc
    if research_run_audit_content_hash(envelope) != envelope.envelope_hash:
        raise DomainViolation(f"research run audit envelope hash mismatch: {path}")
    return envelope


def write_research_run_audit_envelope(
    path: Path,
    envelope: ResearchRunAuditEnvelope,
) -> ResearchRunAuditEnvelope:
    """Persist an audit-only envelope atomically and write-once."""
    if research_run_audit_content_hash(envelope) != envelope.envelope_hash:
        raise DomainViolation("research run audit envelope hash mismatch")
    if path.exists():
        existing = read_research_run_audit_envelope(path)
        if existing != envelope:
            raise DomainViolation(f"research run audit envelope path is immutable: {path}")
        return existing

    payload = json.dumps(envelope.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_research_run_audit_envelope(path)
        if existing != envelope:
            raise DomainViolation(
                f"research run audit envelope path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_research_run_audit_envelope(path)


__all__ = [
    "read_research_run_audit_envelope",
    "write_research_run_audit_envelope",
]
