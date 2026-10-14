from dataclasses import replace
from decimal import Decimal

import pytest
from test_production_remediation import account_data
from test_protective_lifecycle import PLAN

from autonomous_futures.execution.qualification_domain import (
    verify_execution_domain,
    verify_plan_risk,
)


def domain():
    # Explicit policy fixture, never a production qualification report.
    return {
        "schema": "researched-execution-domain-v1",
        "testnet": True,
        "equity_basis": "ACCOUNT",
        "minimum_equity": "90",
        "maximum_equity": "110",
        "daily_loss_pct": "5",
        "trade_risk_pct": "0.5",
        "leverages": [1],
        "maximum_concurrent_symbols": 1,
    }


def test_single_leverage_study_cannot_authorize_different_runtime_leverage():
    verify_execution_domain(domain(), account_data(), leverage=1)
    with pytest.raises(ValueError, match="leverage"):
        verify_execution_domain(domain(), account_data(), leverage=10)


def test_single_symbol_study_cannot_authorize_concurrent_exposure():
    account = account_data()
    account["positions"] = [{"symbol": "ETHUSDT", "positionAmt": "1"}]
    with pytest.raises(ValueError, match="concurrency"):
        verify_execution_domain(domain(), account, leverage=1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_equity", "99"),
        ("testnet", False),
        ("equity_basis", "ALLOCATION"),
        ("trade_risk_pct", "1"),
    ],
)
def test_different_runtime_capital_contract_rejected(field, value):
    policy = domain()
    policy[field] = value
    with pytest.raises(ValueError):
        verify_execution_domain(policy, account_data(), leverage=1)


def test_missing_domain_is_not_inferred_from_replay_starting_equity():
    with pytest.raises(ValueError, match="lacks a researched"):
        verify_execution_domain(None, account_data(), leverage=1)


def test_unobserved_durable_entry_occupies_qualification_capacity():
    with pytest.raises(ValueError, match="concurrency"):
        verify_execution_domain(domain(), account_data(), leverage=1, pending_symbols=("ETHUSDT",))


def test_queued_plan_is_rejected_when_equity_loss_reduces_its_budget():
    plan = replace(PLAN, quantity=Decimal(".048"))
    account = account_data()
    verify_plan_risk(plan, account)
    account["account"].update(totalMarginBalance="98", totalWalletBalance="98")
    account["daily_risk"].update(loss_usdt="2", remaining_usdt="3")
    with pytest.raises(ValueError, match="percentage risk budget"):
        verify_plan_risk(plan, account)
