from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from autonomous_futures.domain.contracts import OrderAction, OrderIntent
from autonomous_futures.domain.environment import ExecutionEnvironment
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.execution.boundary import (
    ExecutionAuthority,
    ExecutionConfig,
    SimulatedExecutionRuntime,
    default_execution_config,
)

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)


def _intent() -> OrderIntent:
    return OrderIntent(
        intent_id=UUID("00000000-0000-0000-0000-000000000001"),
        candidate_manifest_hash="candidate-sha256",
        symbol="BTCUSDT",
        action=OrderAction.OPEN_LONG,
        signal_time=NOW,
        valid_until=NOW + timedelta(minutes=5),
        reference_price=Decimal("100"),
        requested_stop_price=Decimal("99"),
        reason_codes=("test",),
        feature_snapshot_hash="feature-sha256",
    )


def test_paper_and_shadow_have_isolated_simulated_runtime_state() -> None:
    paper_config = default_execution_config(ExecutionEnvironment.PAPER)
    shadow_config = default_execution_config(ExecutionEnvironment.SHADOW)

    assert paper_config.execution_authority is ExecutionAuthority.SIMULATED
    assert shadow_config.execution_authority is ExecutionAuthority.SIMULATED
    assert paper_config.storage_root != shadow_config.storage_root
    assert paper_config.database_namespace != shadow_config.database_namespace
    assert paper_config.event_stream_namespace != shadow_config.event_stream_namespace
    assert paper_config.runtime_id != shadow_config.runtime_id

    paper = SimulatedExecutionRuntime.start(paper_config)
    event = paper.submit(_intent(), source_environment=ExecutionEnvironment.PAPER)

    assert event.environment is ExecutionEnvironment.PAPER
    assert event.runtime_id == paper_config.runtime_id
    assert event.execution_authority is ExecutionAuthority.SIMULATED
    assert event.status == "SIMULATED"
    assert event.simulated_fill_price == Decimal("100")
    assert paper.persisted_events() == (event,)


def test_paper_and_shadow_fail_closed_for_live_endpoint_credentials_and_authority() -> None:
    for environment in (ExecutionEnvironment.PAPER, ExecutionEnvironment.SHADOW):
        config = default_execution_config(environment)

        with pytest.raises(ValidationError, match="venue_endpoint"):
            ExecutionConfig.model_validate(
                {**config.model_dump(), "venue_endpoint": "https://fapi.binance.com"}
            )
        with pytest.raises(ValidationError, match="venue_credentials"):
            ExecutionConfig.model_validate(
                {**config.model_dump(), "venue_credentials": "credential-ref"}
            )
        with pytest.raises(ValidationError, match="SIMULATED"):
            ExecutionConfig.model_validate(
                {**config.model_dump(), "execution_authority": ExecutionAuthority.LIVE_ORDER}
            )


def test_research_artifact_cannot_silently_route_to_simulated_execution() -> None:
    runtime = SimulatedExecutionRuntime.start(default_execution_config(ExecutionEnvironment.PAPER))

    with pytest.raises(DomainViolation, match="source environment"):
        runtime.submit(_intent(), source_environment=ExecutionEnvironment.RESEARCH)

    assert runtime.persisted_events() == ()


def test_live_mode_cannot_start_without_a_separate_explicit_promotion_boundary() -> None:
    with pytest.raises(DomainViolation, match="not implemented"):
        SimulatedExecutionRuntime.start(default_execution_config(ExecutionEnvironment.LIVE))


def test_research_cannot_start_an_order_runtime() -> None:
    with pytest.raises(DomainViolation, match="cannot submit orders"):
        SimulatedExecutionRuntime.start(default_execution_config(ExecutionEnvironment.RESEARCH))
