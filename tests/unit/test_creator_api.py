from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from autonomous_futures.api import create_app
from autonomous_futures.api.creator import (
    CreatorCandidateRegistryIntegrityError,
    collect_verified_creator_candidate_ids,
)
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import (
    build_creator_candidate_artifact,
    build_creator_candidate_registry,
    write_creator_candidate_artifact,
    write_creator_candidate_registry,
)
from autonomous_futures.research.creator_proposals import canonical_creator_candidate_id

CREATED_AT = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _strategy() -> StrategySpec:
    return StrategySpec(
        dsl_version=1,
        strategy_id="cand-api-001",
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )


def _request(app: FastAPI, method: str, path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(send())


def _write_creator_fixture(tmp_path: Path) -> tuple[FastAPI, Path]:
    artifact = build_creator_candidate_artifact(
        candidate_id="cand-api-001",
        strategy=_strategy(),
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-run-api",
        research_seed=23,
        created_at=CREATED_AT,
    )
    artifact_root = tmp_path / "creator-artifacts"
    artifact_path = artifact_root / "candidates" / "cand-api-001.json"
    write_creator_candidate_artifact(artifact_path, artifact)
    registry = build_creator_candidate_registry(
        ((artifact, "candidates/cand-api-001.json"),),
        created_at=CREATED_AT,
    )
    registry_path = tmp_path / "creator-candidate-registry.json"
    write_creator_candidate_registry(registry_path, registry)
    return (
        create_app(
            bundle_path=tmp_path / "missing-bundle.json",
            registry_path=tmp_path / "missing-dataset-registry.json",
            artifact_root=tmp_path / "missing-artifacts",
            creator_candidate_registry_path=registry_path,
            creator_candidate_artifact_root=artifact_root,
        ),
        artifact_path,
    )


def test_creator_registry_endpoint_returns_verified_metadata_only(tmp_path: Path) -> None:
    app, _ = _write_creator_fixture(tmp_path)

    response = _request(app, "GET", "/api/v1/creator/registry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["candidate_count"] == 1
    assert payload["registry"]["entries"][0]["candidate_id"] == "cand-api-001"
    assert payload["registry"]["entries"][0]["state"] == "testing"
    assert "strategy" not in payload["registry"]["entries"][0]
    assert "order" not in payload


def test_creator_registry_is_get_only_and_missing_registry_is_unavailable(tmp_path: Path) -> None:
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-dataset-registry.json",
        artifact_root=tmp_path / "missing-artifacts",
        creator_candidate_registry_path=tmp_path / "missing-creator-registry.json",
        creator_candidate_artifact_root=tmp_path,
    )

    response = _request(app, "GET", "/api/v1/creator/registry")

    assert response.status_code == 404
    assert response.json() == {"detail": "creator candidate registry unavailable"}
    assert _request(app, "POST", "/api/v1/creator/registry").status_code == 405


def test_creator_registry_fails_closed_on_tampered_artifact(tmp_path: Path) -> None:
    app, artifact_path = _write_creator_fixture(tmp_path)
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8").replace(
            "creator-run-api", "creator-run-tampered"
        ),
        encoding="utf-8",
    )

    response = _request(app, "GET", "/api/v1/creator/registry")

    assert response.status_code == 503
    assert response.json() == {"detail": "creator candidate registry integrity verification failed"}


def test_verified_creator_candidate_history_collects_every_registry(tmp_path: Path) -> None:
    history_root = tmp_path / "history"
    artifacts = []
    for run_id, candidate_id in (("run-a", "cand-history-a"), ("run-b", "cand-history-b")):
        artifact = build_creator_candidate_artifact(
            candidate_id=candidate_id,
            strategy=_strategy().model_copy(update={"strategy_id": candidate_id}),
            bundle_hash="a" * 64,
            dataset_registry_hash="b" * 64,
            creator_run_id=run_id,
            research_seed=23,
            created_at=CREATED_AT,
        )
        run_root = history_root / run_id
        write_creator_candidate_artifact(run_root / "candidates" / f"{candidate_id}.json", artifact)
        registry = build_creator_candidate_registry(
            ((artifact, f"candidates/{candidate_id}.json"),), created_at=CREATED_AT
        )
        write_creator_candidate_registry(run_root / "creator-candidate-registry.json", registry)
        artifacts.extend((candidate_id, canonical_creator_candidate_id(artifact.strategy)))

    assert collect_verified_creator_candidate_ids(history_root) == tuple(sorted(set(artifacts)))


def test_verified_creator_candidate_history_rejects_tampered_artifact(tmp_path: Path) -> None:
    app, artifact_path = _write_creator_fixture(tmp_path)
    del app
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8").replace(
            "creator-run-api", "creator-run-tampered"
        ),
        encoding="utf-8",
    )

    with pytest.raises(CreatorCandidateRegistryIntegrityError):
        collect_verified_creator_candidate_ids(tmp_path)


def test_verified_creator_candidate_history_rejects_conflicting_identity(tmp_path: Path) -> None:
    history_root = tmp_path / "history"
    for run_id, seed in (("run-a", 23), ("run-b", 24)):
        artifact = build_creator_candidate_artifact(
            candidate_id="cand-history-conflict",
            strategy=_strategy().model_copy(update={"strategy_id": "cand-history-conflict"}),
            bundle_hash="a" * 64,
            dataset_registry_hash="b" * 64,
            creator_run_id=run_id,
            research_seed=seed,
            created_at=CREATED_AT,
        )
        run_root = history_root / run_id
        write_creator_candidate_artifact(
            run_root / "candidates" / "cand-history-conflict.json", artifact
        )
        registry = build_creator_candidate_registry(
            ((artifact, "candidates/cand-history-conflict.json"),), created_at=CREATED_AT
        )
        write_creator_candidate_registry(run_root / "creator-candidate-registry.json", registry)

    with pytest.raises(CreatorCandidateRegistryIntegrityError, match="multiple artifacts"):
        collect_verified_creator_candidate_ids(history_root)


def test_verified_creator_candidate_history_includes_canonical_strategy_identity(
    tmp_path: Path,
) -> None:
    artifact = build_creator_candidate_artifact(
        candidate_id="cand-provider-history",
        strategy=_strategy().model_copy(update={"strategy_id": "cand-provider-history"}),
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="run-history",
        research_seed=23,
        created_at=CREATED_AT,
    )
    run_root = tmp_path / "history"
    write_creator_candidate_artifact(
        run_root / "candidates" / "cand-provider-history.json", artifact
    )
    registry = build_creator_candidate_registry(
        ((artifact, "candidates/cand-provider-history.json"),), created_at=CREATED_AT
    )
    write_creator_candidate_registry(run_root / "creator-candidate-registry.json", registry)

    assert collect_verified_creator_candidate_ids(run_root) == tuple(
        sorted((artifact.candidate_id, canonical_creator_candidate_id(artifact.strategy)))
    )
