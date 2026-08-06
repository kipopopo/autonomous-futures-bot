from __future__ import annotations

from enum import StrEnum

from .errors import DomainViolation


class RuntimeState(StrEnum):
    NORMAL = "NORMAL"
    THROTTLED = "THROTTLED"
    HALTED = "HALTED"
    EMERGENCY_FLAT = "EMERGENCY_FLAT"


class RuntimeEvent(StrEnum):
    DAILY_LOSS_STOP = "DAILY_LOSS_STOP"
    DRAWDOWN_HALT = "DRAWDOWN_HALT"
    CRITICAL_MISMATCH = "CRITICAL_MISMATCH"
    HEALTHY = "HEALTHY"


def transition_runtime_state(current: RuntimeState, event: RuntimeEvent) -> RuntimeState:
    """Apply only automatic risk-reducing transitions.

    Upward transitions require ``ResumeEvidence`` and an explicit operator action;
    they are intentionally not part of this automatic function.
    """
    if event is RuntimeEvent.HEALTHY:
        raise DomainViolation("automatic resume is forbidden")
    if event is RuntimeEvent.CRITICAL_MISMATCH:
        return RuntimeState.EMERGENCY_FLAT
    if event is RuntimeEvent.DRAWDOWN_HALT:
        return RuntimeState.HALTED
    if event is RuntimeEvent.DAILY_LOSS_STOP:
        if current is RuntimeState.NORMAL:
            return RuntimeState.THROTTLED
        return current
    raise DomainViolation(f"unsupported runtime event: {event}")
