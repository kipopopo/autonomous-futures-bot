"""Fresh authenticated commission evidence for qualified opening-margin admission."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from autonomous_futures.execution.account_evidence import exchange_bool, finite_decimal
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.live_orders import TERMINAL
from autonomous_futures.execution.trade_plan import TradePlan


@dataclass(frozen=True)
class CommissionEvidence:
    symbol: str
    maker: Decimal
    taker: Decimal
    observed_ms: int

    def rate(self, now_ms: int, *, maker: bool) -> Decimal:
        if not 0 <= now_ms - self.observed_ms <= 30_000:
            raise ValueError("Authenticated commission evidence is stale")
        if any(not rate.is_finite() or not -1 < rate < 1 for rate in (self.maker, self.taker)):
            raise ValueError("Invalid authenticated commission rate")
        # A rebate is not available cash before a real fill credits it.
        return max(Decimal("0"), self.maker if maker else self.taker)


def pending_openings(
    account: dict[str, Any], journal: dict[str, dict[str, Any]]
) -> tuple[tuple[str, Decimal, Decimal, bool], ...]:
    result = []
    observed = set()
    for row in account.get("open_algo_orders", []):
        if not exchange_bool(row.get("reduceOnly")):
            raise ValueError("Opening conditional-order fee exposure is not valued")
    for row in account["open_orders"]:
        observed.add(str(row["clientOrderId"]))
        if exchange_bool(row.get("reduceOnly")):
            continue
        remaining = finite_decimal(row["origQty"]) - finite_decimal(row["executedQty"])
        price = finite_decimal(row["price"])
        if remaining < 0 or price <= 0:
            raise ValueError("Cannot value pending opening fees")
        result.append((str(row["symbol"]), remaining * price, Decimal("0"), False))
    for cid, row in journal.items():
        if cid in observed or exchange_bool(row["reduce_only"]):
            continue
        if (
            row["state"] in TERMINAL
            and row.get("observed_ms", row["timestamp_ms"]) < account["timestamp_ms"]
        ):
            continue
        quantity, price = finite_decimal(row["quantity"]), finite_decimal(row["price"])
        leverage = finite_decimal(row["leverage"])
        if quantity <= 0 or price <= 0 or leverage < 1 or leverage != leverage.to_integral_value():
            raise ValueError("Cannot value unobserved opening margin")
        notional = quantity * price
        result.append((str(row["symbol"]), notional, notional / leverage, True))
    return tuple(result)


async def observe_commissions(
    gateway: BinanceFuturesGateway, symbols: tuple[str, ...]
) -> dict[str, CommissionEvidence]:
    evidence = {}
    for symbol in sorted(set(symbols)):
        response = await gateway.signed_get("/fapi/v1/commissionRate", {"symbol": symbol})
        if not isinstance(response, dict) or response.get("symbol") != symbol:
            raise ValueError("Commission response does not bind the requested symbol")
        observation = CommissionEvidence(
            symbol,
            finite_decimal(response["makerCommissionRate"]),
            finite_decimal(response["takerCommissionRate"]),
            time.time_ns() // 1_000_000,
        )
        observation.rate(observation.observed_ms, maker=True)
        evidence[symbol] = observation
    return evidence


def verify_margin_with_fees(
    plan: TradePlan,
    account: dict[str, Any],
    journal: dict[str, dict[str, Any]],
    evidence: dict[str, CommissionEvidence],
    now_ms: int,
) -> Decimal:
    def rate(symbol: str, maker: bool) -> Decimal:
        observed = evidence.get(symbol)
        if observed is None or observed.symbol != symbol:
            raise ValueError("Missing authenticated commission evidence")
        return observed.rate(now_ms, maker=maker)

    required = plan.notional / plan.leverage + plan.notional * rate(plan.symbol, True)
    for symbol, notional, margin, unobserved in pending_openings(account, journal):
        # Journal openings are GTX. External order execution role is not guaranteed;
        # never assume that a particular fee schedule has maker <= taker.
        pending_rate = rate(symbol, True)
        if not unobserved:
            pending_rate = max(pending_rate, rate(symbol, False))
        required += margin + notional * pending_rate
    if finite_decimal(account["account"]["availableBalance"]) < required:
        raise ValueError("Insufficient exchange available margin including opening fees")
    return required
