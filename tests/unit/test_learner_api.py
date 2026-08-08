from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pandas as pd
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
from autonomous_futures.research.learner_qualification import (
    LearnerQualificationEvidence,
    LearnerQualificationPolicy,
    LearnerQualificationPolicyGate,
    build_learner_qualification_evidence,
    learner_qualification_content_hash,
    write_learner_qualification_evidence,
)
from autonomous_futures.research.learner_quality_review import (
    LearnerQualityReviewMetric,
    LearnerQualityReviewWindow,
    LearnerQualityReviewWindowResult,
    LearnerQualityReviewWindowSpec,
    execute_learner_quality_review,
    write_learner_quality_review_evidence,
)
from autonomous_futures.research.learner_runs import (
    LearnerRun,
    learner_run_content_hash,
    write_learner_run,
)
from autonomous_futures.research.learner_training_evidence import (
    build_learner_training_evidence,
    write_learner_training_evidence,
)

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


def _write_fixture(
    tmp_path: Path,
    *,
    with_run: bool = False,
    with_training_evidence: bool = False,
    with_quality_review: bool = False,
    with_qualification: bool = False,
) -> tuple[FastAPI, Path, Path | None]:
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

    run: LearnerRun | None = None
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
        write_learner_run(run_path, run)

    evidence_path: Path | None = None
    if with_training_evidence:
        if run is None:
            raise AssertionError("training evidence fixture requires a persisted run")
        output_bytes = b"verified trained learner model bytes"
        output_model_path = model_root / "output.bin"
        output_model_path.write_bytes(output_bytes)
        output = build_learner_artifact(
            candidate=candidate,
            learner_id=learner.learner_id,
            learner_run_id=run.run_id,
            learner_version="output-v1",
            model_family="explicit-test-output",
            feature_ids=learner.feature_ids,
            training_window_start=START,
            training_window_end=END,
            model_artifact_ref="output.bin",
            model_artifact_hash=hashlib.sha256(output_bytes).hexdigest(),
            created_at=OBSERVED,
        )
        output_path = tmp_path / "trained" / "learner.json"
        write_learner_artifact(output_path, output, model_root=model_root)
        evidence = build_learner_training_evidence(
            prepared_run=run,
            source_learner=learner,
            output_artifact=output,
            candidate=candidate,
            source_learner_artifact_ref="learner-artifact.json",
            prepared_run_ref="learner-run.json",
            output_artifact_ref="trained/learner.json",
            created_at=OBSERVED,
        )
        evidence_path = tmp_path / "learner-training-evidence.json"
        write_learner_training_evidence(
            evidence_path,
            evidence,
            run_root=tmp_path,
            artifact_root=tmp_path,
            model_root=model_root,
            candidate=candidate,
        )

    quality_review_path: Path | None = None
    if with_quality_review:
        if run is None or evidence_path is None:
            raise AssertionError("quality review fixture requires training evidence")
        review_start = END
        review_frame = pd.DataFrame(
            {
                "timestamp": [review_start + timedelta(minutes=5 * index) for index in range(3)],
                "open": [Decimal("100"), Decimal("101"), Decimal("102")],
                "high": [Decimal("101"), Decimal("102"), Decimal("103")],
                "low": [Decimal("99"), Decimal("100"), Decimal("101")],
                "close": [Decimal("100.5"), Decimal("101.5"), Decimal("102.5")],
            }
        )
        review_window = LearnerQualityReviewWindow(
            spec=LearnerQualityReviewWindowSpec(
                window_id="window-api-quality",
                symbol=SYMBOL,
                bundle_hash=output.bundle_hash,
                dataset_registry_hash=output.dataset_registry_hash,
                split="holdout",
                time_start=review_start,
                time_end=review_start + timedelta(minutes=15),
            ),
            frame=review_frame,
        )

        def reviewer(received_output, frame, window):
            return LearnerQualityReviewWindowResult(
                window_id=window.spec.window_id,
                symbol=window.spec.symbol,
                rows_evaluated=len(frame),
                metrics=(
                    LearnerQualityReviewMetric(metric_id="holdout_score", value=Decimal("0.75")),
                ),
            )

        quality_evidence = execute_learner_quality_review(
            training_evidence=evidence,
            output_artifact=output,
            candidate=candidate,
            windows=(review_window,),
            review_run_id="quality-review-api",
            review_version="holdout-review-v1",
            reviewer=reviewer,
            reviewed_at=OBSERVED,
        )
        quality_review_path = tmp_path / "learner-quality-review-evidence.json"
        write_learner_quality_review_evidence(
            quality_review_path,
            quality_evidence,
            training_evidence=evidence,
            output_artifact=output,
            candidate=candidate,
        )

    qualification_path: Path | None = None
    qualification_policy_path: Path | None = None
    if with_qualification:
        if not with_quality_review or quality_review_path is None:
            raise AssertionError("qualification fixture requires quality-review evidence")
        policy = LearnerQualificationPolicy(
            policy_id="learner-holdout-v1",
            minimum_windows=1,
            gates=(
                LearnerQualificationPolicyGate(
                    metric_id="holdout_score",
                    comparator="gte",
                    threshold=Decimal("0.50"),
                ),
            ),
        )
        qualification = build_learner_qualification_evidence(
            training_evidence=evidence,
            quality_review=quality_evidence,
            output_artifact=output,
            candidate=candidate,
            policy=policy,
            evaluated_at=OBSERVED,
        )
        qualification_path = tmp_path / "learner-qualification-evidence.json"
        write_learner_qualification_evidence(
            qualification_path,
            qualification,
            training_evidence=evidence,
            quality_review=quality_evidence,
            output_artifact=output,
            candidate=candidate,
            policy=policy,
        )
        qualification_policy_path = tmp_path / "learner-qualification-policy.json"
        qualification_policy_path.write_text(policy.model_dump_json(), encoding="utf-8")

    app = create_app(
        bundle_path=bundle_path,
        registry_path=registry_path,
        creator_candidate_registry_path=candidate_registry_path,
        creator_candidate_artifact_root=candidate_root,
        learner_artifact_path=artifact_path,
        learner_model_root=model_root,
        learner_run_path=run_path or tmp_path / "missing-learner-run.json",
        learner_training_evidence_path=evidence_path
        or tmp_path / "missing-learner-training-evidence.json",
        learner_training_artifact_root=tmp_path,
        learner_quality_review_evidence_path=quality_review_path
        or tmp_path / "missing-learner-quality-review-evidence.json",
        learner_qualification_evidence_path=qualification_path
        or tmp_path / "missing-learner-qualification-evidence.json",
        learner_qualification_policy_path=qualification_policy_path
        or tmp_path / "missing-learner-qualification-policy.json",
    )
    return app, artifact_path, run_path


