from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_artifacts import (
    build_creator_candidate_artifact,
    read_creator_candidate_artifact,
    write_creator_candidate_artifact,
)
from autonomous_futures.research.performance_metrics import TradePerformanceMetrics
from autonomous_futures.research.persisted_qualification import qualify_persisted_candidate
from autonomous_futures.research.qualification_artifacts import WalkForwardQualificationPolicy
from autonomous_futures.research.walk_forward import (
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
    read_walk_forward_aggregation,
    write_walk_forward_aggregation,
)

START = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _candidate():
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id="cand-persisted-oos-001",
        family="experimental",
        universe=StrategyUniverse(
            symbols=("BTCUSDT",), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="returns", lookback=20, shift=1),),
        entry=EntryExit(long="ema_slope > 0", short="ema_slope < 0"),
        exit=EntryExit(long="rsi > 70", short="rsi < 30"),
        vetoes=("regime_trend == 0",),
    )
    return build_creator_candidate_artifact(
        candidate_id="cand-persisted-oos-001",
        strategy=strategy,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-run-persisted-oos",
        research_seed=37,
        created_at=START,
    )


def _window(window_id: str, offset: int, pnl_text: str, drawdown: str = "2"):
    pnl = Decimal(pnl_text)
    gross_profit = max(pnl, Decimal("0"))
    gross_loss = max(-pnl, Decimal("0"))
    start = START + timedelta(minutes=5 * offset)
    return WalkForwardWindowMetrics(
        window_id=window_id,
        symbol="BTCUSDT",
        split="oos",
        window_start=start,
        window_end=start + timedelta(minutes=10),
        metrics=TradePerformanceMetrics(
            symbol="BTCUSDT",
            starting_equity=Decimal("100"),
            final_equity=Decimal("100") + pnl,
            trade_count=1,
            winning_trades=int(pnl > 0),
            losing_trades=int(pnl < 0),
            breakeven_trades=int(pnl == 0),
            win_rate=Decimal("1") if pnl > 0 else Decimal("0"),
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_pnl=pnl,
            average_trade_pnl=pnl,
            return_pct=pnl,
            profit_factor=(gross_profit / gross_loss if gross_loss else None),
            max_drawdown=Decimal(drawdown),
            max_drawdown_pct=Decimal(drawdown),
            peak_equity=Decimal("100"),
        ),
    )


def _aggregation(*, drawdown: str = "2"):
    return aggregate_walk_forward_metrics(
        (_window("fold-1", 0, "5", drawdown), _window("fold-2", 4, "-1", drawdown)),
        required_symbols=("BTCUSDT",),
        minimum_windows=2,
    )


def _policy(*, maximum_drawdown_pct: str = "5") -> WalkForwardQualificationPolicy:
    return WalkForwardQualificationPolicy(
        policy_id="strict-oos-v1",
        minimum_windows=2,
        minimum_trades=2,
        minimum_profit_factor=Decimal("1"),
        maximum_drawdown_pct=Decimal(maximum_drawdown_pct),
        minimum_average_return_pct=Decimal("0"),
    )


def _persist_inputs(tmp_path):
    candidate = _candidate()
    aggregation = _aggregation()
    candidate_path = tmp_path / "candidates" / "candidate.json"
    aggregation_path = tmp_path / "oos" / "aggregation.json"
    qualification_path = tmp_path / "qualifications" / "candidate.json"
    write_creator_candidate_artifact(candidate_path, candidate)
    write_walk_forward_aggregation(aggregation_path, aggregation)
    return candidate, aggregation, candidate_path, aggregation_path, qualification_path


def test_persisted_flow_writes_qualified_artifact_without_mutating_candidate(tmp_path) -> None:
    candidate, aggregation, candidate_path, aggregation_path, qualification_path = _persist_inputs(
        tmp_path
    )
    candidate_before = candidate_path.read_bytes()

    artifact = qualify_persisted_candidate(
        candidate_artifact_path=candidate_path,
        aggregation_path=aggregation_path,
        qualification_artifact_path=qualification_path,
        policy=_policy(),
        evaluator_run_id="persisted-oos-run-001",
        evaluator_version="persisted-oos-v1",
        evaluated_at=START,
    )

    assert artifact.decision == "qualified"
    assert artifact.oos_aggregation_hash is not None
    assert qualification_path.exists()
    assert candidate_path.read_bytes() == candidate_before
    assert read_creator_candidate_artifact(candidate_path) == candidate
    assert read_walk_forward_aggregation(aggregation_path).aggregation == aggregation
    assert artifact.promotion_state == "unpromoted"
    assert artifact.execution_authority is False


