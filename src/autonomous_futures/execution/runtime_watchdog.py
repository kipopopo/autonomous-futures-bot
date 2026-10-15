"""Read-only runtime health and risk watchdog for the qualified portfolio executor.

Audits the durable runtime directory (`exchange-account.json`, `daily-risk.json`,
`runtime-health.json`, and `portfolio-scanner-state.json`) and optional systemd unit
state without mutating trading state or touching the active writer lease.
"""

from __future__ import annotations

import json
import subprocess
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.execution.account_evidence import (
    SNAPSHOT_NAME,
    atomic_json,
    finite_decimal,
)
from autonomous_futures.execution.portfolio_runtime import PORTFOLIO_SCANNER_STATE_NAME
from autonomous_futures.execution.single_writer_guard import LegacyWriterHandoffGuard
from autonomous_futures.research.runtime_qualification import content_hash


def _inspect_systemd_unit(unit_name: str) -> dict[str, str]:
    """Read systemd unit properties via user scope (or system scope fallback)."""
    props = ("Id", "LoadState", "UnitFileState", "ActiveState", "SubState", "MainPID", "NRestarts")
    prop_arg = ",".join(props)
    for cmd in (
        ["systemctl", "--user", "show", unit_name, f"--property={prop_arg}"],
        ["systemctl", "show", unit_name, f"--property={prop_arg}"],
    ):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0 and not proc.stdout.strip():
            continue
        parsed: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                parsed[k.strip()] = v.strip()
        if parsed.get("LoadState") and parsed.get("LoadState") != "not-found":
            return parsed
    return {"Id": unit_name, "LoadState": "unknown", "ActiveState": "unknown"}


