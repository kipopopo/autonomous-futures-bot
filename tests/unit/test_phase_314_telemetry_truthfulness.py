from __future__ import annotations

import asyncio
import json
import sqlite3
import urllib.request
from pathlib import Path
from urllib.error import URLError

import httpx
import pytest
from fastapi import FastAPI

from autonomous_futures.api import create_app
from autonomous_futures.api.app import (
    compute_authentic_btc_macro,
    reset_live_market_cache,
)


def _request(app: FastAPI, method: str, path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(send())


class MockHttpResponse:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self._data = data
        self.status = status

    def read(self) -> bytes:
        return self._data

    def decode(self, encoding: str = "utf-8") -> str:
        return self._data.decode(encoding)

    def __enter__(self) -> MockHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_market_prices_btc_macro_eliminates_linear_multipliers(tmp_path: Path) -> None:
    """Verifies market prices btc_macro does not use linear multipliers (1.004, 0.988)."""
    reset_live_market_cache()
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(app, "GET", "/api/v1/market/prices")
    assert response.status_code == 200
    payload = response.json()

    assert "btc_macro" in payload
    macro = payload["btc_macro"]
    assert "current_price" in macro
    assert "ema50_1h" in macro
    assert "ema200_1h" in macro
    assert "regime" in macro
    assert "source" in macro

    current_price = macro["current_price"]
    ema50 = macro["ema50_1h"]
    ema200 = macro["ema200_1h"]

    # Verify that authentic EMAs strictly do NOT use fake linear multipliers
    ratio_50 = ema50 / current_price
    ratio_200 = ema200 / current_price

    # The old fake implementation was identically 1.004 and 0.988
    assert abs(ratio_50 - 1.004) > 1e-4, f"Fake multiplier 1.004 detected: {ratio_50}"
    assert abs(ratio_200 - 0.988) > 1e-4, f"Fake multiplier 0.988 detected: {ratio_200}"

    # Verify across multiple price levels that ratios vary (proving exponential smoothing)
    prices_to_test = [72000.0, 82600.0, 94000.0]
    ratios_50: list[float] = []
    ratios_200: list[float] = []

    for test_p in prices_to_test:
        computed = compute_authentic_btc_macro(test_p)
        r_50 = computed["ema50_1h"] / test_p
        r_200 = computed["ema200_1h"] / test_p
        ratios_50.append(r_50)
        ratios_200.append(r_200)
        assert abs(r_50 - 1.004) > 1e-4
        assert abs(r_200 - 0.988) > 1e-4

    # Ratios MUST vary across price levels for non-linear authentic EMA smoothing
    assert ratios_50[0] != ratios_50[-1], "EMA50 ratio remained constant across price levels!"
    assert ratios_200[0] != ratios_200[-1], "EMA200 ratio remained constant across price levels!"


def test_market_prices_authentic_ema_offline_resilient_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies market_prices falls back gracefully to local history and maintains EMAs."""
    reset_live_market_cache()

    def mock_urlopen_fail(*args: object, **kwargs: object) -> object:
        raise URLError("Network offline simulation")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_fail)

    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(app, "GET", "/api/v1/market/prices")
    assert response.status_code == 200
    payload = response.json()

    assert "btc_macro" in payload
    macro = payload["btc_macro"]
    current_price = macro["current_price"]
    ema50 = macro["ema50_1h"]
    ema200 = macro["ema200_1h"]

    assert current_price > 0
    assert ema50 > 0
    assert ema200 > 0
    # Must still NOT be fake linear multipliers
    assert abs(ema50 / current_price - 1.004) > 1e-4
    assert abs(ema200 / current_price - 0.988) > 1e-4
    assert macro["source"] in {"local_parquet_cache", "local_csv_history", "synthetic_history"}


def test_execution_status_mark_prices_sync_with_live_market(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies execution status mark prices reflect live market prices dynamically."""
    reset_live_market_cache()

    # 1. First test: Ensure BTC mark price is NOT the stale 95000.0 backtest placeholder
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    resp1 = _request(app, "GET", "/api/v1/execution/status")
    assert resp1.status_code == 200
    status1 = resp1.json()
    btc_mark = status1["positions"]["BTCUSDT"]["mark_price"]
    assert btc_mark is not None
    assert btc_mark != 95000.0, "BTC mark price is stuck at stale 95000.0 backtest placeholder!"

    # 2. Second test: Mock live ticker prices and verify dynamic synchronization
    mock_ticker_data = [
        {"symbol": "BTCUSDT", "price": "78450.25"},
        {"symbol": "ETHUSDT", "price": "2365.50"},
        {"symbol": "SOLUSDT", "price": "142.75"},
    ]
    raw_bytes = json.dumps(mock_ticker_data).encode("utf-8")

    def mock_live_ticker(req: object, *args: object, **kwargs: object) -> MockHttpResponse:
        return MockHttpResponse(raw_bytes)

    monkeypatch.setattr(urllib.request, "urlopen", mock_live_ticker)
    reset_live_market_cache()

    resp2 = _request(app, "GET", "/api/v1/execution/status")
    assert resp2.status_code == 200
    status2 = resp2.json()

    positions = status2["positions"]
    assert positions["BTCUSDT"]["mark_price"] == 78450.25
    assert positions["ETHUSDT"]["mark_price"] == 2365.50
    assert positions["SOLUSDT"]["mark_price"] == 142.75

    # Cross-verify with /api/v1/market/prices
    resp_market = _request(app, "GET", "/api/v1/market/prices")
    assert resp_market.status_code == 200
    m_payload = resp_market.json()
    assert m_payload["prices"]["BTCUSDT"] == positions["BTCUSDT"]["mark_price"]
    assert m_payload["prices"]["ETHUSDT"] == positions["ETHUSDT"]["mark_price"]
    assert m_payload["prices"]["SOLUSDT"] == positions["SOLUSDT"]["mark_price"]


def test_execution_status_flat_positions_and_zero_phantom_positions(tmp_path: Path) -> None:
    """Verifies flat position state (0.00 exposure) and complete absence of phantoms."""
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(app, "GET", "/api/v1/execution/status")
    assert response.status_code == 200
    payload = response.json()

    assert payload["aggregate_exposure_usdt"] == 0.0

    positions = payload["positions"]
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert sym in positions
        pos = positions[sym]
        assert pos["symbol"] == sym
        assert pos["position_qty"] == 0.0, f"Phantom position detected on {sym}"
        assert pos["allocated_exposure_usdt"] == 0.0
        assert pos["allocated_margin_usdt"] == 0.0
        assert pos["unrealized_pnl_usdt"] == 0.0
        assert pos["state"] == "STANDBY / SCANNING"
        assert pos["status"] == "STANDBY / SCANNING"
        assert pos["entry_price"] is None
        assert pos["take_profit_price"] is None
        assert pos["stop_loss_price"] is None


def test_double_entry_ledger_zero_drift_invariant(tmp_path: Path) -> None:
    """Verifies double-entry solvency invariant holds with |drift| < 10^-15 USDT."""
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(app, "GET", "/api/v1/execution/status")
    assert response.status_code == 200
    payload = response.json()

    solvency = payload["solvency"]
    starting_equity = solvency["starting_equity_usdt"]
    cash = solvency["cash_usdt"]
    allocated_margin = solvency["allocated_margin_usdt"]
    unrealized_pnl = solvency["unrealized_pnl_usdt"]
    realized_pnl = solvency["realized_pnl_usdt"]

    # Fundamental Balance Equation:
    # Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL
    left_hand_side = cash + allocated_margin + unrealized_pnl
    right_hand_side = starting_equity + realized_pnl
    drift = abs(left_hand_side - right_hand_side)

    assert drift < 1e-15, f"Double-entry ledger drift violation: {drift} >= 1e-15 USDT"
    assert solvency["drift_usdt"] == 0.0 or solvency["drift_usdt"] < 1e-15
    assert solvency["zero_balance_drift_verified"] is True
    assert solvency["cash_reserve_pct"] == 100.0
    assert solvency["unencumbered_cash_verified"] is True


def test_authentic_orders_zero_ord_p309_records(tmp_path: Path) -> None:
    """Verifies 100% authentic order IDs (canary-p310-, canary-p311-) and zero ord-p309- records."""
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    response = _request(app, "GET", "/api/v1/execution/status")
    assert response.status_code == 200
    payload = response.json()

    orders = payload["recent_orders"]
    assert len(orders) > 0, "Expected non-empty authentic orders feed"
    assert payload["total_orders"] == len(orders)

    for o in orders:
        cid = o["client_order_id"]
        oid = o["order_id"]
        # Zero ord-p309 records allowed
        assert not cid.startswith("ord-p309-"), f"Stale ord-p309 client order ID found: {cid}"
        assert not oid.startswith("ord-p309-"), f"Stale ord-p309 order ID found: {oid}"

        # 100% authentic order IDs
        assert cid.startswith("canary-p310-") or cid.startswith("canary-p311-"), (
            f"Unrecognized non-authentic order ID: {cid}"
        )

        assert o["symbol"] in {"SOLUSDT", "ETHUSDT", "BTCUSDT"}
        assert o["side"] in {"BUY", "SELL"}
        assert o["price"] >= 0.0
        assert o["quantity"] >= 0.0
        assert o["notional_usdt"] >= 0.0
        assert o["status"] in {"FILLED", "CANCELED", "NEW"}
        assert o["fee_usdt"] >= 0.0
        assert o["timestamp_ms"] > 0

    # Ensure chronological sort descending
    timestamps = [o["timestamp_ms"] for o in orders]
    assert timestamps == sorted(timestamps, reverse=True)


def test_sqlite_solvency_telemetry_zero_drift_attestation() -> None:
    """Verifies continuous mathematical zero drift (|drift| < 10^-15) across SQLite records."""
    db_paths = [
        Path("artifacts/research/phase310/canary-production-telemetry.sqlite3"),
        Path("artifacts/research/phase311/canary-lifecycle-telemetry.sqlite3"),
    ]

    query = (
        "SELECT cash, allocated_margin, unrealized_pnl, realized_pnl, "
        "starting_equity, total_equity, drift FROM solvency_snapshots"
    )

    for db_path in db_paths:
        if not db_path.is_file():
            continue
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        assert len(rows) > 0, f"Expected solvency snapshots in {db_path}"
        for cash, margin, upnl, rpnl, start_eq, _tot_eq, drift in rows:
            calc_total = float(cash) + float(margin) + float(upnl)
            calc_target = float(start_eq) + float(rpnl)
            calculated_drift = abs(calc_total - calc_target)
            assert calculated_drift < 1e-15, f"Drift in {db_path}: {calculated_drift} >= 1e-15"
            assert float(drift) < 1e-15
        conn.close()
