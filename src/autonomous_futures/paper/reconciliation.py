"""Read-only reconciliation between injected runtime IDs and paper-ledger opens."""

from __future__ import annotations

from pydantic import Field

from ..domain.contracts import DomainModel
from .ledger import PaperLedger


class PaperReconciliationResult(DomainModel):
    reconciled: bool
    runtime_only_trade_ids: tuple[str, ...] = ()
    ledger_only_trade_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)


def reconcile_paper_positions(
    ledger: PaperLedger, runtime_open_trade_ids: tuple[str, ...]
) -> PaperReconciliationResult:
    """Compare injected state and report drift without repairing either side."""
    runtime_ids = set(runtime_open_trade_ids)
    ledger_ids = {entry.trade_id for entry in ledger.open_positions()}
    reasons: list[str] = []
    if len(runtime_ids) != len(runtime_open_trade_ids):
        reasons.append("runtime_duplicate_trade_id")
    runtime_only = tuple(sorted(runtime_ids - ledger_ids))
    ledger_only = tuple(sorted(ledger_ids - runtime_ids))
    if runtime_only:
        reasons.append("runtime_position_missing_from_ledger")
    if ledger_only:
        reasons.append("ledger_position_missing_from_runtime")
    return PaperReconciliationResult(
        reconciled=not reasons,
        runtime_only_trade_ids=runtime_only,
        ledger_only_trade_ids=ledger_only,
        reason_codes=tuple(reasons) if reasons else ("paper_positions_reconciled",),
    )
