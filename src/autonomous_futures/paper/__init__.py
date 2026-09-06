"""Autonomous Futures Paper Trading Subsystem."""

from .circuit_breakers import (
    CircuitBreakerConfig,
    CircuitBreakerEvaluationResult,
    HardenedSharedMarginAccount,
    calculate_adverse_gap_fill,
)
from .fills import PaperRoundTripResult, simulate_paper_round_trip
from .ledger import PaperLedger, PaperLedgerEntry, PaperLedgerError
from .lifecycle import PaperLifecycleTelemetry, mark_paper_position
from .live_engine import ActivePaperTrade, LivePaperEngine
from .observation import PaperObservation, observe_paper_ledger
from .runtime import PaperRuntime, PaperRuntimeResult
from .safety import (
    PaperActionApproval,
    PaperActionPermission,
    PaperSafetyDecision,
    PaperSafetyEvidence,
    evaluate_paper_action_permission,
    evaluate_paper_safety,
)
from .sqlite_ledger import SqlitePaperLedger
from .sqlite_lifecycle import SqlitePaperLifecycle
from .sqlite_observation import SqlitePaperObservations

__all__ = [
    "ActivePaperTrade",
    "CircuitBreakerConfig",
    "CircuitBreakerEvaluationResult",
    "HardenedSharedMarginAccount",
    "LivePaperEngine",
    "PaperActionApproval",
    "PaperActionPermission",
    "PaperLedger",
    "PaperLedgerEntry",
    "PaperLedgerError",
    "PaperLifecycleTelemetry",
    "PaperObservation",
    "PaperRoundTripResult",
    "PaperRuntime",
    "PaperRuntimeResult",
    "PaperSafetyDecision",
    "PaperSafetyEvidence",
    "SqlitePaperLedger",
    "SqlitePaperLifecycle",
    "SqlitePaperObservations",
    "calculate_adverse_gap_fill",
    "evaluate_paper_action_permission",
    "evaluate_paper_safety",
    "mark_paper_position",
    "observe_paper_ledger",
    "simulate_paper_round_trip",
]