def evaluate_runtime_watchdog(
    storage_dir: Path,
    *,
    now_ms: int | None = None,
    max_account_age_ms: int = 30_000,
    max_health_age_ms: int = 30_000,
    max_scanner_age_ms: int = 300_000,
    spectral_radius_warning: float = 0.85,
    spectral_radius_critical: float = 1.0,
    daily_loss_warning_ratio: float = 0.50,
    check_systemd: bool = False,
    qualified_service_name: str = "autonomous-futures-qualified-runtime.service",
) -> dict[str, Any]:
    """Audit runtime state artifacts and return a deterministic watchdog report."""
    eval_ms = now_ms if now_ms is not None else (time.time_ns() // 1_000_000)
    critical_alerts: list[str] = []
    warning_alerts: list[str] = []

    # 1. Account Reconciliation & Daily Risk Audit
    account_path = storage_dir / SNAPSHOT_NAME
    account_check: dict[str, Any] = {
        "path": str(account_path),
        "exists": account_path.is_file(),
        "fresh": False,
        "reconciled": False,
        "wallet_drift": None,
        "equity_drift": None,
        "total_equity_usdt": None,
        "available_balance_usdt": None,
        "open_positions_count": 0,
        "open_orders_count": 0,
        "passed": False,
    }
    daily_risk_check: dict[str, Any] = {
        "verified": False,
        "equity_basis": None,
        "day_start_equity_usdt": None,
        "loss_usdt": None,
        "limit_usdt": None,
        "remaining_usdt": None,
        "utilization_pct": None,
        "breached": None,
        "passed": False,
    }

    if not account_path.is_file():
        critical_alerts.append("account_snapshot_missing")
    else:
        try:
            raw_acc = json.loads(account_path.read_text(encoding="utf-8"))
            ts_ms = int(raw_acc.get("timestamp_ms", 0))
            age_ms = abs(eval_ms - ts_ms)
            is_fresh = age_ms <= max_account_age_ms
            account_check["timestamp_ms"] = ts_ms
            account_check["age_ms"] = age_ms
            account_check["fresh"] = is_fresh
            if not is_fresh:
                critical_alerts.append(f"account_snapshot_stale:{age_ms}ms")

            rec = raw_acc.get("reconciliation", {})
            if not isinstance(rec, dict):
                rec = {}
            w_drift = abs(finite_decimal(rec.get("wallet_drift", "1"))) if rec else Decimal("1")
            e_drift = abs(finite_decimal(rec.get("equity_drift", "1"))) if rec else Decimal("1")
            reconciled = (
                rec.get("verified") is True
                and w_drift < Decimal("1e-15")
                and e_drift < Decimal("1e-15")
            )
            account_check["reconciled"] = reconciled
            account_check["wallet_drift"] = str(w_drift) if rec else None
            account_check["equity_drift"] = str(e_drift) if rec else None
            if not reconciled:
                critical_alerts.append("account_reconciliation_unverified_or_drift")

            acc_inner = raw_acc.get("account", {})
            if isinstance(acc_inner, dict):
                eq = finite_decimal(acc_inner.get("totalMarginBalance", "0"))
                avail = finite_decimal(acc_inner.get("availableBalance", "0"))
                account_check["total_equity_usdt"] = float(eq)
                account_check["available_balance_usdt"] = float(avail)

            positions = raw_acc.get("positions", [])
            if isinstance(positions, list):
                account_check["open_positions_count"] = sum(
                    1
                    for p in positions
                    if isinstance(p, dict)
                    and finite_decimal(p.get("positionAmt", "0")) != Decimal("0")
                )
            open_orders = raw_acc.get("open_orders", [])
            if isinstance(open_orders, list):
                account_check["open_orders_count"] = len(open_orders)

            account_check["passed"] = bool(is_fresh and reconciled)

            dr = raw_acc.get("daily_risk", {})
            if not isinstance(dr, dict):
                dr = {}
            dr_verified = (
                dr.get("verified") is True
                and dr.get("observed_ms") == ts_ms
                and dr.get("equity_basis") == "ACCOUNT"
            )
            breached = bool(dr.get("breached", False))
            daily_risk_check["verified"] = dr_verified
            daily_risk_check["equity_basis"] = dr.get("equity_basis")
            daily_risk_check["breached"] = breached
            if dr_verified:
                loss_val = float(finite_decimal(dr.get("loss_usdt", "0")))
                limit_val = float(finite_decimal(dr.get("limit_usdt", "0")))
                rem_val = float(finite_decimal(dr.get("remaining_usdt", "0")))
                start_val = float(finite_decimal(dr.get("day_start_equity", "0")))
                util_pct = round((loss_val / limit_val) * 100.0, 2) if limit_val > 0 else 0.0
                daily_risk_check["day_start_equity_usdt"] = start_val
                daily_risk_check["loss_usdt"] = loss_val
                daily_risk_check["limit_usdt"] = limit_val
                daily_risk_check["remaining_usdt"] = rem_val
                daily_risk_check["utilization_pct"] = util_pct
                if breached:
                    critical_alerts.append("daily_loss_limit_breached")
                elif util_pct >= daily_loss_warning_ratio * 100.0:
                    warning_alerts.append(f"daily_loss_budget_high:{util_pct:.1f}pct")
                daily_risk_check["passed"] = not breached
            else:
                critical_alerts.append("daily_risk_unverified")
        except Exception as exc:
            critical_alerts.append(f"account_snapshot_parse_error:{type(exc).__name__}")

    # 2. Runtime Health & Multivariate Hawkes Audit
    health_path = storage_dir / "runtime-health.json"
    health_check: dict[str, Any] = {
        "path": str(health_path),
        "exists": health_path.is_file(),
        "fresh": False,
        "streams_healthy": False,
        "hawkes_status": "UNKNOWN",
        "arrival_count": 0,
        "spectral_radius": None,
        "baseline_boundary_symbols": [],
        "fit_error": None,
        "passed": False,
    }
    if not health_path.is_file():
        critical_alerts.append("runtime_health_missing")
    else:
        try:
            raw_h = json.loads(health_path.read_text(encoding="utf-8"))
            h_ts = int(raw_h.get("timestamp_ms", 0))
            h_age = abs(eval_ms - h_ts)
            h_fresh = h_age <= max_health_age_ms
            health_check["timestamp_ms"] = h_ts
            health_check["age_ms"] = h_age
            health_check["fresh"] = h_fresh
            if not h_fresh:
                critical_alerts.append(f"runtime_health_stale:{h_age}ms")

            market_ok = bool(raw_h.get("market_connected"))
            user_ok = bool(raw_h.get("user_stream_connected"))
            reconcile_req = bool(raw_h.get("user_stream_reconciliation_required"))
            stream_gap = bool(raw_h.get("user_stream_gap"))
            flatten_reason = raw_h.get("force_flatten_reason")
            cycle_err = raw_h.get("cycle_error_type")
            refresh_err = raw_h.get("last_account_refresh_error_type")
            scan_err = raw_h.get("scan_error_type")

            if not market_ok:
                critical_alerts.append("market_stream_disconnected")
            if not user_ok:
                critical_alerts.append("user_data_stream_disconnected")
            if stream_gap or reconcile_req:
                critical_alerts.append("user_data_stream_gap_or_reconciliation_required")
            if flatten_reason is not None:
                critical_alerts.append(f"force_flatten_active:{flatten_reason}")
            if cycle_err is not None:
                critical_alerts.append(f"protective_cycle_error:{cycle_err}")
            if refresh_err is not None:
                warning_alerts.append(f"account_refresh_error:{refresh_err}")
            if scan_err is not None:
                warning_alerts.append(f"causal_scan_error:{scan_err}")

            streams_healthy = (
                market_ok
                and user_ok
                and not reconcile_req
                and not stream_gap
                and flatten_reason is None
                and cycle_err is None
            )
            health_check["streams_healthy"] = streams_healthy

            micro = raw_h.get("microstructure", {})
            if not isinstance(micro, dict):
                micro = {}
            arrivals = int(micro.get("arrival_count", 0))
            fit_err = micro.get("fit_error")
            fit = micro.get("fit") if isinstance(micro.get("fit"), dict) else None
            sr = (
                float(fit["spectral_radius"])
                if fit is not None and isinstance(fit.get("spectral_radius"), (int, float))
                else None
            )
            boundary_syms = (
                [str(s) for s in fit.get("baseline_boundary_symbols", []) if isinstance(s, str)]
                if fit is not None
                else []
            )
            health_check["arrival_count"] = arrivals
            health_check["spectral_radius"] = sr
            health_check["baseline_boundary_symbols"] = boundary_syms
            health_check["fit_error"] = fit_err

            if sr is not None and sr >= spectral_radius_critical:
                health_check["hawkes_status"] = "CRITICAL_SUPERCRITICAL"
                critical_alerts.append(f"hawkes_spectral_radius_supercritical:{sr:.4f}")
            elif sr is not None and sr >= spectral_radius_warning:
                health_check["hawkes_status"] = "WARNING_ELEVATED"
                warning_alerts.append(f"hawkes_spectral_radius_elevated:{sr:.4f}")
            elif fit_err is not None:
                is_warmup = any(
                    tok in str(fit_err).lower()
                    for tok in ("span", "observed arrivals", "dimension")
                )
                if is_warmup:
                    health_check["hawkes_status"] = "WARMUP"
                    warning_alerts.append("hawkes_microstructure_warmup")
                else:
                    health_check["hawkes_status"] = "FIT_ERROR"
                    critical_alerts.append(f"hawkes_fit_error:{fit_err}")
            elif boundary_syms:
                health_check["hawkes_status"] = "BOUNDARY_DEGRADED"
                warning_alerts.append(
                    f"hawkes_baseline_boundary_symbols:{','.join(boundary_syms)}"
                )
            elif sr is not None:
                health_check["hawkes_status"] = "STABLE"

            health_check["passed"] = bool(
                h_fresh
                and streams_healthy
                and (sr is None or sr < spectral_radius_critical)
                and health_check["hawkes_status"]
                in {"STABLE", "WARMUP", "WARNING_ELEVATED", "BOUNDARY_DEGRADED"}
            )
        except Exception as exc:
            critical_alerts.append(f"runtime_health_parse_error:{type(exc).__name__}")

    # 3. Portfolio Scanner State Audit
    scanner_path = storage_dir / PORTFOLIO_SCANNER_STATE_NAME
    scanner_check: dict[str, Any] = {
        "path": str(scanner_path),
        "exists": scanner_path.is_file(),
        "fresh": False,
        "source": None,
        "portfolio_id": None,
        "btc_regime": None,
        "variant_count": 0,
        "ready_variants_count": 0,
        "max_gates_passed": 0,
        "passed": False,
    }
    if not scanner_path.is_file():
        warning_alerts.append("portfolio_scanner_state_missing")
    else:
        try:
            raw_s = json.loads(scanner_path.read_text(encoding="utf-8"))
            s_ts = int(raw_s.get("evaluated_at_ms", 0))
            s_age = abs(eval_ms - s_ts)
            s_fresh = s_age <= max_scanner_age_ms
            variants = raw_s.get("variants", [])
            if not isinstance(variants, list):
                variants = []
            scanner_check["evaluated_at_ms"] = s_ts
            scanner_check["age_ms"] = s_age
            scanner_check["fresh"] = s_fresh
            scanner_check["source"] = raw_s.get("source")
            scanner_check["portfolio_id"] = raw_s.get("portfolio_id")
            scanner_check["btc_regime"] = raw_s.get("btc_regime")
            scanner_check["variant_count"] = len(variants)
            scanner_check["ready_variants_count"] = sum(
                1 for v in variants if isinstance(v, dict) and v.get("signal_ready") is True
            )
            scanner_check["max_gates_passed"] = max(
                (int(v.get("gates_passed", 0)) for v in variants if isinstance(v, dict)),
                default=0,
            )
            if not s_fresh:
                warning_alerts.append(f"portfolio_scanner_state_stale:{s_age}ms")
            if len(variants) < 6:
                warning_alerts.append(f"portfolio_scanner_incomplete_variants:{len(variants)}")
            scanner_check["passed"] = bool(s_fresh and len(variants) >= 6)
        except Exception as exc:
            warning_alerts.append(f"portfolio_scanner_parse_error:{type(exc).__name__}")

    # 4. Optional Systemd Single-Writer & Daemon Audit
    systemd_check: dict[str, Any] | None = None
    if check_systemd:
        try:
            raw_legacy = LegacyWriterHandoffGuard().inspect_legacy_status()
            disabled = raw_legacy.get("UnitFileState") in {"disabled", "masked"}
            inactive = (
                raw_legacy.get("returncode") == "0"
                and disabled
                and raw_legacy.get("LoadState") == "loaded"
                and raw_legacy.get("ActiveState") == "inactive"
                and raw_legacy.get("SubState") == "dead"
                and raw_legacy.get("MainPID") == "0"
                and raw_legacy.get("Restart") == "no"
            )
            legacy_status: dict[str, Any] = {**raw_legacy, "inactive": inactive}
        except RuntimeError as exc:
            inactive = False
            legacy_status = {"inactive": False, "error": str(exc)}

        qualified_unit = _inspect_systemd_unit(qualified_service_name)
        q_active = (
            qualified_unit.get("ActiveState") == "active"
            and qualified_unit.get("SubState") == "running"
        )
        q_restarts = int(qualified_unit.get("NRestarts", "0") or "0")
        if not inactive:
            critical_alerts.append("legacy_writer_service_active_or_enabled")
        if not q_active:
            critical_alerts.append("qualified_runtime_service_not_running")
        elif q_restarts > 0:
            warning_alerts.append(f"qualified_runtime_service_restarts:{q_restarts}")
        systemd_check = {
            "legacy_writer": legacy_status,
            "qualified_runtime": qualified_unit,
            "passed": bool(inactive and q_active),
        }

    status = (
        "CRITICAL"
        if critical_alerts
        else ("WARNING" if warning_alerts else "HEALTHY")
    )
    body: dict[str, Any] = {
        "schema": "qualified-runtime-watchdog-v1",
        "evaluated_at_ms": eval_ms,
        "storage_dir": str(storage_dir),
        "status": status,
        "healthy": status == "HEALTHY",
        "critical_alerts": critical_alerts,
        "warning_alerts": warning_alerts,
        "checks": {
            "account_reconciliation": account_check,
            "daily_risk_budget": daily_risk_check,
            "streams_and_hawkes": health_check,
            "portfolio_scanner": scanner_check,
            **({"systemd": systemd_check} if systemd_check is not None else {}),
        },
    }
    body["watchdog_hash"] = content_hash(body)
    return body


def write_watchdog_report(storage_dir: Path, report: dict[str, Any]) -> Path:
    """Atomically persist the latest watchdog report inside `storage_dir`."""
    target = storage_dir / "watchdog-report.json"
    atomic_json(target, report)
    return target
