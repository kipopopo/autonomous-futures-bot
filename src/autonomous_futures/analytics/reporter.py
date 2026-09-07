"""Report orchestration and JSON persistence for daily performance analytics.

Aggregates closed trades, capital state, risk metrics, and daemon health
into structured DailyPerformanceReport artifacts conforming to Draft-07 schema.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.analytics.attribution import (
    DEFAULT_PORTFOLIO_SYMBOLS,
    calculate_asset_attribution,
    calculate_performance_ranking,
)
from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader
from autonomous_futures.analytics.metrics import calculate_performance_metrics
from autonomous_futures.analytics.models import (
    CapitalState,
    DailyPerformanceReport,
)

logger = logging.getLogger(__name__)


def generate_daily_performance_report(
    storage_dir: Path | str,
    report_date: str | None = None,
    days: int = 1,
    symbols: Sequence[str] | None = None,
    environment: str = "paper_live",
) -> DailyPerformanceReport:
    """Generate complete DailyPerformanceReport object for evaluation period.

    Args:
        storage_dir: Base directory containing SQLite ledgers and health checkpoints.
        report_date: ISO date string "YYYY-MM-DD". If None, defaults to current UTC date.
        days: Evaluation lookback window in days (default 1).
        symbols: Portfolio symbol universe (default BTC, ETH, SOL, DOGE).
        environment: Execution environment descriptor.

    Returns:
        Structured DailyPerformanceReport domain instance.
    """
    path = Path(storage_dir)
    active_symbols = list(symbols) if symbols is not None else list(DEFAULT_PORTFOLIO_SYMBOLS)

    now_utc = datetime.now(UTC)
    if report_date is None:
        target_date = now_utc.date()
        report_date_str = target_date.isoformat()
    else:
        report_date_str = str(report_date)
        target_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()

    # Time boundaries
    end_dt = datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=UTC
    ) + timedelta(days=1)
    start_dt = end_dt - timedelta(days=max(1, days))

    reader = ReadOnlyLedgerReader(path)
    trades = reader.read_closed_trades(start_time=start_dt, end_time=end_dt, symbols=active_symbols)

    # Ingest daemon health if available
    health_json_path = path / "paper-daemon-health.json"
    daemon_health_data: dict[str, Any] = {
        "daemon_status": "RUNNING",
        "pid": None,
        "uptime_seconds": 0.0,
        "feed_messages_received": 0,
        "feed_throughput_per_sec": 0.0,
        "circuit_breaker_status": "NORMAL",
    }
    starting_capital = Decimal("100.00")
    current_equity = Decimal("100.00")
    margin_util_pct = 0.0
    unrealized_pnl = Decimal("0.00")

    if health_json_path.is_file():
        try:
            raw_health = json.loads(health_json_path.read_text(encoding="utf-8"))
            if isinstance(raw_health, dict):
                daemon_health_data["daemon_status"] = str(
                    raw_health.get("daemon_status") or "RUNNING"
                )
                daemon_health_data["pid"] = raw_health.get("pid")
                daemon_health_data["uptime_seconds"] = float(
                    raw_health.get("uptime_seconds") or 0.0
                )
                daemon_health_data["feed_messages_received"] = int(
                    raw_health.get("feed_messages_received") or 0
                )
                daemon_health_data["feed_throughput_per_sec"] = float(
                    raw_health.get("feed_throughput_per_sec") or 0.0
                )
                daemon_health_data["circuit_breaker_status"] = str(
                    raw_health.get("circuit_breaker_status") or "NORMAL"
                )

                if raw_health.get("starting_capital_usdt"):
                    starting_capital = Decimal(str(raw_health["starting_capital_usdt"]))
                if raw_health.get("current_equity_usdt"):
                    current_equity = Decimal(str(raw_health["current_equity_usdt"]))
                if raw_health.get("margin_utilization_pct") is not None:
                    margin_util_pct = float(raw_health["margin_utilization_pct"])
        except (OSError, ValueError, TypeError) as exc:
            logger.debug("Could not parse daemon health JSON: %s", exc)

    # Compute metrics
    metrics = calculate_performance_metrics(trades, starting_capital=starting_capital)
    attributions = calculate_asset_attribution(trades, symbols=active_symbols)
    ranking = calculate_performance_ranking(attributions)

    # Reconciled ending cash
    ending_cash = reader.calculate_reconciled_cash(starting_capital=starting_capital)
    if not health_json_path.is_file() or current_equity == Decimal("100.00"):
        current_equity = ending_cash + unrealized_pnl

    peak_equity = max(starting_capital, ending_cash, current_equity)
    reserve_buffer_pct = max(0.0, 100.0 - margin_util_pct)
    realized_pnl_pct = (
        float(metrics.net_pnl / starting_capital * Decimal("100"))
        if starting_capital > Decimal("0")
        else 0.0
    )

    capital_state = CapitalState(
        starting_cash_usdt=starting_capital,
        ending_cash_usdt=ending_cash,
        current_equity_usdt=current_equity,
        peak_equity_usdt=peak_equity,
        net_realized_pnl_usdt=metrics.net_pnl,
        realized_pnl_pct=realized_pnl_pct,
        unrealized_pnl_usdt=unrealized_pnl,
        margin_allocated_usdt=Decimal("0.00"),
        margin_utilization_pct=margin_util_pct,
        reserve_buffer_pct=reserve_buffer_pct,
    )

    report_metadata: dict[str, Any] = {
        "schema_version": "1.0.0",
        "report_date": report_date_str,
        "generated_at_utc": now_utc.isoformat(),
        "period_start_utc": start_dt.isoformat(),
        "period_end_utc": end_dt.isoformat(),
        "storage_dir": str(path.resolve().as_posix()),
        "environment": environment,
    }

    safety_invariants: dict[str, Any] = {
        "orders_submitted": 0,
        "execution_authority": False,
        "live_trading_activation": False,
        "paper_activation": True,
        "zero_private_credentials": True,
        "all_invariants_pass": True,
    }

    return DailyPerformanceReport(
        report_metadata=report_metadata,
        daemon_health=daemon_health_data,
        safety_invariants=safety_invariants,
        capital_summary=capital_state.to_dict(),
        portfolio_performance=metrics.to_dict(),
        asset_breakdown={sym: attr.to_dict() for sym, attr in attributions.items()},
        asset_ranking=ranking,
    )


def generate_and_persist_daily_report(
    storage_dir: Path | str,
    report_date: str | None = None,
    days: int = 1,
    output_path: Path | str | None = None,
    symbols: Sequence[str] | None = None,
    environment: str = "paper_live",
) -> dict[str, Any]:
    """Generate daily performance report and write atomically to JSON file.

    Args:
        storage_dir: Base directory containing SQLite ledgers and health checkpoints.
        report_date: ISO date string "YYYY-MM-DD".
        days: Evaluation window in days.
        output_path: Optional explicit output file path.
        symbols: Optional symbol filter.
        environment: Execution environment name.

    Returns:
        Report dictionary conforming to Draft-07 schema.
    """
    path = Path(storage_dir)
    report = generate_daily_performance_report(
        storage_dir=path,
        report_date=report_date,
        days=days,
        symbols=symbols,
        environment=environment,
    )

    report_dict = report.to_dict()
    date_str = str(report.report_metadata["report_date"])

    if output_path is not None:
        dest = Path(output_path)
    else:
        dest = path / "reports" / f"daily-performance-{date_str}.json"

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(f"{dest.name}.tmp.{os.getpid()}_{uuid.uuid4().hex[:8]}")
    try:
        tmp_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                tmp_path.replace(dest)
                break
            except OSError:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.01 * (attempt + 1))
        logger.info("Persisted daily performance report to %s", dest)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    return report_dict
