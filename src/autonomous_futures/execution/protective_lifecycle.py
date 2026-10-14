"""Pure protective lifecycle decisions from authenticated fills and owned position evidence.

Exchange acknowledgements are orders, never fills. The I/O adapter must persist each
command before submission and reconcile UNKNOWN commands rather than retry them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from hashlib import sha256
from typing import Literal

from autonomous_futures.execution.trade_plan import SymbolFilters, TradePlan, split_exit

TERMINAL = frozenset({"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"})
ACTIVE = frozenset({"NEW", "PARTIALLY_FILLED", "CONDITIONAL_NEW"})
Role = Literal["ENTRY", "STOP", "TP1", "TP2", "FLATTEN"]


@dataclass(frozen=True)
class OrderEvidence:
    client_id: str
    role: Role
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    filled: Decimal
    status: str
    reduce_only: bool
    price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.client_id or not self.quantity.is_finite() or not self.filled.is_finite():
            raise ValueError("Invalid order observation")
        if not 0 <= self.filled <= self.quantity or self.quantity <= 0:
            raise ValueError("Invalid cumulative exchange fill")
        if self.role != "ENTRY" and not self.reduce_only:
            raise ValueError("Protective order is not reduce-only")

    @property
    def outstanding(self) -> Decimal:
        return self.quantity - self.filled


@dataclass(frozen=True)
class ProtectiveAction:
    client_id: str
    role: Role
    operation: Literal["CANCEL", "PLACE"]
    order_type: Literal["LIMIT", "STOP_MARKET", "MARKET"]
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    price: Decimal | None
    reduce_only: bool = True


def action_id(plan: TradePlan, role: Role, key: str) -> str:
    return "afbot-" + sha256(f"{plan.signal_key}:{role}:{key}".encode()).hexdigest()[:30]


def prearm_actions(plan: TradePlan, filters: SymbolFilters) -> tuple[ProtectiveAction, ...]:
    """Conditional protection must be acknowledged before an entry can be sent.

    If the venue refuses a reduce-only stop before a position exists, entry stays
    disabled. We never retry with reduceOnly=false to manufacture acceptance.
    """
    side: Literal["BUY", "SELL"] = "SELL" if plan.side == "BUY" else "BUY"
    return tuple(
        ProtectiveAction(
            action_id(plan, "STOP", f"prearm:{index}"),
            "STOP",
            "PLACE",
            "STOP_MARKET",
            side,
            part.quantity,
            plan.stop,
        )
        for index, part in enumerate(split_exit(plan.quantity, plan.stop, "STOP", filters))
    )


def stop_coverage(plan: TradePlan, orders: tuple[OrderEvidence, ...]) -> Decimal:
    return sum(
        (
            order.outstanding
            for order in orders
            if order.role == "STOP"
            and order.status == "CONDITIONAL_NEW"
            and order.symbol == plan.symbol
            and order.side == ("SELL" if plan.side == "BUY" else "BUY")
            and order.price == plan.stop
            and order.reduce_only
        ),
        Decimal("0"),
    )


def entry_is_protected(plan: TradePlan, orders: tuple[OrderEvidence, ...]) -> bool:
    return stop_coverage(plan, orders) >= plan.quantity


def protective_actions(
    plan: TradePlan,
    entry: OrderEvidence,
    exits: tuple[OrderEvidence, ...],
    position_amount: Decimal,
    filters: SymbolFilters,
    *,
    now_ms: int,
    first_fill_ms: int | None,
    daily_breached: bool,
    entry_expiry_ms: int,
    strategy_invalidated: bool = False,
    external_risk_breach: bool = False,
) -> tuple[ProtectiveAction, ...]:
    if (
        entry.role != "ENTRY"
        or entry.reduce_only
        or entry.quantity != plan.quantity
        or entry.symbol != plan.symbol
        or entry.side != plan.side
    ):
        raise ValueError("Entry evidence does not bind the trade plan")
    if not position_amount.is_finite() or now_ms <= 0:
        raise ValueError("Invalid observed position")
    if any(
        order.role == "ENTRY" or order.symbol != plan.symbol or order.side == plan.side
        for order in exits
    ):
        raise ValueError("Exit journal contains an entry")
    exit_filled = sum((order.filled for order in exits), Decimal("0"))
    owned = entry.filled - exit_filled
    expected = owned if plan.side == "BUY" else -owned
    if owned < 0 or position_amount != expected:
        raise ValueError("Position ownership is unreconciled; do not adopt external exposure")
    side: Literal["BUY", "SELL"] = "SELL" if plan.side == "BUY" else "BUY"
    pending_entry = entry.status not in TERMINAL
    cancellation = (
        (
            ProtectiveAction(
                entry.client_id,
                "ENTRY",
                "CANCEL",
                "LIMIT",
                plan.side,
                entry.outstanding,
                plan.entry,
                False,
            ),
        )
        if pending_entry
        else ()
    )
    if owned == 0:
        if pending_entry:
            return (
                cancellation
                if daily_breached
                or external_risk_breach
                or strategy_invalidated
                or now_ms >= entry_expiry_ms
                else ()
            )
        cleanup = tuple(
            ProtectiveAction(
                order.client_id, order.role, "CANCEL", "LIMIT", side, order.outstanding, order.price
            )
            for order in exits
            if order.status not in TERMINAL
        )
        return (
            cancellation
            if daily_breached or external_risk_breach or now_ms >= entry_expiry_ms
            else ()
        ) + cleanup
    if first_fill_ms is not None and not 0 < first_fill_ms <= now_ms:
        raise ValueError("Invalid first-fill timestamp")
    # An uncertain or pending market closure is reconciled, never blindly duplicated.
    flatten_pending = any(
        order.role == "FLATTEN" and order.status not in TERMINAL for order in exits
    )
    stop_pending = any(
        order.role == "STOP" and order.status in {"NEW", "PARTIALLY_FILLED"} for order in exits
    )
    if flatten_pending or (stop_pending and not (daily_breached or external_risk_breach)):
        return cancellation
    must_flatten = (
        daily_breached
        or external_risk_breach
        or strategy_invalidated
        or first_fill_ms is None
        or now_ms - first_fill_ms >= plan.hold_ms
    )
    stop_failed = any(
        order.role == "STOP" and order.status in TERMINAL | {"UNKNOWN"} for order in exits
    )
    if must_flatten or stop_failed:
        key = f"{entry.filled}:{exit_filled}:{owned}"
        closure = tuple(
            ProtectiveAction(
                action_id(plan, "FLATTEN", f"{key}:{index}"),
                "FLATTEN",
                "PLACE",
                "MARKET",
                side,
                part.quantity,
                None,
            )
            for index, part in enumerate(split_exit(owned, plan.entry, "STOP", filters))
        )
        # Leave accepted stops intact until an exchange fill proves the position flat.
        return cancellation + closure
    coverage = stop_coverage(plan, exits)
    if coverage < owned:
        parts = split_exit(owned - coverage, plan.stop, "STOP", filters)
        protection = tuple(
            ProtectiveAction(
                action_id(plan, "STOP", f"fill:{entry.filled}:{index}"),
                "STOP",
                "PLACE",
                "STOP_MARKET",
                side,
                part.quantity,
                plan.stop,
            )
            for index, part in enumerate(parts)
        )
        return protection + cancellation
    # Cancel the unfilled entry remainder after a partial fill; prearmed stops cover any race.
    if pending_entry:
        return cancellation
    if any(order.status not in ACTIVE | TERMINAL for order in exits):
        return ()
    tp1_filled = sum((order.filled for order in exits if order.role == "TP1"), Decimal("0"))
    initial_tp1 = sum((part.quantity for part in plan.exits if part.role == "TP1"), Decimal("0"))
    actual_tp1 = (entry.filled * initial_tp1 / plan.quantity / filters.step_size).to_integral_value(
        rounding=ROUND_DOWN
    ) * filters.step_size
    if plan.tp2 is not None and (
        actual_tp1 < filters.min_qty or entry.filled - actual_tp1 < filters.min_qty
    ):
        actual_tp1 = Decimal("0")
    desired_tp1 = min(owned, max(Decimal("0"), actual_tp1 - tp1_filled))
    desired = {"TP1": desired_tp1, "TP2": owned - desired_tp1}
    prices = {"TP1": plan.tp1, "TP2": plan.tp2}
    actions = []
    for role in ("TP1", "TP2"):
        price = prices[role]
        quantity = desired[role]
        existing = tuple(order for order in exits if order.role == role and order.status in ACTIVE)
        remaining = sum((order.outstanding for order in existing), Decimal("0"))
        if remaining > quantity or any(order.price != price for order in existing):
            return tuple(
                ProtectiveAction(
                    order.client_id,
                    order.role,
                    "CANCEL",
                    "LIMIT",
                    side,
                    order.outstanding,
                    order.price,
                )
                for order in existing
            )
        if quantity > remaining and price is not None:
            for index, part in enumerate(split_exit(quantity - remaining, price, role, filters)):
                actions.append(
                    ProtectiveAction(
                        action_id(plan, role, f"{entry.filled}:{exit_filled}:{index}"),
                        role,
                        "PLACE",
                        "LIMIT",
                        side,
                        part.quantity,
                        price,
                    )
                )
    return tuple(actions)
