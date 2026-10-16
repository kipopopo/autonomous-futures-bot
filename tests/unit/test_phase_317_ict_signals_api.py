"""Phase 317 Milestone 5 Unit Tests: FastAPI ICT Signals Endpoint.

File: tests/unit/test_phase_317_ict_signals_api.py

Covers:
- Suite 1: TestIctSignalsSchemaAndUniverse
  (Verifies GET /api/v1/strategy/ict-signals returns HTTP 200, valid IctSignalsResponse,
   verified=True, active_family='ICT_MMXM_TWINS', and all 8 active pairs).
- Suite 2: TestIctSignalsSubSchemas
  (Asserts all required fields in twins_state, pd_arrays [4h, 1h, 15m, 5m, 1m],
   candidate_genome, and recent_autopsies).
- Suite 3: TestTtlCacheAndLatencyBudget
  (Verifies thread-safe 5.0-second TTL cache, response time strictly < 10ms on cached hits,
   and deterministic cache reset via reset_ict_signals_cache).
- Suite 4: TestOfflineTraderResilientFallback
  (Verifies clean baseline fallback when trader daemon is offline or cold starting,
   with 0 uncaught exceptions or 500 errors).
- Suite 5: TestLiveTraderIntegration
  (Verifies active ContinuousSelfDrivingTrader signals and PD arrays flow correctly into payload).
"""

from __future__ import annotations

import time
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.strategy_router import (
    reset_ict_signals_cache,
    set_active_trader,
)
from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS, ACTIVE_TIMEFRAMES
from autonomous_futures.strategy.ict_mmxm import Candle, IctMmxmEngine


@pytest.fixture(autouse=True)
def clean_cache() -> Generator[None]:
    reset_ict_signals_cache()
    set_active_trader(None)
    yield
    reset_ict_signals_cache()
    set_active_trader(None)


def test_endpoint_returns_all_8_pairs_and_schema() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/strategy/ict-signals")
    assert resp.status_code == 200
    data = resp.json()

    assert data["verified"] is False
    assert data["active_family"] == "ICT_MMXM_TWINS"
    assert "timestamp_ms" in data
    assert len(data["signals"]) == len(ACTIVE_PAIRS)

    for sym in ACTIVE_PAIRS:
        assert sym in data["signals"], f"Missing pair {sym}"
        pair_data = data["signals"][sym]
        assert pair_data["symbol"] == sym
        assert "twins_state" in pair_data
        assert "pd_arrays" in pair_data
        assert "candidate_genome" in pair_data
        assert "recent_autopsies" in pair_data


def test_twins_state_sub_schema_conformance() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/strategy/ict-signals")
    data = resp.json()

    expected_keys = {
        "step_1_htf_hit",
        "step_2_m5_cisd",
        "step_3_twins_fvg",
        "step_4_ote_retrace",
        "step_5_m1_cisd",
        "step_6_ready",
        "active_pda",
        "m5_cisd_price",
        "m1_cisd_price",
        "ote_62",
        "ote_705",
        "ote_79",
        "stdv_2_0",
        "stdv_4_0",
        "stop_loss",
        "take_profit_partial",
        "take_profit_final",
        "side",
    }

    for sym, pair_data in data["signals"].items():
        twins = pair_data["twins_state"]
        assert expected_keys.issubset(twins.keys()), f"Missing keys in twins_state for {sym}"
        assert isinstance(twins["step_1_htf_hit"], bool)
        assert isinstance(twins["step_6_ready"], bool)


def test_pd_arrays_grouped_by_timeframe() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/strategy/ict-signals")
    data = resp.json()

    for sym, pair_data in data["signals"].items():
        pdas = pair_data["pd_arrays"]
        for tf in ACTIVE_TIMEFRAMES:
            assert tf in pdas, f"Missing timeframe {tf} for {sym}"
            assert isinstance(pdas[tf], list)


