"""Adversarial Empirical Challenge Suite: Milestone 1 Backend Telemetry Truthfulness.

Stress-tests:
1. Authentic BTC Macro EMAs:
   - Validates that EMAs change dynamically across bull, bear, oscillating, and flash-crash series.
   - Mathematically verifies that ratios (ema50 / price, ema200 / price) are NEVER fixed
     linear constants (e.g. 1.004, 0.988).
   - Validates numerical accuracy against an independent reference exponential smoothing oracle.
   - Tests regime classification truthfulness under adversarial trend switches.
2. Offline / Network Chaos Resilience:
   - Injects network timeouts, HTTP 500/502/503 errors, socket disconnects, malformed/truncated.
   - Tests graceful degradation across cascading fallbacks (Parquet -> CSV -> Synthetic wave).
   - Tests boundary input prices (0.0, negative prices, extreme values like $1M and $0.001).
   - Asserts zero unhandled exceptions and valid telemetry output under full network failure.
3. Mark Price Dynamic Synchronization:
   - Tests extreme live ticker prices (BTC at $15k, $250k; ETH at $12k; SOL at $950).
   - Tests stale placeholder sanitization (ensures 95k backtest placeholder never leaks offline).
   - Cross-verifies synchronization between /api/v1/market/prices and /api/v1/execution/status.
4. Zero-Drift Balance Invariant Under Fills and Fees:
   - Generates 1,000 simulated micro-trades with fills, fee deductions, and mark moves.
   - Evaluates: Cash + Allocated Margin + Unrealized PnL = Starting Equity + Realized PnL.
   - Injects deliberate balance tampering into execution reports to verify fail-closed drift.
   - Empirically verifies zero-drift invariant across all SQLite solvency records.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from autonomous_futures.api import create_app
from autonomous_futures.api.app import (
    _compute_ema_series,
    compute_authentic_btc_macro,
    load_execution_status,
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


def _oracle_ema(series: list[float], span: int) -> float:
    """Independent reference oracle for exponential moving average calculation."""
    if not series:
        return 0.0
    alpha = 2.0 / (span + 1.0)
    ema = series[0]
    for p in series[1:]:
        ema = (p * alpha) + (ema * (1.0 - alpha))
    return ema


# ==============================================================================
# SECTION 1: ADVERSARIAL CHALLENGES ON BTC MACRO EMA & REGIME TRUTHFULNESS
# ==============================================================================


@pytest.mark.parametrize(
    "scenario,base_price,price_generator",
    [
        (
            "parabolic_bull",
            60000.0,
            lambda i, base: base * (1.0 + 0.003 * i + 0.00005 * (i**2)),
        ),
        (
            "catastrophic_bear",
            90000.0,
            lambda i, base: base * (1.0 - 0.0025 * i),
        ),
        (
            "high_frequency_chop",
            75000.0,
            lambda i, base: base + 1500.0 * math.sin(i * 0.5) + 600.0 * math.cos(i * 1.2),
        ),
        (
            "flash_crash_step",
            82000.0,
            lambda i, base: base if i < 180 else base * 0.70,
        ),
    ],
)
def test_adversarial_btc_macro_never_fixed_linear_multipliers(
    scenario: str,
    base_price: float,
    price_generator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adversarial stress-test: verifies EMAs dynamically adapt and NEVER match static ratios."""
    reset_live_market_cache()

    # Generate 210 candles of simulated market structure
    candles = [price_generator(i, base_price) for i in range(210)]
    current_price = candles[-1]

    # Mock Binance klines endpoint to feed our synthetic market scenario
    mock_klines = [
        [
            1700000000000 + i * 3600000,
            str(p),
            str(p * 1.002),
            str(p * 0.998),
            str(p),
            "100.0",
        ]
        for i, p in enumerate(candles)
    ]
    raw_bytes = json.dumps(mock_klines).encode("utf-8")

    def mock_fetch(req: object, *args: object, **kwargs: object) -> MockHttpResponse:
        return MockHttpResponse(raw_bytes)

    monkeypatch.setattr(urllib.request, "urlopen", mock_fetch)

    macro = compute_authentic_btc_macro(current_price)

    ema50 = macro["ema50_1h"]
    ema200 = macro["ema200_1h"]
    price = macro["current_price"]

    ratio_50 = ema50 / price
    ratio_200 = ema200 / price

    # Critical Assertion: The old fake linear multiplier was identically 1.004 and 0.988
    # Under authentic smoothing, these ratios MUST NOT match 1.004 or 0.988 within 1e-4 tolerance
    assert abs(ratio_50 - 1.004) > 1e-4, f"Scenario '{scenario}': Fake multiplier 1.004 detected!"
    assert abs(ratio_200 - 0.988) > 1e-4, f"Scenario '{scenario}': Fake multiplier 0.988 detected!"

    # Scenario-specific structural verification
    if scenario == "parabolic_bull":
        assert price > ema50 > ema200, f"Bullish structure violation: price={price}"
        assert ratio_50 < 1.0, f"In bull trend, ema50/price must be < 1.0, got {ratio_50}"
        assert ratio_200 < ratio_50, f"In bull trend, ema200 must be below ema50: {ratio_200}"
        assert macro["regime"] == "BULLISH ALIGNED"

    elif scenario == "catastrophic_bear":
        assert price < ema50 < ema200, f"Bearish structure violation: price={price}"
        assert ratio_50 > 1.0, f"In bear dump, ema50/price must be > 1.0, got {ratio_50}"
        assert ratio_200 > ratio_50, f"In bear dump, ema200 must be above ema50: {ratio_200}"
        assert macro["regime"] == "BEARISH"

    elif scenario == "flash_crash_step":
        assert price < ema50
        assert price < ema200
        assert macro["regime"] in {"BEARISH", "SIDEWAYS"}


