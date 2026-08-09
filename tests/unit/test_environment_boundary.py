from __future__ import annotations

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.environment import (
    EnvironmentBoundary,
    ExecutionEnvironment,
    default_boundaries,
    validate_isolation,
)
from autonomous_futures.domain.errors import DomainViolation


def test_default_boundaries_are_isolated_for_all_runtime_environments() -> None:
    boundaries = default_boundaries()

    assert {item.environment for item in boundaries} == {
        ExecutionEnvironment.RESEARCH,
        ExecutionEnvironment.PAPER,
        ExecutionEnvironment.SHADOW,
        ExecutionEnvironment.DEMO,
        ExecutionEnvironment.LIVE,
    }
    validate_isolation(boundaries)
    assert len({item.storage_root for item in boundaries}) == 5
    assert len({item.database_namespace for item in boundaries}) == 5
    assert len({item.event_stream_namespace for item in boundaries}) == 5
    assert len({item.credential_namespace for item in boundaries}) == 5


def test_shared_storage_or_ledger_namespace_is_rejected() -> None:
    boundaries = list(default_boundaries())
    boundaries[1] = boundaries[1].model_copy(update={"storage_root": boundaries[0].storage_root})

    with pytest.raises(DomainViolation, match="storage_root"):
        validate_isolation(boundaries)

    boundaries = list(default_boundaries())
    boundaries[1] = boundaries[1].model_copy(
        update={"database_namespace": boundaries[0].database_namespace}
    )
    with pytest.raises(DomainViolation, match="database_namespace"):
        validate_isolation(boundaries)


def test_research_paper_and_shadow_cannot_enable_authenticated_exchange() -> None:
    for environment in (
        ExecutionEnvironment.RESEARCH,
        ExecutionEnvironment.PAPER,
        ExecutionEnvironment.SHADOW,
    ):
        with pytest.raises(ValidationError, match="authenticated"):
            EnvironmentBoundary(
                environment=environment,
                storage_root=f"artifacts/{environment}",
                database_namespace=f"db_{environment}",
                event_stream_namespace=f"events_{environment}",
                credential_namespace=f"credentials_{environment}",
                authenticated_exchange=True,
            )


def test_duplicate_environment_identity_is_rejected() -> None:
    boundaries = list(default_boundaries())
    boundaries.append(boundaries[0].model_copy())

    with pytest.raises(DomainViolation, match="environment"):
        validate_isolation(boundaries)