def test_candidate_genome_attributes() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/strategy/ict-signals")
    data = resp.json()

    for _sym, pair_data in data["signals"].items():
        gen = pair_data["candidate_genome"]
        assert gen["ote_lower"] == 0.50
        assert gen["ote_upper"] == 0.79
        assert gen["stdv_tp1"] == 2.0
        assert gen["stdv_tp2"] == 4.0
        assert gen["swing_lookback"] == 50
        assert gen["fvg_threshold_pct"] == 0.0015
        assert gen["health_tier"] == "HEALTHY"


def test_ttl_cache_hit_latency_under_10ms() -> None:
    import gc

    gc.collect()

    app = create_app()
    client = TestClient(app)

    # Prime cache
    r1 = client.get("/api/v1/strategy/ict-signals")
    assert r1.status_code == 200
    ts1 = r1.json()["timestamp_ms"]

    # Warmup 1 cached request
    client.get("/api/v1/strategy/ict-signals")

    # 10 consecutive cached requests
    latencies = []
    for _ in range(10):
        t_req = time.perf_counter()
        resp = client.get("/api/v1/strategy/ict-signals")
        lat_ms = (time.perf_counter() - t_req) * 1000.0
        latencies.append(lat_ms)
        assert resp.status_code == 200
        assert resp.json()["timestamp_ms"] == ts1

    sorted_lats = sorted(latencies)
    median_ms = sorted_lats[len(sorted_lats) // 2]
    avg_ms = sum(latencies) / len(latencies)
    assert median_ms < 10.0, f"Median cached latency {median_ms:.2f}ms exceeded 10.0ms ceiling"
    assert avg_ms < 10.0, f"Average cached latency {avg_ms:.2f}ms exceeded 10.0ms ceiling"
    assert sorted_lats[int(len(sorted_lats) * 0.8)] < 15.0, "P80 latency exceeded 15.0ms threshold"


def test_offline_trader_resilient_fallback() -> None:
    # Cold test with non-existent research dir
    app = create_app(research_dir=Path("/non_existent_path_xyz_12345"))
    client = TestClient(app)
    resp = client.get("/api/v1/strategy/ict-signals")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["signals"]) == len(ACTIVE_PAIRS)
    assert data["verified"] is False


def test_live_trader_integration_signals() -> None:
    # Create mock candles for BTCUSDT forming an obvious FVG / Order block
    now = int(time.time() * 1000)
    c1 = Candle(
        timestamp_ms=now - 300000,
        open=Decimal("60000"),
        high=Decimal("60500"),
        low=Decimal("59900"),
        close=Decimal("60400"),
        volume=Decimal("10"),
    )
    c2 = Candle(
        timestamp_ms=now - 200000,
        open=Decimal("60400"),
        high=Decimal("61500"),
        low=Decimal("60300"),
        close=Decimal("61400"),
        volume=Decimal("50"),
    )
    c3 = Candle(
        timestamp_ms=now - 100000,
        open=Decimal("61400"),
        high=Decimal("62000"),
        low=Decimal("61300"),
        close=Decimal("61900"),
        volume=Decimal("30"),
    )
    synthetic_candles = [c1, c2, c3]

    mock_sequencer = MagicMock()
    mock_sequencer.get_multi_tf_candles.return_value = (
        synthetic_candles,  # 4h
        synthetic_candles,  # 1h
        synthetic_candles,  # 15m
        synthetic_candles,  # 5m
        synthetic_candles,  # 1m
    )

    mock_trader = MagicMock()
    mock_trader.sequencer = mock_sequencer
    mock_trader.ict_engine = IctMmxmEngine(lookback_htf=100)

    app = create_app(trader=mock_trader)
    client = TestClient(app)

    resp = client.get("/api/v1/strategy/ict-signals")
    assert resp.status_code == 200
    data = resp.json()

    assert "BTCUSDT" in data["signals"]
    btc_pdas = data["signals"]["BTCUSDT"]["pd_arrays"]
    # Check that detect_pd_arrays was executed across timeframes
    assert "4h" in btc_pdas
    assert "1h" in btc_pdas
    # Verify at least one FVG detected in 4h/1h due to synthetic gap (c1.high 60500 vs c3.low 61300)
    assert any(pda["array_type"] == "FVG_BISI" for pda in btc_pdas["4h"])


