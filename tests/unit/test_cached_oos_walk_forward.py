from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from autonomous_futures.research.cached_evaluation import (
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.cached_oos_walk_forward import evaluate_cached_oos_walk_forward
from autonomous_futures.research.trade_simulation import (
    EquityPoint,
    TradeSimulationResult,
)

_HASH = "a" * 64


def _window(window_id: str, symbol: str, start: datetime) -> CachedEvaluationWindow:
    timestamps = pd.date_range(start, periods=2, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
        }
    )
    return CachedEvaluationWindow(
        spec=CachedEvaluationWindowSpec(
            window_id=window_id,
            symbol=symbol,
            bundle_hash=_HASH,
            dataset_registry_hash=_HASH,
            time_start=start,
            time_end=start + timedelta(minutes=10),
        ),
        frame=frame,
    )


def _candidate() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="cand-test",
        artifact_hash=_HASH,
        bundle_hash=_HASH,
        dataset_registry_hash=_HASH,
        strategy=SimpleNamespace(universe=SimpleNamespace(symbols=("BTCUSDT", "ETHUSDT"))),
    )


def _flat_result(
    candidate: object, frame: pd.DataFrame, window: CachedEvaluationWindow
) -> TradeSimulationResult:
    timestamp = frame["timestamp"].iloc[-1].to_pydatetime()
    return TradeSimulationResult(
        symbol=window.spec.symbol,
        starting_equity=Decimal("100"),
        final_equity=Decimal("100"),
        total_fees=Decimal("0"),
        total_slippage_cost=Decimal("0"),
        equity_curve=(EquityPoint(timestamp=timestamp, equity=Decimal("100")),),
    )


def test_cached_windows_become_deterministic_oos_aggregation() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    aggregation = evaluate_cached_oos_walk_forward(
        _candidate(),
        (_window("btc-1", "BTCUSDT", start), _window("eth-1", "ETHUSDT", start)),
        simulator=_flat_result,
    )

    assert aggregation.required_symbols == ("BTCUSDT", "ETHUSDT")
    assert aggregation.window_count == 2
    assert aggregation.total_trade_count == 0
    assert aggregation.data_source == "cached_only"
    assert aggregation.exchange_access is False


def test_cached_windows_reject_candidate_hash_drift() -> None:
    candidate = _candidate()
    candidate.bundle_hash = "b" * 64

    try:
        evaluate_cached_oos_walk_forward(
            candidate,
            (_window("btc-1", "BTCUSDT", datetime(2026, 1, 1, tzinfo=UTC)),),
            simulator=_flat_result,
        )
    except ValueError as exc:
        assert "bundle_hash" in str(exc)
    else:
        raise AssertionError("candidate hash drift must fail closed")
