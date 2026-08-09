# ruff: noqa
from __future__ import annotations
import json, os
from pathlib import Path
from uuid import uuid4
from ..data.parquet import DataQualityError
from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation_observation_result import (
    ResearchObservationIntegrityEvaluationObservationObservationReview,
    research_observation_integrity_evaluation_observation_observation_review_content_hash,
)


def _validate(review: ResearchObservationIntegrityEvaluationObservationObservationReview) -> None:
    if (
        research_observation_integrity_evaluation_observation_observation_review_content_hash(
            review
        )
        != review.review_hash
    ):
        raise DomainViolation("review hash mismatch")


def _payload(review: ResearchObservationIntegrityEvaluationObservationObservationReview) -> str:
    return (
        json.dumps(
            review.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        + "\n"
    )


def write_research_observation_integrity_evaluation_observation_observation_review(
    path: Path, review: ResearchObservationIntegrityEvaluationObservationObservationReview
) -> None:
    _validate(review)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _payload(review)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp.write_text(payload, encoding="utf-8", newline="\n")
        try:
            os.link(temp, path)
        except FileExistsError:
            existing = (
                read_research_observation_integrity_evaluation_observation_observation_review(path)
            )
            if existing != review:
                raise DomainViolation("review path is immutable")
    finally:
        temp.unlink(missing_ok=True)


def read_research_observation_integrity_evaluation_observation_observation_review(
    path: Path,
) -> ResearchObservationIntegrityEvaluationObservationObservationReview:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DataQualityError("malformed review artifact") from e
    try:
        review = ResearchObservationIntegrityEvaluationObservationObservationReview.model_validate(
            raw
        )
    except ValueError as e:
        raise DataQualityError("invalid review artifact") from e
    _validate(review)
    return review
