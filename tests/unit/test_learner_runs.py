from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
from autonomous_futures.research.learner_artifacts import build_learner_artifact
from autonomous_futures.research.learner_inputs import LearnerInputMaterializer, LearnerInputWindow
from autonomous_futures.research.learner_runs import LearnerRun, prepare_learner_run

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    candidate_id = "cand-learner-run-001"
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT", "ETHUSDT"), timeframe="5m", regime_context_timeframe="15m"
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
        creator_run_id="creator-run-learner-run",
        research_seed=43,
        created_at=START,
    )


def _learner(tmp_path: Path):
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    model_bytes = b"learner-run-model"
    (model_root / "learner-run.bin").write_bytes(model_bytes)
    return build_learner_artifact(
        candidate=_candidate(),
        learner_id="learner-run-001",
        learner_run_id="learner-run-source-001",
        learner_version="learner-v1",
        model_family="cached_classifier",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="learner-run.bin",
        model_artifact_hash=hashlib.sha256(model_bytes).hexdigest(),
        created_at=START,
    )


def _primary(start: datetime = START) -> pd.DataFrame:
    timestamps = [start + timedelta(minutes=5 * index) for index in range(7)]
    closes = [Decimal(str(100 + index)) for index in range(7)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + Decimal("1") for value in closes],
            "low": [value - Decimal("1") for value in closes],
            "close": closes,
        }
    )


def _context(start: datetime = START) -> pd.DataFrame:
    timestamps = [start + timedelta(minutes=15 * index) for index in range(3)]
    closes = [Decimal("110"), Decimal("120"), Decimal("130")]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + Decimal("1") for value in closes],
            "low": [value - Decimal("1") for value in closes],
            "close": closes,
            "close_time": [
                timestamp + timedelta(minutes=15) - timedelta(milliseconds=1)
                for timestamp in timestamps
            ],
        }
    )


def _windows(tmp_path: Path) -> tuple[object, LearnerInputWindow, LearnerInputWindow]:
    learner = _learner(tmp_path)
    materializer = LearnerInputMaterializer(learner=learner, candidate=_candidate())
    btc = materializer.materialize(
        primary=_primary(), context=_context(), symbol="BTCUSDT", input_id="input-btc"
    )
    eth = materializer.materialize(
        primary=_primary(), context=_context(), symbol="ETHUSDT", input_id="input-eth"
    )
    return learner, btc, eth


def test_prepared_run_is_deterministic_and_not_a_training_result(tmp_path: Path) -> None:
    learner, btc, eth = _windows(tmp_path)
    first = prepare_learner_run(
        learner=learner,
        windows=(eth, btc),
        run_id="run-learner-prepared-001",
        prepared_at=datetime(2026, 8, 8, 13, tzinfo=UTC),
    )
    second = prepare_learner_run(
        learner=learner,
        windows=(btc, eth),
        run_id="run-learner-prepared-001",
        prepared_at=datetime(2026, 8, 8, 14, tzinfo=UTC),
    )

    assert first.run_hash == second.run_hash
    assert first.model_dump(exclude={"prepared_at"}) == second.model_dump(exclude={"prepared_at"})
    assert isinstance(first, LearnerRun)
    assert first.status == "prepared"
    assert first.input_window_ids == ("input-btc", "input-eth")
    assert first.input_symbols == ("BTCUSDT", "ETHUSDT")
    assert first.feature_ids == ("returns",)
    assert first.output_artifact_hash is None
    assert first.training_metrics is None
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first.promotion_state == "unpromoted"
    assert first.paper_activation is False
    assert first.execution_authority is False


def test_prepared_run_requires_complete_symbol_coverage(tmp_path: Path) -> None:
    learner, btc, _ = _windows(tmp_path)

    with pytest.raises(DataQualityError, match="symbol coverage"):
        prepare_learner_run(
            learner=learner,
            windows=(btc,),
            run_id="run-learner-prepared-001",
            prepared_at=START,
        )


def test_prepared_run_rejects_binding_duplicate_and_range_mismatch(tmp_path: Path) -> None:
    learner, btc, eth = _windows(tmp_path)
    bad_spec = btc.spec.model_copy(update={"bundle_hash": "c" * 64})
    bad_window = LearnerInputWindow(spec=bad_spec, frame=btc.frame)

    with pytest.raises(DataQualityError, match="bundle_hash"):
        prepare_learner_run(
            learner=learner,
            windows=(bad_window, eth),
            run_id="run-learner-prepared-001",
            prepared_at=START,
        )

    with pytest.raises(DataQualityError, match="unique"):
        prepare_learner_run(
            learner=learner,
            windows=(btc, btc, eth),
            run_id="run-learner-prepared-001",
            prepared_at=START,
        )

    shifted_frame = _primary(START + timedelta(minutes=5))
    shifted = LearnerInputMaterializer(learner=learner, candidate=_candidate()).materialize(
        primary=shifted_frame,
        context=_context(START + timedelta(minutes=5)),
        symbol="ETHUSDT",
        input_id="input-shifted",
    )
    with pytest.raises(DataQualityError, match="same training window"):
        prepare_learner_run(
            learner=learner,
            windows=(btc, shifted),
            run_id="run-learner-prepared-001",
            prepared_at=START,
        )


def test_prepared_run_rejects_invalid_identity_and_timestamp(tmp_path: Path) -> None:
    learner, btc, eth = _windows(tmp_path)
    with pytest.raises(DataQualityError, match="run_id"):
        prepare_learner_run(
            learner=learner,
            windows=(btc, eth),
            run_id="run/unsafe",
            prepared_at=START,
        )

    with pytest.raises(DataQualityError, match="UTC"):
        prepare_learner_run(
            learner=learner,
            windows=(btc, eth),
            run_id="run-learner-prepared-001",
            prepared_at=datetime(2026, 8, 8, 13),
        )