def test_learner_evidence_endpoints_are_get_only_and_missing_is_unavailable(tmp_path: Path) -> None:
    app = create_app(
        learner_artifact_path=tmp_path / "missing-artifact.json",
        learner_model_root=tmp_path / "models",
        learner_run_path=tmp_path / "missing-run.json",
        learner_quality_review_evidence_path=tmp_path / "missing-quality-review.json",
    )

    artifact_response = _request(app, "GET", "/api/v1/learner/artifact")
    run_response = _request(app, "GET", "/api/v1/learner/run")

    assert artifact_response.status_code == 404
    assert artifact_response.json() == {"detail": "learner artifact unavailable"}
    assert run_response.status_code == 404
    assert run_response.json() == {"detail": "learner run unavailable"}
    training_response = _request(app, "GET", "/api/v1/learner/training-evidence")
    assert training_response.status_code == 404
    assert training_response.json() == {"detail": "learner training evidence unavailable"}
    quality_response = _request(app, "GET", "/api/v1/learner/quality-review")
    assert quality_response.status_code == 404
    assert quality_response.json() == {"detail": "learner quality review unavailable"}
    qualification_response = _request(app, "GET", "/api/v1/learner/qualification")
    assert qualification_response.status_code == 404
    assert qualification_response.json() == {"detail": "learner qualification unavailable"}
    assert _request(app, "POST", "/api/v1/learner/artifact").status_code == 405
    assert _request(app, "POST", "/api/v1/learner/run").status_code == 405
    assert _request(app, "POST", "/api/v1/learner/training-evidence").status_code == 405
    assert _request(app, "POST", "/api/v1/learner/quality-review").status_code == 405
    assert _request(app, "POST", "/api/v1/learner/qualification").status_code == 405


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


def test_learner_run_endpoint_fails_closed_on_malformed_persisted_run(tmp_path: Path) -> None:
    app, _, run_path = _write_fixture(tmp_path, with_run=True)
    assert run_path is not None
    run_path.write_text("{ malformed learner run", encoding="utf-8")

    response = _request(app, "GET", "/api/v1/learner/run")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner run integrity verification failed"}


def test_learner_training_evidence_endpoint_returns_completed_provenance(
    tmp_path: Path,
) -> None:
    app, _, _ = _write_fixture(tmp_path, with_run=True, with_training_evidence=True)

    response = _request(app, "GET", "/api/v1/learner/training-evidence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["evidence"]["status"] == "completed"
    assert payload["evidence"]["output_artifact_hash"] != "0" * 64
    assert payload["evidence"]["training_metrics"] is None
    assert payload["evidence"]["promotion_state"] == "unpromoted"
    assert payload["evidence"]["paper_activation"] is False
    assert payload["evidence"]["execution_authority"] is False


def test_learner_training_evidence_endpoint_fails_closed_on_tampered_output_model(
    tmp_path: Path,
) -> None:
    app, _, _ = _write_fixture(tmp_path, with_run=True, with_training_evidence=True)
    (tmp_path / "models" / "output.bin").write_bytes(b"tampered output model")

    response = _request(app, "GET", "/api/v1/learner/training-evidence")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner training evidence integrity verification failed"}


def test_learner_training_evidence_endpoint_fails_closed_on_malformed_evidence(
    tmp_path: Path,
) -> None:
    app, _, _ = _write_fixture(tmp_path, with_run=True, with_training_evidence=True)
    (tmp_path / "learner-training-evidence.json").write_text(
        "{ malformed training evidence",
        encoding="utf-8",
    )

    response = _request(app, "GET", "/api/v1/learner/training-evidence")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner training evidence integrity verification failed"}


def test_learner_training_evidence_endpoint_fails_closed_on_tampered_source_artifact(
    tmp_path: Path,
) -> None:
    app, artifact_path, _ = _write_fixture(tmp_path, with_run=True, with_training_evidence=True)
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8").replace(
            '"artifact_hash": "', '"artifact_hash": "0'
        ),
        encoding="utf-8",
    )

    response = _request(app, "GET", "/api/v1/learner/training-evidence")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner training evidence integrity verification failed"}


