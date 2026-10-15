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
    max_scanner_age_ms: int = 1_200_000,
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
            last_cycle_ms = raw_h.get("last_protective_cycle_ms")
            cycle_err = raw_h.get("cycle_error_type")
            refresh_err = raw_h.get("last_account_refresh_error_type")
            scan_err = raw_h.get("scan_error_type")

            cycle_fresh = (
                isinstance(last_cycle_ms, int)
                and abs(eval_ms - last_cycle_ms) <= max_health_age_ms
            )
            is_transient_refresh_cycle_err = (
                cycle_err == "ValueError"
                and refresh_err is not None
                and cycle_fresh
                and bool(account_check.get("passed"))
            )

            if not market_ok:
                critical_alerts.append("market_stream_disconnected")
            if not user_ok:
                critical_alerts.append("user_data_stream_disconnected")
            if stream_gap or reconcile_req:
                critical_alerts.append("user_data_stream_gap_or_reconciliation_required")
            if flatten_reason is not None:
                critical_alerts.append(f"force_flatten_active:{flatten_reason}")
            if cycle_err is not None and not is_transient_refresh_cycle_err:
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
                and (cycle_err is None or is_transient_refresh_cycle_err)
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
            elif boundary_syms or (
                fit_err is not None
                and "pinned to the optimizer lower bound" in str(fit_err).lower()
            ):
                health_check["hawkes_status"] = "BOUNDARY_DEGRADED"
                syms_label = ",".join(boundary_syms) if boundary_syms else str(fit_err)
                warning_alerts.append(f"hawkes_baseline_boundary_symbols:{syms_label}")
            elif fit_err is not None:
                err_lower = str(fit_err).lower()
                is_warmup = any(
                    tok in err_lower
                    for tok in ("warmup", "span", "observed arrivals", "dimension")
                )
                is_non_convergent = any(
                    tok in err_lower for tok in ("did not converge", "line search failed")
                )
                if is_warmup:
                    health_check["hawkes_status"] = "WARMUP"
                    warning_alerts.append("hawkes_microstructure_warmup")
                elif is_non_convergent:
                    health_check["hawkes_status"] = "NON_CONVERGENT_GUARDED"
                    warning_alerts.append("hawkes_fit_non_convergent_guarded")
                else:
                    health_check["hawkes_status"] = "FIT_ERROR"
                    critical_alerts.append(f"hawkes_fit_error:{fit_err}")
            elif sr is not None:
                health_check["hawkes_status"] = "STABLE"

            health_check["passed"] = bool(
                h_fresh
                and streams_healthy
                and (sr is None or sr < spectral_radius_critical)
                and health_check["hawkes_status"]
                in {
                    "STABLE",
                    "WARMUP",
                    "NON_CONVERGENT_GUARDED",
                    "WARNING_ELEVATED",
                    "BOUNDARY_DEGRADED",
                }
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

    # 4. Optional Systemd Single-Writer & Daemon Audit (or fresh cached watchdog-report.json)
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
    else:
        report_path = storage_dir / "watchdog-report.json"
        if report_path.is_file():
            try:
                cached = json.loads(report_path.read_text(encoding="utf-8"))
                cached_ts = int(cached.get("evaluated_at_ms", 0))
                cached_sys = cached.get("checks", {}).get("systemd")
                if isinstance(cached_sys, dict) and abs(eval_ms - cached_ts) <= 180_000:
                    systemd_check = {**cached_sys, "cached_from_report": True}
            except Exception:
                pass

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
    alert_state_path = storage_dir / WATCHDOG_ALERT_STATE_NAME
    if alert_state_path.is_file():
        try:
            raw_alert_state = json.loads(alert_state_path.read_text(encoding="utf-8"))
            if isinstance(raw_alert_state, dict):
                body["alert_dispatch"] = {
                    "alert_active": bool(raw_alert_state.get("alert_active", False)),
                    "last_transition": raw_alert_state.get("last_transition"),
                    "last_alert_sent_ms": raw_alert_state.get("last_alert_sent_ms"),
                    "last_alert_status": raw_alert_state.get("last_alert_status"),
                    "total_alerts_sent": int(raw_alert_state.get("total_alerts_sent", 0) or 0),
                    "channels_configured": list(
                        raw_alert_state.get("channels_configured", [])
                    ),
                }
        except Exception:
            pass
    body["watchdog_hash"] = content_hash(body)
    return body


WATCHDOG_ALERT_STATE_NAME = "watchdog-alert-state.json"


def dispatch_watchdog_alerts(
    storage_dir: Path,
    report: dict[str, Any],
    *,
    cooldown_seconds: int = 900,
    min_warning_consecutive: int = 2,
    bot_token: str | None = None,
    chat_id: str | None = None,
    webhook_url: str | None = None,
    dry_run: bool = False,
    notifier: Any | None = None,
    http_client: Any | None = None,
) -> dict[str, Any]:
    """Evaluate state transitions & cooldowns and dispatch Telegram / Webhook alerts.

    - CRITICAL alerts fire immediately on tick 1 (`CRITICAL_OPENED`), on escalation from
      WARNING (`CRITICAL_ESCALATED`), on new critical alert keys (`CRITICAL_NEW_ALERT`),
      or after `cooldown_seconds` (`CRITICAL_REMINDER`).
    - WARNING alerts fire once `consecutive_warning >= min_warning_consecutive`
      (`WARNING_OPENED`) and repeat after `cooldown_seconds` (`WARNING_REMINDER`).
    - Returning to HEALTHY while `alert_active` is True dispatches a one-time
      `RECOVERED` notification and clears `alert_active`.
    """
    import os

    import httpx

    from autonomous_futures.notify.telegram import (
        TelegramNotifierClient,
        format_watchdog_alert,
        resolve_telegram_credentials,
    )

    state_path = storage_dir / WATCHDOG_ALERT_STATE_NAME
    prev: dict[str, Any] = {}
    if state_path.is_file():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prev = loaded
        except Exception:
            prev = {}

    eval_ms = int(report.get("evaluated_at_ms") or (time.time_ns() // 1_000_000))
    status = str(report.get("status", "UNKNOWN")).upper()
    critical_alerts = sorted(str(a) for a in report.get("critical_alerts", []))
    warning_alerts = sorted(str(a) for a in report.get("warning_alerts", []))

    prev_warning = int(prev.get("consecutive_warning", 0) or 0)
    prev_critical = int(prev.get("consecutive_critical", 0) or 0)
    prev_non_healthy = int(prev.get("consecutive_non_healthy", 0) or 0)
    prev_active = bool(prev.get("alert_active", False))
    prev_alert_status = prev.get("last_alert_status")
    prev_sent_ms = prev.get("last_alert_sent_ms")
    prev_total_sent = int(prev.get("total_alerts_sent", 0) or 0)
    prev_crit_set = {str(x) for x in prev.get("last_alerted_critical_alerts", [])}

    cooldown_ms = max(0, int(cooldown_seconds) * 1000)
    min_warn = max(1, int(min_warning_consecutive))

    should_send = False
    suppressed_by_cooldown = False
    transition = "HEALTHY_NOOP"

    if status == "CRITICAL":
        consecutive_critical = prev_critical + 1
        consecutive_warning = 0
        consecutive_non_healthy = prev_non_healthy + 1
        new_crit = set(critical_alerts) - prev_crit_set
        if not prev_active:
            should_send = True
            transition = "CRITICAL_OPENED"
        elif prev_alert_status != "CRITICAL":
            should_send = True
            transition = "CRITICAL_ESCALATED"
        elif new_crit:
            should_send = True
            transition = "CRITICAL_NEW_ALERT"
        elif prev_sent_ms is None or (eval_ms - int(prev_sent_ms)) >= cooldown_ms:
            should_send = True
            transition = "CRITICAL_REMINDER"
        else:
            should_send = False
            suppressed_by_cooldown = True
            transition = "COOLDOWN_ACTIVE"
    elif status == "WARNING":
        consecutive_warning = prev_warning + 1
        consecutive_critical = 0
        consecutive_non_healthy = prev_non_healthy + 1
        if consecutive_warning < min_warn and not prev_active:
            should_send = False
            transition = "WARNING_DEBOUNCING"
        elif not prev_active:
            should_send = True
            transition = "WARNING_OPENED"
        elif prev_sent_ms is None or (eval_ms - int(prev_sent_ms)) >= cooldown_ms:
            should_send = True
            transition = "WARNING_REMINDER"
        else:
            should_send = False
            suppressed_by_cooldown = True
            transition = "COOLDOWN_ACTIVE"
    else:
        consecutive_warning = 0
        consecutive_critical = 0
        consecutive_non_healthy = 0
        if prev_active:
            should_send = True
            transition = "RECOVERED"
        else:
            should_send = False
            transition = "HEALTHY_NOOP"

    tg_config = resolve_telegram_credentials(
        bot_token,
        chat_id,
        dry_run=dry_run,
        storage_dir=storage_dir,
    )
    resolved_webhook = (webhook_url or os.environ.get("WATCHDOG_WEBHOOK_URL", "")).strip()
    channels_configured: list[str] = []
    if tg_config.is_configured or notifier is not None:
        channels_configured.append("telegram")
    if resolved_webhook:
        channels_configured.append("webhook")

    dispatched = False
    delivery_ok: bool | None = None
    delivery_error: str | None = None
    formatted_text: str | None = None

    if should_send:
        formatted_text = format_watchdog_alert(report, transition=transition)
        errors: list[str] = []
        # 1. Telegram delivery
        try:
            if notifier is not None:
                notifier.send_message(formatted_text)
            else:
                with TelegramNotifierClient(config=tg_config) as tg_client:
                    tg_client.send_message(formatted_text)
        except Exception as exc:
            errors.append(f"telegram:{type(exc).__name__}:{exc}")

        # 2. Optional Webhook delivery
        if resolved_webhook and not dry_run:
            webhook_payload = {
                "schema": "qualified-runtime-watchdog-webhook-v1",
                "transition": transition,
                "status": status,
                "evaluated_at_ms": eval_ms,
                "critical_alerts": critical_alerts,
                "warning_alerts": warning_alerts,
                "text": formatted_text,
            }
            try:
                if http_client is not None:
                    resp = http_client.post(resolved_webhook, json=webhook_payload, timeout=10.0)
                    if resp.status_code >= 400:
                        errors.append(f"webhook:HTTP_{resp.status_code}")
                else:
                    with httpx.Client(timeout=10.0) as w_client:
                        resp = w_client.post(resolved_webhook, json=webhook_payload)
                        if resp.status_code >= 400:
                            errors.append(f"webhook:HTTP_{resp.status_code}")
            except Exception as exc:
                errors.append(f"webhook:{type(exc).__name__}")

        dispatched = True
        delivery_ok = len(errors) == 0
        delivery_error = "; ".join(errors) if errors else None
        if status == "HEALTHY":
            alert_active = False
            last_alert_status = "HEALTHY"
            last_alerted_critical_alerts: list[str] = []
        else:
            alert_active = True
            last_alert_status = status
            last_alerted_critical_alerts = list(critical_alerts)
        last_alert_sent_ms: int | None = eval_ms
        total_alerts_sent = prev_total_sent + 1
    else:
        alert_active = False if status == "HEALTHY" else prev_active
        last_alert_status = prev_alert_status
        last_alert_sent_ms = prev_sent_ms
        last_alerted_critical_alerts = (
            [] if status == "HEALTHY" else list(prev_crit_set)
        )
        total_alerts_sent = prev_total_sent

    next_state: dict[str, Any] = {
        "schema": "qualified-runtime-watchdog-alert-state-v1",
        "updated_at_ms": eval_ms,
        "last_status": status,
        "last_transition": transition,
        "consecutive_non_healthy": consecutive_non_healthy,
        "consecutive_warning": consecutive_warning,
        "consecutive_critical": consecutive_critical,
        "alert_active": alert_active,
        "suppressed_by_cooldown": suppressed_by_cooldown,
        "cooldown_seconds": int(cooldown_seconds),
        "min_warning_consecutive": min_warn,
        "dispatched": dispatched,
        "dry_run": bool(tg_config.dry_run and not resolved_webhook),
        "channels_configured": channels_configured,
        "last_alert_sent_ms": last_alert_sent_ms,
        "last_alert_status": last_alert_status,
        "last_alerted_critical_alerts": sorted(last_alerted_critical_alerts),
        "last_alerted_warning_alerts": (
            warning_alerts if dispatched else prev.get("last_alerted_warning_alerts", [])
        ),
        "last_delivery_ok": delivery_ok if dispatched else prev.get("last_delivery_ok"),
        "last_delivery_error": delivery_error if dispatched else prev.get("last_delivery_error"),
        "total_alerts_sent": total_alerts_sent,
    }
    if storage_dir.is_dir():
        atomic_json(state_path, next_state)

    summary = {
        **next_state,
        **({"message_preview": formatted_text[:200]} if formatted_text else {}),
    }
    report["alert_dispatch"] = {
        "alert_active": alert_active,
        "dispatched": dispatched,
        "transition": transition,
        "last_transition": transition,
        "suppressed_by_cooldown": suppressed_by_cooldown,
        "last_alert_sent_ms": last_alert_sent_ms,
        "last_alert_status": last_alert_status,
        "total_alerts_sent": total_alerts_sent,
        "channels_configured": channels_configured,
        "delivery_ok": delivery_ok,
        "delivery_error": delivery_error,
    }
    report["watchdog_hash"] = content_hash(
        {k: v for k, v in report.items() if k != "watchdog_hash"}
    )
    return summary


def send_watchdog_test_alert(
    report: dict[str, Any],
    *,
    notifier: Any | None = None,
    webhook_url: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Send a one-shot verification test alert without mutating `watchdog-alert-state.json`."""
    import os

    import httpx

    from autonomous_futures.notify.telegram import (
        TelegramNotifierClient,
        format_watchdog_alert,
        resolve_telegram_credentials,
    )

    eval_ms = int(report.get("evaluated_at_ms") or (time.time_ns() // 1_000_000))
    resolved_webhook = (
        webhook_url
        if webhook_url is not None
        else os.environ.get("WATCHDOG_WEBHOOK_URL", "").strip()
    )
    raw_dir = report.get("storage_dir")
    storage_dir = Path(str(raw_dir)) if raw_dir else None
    tg_config = resolve_telegram_credentials(dry_run=dry_run, storage_dir=storage_dir)
    tg_configured = notifier is not None or tg_config.is_configured
    channels_configured: list[str] = []
    if tg_configured:
        channels_configured.append("telegram")
    if resolved_webhook:
        channels_configured.append("webhook")

    formatted_text = format_watchdog_alert(report, transition="TEST")
    errors: list[str] = []

    if notifier is not None:
        try:
            res = notifier.send_message(formatted_text)
            if isinstance(res, dict) and res.get("ok") is False:
                errors.append(f"telegram:{res.get('error', 'send_failed')}")
        except Exception as exc:
            errors.append(f"telegram:{type(exc).__name__}")
    elif tg_config.is_configured or tg_config.dry_run:
        try:
            with TelegramNotifierClient(tg_config) as client:
                res = client.send_message(formatted_text)
                if not res.get("ok"):
                    errors.append(f"telegram:{res.get('error', 'send_failed')}")
        except Exception as exc:
            errors.append(f"telegram:{type(exc).__name__}")

    if resolved_webhook and not dry_run:
        try:
            with httpx.Client(timeout=10.0) as http_client:
                resp = http_client.post(
                    resolved_webhook,
                    json={
                        "event": "watchdog_test_alert",
                        "transition": "TEST",
                        "status": str(report.get("status", "UNKNOWN")).upper(),
                        "evaluated_at_ms": eval_ms,
                        "text": formatted_text,
                        "report": report,
                    },
                )
                if resp.status_code >= 400:
                    errors.append(f"webhook:HTTP_{resp.status_code}")
        except Exception as exc:
            errors.append(f"webhook:{type(exc).__name__}")

    delivery_ok = len(errors) == 0 and (len(channels_configured) > 0 or dry_run)
    if not channels_configured and not dry_run:
        errors.append("no_alert_channels_configured")
    delivery_error = "; ".join(errors) if errors else None

    summary: dict[str, Any] = {
        "dispatched": True,
        "transition": "TEST",
        "evaluated_at_ms": eval_ms,
        "dry_run": bool(tg_config.dry_run and not resolved_webhook),
        "channels_configured": channels_configured,
        "delivery_ok": delivery_ok,
        "delivery_error": delivery_error,
        "message_preview": formatted_text[:200],
    }
    report["test_alert_dispatch"] = summary
    report["watchdog_hash"] = content_hash(
        {k: v for k, v in report.items() if k != "watchdog_hash"}
    )
    return summary


def write_watchdog_report(storage_dir: Path, report: dict[str, Any]) -> Path:
    """Atomically persist the latest watchdog report inside `storage_dir`."""
    target = storage_dir / "watchdog-report.json"
    atomic_json(target, report)
    return target

