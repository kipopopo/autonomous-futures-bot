"""Bind runtime capital and concurrency to an explicitly researched execution domain."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from autonomous_futures.execution.account_evidence import finite_decimal
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.trade_plan import DEFAULT_CAPITAL_POLICY, TradePlan


def verify_execution_domain(
    domain: dict[str, Any] | None,
    account: dict[str, Any],
    *,
    leverage: int,
    pending_symbols: tuple[str, ...] = (),
) -> None:
    if not domain or domain.get("schema") != "researched-execution-domain-v1":
        raise ValueError("Qualification lacks a researched runtime capital/portfolio domain")
    if domain.get("testnet") is not account["testnet"]:
        raise ValueError("Qualification execution environment differs from runtime")
    daily = account.get("daily_risk", {})
    if daily.get("verified") is not True or domain.get("equity_basis") != daily.get("equity_basis"):
        raise ValueError("Qualification equity basis differs from authenticated daily evidence")
    equity = finite_decimal(account["account"]["totalMarginBalance"])
    minimum, maximum = (
        finite_decimal(domain["minimum_equity"]),
        finite_decimal(domain["maximum_equity"]),
    )
    if not 0 < minimum <= equity <= maximum:
        raise ValueError("Runtime equity is outside the researched capital domain")
    if finite_decimal(domain["daily_loss_pct"]) != DEFAULT_CAPITAL_POLICY.daily_loss_pct or (
        finite_decimal(domain["trade_risk_pct"]) != DEFAULT_CAPITAL_POLICY.trade_risk_pct
    ):
        raise ValueError("Runtime risk sizing differs from qualification")
    allowed = domain["leverages"]
    if (
        not allowed
        or any(type(value) is not int or value < 1 for value in allowed)
        or leverage not in allowed
    ):
        raise ValueError("Runtime leverage is outside the researched execution domain")
    capacity = domain["maximum_concurrent_symbols"]
    if type(capacity) is not int or capacity < 1:
        raise ValueError("Invalid researched portfolio capacity")
    occupied = {row["symbol"] for row in account["positions"] if finite_decimal(row["positionAmt"])}
    occupied.update(
        row["symbol"]
        for row in account["open_orders"]
        if row.get("reduceOnly") not in (True, "true")
    )
    occupied.update(pending_symbols)
    if len(occupied) >= capacity:
        raise ValueError("Runtime portfolio exceeds researched concurrency")


def verify_plan_risk(plan: TradePlan, account: dict[str, Any]) -> None:
    """A queued plan cannot retain a budget calculated before an equity loss."""
    budget = min(
        finite_decimal(account["account"]["totalMarginBalance"])
        * DEFAULT_CAPITAL_POLICY.trade_risk_pct
        / 100,
        remaining_daily_budget(account),
    )
    required = plan.quantity * (
        abs(plan.entry - plan.stop) + (plan.entry + plan.stop) * Decimal("0.0013")
    )
    if not required.is_finite() or required <= 0 or required > budget:
        raise ValueError("Queued plan exceeds the current percentage risk budget")
