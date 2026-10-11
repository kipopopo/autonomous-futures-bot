"""Phase 315 Milestone 5: Kainode Linux VPS Hot-Sync & Zero-Disruption Daemon Continuity Challenge.

Empirically challenges and verifies:
1. SSH remote connection to Kainode VPS (147.79.18.15) as afbot@kipopopo.
2. Continuous trader daemon (autonomous-futures-trader.service):
   - Service is active and running.
   - Main PID is strictly 87549.
   - Restart count (NRestarts) is strictly 0.
   - Process table indicates continuous multi-day execution without restarts.
   - Journalctl logs contain zero tracebacks or unhandled exceptions.
3. Web service (autonomous-futures-web.service):
   - Service is active and running.
4. Live production public endpoints on https://futures.semua.dev:
   - GET /health: HTTP 200, service healthy.
   - GET /: HTTP 200, serving the Phase 315 production bundle with active script and css tags.
   - GET /assets/index-BRnwio6R.js & /assets/index-YhmaWQb1.css: HTTP 200, non-empty production assets.
   - GET /api/v1/market/prices: HTTP 200, all 8 perpetual pairs present with genuine mark prices and authentic btc_macro indicators.
   - GET /api/v1/market/klines: HTTP 200, structured OHLCV records for candidate pairs.
   - GET /api/v1/execution/status: HTTP 200, zero balance drift (|Delta| < 10^-15 USDT), full 100% cash reserve, and all 8 pairs in positions dictionary.
   - GET /api/v1/canary/evolution: HTTP 200, dynamic 5-stage state machine, 15s scan cycle, sample scorecard (0/5), and macro gating explanations.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

SSH_KEY_PATH = Path.home() / ".ssh" / "kainode_ed25519_openssh"
VPS_HOST = "afbot@147.79.18.15"
BASE_URL = "https://futures.semua.dev"

EXPECTED_UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
]

VALID_CYCLE_STAGES = [
    "INGRESS",
    "HEALTH_EVALUATION",
    "TRADE_AUTOPSY",
    "MUTATION_STAGING",
    "SHADOW_OOS_GATE",
    "SHADOW_VALIDATION",
]


def run_ssh_cmd(command: str) -> subprocess.CompletedProcess[str]:
    """Execute SSH command on Kainode VPS."""
    full_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-i", str(SSH_KEY_PATH),
        VPS_HOST,
        command,
    ]
    return subprocess.run(full_cmd, capture_output=True, text=True, check=False)


@pytest.mark.skipif(not SSH_KEY_PATH.exists(), reason="Kainode SSH key not present on host")
class TestKainodeVPSContinuityPhase315:
    """Empirical verification of 24/7 daemon continuity on Kainode VPS."""

    def test_ssh_connectivity_and_host_identity(self) -> None:
        """Verify SSH connectivity to Kainode VPS host."""
        proc = run_ssh_cmd("whoami; hostname")
        assert proc.returncode == 0, f"SSH connection failed: {proc.stderr}"
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        assert "afbot" in lines, f"Expected user afbot, got: {lines}"
        assert "kipopopo" in lines, f"Expected hostname kipopopo, got: {lines}"

    def test_trader_daemon_main_pid_is_strictly_87549(self) -> None:
        """Verify autonomous-futures-trader.service Main PID is strictly 87549."""
        proc = run_ssh_cmd(
            "systemctl --user show autonomous-futures-trader.service --property=MainPID,ActiveState,SubState"
        )
        assert proc.returncode == 0, f"systemctl query failed: {proc.stderr}"
        output = proc.stdout
        assert "ActiveState=active" in output, f"Service not active: {output}"
        assert "SubState=running" in output, f"Service not running: {output}"
        assert "MainPID=87549" in output, f"Expected MainPID=87549, got: {output}"

    def test_trader_daemon_restart_count_is_zero(self) -> None:
        """Verify autonomous-futures-trader.service restart count (NRestarts) is strictly 0."""
        proc = run_ssh_cmd(
            "systemctl --user show autonomous-futures-trader.service --property=NRestarts,Result"
        )
        assert proc.returncode == 0, f"systemctl query failed: {proc.stderr}"
        output = proc.stdout
        assert "NRestarts=0" in output, f"Expected NRestarts=0, got: {output}"
        assert "Result=success" in output, f"Expected Result=success, got: {output}"

    def test_trader_daemon_proc_table_continuity(self) -> None:
        """Verify PID 87549 in Linux process table with > 1 day elapsed time."""
        proc = run_ssh_cmd("ps -p 87549 -o pid,ppid,user,etime,args --no-headers")
        assert proc.returncode == 0, f"ps query failed: {proc.stderr}"
        stdout = proc.stdout.strip()
        assert "87549" in stdout, f"PID 87549 not found in ps table: {stdout}"
        assert "run_phase_310_real_autonomous_trading.py" in stdout
        assert "1-" in stdout or "2-" in stdout or "3-" in stdout, (
            f"Process appears restarted (no multi-day prefix in etime): {stdout}"
        )

    def test_trader_daemon_journalctl_clean_logs(self) -> None:
        """Verify journalctl logs contain 0 fatal errors, crashes, or unhandled tracebacks."""
        proc_err = run_ssh_cmd("journalctl --user -u autonomous-futures-trader.service -p err --no-pager")
        assert proc_err.returncode == 0
        assert "-- No entries --" in proc_err.stdout or proc_err.stdout.strip() == ""

        proc_grep = run_ssh_cmd(
            "journalctl --user -u autonomous-futures-trader.service --since '2026-10-09 02:30:00' | grep -iE 'traceback|unhandled exception' | head -n 10"
        )
        assert proc_grep.returncode == 0
        assert proc_grep.stdout.strip() == "", f"Found unexpected tracebacks: {proc_grep.stdout}"

    def test_web_service_active_and_running(self) -> None:
        """Verify autonomous-futures-web.service is active and healthy."""
        proc = run_ssh_cmd(
            "systemctl --user show autonomous-futures-web.service --property=Id,ActiveState,SubState,Result"
        )
        assert proc.returncode == 0, f"systemctl query failed: {proc.stderr}"
        output = proc.stdout
        assert "ActiveState=active" in output, f"Web service not active: {output}"
        assert "SubState=running" in output, f"Web service not running: {output}"
        assert "Result=success" in output, f"Web service result not success: {output}"


class TestLivePublicEndpointsPhase315:
    """Empirical verification of live public endpoints on https://futures.semua.dev."""

    @pytest.fixture
    def client(self) -> httpx.Client:
        return httpx.Client(base_url=BASE_URL, timeout=15.0)

    def test_live_health_endpoint(self, client: httpx.Client) -> None:
        """Verify /health returns HTTP 200 and healthy status."""
        resp = client.get("/health")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert data.get("status") == "ok"
        assert data.get("service") == "autonomous-futures-data-api"
        assert data.get("paper_safe") is True

    def test_live_root_serves_phase315_bundle(self, client: httpx.Client) -> None:
        """Verify root URL serves the newly deployed Phase 315 production bundle."""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert '<div id="root"></div>' in html
        assert 'data-theme="dark"' in html
        assert "index-BRnwio6R.js" in html, f"Expected latest script bundle in HTML: {html}"
        assert "index-YhmaWQb1.css" in html, f"Expected latest css bundle in HTML: {html}"

    def test_live_static_assets_retrieval(self, client: httpx.Client) -> None:
        """Verify static js and css assets are accessible and valid."""
        resp_js = client.get("/assets/index-BRnwio6R.js")
        assert resp_js.status_code == 200
        assert len(resp_js.content) > 500_000
        assert "javascript" in resp_js.headers.get("content-type", "").lower()

        resp_css = client.get("/assets/index-YhmaWQb1.css")
        assert resp_css.status_code == 200
        assert len(resp_css.content) > 100_000
        assert "css" in resp_css.headers.get("content-type", "").lower()

    def test_live_market_prices_8_pairs(self, client: httpx.Client) -> None:
        """Verify /api/v1/market/prices returns all 8 perpetual pairs and btc_macro."""
        resp = client.get(f"/api/v1/market/prices?_ts={int(time.time() * 1000)}")
        assert resp.status_code == 200
        data = resp.json()

        prices = data.get("prices", {})
        for sym in EXPECTED_UNIVERSE:
            assert sym in prices, f"Missing pair {sym} in prices: {prices}"
            assert float(prices[sym]) > 0.0, f"Non-positive price for {sym}: {prices[sym]}"
            assert sym in data, f"Missing top-level key {sym} in data"

        assert "btc_macro" in data
        macro = data["btc_macro"]
        assert "ema50_1h" in macro
        assert "ema200_1h" in macro
        assert float(macro["ema50_1h"]) > 10_000.0
        assert float(macro["ema200_1h"]) > 10_000.0
        assert macro["regime"] in ["BULLISH ALIGNED", "BEARISH", "SIDEWAYS"]

    def test_live_market_klines_ohlcv(self, client: httpx.Client) -> None:
        """Verify /api/v1/market/klines returns structured candlesticks for candidate pairs."""
        for sym in ["SOLUSDT", "DOGEUSDT", "BTCUSDT"]:
            resp = client.get(f"/api/v1/market/klines?symbol={sym}&interval=15m&limit=20")
            assert resp.status_code == 200, f"Klines failed for {sym}: {resp.status_code}"
            data = resp.json()
            assert isinstance(data, dict), f"Expected MarketKlinesResponse dict, got: {type(data)}"
            assert "candles" in data
            candles = data["candles"]
            assert isinstance(candles, list), f"Expected list of candles, got: {type(candles)}"
            assert len(candles) >= 10, f"Expected >= 10 candles for {sym}, got {len(candles)}"
            first_candle = candles[0]
            for field in ["timestamp", "open", "high", "low", "close", "volume"]:
                assert field in first_candle, f"Missing {field} in candle: {first_candle}"

    def test_live_execution_status_8_pairs_and_solvency(self, client: httpx.Client) -> None:
        """Verify /api/v1/execution/status proves mathematical solvency across all 8 pairs."""
        resp = client.get(f"/api/v1/execution/status?_ts={int(time.time() * 1000)}")
        assert resp.status_code == 200
        data = resp.json()

        assert data.get("verified") is True
        assert data.get("aggregate_exposure_usdt") == 0.0

        solvency = data.get("solvency", {})
        assert solvency.get("zero_balance_drift_verified") is True
        assert abs(float(solvency.get("drift_usdt", 999.0))) < 1e-15
        assert float(solvency.get("cash_reserve_pct", 0.0)) == 100.0

        positions = data.get("positions", {})
        for sym in EXPECTED_UNIVERSE:
            assert sym in positions, f"Missing pair {sym} in positions: {positions}"
            pos = positions[sym]
            assert pos.get("position_qty") == 0.0, f"{sym} position qty not 0.0: {pos}"
            assert pos.get("allocated_exposure_usdt") == 0.0
            assert "STANDBY" in str(pos.get("state", ""))

    def test_live_canary_evolution_dynamic_state_machine(self, client: httpx.Client) -> None:
        """Verify /api/v1/canary/evolution returns dynamic state machine and OOS gate metrics."""
        resp = client.get(f"/api/v1/canary/evolution?_ts={int(time.time() * 1000)}")
        assert resp.status_code == 200
        data = resp.json()

        assert data.get("verified") is True
        assert "live_progress" in data
        live_prog = data["live_progress"]

        assert live_prog.get("is_live_daemon_active") is True
        assert live_prog.get("daemon_pid") == 87549
        assert live_prog.get("current_cycle_stage") in VALID_CYCLE_STAGES
        assert float(live_prog.get("cycle_progress_pct", 0.0)) >= 80.0
        assert live_prog.get("stage_status") in [
            "WAITING_FOR_SAMPLES",
            "EVALUATING",
            "QUALIFIED",
        ]

        # Transparent OOS gate trade sample count
        assert live_prog.get("required_trades_count") == 5
        assert live_prog.get("closed_trades_count") >= 0
        # Dynamic 15s scan cycle countdown timer
        cycle_sec = live_prog.get("next_cycle_seconds")
        assert isinstance(cycle_sec, int) and 0 <= cycle_sec <= 15

        # Macro gating explanation
        assert "macro_gating_state" in live_prog
        macro_gate = live_prog["macro_gating_state"]
        assert macro_gate.get("regime") in ["BEARISH", "BULLISH_ALIGNED", "SIDEWAYS", "NEUTRAL"]
        assert isinstance(macro_gate.get("longs_filtered"), bool)
        assert len(macro_gate.get("explanation", "")) > 10
        assert len(macro_gate.get("explanation_ms", "")) > 10
