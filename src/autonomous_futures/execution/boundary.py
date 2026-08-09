from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from autonomous_futures.domain.contracts import DomainModel, OrderAction, OrderIntent
from autonomous_futures.domain.environment import ExecutionEnvironment
from autonomous_futures.domain.errors import DomainViolation


class ExecutionAuthority(StrEnum):
    NONE = "NONE"
    SIMULATED = "SIMULATED"
    LIVE_ORDER = "LIVE_ORDER"


_SIMULATED_ENVIRONMENTS = frozenset({ExecutionEnvironment.PAPER, ExecutionEnvironment.SHADOW})


class ExecutionConfig(DomainModel):
    """Validated runtime configuration with no live routing implementation."""

    environment: ExecutionEnvironment
    runtime_id: str = Field(min_length=1)
    storage_root: str = Field(min_length=1)
    database_namespace: str = Field(min_length=1)
    event_stream_namespace: str = Field(min_length=1)
    execution_authority: ExecutionAuthority
    venue_endpoint: str | None = None
    venue_credentials: str | None = None

    @model_validator(mode="after")
    def reject_pre_live_capabilities(self) -> ExecutionConfig:
        if self.environment in _SIMULATED_ENVIRONMENTS:
            if self.execution_authority is not ExecutionAuthority.SIMULATED:
                raise ValueError("paper and shadow execution_authority must be SIMULATED")
            if self.venue_endpoint is not None:
                raise ValueError("venue_endpoint is forbidden for paper and shadow")
            if self.venue_credentials is not None:
                raise ValueError("venue_credentials are forbidden for paper and shadow")
        elif self.environment is ExecutionEnvironment.RESEARCH:
            if self.execution_authority is not ExecutionAuthority.NONE:
                raise ValueError("research execution_authority must be NONE")
            if self.venue_endpoint is not None:
                raise ValueError("venue_endpoint is forbidden for research")
            if self.venue_credentials is not None:
                raise ValueError("venue_credentials are forbidden for research")
        return self

    def assert_startup_safe(self) -> None:
        """Defence in depth for the validation performed at configuration load."""
        self.__class__.model_validate(self.model_dump())


class ExecutionEvent(DomainModel):
    """The persistable result of one simulated order; environment is mandatory."""

    event_id: UUID = Field(default_factory=uuid4)
    environment: ExecutionEnvironment
    source_environment: ExecutionEnvironment
    runtime_id: str = Field(min_length=1)
    execution_authority: Literal[ExecutionAuthority.SIMULATED] = ExecutionAuthority.SIMULATED
    intent_id: UUID
    symbol: str = Field(min_length=1, pattern=r"^[A-Z0-9]+$")
    action: OrderAction
    status: Literal["SIMULATED"] = "SIMULATED"
    simulated_fill_price: Decimal


class SimulatedExecutionRuntime:
    """In-memory, isolated paper/shadow order simulator with no venue dependency."""

    def __init__(self, config: ExecutionConfig) -> None:
        self._config = config
        self._events: list[ExecutionEvent] = []

    @classmethod
    def start(cls, config: ExecutionConfig) -> Self:
        config.assert_startup_safe()
        if config.environment is ExecutionEnvironment.RESEARCH:
            raise DomainViolation("research cannot submit orders")
        if config.environment not in _SIMULATED_ENVIRONMENTS:
            raise DomainViolation(
                "live or demo execution is not implemented; a separate explicit "
                "promotion boundary is required"
            )
        return cls(config)

    def submit(
        self, intent: OrderIntent, *, source_environment: ExecutionEnvironment
    ) -> ExecutionEvent:
        self._config.assert_startup_safe()
        if source_environment is not self._config.environment:
            raise DomainViolation(
                "source environment must match the isolated execution environment"
            )

        event = ExecutionEvent(
            environment=self._config.environment,
            source_environment=source_environment,
            runtime_id=self._config.runtime_id,
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            action=intent.action,
            simulated_fill_price=intent.reference_price,
        )
        self._events.append(event)
        return event

    def persisted_events(self) -> tuple[ExecutionEvent, ...]:
        return tuple(self._events)


def default_execution_config(environment: ExecutionEnvironment) -> ExecutionConfig:
    """Return a deny-by-default configuration for one isolated runtime namespace."""
    authority = (
        ExecutionAuthority.SIMULATED
        if environment in _SIMULATED_ENVIRONMENTS
        else ExecutionAuthority.NONE
    )
    return ExecutionConfig(
        environment=environment,
        runtime_id=f"simulated-{environment.value}-v1",
        storage_root=f"artifacts/{environment.value}/execution",
        database_namespace=f"autonomous_futures_execution_{environment.value}",
        event_stream_namespace=f"autonomous_futures_execution_events_{environment.value}",
        execution_authority=authority,
    )
