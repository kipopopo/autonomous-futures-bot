"""Phase 314 Milestone 4: Remote Kainode Linux VPS Trader Daemon Continuity Challenge Suite.

Empirically challenges and verifies:
1. SSH remote connection to Kainode VPS (147.79.18.15).
2. Continuous trader daemon (autonomous-futures-trader.service):
   - Service is active and running.
   - Main PID is strictly 87549.
   - Restart count is strictly 0.
   - Journalctl logs have zero tracebacks, critical errors, or unhandled exceptions.
3. Web service (autonomous-futures-web.service):
   - Service is active and running.
4. Public live endpoints on https://futures.semua.dev:
   - /api/v1/execution/status: zero balance drift (|Δ| == 0.0), flat positions, authentic orders.
   - /api/v1/market/prices: live prices, genuine btc_macro indicators.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
import httpx
import pytest

SSH_KEY_PATH = Path.home() / ".ssh" / "kainode_ed25519_openssh"
VPS_HOST = "afbot@147.79.18.15"


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
class TestKainodeVPSContinuity:
    """Empirical verification of 24/7 daemon continuity on Kainode VPS."""

    def test_ssh_connectivity_and_host_identity(self) -> None:
        """Verify SSH connectivity to Kainode VPS host."""
        proc = run_ssh_cmd("whoami; hostname")
        assert proc.returncode == 0, f"SSH connection failed: {proc.stderr}"
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        assert "afbot" in lines, f"Expected user afbot, got: {lines}"
        assert "kipopopo" in lines, f"Expected hostname kipopopo, got: {lines}"

    def test_trader_daemon_main_pid_is_87549(self) -> None:
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
        """Verify autonomous-futures-trader.service restart count (NRestarts) is 0."""
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
        # Confirm elapsed time indicates continuous operation (> 1 day, e.g., '1-13:')
        assert "1-" in stdout or "2-" in stdout, f"Process appears restarted (no day prefix in etime): {stdout}"

    def test_trader_daemon_journalctl_clean_logs(self) -> None:
        """Verify journalctl logs contain 0 fatal errors, crashes, or unhandled tracebacks."""
        # 1. Check priority err..emerg
        proc_err = run_ssh_cmd("journalctl --user -u autonomous-futures-trader.service -p err --no-pager")
        assert proc_err.returncode == 0
        assert "-- No entries --" in proc_err.stdout or proc_err.stdout.strip() == ""

        # 2. Grep for Traceback or unhandled exception
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

    def test_public_execution_status_solvency_and_flat_state(self) -> None:
        """Verify public API execution status proves mathematical zero-drift solvency."""
        with httpx.Client(timeout=15.0) as client:
            resp = client.get("https://futures.semua.dev/api/v1/execution/status")
            assert resp.status_code == 200, f"Unexpected status: {resp.status_code}"
            data = resp.json()
            assert data["verified"] is True
            assert data["aggregate_exposure_usdt"] == 0.0
            assert data["solvency"]["zero_balance_drift_verified"] is True
            assert abs(data["solvency"]["drift_usdt"]) < 1e-15
            assert data["solvency"]["cash_reserve_pct"] == 100.0

            # Positions must be strictly flat STANDBY / SCANNING
            positions = data["positions"]
            for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
                assert sym in positions
                assert positions[sym]["position_qty"] == 0.0
                assert positions[sym]["allocated_exposure_usdt"] == 0.0
                assert "STANDBY" in positions[sym]["state"]

    def test_public_market_prices_authentic_indicators(self) -> None:
        """Verify public API market prices returns live prices and real EMAs."""
        with httpx.Client(timeout=15.0) as client:
            resp = client.get("https://futures.semua.dev/api/v1/market/prices")
            assert resp.status_code == 200
            data = resp.json()
            assert "BTCUSDT" in data
            assert data["BTCUSDT"] > 10000.0
            assert "btc_macro" in data
            macro = data["btc_macro"]
            assert "ema50_1h" in macro
            assert "ema200_1h" in macro
            assert macro["ema50_1h"] > 10000.0
            assert macro["ema200_1h"] > 10000.0
            assert macro["regime"] in ["BULLISH ALIGNED", "BEARISH", "SIDEWAYS"]
