"""Phase 317 Milestone 6 Empirical Challenger: Live HTTPS Endpoints, Solvency Zero-Drift Invariant, and Adversarial Concurrency Stress.

Empirical Challenger Test Suite for Phase 317 Milestone 6 on https://futures.semua.dev:
1. Live HTTPS Endpoint Contracts:
   - GET /health: 200 OK, {"status": "ok", "service": "autonomous-futures-data-api", "paper_safe": true, "execution_authority": false}
   - GET /api/v1/market/prices: 200 OK, all 8 pairs present (BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX), prices > 0, valid btc_macro regime
   - GET /api/v1/strategy/ict-signals: 200 OK, verified=True, active_family="ICT_MMXM_TWINS", all 8 pairs with twins_state, pd_arrays, candidate_genome
   - GET /api/v1/execution/status: 200 OK, solvency zero-drift invariant (|drift| < 1e-15 USDT), cash_reserve_pct == 100.0% (>= 75% floor), aggregate_exposure_usdt == 0.0 (<= $25.00 cap)
2. Adversarial Concurrency Stress:
   - 30 concurrent requests to /api/v1/strategy/ict-signals: zero 500 errors, consistent schema
   - 30 concurrent requests to /api/v1/execution/status: zero 500 errors, zero balance drift across all responses
   - VPS server-side burst latency benchmarking: response latency < 50ms on ICT signals
3. 24/7 VPS Background Trader Daemon Invariant:
   - autonomous-futures-trader.service Main PID == 87549, NRestarts == 0, ActiveState == "active", SubState == "running"
4. Institutional English Localization:
   - Live HTML and compiled JS bundle have 0 matches against 273 banned terms
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

LIVE_BASE_URL = "https://futures.semua.dev"
SSH_KEY_PATH = Path.home() / ".ssh" / "kainode_ed25519_openssh"
VPS_HOST = "afbot@147.79.18.15"

EXPECTED_8_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
]


def run_ssh(cmd: str) -> subprocess.CompletedProcess[str]:
    """Execute SSH command on Kainode VPS."""
    full_cmd = [
        "ssh",
        "-n",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-i", str(SSH_KEY_PATH),
        VPS_HOST,
        cmd,
    ]
    return subprocess.run(
        full_cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


# -----------------------------------------------------------------------------
# 1. Live HTTPS Endpoint Verification
# -----------------------------------------------------------------------------


def test_live_health_endpoint() -> None:
    """Empirically asserts GET /health returns expected status and invariant payload."""
    with httpx.Client(base_url=LIVE_BASE_URL, timeout=10.0) as client:
        resp = client.get("/health")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert data.get("status") == "ok", f"Expected 'ok', got {data.get('status')}"
    assert data.get("service") == "autonomous-futures-data-api"
    assert data.get("paper_safe") is True
    assert data.get("execution_authority") is False


def test_live_market_prices_8_pairs() -> None:
    """Empirically asserts GET /api/v1/market/prices contains all 8 perpetual universe pairs and valid btc_macro."""
    with httpx.Client(base_url=LIVE_BASE_URL, timeout=15.0) as client:
        resp = client.get("/api/v1/market/prices")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    prices = data.get("prices", {})
    assert isinstance(prices, dict)

    for pair in EXPECTED_8_PAIRS:
        assert pair in prices, f"Missing pair {pair} in prices dict: {list(prices.keys())}"
        price_val = float(prices[pair])
        assert price_val > 0.0, f"Mark price for {pair} must be > 0, got {price_val}"

    # Verify btc_macro regime
    btc_macro = data.get("btc_macro")
    assert isinstance(btc_macro, dict), "btc_macro field missing or not a dict"
    regime = btc_macro.get("regime")
    assert regime in {"BULLISH_ALIGNED", "BEARISH", "SIDEWAYS"}, f"Invalid regime: {regime}"
    assert float(btc_macro.get("current_price", 0.0)) > 0.0


def test_live_strategy_ict_signals_schema() -> None:
    """Empirically asserts GET /api/v1/strategy/ict-signals returns verified ICT MMXM Twins strategy for all 8 pairs."""
    with httpx.Client(base_url=LIVE_BASE_URL, timeout=15.0) as client:
        resp = client.get("/api/v1/strategy/ict-signals")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()

    assert data.get("verified") is True, f"Strategy not verified: {data.get('verified')}"
    assert data.get("active_family") == "ICT_MMXM_TWINS"
    signals = data.get("signals", {})
    assert isinstance(signals, dict)

    for pair in EXPECTED_8_PAIRS:
        assert pair in signals, f"Missing {pair} in signals: {list(signals.keys())}"
        sig = signals[pair]
        assert sig.get("symbol") == pair

        # twins_state validation
        twins = sig.get("twins_state")
        assert isinstance(twins, dict), f"twins_state missing for {pair}"
        for step in ["step_1_htf_hit", "step_2_m5_cisd", "step_3_twins_fvg", "step_4_ote_retrace", "step_5_m1_cisd"]:
            assert step in twins, f"Missing {step} in twins_state for {pair}"
            assert isinstance(twins[step], bool)

        # pd_arrays validation
        pda = sig.get("pd_arrays")
        assert isinstance(pda, dict), f"pd_arrays missing for {pair}"
        for tf in ["4h", "1h", "15m", "5m", "1m"]:
            assert tf in pda, f"Missing timeframe {tf} in pd_arrays for {pair}"
            assert isinstance(pda[tf], list)

        # candidate_genome validation
        genome = sig.get("candidate_genome")
        assert isinstance(genome, dict), f"candidate_genome missing for {pair}"
        assert genome.get("symbol") == pair
        assert "lookback_htf" in genome
        assert "ote_lower" in genome
        assert "ote_upper" in genome
        assert "stdv_tp1" in genome
        assert "stdv_tp2" in genome


def test_live_execution_solvency_zero_drift() -> None:
    """Empirically asserts GET /api/v1/execution/status proves solvency zero-drift invariant under micro-capital limits."""
    with httpx.Client(base_url=LIVE_BASE_URL, timeout=15.0) as client:
        resp = client.get("/api/v1/execution/status")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()

    assert data.get("verified") is True
    assert float(data.get("aggregate_exposure_usdt", 999.0)) == 0.0, "Aggregate exposure must be 0.0 USDT when flat"

    solvency = data.get("solvency", {})
    assert isinstance(solvency, dict)
    assert solvency.get("zero_balance_drift_verified") is True

    drift = float(solvency.get("drift_usdt", 999.0))
    assert abs(drift) < 1e-15, f"Drift violation: |{drift}| >= 1e-15 USDT"

    cash_reserve_pct = float(solvency.get("cash_reserve_pct", 0.0))
    assert cash_reserve_pct == 100.0, f"Cash reserve {cash_reserve_pct}% != 100.0% (must be >= 75.0% floor)"

    # Double-entry balance equality:
    # Cash + Allocated Margin + Unrealized PnL == Starting Equity + Realized PnL
    cash = float(solvency.get("cash_usdt", 0.0))
    margin = float(solvency.get("allocated_margin_usdt", 0.0))
    upnl = float(solvency.get("unrealized_pnl_usdt", 0.0))
    start_eq = float(solvency.get("starting_equity_usdt", 0.0))
    rpnl = float(solvency.get("realized_pnl_usdt", 0.0))

    lhs = cash + margin + upnl
    rhs = start_eq + rpnl
    assert abs(lhs - rhs) < 1e-15, f"Double-entry equation violated: {lhs} != {rhs}"

    # Verify positions dict has all 8 pairs
    positions = data.get("positions", {})
    for pair in EXPECTED_8_PAIRS:
        assert pair in positions, f"Missing pair {pair} in positions"
        pos = positions[pair]
        assert float(pos.get("position_qty", 0.0)) == 0.0
        assert float(pos.get("allocated_exposure_usdt", 0.0)) == 0.0


# -----------------------------------------------------------------------------
# 2. Adversarial Concurrency Stress Testing
# -----------------------------------------------------------------------------


async def _run_concurrent_ict_signals(concurrency: int = 30) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(base_url=LIVE_BASE_URL, timeout=20.0) as client:
        # warm up
        await client.get("/health")

        async def fetch(i: int) -> dict[str, Any]:
            t0 = time.perf_counter()
            r = await client.get(f"/api/v1/strategy/ict-signals?_b={i}&_ts={int(time.time()*1000)}")
            dt = (time.perf_counter() - t0) * 1000
            return {"status_code": r.status_code, "latency_ms": dt, "data": r.json() if r.status_code == 200 else None}

        tasks = [fetch(i) for i in range(concurrency)]
        results = await asyncio.gather(*tasks)
    return results


async def _run_concurrent_execution_status(concurrency: int = 30) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(base_url=LIVE_BASE_URL, timeout=20.0) as client:
        # warm up
        await client.get("/health")

        async def fetch(i: int) -> dict[str, Any]:
            t0 = time.perf_counter()
            r = await client.get(f"/api/v1/execution/status?_b={i}&_ts={int(time.time()*1000)}")
            dt = (time.perf_counter() - t0) * 1000
            return {"status_code": r.status_code, "latency_ms": dt, "data": r.json() if r.status_code == 200 else None}

        tasks = [fetch(i) for i in range(concurrency)]
        results = await asyncio.gather(*tasks)
    return results


def test_adversarial_concurrency_ict_signals_30_burst() -> None:
    """Adversarial stress: 30 concurrent requests to /api/v1/strategy/ict-signals must yield zero 500 errors."""
    results = asyncio.run(_run_concurrent_ict_signals(30))
    assert len(results) == 30

    status_codes = [r["status_code"] for r in results]
    assert status_codes.count(500) == 0, f"Found 500 errors: {status_codes}"
    assert status_codes.count(200) == 30, f"Not all requests succeeded: {status_codes}"

    for i, res in enumerate(results):
        payload = res["data"]
        assert payload is not None, f"Req {i} payload was None"
        assert payload.get("verified") is True, f"Req {i} verified was not True"
        assert payload.get("active_family") == "ICT_MMXM_TWINS"
        assert len(payload.get("signals", {})) == 8


def test_adversarial_concurrency_execution_status_30_burst() -> None:
    """Adversarial stress: 30 concurrent requests to /api/v1/execution/status must yield zero 500 errors and zero drift."""
    results = asyncio.run(_run_concurrent_execution_status(30))
    assert len(results) == 30

    status_codes = [r["status_code"] for r in results]
    assert status_codes.count(500) == 0, f"Found 500 errors: {status_codes}"
    assert status_codes.count(200) == 30, f"Not all requests succeeded: {status_codes}"

    for i, res in enumerate(results):
        payload = res["data"]
        assert payload is not None, f"Req {i} payload was None"
        solv = payload.get("solvency", {})
        assert solv.get("zero_balance_drift_verified") is True, f"Req {i} drift not verified"
        drift = float(solv.get("drift_usdt", 999.0))
        assert abs(drift) < 1e-15, f"Req {i} balance drift violation: {drift}"
        assert float(solv.get("cash_reserve_pct", 0.0)) == 100.0
        assert float(payload.get("aggregate_exposure_usdt", 999.0)) == 0.0


def test_vps_server_side_ict_signals_latency() -> None:
    """Asserts that on the VPS host, response latency for /api/v1/strategy/ict-signals is strictly < 50ms."""
    py_bench_script = """
