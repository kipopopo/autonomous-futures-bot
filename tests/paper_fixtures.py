"""Synthetic paper admission fixtures; never market or promotion evidence."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from autonomous_futures.research.creator_artifacts import CreatorCandidateArtifact
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
    build_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)


def write_qualified_paper_fixture(path: Path, candidate: CreatorCandidateArtifact) -> str:
    qualification = build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id="fixture-only-evaluator",
        evaluator_version="fixture-only",
        decision="qualified",
        metrics=(QualificationMetric(metric_id="fixture_metric", value=Decimal("1")),),
        gates=(
            QualificationGateResult(
                gate_id="fixture_gate", passed=True, comparator="bool", reason_code="fixture_only"
            ),
        ),
        windows_evaluated=1,
        qualification_policy_id="fixture-only-policy",
        oos_aggregation_hash="d" * 64,
        source="walk_forward_oos",
        evaluated_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    write_creator_candidate_qualification_artifact(
        path.parent / "qualifications" / f"{qualification.qualification_hash}.json",
        qualification,
    )
    return qualification.qualification_hash
