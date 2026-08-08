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
    build_creator_candidate_registry,
    read_creator_candidate_registry,
    write_creator_candidate_artifact,
    write_creator_candidate_registry,
)
from autonomous_futures.research.performance_metrics import TradePerformanceMetrics
from autonomous_futures.research.persisted_qualification import (
    PersistedQualificationBatchResult,
    run_persisted_qualification_batch,
)
from autonomous_futures.research.qualification_artifacts import WalkForwardQualificationPolicy
from autonomous_futures.research.walk_forward import (
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
    write_walk_forward_aggregation,
)

START = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _candidate(candidate_id: str, offset: int):
    strategy = StrategySpec(
        dsl_version=1,
        strategy_id=candidate_id,
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
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash="a" * 64,
        dataset_registry_hash="b" * 64,
        creator_run_id="creator-batch-run",
        research_seed=offset,
        created_at=START + timedelta(minutes=offset),
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


def _persist_registry(tmp_path, *, include_bad: bool = True):
    candidates = [_candidate("cand-batch-a", 0), _candidate("cand-batch-b", 1)]
    candidate_root = tmp_path / "candidates"
    aggregation_root = tmp_path / "aggregations"
    qualification_root = tmp_path / "qualifications"
    refs = {}
    for candidate in candidates:
        ref = f"{candidate.candidate_id}.json"
        write_creator_candidate_artifact(candidate_root / ref, candidate)
        refs[candidate.candidate_id] = ref
    write_walk_forward_aggregation(aggregation_root / "cand-batch-a.json", _aggregation())
    if include_bad:
        write_walk_forward_aggregation(
            aggregation_root / "cand-batch-b.json", _aggregation(drawdown="9")
        )
    registry = build_creator_candidate_registry(
        tuple((candidate, refs[candidate.candidate_id]) for candidate in candidates),
        created_at=START,
    )
    registry_path = tmp_path / "registry.json"
    write_creator_candidate_registry(registry_path, registry)
    return (
        registry,
        registry_path,
        candidate_root,
        aggregation_root,
        qualification_root,
        refs,
    )


def test_batch_qualifies_each_persisted_candidate_independently(tmp_path) -> None:
    (
        registry,
        registry_path,
        candidate_root,
        aggregation_root,
        qualification_root,
        refs,
    ) = _persist_registry(tmp_path)
    candidate_bytes = {
        candidate_id: (candidate_root / ref).read_bytes() for candidate_id, ref in refs.items()
    }

    result = run_persisted_qualification_batch(
        registry_path=registry_path,
        candidate_artifact_root=candidate_root,
        aggregation_root=aggregation_root,
        qualification_root=qualification_root,
        aggregation_refs={
            "cand-batch-a": "cand-batch-a.json",
            "cand-batch-b": "cand-batch-b.json",
        },
        policy=_policy(),
        evaluator_run_id="batch-oos-run-001",
        evaluator_version="batch-oos-v1",
        evaluated_at=START,
    )

    assert isinstance(result, PersistedQualificationBatchResult)
    assert result.selected_candidate_ids == ("cand-batch-a", "cand-batch-b")
    assert result.evaluated_candidate_ids == ("cand-batch-a", "cand-batch-b")
    assert result.qualified_candidate_ids == ("cand-batch-a",)
    assert result.rejected_candidate_ids == ("cand-batch-b",)
    assert result.blocked_candidate_ids == ()
    assert result.promotion_state == "unpromoted"
    assert result.execution_authority is False
    assert read_creator_candidate_registry(registry_path) == registry
    assert all(
        (candidate_root / ref).read_bytes() == candidate_bytes[candidate_id]
        for candidate_id, ref in refs.items()
    )
    assert (qualification_root / "cand-batch-a.json").exists()
    assert (qualification_root / "cand-batch-b.json").exists()


def test_batch_blocks_missing_aggregation_without_qualification_output(tmp_path) -> None:
    (
        _,
        registry_path,
        candidate_root,
        aggregation_root,
        qualification_root,
        _,
    ) = _persist_registry(tmp_path, include_bad=False)

    result = run_persisted_qualification_batch(
        registry_path=registry_path,
        candidate_artifact_root=candidate_root,
        aggregation_root=aggregation_root,
        qualification_root=qualification_root,
        aggregation_refs={"cand-batch-a": "cand-batch-a.json", "cand-batch-b": "missing.json"},
        policy=_policy(),
        evaluator_run_id="batch-oos-run-001",
        evaluator_version="batch-oos-v1",
        evaluated_at=START,
    )

    assert result.evaluated_candidate_ids == ("cand-batch-a",)
    assert result.qualified_candidate_ids == ("cand-batch-a",)
    assert result.blocked_candidate_ids == ("cand-batch-b",)
    assert result.rejected_candidate_ids == ()
    assert result.failures[0].reason_code == "missing_persisted_aggregation"
    assert not (qualification_root / "cand-batch-b.json").exists()


def test_batch_tampered_candidate_is_blocked_and_other_candidates_continue(tmp_path) -> None:
    (
        _,
        registry_path,
        candidate_root,
        aggregation_root,
        qualification_root,
        refs,
    ) = _persist_registry(tmp_path)
    tampered_path = candidate_root / refs["cand-batch-a"]
    payload = json.loads(tampered_path.read_text(encoding="utf-8"))
    payload["artifact_hash"] = "0" * 64
    tampered_path.write_text(json.dumps(payload), encoding="utf-8")

    result = run_persisted_qualification_batch(
        registry_path=registry_path,
        candidate_artifact_root=candidate_root,
        aggregation_root=aggregation_root,
        qualification_root=qualification_root,
        aggregation_refs={
            "cand-batch-a": "cand-batch-a.json",
            "cand-batch-b": "cand-batch-b.json",
        },
        policy=_policy(),
        evaluator_run_id="batch-oos-run-001",
        evaluator_version="batch-oos-v1",
        evaluated_at=START,
    )

    assert result.blocked_candidate_ids == ("cand-batch-a",)
    assert result.evaluated_candidate_ids == ("cand-batch-b",)
    assert result.failures[0].reason_code == "candidate_artifact_hash_mismatch"
    assert (qualification_root / "cand-batch-b.json").exists()


def test_batch_limit_is_deterministic_and_does_not_change_candle_evidence(tmp_path) -> None:
    (
        registry,
        registry_path,
        candidate_root,
        aggregation_root,
        qualification_root,
        refs,
    ) = _persist_registry(tmp_path)
    candidate_c = _candidate("cand-batch-c", 2)
    candidate_c_ref = "cand-batch-c.json"
    write_creator_candidate_artifact(candidate_root / candidate_c_ref, candidate_c)
    write_walk_forward_aggregation(aggregation_root / candidate_c_ref, _aggregation())
    registry = build_creator_candidate_registry(
        tuple(
            [
                (_candidate("cand-batch-a", 0), refs["cand-batch-a"]),
                (_candidate("cand-batch-b", 1), refs["cand-batch-b"]),
                (candidate_c, candidate_c_ref),
            ]
        ),
        created_at=START,
    )
    write_creator_candidate_artifact(
        candidate_root / refs["cand-batch-a"], _candidate("cand-batch-a", 0)
    )
    write_creator_candidate_artifact(
        candidate_root / refs["cand-batch-b"], _candidate("cand-batch-b", 1)
    )
    registry_path = tmp_path / "registry-with-limit-fixture.json"
    write_creator_candidate_registry(registry_path, registry)

    result = run_persisted_qualification_batch(
        registry_path=registry_path,
        candidate_artifact_root=candidate_root,
        aggregation_root=aggregation_root,
        qualification_root=qualification_root,
        aggregation_refs={
            entry.candidate_id: f"{entry.candidate_id}.json" for entry in registry.entries
        },
        policy=_policy(),
        evaluator_run_id="batch-oos-run-001",
        evaluator_version="batch-oos-v1",
        evaluated_at=START,
        limit=2,
    )

    assert result.selected_candidate_ids == ("cand-batch-a", "cand-batch-b")
    assert result.unselected_candidate_ids == ("cand-batch-c",)
    assert not (qualification_root / "cand-batch-c.json").exists()


def test_batch_rejects_conflicting_existing_qualification_artifact(tmp_path) -> None:
    (
        _,
        registry_path,
        candidate_root,
        aggregation_root,
        qualification_root,
        _,
    ) = _persist_registry(tmp_path)
    qualification_root.mkdir(parents=True)
    conflict_path = qualification_root / "cand-batch-a.json"
    conflict_path.write_text("{}", encoding="utf-8")

    result = run_persisted_qualification_batch(
        registry_path=registry_path,
        candidate_artifact_root=candidate_root,
        aggregation_root=aggregation_root,
        qualification_root=qualification_root,
        aggregation_refs={
            "cand-batch-a": "cand-batch-a.json",
            "cand-batch-b": "cand-batch-b.json",
        },
        policy=_policy(),
        evaluator_run_id="batch-oos-run-001",
        evaluator_version="batch-oos-v1",
        evaluated_at=START,
    )

    assert result.blocked_candidate_ids == ("cand-batch-a",)
    assert result.failures[0].reason_code == "qualification_artifact_conflict"
    assert result.evaluated_candidate_ids == ("cand-batch-b",)
    assert conflict_path.read_text(encoding="utf-8") == "{}"


def test_batch_result_rejects_non_positive_limit(tmp_path) -> None:
    with pytest.raises(DomainViolation, match="limit must be positive"):
        run_persisted_qualification_batch(
            registry_path=tmp_path / "unused-registry.json",
            candidate_artifact_root=tmp_path,
            aggregation_root=tmp_path,
            qualification_root=tmp_path,
            aggregation_refs={},
            policy=_policy(),
            evaluator_run_id="batch-oos-run-001",
            evaluator_version="batch-oos-v1",
            evaluated_at=START,
            limit=0,
        )
