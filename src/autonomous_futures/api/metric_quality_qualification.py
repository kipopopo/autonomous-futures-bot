from __future__ import annotations

from pathlib import Path

from ..research.creator_artifacts import CreatorCandidateArtifact
from ..research.learner_artifacts import LearnerArtifact
from ..research.learner_metric_quality_decision import LearnerMetricQualityPolicy
from ..research.learner_metric_quality_qualification import (
    LearnerMetricQualityQualificationEvidence,
    LearnerMetricQualityQualificationPolicy,
)
from ..research.learner_metric_quality_qualification_evidence_input import (
    load_verified_learner_metric_quality_qualification_evidence,
)


class LearnerMetricQualityQualificationEvidenceNotFoundError(FileNotFoundError):
    """One required persisted metric-quality qualification artifact is unavailable."""


class LearnerMetricQualityQualificationEvidenceIntegrityError(ValueError):
    """Metric-quality qualification evidence cannot be trusted after verification."""


def _read_source_policy(path: Path) -> LearnerMetricQualityPolicy:
    try:
        return LearnerMetricQualityPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LearnerMetricQualityQualificationEvidenceNotFoundError(path) from exc
    except OSError as exc:
        raise LearnerMetricQualityQualificationEvidenceIntegrityError(
            "metric-quality source policy cannot be read"
        ) from exc
    except ValueError as exc:
        raise LearnerMetricQualityQualificationEvidenceIntegrityError(
            "invalid persisted metric-quality source policy"
        ) from exc


def _read_qualification_policy(path: Path) -> LearnerMetricQualityQualificationPolicy:
    try:
        return LearnerMetricQualityQualificationPolicy.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise LearnerMetricQualityQualificationEvidenceNotFoundError(path) from exc
    except OSError as exc:
        raise LearnerMetricQualityQualificationEvidenceIntegrityError(
            "metric-quality qualification policy cannot be read"
        ) from exc
    except ValueError as exc:
        raise LearnerMetricQualityQualificationEvidenceIntegrityError(
            "invalid persisted metric-quality qualification policy"
        ) from exc


def load_verified_metric_quality_qualification_evidence(
    *,
    qualification_evidence_path: Path,
    decision_path: Path,
    review_path: Path,
    metric_evaluation_path: Path,
    source_policy_path: Path,
    qualification_policy_path: Path,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> LearnerMetricQualityQualificationEvidence:
    """Load Phase 3AD evidence through typed policies and its full-chain verifier."""
    try:
        source_policy = _read_source_policy(source_policy_path)
        qualification_policy = _read_qualification_policy(qualification_policy_path)
        return load_verified_learner_metric_quality_qualification_evidence(
            qualification_evidence_path,
            decision_path,
            review_path,
            metric_evaluation_path,
            learner=learner,
            candidate=candidate,
            source_policy=source_policy,
            qualification_policy=qualification_policy,
        )
    except LearnerMetricQualityQualificationEvidenceNotFoundError:
        raise
    except FileNotFoundError as exc:
        raise LearnerMetricQualityQualificationEvidenceNotFoundError(
            exc.filename or "evidence"
        ) from exc
    except (OSError, ValueError) as exc:
        raise LearnerMetricQualityQualificationEvidenceIntegrityError(
            "metric-quality qualification evidence integrity verification failed"
        ) from exc


__all__ = [
    "LearnerMetricQualityQualificationEvidenceIntegrityError",
    "LearnerMetricQualityQualificationEvidenceNotFoundError",
    "load_verified_metric_quality_qualification_evidence",
]
