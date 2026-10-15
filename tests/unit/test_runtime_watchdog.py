from __future__ import annotations

import json
import time
from pathlib import Path

from autonomous_futures.execution.runtime_watchdog import (
    evaluate_runtime_watchdog,
    write_watchdog_report,
)
from scripts.check_qualified_runtime_health import main as watchdog_cli_main


def _write_runtime_fixtures(
    storage_dir: Path,
    *,
    now_ms: int,
    reconciled: bool = True,
    daily_loss_usdt: str = "0.00",
    daily_breached: bool = False,
    market_connected: bool = True,
    user_stream_connected: bool = True,
    spectral_radius: float = 0.3125,
    boundary_symbols: list[str] | None = None,
) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "exchange-account.json").write_text(
        json.dumps(
            {
                "timestamp_ms": now_ms,
                "testnet": True,
                "account": {
                    "totalWalletBalance": "497.43841186",
                    "totalMarginBalance": "497.43841186",
                    "availableBalance": "497.43841186",
                    "totalInitialMargin": "0.0",
                    "totalUnrealizedProfit": "0.0",
                },
                "positions": [],
                "open_orders": [],
                "reconciliation": {
                    "verified": reconciled,
                    "starting_equity": "500.0",
                    "net_realized_pnl": "-2.56158814",
                    "wallet_drift": "0" if reconciled else "1.25",
                    "equity_drift": "0" if reconciled else "1.25",
                },
                "daily_risk": {
                    "verified": True,
                    "observed_ms": now_ms,
                    "equity_basis": "ACCOUNT",
                    "day_start_equity": "497.43841186",
                    "limit_pct": "5.0",
                    "limit_usdt": "24.87192059",
                    "loss_usdt": daily_loss_usdt,
                    "remaining_usdt": "24.87192059",
                    "breached": daily_breached,
                },
            }
        ),
        encoding="utf-8",
    )
    (storage_dir / "runtime-health.json").write_text(
        json.dumps(
            {
                "source": "runtime_observation",
                "timestamp_ms": now_ms,
                "last_protective_cycle_ms": now_ms,
                "cycle_error_type": None,
                "last_account_refresh_error_type": None,
                "scan_error_type": None,
                "market_connected": market_connected,
                "market_error_type": None,
                "user_stream_connected": user_stream_connected,
                "user_stream_reconciliation_required": False,
                "user_stream_entry_block_reason": None,
                "user_stream_error_type": None,
                "user_stream_last_event_type": "ORDER_TRADE_UPDATE",
                "user_stream_event_count": 4,
                "user_stream_gap": False,
                "force_flatten_reason": None,
                "market_generation": 1,
                "microstructure": {
                    "calibration_window_ms": 21_600_000,
                    "arrival_count": 32,
                    "fit_error": None,
                    "calibration": {"beta_per_second": 0.25},
                    "fit": {
                        "spectral_radius": spectral_radius,
                        "beta_per_second": 0.25,
                        "baseline_boundary_symbols": boundary_symbols or [],
                        "event_counts": {"SOLUSDT": 14, "ETHUSDT": 10, "AVAXUSDT": 8},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    variants = [
        {
            "member_id": mid,
            "symbol": sym,
            "tier": tier,
            "close_price": 100.0,
            "ema20": 101.0,
            "atr14": 1.0,
            "dist_atr": -1.0,
            "price_below_ema20_atr": 1.0,
            "distance_threshold": -3.5,
            "dist_triggered": False,
            "relative_volume": 0.9,
            "vol_spike_multiplier": 2.0,
            "vol_triggered": False,
            "rsi_14": 44.0,
            "rsi_threshold": 30.0,
            "rsi_triggered": False,
            "macro_regime": "BULLISH",
            "macro_aligned": True,
            "gates_passed": 1,
            "gates_total": 4,
            "signal_ready": False,
        }
        for mid, sym, tier in (
            ("avax-1-hf-d-3.5-tp6.0-sl10.0", "AVAXUSDT", "HF"),
            ("eth-1-deep-d-4.0-tp10.0-sl6.0", "ETHUSDT", "DEEP"),
            ("eth-2-med-d-3.5-tp10.0-sl8.0", "ETHUSDT", "MED"),
            ("eth-3-hf-d-3.0-tp12.0-sl12.0", "ETHUSDT", "HF"),
            ("sol-1-deep-d-4.0-tp3.0-sl3.0", "SOLUSDT", "DEEP"),
            ("sol-2-hf-d-1.8-tp8.0-sl10.0", "SOLUSDT", "HF"),
        )
    ]
    (storage_dir / "portfolio-scanner-state.json").write_text(
        json.dumps(
            {
                "schema": "portfolio-scanner-state-v1",
                "source": "qualified_runtime_scanner",
                "portfolio_id": "macro-scalper-uninspected-3sym-medium-frequency-v1",
                "evaluated_at_ms": now_ms,
                "btc_regime": "BULLISH",
                "variants": variants,
            }
        ),
        encoding="utf-8",
    )


def test_evaluate_runtime_watchdog_healthy(tmp_path: Path) -> None:
    now_ms = int(time.time() * 1000)
    _write_runtime_fixtures(tmp_path, now_ms=now_ms)

    report = evaluate_runtime_watchdog(tmp_path, now_ms=now_ms)
    assert report["schema"] == "qualified-runtime-watchdog-v1"
    assert report["status"] == "HEALTHY"
    assert report["healthy"] is True
    assert report["critical_alerts"] == []
    assert report["warning_alerts"] == []
    assert len(report["watchdog_hash"]) == 64
    assert report["checks"]["account_reconciliation"]["passed"] is True
    assert report["checks"]["daily_risk_budget"]["passed"] is True
    assert report["checks"]["streams_and_hawkes"]["passed"] is True
    assert report["checks"]["portfolio_scanner"]["passed"] is True

    persisted = write_watchdog_report(tmp_path, report)
    assert persisted.is_file()
    loaded = json.loads(persisted.read_text(encoding="utf-8"))
    assert loaded["watchdog_hash"] == report["watchdog_hash"]


def test_evaluate_runtime_watchdog_warning_alerts(tmp_path: Path) -> None:
    now_ms = int(time.time() * 1000)
    _write_runtime_fixtures(
        tmp_path,
        now_ms=now_ms,
        daily_loss_usdt="15.00",
        boundary_symbols=["ETHUSDT", "AVAXUSDT"],
    )

    report = evaluate_runtime_watchdog(tmp_path, now_ms=now_ms)
    assert report["status"] == "WARNING"
    assert report["healthy"] is False
    assert report["critical_alerts"] == []
    assert any(a.startswith("daily_loss_budget_high:") for a in report["warning_alerts"])
    assert "hawkes_baseline_boundary_symbols:ETHUSDT,AVAXUSDT" in report["warning_alerts"]
    assert report["checks"]["streams_and_hawkes"]["passed"] is True


def test_evaluate_runtime_watchdog_critical_alerts(tmp_path: Path) -> None:
    now_ms = int(time.time() * 1000)
    _write_runtime_fixtures(
        tmp_path,
        now_ms=now_ms,
        daily_breached=True,
        user_stream_connected=False,
        spectral_radius=1.04,
    )

    report = evaluate_runtime_watchdog(tmp_path, now_ms=now_ms)
    assert report["status"] == "CRITICAL"
    assert report["healthy"] is False
    assert "daily_loss_limit_breached" in report["critical_alerts"]
    assert "user_data_stream_disconnected" in report["critical_alerts"]
    assert "hawkes_spectral_radius_supercritical:1.0400" in report["critical_alerts"]
    assert report["checks"]["daily_risk_budget"]["passed"] is False
    assert report["checks"]["streams_and_hawkes"]["passed"] is False


def test_cli_check_qualified_runtime_health_exit_codes(tmp_path: Path) -> None:
    now_ms = int(time.time() * 1000)
    _write_runtime_fixtures(tmp_path, now_ms=now_ms)

    rc_healthy = watchdog_cli_main(["--storage-dir", str(tmp_path), "--write-report"])
    assert rc_healthy == 0
    assert (tmp_path / "watchdog-report.json").is_file()

    _write_runtime_fixtures(
        tmp_path,
        now_ms=now_ms,
        boundary_symbols=["ETHUSDT"],
    )
    rc_warn_allowed = watchdog_cli_main(["--storage-dir", str(tmp_path)])
    assert rc_warn_allowed == 0
    rc_warn_strict = watchdog_cli_main(["--storage-dir", str(tmp_path), "--fail-on-warning"])
    assert rc_warn_strict == 1


def test_watchdog_systemd_units_and_cached_systemd_report(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    svc_path = repo / "deploy" / "systemd" / "autonomous-futures-watchdog.service"
    timer_path = repo / "deploy" / "systemd" / "autonomous-futures-watchdog.timer"
    svc_text = svc_path.read_text(encoding="utf-8")
    timer_text = timer_path.read_text(encoding="utf-8")

    assert "Type=oneshot" in svc_text
    assert "scripts/check_qualified_runtime_health.py" in svc_text
    assert "--check-systemd --write-report" in svc_text
    assert "NoNewPrivileges=true" in svc_text
    assert "OnUnitActiveSec=60s" in timer_text
    assert "Unit=autonomous-futures-watchdog.service" in timer_text

    now_ms = int(time.time() * 1000)
    _write_runtime_fixtures(tmp_path, now_ms=now_ms)
    write_watchdog_report(
        tmp_path,
        {
            "schema": "qualified-runtime-watchdog-v1",
            "evaluated_at_ms": now_ms,
            "status": "HEALTHY",
            "healthy": True,
            "checks": {
                "systemd": {
                    "passed": True,
                    "legacy_writer": {"inactive": True},
                    "qualified_runtime": {
                        "ActiveState": "active",
                        "SubState": "running",
                        "MainPID": "63408",
                        "NRestarts": "0",
                    },
                }
            },
        },
    )
    report = evaluate_runtime_watchdog(tmp_path, now_ms=now_ms, check_systemd=False)
    assert report["checks"]["systemd"]["passed"] is True
    assert report["checks"]["systemd"]["cached_from_report"] is True
    assert report["checks"]["systemd"]["qualified_runtime"]["MainPID"] == "63408"

