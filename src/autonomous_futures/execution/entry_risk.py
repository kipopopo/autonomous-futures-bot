"""Validate authentic percentage-loss evidence before reserving exchange margin."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from autonomous_futures.execution.account_evidence import finite_decimal
from autonomous_futures.execution.daily_risk import DailyRisk, net_external_flow_amount


def remaining_daily_budget(snapshot: dict[str, Any]) -> Decimal:
    risk = snapshot.get("daily_risk", {})
    timestamp = int(snapshot["timestamp_ms"])
    if (
        risk.get("verified") is not True
        or risk.get("equity_basis") != "ACCOUNT"
        or risk.get("testnet") != snapshot.get("testnet")
        or int(risk.get("observed_ms", -1)) != timestamp
        or int(risk.get("day", -1)) != timestamp // 86400000
    ):
        raise ValueError("Genuine current daily-equity risk evidence is missing")
    captured = int(risk["captured_ms"])
    if (
        captured // 86400000 != timestamp // 86400000
        or not 0 <= captured % 86400000 <= 30000
        or captured > timestamp
    ):
        raise ValueError("Daily baseline was not captured at the day boundary")
    observed_external_flows = net_external_flow_amount(
        snapshot.get("daily_external_flows"),
        day_start_ms=timestamp // 86400000 * 86400000,
        captured_ms=captured,
        observed_ms=timestamp,
    )
    if finite_decimal(risk["net_external_flows"]) != observed_external_flows:
        raise ValueError("Daily risk external-flow evidence disagrees with authenticated income")
    if finite_decimal(risk["limit_pct"]) != Decimal("5"):
        raise ValueError("Daily risk does not match the approved 5 percent policy")
    daily = DailyRisk(
        finite_decimal(risk["day_start_equity"]),
        finite_decimal(snapshot["account"]["totalMarginBalance"]),
        net_external_flows=finite_decimal(risk["net_external_flows"]),
    )
    if (
        finite_decimal(risk["limit_usdt"]) != daily.limit_usdt
        or finite_decimal(risk["loss_usdt"]) != daily.loss_usdt
    ):
        raise ValueError("Daily risk evidence disagrees with observed equity")
    if risk.get("breached") is not False or daily.breached:
        raise ValueError("Daily percentage loss budget exhausted")
    remaining = finite_decimal(risk["remaining_usdt"])
    if not 0 < remaining <= daily.remaining_usdt:
        raise ValueError("Daily risk remaining budget is inconsistent")
    return remaining