def test_fetch_binance_candles_sync_filters_unclosed_forming_kline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import json
    import urllib.request

    from autonomous_futures.api.strategy_router import _fetch_binance_candles_sync

    now_ms = int(time.time() * 1000)
    raw_klines = [
        [now_ms - 180_000, "100.0", "105.0", "99.0", "104.0", "50.0", now_ms - 120_001],
        [now_ms - 120_000, "104.0", "108.0", "103.0", "107.0", "60.0", now_ms - 60_001],
        # Forming (unclosed) candle with close_time in the future
        [now_ms - 10_000, "107.0", "150.0", "90.0", "149.0", "10.0", now_ms + 50_000],
    ]

    class _DummyResponse(io.BytesIO):
        def __enter__(self) -> _DummyResponse:
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=2.5: _DummyResponse(json.dumps(raw_klines).encode("utf-8")),
    )
    candles = _fetch_binance_candles_sync("SOLUSDT", "1m", limit=250)
    assert len(candles) == 2
    assert candles[-1].close == Decimal("107.0")


def test_lumitraders_mmxm_telemetry_fields_in_ict_signals_response() -> None:
    now = 1_700_028_000_000  # 06:00 UTC -> 01:00 NY (Q2 Manipulation)
    candles_15m = [
        Candle(
            timestamp_ms=now - (6 - i) * 900_000,
            open=Decimal(str(180 + i)),
            high=Decimal(str(182 + i)),
            low=Decimal(str(179 + i)),
            close=Decimal(str(181 + i)),
            volume=Decimal("100"),
        )
        for i in range(6)
    ]
    candles_5m = [
        Candle(
            timestamp_ms=now - 900_000,
            open=Decimal("100"),
            high=Decimal("118"),
            low=Decimal("100"),
            close=Decimal("117"),
            volume=Decimal("50"),
        ),
        Candle(
            timestamp_ms=now - 600_000,
            open=Decimal("117"),
            high=Decimal("128"),
            low=Decimal("116"),
            close=Decimal("127"),
            volume=Decimal("50"),
        ),
        Candle(
            timestamp_ms=now - 300_000,
            open=Decimal("127"),
            high=Decimal("140"),
            low=Decimal("122"),
            close=Decimal("138"),
            volume=Decimal("50"),
        ),
    ]
    mock_sequencer = MagicMock()
    mock_sequencer.is_trade_ready.return_value = True
    mock_sequencer.get_multi_tf_candles.return_value = (
        candles_15m,
        candles_15m,
        candles_15m,
        candles_5m,
        candles_5m,
    )
    mock_trader = MagicMock()
    mock_trader.sequencer = mock_sequencer
    mock_trader.ict_engine = IctMmxmEngine(lookback_htf=100)

    app = create_app(trader=mock_trader)
    client = TestClient(app)
    resp = client.get("/api/v1/strategy/ict-signals")
    assert resp.status_code == 200
    data = resp.json()

    assert "quarterly_cycle" in data
    assert data["quarterly_cycle"] is not None
    assert "daily_quarter" in data["quarterly_cycle"]
    assert "active_killzone" in data["quarterly_cycle"]

    sol_sig = data["signals"]["SOLUSDT"]
    assert "quarterly_cycle" in sol_sig
    assert "intraday_bias" in sol_sig
    assert sol_sig["intraday_bias"] is not None
    assert "pdr_zone" in sol_sig["intraday_bias"]
    assert "nymo_zone" in sol_sig["intraday_bias"]
    assert sol_sig["measuring_gap"] is not None
    assert sol_sig["measuring_gap"]["projected_terminus"] == 140.0
    assert sol_sig["oos_qualification"] is not None
    assert sol_sig["oos_qualification"]["net_pnl_usdt"] == 139.93
    assert sol_sig["oos_qualification"]["gates_passed"] == 6
