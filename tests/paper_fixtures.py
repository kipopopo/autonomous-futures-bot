"""Test-only paper fixtures; never promotion or complete-history authority."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
    build_creator_candidate_qualification_artifact,
    read_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)

if TYPE_CHECKING:
    from autonomous_futures.paper.live_engine import LivePaperEngine


def load_legacy_indicator_candidates_fixture() -> dict[str, CreatorCandidateArtifact]:
    """Explicit archived indicator fixtures; not admission or complete-history authority."""
    candidates_dir = Path(__file__).resolve().parents[1] / "artifacts/research/phase252/candidates"
    candidate_ids = {
        "BTCUSDT": "cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74",
        "ETHUSDT": "cand-1f87c23b87c117a5909a32a38dd44f0001b66d70f6a0818375a6e95d429aa632",
        "SOLUSDT": "cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd",
        "DOGEUSDT": "cand-09891e9fead9965035c61117e65bd12a9e6b59f179905ec7c5d2963288f8f2a8",
    }
    return {
        symbol: read_creator_candidate_artifact(candidates_dir / f"{candidate_id}.json")
        for symbol, candidate_id in candidate_ids.items()
    }


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


def admit_paper_candidates_fixture(engine: LivePaperEngine, root: Path) -> None:
    """Explicit test-only admission through the real engine, never production authority."""
    for symbol, candidate in tuple(engine.candidates.items()):
        qualification_hash = write_qualified_paper_fixture(root / "candidate.json", candidate)
        qualification = read_creator_candidate_qualification_artifact(
            root / "qualifications" / f"{qualification_hash}.json"
        )
        decision = engine.admit_candidate(
            candidate,
            qualification=qualification,
            qualification_hash=qualification_hash,
            symbol=symbol,
        )
        assert decision.decision == "admitted"
