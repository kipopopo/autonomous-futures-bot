from dataclasses import replace
from decimal import Decimal as D

import pytest

from autonomous_futures.execution.protective_lifecycle import (
    OrderEvidence,
    entry_is_protected,
    prearm_actions,
    protective_actions,
)
from autonomous_futures.execution.trade_plan import ExitSlice, SymbolFilters, TradePlan

FILTERS = SymbolFilters(D(".01"), D(".1"), D(".1"), D("100"), D("5"))
PLAN = TradePlan(
    "ICT_TWINS",
    "SOLUSDT",
    "BUY",
    1000,
    "actual-signal-fixture",
    D("100"),
    D("2"),
    1,
    D("90"),
    D("120"),
    D("140"),
    120000,
    (
        ExitSlice("STOP", D("2"), D("90")),
        ExitSlice("TP1", D("1"), D("120")),
        ExitSlice("TP2", D("1"), D("140")),
    ),
)


def entry(filled="2", status="FILLED"):
    return OrderEvidence(
        "entry", "ENTRY", "SOLUSDT", "BUY", D("2"), D(filled), status, False, D("100")
    )


def stop(status="CONDITIONAL_NEW"):
    return OrderEvidence("stop", "STOP", "SOLUSDT", "SELL", D("2"), D("0"), status, True, D("90"))


def actions(entry_, exits, position, **kwargs):
    return protective_actions(
        PLAN,
        entry_,
        exits,
        D(position),
        FILTERS,
        now_ms=5000,
        first_fill_ms=2000,
        daily_breached=False,
        entry_expiry_ms=6000,
        **kwargs,
    )


def test_no_fill_is_not_a_position_and_does_not_cancel_prearmed_stop():
    assert actions(entry("0", "NEW"), (stop(),), "0") == ()
    assert not entry_is_protected(PLAN, (stop("UNKNOWN"),))
    assert entry_is_protected(PLAN, (stop(),))
    assert all(command.reduce_only for command in prearm_actions(PLAN, FILTERS))


def test_partial_fill_cancels_remainder_then_splits_actual_filled_quantity():
    initial = actions(entry(".5", "PARTIALLY_FILLED"), (stop(),), ".5")
    assert len(initial) == 1 and initial[0].operation == "CANCEL"
    exits = actions(entry(".5", "CANCELED"), (stop(),), ".5")
    assert [(order.role, order.quantity) for order in exits] == [("TP1", D(".2")), ("TP2", D(".3"))]
    assert all(order.reduce_only for order in exits)


def test_tp1_fill_preserves_stop_and_remaining_final_target():
    tp1 = OrderEvidence("tp1", "TP1", "SOLUSDT", "SELL", D("1"), D("1"), "FILLED", True, D("120"))
    result = actions(entry(), (stop(), tp1), "1")
    assert len(result) == 1 and result[0].role == "TP2" and result[0].quantity == 1
    assert all(order.client_id != "stop" for order in result)


def test_daily_breach_flatten_leaves_protection_until_confirmed_flat():
    result = protective_actions(
        PLAN,
        entry(),
        (stop(),),
        D("2"),
        FILTERS,
        now_ms=5000,
        first_fill_ms=None,
        daily_breached=True,
        entry_expiry_ms=6000,
    )
    assert len(result) == 1 and result[0].role == "FLATTEN" and result[0].reduce_only
    unknown = OrderEvidence(
        result[0].client_id, "FLATTEN", "SOLUSDT", "SELL", D("2"), D("0"), "UNKNOWN", True
    )
    assert actions(entry(), (stop(), unknown), "2") == ()
    filled = replace(unknown, status="FILLED", filled=D("2"))
    cleanup = actions(entry(), (stop(), filled), "0")
    assert len(cleanup) == 1 and cleanup[0].client_id == "stop" and cleanup[0].operation == "CANCEL"


def test_authenticated_external_risk_event_cancels_entries_and_flattens_owned_position():
    result = actions(entry(), (stop(),), "2", external_risk_breach=True)
    assert len(result) == 1
    assert result[0].role == "FLATTEN"
    assert result[0].reduce_only
    assert result[0].quantity == D("2")


def test_external_risk_event_flattens_even_when_exchange_stop_is_live():
    result = actions(entry(), (stop("NEW"),), "2", external_risk_breach=True)
    assert len(result) == 1
    assert result[0].role == "FLATTEN"
    assert result[0].reduce_only


def test_daily_loss_cutoff_flattens_even_when_exchange_stop_is_live():
    result = protective_actions(
        PLAN,
        entry(),
        (stop("NEW"),),
        D("2"),
        FILTERS,
        now_ms=5000,
        first_fill_ms=2000,
        daily_breached=True,
        entry_expiry_ms=6000,
    )
    assert len(result) == 1
    assert result[0].role == "FLATTEN"
    assert result[0].reduce_only


def test_external_or_opposite_position_cannot_be_adopted():
    for position in ("3", "-2"):
        with pytest.raises(ValueError, match="ownership"):
            actions(entry(), (stop(),), position)
    assert not entry_is_protected(PLAN, (replace(stop(), symbol="ETHUSDT"),))
    assert not entry_is_protected(PLAN, (replace(stop(), side="BUY"),))


def test_minimal_partial_lot_has_no_invalid_half_lot():
    result = actions(entry(".1", "CANCELED"), (stop(),), ".1")
    assert [(order.role, order.quantity) for order in result] == [("TP2", D(".1"))]


def test_triggered_stop_child_ack_is_reconciled_without_duplicate_close():
    assert actions(entry(), (stop("NEW"),), "2") == ()


def test_late_entry_fill_after_stop_execution_is_flattened_not_rearmed():
    executed_stop = replace(stop(), status="FILLED", filled=D(".5"))
    result = actions(entry("1", "CANCELED"), (executed_stop,), ".5")
    assert len(result) == 1 and result[0].role == "FLATTEN"
    assert result[0].quantity == D(".5") and result[0].reduce_only


@pytest.mark.parametrize("status", ["CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"])
def test_terminal_stop_with_owned_exposure_requires_protective_flatten(status):
    result = actions(entry(), (stop(status),), "2")
    assert len(result) == 1 and result[0].role == "FLATTEN"
    assert result[0].quantity == D("2") and result[0].reduce_only
