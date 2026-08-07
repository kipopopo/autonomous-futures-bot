from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import (
    build_creator_candidate_artifact,
    build_creator_candidate_registry,
    find_creator_candidate,
    read_creator_candidate_artifact,
    read_creator_candidate_registry,
    write_creator_candidate_artifact,
    write_creator_candidate_registry,
)

CREATED_AT = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _strategy(strategy_id: str = "cand-001") -> StrategySpec:
    return StrategySpec(
        dsl_version=1,
        strategy_id=strategy_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )


def _artifact(
    *,
    candidate_id: str = "cand-001",
    created_at: datetime = CREATED_AT,
    strategy_id: str | None = None,
):
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=_strategy(strategy_id or candidate_id),
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-run-001",
        research_seed=17,
        created_at=created_at,
    )


def test_candidate_artifact_is_deterministic_and_defaults_to_testing() -> None:
    first = _artifact()
    second = _artifact(created_at=CREATED_AT + timedelta(hours=1))

    assert first.artifact_hash == second.artifact_hash
    assert first.state == "testing"
    assert first.strategy.strategy_id == first.candidate_id
    assert first.strategy.universe.timeframe == "5m"
    assert first.strategy.universe.regime_context_timeframe == "15m"


def test_candidate_artifact_rejects_strategy_identity_mismatch() -> None:
    with pytest.raises(DataQualityError, match="strategy_id"):
        _artifact(candidate_id="cand-001", strategy_id="cand-other")


def test_candidate_artifact_is_write_once_and_tamper_evident(tmp_path: Path) -> None:
    artifact = _artifact()
    path = tmp_path / "candidates" / "cand-001.json"

    write_creator_candidate_artifact(path, artifact)
    assert read_creator_candidate_artifact(path) == artifact
    assert write_creator_candidate_artifact(path, artifact) == artifact

    path.write_text(
        path.read_text(encoding="utf-8").replace("creator-run-001", "creator-run-002"),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_creator_candidate_artifact(path)


def test_candidate_registry_sorts_and_binds_artifacts() -> None:
    first = _artifact(candidate_id="cand-001")
    second = _artifact(candidate_id="cand-002")
    registry = build_creator_candidate_registry(
        (
            (second, "candidates/cand-002.json"),
            (first, "candidates/cand-001.json"),
        ),
        created_at=CREATED_AT,
    )

    assert [entry.candidate_id for entry in registry.entries] == ["cand-001", "cand-002"]
    assert registry.registry_hash
    assert registry.entries[0].artifact_hash == first.artifact_hash
    assert find_creator_candidate(registry, candidate_id="cand-002") == registry.entries[1]
    assert find_creator_candidate(registry, candidate_id="cand-missing") is None


def test_candidate_registry_rejects_mixed_dataset_bindings() -> None:
    first = _artifact(candidate_id="cand-001")
    second = build_creator_candidate_artifact(
        candidate_id="cand-002",
        strategy=_strategy("cand-002"),
        bundle_hash="c" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-run-001",
        research_seed=17,
        created_at=CREATED_AT,
    )

    with pytest.raises(DataQualityError, match="same dataset binding"):
        build_creator_candidate_registry(
            ((first, "candidates/cand-001.json"), (second, "candidates/cand-002.json")),
            created_at=CREATED_AT,
        )


def test_candidate_registry_is_write_once_and_tamper_evident(tmp_path: Path) -> None:
    artifact = _artifact()
    registry = build_creator_candidate_registry(
        ((artifact, "candidates/cand-001.json"),),
        created_at=CREATED_AT,
    )
    path = tmp_path / "creator-candidate-registry.json"

    write_creator_candidate_registry(path, registry)
    assert read_creator_candidate_registry(path) == registry
    assert write_creator_candidate_registry(path, registry) == registry

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "candidates/cand-001.json", "candidates/other.json"
        ),
        encoding="utf-8",
    )
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_creator_candidate_registry(path)


def test_candidate_contract_rejects_path_traversal_and_non_testing_state() -> None:
    artifact = _artifact()
    with pytest.raises(ValidationError, match="artifact_ref"):
        build_creator_candidate_registry(((artifact, "../cand-001.json"),), created_at=CREATED_AT)