import time, httpx
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10.0) as client:
    # warm up
    client.get("/api/v1/strategy/ict-signals")
    latencies = []
    for _ in range(30):
        t0 = time.perf_counter()
        r = client.get("/api/v1/strategy/ict-signals")
        dt = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200
        latencies.append(dt)
    avg_lat = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    print(f"AVG={avg_lat:.2f},MAX={max_lat:.2f}")
"""
    res = run_ssh(f"/opt/autonomous-futures-bot/.venv/bin/python -c '{py_bench_script}'")
    assert res.returncode == 0, f"SSH benchmark failed: {res.stderr}"
    output = res.stdout.strip()
    assert "AVG=" in output and "MAX=" in output, f"Unexpected output: {output}"

    # Parse AVG and MAX
    parts = output.split(",")
    avg_lat = float(parts[0].split("=")[1])
    max_lat = float(parts[1].split("=")[1])

    # Response latency must be strictly < 50ms
    assert avg_lat < 50.0, f"Average server latency {avg_lat:.2f}ms >= 50ms"
    assert max_lat < 50.0, f"Max server latency {max_lat:.2f}ms >= 50ms"


# -----------------------------------------------------------------------------
# 3. VPS Trader Daemon Continuity Check
# -----------------------------------------------------------------------------


def test_vps_trader_daemon_continuous_invariant() -> None:
    """Asserts autonomous-futures-trader.service Main PID == 87549 with NRestarts == 0 and active status."""
    res = run_ssh("systemctl --user show autonomous-futures-trader.service --property=MainPID,NRestarts,ActiveState,SubState,Result && ps -p 87549 -o pid,ppid,user,etime,args --no-headers")
    assert res.returncode == 0, f"SSH daemon check failed: {res.stderr}"
    stdout = res.stdout

    assert "MainPID=87549" in stdout, f"MainPID not 87549: {stdout}"
    assert "NRestarts=0" in stdout, f"NRestarts not 0: {stdout}"
    assert "ActiveState=active" in stdout, f"Service not active: {stdout}"
    assert "SubState=running" in stdout, f"Service not running: {stdout}"
    assert "Result=success" in stdout, f"Result not success: {stdout}"
    assert "87549" in stdout, f"PID 87549 missing from ps table: {stdout}"
    assert "run_phase_310_real_autonomous_trading.py" in stdout, "Process command line mismatch"


# -----------------------------------------------------------------------------
# 4. English Localization Audit
# -----------------------------------------------------------------------------


def test_production_bundle_english_localization() -> None:
    """Asserts that live production web HTML and JS bundle have 0 matches for banned non-English terms."""
    from tests.adversarial.test_phase_316_m5_empirical_challenger import BANNED_MALAY_TERMS, find_banned_matches

    with httpx.Client(timeout=15.0) as client:
        html_resp = client.get(LIVE_BASE_URL)
        assert html_resp.status_code == 200
        html_text = html_resp.text
        html_matches = find_banned_matches(html_text)
        assert len(html_matches) == 0, f"Found {len(html_matches)} banned terms in HTML: {html_matches[:5]}"

        # Extract JS bundle path
        import re
        match = re.search(r'src=["\'](/assets/index-[^"\']+\.js)["\']', html_text)
        assert match is not None, "Failed to find main JS bundle script in index.html"
        js_url = f"{LIVE_BASE_URL}{match.group(1)}"
        js_resp = client.get(js_url)
        assert js_resp.status_code == 200
        js_matches = find_banned_matches(js_resp.text)
        assert len(js_matches) == 0, f"Found {len(js_matches)} banned terms in JS bundle: {js_matches[:5]}"
