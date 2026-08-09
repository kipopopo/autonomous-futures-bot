from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from ..data.parquet import DataQualityError
from ..domain.errors import DomainViolation
from .research_observation_integrity import (
    ResearchObservationIntegrityReview,
    research_observation_integrity_content_hash,
)


def read_research_observation_integrity_review(
    path: Path,
) -> ResearchObservationIntegrityReview:
    """Read and hash-verify one persisted integrity-only review."""
    try:
        review = ResearchObservationIntegrityReview.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except ValidationError as exc:
        if any("review hash mismatch" in error["msg"] for error in exc.errors()):
            raise DomainViolation(
                f"research observation integrity review hash mismatch: {path}"
            ) from None
        raise DataQualityError("invalid persisted research observation integrity review") from exc
    except ValueError as exc:
        raise DataQualityError("invalid persisted research observation integrity review") from exc
    if research_observation_integrity_content_hash(review) != review.review_hash:
        raise DomainViolation(f"research observation integrity review hash mismatch: {path}")
    return review


def write_research_observation_integrity_review(
    path: Path,
    review: ResearchObservationIntegrityReview,
) -> ResearchObservationIntegrityReview:
    """Persist an integrity-only review atomically and write-once."""
    if research_observation_integrity_content_hash(review) != review.review_hash:
        raise DomainViolation("research observation integrity review hash mismatch")
    if path.exists():
        existing = read_research_observation_integrity_review(path)
        if existing != review:
            raise DomainViolation(
                f"research observation integrity review path is immutable: {path}"
            )
        return existing

    payload = json.dumps(review.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_research_observation_integrity_review(path)
        if existing != review:
            raise DomainViolation(
                f"research observation integrity review path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_research_observation_integrity_review(path)


__all__ = [
    "read_research_observation_integrity_review",
    "write_research_observation_integrity_review",
]
