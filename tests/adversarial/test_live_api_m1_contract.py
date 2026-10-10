"""Pytest Adversarial Test Suite for Live Production API Contracts.

Milestone 1: Empirical Adversarial Probing of https://futures.semua.dev/
Target Endpoints:
- /api/v1/market/prices
- /api/v1/execution/status
- /api/v1/canary/summary
- /api/v1/market/klines
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import httpx
import pytest

LIVE_BASE_URL = "https://futures.semua.dev"


@pytest.fixture(scope="module")
def api_client() -> httpx.Client:
    return httpx.Client(base_url=LIVE_BASE_URL, timeout=12.0)


def test_live_market_prices_burst_and_schema(api_client: httpx.Client) -> None:
    """Probes /api/v1/market/prices across burst requests and asserts schema validity."""
    responses = [api_client.get("/api/v1/market/prices") for _ in range(10)]
    for r in responses:
        assert r.status_code == 200
        data = r.json()
        assert "prices" in data
        assert "BTCUSDT" in data["prices"]
        assert "ETHUSDT" in data["prices"]
        assert "SOLUSDT" in data["prices"]
        assert data["prices"]["BTCUSDT"] > 0
        assert data["prices"]["ETHUSDT"] > 0
        assert data["prices"]["SOLUSDT"] > 0
        assert data["source"] in {"binance_futures_live", "daemon_live_prices", "phase310_report"}


def test_live_btc_macro_strictly_nonlinear_emas(api_client: httpx.Client) -> None:
    """Adversarially tests that btc_macro EMAs are authentic non-linear smoothed values."""
    resp = api_client.get("/api/v1/market/prices")
    assert resp.status_code == 200
    data = resp.json()
    macro = data["btc_macro"]

    cur_p = float(macro["current_price"])
    ema50 = float(macro["ema50_1h"])
    ema200 = float(macro["ema200_1h"])

    ratio_50 = ema50 / cur_p
    ratio_200 = ema200 / cur_p

    # Mathematically verify that static linear multipliers 1.004 and 0.988 never leak
    assert abs(ratio_50 - 1.004) > 1e-4, f"Fake linear multiplier 1.004 leaked: {ratio_50}"
    assert abs(ratio_200 - 0.988) > 1e-4, f"Fake linear multiplier 0.988 leaked: {ratio_200}"

    assert macro["regime"] in {"BULLISH ALIGNED", "BEARISH", "SIDEWAYS"}
    assert macro["source"] in {
        "binance_futures_live",
        "local_parquet_cache",
        "local_csv_history",
        "synthetic_history",
    }


def test_live_execution_status_zero_drift_solvency(api_client: httpx.Client) -> None:
    """Validates double-entry mathematical zero-drift balance invariant on live backend."""
    resp = api_client.get("/api/v1/execution/status")
    assert resp.status_code == 200
    data = resp.json()

    solv = data["solvency"]
    start_eq = Decimal(str(solv["starting_equity_usdt"]))
    cash = Decimal(str(solv["cash_usdt"]))
    alloc_margin = Decimal(str(solv["allocated_margin_usdt"]))
    upnl = Decimal(str(solv["unrealized_pnl_usdt"]))
    rpnl = Decimal(str(solv["realized_pnl_usdt"]))

    # Equation: Cash + Margin + uPnL == StartEq + rPnL
    lhs = cash + alloc_margin + upnl
    rhs = start_eq + rpnl
    delta = abs(lhs - rhs)

    assert delta < Decimal("1e-15"), f"Drift violation on live API: |Delta|={delta} >= 1e-15"
    assert solv["drift_usdt"] == 0.0 or Decimal(str(solv["drift_usdt"])) < Decimal("1e-15")
    assert solv["zero_balance_drift_verified"] is True
    assert solv["cash_reserve_pct"] == 100.0
    assert solv["unencumbered_cash_verified"] is True


def test_live_execution_status_positions_flat_zero_phantoms(api_client: httpx.Client) -> None:
    """Verifies flat positions (0.00 exposure) and complete absence of phantom positions or TP/SL."""
    resp = api_client.get("/api/v1/execution/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["aggregate_exposure_usdt"] == 0.0
    positions = data["positions"]

    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert sym in positions
        p = positions[sym]
        assert p["position_qty"] == 0.0, f"Phantom quantity on {sym}"
        assert p["allocated_exposure_usdt"] == 0.0
        assert p["allocated_margin_usdt"] == 0.0
        assert p["unrealized_pnl_usdt"] == 0.0
        assert p["state"] == "STANDBY / SCANNING"
        assert p["status"] == "STANDBY / SCANNING"
        # Brackets MUST be suppressed when position is flat
        assert p["take_profit_price"] is None, f"Unsuppressed TP on flat position {sym}"
        assert p["stop_loss_price"] is None, f"Unsuppressed SL on flat position {sym}"


def test_live_recent_orders_authentic_canary_ids(api_client: httpx.Client) -> None:
    """Verifies that all orders are authentic canary executions and zero ord-p309- records exist."""
    resp = api_client.get("/api/v1/execution/status")
    assert resp.status_code == 200
    data = resp.json()

    orders = data["recent_orders"]
    assert len(orders) > 0, "Expected non-empty authentic orders"

    for o in orders:
        cid = o["client_order_id"]
        oid = o["order_id"]
        assert not cid.startswith("ord-p309-"), f"Stale p309 client order ID found: {cid}"
        assert not oid.startswith("ord-p309-"), f"Stale p309 order ID found: {oid}"
        assert cid.startswith("canary-p310-") or cid.startswith("canary-p311-"), (
            f"Unrecognized order prefix: {cid}"
        )
        assert o["symbol"] in {"SOLUSDT", "ETHUSDT", "BTCUSDT"}

    # Strict descending chronology
    ts_list = [o["timestamp_ms"] for o in orders]
    assert ts_list == sorted(ts_list, reverse=True)


def test_live_canary_summary_contract(api_client: httpx.Client) -> None:
    """Probes /api/v1/canary/summary and validates response structure."""
    resp = api_client.get("/api/v1/canary/summary")
    assert resp.status_code == 200
    data = resp.json()

    assert data["verified"] is True
    assert "candidates" in data
    assert set(data["candidates"]) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert data["circuit_state"] == "NORMAL"


def test_live_api_fuzzing_and_error_handling(api_client: httpx.Client) -> None:
    """Tests unexpected parameters and malformed queries on live endpoints."""
    # Harmless extra parameters should not crash endpoints
    r1 = api_client.get("/api/v1/market/prices?unexpected_param=12345&foo=bar")
    assert r1.status_code == 200

    r2 = api_client.get("/api/v1/execution/status?research_dir=/etc/shadow")
    assert r2.status_code == 200

    # Malformed queries on klines must return 422 Unprocessable Entity
    r3 = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=invalid_interval")
    assert r3.status_code == 422

    r4 = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=-1")
    assert r4.status_code == 422
