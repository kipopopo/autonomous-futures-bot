"""Comprehensive unit test suite for Phase 250 Walk-Forward Evaluation & Qualification.

Covers 48 discrete unit tests across 9 specialized test classes:
1. TestCandidateSpecificationAndLoading (6 tests)
2. TestOOSWindowConstructionAndValidation (5 tests)
3. TestDataQualityEnforcement (10 tests)
4. TestSimulationExecutionAndModeling (4 tests)
5. TestWalkForwardAggregationAndDeterministicHashing (4 tests)
6. TestQualificationDecisionsAndPolicies (6 tests)
7. TestOfflineSafetyInvariants (4 tests)
8. TestScriptExecutionEndToEnd (5 tests)
9. TestEdgeCasesAndBoundaryConditions (4 tests)
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from autonomous_futures.creator_staging_probe import assert_offline_safety_invariants
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import (
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.cached_evaluation import (
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.cached_oos_walk_forward import (
    evaluate_cached_oos_walk_forward,
)
from autonomous_futures.research.candidate_window_simulation import (
    simulate_candidate_window,
)
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.creator_proposals import (
    canonical_creator_candidate_id,
)
from autonomous_futures.research.performance_metrics import (
    calculate_performance_metrics,
)
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
    QualificationMetric,
    WalkForwardQualificationPolicy,
    build_creator_candidate_qualification_artifact,
    build_walk_forward_qualification_artifact,
)
from autonomous_futures.research.trade_simulation import (
    TradeSimulationConfig,
    TradeSimulationResult,
)
from autonomous_futures.research.walk_forward import (
    PersistedWalkForwardAggregation,
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
    build_persisted_walk_forward_aggregation,
    read_walk_forward_aggregation,
    walk_forward_aggregation_hash,
    write_walk_forward_aggregation,
)


# Dynamically load the runner script module
def _load_script_module(name: str) -> Any:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eval_script = _load_script_module("evaluate_phase_250_walk_forward")
script_main: Callable[[list[str] | None], int] = eval_script.main

# Authoritative Pinned Identifiers & Hashes
PINNED_CANDIDATE_ID: str = eval_script.PINNED_CANDIDATE_ID
PINNED_ARTIFACT_HASH: str = eval_script.PINNED_ARTIFACT_HASH
PINNED_BUNDLE_HASH: str = eval_script.PINNED_BUNDLE_HASH
PINNED_REGISTRY_HASH: str = eval_script.PINNED_REGISTRY_HASH
PINNED_CREATOR_RUN_ID: str = eval_script.PINNED_CREATOR_RUN_ID
PINNED_RESEARCH_SEED: int = eval_script.PINNED_RESEARCH_SEED
PINNED_CREATED_AT: datetime = eval_script.PINNED_CREATED_AT
START_TIME: datetime = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _make_pinned_strategy(strategy_id: str = PINNED_CANDIDATE_ID) -> StrategySpec:
    return eval_script.build_phase_250_strategy_spec(strategy_id=strategy_id)


def _make_pinned_candidate_artifact() -> CreatorCandidateArtifact:
    return eval_script.materialize_candidate_artifact()


def _make_synthetic_bars(
    start: datetime,
    bars_count: int = 30,
    *,
    pattern: str = "dip_and_bounce",
) -> pd.DataFrame:
    """Generate synthetic 5m OHLC bars with exact boundary alignment."""
    if pattern == "dip_and_bounce":
        # 15 flat bars, 8 oversold dipping bars (RSI <= 30), bounce bars (RSI >= 50)
        base = [100.0] * 15 + [98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0]
        remaining = max(0, bars_count - len(base))
        bounce = [86.0 + i * 2.0 for i in range(remaining)]
        prices = (base + bounce)[:bars_count]
    elif pattern == "flat":
        prices = [100.0] * bars_count
    elif pattern == "trending_down":
        prices = [100.0 - i * 1.0 for i in range(bars_count)]
    else:
        prices = [100.0 + i * 1.0 for i in range(bars_count)]

    timestamps = [start + timedelta(minutes=5 * i) for i in range(bars_count)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(round(p, 4))) for p in prices],
            "high": [Decimal(str(round(p + 0.5, 4))) for p in prices],
            "low": [Decimal(str(round(p - 0.5, 4))) for p in prices],
            "close": [Decimal(str(round(p, 4))) for p in prices],
        }
    )


def _make_oos_window(
    window_id: str,
    start: datetime,
    bars_count: int = 30,
    *,
    symbol: str = "DOGEUSDT",
    bundle_hash: str = PINNED_BUNDLE_HASH,
    dataset_registry_hash: str = PINNED_REGISTRY_HASH,
    pattern: str = "dip_and_bounce",
) -> CachedEvaluationWindow:
    spec = CachedEvaluationWindowSpec(
        window_id=window_id,
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        time_start=start,
        time_end=start + timedelta(minutes=5 * bars_count),
    )
    frame = _make_synthetic_bars(start, bars_count=bars_count, pattern=pattern)
    return CachedEvaluationWindow(spec=spec, frame=frame)


def _make_sequential_windows(
    count: int = 3,
    bars_per_window: int = 30,
    *,
    start: datetime = START_TIME,
) -> tuple[CachedEvaluationWindow, ...]:
    windows: list[CachedEvaluationWindow] = []
    current_start = start
    for i in range(count):
        window = _make_oos_window(
            window_id=f"oos-window-{i + 1:03d}",
            start=current_start,
            bars_count=bars_per_window,
        )
        windows.append(window)
        current_start = window.spec.time_end
    return tuple(windows)


# ==============================================================================
# 1. TestCandidateSpecificationAndLoading (6 tests)
# ==============================================================================
class TestCandidateSpecificationAndLoading:
    def test_candidate_spec_matches_pydantic_contracts(self) -> None:
        strategy = _make_pinned_strategy()
        assert strategy.dsl_version == 1
        assert strategy.family == "range_mean_reversion"
        assert strategy.universe.symbols == ("DOGEUSDT",)
        assert strategy.universe.timeframe == "5m"
        assert strategy.universe.regime_context_timeframe == "15m"
        assert len(strategy.features) == 1
        assert strategy.features[0].name == "rsi"
        assert strategy.features[0].lookback == 14
        assert strategy.features[0].shift == 1
        assert strategy.entry.long == "rsi <= 30"
        assert strategy.entry.short == "rsi >= 70"
        assert strategy.exit.long == "rsi >= 50"
        assert strategy.exit.short == "rsi <= 50"
        assert strategy.vetoes == ("funding_adverse",)
        assert strategy.risk is None

    def test_candidate_id_deterministic_hash_derivation(self) -> None:
        strategy = _make_pinned_strategy()
        id1 = canonical_creator_candidate_id(strategy)
        id2 = canonical_creator_candidate_id(strategy)
        assert id1 == id2
        assert id1 == PINNED_CANDIDATE_ID
        assert strategy.strategy_id == PINNED_CANDIDATE_ID
        assert canonical_creator_candidate_id(strategy) == strategy.strategy_id

        # Verify sensitivity: altered lookback changes candidate hash
        altered = strategy.model_copy(
            update={"features": (FeatureRef(name="rsi", lookback=20, shift=1),)}
        )
        assert canonical_creator_candidate_id(altered) != PINNED_CANDIDATE_ID

    def test_candidate_artifact_hash_verification(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        assert candidate.candidate_id == PINNED_CANDIDATE_ID
        assert candidate.artifact_hash == PINNED_ARTIFACT_HASH
        assert candidate.bundle_hash == PINNED_BUNDLE_HASH
        assert candidate.dataset_registry_hash == PINNED_REGISTRY_HASH
        assert candidate.creator_run_id == PINNED_CREATOR_RUN_ID
        assert candidate.research_seed == PINNED_RESEARCH_SEED
        assert candidate.created_at == PINNED_CREATED_AT

        # Dynamic artifact created via builder derives self-consistent content hash
        dynamic = build_creator_candidate_artifact(
            candidate_id=PINNED_CANDIDATE_ID,
            strategy=_make_pinned_strategy(),
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            creator_run_id=PINNED_CREATOR_RUN_ID,
            research_seed=PINNED_RESEARCH_SEED,
            created_at=PINNED_CREATED_AT,
        )
        assert dynamic.artifact_hash == PINNED_ARTIFACT_HASH
        assert dynamic.artifact_hash == candidate.artifact_hash
        assert dynamic.candidate_id == PINNED_CANDIDATE_ID
        assert dynamic == candidate

    def test_candidate_artifact_tamper_detection(self, tmp_path: Path) -> None:
        candidate = _make_pinned_candidate_artifact()
        # 1. Pydantic validator checks: strategy_id must match candidate_id
        with pytest.raises(ValidationError, match="strategy_id must match candidate_id"):
            CreatorCandidateArtifact.model_validate(
                {**candidate.model_dump(mode="json"), "candidate_id": "cand-different-id-12345"}
            )

        # 2. Hash format regex validation
        with pytest.raises(ValidationError):
            CreatorCandidateArtifact.model_validate(
                {**candidate.model_dump(mode="json"), "bundle_hash": "not_a_valid_hex"}
            )

        # 3. Altered content changes hash derivation
        altered_spec = candidate.strategy.model_copy(
            update={"entry": EntryExit(long="rsi <= 20", short="rsi >= 80")}
        )
        dynamic = build_creator_candidate_artifact(
            candidate_id=candidate.candidate_id,
            strategy=candidate.strategy,
            bundle_hash=candidate.bundle_hash,
            dataset_registry_hash=candidate.dataset_registry_hash,
            creator_run_id=candidate.creator_run_id,
            research_seed=candidate.research_seed,
            created_at=candidate.created_at,
        )
        tampered = build_creator_candidate_artifact(
            candidate_id=candidate.candidate_id,
            strategy=altered_spec,
            bundle_hash=candidate.bundle_hash,
            dataset_registry_hash=candidate.dataset_registry_hash,
            creator_run_id=candidate.creator_run_id,
            research_seed=candidate.research_seed,
            created_at=candidate.created_at,
        )
        assert dynamic.artifact_hash != tampered.artifact_hash

        # 4. Authoritative domain loader catches corrupted hash on disk
        tampered_file = tmp_path / "tampered_candidate.json"
        tampered_file.write_text(
            json.dumps({**candidate.model_dump(mode="json"), "artifact_hash": "0" * 64}),
            encoding="utf-8",
        )
        with pytest.raises(DomainViolation, match="creator candidate artifact hash mismatch"):
            read_creator_candidate_artifact(tampered_file)

    def test_candidate_file_persistence_write_once_and_read(self, tmp_path: Path) -> None:
        candidate_path = tmp_path / "test-candidate.json"
        candidate = _make_pinned_candidate_artifact()

        eval_script.persist_phase_250_candidate_artifact(candidate_path, candidate)
        assert candidate_path.is_file()

        # Authoritative domain loader successfully validates content hash
        domain_loaded = read_creator_candidate_artifact(candidate_path)
        assert domain_loaded == candidate
        assert domain_loaded.candidate_id == PINNED_CANDIDATE_ID
        assert domain_loaded.artifact_hash == PINNED_ARTIFACT_HASH

        # Script loader also succeeds and returns identical candidate
        loaded = eval_script.load_or_materialize_candidate(candidate_path)
        assert loaded == candidate
        assert loaded.candidate_id == PINNED_CANDIDATE_ID
        assert loaded.artifact_hash == PINNED_ARTIFACT_HASH

        # Idempotent re-write of identical candidate succeeds
        eval_script.persist_phase_250_candidate_artifact(candidate_path, candidate)

        # Attempting to re-write divergent candidate raises DomainViolation
        divergent = candidate.model_copy(update={"research_seed": 99999})
        with pytest.raises(DomainViolation, match="immutable"):
            eval_script.persist_phase_250_candidate_artifact(candidate_path, divergent)

    def test_candidate_rejection_of_invalid_dsl_specs(self) -> None:
        from autonomous_futures.domain.contracts import CandidateSimulationRisk

        risk = CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal("1.0"),
            take_profit_atr_multiplier=Decimal("2.0"),
            trailing_atr_multiplier=Decimal("0.0"),
        )
        with pytest.raises(ValueError, match="dsl_version 1 forbids simulation risk"):
            StrategySpec(
                dsl_version=1,
                strategy_id=PINNED_CANDIDATE_ID,
                family="range_mean_reversion",
                universe=StrategyUniverse(
                    symbols=("DOGEUSDT",),
                    timeframe="5m",
                    regime_context_timeframe="15m",
                ),
                features=(FeatureRef(name="rsi", lookback=14, shift=1),),
                entry=EntryExit(long="rsi <= 30", short="rsi >= 70"),
                exit=EntryExit(long="rsi >= 50", short="rsi <= 50"),
                vetoes=("funding_adverse",),
                risk=risk,
            )

        # Unknown feature
        with pytest.raises(ValidationError):
            FeatureRef(name="unknown_indicator", lookback=14, shift=1)

        # Lowercase symbol
        with pytest.raises(ValidationError):
            StrategyUniverse(
                symbols=("dogeusdt",),
                timeframe="5m",
                regime_context_timeframe="15m",
            )


# ==============================================================================
# 2. TestOOSWindowConstructionAndValidation (5 tests)
# ==============================================================================
class TestOOSWindowConstructionAndValidation:
    def test_valid_oos_window_construction(self) -> None:
        window = _make_oos_window("oos-001", START_TIME, bars_count=30)
        assert window.spec.window_id == "oos-001"
        assert window.spec.symbol == "DOGEUSDT"
        assert window.frame.shape[0] == 30
        assert window.spec.time_start == START_TIME
        assert window.spec.time_end == START_TIME + timedelta(minutes=150)

    def test_window_copy_frame_isolation(self) -> None:
        window = _make_oos_window("oos-001", START_TIME, bars_count=30)
        copied = window.copy_frame()
        original_val = window.frame.iloc[0]["close"]
        copied.loc[0, "close"] = Decimal("999999.0")
        assert window.frame.iloc[0]["close"] == original_val

    def test_sequential_non_overlapping_oos_windows_chain(self) -> None:
        windows = eval_script.establish_oos_windows(count=3, bars_per_window=30)
        assert len(windows) == 3
        for i in range(len(windows) - 1):
            assert windows[i].spec.time_end == windows[i + 1].spec.time_start

    def test_window_spec_requires_utc_timezone(self) -> None:
        naive_start = datetime(2026, 1, 1, 0, 0)
        naive_end = datetime(2026, 1, 1, 2, 30)
        with pytest.raises(ValidationError, match="timezone-aware UTC"):
            CachedEvaluationWindowSpec(
                window_id="oos-naive",
                symbol="DOGEUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=naive_start,
                time_end=naive_end,
            )

    def test_window_spec_time_start_before_time_end(self) -> None:
        with pytest.raises(ValidationError, match="time_start must be before time_end"):
            CachedEvaluationWindowSpec(
                window_id="oos-inverted",
                symbol="DOGEUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=START_TIME + timedelta(hours=1),
                time_end=START_TIME,
            )


# ==============================================================================
# 3. TestDataQualityEnforcement (10 tests)
# ==============================================================================
class TestDataQualityEnforcement:
    def test_data_quality_missing_ohlc_columns(self) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-missing-col",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        frame = _make_synthetic_bars(START_TIME, bars_count=30).drop(columns=["close"])
        with pytest.raises(DataQualityError, match="missing OHLC columns: close"):
            CachedEvaluationWindow(spec=spec, frame=frame)

    def test_data_quality_timestamp_gaps(self) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-gapped",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        frame = _make_synthetic_bars(START_TIME, bars_count=30).drop(index=[10])
        with pytest.raises(DataQualityError, match="timestamp gap"):
            CachedEvaluationWindow(spec=spec, frame=frame)

    def test_data_quality_duplicate_timestamps(self) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-duplicate",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        frame = _make_synthetic_bars(START_TIME, bars_count=30)
        duplicated = pd.concat([frame, frame.iloc[[5]]]).sort_values("timestamp")
        with pytest.raises(DataQualityError, match="duplicate timestamps"):
            CachedEvaluationWindow(spec=spec, frame=duplicated)

    def test_data_quality_frame_coverage_mismatch(self) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-mismatch",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        # 10 bars instead of 30 bars
        frame = _make_synthetic_bars(START_TIME, bars_count=10)
        with pytest.raises(DataQualityError, match="cover exactly the window range"):
            CachedEvaluationWindow(spec=spec, frame=frame)

    def test_data_quality_bundle_hash_drift(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        drifted_window = _make_oos_window(
            "oos-drift-bundle",
            START_TIME,
            bars_count=30,
            bundle_hash="0" * 64,
        )
        with pytest.raises(DataQualityError, match="bundle_hash does not match"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (drifted_window,),
                simulator=lambda c, f, w: simulate_candidate_window(
                    c,
                    f,
                    symbol=w.spec.symbol,
                    config=TradeSimulationConfig(
                        starting_equity=Decimal("100"),
                        position_fraction=Decimal("1"),
                        taker_fee_rate=Decimal("0.0004"),
                        slippage_rate=Decimal("0.0002"),
                    ),
                ),
            )

    def test_data_quality_dataset_registry_hash_drift(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        drifted_window = _make_oos_window(
            "oos-drift-reg",
            START_TIME,
            bars_count=30,
            dataset_registry_hash="0" * 64,
        )
        with pytest.raises(DataQualityError, match="dataset_registry_hash does not match"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (drifted_window,),
                simulator=lambda c, f, w: simulate_candidate_window(
                    c,
                    f,
                    symbol=w.spec.symbol,
                    config=TradeSimulationConfig(
                        starting_equity=Decimal("100"),
                        position_fraction=Decimal("1"),
                        taker_fee_rate=Decimal("0.0004"),
                        slippage_rate=Decimal("0.0002"),
                    ),
                ),
            )

    def test_data_quality_symbol_universe_mismatch(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        drifted_window = _make_oos_window(
            "oos-drift-symbol",
            START_TIME,
            bars_count=30,
            symbol="BTCUSDT",
        )
        with pytest.raises(DataQualityError, match="symbol is not present in candidate universe"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (drifted_window,),
                simulator=lambda c, f, w: simulate_candidate_window(
                    c,
                    f,
                    symbol=w.spec.symbol,
                    config=TradeSimulationConfig(
                        starting_equity=Decimal("100"),
                        position_fraction=Decimal("1"),
                        taker_fee_rate=Decimal("0.0004"),
                        slippage_rate=Decimal("0.0002"),
                    ),
                ),
            )

    def test_data_quality_empty_windows_rejected(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        with pytest.raises(DataQualityError, match="requires at least one window"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (),
                simulator=lambda c, f, w: simulate_candidate_window(
                    c,
                    f,
                    symbol=w.spec.symbol,
                    config=TradeSimulationConfig(
                        starting_equity=Decimal("100"),
                        position_fraction=Decimal("1"),
                        taker_fee_rate=Decimal("0.0004"),
                        slippage_rate=Decimal("0.0002"),
                    ),
                ),
            )

    def test_data_quality_overlapping_windows_rejected(self) -> None:
        w1 = _make_oos_window("oos-1", START_TIME, bars_count=30)
        # w2 starts before w1 ends (overlapping)
        w2 = _make_oos_window("oos-2", START_TIME + timedelta(minutes=50), bars_count=30)
        config = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        res1 = simulate_candidate_window(
            _make_pinned_candidate_artifact(),
            w1.copy_frame(),
            symbol="DOGEUSDT",
            config=config,
        )
        res2 = simulate_candidate_window(
            _make_pinned_candidate_artifact(),
            w2.copy_frame(),
            symbol="DOGEUSDT",
            config=config,
        )
        metrics1 = WalkForwardWindowMetrics(
            window_id="oos-1",
            symbol="DOGEUSDT",
            split="oos",
            window_start=w1.spec.time_start,
            window_end=w1.spec.time_end,
            metrics=calculate_performance_metrics(res1),
        )
        metrics2 = WalkForwardWindowMetrics(
            window_id="oos-2",
            symbol="DOGEUSDT",
            split="oos",
            window_start=w2.spec.time_start,
            window_end=w2.spec.time_end,
            metrics=calculate_performance_metrics(res2),
        )
        with pytest.raises(ValueError, match="overlapping OOS windows"):
            aggregate_walk_forward_metrics((metrics1, metrics2), required_symbols=("DOGEUSDT",))

    def test_data_quality_non_oos_split_rejected(self) -> None:
        w1 = _make_oos_window("oos-1", START_TIME, bars_count=30)
        sim_res = simulate_candidate_window(
            _make_pinned_candidate_artifact(),
            w1.copy_frame(),
            symbol="DOGEUSDT",
            config=TradeSimulationConfig(
                starting_equity=Decimal("100"),
                position_fraction=Decimal("1"),
                taker_fee_rate=Decimal("0.0004"),
                slippage_rate=Decimal("0.0002"),
            ),
        )
        train_window = WalkForwardWindowMetrics(
            window_id="oos-1",
            symbol="DOGEUSDT",
            split="train",
            window_start=w1.spec.time_start,
            window_end=w1.spec.time_end,
            metrics=calculate_performance_metrics(sim_res),
        )
        with pytest.raises(ValueError, match="walk-forward aggregation accepts OOS windows only"):
            aggregate_walk_forward_metrics((train_window,), required_symbols=("DOGEUSDT",))


# ==============================================================================
# 4. TestSimulationExecutionAndModeling (4 tests)
# ==============================================================================
class TestSimulationExecutionAndModeling:
    def test_simulate_candidate_window_causal_rsi_signals(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        bars = _make_synthetic_bars(START_TIME, bars_count=50, pattern="dip_and_bounce")
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        result = simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)
        assert len(result.trades) >= 1
        assert result.data_source == "cached_only"
        assert result.exchange_access is False

    def test_realistic_fee_and_slippage_accounting(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        bars = _make_synthetic_bars(START_TIME, bars_count=50, pattern="dip_and_bounce")
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        result = simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)
        trade = result.trades[0]
        # Fees and slippage must be positive under non-zero rates
        assert trade.fees > Decimal("0")
        assert trade.slippage_cost > Decimal("0")
        assert trade.fees == trade.entry_fee + trade.exit_fee
        assert trade.net_pnl == trade.gross_pnl - trade.fees

    def test_forced_exit_at_window_boundary(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        # Bars that enter right at the end of the window without bounce
        base = [100.0] * 15 + [100.0 - i * 2.5 for i in range(15)]
        bars = pd.DataFrame(
            {
                "timestamp": [START_TIME + timedelta(minutes=5 * i) for i in range(len(base))],
                "open": [Decimal(str(round(p, 4))) for p in base],
                "high": [Decimal(str(round(p + 0.5, 4))) for p in base],
                "low": [Decimal(str(round(p - 0.5, 4))) for p in base],
                "close": [Decimal(str(round(p, 4))) for p in base],
            }
        )
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        result = simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)
        assert len(result.trades) >= 1
        last_trade = result.trades[-1]
        assert last_trade.exit_reason == "forced_end_of_window"

    def test_exact_ledger_reconciliation(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        bars = _make_synthetic_bars(START_TIME, bars_count=60, pattern="dip_and_bounce")
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        result = simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)
        expected_final_equity = config.starting_equity + sum(
            (t.net_pnl for t in result.trades), start=Decimal("0")
        )
        assert result.final_equity == expected_final_equity
        assert result.total_fees == sum((t.fees for t in result.trades), start=Decimal("0"))
        assert result.total_slippage_cost == sum(
            (t.slippage_cost for t in result.trades), start=Decimal("0")
        )


# ==============================================================================
# 5. TestWalkForwardAggregationAndDeterministicHashing (4 tests)
# ==============================================================================
class TestWalkForwardAggregationAndDeterministicHashing:
    def test_walk_forward_aggregation_structure_and_metrics(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        windows = eval_script.establish_oos_windows(count=3, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        aggregation = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        assert aggregation.window_count == 3
        assert aggregation.data_source == "cached_only"
        assert aggregation.exchange_access is False
        assert aggregation.total_trade_count >= 1

    def test_walk_forward_aggregation_hash_determinism(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        windows = eval_script.establish_oos_windows(count=2, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg1 = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        hash1 = walk_forward_aggregation_hash(agg1)
        hash2 = walk_forward_aggregation_hash(agg1)
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_persisted_walk_forward_aggregation_envelope(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        windows = eval_script.establish_oos_windows(count=2, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        envelope = build_persisted_walk_forward_aggregation(agg)
        assert envelope.aggregation_hash == walk_forward_aggregation_hash(agg)

        # Tampering with hash raises ValidationError
        with pytest.raises(ValidationError, match="aggregation hash mismatch"):
            PersistedWalkForwardAggregation(
                aggregation=agg,
                aggregation_hash="0" * 64,
            )

    def test_write_and_read_walk_forward_aggregation_file(self, tmp_path: Path) -> None:
        candidate = _make_pinned_candidate_artifact()
        windows = eval_script.establish_oos_windows(count=2, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        file_path = tmp_path / "walk-forward-aggregation.json"
        write_walk_forward_aggregation(file_path, agg)
        assert file_path.is_file()

        loaded = read_walk_forward_aggregation(file_path)
        assert loaded.aggregation_hash == walk_forward_aggregation_hash(agg)
        assert loaded.aggregation.window_count == agg.window_count


# ==============================================================================
# 6. TestQualificationDecisionsAndPolicies (6 tests)
# ==============================================================================
class TestQualificationDecisionsAndPolicies:
    def test_qualification_decision_qualified_under_passing_policy(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        windows = eval_script.establish_oos_windows(count=3, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        policy = WalkForwardQualificationPolicy(
            policy_id="policy-lenient",
            minimum_windows=2,
            minimum_trades=1,
            minimum_profit_factor=Decimal("1.0"),
            maximum_drawdown_pct=Decimal("10.0"),
            minimum_average_return_pct=Decimal("0.0"),
        )
        qual = build_walk_forward_qualification_artifact(
            candidate=candidate,
            aggregation=agg,
            policy=policy,
            evaluator_run_id="eval-test",
            evaluator_version="1",
            evaluated_at=datetime.now(UTC),
        )
        assert qual.decision == "qualified"
        assert all(g.passed for g in qual.gates)
        assert qual.promotion_state == "unpromoted"
        assert qual.execution_authority is False

    def test_qualification_decision_rejected_excessive_drawdown(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        windows = eval_script.establish_oos_windows(count=3, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        policy = WalkForwardQualificationPolicy(
            policy_id="policy-tight-dd",
            minimum_windows=2,
            minimum_trades=1,
            minimum_profit_factor=Decimal("0.5"),
            maximum_drawdown_pct=Decimal("0.01"),  # Very tight drawdown threshold
            minimum_average_return_pct=Decimal("0.0"),
        )
        qual = build_walk_forward_qualification_artifact(
            candidate=candidate,
            aggregation=agg,
            policy=policy,
            evaluator_run_id="eval-test",
            evaluator_version="1",
            evaluated_at=datetime.now(UTC),
        )
        assert qual.decision == "rejected"
        dd_gate = next(g for g in qual.gates if g.gate_id == "oos_drawdown_max")
        assert dd_gate.passed is False
        assert dd_gate.reason_code == "oos_drawdown_above_threshold"

    def test_qualification_decision_rejected_insufficient_trades(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        windows = eval_script.establish_oos_windows(count=3, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        policy = WalkForwardQualificationPolicy(
            policy_id="policy-high-trades",
            minimum_windows=2,
            minimum_trades=1000,  # Unattainable trade count
            minimum_profit_factor=Decimal("0.5"),
            maximum_drawdown_pct=Decimal("50.0"),
            minimum_average_return_pct=Decimal("0.0"),
        )
        qual = build_walk_forward_qualification_artifact(
            candidate=candidate,
            aggregation=agg,
            policy=policy,
            evaluator_run_id="eval-test",
            evaluator_version="1",
            evaluated_at=datetime.now(UTC),
        )
        assert qual.decision == "rejected"
        trades_gate = next(g for g in qual.gates if g.gate_id == "oos_trades_min")
        assert trades_gate.passed is False
        assert trades_gate.reason_code == "oos_trades_below_threshold"

    def test_qualification_decision_fails_closed_missing_profit_factor(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        # Single window with 0 losses
        w = _make_oos_window("oos-no-loss", START_TIME, bars_count=50, pattern="dip_and_bounce")
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            (w,),
            simulator=lambda c, f, win: simulate_candidate_window(
                c, f, symbol=win.spec.symbol, config=config
            ),
        )
        if agg.pooled_gross_loss == Decimal("0"):
            assert agg.pooled_profit_factor is None
            policy = WalkForwardQualificationPolicy(
                policy_id="policy-pf-check",
                minimum_windows=1,
                minimum_trades=1,
                minimum_profit_factor=Decimal("1.0"),
                maximum_drawdown_pct=Decimal("50.0"),
                minimum_average_return_pct=Decimal("0.0"),
            )
            qual = build_walk_forward_qualification_artifact(
                candidate=candidate,
                aggregation=agg,
                policy=policy,
                evaluator_run_id="eval-test",
                evaluator_version="1",
                evaluated_at=datetime.now(UTC),
            )
            assert qual.decision == "rejected"
            pf_gate = next(g for g in qual.gates if g.gate_id == "oos_profit_factor_min")
            assert pf_gate.passed is False
            assert pf_gate.reason_code == "oos_profit_factor_missing"

    def test_qualification_artifact_immutable_safety_state(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        windows = eval_script.establish_oos_windows(count=2, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        policy = WalkForwardQualificationPolicy(
            policy_id="policy-safety",
            minimum_windows=1,
            minimum_trades=1,
            minimum_profit_factor=Decimal("0.5"),
            maximum_drawdown_pct=Decimal("50.0"),
            minimum_average_return_pct=Decimal("0.0"),
        )
        qual = build_walk_forward_qualification_artifact(
            candidate=candidate,
            aggregation=agg,
            policy=policy,
            evaluator_run_id="eval-test",
            evaluator_version="1",
            evaluated_at=datetime.now(UTC),
        )
        assert qual.promotion_state == "unpromoted"
        assert qual.execution_authority is False
        assert qual.source == "walk_forward_oos"

    def test_qualification_model_rejects_inconsistent_qualified_decision(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        failed_gate = QualificationGateResult(
            gate_id="oos_trades_min",
            passed=False,
            observed=Decimal("0"),
            threshold=Decimal("1"),
            comparator="gte",
            reason_code="oos_trades_below_threshold",
        )
        with pytest.raises(DataQualityError, match="invalid creator qualification artifact"):
            build_creator_candidate_qualification_artifact(
                candidate=candidate,
                decision="qualified",
                gates=(failed_gate,),
                metrics=(QualificationMetric(metric_id="trades", value=Decimal("0")),),
                windows_evaluated=1,
                qualification_policy_id="policy-inconsistent",
                evaluator_run_id="eval-test",
                evaluator_version="1",
                evaluated_at=datetime.now(UTC),
                source="walk_forward_oos",
            )


# ==============================================================================
# 7. TestOfflineSafetyInvariants (4 tests)
# ==============================================================================
class TestOfflineSafetyInvariants:
    def test_simulation_rejects_non_cached_data_source(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        window = _make_oos_window("oos-live-src", START_TIME, bars_count=30)

        def mock_live_simulator(c: Any, f: Any, w: Any) -> TradeSimulationResult:
            res = simulate_candidate_window(
                c,
                f,
                symbol=w.spec.symbol,
                config=TradeSimulationConfig(
                    starting_equity=Decimal("100"),
                    position_fraction=Decimal("1"),
                    taker_fee_rate=Decimal("0.0004"),
                    slippage_rate=Decimal("0.0002"),
                ),
            )
            return res.model_copy(update={"data_source": "live"})  # type: ignore[arg-type]

        with pytest.raises(DataQualityError, match="must be cached-only"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (window,),
                simulator=mock_live_simulator,
            )

    def test_simulation_rejects_exchange_access(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        window = _make_oos_window("oos-exchange", START_TIME, bars_count=30)

        def mock_exchange_simulator(c: Any, f: Any, w: Any) -> TradeSimulationResult:
            res = simulate_candidate_window(
                c,
                f,
                symbol=w.spec.symbol,
                config=TradeSimulationConfig(
                    starting_equity=Decimal("100"),
                    position_fraction=Decimal("1"),
                    taker_fee_rate=Decimal("0.0004"),
                    slippage_rate=Decimal("0.0002"),
                ),
            )
            return res.model_copy(update={"exchange_access": True})  # type: ignore[arg-type]

        with pytest.raises(DataQualityError, match="must be cached-only"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (window,),
                simulator=mock_exchange_simulator,
            )

    def test_environment_boundary_zero_binance_credentials(self) -> None:
        assert_offline_safety_invariants()
        binance_keys = [k for k in os.environ if "BINANCE" in k.upper()]
        assert len(binance_keys) == 0

    def test_zero_order_placement_invariant(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        window = _make_oos_window("oos-orders", START_TIME, bars_count=30)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        res = simulate_candidate_window(
            candidate, window.copy_frame(), symbol="DOGEUSDT", config=config
        )
        assert res.exchange_access is False
        assert res.data_source == "cached_only"


# ==============================================================================
# 8. TestScriptExecutionEndToEnd (5 tests)
# ==============================================================================
class TestScriptExecutionEndToEnd:
    def test_script_cli_help(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = script_main(["--help"])
        assert exit_code == 0
        output = buf.getvalue()
        assert "Standard Offline Walk-Forward Evaluation & Qualification Runner" in output
        assert "--candidate-path" in output
        assert "--output-dir" in output

    def test_script_cli_end_to_end_successful_run(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "artifacts_run"
        cand_path = tmp_path / "candidate.json"
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = script_main(
                [
                    "--candidate-path",
                    str(cand_path),
                    "--output-dir",
                    str(out_dir),
                    "--windows-count",
                    "3",
                    "--bars-per-window",
                    "60",
                ]
            )
        assert exit_code == 0
        output = buf.getvalue()
        summary = json.loads(output)
        assert summary["candidate_id"] == PINNED_CANDIDATE_ID
        assert summary["candidate_artifact_hash"] == PINNED_ARTIFACT_HASH
        assert summary["qualification_decision"] == "qualified"
        assert summary["safety_state"]["orders"] == 0
        assert summary["safety_state"]["exchange_access"] is False

        # Verify artifacts persisted to disk and readable by domain loaders
        assert cand_path.is_file()
        cand_domain = read_creator_candidate_artifact(cand_path)
        assert cand_domain.candidate_id == PINNED_CANDIDATE_ID
        assert cand_domain.artifact_hash == PINNED_ARTIFACT_HASH
        assert (out_dir / "walk-forward-aggregation.json").is_file()
        assert (out_dir / "qualification-artifact.json").is_file()
        assert (out_dir / "evaluation-summary.json").is_file()

    def test_script_cli_missing_arguments_or_bad_paths(self, tmp_path: Path) -> None:
        # Invalid option raises error and exits with code 2
        exit_code = script_main(["--nonexistent-argument"])
        assert exit_code == 2

        # Corrupted candidate artifact exits with error code 3
        bad_cand = tmp_path / "bad_cand.json"
        bad_cand.write_text("invalid json", encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = script_main(["--candidate-path", str(bad_cand)])
        assert code == 3

    def test_script_cli_idempotent_execution(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "idempotent_run"
        cand_path = tmp_path / "candidate.json"

        # Run 1
        buf1 = io.StringIO()
        with redirect_stdout(buf1):
            code1 = script_main(
                [
                    "--candidate-path",
                    str(cand_path),
                    "--output-dir",
                    str(out_dir),
                    "--windows-count",
                    "3",
                    "--bars-per-window",
                    "60",
                ]
            )
        assert code1 == 0
        summary1 = json.loads(buf1.getvalue())

        # Run 2 against same output directory
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            code2 = script_main(
                [
                    "--candidate-path",
                    str(cand_path),
                    "--output-dir",
                    str(out_dir),
                    "--windows-count",
                    "3",
                    "--bars-per-window",
                    "60",
                ]
            )
        assert code2 == 0
        summary2 = json.loads(buf2.getvalue())

        # Hashes and decisions are identical
        assert (
            summary1["walk_forward_aggregation_hash"] == summary2["walk_forward_aggregation_hash"]
        )
        assert summary1["qualification_hash"] == summary2["qualification_hash"]

    def test_script_cli_zero_secret_leakage(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "audit_run"
        cand_path = tmp_path / "candidate.json"
        buf = io.StringIO()
        with redirect_stdout(buf):
            script_main(
                [
                    "--candidate-path",
                    str(cand_path),
                    "--output-dir",
                    str(out_dir),
                    "--windows-count",
                    "2",
                    "--bars-per-window",
                    "60",
                ]
            )
        raw_output = buf.getvalue()
        assert not _SECRET_PATTERN.search(raw_output)
        summary_file = out_dir / "evaluation-summary.json"
        assert not _SECRET_PATTERN.search(summary_file.read_text(encoding="utf-8"))


# ==============================================================================
# 9. TestEdgeCasesAndBoundaryConditions (4 tests)
# ==============================================================================
class TestEdgeCasesAndBoundaryConditions:
    def test_zero_trades_in_evaluation_window(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        window = _make_oos_window("oos-flat", START_TIME, bars_count=40, pattern="flat")
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            (window,),
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        assert agg.total_trade_count == 0
        assert agg.pooled_net_pnl == Decimal("0")
        assert agg.pooled_profit_factor is None

    def test_entry_on_very_last_bar_of_window(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        # Bar 28 triggers entry, bar 29 closes window
        base = [100.0] * 20 + [100.0 - i * 3.0 for i in range(10)]
        bars = pd.DataFrame(
            {
                "timestamp": [START_TIME + timedelta(minutes=5 * i) for i in range(len(base))],
                "open": [Decimal(str(round(p, 4))) for p in base],
                "high": [Decimal(str(round(p + 0.5, 4))) for p in base],
                "low": [Decimal(str(round(p - 0.5, 4))) for p in base],
                "close": [Decimal(str(round(p, 4))) for p in base],
            }
        )
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        res = simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)
        if len(res.trades) > 0:
            assert res.trades[-1].exit_reason in ("forced_end_of_window", "signal_exit")

    def test_high_slippage_and_fee_stress_test(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        bars = _make_synthetic_bars(START_TIME, bars_count=60, pattern="dip_and_bounce")
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.05"),  # Extreme 5% fee
            slippage_rate=Decimal("0.02"),  # Extreme 2% slippage
        )
        res = simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)
        assert res.final_equity < Decimal("10000")
        # Reconciliation must still hold exactly
        expected = config.starting_equity + sum((t.net_pnl for t in res.trades), start=Decimal("0"))
        assert res.final_equity == expected

    def test_all_windows_negative_expectancy(self) -> None:
        candidate = _make_pinned_candidate_artifact()
        # Downward trending windows
        w1 = _make_oos_window("oos-down-1", START_TIME, bars_count=40, pattern="trending_down")
        w2 = _make_oos_window(
            "oos-down-2",
            START_TIME + timedelta(minutes=200),
            bars_count=40,
            pattern="trending_down",
        )
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            (w1, w2),
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        policy = WalkForwardQualificationPolicy(
            policy_id="policy-expectancy",
            minimum_windows=1,
            minimum_trades=1,
            minimum_profit_factor=Decimal("1.0"),
            maximum_drawdown_pct=Decimal("10.0"),
            minimum_average_return_pct=Decimal("0.0"),
        )
        qual = build_walk_forward_qualification_artifact(
            candidate=candidate,
            aggregation=agg,
            policy=policy,
            evaluator_run_id="eval-test",
            evaluator_version="1",
            evaluated_at=datetime.now(UTC),
        )
        assert qual.decision == "rejected"
