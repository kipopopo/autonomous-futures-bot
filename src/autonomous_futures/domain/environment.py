from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, model_validator

from .contracts import DomainModel
from .errors import DomainViolation


class ExecutionEnvironment(StrEnum):
    RESEARCH = "research"
    PAPER = "paper"
    DEMO = "demo"
    LIVE = "live"


class EnvironmentBoundary(DomainModel):
    environment: ExecutionEnvironment
    storage_root: str = Field(min_length=1)
    database_namespace: str = Field(min_length=1)
    event_stream_namespace: str = Field(min_length=1)
    credential_namespace: str = Field(min_length=1)
    authenticated_exchange: bool = False

    @model_validator(mode="after")
    def protect_pre_live_environments(self) -> EnvironmentBoundary:
        if self.environment in (ExecutionEnvironment.RESEARCH, ExecutionEnvironment.PAPER):
            if self.authenticated_exchange:
                raise ValueError(
                    "authenticated exchange access is forbidden for research and paper environments"
                )
        return self


def default_boundaries() -> tuple[EnvironmentBoundary, ...]:
    return tuple(
        EnvironmentBoundary(
            environment=environment,
            storage_root=f"artifacts/{environment.value}",
            database_namespace=f"autonomous_futures_{environment.value}",
            event_stream_namespace=f"autonomous_futures_events_{environment.value}",
            credential_namespace=f"autonomous_futures_credentials_{environment.value}",
        )
        for environment in ExecutionEnvironment
    )


def validate_isolation(boundaries: Iterable[EnvironmentBoundary]) -> None:
    items = tuple(boundaries)
    environments = [item.environment for item in items]
    if len(environments) != len(set(environments)):
        raise DomainViolation("environment identity must be unique")

    for field_name in (
        "storage_root",
        "database_namespace",
        "event_stream_namespace",
        "credential_namespace",
    ):
        values = [getattr(item, field_name) for item in items]
        if len(values) != len(set(values)):
            raise DomainViolation(f"{field_name} must be isolated per environment")
