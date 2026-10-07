from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pandas as pd
import pytest
from pydantic import ValidationError

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.data.verified_funding import VerifiedFundingSlice
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.cached_evaluation import (
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
    CachedOnlyEvaluatorAdapter,
    CachedWindowEvaluation,
    _evaluation_content_hash,
)
from autonomous_futures.research.creator_artifacts import build_creator_candidate_artifact
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
)

START = datetime(2026, 8, 7, 12, tzinfo=UTC)
BUNDLE_HASH = "a" * 64
DATASET_REGISTRY_HASH = "b" * 64


def _candidate():
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id="cand-cached-eval-001",
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id="cand-cached-eval-001",
        strategy=strategy,
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        creator_run_id="creator-run-cached-eval",
        research_seed=31,
        created_at=START,
    )


def _frame(start: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * index) for index in range(3)],
            "open": [Decimal("100"), Decimal("101"), Decimal("102")],
            "high": [Decimal("101"), Decimal("102"), Decimal("103")],
            "low": [Decimal("99"), Decimal("100"), Decimal("101")],
            "close": [Decimal("100.5"), Decimal("101.5"), Decimal("102.5")],
        }
    )


def _window(window_id: str, start: datetime, *, bundle_hash: str = BUNDLE_HASH):
    spec = CachedEvaluationWindowSpec(
        window_id=window_id,
        symbol="BTCUSDT",
        bundle_hash=bundle_hash,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=start,
        time_end=start + timedelta(minutes=15),
    )
    return CachedEvaluationWindow(spec=spec, frame=_frame(start))


def test_cached_window_binds_and_copies_its_verified_funding_slice() -> None:
    funding_hash = "c" * 64
    spec = CachedEvaluationWindowSpec(
        window_id="window-funding-01",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        funding_artifact_hash=funding_hash,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    funding = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"],
            "funding_time": [START + timedelta(minutes=5, milliseconds=1)],
            "funding_rate": [Decimal("0.001")],
            "funding_mark_price": [Decimal("100")],
        }
    )

    window = CachedEvaluationWindow(
        spec=spec,
        frame=_frame(START),
        funding_slice=VerifiedFundingSlice(
            symbol="BTCUSDT",
            time_start=START,
            time_end=START + timedelta(minutes=15),
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_REGISTRY_HASH,
            manifest_hash=funding_hash,
            artifact_sha256="d" * 64,
            _events=funding,
        ),
    )
    isolated = window.copy_funding_events()
    isolated.loc[0, "funding_rate"] = Decimal("9")
    exposed = window.funding_events
    assert exposed is not None
    exposed.loc[0, "funding_rate"] = Decimal("8")
    exposed_frame = window.frame
    exposed_frame.loc[0, "close"] = Decimal("999")

    assert window.spec.funding_artifact_hash == funding_hash
    assert window.funding_events is not None
    assert window.funding_events.loc[0, "funding_rate"] == Decimal("0.001")
    assert window.copy_frame().loc[0, "close"] == Decimal("100.5")


