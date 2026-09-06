"""Unit tests for Phase 259 24/7 Live Paper Daemon CLI, invariants, and checkpointing."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repo root is on path for scripts
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.run_phase_259_live_paper_daemon as daemon_mod  # noqa: E402


def test_daemon_arg_parser_defaults() -> None:
    parser = daemon_mod.build_arg_parser()
    args = parser.parse_args([])
    assert args.duration is None
    assert args.smoke_test is False
    assert args.storage_dir == Path("artifacts/paper_live")
    assert args.starting_capital == Decimal("100.00")
    assert "BTCUSDT" in args.symbols
    assert "ETHUSDT" in args.symbols
    assert "SOLUSDT" in args.symbols
    assert "DOGEUSDT" in args.symbols
    assert args.checkpoint_interval == 30.0


def test_daemon_arg_parser_custom_and_smoke_test() -> None:
    args = daemon_mod.parse_cli_args(
        [
            "--smoke-test",
            "--storage-dir",
            "/tmp/test_paper",
            "--starting-capital",
            "100.00",
            "--checkpoint-interval",
            "5.0",
        ]
    )
    assert args.smoke_test is True
    assert args.duration == 10.0  # Smoke test defaults to 10s if not specified
    assert args.storage_dir == Path("/tmp/test_paper")
    assert args.checkpoint_interval == 5.0


def test_daemon_arg_parser_validation_negative_capital() -> None:
    with pytest.raises(SystemExit):
        daemon_mod.parse_cli_args(["--starting-capital", "-50.00"])


def test_daemon_arg_parser_validation_negative_duration() -> None:
    with pytest.raises(SystemExit):
        daemon_mod.parse_cli_args(["--duration", "-5"])


def test_verify_strict_safety_invariants_clean() -> None:
    with patch.dict("os.environ", {}, clear=True):
        invariants = daemon_mod.verify_strict_safety_invariants(orders_submitted=0)
        assert invariants["orders_submitted"] == 0
        assert invariants["execution_authority"] is False
        assert invariants["promotion_state"] == "unpromoted"
        assert invariants["live_trading_activation"] is False
        assert invariants["paper_activation"] is True
        assert invariants["api_keys_loaded"] == 0
        assert invariants["zero_secret_leakage"] is True


def test_verify_strict_safety_invariants_order_violation() -> None:
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION: orders submitted"):
        daemon_mod.verify_strict_safety_invariants(orders_submitted=1)


def test_verify_strict_safety_invariants_credential_violation() -> None:
    with patch.dict("os.environ", {"BINANCE_API_KEY": "fake_key"}):
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION: private credentials detected"):
            daemon_mod.verify_strict_safety_invariants(orders_submitted=0)


def test_emit_daemon_health_checkpoint(tmp_path: Path) -> None:
    health_file = tmp_path / "paper-daemon-health.json"
    daemon_mod.emit_daemon_health_checkpoint(
        output_path=health_file,
        status="RUNNING",
        uptime_seconds=42.5,
        started_at="2026-09-06T05:00:00Z",
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"],
        starting_capital=Decimal("100.00"),
        current_cash=Decimal("100.00"),
        current_equity=Decimal("100.00"),
        margin_utilization_pct=0.0,
        reserve_buffer_pct=100.0,
        active_positions={},
        total_trades=0,
        circuit_breaker_status="NORMAL",
        feed_messages_received=1500,
        reconnect_count=0,
    )

    assert health_file.exists()
    data = json.loads(health_file.read_text(encoding="utf-8"))
    assert data["daemon_status"] == "RUNNING"
    assert data["uptime_seconds"] == 42.5
    assert data["starting_capital_usdt"] == "100.00"
    assert data["current_cash_usdt"] == "100.00"
    assert data["circuit_breaker_status"] == "NORMAL"
    assert data["feed_messages_received"] == 1500
    assert data["zero_order_safety_invariants"]["orders_submitted"] == 0
    assert data["zero_order_safety_invariants"]["execution_authority"] is False