def test_learner_quality_review_endpoint_returns_verified_observation_only_evidence(
    tmp_path: Path,
) -> None:
    app, _, _ = _write_fixture(
        tmp_path,
        with_run=True,
        with_training_evidence=True,
        with_quality_review=True,
    )

    response = _request(app, "GET", "/api/v1/learner/quality-review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["evidence"]["status"] == "completed"
    assert payload["evidence"]["review_conclusion"] == "observed_only"
    assert payload["evidence"]["split"] == "holdout"
    assert payload["evidence"]["windows"][0]["metrics"][0]["value"] == "0.75"
    assert payload["evidence"]["promotion_state"] == "unpromoted"
    assert payload["evidence"]["paper_activation"] is False
    assert payload["evidence"]["execution_authority"] is False


def test_learner_quality_review_endpoint_fails_closed_on_tampered_review(
    tmp_path: Path,
) -> None:
    app, _, _ = _write_fixture(
        tmp_path,
        with_run=True,
        with_training_evidence=True,
        with_quality_review=True,
    )
    review_path = tmp_path / "learner-quality-review-evidence.json"
    review_path.write_text(
        review_path.read_text(encoding="utf-8").replace('"review_hash": "', '"review_hash": "0'),
        encoding="utf-8",
    )

    response = _request(app, "GET", "/api/v1/learner/quality-review")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner quality review integrity verification failed"}


def test_learner_qualification_endpoint_returns_verified_evidence_only(
    tmp_path: Path,
) -> None:
    app, _, _ = _write_fixture(
        tmp_path,
        with_run=True,
        with_training_evidence=True,
        with_quality_review=True,
        with_qualification=True,
    )
    candidate_path = tmp_path / "creator-artifacts" / "candidates" / "cand-learner-api.json"
    registry_path = tmp_path / "creator-candidate-registry.json"
    candidate_before = candidate_path.read_bytes()
    registry_before = registry_path.read_bytes()

    response = _request(app, "GET", "/api/v1/learner/qualification")

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["evidence"]["decision"] == "qualified"
    assert payload["evidence"]["policy_id"] == "learner-holdout-v1"
    assert payload["evidence"]["metrics"][0]["observed"] == "0.75"
    assert payload["evidence"]["promotion_state"] == "unpromoted"
    assert payload["evidence"]["paper_activation"] is False
    assert payload["evidence"]["execution_authority"] is False
    assert candidate_path.read_bytes() == candidate_before
    assert registry_path.read_bytes() == registry_before


def test_learner_qualification_endpoint_fails_closed_on_tampered_evidence(
    tmp_path: Path,
) -> None:
    app, _, _ = _write_fixture(
        tmp_path,
        with_run=True,
        with_training_evidence=True,
        with_quality_review=True,
        with_qualification=True,
    )
    qualification_path = tmp_path / "learner-qualification-evidence.json"
    qualification_path.write_text(
        qualification_path.read_text(encoding="utf-8").replace(
            '"qualification_hash": "', '"qualification_hash": "0'
        ),
        encoding="utf-8",
    )

    response = _request(app, "GET", "/api/v1/learner/qualification")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner qualification integrity verification failed"}


def test_learner_qualification_endpoint_rejects_valid_hash_with_binding_drift(
    tmp_path: Path,
) -> None:
    app, _, _ = _write_fixture(
        tmp_path,
        with_run=True,
        with_training_evidence=True,
        with_quality_review=True,
        with_qualification=True,
    )
    qualification_path = tmp_path / "learner-qualification-evidence.json"
    payload = json.loads(qualification_path.read_text(encoding="utf-8"))
    payload["candidate_id"] = "cand-other"
    payload["qualification_hash"] = "0" * 64
    tampered = LearnerQualificationEvidence.model_validate(payload)
    payload["qualification_hash"] = learner_qualification_content_hash(tampered)
    qualification_path.write_text(json.dumps(payload), encoding="utf-8")

    response = _request(app, "GET", "/api/v1/learner/qualification")

    assert response.status_code == 503
    assert response.json() == {"detail": "learner qualification integrity verification failed"}
