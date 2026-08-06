from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import strategy_screen as screen


def frame_from_open(values: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(values), freq="5min", tz="UTC")
    open_ = pd.Series(values, index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": open_,
            "high": open_ * 1.01,
            "low": open_ * 0.99,
            "close": open_,
            "volume": 1.0,
            "funding_rate": 0.0,
        },
        index=index,
    )


def test_simulation_uses_next_open_and_charges_two_sides_on_reversal() -> None:
    frame = frame_from_open([100, 101, 102, 103])
    signal = pd.Series([1.0, 1.0, -1.0, -1.0], index=frame.index)
    result = screen.simulate(frame, signal)
    assert result["position"].tolist() == [0.0, 1.0, 1.0, -1.0]
    assert result["execution_cost"].tolist() == pytest.approx(
        [0.0, screen.PER_SIDE_COST, 0.0, 2 * screen.PER_SIDE_COST]
    )
    assert result.loc[frame.index[1], "gross"] == pytest.approx(102 / 101 - 1)
    assert result.loc[frame.index[2], "gross"] == pytest.approx(103 / 102 - 1)
    assert int(result["entries"].sum()) == 2


def test_bollinger_uses_prior_rolling_bands() -> None:
    frame = frame_from_open([100 + np.sin(i / 4) for i in range(200)])
    params = {"period": 20, "z": 2.0}
    baseline = screen.bollinger_signal(frame, params)
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] = 1_000_000
    altered = screen.bollinger_signal(changed, params)
    pd.testing.assert_series_equal(baseline.iloc[:-1], altered.iloc[:-1])


def test_cached_snapshot_is_gap_free() -> None:
    snapshot = json.loads((screen.DATA / "snapshot-5m-15m.json").read_text(encoding="utf-8"))
    assert set(snapshot["intervals"]) == {"5m", "15m"}
    assert set(snapshot["intervals"]["5m"]["symbols"]) == set(screen.SYMBOLS)
    for symbol in screen.SYMBOLS:
        frame = screen.load_symbol(symbol)
        assert len(frame) == snapshot["intervals"]["5m"]["symbols"][symbol]["klines"]
        gaps = frame.index.to_series().diff().dropna()
        assert (gaps == pd.Timedelta(minutes=5)).all()
        assert np.isfinite(frame[["open", "high", "low", "close", "funding_rate"]].to_numpy()).all()


def test_screen_results_are_finite_and_cover_all_periods() -> None:
    payload = json.loads(
        (Path(__file__).parent / "strategy_screen_results.json").read_text(encoding="utf-8")
    )
    assert {row["family"] for row in payload["selected"]} == {
        "ema_trend",
        "donchian_breakout",
        "bollinger_reversion",
        "rsi_reversion",
        "regime_hybrid",
    }
    for row in payload["selected"]:
        for period in ("train", "validation", "test_2026_ytd"):
            values = row[period]
            assert values["bars"] > 0
            assert values["trades"] >= 0
            for key in (
                "total_return",
                "annual_return",
                "sharpe",
                "max_drawdown",
                "cost_drag",
                "funding_pnl",
            ):
                assert np.isfinite(values[key])
            assert -1 <= values["max_drawdown"] <= 0


def test_secondary_context_is_unavailable_until_15m_bar_has_closed() -> None:
    primary_index = pd.date_range("2026-01-01T00:00:00Z", periods=7, freq="5min")
    # A 15m candle that starts at 00:00 only becomes available at 00:15.
    closed_context = pd.Series(
        [1.0, -1.0],
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2026-01-01T00:15:00Z"),
                pd.Timestamp("2026-01-01T00:30:00Z"),
            ]
        ),
    )
    aligned = screen.align_closed_context(primary_index, closed_context)
    assert aligned.iloc[:3].isna().all()
    assert aligned.loc[pd.Timestamp("2026-01-01T00:15:00Z")] == 1.0
    assert aligned.loc[pd.Timestamp("2026-01-01T00:25:00Z")] == 1.0
    assert aligned.loc[pd.Timestamp("2026-01-01T00:30:00Z")] == -1.0