def test_persisted_flow_preserves_rejected_evidence_and_is_idempotent(tmp_path) -> None:
    _, _, candidate_path, aggregation_path, qualification_path = _persist_inputs(tmp_path)

    first = qualify_persisted_candidate(
        candidate_artifact_path=candidate_path,
        aggregation_path=aggregation_path,
        qualification_artifact_path=qualification_path,
        policy=_policy(maximum_drawdown_pct="1"),
        evaluator_run_id="persisted-oos-run-001",
        evaluator_version="persisted-oos-v1",
        evaluated_at=START,
    )
    before = qualification_path.read_bytes()
    second = qualify_persisted_candidate(
        candidate_artifact_path=candidate_path,
        aggregation_path=aggregation_path,
        qualification_artifact_path=qualification_path,
        policy=_policy(maximum_drawdown_pct="1"),
        evaluator_run_id="persisted-oos-run-001",
        evaluator_version="persisted-oos-v1",
        evaluated_at=START,
    )

    assert first.decision == "rejected"
    assert any(not gate.passed for gate in first.gates)
    assert second == first
    assert qualification_path.read_bytes() == before


def test_tampered_persisted_candidate_or_aggregation_fails_closed(tmp_path) -> None:
    candidate, aggregation, candidate_path, aggregation_path, qualification_path = _persist_inputs(
        tmp_path
    )
    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_payload["artifact_hash"] = "0" * 64
    candidate_path.write_text(json.dumps(candidate_payload), encoding="utf-8")

    with pytest.raises(DomainViolation, match="candidate artifact hash mismatch"):
        qualify_persisted_candidate(
            candidate_artifact_path=candidate_path,
            aggregation_path=aggregation_path,
            qualification_artifact_path=qualification_path,
            policy=_policy(),
            evaluator_run_id="persisted-oos-run-001",
            evaluator_version="persisted-oos-v1",
            evaluated_at=START,
        )

    candidate_path.write_text(json.dumps(candidate.model_dump(mode="json")), encoding="utf-8")
    aggregation_payload = json.loads(aggregation_path.read_text(encoding="utf-8"))
    aggregation_payload["aggregation_hash"] = "0" * 64
    aggregation_path.write_text(json.dumps(aggregation_payload), encoding="utf-8")

    with pytest.raises(DomainViolation, match="aggregation hash mismatch"):
        qualify_persisted_candidate(
            candidate_artifact_path=candidate_path,
            aggregation_path=aggregation_path,
            qualification_artifact_path=qualification_path,
            policy=_policy(),
            evaluator_run_id="persisted-oos-run-001",
            evaluator_version="persisted-oos-v1",
            evaluated_at=START,
        )
    assert aggregation.window_count == 2


def test_conflicting_qualification_rewrite_is_rejected(tmp_path) -> None:
    _, _, candidate_path, aggregation_path, qualification_path = _persist_inputs(tmp_path)
    qualify_persisted_candidate(
        candidate_artifact_path=candidate_path,
        aggregation_path=aggregation_path,
        qualification_artifact_path=qualification_path,
        policy=_policy(),
        evaluator_run_id="persisted-oos-run-001",
        evaluator_version="persisted-oos-v1",
        evaluated_at=START,
    )

    with pytest.raises(DomainViolation, match="qualification artifact path is immutable"):
        qualify_persisted_candidate(
            candidate_artifact_path=candidate_path,
            aggregation_path=aggregation_path,
            qualification_artifact_path=qualification_path,
            policy=_policy(),
            evaluator_run_id="persisted-oos-run-002",
            evaluator_version="persisted-oos-v1",
            evaluated_at=START,
        )
