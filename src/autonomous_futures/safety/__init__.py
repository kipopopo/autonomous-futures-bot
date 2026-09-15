"""Safety readiness gates, fail-closed boundaries, and completion status matrix."""

from __future__ import annotations

from .readiness_gates import (
    CompletionMatrixEntry,
    ExecutionGateStatus,
    ExecutionTarget,
    SafetyGateResult,
    evaluate_safety_gate,
    get_system_completion_matrix,
)

__all__ = [
    "CompletionMatrixEntry",
    "ExecutionGateStatus",
    "ExecutionTarget",
    "SafetyGateResult",
    "evaluate_safety_gate",
    "get_system_completion_matrix",
]
