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
from autonomous_futures.research.learner_inputs import (
    LearnerInputMaterializer,
    LearnerInputWindow,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate(candidate_id: str = "cand-learner-input-001"):
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
        creator_run_id="creator-run-learner-input",
        research_seed=41,
        created_at=START,
    )


def _learner(tmp_path: Path):
    model_root = tmp_path / "models"
    model_root.mkdir(parents=True)
    model_bytes = b"learner-input-model"
    (model_root / "learner-input.bin").write_bytes(model_bytes)
    return build_learner_artifact(
        candidate=_candidate(),
        learner_id="learner-input-001",
        learner_run_id="learner-run-input-001",
        learner_version="learner-v1",
        model_family="cached_classifier",
        feature_ids=("returns",),
        training_window_start=START - timedelta(days=7),
        training_window_end=START,
        model_artifact_ref="learner-input.bin",
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


def test_materializer_is_causal_and_context_is_available_only_after_close(tmp_path: Path) -> None:
    learner = _learner(tmp_path)
    candidate = _candidate()
    materializer = LearnerInputMaterializer(learner=learner, candidate=candidate)

    result = materializer.materialize(
        primary=_primary(),
        context=_context(),
        symbol="BTCUSDT",
        input_id="input-window-001",
    )

    assert isinstance(result, LearnerInputWindow)
    assert result.spec.data_source == "cached_only"
    assert result.spec.exchange_access is False
    assert result.spec.context_feature_policy == "close_time_plus_1ms"
    assert result.spec.feature_ids == ("returns",)
    assert result.spec.row_count == 7
    assert "signal" not in result.frame.columns
    assert pd.isna(result.frame.loc[0, "context_close"])
    assert pd.isna(result.frame.loc[1, "context_close"])
    assert pd.isna(result.frame.loc[2, "context_close"])
    assert result.frame.loc[3, "context_close"] == Decimal("110")
    assert result.frame.loc[6, "context_close"] == Decimal("120")


def test_materializer_does_not_use_current_candle_for_feature_value(tmp_path: Path) -> None:
    learner = _learner(tmp_path)
    materializer = LearnerInputMaterializer(learner=learner, candidate=_candidate())
    baseline = materializer.materialize(
        primary=_primary(), context=_context(), symbol="BTCUSDT", input_id="input-window-001"
    )

    mutated_primary = _primary()
    mutated_primary.loc[4, "close"] = Decimal("999999")
    mutated = materializer.materialize(
        primary=mutated_primary, context=_context(), symbol="BTCUSDT", input_id="input-window-001"
    )

    assert baseline.frame.loc[4, "returns"] == mutated.frame.loc[4, "returns"]
    assert baseline.frame.loc[5, "returns"] != mutated.frame.loc[5, "returns"]


def test_materializer_isolates_sources_and_rejects_binding_or_symbol_mismatch(
    tmp_path: Path,
) -> None:
    learner = _learner(tmp_path)
    primary = _primary()
    context = _context()
    materializer = LearnerInputMaterializer(learner=learner, candidate=_candidate())
    result = materializer.materialize(
        primary=primary, context=context, symbol="BTCUSDT", input_id="input-window-001"
    )
    result.frame.loc[0, "close"] = Decimal("999")
    assert primary.loc[0, "close"] == Decimal("100")
    assert context.loc[0, "close"] == Decimal("110")

    with pytest.raises(DataQualityError, match="candidate binding"):
        LearnerInputMaterializer(learner=learner, candidate=_candidate("cand-other")).materialize(
            primary=_primary(), context=_context(), symbol="BTCUSDT", input_id="input-window-001"
        )

    with pytest.raises(DataQualityError, match="not present in learner universe"):
        materializer.materialize(
            primary=_primary(), context=_context(), symbol="SOLUSDT", input_id="input-window-001"
        )


def test_materializer_rejects_feature_binding_and_missing_context(tmp_path: Path) -> None:
    learner = _learner(tmp_path)
    candidate = _candidate()
    mismatched_learner = learner.model_copy(update={"feature_ids": ("ema_slope",)})
    materializer = LearnerInputMaterializer(learner=mismatched_learner, candidate=candidate)

    with pytest.raises(DataQualityError, match="feature IDs"):
        materializer.materialize(
            primary=_primary(), context=_context(), symbol="BTCUSDT", input_id="input-window-001"
        )

    with pytest.raises(DataQualityError, match="context"):
        LearnerInputMaterializer(learner=learner, candidate=candidate).materialize(
            primary=_primary(),
            context=_context().iloc[:1],
            symbol="BTCUSDT",
            input_id="input-window-001",
        )
