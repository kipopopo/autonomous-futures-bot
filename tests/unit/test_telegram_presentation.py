"""Presentation trust boundaries: unknown money never becomes a fabricated value."""

import pytest

from autonomous_futures.notify.telegram import (
    format_portfolio_digest,
    format_risk_alert,
    format_trade_closed_alert,
    format_trade_opened_alert,
)


@pytest.mark.parametrize("value", [None, "bad", "NaN", "Infinity"])
def test_invalid_money_is_unavailable(value: object) -> None:
    msg = format_trade_closed_alert({"net_pnl": value, "entry_fee": value, "exit_fee": "0"})
    assert "Net Realized PnL*: Unavailable" in msg
    assert "Total Fees*: Unavailable" in msg
    assert "$N/A" not in msg


def test_zero_money_and_partial_fees_are_not_missing_or_total() -> None:
    msg = format_trade_closed_alert({"net_pnl": "0", "cash": 0, "entry_fee": "1"})
    assert r"Cash Balance*: $0\.00 USDT" in msg
    assert "Total Fees*: Unavailable" in msg
    assert "(N/A%)" not in msg
    assert msg.index("Net Realized PnL") < msg.index("Entry Price")
    msg = format_trade_closed_alert({"entry_fee": "0.0012", "exit_fee": "0.0034"})
    assert r"Total Fees*: $0\.0046 USDT" in msg


def test_all_money_formatters_omit_unknown_currency() -> None:
    for msg in [
        format_trade_opened_alert({}),
        format_portfolio_digest({}),
        format_risk_alert("margin_warning", {}),
    ]:
        assert "$N/A" not in msg
        assert "$100" not in msg
    digest = format_portfolio_digest({"current_cash": 0, "current_equity": 0})
    assert r"$0\.00 USDT" in digest
    assert digest.index("Net Equity") < digest.index("Daemon")