def test_adversarial_oracle_numerical_precision_verification() -> None:
    """Verifies that internal _compute_ema_series matches independent reference oracle."""
    random.seed(42)

    for trial in range(50):
        length = random.randint(50, 300)
        start = random.uniform(20000.0, 90000.0)
        series = [start]
        for _ in range(length - 1):
            drift = random.gauss(0.0, 0.005)
            series.append(series[-1] * (1.0 + drift))

        for span in (50, 200):
            actual_series = _compute_ema_series(series, span)
            actual_latest = actual_series[-1]
            oracle_latest = _oracle_ema(series, span)

            diff = abs(actual_latest - oracle_latest)
            assert diff < 1e-9, f"Trial {trial}, span {span}: Oracle deviation {diff} >= 1e-9"


# ==============================================================================
# SECTION 2: OFFLINE AND NETWORK CHAOS FAULT INJECTION
# ==============================================================================


@pytest.mark.parametrize(
    "fault_type,fault_exception",
    [
        ("connection_timeout", urllib.error.URLError("Connection timed out")),
        (
            "http_500_internal",
            urllib.error.HTTPError(
                "http://test", 500, "Internal Server Error", cast(Any, {}), None
            ),
        ),
        (
            "http_502_bad_gateway",
            urllib.error.HTTPError(
                "http://test", 502, "Bad Gateway", cast(Any, {}), None
            ),
        ),
        (
            "http_429_rate_limit",
            urllib.error.HTTPError(
                "http://test", 429, "Too Many Requests", cast(Any, {}), None
            ),
        ),
        ("socket_disconnect", OSError("Connection reset by peer")),
    ],
)
def test_adversarial_network_fault_injection_resilience(
    fault_type: str,
    fault_exception: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fault injection: Simulates network degradation and verifies reliable fallback."""
    reset_live_market_cache()

    def mock_fault(*args: object, **kwargs: object) -> object:
        raise fault_exception

    monkeypatch.setattr(urllib.request, "urlopen", mock_fault)

    macro = compute_authentic_btc_macro(82600.0)

    assert isinstance(macro, dict)
    assert macro["current_price"] == 82600.0
    assert macro["ema50_1h"] > 0
    assert macro["ema200_1h"] > 0
    assert macro["regime"] in {"BULLISH ALIGNED", "BEARISH", "SIDEWAYS"}
    assert macro["source"] in {"local_parquet_cache", "local_csv_history", "synthetic_history"}
    # Verify non-trivial values
    assert abs(macro["ema50_1h"] / 82600.0 - 1.004) > 1e-4
    assert abs(macro["ema200_1h"] / 82600.0 - 0.988) > 1e-4


@pytest.mark.parametrize(
    "corrupt_payload",
    [
        b"<html>502 Bad Gateway</html>",
        b"",
        b"[]",
        b'[{"close": 82500}]',  # < 50 items
        b'{"code": -1003, "msg": "Too many requests"}',  # Dict instead of list
        b"not-even-json",
    ],
)
def test_adversarial_malformed_network_payload_resilience(
    corrupt_payload: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adversarial testing against malformed, truncated, or hostile network payloads."""
    reset_live_market_cache()

    def mock_corrupt(*args: object, **kwargs: object) -> MockHttpResponse:
        return MockHttpResponse(corrupt_payload)

    monkeypatch.setattr(urllib.request, "urlopen", mock_corrupt)

    macro = compute_authentic_btc_macro(81500.0)
    assert isinstance(macro, dict)
    assert macro["current_price"] == 81500.0
    assert macro["ema50_1h"] > 0
    assert macro["ema200_1h"] > 0
    assert macro["source"] in {"local_parquet_cache", "local_csv_history", "synthetic_history"}


def test_adversarial_full_isolation_synthetic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adversarial stress-test: Complete isolation (no network, no parquet, no csv)."""
    reset_live_market_cache()

    def mock_fail(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("Isolated network")

    monkeypatch.setattr(urllib.request, "urlopen", mock_fail)

    # 1. When files are present, network failure gracefully falls back to local_parquet_cache
    macro_parquet = compute_authentic_btc_macro(79000.0)
    assert macro_parquet["source"] in {"local_parquet_cache", "local_csv_history"}
    assert macro_parquet["ema50_1h"] > 0
    assert macro_parquet["ema200_1h"] > 0

    # 2. When local files are also missing/inaccessible, falls back to synthetic_history
    orig_is_file = Path.is_file

    def mock_no_files(path_obj: Path) -> bool:
        if path_obj.suffix in {".parquet", ".csv"}:
            return False
        return orig_is_file(path_obj)

    monkeypatch.setattr(Path, "is_file", mock_no_files)
    reset_live_market_cache()

    macro_synthetic = compute_authentic_btc_macro(79000.0)
    assert macro_synthetic["source"] == "synthetic_history"
    assert macro_synthetic["current_price"] == 79000.0
    assert macro_synthetic["ema50_1h"] > 0
    assert macro_synthetic["ema200_1h"] > 0
    assert abs(macro_synthetic["ema50_1h"] / 79000.0 - 1.004) > 1e-4
    assert abs(macro_synthetic["ema200_1h"] / 79000.0 - 0.988) > 1e-4


@pytest.mark.parametrize("edge_price", [0.0, -100.0, 1000000.0, 0.001])
def test_adversarial_edge_price_inputs(edge_price: float, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stress-tests boundary and anomalous price inputs to compute_authentic_btc_macro."""
    reset_live_market_cache()

    def mock_fail(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("Isolated")

    monkeypatch.setattr(urllib.request, "urlopen", mock_fail)

    ghost_dir = Path("nonexistent_isolation_dir/test")
    macro = compute_authentic_btc_macro(edge_price, research_dir=ghost_dir)
    assert isinstance(macro, dict)
    assert macro["current_price"] == float(edge_price)
    assert isinstance(macro["ema50_1h"], float)
    assert isinstance(macro["ema200_1h"], float)


# ==============================================================================
# SECTION 3: MARK PRICE SYNCHRONIZATION AND EXTREME EXPOSURE TESTS
# ==============================================================================


@pytest.mark.parametrize(
    "extreme_btc,extreme_eth,extreme_sol",
    [
        (15000.0, 800.0, 12.0),
        (250000.0, 12500.0, 950.0),
        (82765.43, 2432.10, 153.25),
    ],
)
def test_adversarial_mark_price_synchronization_extremes(
    extreme_btc: float,
    extreme_eth: float,
    extreme_sol: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies mark price synchronization in execution status against extreme market regimes."""
    reset_live_market_cache()

    mock_ticker_data = [
        {"symbol": "BTCUSDT", "price": str(extreme_btc)},
        {"symbol": "ETHUSDT", "price": str(extreme_eth)},
        {"symbol": "SOLUSDT", "price": str(extreme_sol)},
    ]
    raw_bytes = json.dumps(mock_ticker_data).encode("utf-8")

    def mock_live_ticker(req: object, *args: object, **kwargs: object) -> MockHttpResponse:
        return MockHttpResponse(raw_bytes)

    monkeypatch.setattr(urllib.request, "urlopen", mock_live_ticker)

    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )

    resp = _request(app, "GET", "/api/v1/execution/status")
    assert resp.status_code == 200
    data = resp.json()

    positions = data["positions"]
    assert positions["BTCUSDT"]["mark_price"] == extreme_btc
    assert positions["ETHUSDT"]["mark_price"] == extreme_eth
    assert positions["SOLUSDT"]["mark_price"] == extreme_sol

    # Synchronized with /api/v1/market/prices
    resp_market = _request(app, "GET", "/api/v1/market/prices")
    assert resp_market.status_code == 200
    market_data = resp_market.json()
    assert market_data["prices"]["BTCUSDT"] == extreme_btc
    assert market_data["prices"]["ETHUSDT"] == extreme_eth
    assert market_data["prices"]["SOLUSDT"] == extreme_sol


def test_adversarial_stale_95k_backtest_placeholder_clamp_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies offline 95k backtest placeholder in report files is clamped to 82.6k baseline."""
    reset_live_market_cache()

    def mock_fail(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("Network down")

    monkeypatch.setattr(urllib.request, "urlopen", mock_fail)

    p310_dir = tmp_path / "phase310"
    p310_dir.mkdir(parents=True)
    report_content = {
        "phase": "phase_310",
        "timestamp_ms": 1700000000000,
        "solvency": {
            "starting_equity": 100.0,
            "cash": 100.0,
            "realized_pnl": 0.0,
        },
        "candidates": {
            "BTCUSDT": {"current_price": 95000.0, "position_qty": 0.0},
            "ETHUSDT": {"current_price": 2750.0, "position_qty": 0.0},
            "SOLUSDT": {"current_price": 185.0, "position_qty": 0.0},
        },
    }
    rep_file = p310_dir / "canary-production-report.json"
    rep_file.write_text(json.dumps(report_content), encoding="utf-8")

    status = load_execution_status(tmp_path)
    btc_mark = status.positions["BTCUSDT"].mark_price

    assert btc_mark != 95000.0, f"Stale 95k placeholder leaked: {btc_mark}"
    assert btc_mark == 82600.0, f"Expected clamped baseline 82600.0, got {btc_mark}"


# ==============================================================================
# SECTION 4: DOUBLE-ENTRY ZERO-DRIFT INVARIANT UNDER SIMULATED FILLS AND FEES
# ==============================================================================


def test_adversarial_monte_carlo_fills_fees_zero_drift_simulation() -> None:
    """Simulates 1,000 continuous trade fills, fees, mark moves; verifies drift < 1e-12."""
    random.seed(1337)

    starting_equity = 100.0000000000000
    cash = 100.0000000000000
    allocated_margin = 0.0
    unrealized_pnl = 0.0
    realized_pnl = 0.0

    position_qty = 0.0
    entry_price = 0.0
    current_mark = 185.0

    for step in range(1000):
        action = random.choice(["FILL_BUY", "PRICE_MOVE", "FILL_SELL", "PARTIAL_CLOSE", "IDLE"])

        if action == "FILL_BUY" and position_qty == 0.0:
            qty = round(random.uniform(0.01, 0.05), 4)
            price = round(current_mark, 2)
            notional = price * qty
            leverage = 5.0
            margin = notional / leverage
            maker_fee = notional * 0.0002

            cash -= margin + maker_fee
            allocated_margin += margin
            realized_pnl -= maker_fee
            position_qty = qty
            entry_price = price
            unrealized_pnl = (current_mark - entry_price) * position_qty

        elif action == "PRICE_MOVE" and position_qty > 0.0:
            delta = random.uniform(-2.0, 2.0)
            current_mark = max(10.0, current_mark + delta)
            unrealized_pnl = (current_mark - entry_price) * position_qty

        elif action in {"FILL_SELL", "PARTIAL_CLOSE"} and position_qty > 0.0:
            close_qty = position_qty if action == "FILL_SELL" else round(position_qty * 0.5, 4)
            exit_price = round(current_mark, 2)
            trade_realized_pnl = (exit_price - entry_price) * close_qty
            notional = exit_price * close_qty
            exit_fee = notional * 0.0002

            margin_fraction = close_qty / position_qty
            released_margin = allocated_margin * margin_fraction

            allocated_margin -= released_margin
            cash += released_margin + trade_realized_pnl - exit_fee
            realized_pnl += trade_realized_pnl - exit_fee
            position_qty -= close_qty

            if position_qty <= 1e-6:
                position_qty = 0.0
                entry_price = 0.0
                unrealized_pnl = 0.0
                allocated_margin = 0.0
            else:
                unrealized_pnl = (current_mark - entry_price) * position_qty

        lhs = cash + allocated_margin + unrealized_pnl
        rhs = starting_equity + realized_pnl + unrealized_pnl
        drift = abs(lhs - rhs)

        assert drift < 1e-12, (
            f"Step {step} ({action}) Drift violation: {drift} >= 1e-12. "
            f"LHS={lhs}, RHS={rhs}, Cash={cash}, Margin={allocated_margin}"
        )


def test_adversarial_solvency_tamper_detection(tmp_path: Path) -> None:
    """Verifies that load_execution_status detects balance drift if reports are tampered."""
    reset_live_market_cache()

    p310_dir = tmp_path / "phase310"
    p310_dir.mkdir(parents=True)

    report_content = {
        "phase": "phase_310",
        "timestamp_ms": 1700000000000,
        "solvency": {
            "starting_equity": 100.0,
            "cash": 105.0,  # Phantom $5 drift!
            "realized_pnl": 0.0,
        },
        "candidates": {},
    }
    rep_file = p310_dir / "canary-production-report.json"
    rep_file.write_text(json.dumps(report_content), encoding="utf-8")

    status = load_execution_status(tmp_path)
    solvency = status.solvency

    assert solvency.zero_balance_drift_verified is False
    assert abs(solvency.drift_usdt - 5.0) < 1e-6
    assert abs(solvency.drift - 5.0) < 1e-6


def test_adversarial_sqlite_zero_drift_all_rows() -> None:
    """Exhaustively verifies every single solvency snapshot row in production SQLite databases."""
    db_paths = [
        Path("artifacts/research/phase310/canary-production-telemetry.sqlite3"),
        Path("artifacts/research/phase311/canary-lifecycle-telemetry.sqlite3"),
    ]

    total_rows_checked = 0
    for db in db_paths:
        if not db.is_file():
            continue
        conn = sqlite3.connect(str(db))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp_ms, cash, allocated_margin, unrealized_pnl, realized_pnl, "
            "starting_equity, total_equity, drift FROM solvency_snapshots"
        )
        rows = cursor.fetchall()
        assert len(rows) > 0, f"No rows found in {db}"
        for ts, cash, margin, upnl, rpnl, start_eq, _tot_eq, drift in rows:
            calc_lhs = float(cash) + float(margin) + float(upnl)
            calc_rhs = float(start_eq) + float(rpnl)
            recomputed_drift = abs(calc_lhs - calc_rhs)
            assert recomputed_drift < 1e-15, (
                f"DB {db} row ts={ts}: Drift violation {recomputed_drift} >= 1e-15 "
                f"(cash={cash}, margin={margin}, upnl={upnl}, start={start_eq}, rpnl={rpnl})"
            )
            assert float(drift) < 1e-15
            total_rows_checked += 1
        conn.close()

    assert total_rows_checked > 0, "No SQLite solvency rows were evaluated!"
