# ruff: noqa
from __future__ import annotations
import json, os
from pathlib import Path
from uuid import uuid4
from ..data.parquet import DataQualityError
from ..domain.errors import DomainViolation
from .research_observation_integrity_evaluation_observation_observation_handoff_observation_result import (
    ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview,
    research_observation_integrity_evaluation_observation_observation_handoff_observation_review_content_hash,
)


def _validate(
    r: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview,
) -> None:
    if (
        research_observation_integrity_evaluation_observation_observation_handoff_observation_review_content_hash(
            r
        )
        != r.review_hash
    ):
        raise DomainViolation("review hash mismatch")


def _payload(
    r: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview,
) -> str:
    return json.dumps(r.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"


def write_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
    path: Path,
    review: ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview,
) -> None:
    _validate(review)
    path.parent.mkdir(parents=True, exist_ok=True)
    t = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        t.write_text(_payload(review), encoding="utf-8", newline="\n")
        try:
            os.link(t, path)
        except FileExistsError:
            if (
                read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
                    path
                )
                != review
            ):
                raise DomainViolation("review path is immutable")
    finally:
        t.unlink(missing_ok=True)


def read_research_observation_integrity_evaluation_observation_observation_handoff_observation_review(
    path: Path,
) -> ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DataQualityError("malformed review artifact") from e
    try:
        r = ResearchObservationIntegrityEvaluationObservationObservationHandoffObservationReview.model_validate(
            raw
        )
    except ValueError as e:
        raise DataQualityError("invalid review artifact") from e
    _validate(r)
    return r
