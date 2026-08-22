from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.creator_qualification import (
    CreatorQualificationFailure,
    CreatorQualificationResult,
)
from autonomous_futures.research.creator_qualification_persistence import (
    persist_creator_qualification_result,
)
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
    build_creator_candidate_qualification_artifact,
    read_creator_candidate_qualification_artifact,
)

HASH = "a" * 64
CREATED_AT = datetime(2026, 8, 22, tzinfo=UTC)


def _candidate():
    return build_creator_candidate_artifact(
        candidate_id="cand-persist-001",
        strategy=StrategySpec(
            dsl_version=1,
            strategy_id="cand-persist-001",
            family="range_mean_reversion",
            universe=StrategyUniverse(
                symbols=("DOGEUSDT",), timeframe="5m", regime_context_timeframe="15m"
            ),
            features=(FeatureRef(name="rsi", lookback=14, shift=1),),
            entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
            exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
            vetoes=("testing_only_no_promotion",),
        ),
        bundle_hash=HASH,
        dataset_registry_hash=HASH,
        creator_run_id="creator-persist-001",
        research_seed=1,
        created_at=CREATED_AT,
    )


def _qualification(candidate, evaluator_run_id: str = "oos-persist-001"):
    gates = (
        QualificationGateResult(
            gate_id="oos_return_min",
            passed=False,
            observed=Decimal("-1"),
            threshold=Decimal("0"),
            comparator="gte",
            reason_code="oos_return_below_threshold",
        ),
    )
    return build_creator_candidate_qualification_artifact(
        candidate=candidate,
        evaluator_run_id=evaluator_run_id,
        evaluator_version="cached-oos-v1",
        decision="rejected",
        metrics=(QualificationMetric(metric_id="oos_return_pct", value=Decimal("-1")),),
        gates=gates,
        windows_evaluated=1,
        evaluated_at=CREATED_AT,
        qualification_policy_id="policy-persist-001",
        oos_aggregation_hash=HASH,
        source="walk_forward_oos",
    )


def test_persists_rejected_qualification_and_reads_it_back(tmp_path: Path) -> None:
    artifact = _qualification(_candidate())
    result = CreatorQualificationResult(qualifications=(artifact,))

    persisted = persist_creator_qualification_result(result, root=tmp_path)

    assert persisted == (artifact,)
    assert (
        read_creator_candidate_qualification_artifact(tmp_path / "cand-persist-001.json")
        == artifact
    )


def test_blocked_candidates_create_no_qualification_file(tmp_path: Path) -> None:
    result = CreatorQualificationResult(
        blocked_candidate_ids=("cand-blocked-001",),
        failures=(
            CreatorQualificationFailure(
                candidate_id="cand-blocked-001",
                reason_code="cached_evaluation_blocked",
            ),
        ),
    )

    assert persist_creator_qualification_result(result, root=tmp_path) == ()
    assert tuple(tmp_path.iterdir()) == ()


def test_conflicting_qualification_artifact_is_rejected(tmp_path: Path) -> None:
    candidate = _candidate()
    first = _qualification(candidate)
    second = _qualification(candidate, evaluator_run_id="oos-persist-002")
    persist_creator_qualification_result(
        CreatorQualificationResult(qualifications=(first,)), root=tmp_path
    )

    with pytest.raises(DomainViolation, match="immutable"):
        persist_creator_qualification_result(
            CreatorQualificationResult(qualifications=(second,)), root=tmp_path
        )
