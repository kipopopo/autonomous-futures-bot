"""Pure daily equity-loss circuit; the caller persists genuine boundary observations."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.execution.account_evidence import (
    EXTERNAL_BASIS_INCOME_TYPES,
    atomic_json,
    finite_decimal,
)

D = Decimal
DEFAULT_DAILY_LOSS_PCT = D("5")


def net_external_flow_amount(
    flows: Any, *, day_start_ms: int, captured_ms: int, observed_ms: int
) -> Decimal:
    """Validate unique USDT basis flows and total only those after day-start equity capture."""
    if not isinstance(flows, list):
        raise ValueError("Daily risk requires complete external-flow evidence")
    seen: set[str] = set()
    total = D("0")
    for flow in flows:
        if (
            not isinstance(flow, dict)
            or flow.get("incomeType") not in EXTERNAL_BASIS_INCOME_TYPES
            or flow.get("asset") != "USDT"
        ):
            raise ValueError("Daily risk contains an unclassified external flow")
        transaction_id = str(flow.get("tranId", ""))
        if not transaction_id:
            raise ValueError("External flow is missing its authenticated transaction identity")
        identity = f"{flow['incomeType']}:{transaction_id}"
        if identity in seen:
            raise ValueError("Duplicate external flow would distort daily risk")
        seen.add(identity)
        flow_ms = int(flow["time"])
        amount = finite_decimal(flow["income"])
        if not day_start_ms <= flow_ms <= observed_ms:
            raise ValueError("External flow falls outside the observed UTC day")
        if flow_ms == captured_ms:
            raise ValueError("External flow timing is ambiguous at the day-start snapshot")
        if flow_ms > captured_ms:
            total += amount
    return total


@dataclass(frozen=True)
class DailyRisk:
    day_start_equity: Decimal
    current_equity: Decimal
    net_external_flows: Decimal = D("0")
    limit_pct: Decimal = DEFAULT_DAILY_LOSS_PCT

    def __post_init__(self) -> None:
        if not all(
            v.is_finite()
            for v in (
                self.day_start_equity,
                self.current_equity,
                self.net_external_flows,
                self.limit_pct,
            )
        ):
            raise ValueError("Daily risk requires finite authenticated values")
        if self.day_start_equity <= 0 or not 0 < self.limit_pct < 100:
            raise ValueError("Invalid day-start equity or daily percentage")

    @property
    def limit_usdt(self) -> Decimal:
        return self.day_start_equity * self.limit_pct / 100

    @property
    def loss_usdt(self) -> Decimal:
        # Deposits cannot erase trading losses; withdrawals are not trading losses.
        return max(D("0"), self.day_start_equity + self.net_external_flows - self.current_equity)

    @property
    def remaining_usdt(self) -> Decimal:
        return max(D("0"), self.limit_usdt - self.loss_usdt)

    @property
    def breached(self) -> bool:
        return self.loss_usdt >= self.limit_usdt


class DailyRiskTracker:
    """Persist a real UTC boundary observation and latch a breach until the next day.

    No mid-day wallet or simulated allocation may masquerade as day-start equity.
    The account basis must be explicitly selected before this tracker is constructed.
    """

    DAY_MS = 86_400_000
    BOUNDARY_GRACE_MS = 30_000

    def __init__(
        self, path: Path, *, equity_basis: str, limit_pct: Decimal = DEFAULT_DAILY_LOSS_PCT
    ) -> None:
        if equity_basis != "ACCOUNT":
            raise ValueError("An explicitly selected account-equity basis is required")
        self.path = path
        self.limit_pct = limit_pct
        self.state: dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )

    def observe(self, snapshot: dict[str, Any], now_ms: int) -> dict[str, Any]:
        timestamp = int(snapshot["timestamp_ms"])
        if (
            snapshot.get("source") != "binance_authenticated_rest"
            or snapshot.get("reconciliation", {}).get("verified") is not True
            or not 0 <= now_ms - timestamp <= self.BOUNDARY_GRACE_MS
        ):
            raise ValueError("Daily risk requires fresh reconciled exchange evidence")
        day = timestamp // self.DAY_MS
        equity = finite_decimal(snapshot["account"]["totalMarginBalance"])
        environment = snapshot.get("testnet")
        if type(environment) is not bool:
            raise ValueError("Daily risk requires an authenticated exchange environment")
        if self.state and (
            self.state["testnet"] != environment or self.state["limit_pct"] != str(self.limit_pct)
        ):
            raise ValueError("Daily baseline belongs to a different environment or policy")
        if not self.state or self.state["day"] != day:
            if timestamp % self.DAY_MS > self.BOUNDARY_GRACE_MS:
                raise ValueError("Missing authentic day-start equity; entries remain disabled")
            self.state = {
                "day": day,
                "day_start_equity": str(equity),
                "captured_ms": timestamp,
                "testnet": environment,
                "limit_pct": str(self.limit_pct),
                "equity_basis": "ACCOUNT",
                "breached": False,
            }
        if timestamp < self.state.get("last_observed_ms", self.state["captured_ms"]):
            raise ValueError("Observation predates the latest daily risk evidence")
        captured_ms = int(self.state["captured_ms"])
        net_external_flows = net_external_flow_amount(
            snapshot.get("daily_external_flows"),
            day_start_ms=day * self.DAY_MS,
            captured_ms=captured_ms,
            observed_ms=timestamp,
        )
        risk = DailyRisk(
            D(self.state["day_start_equity"]),
            equity,
            net_external_flows=net_external_flows,
            limit_pct=self.limit_pct,
        )
        self.state["breached"] = bool(self.state["breached"] or risk.breached)
        self.state["last_observed_ms"] = timestamp
        atomic_json(self.path, self.state)
        return {
            **self.state,
            "verified": True,
            "observed_ms": timestamp,
            "limit_usdt": str(risk.limit_usdt),
            "loss_usdt": str(risk.loss_usdt),
            "net_external_flows": str(net_external_flows),
            "remaining_usdt": "0" if self.state["breached"] else str(risk.remaining_usdt),
        }
