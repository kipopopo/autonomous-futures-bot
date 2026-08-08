from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI

from autonomous_futures.api import create_app
from autonomous_futures.data.bundle import build_dataset_bundle, write_dataset_bundle
from autonomous_futures.data.registry import (
    DatasetRegistryEntry,
    build_dataset_registry,
    write_dataset_registry,
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
from autonomous_futures.research.learner_artifacts import (
    build_learner_artifact,
    write_learner_artifact,
)
from autonomous_futures.research.learner_runs import LearnerRun, learner_run_content_hash

START = datetime(2026, 8, 7, tzinfo=UTC)
END = START + timedelta(hours=1)
OBSERVED = datetime(2026, 8, 7, 12, tzinfo=UTC)
SYMBOL = "BTCUSDT"


def _entry(
    kind: str,
    *,
    interval: str | None,
    start: datetime | None,
    end: datetime | None,
    content_hash: str,
) -> DatasetRegistryEntry:
    endpoints = {
        "kline": "/fapi/v1/klines",
        "mark_price": "/fapi/v1/markPriceKlines",
        "funding_rate": "/fapi/v1/fundingRate",
        "exchange_filters": "/fapi/v1/exchangeInfo",
    }
    return DatasetRegistryEntry(
        kind=kind,
        symbols=(SYMBOL,),
        interval=interval,
        time_start=start,
        time_end=end,
        observed_at=OBSERVED,
        schema_version=f"{kind}-v1",
        content_hash=content_hash,
        artifact_ref=f"artifacts/{kind}.json",
        endpoint_path=endpoints[kind],
        provenance=("binance_public_rest", "unsigned", "api_fixture"),
    )


def _strategy() -> StrategySpec:
    return StrategySpec(
        dsl_version=1,
        strategy_id="cand-learner-api",
        family="experimental",
        universe=StrategyUniverse(
            symbols=(SYMBOL,), timeframe="5m", regime_context_timeframe="15m"
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


def _write_fixture(tmp_path: Path, *, with_run: bool = False) -> tuple[FastAPI, Path, Path | None]:
    entries = (
        _entry(
            "kline",
            interval="5m",
            start=START,
            end=END - timedelta(minutes=5),
            content_hash="1" * 64,
        ),
        _entry(
            "kline",
            interval="15m",
            start=START - timedelta(minutes=15),
            end=END - timedelta(minutes=15),
            content_hash="2" * 64,
        ),
        _entry("mark_price", interval="5m", start=START, end=END, content_hash="3" * 64),
        _entry(
            "funding_rate",
            interval=None,
            start=START - timedelta(hours=8),
            end=END + timedelta(hours=8),
            content_hash="4" * 64,
        ),
        _entry("exchange_filters", interval=None, start=None, end=None, content_hash="5" * 64),
    )
    registry = build_dataset_registry(entries, created_at=OBSERVED)
    registry_path = tmp_path / "dataset-registry.json"
    write_dataset_registry(registry_path, registry)
    bundle = build_dataset_bundle(
        registry, symbols=(SYMBOL,), time_start=START, time_end=END, created_at=OBSERVED
    )
    bundle_path = tmp_path / "dataset-bundle.json"
    write_dataset_bundle(bundle_path, bundle)

    candidate = build_creator_candidate_artifact(
        candidate_id="cand-learner-api",
        strategy=_strategy(),
        bundle_hash=bundle.bundle_hash,
        dataset_registry_hash=registry.registry_hash,
        creator_run_id="creator-run-api",
        research_seed=23,
        created_at=OBSERVED,
    )
    candidate_root = tmp_path / "creator-artifacts"
    write_creator_candidate_artifact(
        candidate_root / "candidates" / "cand-learner-api.json", candidate
    )
    candidate_registry = build_creator_candidate_registry(
        ((candidate, "candidates/cand-learner-api.json"),), created_at=OBSERVED
    )
    candidate_registry_path = tmp_path / "creator-candidate-registry.json"
    write_creator_candidate_registry(candidate_registry_path, candidate_registry)

    model_root = tmp_path / "models"
    model_path = model_root / "learner.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"verified learner model bytes")
    import hashlib

    learner = build_learner_artifact(
        candidate=candidate,
        learner_id="learner-api-001",
        learner_run_id="learner-run-api",
        learner_version="v1",
        model_family="explicit-test",
        feature_ids=("returns",),
        training_window_start=START,
        training_window_end=END,
        model_artifact_ref="learner.bin",
        model_artifact_hash=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        created_at=OBSERVED,
    )
    artifact_path = tmp_path / "learner-artifact.json"
    write_learner_artifact(artifact_path, learner, model_root=model_root)

    run_path: Path | None = None
    if with_run:
        run = LearnerRun(
            run_id="run-learner-api",
            learner_id=learner.learner_id,
            learner_run_id=learner.learner_run_id,
            learner_version=learner.learner_version,
            learner_artifact_hash=learner.artifact_hash,
            candidate_id=learner.candidate_id,
            candidate_artifact_hash=learner.candidate_artifact_hash,
            bundle_hash=learner.bundle_hash,
            dataset_registry_hash=learner.dataset_registry_hash,
            input_window_ids=("input-api-001",),
            input_symbols=(SYMBOL,),
            feature_ids=learner.feature_ids,
            training_window_start=START,
            training_window_end=END,
            prepared_at=OBSERVED,
            run_hash="0" * 64,
        )
        run = run.model_copy(update={"run_hash": learner_run_content_hash(run)})
        run_path = tmp_path / "learner-run.json"
        run_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")

    app = create_app(
        bundle_path=bundle_path,
        registry_path=registry_path,
        creator_candidate_registry_path=candidate_registry_path,
        creator_candidate_artifact_root=candidate_root,
        learner_artifact_path=artifact_path,
        learner_model_root=model_root,
        learner_run_path=run_path or tmp_path / "missing-learner-run.json",
    )
    return app, artifact_path, run_path


def test_learner_evidence_endpoints_are_get_only_and_missing_is_unavailable(tmp_path: Path) -> None:
    app = create_app(
        learner_artifact_path=tmp_path / "missing-artifact.json",
        learner_model_root=tmp_path / "models",
        learner_run_path=tmp_path / "missing-run.json",
    )

    artifact_response = _request(app, "GET", "/api/v1/learner/artifact")
    run_response = _request(app, "GET", "/api/v1/learner/run")

    assert artifact_response.status_code == 404
    assert artifact_response.json() == {"detail": "learner artifact unavailable"}
    assert run_response.status_code == 404
    assert run_response.json() == {"detail": "learner run unavailable"}
    assert _request(app, "POST", "/api/v1/learner/artifact").status_code == 405
    assert _request(app, "POST", "/api/v1/learner/run").status_code == 405


def test_learner_artifact_endpoint_returns_verified_metadata_without_model_bytes(
    tmp_path: Path,
) -> None:
    app, artifact_path, _ = _write_fixture(tmp_path)

    response = _request(app, "GET", "/api/v1/learner/artifact")

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["artifact"]["learner_id"] == "learner-api-001"
    assert payload["artifact"]["state"] == "testing"
    assert payload["artifact"]["promotion_state"] == "unpromoted"
    assert payload["artifact"]["execution_authority"] is False
    assert "model_bytes" not in payload
    assert artifact_path.exists()


def test_learner_artifact_endpoint_fails_closed_on_tampered_model(tmp_path: Path) -> None:
    app, _, _ = _write_fixture(tmp_path)
    model_path = tmp_path / "models" / "learner.bin"
    model_path.write_bytes(b"tampered learner model bytes")

    response = _request(app, "GET", "/api/v1/learner/artifact")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner artifact integrity verification failed"}


def test_learner_run_endpoint_returns_verified_prepared_provenance(tmp_path: Path) -> None:
    app, _, run_path = _write_fixture(tmp_path, with_run=True)
    assert run_path is not None

    response = _request(app, "GET", "/api/v1/learner/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["run"]["status"] == "prepared"
    assert payload["run"]["output_artifact_hash"] is None
    assert payload["run"]["training_metrics"] is None
    assert payload["run"]["execution_authority"] is False


def test_learner_run_endpoint_fails_closed_on_tampered_hash(tmp_path: Path) -> None:
    app, _, run_path = _write_fixture(tmp_path, with_run=True)
    assert run_path is not None
    run_path.write_text(
        run_path.read_text(encoding="utf-8").replace('"run_hash": "', '"run_hash": "0'),
        encoding="utf-8",
    )

    response = _request(app, "GET", "/api/v1/learner/run")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner run integrity verification failed"}
