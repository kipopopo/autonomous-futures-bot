"""Milestone M5 Empirical Challenger: Concurrency Stress, Dynamic State Machine, and Daemon Continuity.

Adversarial Stress Verification for Phase 315 Live Deployment on https://futures.semua.dev:
1. High-concurrency load testing (50 concurrent async probes) on /api/v1/canary/evolution:
   - Proves zero dropped requests or 500 errors under burst.
   - Validates dynamic 5-stage state transitions, 15s timer adherence, 0/5 samples scorecard,
     Sharpe hurdle >= 15.0%, and bilingual macro gating banner.
2. Dynamic transition tracking over live time windows:
   - Tracks actual stage transitions across seconds within the 15s cycle:
     INGRESS -> HEALTH_EVALUATION -> TRADE_AUTOPSY -> MUTATION_STAGING -> SHADOW_OOS_GATE.
   - Proves monotonic timer countdown and cycle reset behavior.
3. High-concurrency load testing (50 concurrent async probes) on /api/v1/execution/status:
   - Proves presence of all 8 perpetual pairs (BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX) in positions.
   - Proves exact zero drift: |drift| < 1e-15 USDT across all concurrent responses.
   - Proves 100% cash reserve and 0.0 aggregate exposure when flat.
4. Interleaved multi-endpoint load burst:
   - Concurrently strikes /api/v1/canary/evolution, /api/v1/execution/status, /api/v1/market/prices, /health.
5. VPS Trader Daemon (autonomous-futures-trader.service) Continuity Verification:
   - SSH query to Kainode VPS (147.79.18.15):
   - Proves Main PID remains strictly 87549.
   - Proves NRestarts remains strictly 0.
   - Proves ActiveState is active and SubState is running.
   - Proves multi-day continuous runtime via Linux ps table.
   - Proves journalctl error logs remain clean with zero tracebacks.
6. Frontend Production Bundle Integrity:
   - Proves https://futures.semua.dev/ serves the latest Phase 315 assets (index-BRnwio6R.js).
"""

from __future__ import annotations

import asyncio
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

FIVE_CYCLE_STAGES = [
    "INGRESS",
    "HEALTH_EVALUATION",
    "TRADE_AUTOPSY",
    "MUTATION_STAGING",
    "SHADOW_OOS_GATE",
]


def run_ssh(cmd: str) -> subprocess.CompletedProcess[str]:
    """Execute SSH command on Kainode VPS."""
    full_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-i", str(SSH_KEY_PATH),
        VPS_HOST,
        cmd,
    ]
    return subprocess.run(full_cmd, capture_output=True, text=True, check=False)


# -----------------------------------------------------------------------------
# 1. High-Concurrency Stress Probing on /api/v1/canary/evolution
# -----------------------------------------------------------------------------


