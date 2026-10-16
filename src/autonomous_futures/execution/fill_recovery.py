"""Recover real first-fill time and commissions from authenticated exchange trade records."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from autonomous_futures.execution.account_evidence import finite_decimal


@dataclass(frozen=True)
class FillSummary:
    quantity: Decimal
    quote_quantity: Decimal
    commission_usdt: Decimal
    realized_pnl_usdt: Decimal
    first_fill_ms: int | None
    last_fill_ms: int | None
    trade_ids: tuple[int, ...]


def summarize_fills(
    rows: list[dict[str, Any]], *, symbol: str, order_id: int, side: str, executed_quantity: Decimal
) -> FillSummary:
    quantities = quote = fees = pnl = Decimal("0")
    identities: set[int] = set()
    times = []
    for row in rows:
        identity = int(row["id"])
        if identity in identities:
            raise ValueError("Duplicate fill evidence")
        identities.add(identity)
        if (
            row["symbol"] != symbol
            or int(row["orderId"]) != order_id
            or row["side"] != side
            or row.get("positionSide") != "BOTH"
            or row["commissionAsset"] != "USDT"
        ):
            raise ValueError("Fill evidence does not match the owned USDT one-way order")
        quantity, price = finite_decimal(row["qty"]), finite_decimal(row["price"])
        if quantity <= 0 or price <= 0 or int(row["time"]) <= 0:
            raise ValueError("Invalid authenticated execution")
        quantities += quantity
        quote += finite_decimal(row["quoteQty"])
        fees += finite_decimal(row["commission"])
        pnl += finite_decimal(row["realizedPnl"])
        times.append(int(row["time"]))
    if (
        not executed_quantity.is_finite()
        or executed_quantity < 0
        or quantities != executed_quantity
    ):
        raise ValueError("Trade history does not reconcile with cumulative executed quantity")
    return FillSummary(
        quantities,
        quote,
        fees,
        pnl,
        min(times) if times else None,
        max(times) if times else None,
        tuple(sorted(identities)),
    )