def test_cached_window_rejects_verified_funding_from_another_catalog() -> None:
    funding_hash = "c" * 64
    spec = CachedEvaluationWindowSpec(
        window_id="window-funding-catalog-mismatch",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        funding_artifact_hash=funding_hash,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    empty_funding = pd.DataFrame(
        columns=("symbol", "funding_time", "funding_rate", "funding_mark_price")
    )
    foreign_slice = VerifiedFundingSlice(
        symbol=spec.symbol,
        time_start=spec.time_start,
        time_end=spec.time_end,
        bundle_hash="f" * 64,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        manifest_hash=funding_hash,
        artifact_sha256="d" * 64,
        _events=empty_funding,
    )

    with pytest.raises(DataQualityError, match="verified funding slice"):
        CachedEvaluationWindow(spec=spec, frame=_frame(START), funding_slice=foreign_slice)


def test_cached_evaluation_run_hash_binds_verified_funding_manifest() -> None:
    funding_hash = "c" * 64
    spec = CachedEvaluationWindowSpec(
        window_id="window-bound-01",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        funding_artifact_hash=funding_hash,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    empty_funding = pd.DataFrame(
        columns=("symbol", "funding_time", "funding_rate", "funding_mark_price")
    )
    window = CachedEvaluationWindow(
        spec=spec,
        frame=_frame(START),
        funding_slice=VerifiedFundingSlice(
            symbol=spec.symbol,
            time_start=spec.time_start,
            time_end=spec.time_end,
            bundle_hash=spec.bundle_hash,
            dataset_registry_hash=spec.dataset_registry_hash,
            manifest_hash=funding_hash,
            artifact_sha256="d" * 64,
            _events=empty_funding,
        ),
    )
    adapter = CachedOnlyEvaluatorAdapter(
        candidate=_candidate(),
        evaluator_run_id="evaluator-run-funding-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=lambda _candidate, _frame, current: _result(current),
    )

    run = adapter.evaluate((window,), evaluated_at=START)

    assert run.evaluation_version == 2
    assert run.windows[0].funding_artifact_hash == funding_hash


def test_legacy_cached_evaluation_hash_omits_new_funding_binding_field() -> None:
    window = _window("legacy-window", START)
    run = CachedOnlyEvaluatorAdapter(
        candidate=_candidate(),
        evaluator_run_id="evaluator-run-legacy-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=lambda _candidate, _frame, current: _result(current),
    ).evaluate((window,), evaluated_at=START)
    payload = run.model_dump(mode="json", exclude={"evaluated_at", "evaluation_hash"})
    for window_payload in payload["windows"]:
        window_payload.pop("funding_artifact_hash", None)
    expected = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert run.evaluation_version == 1
    assert _evaluation_content_hash(run) == expected


def _result(window: CachedEvaluationWindow) -> CachedWindowEvaluation:
    return CachedWindowEvaluation(
        window_id=window.spec.window_id,
        symbol=window.spec.symbol,
        metrics=(QualificationMetric(metric_id="oos_sharpe", value=Decimal("1.25")),),
        gates=(
            QualificationGateResult(
                gate_id="oos_sharpe_min",
                passed=True,
                observed=Decimal("1.25"),
                threshold=Decimal("1.0"),
                comparator="gte",
                reason_code="passed",
            ),
        ),
    )


def test_cached_adapter_is_deterministic_and_isolates_input_frames() -> None:
    candidate = _candidate()
    first_window = _window("window-01", START)
    second_window = _window("window-02", START + timedelta(minutes=15))
    seen_frames: list[pd.DataFrame] = []

    def evaluator(received_candidate, frame, window):
        assert received_candidate == candidate
        seen_frames.append(frame)
        frame.loc[0, "close"] = Decimal("999")
        return _result(window)

    adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=evaluator,
    )
    first = adapter.evaluate(
        (second_window, first_window), evaluated_at=datetime(2026, 8, 7, 13, tzinfo=UTC)
    )
    second = adapter.evaluate(
        (first_window, second_window), evaluated_at=datetime(2026, 8, 7, 14, tzinfo=UTC)
    )

    assert first.evaluation_hash == second.evaluation_hash
    assert [window.window_id for window in first.windows] == ["window-01", "window-02"]
    assert first.data_source == "cached_only"
    assert first.exchange_access is False
    assert first_window.frame.loc[0, "close"] == Decimal("100.5")
    assert second_window.frame.loc[0, "close"] == Decimal("100.5")
    assert all(received is not first_window.frame for received in seen_frames)


def test_cached_adapter_rejects_binding_mismatch_before_callback() -> None:
    called = False

    def evaluator(received_candidate, frame, window):
        nonlocal called
        called = True
        return _result(window)

    adapter = CachedOnlyEvaluatorAdapter(
        candidate=_candidate(),
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=evaluator,
    )

    with pytest.raises(DataQualityError, match="bundle_hash"):
        adapter.evaluate((_window("window-01", START, bundle_hash="c" * 64),), evaluated_at=START)
    assert called is False


def test_cached_adapter_rejects_unknown_symbol_and_result_identity() -> None:
    candidate = _candidate()
    spec = CachedEvaluationWindowSpec(
        window_id="window-01",
        symbol="ETHUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    window = CachedEvaluationWindow(spec=spec, frame=_frame(START))
    adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=lambda received_candidate, frame, received_window: _result(window),
    )

    with pytest.raises(DataQualityError, match="not present in candidate universe"):
        adapter.evaluate((window,), evaluated_at=START)

    valid_window = _window("window-01", START)
    invalid_result_adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=lambda received_candidate, frame, received_window: CachedWindowEvaluation(
            window_id="different-window",
            symbol=received_window.spec.symbol,
            metrics=_result(valid_window).metrics,
            gates=_result(valid_window).gates,
        ),
    )
    with pytest.raises(DataQualityError, match="window identity"):
        invalid_result_adapter.evaluate((valid_window,), evaluated_at=START)


def test_cached_window_requires_exact_closed_contiguous_coverage() -> None:
    spec = CachedEvaluationWindowSpec(
        window_id="window-01",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    gap_frame = _frame(START).drop(index=1)

    with pytest.raises(DataQualityError, match="gap"):
        CachedEvaluationWindow(spec=spec, frame=gap_frame)

    with pytest.raises(DataQualityError, match="cover exactly"):
        CachedEvaluationWindow(
            spec=spec,
            frame=_frame(START + timedelta(minutes=5)),
        )


def test_cached_window_rejects_timestamp_only_frames() -> None:
    spec = CachedEvaluationWindowSpec(
        window_id="window-01",
        symbol="BTCUSDT",
        bundle_hash=BUNDLE_HASH,
        dataset_registry_hash=DATASET_REGISTRY_HASH,
        time_start=START,
        time_end=START + timedelta(minutes=15),
    )
    timestamp_only = _frame(START).loc[:, ["timestamp"]]

    with pytest.raises(DataQualityError, match="OHLC"):
        CachedEvaluationWindow(spec=spec, frame=timestamp_only)


def test_cached_contract_rejects_empty_run_and_non_utc_window() -> None:
    candidate = _candidate()
    adapter = CachedOnlyEvaluatorAdapter(
        candidate=candidate,
        evaluator_run_id="evaluator-run-cached-001",
        evaluator_version="cached-evaluator-v1",
        evaluator=lambda received_candidate, frame, window: _result(window),
    )
    with pytest.raises(DataQualityError, match="at least one"):
        adapter.evaluate((), evaluated_at=START)

    with pytest.raises(ValidationError, match="UTC"):
        CachedEvaluationWindowSpec(
            window_id="window-01",
            symbol="BTCUSDT",
            bundle_hash=BUNDLE_HASH,
            dataset_registry_hash=DATASET_REGISTRY_HASH,
            time_start=datetime(2026, 8, 7, 12),
            time_end=datetime(2026, 8, 7, 12, 15),
        )