async def _run_canary_evolution_concurrent(concurrency: int = 50) -> None:
    async with httpx.AsyncClient(base_url=LIVE_BASE_URL, timeout=15.0) as client:
        start_t = time.perf_counter()
        tasks = [
            client.get(f"/api/v1/canary/evolution?_req={i}&_ts={int(time.time() * 1000)}")
            for i in range(concurrency)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.perf_counter() - start_t

    assert len(responses) == concurrency
    failures = [
        r for r in responses
        if isinstance(r, Exception) or (isinstance(r, httpx.Response) and r.status_code != 200)
    ]
    assert len(failures) == 0, f"Encountered {len(failures)} failures out of {concurrency} requests: {failures[:3]}"

    # Validate schema and invariants across every single concurrent response
    for i, resp in enumerate(responses):
        assert isinstance(resp, httpx.Response)
        data = resp.json()
        assert data.get("verified") is True, f"Req {i}: verified flag missing or False"
        assert "live_progress" in data, f"Req {i}: missing live_progress"
        lp = data["live_progress"]

        # Daemon status & PID
        assert lp.get("is_live_daemon_active") is True
        assert lp.get("daemon_pid") == 87549
        assert lp.get("daemon_status") == "ONLINE 24/7"

        # 5-stage dynamic cycle validation
        stage = lp.get("current_cycle_stage")
        assert stage in FIVE_CYCLE_STAGES, f"Req {i}: invalid stage {stage}"

        # 15s timer bounds
        next_sec = lp.get("next_cycle_seconds")
        assert isinstance(next_sec, int), f"Req {i}: next_cycle_seconds not int"
        assert 1 <= next_sec <= 15, f"Req {i}: next_cycle_seconds {next_sec} out of [1, 15]"

        # Sample count scorecard: 0 / 5 samples
        closed_trades = lp.get("closed_trades_count")
        required_trades = lp.get("required_trades_count")
        assert closed_trades == 0, f"Req {i}: expected 0 closed trades, got {closed_trades}"
        assert required_trades == 5, f"Req {i}: expected 5 required trades, got {required_trades}"
        assert lp.get("stage_status") == "WAITING_FOR_SAMPLES"
        assert "0/5" in lp.get("stage_status_label", "")

        # Sharpe hurdle >= 15.0%
        sharpe_hurdle = float(lp.get("sharpe_hurdle_pct", 0.0))
        assert sharpe_hurdle >= 15.0, f"Req {i}: Sharpe hurdle {sharpe_hurdle} < 15.0%"

        # Macro gating banner
        macro = lp.get("macro_gating_state", {})
        assert macro.get("regime") in ["BEARISH", "BULLISH_ALIGNED", "SIDEWAYS"]
        assert isinstance(macro.get("longs_filtered"), bool)
        assert len(macro.get("explanation", "")) > 15
        assert len(macro.get("explanation_ms", "")) > 15
        assert "capital" in macro.get("explanation_ms", "").lower() or "Active BTC Macro Trend Filter" in macro.get("explanation_ms", "")

        # Scanned symbols must include all 8 pairs
        scanned = lp.get("scanned_symbols", [])
        for sym in EXPECTED_8_PAIRS:
            assert sym in scanned, f"Req {i}: missing {sym} in scanned_symbols"

    # Concurrency throughput assertion: 50 requests handled within 10s
    assert elapsed < 10.0, f"Total duration for 50 concurrent requests was {elapsed:.2f}s (> 10s)"


def test_canary_evolution_concurrent_load_50_requests() -> None:
    """Stress-test /api/v1/canary/evolution with 50 concurrent async requests."""
    asyncio.run(_run_canary_evolution_concurrent(50))


# -----------------------------------------------------------------------------
# 2. Dynamic 5-Stage Transition Observation across Time
# -----------------------------------------------------------------------------


def test_canary_evolution_dynamic_stage_transitions_over_time() -> None:
    """Empirically samples /api/v1/canary/evolution over 16 seconds to observe dynamic state changes."""
    client = httpx.Client(base_url=LIVE_BASE_URL, timeout=10.0)
    stages_observed: set[str] = set()
    timer_samples: list[tuple[float, int, str]] = []

    # Sample every 1.5 seconds for 11 iterations (~16.5 seconds)
    start_time = time.time()
    for _ in range(11):
        resp = client.get(f"/api/v1/canary/evolution?_t={time.time()}")
        assert resp.status_code == 200
        lp = resp.json().get("live_progress", {})
        st = lp.get("current_cycle_stage")
        nxt = lp.get("next_cycle_seconds")
        stages_observed.add(st)
        timer_samples.append((time.time() - start_time, nxt, st))
        time.sleep(1.5)

    client.close()

    # Across an ~16s window, at least 3 distinct stages of the 5-stage cycle MUST be observed
    assert len(stages_observed) >= 3, (
        f"Expected at least 3 distinct stages across 16s window, observed only {len(stages_observed)}: {stages_observed}"
    )
    for st in stages_observed:
        assert st in FIVE_CYCLE_STAGES, f"Unexpected stage observed: {st}"

    # Verify that the countdown timer actually changes across samples
    timers = [nxt for _, nxt, _ in timer_samples]
    assert len(set(timers)) >= 5, f"Timer appeared static across samples: {timers}"


# -----------------------------------------------------------------------------
# 3. High-Concurrency Stress Probing on /api/v1/execution/status
# -----------------------------------------------------------------------------


async def _run_execution_status_concurrent(concurrency: int = 50) -> None:
    async with httpx.AsyncClient(base_url=LIVE_BASE_URL, timeout=15.0) as client:
        start_t = time.perf_counter()
        tasks = [
            client.get(f"/api/v1/execution/status?_req={i}&_ts={int(time.time() * 1000)}")
            for i in range(concurrency)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.perf_counter() - start_t

    assert len(responses) == concurrency
    failures = [
        r for r in responses
        if isinstance(r, Exception) or (isinstance(r, httpx.Response) and r.status_code != 200)
    ]
    assert len(failures) == 0, f"Encountered {len(failures)} failures: {failures[:3]}"

    for i, resp in enumerate(responses):
        assert isinstance(resp, httpx.Response)
        data = resp.json()
        assert data.get("verified") is True, f"Req {i}: verified is False"
        assert data.get("aggregate_exposure_usdt") == 0.0, f"Req {i}: aggregate exposure not 0.0"

        # Mathematical Solvency Invariants
        solvency = data.get("solvency", {})
        assert solvency.get("zero_balance_drift_verified") is True, f"Req {i}: zero drift unverified"
        drift = float(solvency.get("drift_usdt", 999.0))
        assert abs(drift) < 1e-15, f"Req {i}: drift |{drift}| >= 1e-15 USDT violation!"
        assert float(solvency.get("cash_reserve_pct", 0.0)) == 100.0
        assert float(solvency.get("starting_equity_usdt", 0.0)) == 100.0
        assert float(solvency.get("cash_usdt", 0.0)) == 100.0
        assert float(solvency.get("allocated_margin_usdt", 0.0)) == 0.0
        assert float(solvency.get("unrealized_pnl_usdt", 0.0)) == 0.0

        # Exact double-entry conservation:
        # Cash + Allocated Margin + Unrealized PnL == Starting Equity + Realized PnL
        lhs = solvency["cash_usdt"] + solvency["allocated_margin_usdt"] + solvency["unrealized_pnl_usdt"]
        rhs = solvency["starting_equity_usdt"] + solvency["realized_pnl_usdt"]
        assert abs(lhs - rhs) < 1e-15, f"Req {i}: Double-entry balance equality violated: {lhs} != {rhs}"

        # 8-Pair Universe in Positions
        positions = data.get("positions", {})
        for sym in EXPECTED_8_PAIRS:
            assert sym in positions, f"Req {i}: missing {sym} in positions: {positions}"
            pos = positions[sym]
            assert pos.get("position_qty") == 0.0, f"Req {i}: {sym} position_qty != 0.0: {pos}"
            assert pos.get("allocated_exposure_usdt") == 0.0, f"Req {i}: {sym} allocated_exposure_usdt != 0.0"
            assert "STANDBY" in str(pos.get("state", ""))

    assert elapsed < 10.0, f"Total execution time was {elapsed:.2f}s (> 10s)"


def test_execution_status_concurrent_load_and_exact_zero_drift() -> None:
    """Stress-test /api/v1/execution/status with 50 concurrent requests: 8 pairs and exact zero drift."""
    asyncio.run(_run_execution_status_concurrent(50))


# -----------------------------------------------------------------------------
# 4. Mixed Interleaved Load Burst Across Multiple Endpoints
# -----------------------------------------------------------------------------


async def _run_mixed_endpoints_interleaved(total_calls: int = 60) -> None:
    endpoints = [
        "/api/v1/canary/evolution",
        "/api/v1/execution/status",
        "/api/v1/market/prices",
        "/health",
    ]
    async with httpx.AsyncClient(base_url=LIVE_BASE_URL, timeout=15.0) as client:
        tasks = [
            client.get(f"{endpoints[i % len(endpoints)]}?_b={i}&_ts={int(time.time() * 1000)}")
            for i in range(total_calls)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    assert len(responses) == total_calls
    for i, r in enumerate(responses):
        assert isinstance(r, httpx.Response), f"Call {i} failed with exception: {r}"
        assert r.status_code == 200, f"Call {i} returned status {r.status_code}"


def test_mixed_endpoints_interleaved_burst() -> None:
    """Interleaved concurrent burst across evolution, execution, prices, and health endpoints."""
    asyncio.run(_run_mixed_endpoints_interleaved(60))


# -----------------------------------------------------------------------------
# 5. VPS Trader Daemon Continuity & Zero Restarts (Strict PID 87549)
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not SSH_KEY_PATH.exists(), reason="Kainode VPS SSH key missing")
class TestVPSTraderDaemonContinuityAdversarial:
    """Rigorous independent verification of continuous trader daemon PID 87549 on Kainode VPS."""

    def test_daemon_systemd_properties_strict_pid_and_zero_restarts(self) -> None:
        """Verify autonomous-futures-trader.service Main PID is strictly 87549 and NRestarts=0."""
        proc = run_ssh(
            "systemctl --user show autonomous-futures-trader.service "
            "--property=MainPID,NRestarts,ActiveState,SubState,Result"
        )
        assert proc.returncode == 0, f"systemctl query failed: {proc.stderr}"
        stdout = proc.stdout
        assert "MainPID=87549" in stdout, f"MainPID violation! Expected 87549, got: {stdout}"
        assert "NRestarts=0" in stdout, f"NRestarts violation! Expected 0, got: {stdout}"
        assert "ActiveState=active" in stdout, f"Not active: {stdout}"
        assert "SubState=running" in stdout, f"Not running: {stdout}"
        assert "Result=success" in stdout, f"Result not success: {stdout}"

    def test_daemon_linux_process_table_multi_day_continuous_execution(self) -> None:
        """Verify PID 87549 exists in Linux ps table with multi-day continuous elapsed time."""
        proc = run_ssh("ps -p 87549 -o pid,ppid,user,etime,args --no-headers")
        assert proc.returncode == 0, f"ps query failed: {proc.stderr}"
        stdout = proc.stdout.strip()
        assert "87549" in stdout, f"PID 87549 missing from process table: {stdout}"
        assert "run_phase_310_real_autonomous_trading.py" in stdout
        # etime must contain multi-day indicator (e.g., '2-')
        assert "1-" in stdout or "2-" in stdout or "3-" in stdout, (
            f"Expected multi-day elapsed time in ps table, got: {stdout}"
        )

    def test_daemon_journalctl_zero_crashes_or_tracebacks(self) -> None:
        """Verify trader daemon journalctl contains zero unhandled tracebacks or fatal crashes."""
        proc = run_ssh(
            "journalctl --user -u autonomous-futures-trader.service --since '2026-10-09 02:30:00' "
            "| grep -iE 'traceback|unhandled exception|fatal error' | head -n 10"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == "", f"Found unexpected fatal tracebacks in logs: {proc.stdout}"

    def test_web_service_is_active_and_serving(self) -> None:
        """Verify autonomous-futures-web.service is running cleanly."""
        proc = run_ssh(
            "systemctl --user show autonomous-futures-web.service "
            "--property=ActiveState,SubState,Result"
        )
        assert proc.returncode == 0
        assert "ActiveState=active" in proc.stdout
        assert "SubState=running" in proc.stdout
        assert "Result=success" in proc.stdout


# -----------------------------------------------------------------------------
# 6. Production Frontend Assets Verification
# -----------------------------------------------------------------------------


def test_production_frontend_serves_phase315_assets() -> None:
    """Verify live web dashboard serves the compiled production bundle without error."""
    client = httpx.Client(base_url=LIVE_BASE_URL, timeout=10.0)
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert '<div id="root"></div>' in html
    assert (
        "index-DOERVwn7.js" in html or "index-BRnwio6R.js" in html
    ), f"Latest JS chunk not referenced: {html[:500]}"
    assert (
        "index-i0I7q7Kx.css" in html or "index-YhmaWQb1.css" in html
    ), f"Latest CSS chunk not referenced: {html[:500]}"

    # Verify script chunk is reachable and substantial
    js_bundle = "index-DOERVwn7.js" if "index-DOERVwn7.js" in html else "index-BRnwio6R.js"
    resp_js = client.get(f"/assets/{js_bundle}")
    assert resp_js.status_code == 200
    assert len(resp_js.content) > 500_000
    assert "javascript" in resp_js.headers.get("content-type", "").lower()
    client.close()
