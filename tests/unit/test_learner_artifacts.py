from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.learner_artifacts import (
    build_learner_artifact,
    read_learner_artifact,
    verify_learner_artifact_binding,
    write_learner_artifact,
)

CREATED_AT = datetime(2026, 8, 8, 12, tzinfo=UTC)
WINDOW_START = datetime(2026, 8, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 8, tzinfo=UTC)


def _candidate(candidate_id: str = "cand-learner-001"):
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT", "ETHUSDT"), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(
            FeatureRef(name="ema_slope", lookback=20, shift=1),
            FeatureRef(name="rsi", lookback=14, shift=1),
        ),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-run-learner",
        research_seed=31,
        created_at=CREATED_AT,
    )


def _model_file(tmp_path: Path, content: bytes = b"cached learner model") -> tuple[Path, str]:
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    model_path = model_root / "learner-001.bin"
    model_path.write_bytes(content)
    return model_root, hashlib.sha256(content).hexdigest()


def _artifact(
    tmp_path: Path,
    *,
    created_at: datetime = CREATED_AT,
    model_ref: str = "learner-001.bin",
    model_hash: str | None = None,
):
    _, computed_hash = _model_file(tmp_path)
    return build_learner_artifact(
        candidate=_candidate(),
        learner_id="learner-001",
        learner_run_id="learner-run-001",
        learner_version="learner-v1",
        model_family="cached_classifier",
        feature_ids=("ema_slope", "rsi"),
        training_window_start=WINDOW_START,
        training_window_end=WINDOW_END,
        model_artifact_ref=model_ref,
        model_artifact_hash=model_hash or computed_hash,
        created_at=created_at,
    )


def test_learner_artifact_is_deterministic_and_never_authoritative(tmp_path: Path) -> None:
    first = _artifact(tmp_path / "first")
    second = _artifact(tmp_path / "second", created_at=CREATED_AT + timedelta(hours=1))

    assert first.artifact_hash == second.artifact_hash
    assert first.state == "testing"
    assert first.source == "learner_research"
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first.promotion_state == "unpromoted"
    assert first.paper_activation is False
    assert first.execution_authority is False
    assert first.symbols == ("BTCUSDT", "ETHUSDT")
    assert first.training_window_end > first.training_window_start


def test_learner_artifact_binds_candidate_identity_and_dataset(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)

    verify_learner_artifact_binding(artifact, _candidate())
    with pytest.raises(DomainViolation, match="candidate binding"):
        verify_learner_artifact_binding(artifact, _candidate("cand-other"))


def test_learner_artifact_rejects_invalid_window_and_path(tmp_path: Path) -> None:
    model_root, model_hash = _model_file(tmp_path)
    with pytest.raises(DataQualityError, match="training_window_end"):
        build_learner_artifact(
            candidate=_candidate(),
            learner_id="learner-001",
            learner_run_id="learner-run-001",
            learner_version="learner-v1",
            model_family="cached_classifier",
            feature_ids=("ema_slope", "rsi"),
            training_window_start=WINDOW_END,
            training_window_end=WINDOW_START,
            model_artifact_ref="learner-001.bin",
            model_artifact_hash=model_hash,
            created_at=CREATED_AT,
        )

    with pytest.raises(DataQualityError, match="model_artifact_ref"):
        build_learner_artifact(
            candidate=_candidate(),
            learner_id="learner-001",
            learner_run_id="learner-run-001",
            learner_version="learner-v1",
            model_family="cached_classifier",
            feature_ids=("ema_slope", "rsi"),
            training_window_start=WINDOW_START,
            training_window_end=WINDOW_END,
            model_artifact_ref="../learner-001.bin",
            model_artifact_hash=model_hash,
            created_at=CREATED_AT,
        )
    assert model_root.exists()


def test_learner_artifact_persistence_verifies_model_hash_and_is_write_once(tmp_path: Path) -> None:
    model_root, model_hash = _model_file(tmp_path)
    artifact = _artifact(tmp_path / "artifact", model_hash=model_hash)
    path = tmp_path / "learners" / "learner-001.json"

    write_learner_artifact(path, artifact, model_root=model_root)
    serialized = path.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert payload["model_artifact_hash"] == model_hash
    assert read_learner_artifact(path, model_root=model_root) == artifact
    assert write_learner_artifact(path, artifact, model_root=model_root) == artifact

    path.write_text(serialized.replace("learner-v1", "learner-v2"), encoding="utf-8")
    with pytest.raises(DomainViolation, match="artifact hash mismatch"):
        read_learner_artifact(path, model_root=model_root)
    path.write_text(serialized, encoding="utf-8")

    (model_root / "learner-001.bin").write_bytes(b"tampered learner model")
    with pytest.raises(DomainViolation, match="model artifact hash mismatch"):
        read_learner_artifact(path, model_root=model_root)


def test_learner_artifact_rejects_missing_model_and_conflicting_rewrite(tmp_path: Path) -> None:
    model_root, model_hash = _model_file(tmp_path)
    artifact = _artifact(tmp_path / "artifact", model_hash=model_hash)
    path = tmp_path / "learners" / "learner-001.json"
    write_learner_artifact(path, artifact, model_root=model_root)

    (model_root / "learner-001.bin").unlink()
    with pytest.raises(DomainViolation, match="model artifact missing"):
        read_learner_artifact(path, model_root=model_root)

    replacement_root, replacement_hash = _model_file(tmp_path / "replacement", b"replacement")
    replacement = _artifact(tmp_path / "replacement-artifact", model_hash=replacement_hash)
    with pytest.raises(DomainViolation, match="immutable"):
        write_learner_artifact(path, replacement, model_root=replacement_root)
