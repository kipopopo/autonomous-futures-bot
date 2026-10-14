import asyncio
from decimal import Decimal as D
from unittest.mock import AsyncMock

import pytest
from test_protective_lifecycle import PLAN

from autonomous_futures.execution.commission_headroom import (
    CommissionEvidence,
    observe_commissions,
    verify_margin_with_fees,
)


def account(available="200.04", orders=()):
    return {
        "timestamp_ms": 1000,
        "account": {"availableBalance": available},
        "open_orders": list(orders),
        "open_algo_orders": [],
    }


def rates():
    return {PLAN.symbol: CommissionEvidence(PLAN.symbol, D(".0002"), D(".0004"), 1000)}


def test_margin_sufficiency_includes_entry_commission_without_fixed_order_cap():
    assert verify_margin_with_fees(PLAN, account(), {}, rates(), 1000) == D("200.04")
    with pytest.raises(ValueError, match="opening fees"):
        verify_margin_with_fees(PLAN, account("200"), {}, rates(), 1000)


def test_observed_order_margin_is_not_reserved_twice_but_pending_fees_are():
    order = {
        "symbol": PLAN.symbol,
        "clientOrderId": "opening",
        "reduceOnly": False,
        "origQty": "2",
        "executedQty": "1",
        "price": "100",
    }
    journal = {"opening": {"reduce_only": False}}  # Matching exchange inventory takes precedence.
    assert verify_margin_with_fees(PLAN, account("200.08", (order,)), journal, rates(), 1000) == D(
        "200.08"
    )


def test_unobserved_intention_reserves_full_margin_and_maker_fee():
    journal = {
        "unknown": {
            "symbol": PLAN.symbol,
            "reduce_only": False,
            "state": "UNKNOWN",
            "timestamp_ms": 990,
            "quantity": "1",
            "price": "100",
            "leverage": "2",
        }
    }
    assert verify_margin_with_fees(PLAN, account("250.06"), journal, rates(), 1000) == D("250.06")
    with pytest.raises(ValueError, match="opening fees"):
        verify_margin_with_fees(PLAN, account("250.05"), journal, rates(), 1000)


@pytest.mark.parametrize("now", [999, 31001])
def test_future_or_expired_commission_observation_cannot_admit(now):
    with pytest.raises(ValueError, match="stale"):
        verify_margin_with_fees(PLAN, account(), {}, rates(), now)


def test_new_pending_symbol_without_observed_fees_fails_under_writer_guard():
    other = {
        "symbol": "ETHUSDT",
        "clientOrderId": "external",
        "reduceOnly": False,
        "origQty": "1",
        "executedQty": "0",
        "price": "100",
    }
    with pytest.raises(ValueError, match="Missing authenticated"):
        verify_margin_with_fees(PLAN, account("1000", (other,)), {}, rates(), 1000)


def test_rebates_cannot_fund_an_order_before_they_are_credited():
    rebate = {PLAN.symbol: CommissionEvidence(PLAN.symbol, D("-.0001"), D(".0004"), 1000)}
    assert verify_margin_with_fees(PLAN, account("200"), {}, rebate, 1000) == 200
    with pytest.raises(ValueError, match="opening fees"):
        verify_margin_with_fees(PLAN, account("199.99"), {}, rebate, 1000)


def test_actual_authenticated_endpoint_response_is_bound_to_symbol():
    gateway = AsyncMock()
    gateway.signed_get.return_value = {
        "symbol": PLAN.symbol,
        "makerCommissionRate": ".0002",
        "takerCommissionRate": ".0004",
    }
    result = asyncio.run(observe_commissions(gateway, (PLAN.symbol, PLAN.symbol)))
    gateway.signed_get.assert_awaited_once_with("/fapi/v1/commissionRate", {"symbol": PLAN.symbol})
    assert result[PLAN.symbol].maker == D(".0002")
    gateway.signed_get.return_value["symbol"] = "ETHUSDT"
    with pytest.raises(ValueError, match="requested symbol"):
        asyncio.run(observe_commissions(gateway, (PLAN.symbol,)))


def test_unvalued_conditional_opening_order_blocks_new_admission():
    data = account("1000")
    data["open_algo_orders"] = [{"reduceOnly": False}]
    with pytest.raises(ValueError, match="conditional-order"):
        verify_margin_with_fees(PLAN, data, {}, rates(), 1000)


def test_observed_order_reserves_higher_rate_without_assuming_fee_tier_ordering():
    order = {
        "symbol": PLAN.symbol,
        "clientOrderId": "external",
        "reduceOnly": False,
        "origQty": "1",
        "executedQty": "0",
        "price": "100",
    }
    inverted = {PLAN.symbol: CommissionEvidence(PLAN.symbol, D(".0005"), D(".0002"), 1000)}
    assert verify_margin_with_fees(PLAN, account("200.15", (order,)), {}, inverted, 1000) == D(
        "200.15"
    )
    with pytest.raises(ValueError, match="opening fees"):
        verify_margin_with_fees(PLAN, account("200.14", (order,)), {}, inverted, 1000)
