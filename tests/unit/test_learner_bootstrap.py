from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.learner_artifacts import read_learner_artifact
from autonomous_futures.research.learner_bootstrap import bootstrap_learner_training
from autonomous_futures.research.learner_runs import read_learner_run
from autonomous_futures.research.learner_training import LearnerTrainingOutput

START = datetime(2026, 8, 1, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-bootstrap-001"
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("DOGEUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=2, shift=1),),
        entry=EntryExit(long="returns > 0", short="returns < 0"),
        exit=EntryExit(long="returns < 0", short="returns > 0"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-learner-bootstrap",
        research_seed=202,
        created_at=START,
    )


def _primary() -> pd.DataFrame:
    timestamps = [START + timedelta(minutes=5 * index) for index in range(8)]
    closes = [100 + index for index in range(8)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
        }
    )


def _context() -> pd.DataFrame:
    timestamps = [START + timedelta(minutes=15 * index) for index in range(3)]
    closes = [100, 103, 106]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "close_time": [
                timestamp + timedelta(minutes=15) - timedelta(milliseconds=1)
                for timestamp in timestamps
            ],
        }
    )


def test_bootstrap_materializes_causal_frames_and_persists_prepared_run(tmp_path: Path) -> None:
    candidate = _candidate()
    primary = _primary()
    context = _context()
    primary_before = primary.copy(deep=True)
    context_before = context.copy(deep=True)
    observed: dict[str, object] = {}
    model_bytes = b"bootstrap-model-v1"

    def trainer(received_candidate, frames):
        observed["candidate_id"] = received_candidate.candidate_id
        observed["symbols"] = tuple(frames)
        observed["columns"] = tuple(frames["DOGEUSDT"].columns)
        frames["DOGEUSDT"].loc[0, "close"] = 999999
        return LearnerTrainingOutput(
            model_artifact_ref="bootstrap/doge.bin",
            model_family="explicit_bootstrap_baseline",
            learner_version="learner-bootstrap-v1",
            model_bytes=model_bytes,
        )

    result = bootstrap_learner_training(
        candidate=candidate,
        primary_frames={"DOGEUSDT": primary},
        context_frames={"DOGEUSDT": context},
        learner_id="learner-bootstrap-001",
        run_id="run-learner-bootstrap-001",
        trainer=trainer,
        model_root=tmp_path / "models",
        learner_artifact_path=tmp_path / "learners" / "artifact.json",
        run_path=tmp_path / "runs" / "run.json",
        created_at=START + timedelta(hours=1),
        prepared_at=START + timedelta(hours=2),
    )

    assert observed["candidate_id"] == candidate.candidate_id
    assert observed["symbols"] == ("DOGEUSDT",)
    assert "returns" in observed["columns"]
    assert "signal" not in observed["columns"]
    pd.testing.assert_frame_equal(primary, primary_before)
    pd.testing.assert_frame_equal(context, context_before)
    assert result.learner.state == "testing"
    assert result.learner.data_source == "cached_only"
    assert result.learner.execution_authority is False
    assert result.learner.model_artifact_hash == hashlib.sha256(model_bytes).hexdigest()
    assert result.prepared_run.status == "prepared"
    assert result.prepared_run.output_artifact_hash is None
    assert result.prepared_run.training_metrics is None
    assert result.prepared_run.exchange_access is False
    assert len(result.input_windows) == 1
    assert (
        read_learner_artifact(
            tmp_path / "learners" / "artifact.json", model_root=tmp_path / "models"
        )
        == result.learner
    )
    assert read_learner_run(tmp_path / "runs" / "run.json") == result.prepared_run


def test_bootstrap_rejects_incomplete_symbol_frames(tmp_path: Path) -> None:
    candidate = _candidate()
    with pytest.raises(DataQualityError, match="primary frames must match candidate universe"):
        bootstrap_learner_training(
            candidate=candidate,
            primary_frames={},
            context_frames={"DOGEUSDT": _context()},
            learner_id="learner-bootstrap-001",
            run_id="run-learner-bootstrap-001",
            trainer=lambda _candidate, _frames: LearnerTrainingOutput(
                model_artifact_ref="bootstrap/doge.bin",
                model_family="explicit_bootstrap_baseline",
                learner_version="learner-bootstrap-v1",
                model_bytes=b"model",
            ),
            model_root=tmp_path / "models",
            learner_artifact_path=tmp_path / "learners" / "artifact.json",
            run_path=tmp_path / "runs" / "run.json",
            created_at=START,
            prepared_at=START,
        )
