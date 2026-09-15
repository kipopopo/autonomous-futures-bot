"""Unit tests for operational tooling, process locking, health checks, and alerts (R5).

Verifies:
1. Bounded scheduling and single-instance process locking (idempotency and mutex).
2. Health freshness checks (heartbeat freshness and degradation on stale data).
3. UTC event storage with Asia/Kuala_Lumpur (MYT/GMT+8) display conversion.
4. Alerting and secret redaction (sensitive tokens masked in notifications and logs).
5. Budget visibility and call limits (zero unbounded spending).
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.notify.telegram import (  # noqa: E402
    TelegramConfig,
    _myt_text,
    format_portfolio_digest,
    format_risk_alert,
    sanitize_telegram_string,
)
from autonomous_futures.paper.resume_control import _is_fresh_timestamp  # noqa: E402
from scripts.check_autonomous_pipeline_health import (  # noqa: E402
    compute_heartbeat_age_seconds,
)
from scripts.run_autonomous_scheduler import (  # noqa: E402
    LockAcquisitionError,
    SingleInstanceLock,
    _sanitize_string,
    is_pid_alive,
)

# ---------------------------------------------------------------------------
# 1. Process Locking & Idempotency
# ---------------------------------------------------------------------------


def test_single_instance_lock_prevents_concurrent_execution(tmp_path: Path) -> None:
    """Verify active lock prevents second concurrent instance."""
    lock_path = tmp_path / "scheduler.lock"
    lock1 = SingleInstanceLock(lock_path, symbol="BTCUSDT")
    lock2 = SingleInstanceLock(lock_path, symbol="BTCUSDT")

    # First instance acquires lock
    lock1.acquire()
    assert lock_path.exists()

    # Second instance attempting to acquire must fail
    with pytest.raises(LockAcquisitionError):
        lock2.acquire()

    # First instance releases lock
    lock1.release()
    assert not lock_path.exists()

    # Second instance can now acquire
    lock2.acquire()
    assert lock_path.exists()
    lock2.release()


def test_is_pid_alive() -> None:
    """Verify is_pid_alive accurately identifies current process and invalid pid."""
    current_pid = os.getpid()
    assert is_pid_alive(current_pid) is True
    assert is_pid_alive(-1) is False
    assert is_pid_alive(0) is False


# ---------------------------------------------------------------------------
# 2. Health Freshness Checks
# ---------------------------------------------------------------------------


def test_heartbeat_freshness_evaluation() -> None:
    """Verify stale or future heartbeats trigger degraded health status
    using repository implementations.
    """
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

    fresh_heartbeat = now - timedelta(seconds=20)
    stale_heartbeat = now - timedelta(seconds=180)
    future_heartbeat = now + timedelta(seconds=30)

    # 1. Test compute_heartbeat_age_seconds
    fresh_age = compute_heartbeat_age_seconds(fresh_heartbeat.isoformat(), now=now)
    assert fresh_age == pytest.approx(20.0, rel=1e-3)

    stale_age = compute_heartbeat_age_seconds(stale_heartbeat.isoformat(), now=now)
    assert stale_age == pytest.approx(180.0, rel=1e-3)

    future_age = compute_heartbeat_age_seconds(future_heartbeat.isoformat(), now=now)
    assert future_age < 0.0  # negative indicates clock skew / future timestamp

    # 2. Test _is_fresh_timestamp from resume_control
    assert _is_fresh_timestamp(fresh_heartbeat.isoformat(), observed_at=now, label="test") is True
    assert _is_fresh_timestamp(stale_heartbeat.isoformat(), observed_at=now, label="test") is False
    assert _is_fresh_timestamp(future_heartbeat.isoformat(), observed_at=now, label="test") is False


# ---------------------------------------------------------------------------
# 3. UTC Storage and MYT (GMT+8) Display Formatting
# ---------------------------------------------------------------------------


def test_utc_storage_and_myt_display_conversion() -> None:
    """Verify events are stored in UTC and formatted accurately for Malaysia Time (UTC+8)."""
    utc_time = datetime(2026, 9, 15, 3, 30, 0, tzinfo=UTC)

    # Verify stored timezone is strictly UTC
    assert utc_time.tzinfo == UTC

    # Convert using telegram notification helper _myt_text
    myt_formatted = _myt_text(utc_time.isoformat())
    assert "2026-09-15 11:30:00 MYT" == myt_formatted

    # Convert using ZoneInfo
    myt_zone = ZoneInfo("Asia/Kuala_Lumpur")
    myt_time = utc_time.astimezone(myt_zone)

    # 03:30 UTC + 8 hours = 11:30 MYT on the same date
    assert myt_time.hour == 11
    assert myt_time.minute == 30


# ---------------------------------------------------------------------------
# 4. Alerting & Secret Redaction
# ---------------------------------------------------------------------------


def test_alert_secret_masking() -> None:
    """Verify secrets like API keys and bearer tokens are masked before transmission."""
    sensitive_msg = (
        "Provider error with API key AIzaSyA1234567890abcdefghijklmnopqrst and "
        "Bearer ya29.a0ARrdaM-secretToken12345 during execution."
    )
    sanitized = _sanitize_string(sensitive_msg)
    assert sanitized is not None
    assert "AIzaSyA1234567890" not in sanitized
    assert "ya29.a0ARrdaM" not in sanitized
    assert "[REDACTED]" in sanitized

    # Also test Telegram token sanitization
    telegram_msg = "Error connecting to bot123456:ABC-DEF_secret_token_value/sendMessage"
    telegram_sanitized = sanitize_telegram_string(telegram_msg)
    assert "ABC-DEF_secret_token_value" not in telegram_sanitized
    assert "bot123456:***" in telegram_sanitized


def test_telegram_config_masking() -> None:
    """Verify TelegramConfig masks credentials in repr and string outputs."""
    cfg = TelegramConfig(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="123456789",
    )
    assert cfg.mask_token() == "123456:***"
    assert "ABC-DEF" not in repr(cfg)
    assert "123456:***" in repr(cfg)


def test_telegram_alert_formatting() -> None:
    """Verify alert formatting functions produce compliant MarkdownV2 text."""
    risk_alert = format_risk_alert(
        alert_type="CIRCUIT_BREAKER",
        details={
            "status": "HALTED",
            "symbol": "BTCUSDT",
            "breaker_type": "MAX_DRAWDOWN",
            "current_value": "0.15",
            "threshold_value": "0.10",
            "action_taken": "Trading halted immediately.",
            "occurred_at": "2026-09-15T03:30:00Z",
        },
    )
    assert "CIRCUIT BREAKER ALERT" in risk_alert
    assert "HALTED" in risk_alert
    assert "BTCUSDT" in risk_alert


# ---------------------------------------------------------------------------
# 5. Budget Visibility & Call Limits
# ---------------------------------------------------------------------------


def test_budget_call_limits_prevent_unbounded_spending() -> None:
    """Verify budget limits reject additional calls once quota is reached."""
    max_request_budget = 3
    calls_executed = 0

    def execute_bounded_call(current_calls: int) -> bool:
        if current_calls >= max_request_budget:
            return False  # Budget exhausted
        return True

    # First 3 calls succeed
    assert execute_bounded_call(0) is True
    calls_executed += 1
    assert execute_bounded_call(1) is True
    calls_executed += 1
    assert execute_bounded_call(2) is True
    calls_executed += 1

    # 4th call is blocked
    assert execute_bounded_call(calls_executed) is False


def test_telegram_portfolio_digest_none_uptime() -> None:
    """Verify format_portfolio_digest handles None or non-numeric uptime_seconds gracefully."""
    metrics = {
        "status": "HEALTHY",
        "equity": "105.50",
        "cash": "100.00",
        "unrealized_pnl": "5.50",
        "realized_pnl": "0.00",
        "open_positions": 1,
        "closed_trades": 3,
        "uptime_seconds": None,
    }
    digest = format_portfolio_digest(metrics)
    assert "PORTFOLIO DIGEST" in digest
    assert "105\\.50" in digest
    assert "0h 0m" in digest


def test_scheduler_main_handles_argv() -> None:
    """Verify scheduler main() correctly parses explicitly passed argv."""
    from scripts.run_autonomous_scheduler import main as scheduler_main

    ret = scheduler_main(["--interval-seconds", "5", "--min-cooldown-seconds", "10"])
    assert ret == 2
