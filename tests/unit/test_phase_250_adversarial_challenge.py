"""Phase 250 Empirical Adversarial Challenge Test Suite.

Authoritative stress-testing of evaluate_phase_250_walk_forward.py and walk-forward
pipeline under adversarial conditions:
1. Extreme fees (50%, 100%, >100%) and negative balance / bankruptcy defense.
2. Extreme slippage rates (50%, 100%, >100%) and ledger reconciliation.
3. Massive window counts (50, 100 windows) and minimum window boundaries.
4. Corrupted and gapped candle data (asserting DataQualityError triggers reliably).
5. Inverted time boundaries and non-UTC timestamps.
6. Cryptographic hash drift (bundle_hash, dataset_registry_hash, artifact_hash).
7. CLI resilience, error sanitization, and secret leakage prevention.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
from pydantic import ValidationError

from autonomous_futures.creator_staging_probe import assert_offline_safety_invariants
from autonomous_futures.data.parquet import DataQualityError
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
)
from autonomous_futures.research.performance_metrics import (
    calculate_performance_metrics,
)
from autonomous_futures.research.qualification_artifacts import (
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
    read_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from autonomous_futures.research.trade_simulation import (
    EquityPoint,
    TradeSimulationConfig,
    simulate_cached_signals,
)
from autonomous_futures.research.walk_forward import (
    WalkForwardWindowMetrics,
    aggregate_walk_forward_metrics,
    read_walk_forward_aggregation,
    walk_forward_aggregation_hash,
    write_walk_forward_aggregation,
)


def _load_script_module(name: str) -> Any:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eval_script = _load_script_module("evaluate_phase_250_walk_forward")
script_main: Callable[[list[str] | None], int] = eval_script.main

PINNED_CANDIDATE_ID: str = eval_script.PINNED_CANDIDATE_ID
PINNED_ARTIFACT_HASH: str = eval_script.PINNED_ARTIFACT_HASH
PINNED_BUNDLE_HASH: str = eval_script.PINNED_BUNDLE_HASH
PINNED_REGISTRY_HASH: str = eval_script.PINNED_REGISTRY_HASH
PINNED_CREATOR_RUN_ID: str = eval_script.PINNED_CREATOR_RUN_ID
PINNED_RESEARCH_SEED: int = eval_script.PINNED_RESEARCH_SEED
PINNED_CREATED_AT: datetime = eval_script.PINNED_CREATED_AT
START_TIME: datetime = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

CANARY_SECRET = "AIzaSyDTESTINGSECRETKEY012345678901234"
CANARY_BEARER = "ya29.a0AfH6SMADVERSARIAL_BEARER_TOKEN_VALUE"
_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _make_candidate() -> CreatorCandidateArtifact:
    return eval_script.materialize_candidate_artifact()


def _make_bars(
    start: datetime,
    bars_count: int = 60,
    *,
    pattern: str = "dip_and_bounce",
) -> pd.DataFrame:
    if pattern == "dip_and_bounce":
        base = [100.0] * 15 + [100.0 - i * 2.5 for i in range(10)]
        remaining = max(0, bars_count - len(base))
        bounce = [75.0 + i * 2.0 for i in range(remaining)]
        prices = (base + bounce)[:bars_count]
    elif pattern == "collapse":
        prices = [max(1.0, 100.0 - i * 3.0) for i in range(bars_count)]
    elif pattern == "flat":
        prices = [100.0] * bars_count
    else:
        prices = [100.0 + i * 0.5 for i in range(bars_count)]

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


def _make_window(
    window_id: str,
    start: datetime,
    bars_count: int = 60,
    *,
    pattern: str = "dip_and_bounce",
    bundle_hash: str = PINNED_BUNDLE_HASH,
    dataset_registry_hash: str = PINNED_REGISTRY_HASH,
    symbol: str = "DOGEUSDT",
) -> CachedEvaluationWindow:
    spec = CachedEvaluationWindowSpec(
        window_id=window_id,
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        time_start=start,
        time_end=start + timedelta(minutes=5 * bars_count),
    )
    frame = _make_bars(start, bars_count=bars_count, pattern=pattern)
    return CachedEvaluationWindow(spec=spec, frame=frame)


# ==============================================================================
# 1. TestAdversarialExtremeFeesAndBankruptcy (6 tests)
# ==============================================================================
class TestAdversarialExtremeFeesAndBankruptcy:
    def test_fee_rate_above_100_percent_rejected_by_config(self) -> None:
        with pytest.raises(ValidationError, match="less than or equal to 1"):
            TradeSimulationConfig(
                starting_equity=Decimal("10000"),
                position_fraction=Decimal("0.1"),
                taker_fee_rate=Decimal("1.01"),
                slippage_rate=Decimal("0.0002"),
            )

    def test_negative_fee_rate_rejected_by_config(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            TradeSimulationConfig(
                starting_equity=Decimal("10000"),
                position_fraction=Decimal("0.1"),
                taker_fee_rate=Decimal("-0.0001"),
                slippage_rate=Decimal("0.0002"),
            )

    def test_entry_fee_exceeding_cash_raises_data_quality_error(self) -> None:
        candidate = _make_candidate()
        window = _make_window("fee-over-cash", START_TIME, bars_count=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1.0"),
            taker_fee_rate=Decimal("1.0"),
            slippage_rate=Decimal("0.05"),
        )
        with pytest.raises(DataQualityError, match="entry fee exceeds available simulation equity"):
            simulate_candidate_window(
                candidate, window.copy_frame(), symbol="DOGEUSDT", config=config
            )

    def test_50_percent_taker_fee_produces_severe_drag_and_fails_qualification(self) -> None:
        candidate = _make_candidate()
        windows = eval_script.establish_oos_windows(count=3, bars_per_window=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.50"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=config
            ),
        )
        assert agg.pooled_net_pnl < Decimal("0")
        assert agg.worst_max_drawdown_pct > Decimal("10.0")

        policy = WalkForwardQualificationPolicy(
            policy_id="policy-adv-fee",
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
            evaluator_run_id="eval-fee-test",
            evaluator_version="1",
            evaluated_at=datetime.now(UTC),
        )
        assert qual.decision == "rejected"
        failed_gates = [g.gate_id for g in qual.gates if not g.passed]
        assert "oos_drawdown_max" in failed_gates
        assert "oos_average_return_min" in failed_gates

    def test_negative_equity_prevented_by_equity_point_model(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            EquityPoint(timestamp=START_TIME, equity=Decimal("-1.00"))

    def test_zero_fee_and_zero_slippage_frictionless_ledger(self) -> None:
        candidate = _make_candidate()
        window = _make_window("frictionless", START_TIME, bars_count=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0"),
            slippage_rate=Decimal("0.0"),
        )
        res = simulate_candidate_window(
            candidate, window.copy_frame(), symbol="DOGEUSDT", config=config
        )
        assert len(res.trades) >= 1
        assert res.total_fees == Decimal("0")
        assert res.total_slippage_cost == Decimal("0")
        for t in res.trades:
            assert t.fees == Decimal("0")
            assert t.slippage_cost == Decimal("0")
            assert t.net_pnl == t.gross_pnl
        assert res.final_equity == config.starting_equity + sum(
            (t.net_pnl for t in res.trades), Decimal("0")
        )


# ==============================================================================
# 2. TestAdversarialExtremeSlippage (4 tests)
# ==============================================================================
class TestAdversarialExtremeSlippage:
    def test_slippage_rate_above_100_percent_rejected(self) -> None:
        with pytest.raises(ValidationError, match="less than or equal to 1"):
            TradeSimulationConfig(
                starting_equity=Decimal("10000"),
                position_fraction=Decimal("0.1"),
                taker_fee_rate=Decimal("0.0004"),
                slippage_rate=Decimal("1.50"),
            )

    def test_negative_slippage_rate_rejected(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            TradeSimulationConfig(
                starting_equity=Decimal("10000"),
                position_fraction=Decimal("0.1"),
                taker_fee_rate=Decimal("0.0004"),
                slippage_rate=Decimal("-0.01"),
            )

    def test_50_percent_slippage_simulation_and_ledger_reconciliation(self) -> None:
        candidate = _make_candidate()
        window = _make_window("extreme-slip-50", START_TIME, bars_count=60)
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.50"),
        )
        res = simulate_candidate_window(
            candidate, window.copy_frame(), symbol="DOGEUSDT", config=config
        )
        assert len(res.trades) >= 1
        assert res.total_slippage_cost > Decimal("100")
        expected_final = config.starting_equity + sum(
            (t.net_pnl for t in res.trades), start=Decimal("0")
        )
        assert res.final_equity == expected_final
        assert res.total_slippage_cost == sum(
            (t.slippage_cost for t in res.trades), start=Decimal("0")
        )

    def test_100_percent_adverse_slippage_simulation_bounds(self) -> None:
        candidate = _make_candidate()
        window = _make_window("extreme-slip-100", START_TIME, bars_count=60)
        # 100% adverse slippage on LONG forces exit price to 0; SimulatedTrade rejects
        config_100 = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("1.00"),
        )
        with pytest.raises(ValidationError, match="exit_price"):
            simulate_candidate_window(
                candidate, window.copy_frame(), symbol="DOGEUSDT", config=config_100
            )

        # 80% adverse slippage leaves positive exit price, executes, and reconciles
        config_80 = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.80"),
        )
        res = simulate_candidate_window(
            candidate, window.copy_frame(), symbol="DOGEUSDT", config=config_80
        )
        assert len(res.trades) >= 1
        expected_final = config_80.starting_equity + sum(
            (t.net_pnl for t in res.trades), start=Decimal("0")
        )
        assert res.final_equity == expected_final


# ==============================================================================
# 3. TestAdversarialWindowScalingAndCounts (6 tests)
# ==============================================================================
class TestAdversarialWindowScalingAndCounts:
    def test_zero_windows_count_in_script_rejected(self) -> None:
        with pytest.raises(DataQualityError, match="requires at least one window"):
            eval_script.establish_oos_windows(count=0)

    def test_negative_windows_count_in_script_rejected(self) -> None:
        with pytest.raises(DataQualityError, match="requires at least one window"):
            eval_script.establish_oos_windows(count=-5)

    def test_empty_windows_sequence_in_evaluator_rejected(self) -> None:
        candidate = _make_candidate()
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
                        taker_fee_rate=Decimal("0"),
                        slippage_rate=Decimal("0"),
                    ),
                ),
            )

    def test_empty_windows_in_aggregate_walk_forward_metrics_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one walk-forward window is required"):
            aggregate_walk_forward_metrics((), required_symbols=("DOGEUSDT",))

    def test_single_window_evaluation_boundary(self) -> None:
        candidate = _make_candidate()
        windows = eval_script.establish_oos_windows(count=1, bars_per_window=60)
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
        assert agg.window_count == 1
        assert len(agg.windows) == 1
        assert len(walk_forward_aggregation_hash(agg)) == 64

    def test_massive_50_oos_windows_walk_forward_scaling_and_determinism(self) -> None:
        candidate = _make_candidate()
        windows = eval_script.establish_oos_windows(count=50, bars_per_window=30)
        assert len(windows) == 50
        for i in range(len(windows) - 1):
            assert windows[i].spec.time_end == windows[i + 1].spec.time_start

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
        assert agg.window_count == 50
        assert len(agg.windows) == 50
        hash1 = walk_forward_aggregation_hash(agg)
        hash2 = walk_forward_aggregation_hash(agg)
        assert hash1 == hash2


# ==============================================================================
# 4. TestAdversarialCandleDataCorruption (9 tests)
# ==============================================================================
class TestAdversarialCandleDataCorruption:
    @pytest.mark.parametrize("col", ["timestamp", "open", "high", "low", "close"])
    def test_missing_each_required_column_isolated(self, col: str) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-corrupt-col",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        frame = _make_bars(START_TIME, bars_count=30).drop(columns=[col])
        with pytest.raises(DataQualityError):
            CachedEvaluationWindow(spec=spec, frame=frame)

    @pytest.mark.parametrize("bad_price", [Decimal("0"), Decimal("-10.5"), Decimal("-0.0001")])
    def test_non_positive_and_zero_prices_trigger_data_quality_error(
        self, bad_price: Decimal
    ) -> None:
        candidate = _make_candidate()
        bars = _make_bars(START_TIME, bars_count=40)
        bars.loc[5, "close"] = bad_price
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        with pytest.raises(DataQualityError, match="must be positive"):
            simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)

    def test_high_lower_than_low_inversion_trigger_data_quality_error(self) -> None:
        bars = _make_bars(START_TIME, bars_count=30)
        bars.loc[10, "high"] = Decimal("50.0")
        bars.loc[10, "low"] = Decimal("60.0")
        candidate = _make_candidate()
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        res = simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)
        assert res.final_equity.is_finite()

    def test_nan_and_inf_prices_trigger_data_quality_error(self) -> None:
        candidate = _make_candidate()
        bars = _make_bars(START_TIME, bars_count=40)
        bars.loc[5, "close"] = Decimal("NaN")
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        with pytest.raises(DataQualityError, match="not finite"):
            simulate_candidate_window(candidate, bars, symbol="DOGEUSDT", config=config)

    def test_timestamp_gap_middle_of_window(self) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-gap-middle",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        frame = _make_bars(START_TIME, bars_count=30).drop(index=[15])
        with pytest.raises(DataQualityError, match="timestamp gap"):
            CachedEvaluationWindow(spec=spec, frame=frame)

    def test_duplicate_timestamps_trigger_data_quality_error(self) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-duplicate-ts",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        frame = _make_bars(START_TIME, bars_count=30)
        duplicated = pd.concat([frame, frame.iloc[[8]]]).sort_values("timestamp")
        with pytest.raises(DataQualityError, match="duplicate timestamps are not allowed"):
            CachedEvaluationWindow(spec=spec, frame=duplicated)

    def test_frame_coverage_mismatch_start_later(self) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-coverage-start",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        frame = _make_bars(START_TIME + timedelta(minutes=10), bars_count=28)
        with pytest.raises(DataQualityError, match="cover exactly the window range"):
            CachedEvaluationWindow(spec=spec, frame=frame)

    def test_frame_coverage_mismatch_end_earlier(self) -> None:
        spec = CachedEvaluationWindowSpec(
            window_id="oos-coverage-end",
            symbol="DOGEUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=START_TIME,
            time_end=START_TIME + timedelta(minutes=150),
        )
        frame = _make_bars(START_TIME, bars_count=25)
        with pytest.raises(DataQualityError, match="cover exactly the window range"):
            CachedEvaluationWindow(spec=spec, frame=frame)

    @pytest.mark.parametrize(
        "bad_signal", [Decimal("2"), Decimal("-2"), Decimal("0.5"), Decimal("99")]
    )
    def test_invalid_signal_discrete_values(self, bad_signal: Decimal) -> None:
        frame = _make_bars(START_TIME, bars_count=30)
        frame["signal"] = Decimal("0")
        frame.loc[5, "signal"] = bad_signal
        config = TradeSimulationConfig(
            starting_equity=Decimal("10000"),
            position_fraction=Decimal("0.1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        with pytest.raises(DataQualityError, match="simulation signal must be -1, 0, or 1"):
            simulate_cached_signals(frame, symbol="DOGEUSDT", config=config)


# ==============================================================================
# 5. TestAdversarialTimeBoundariesAndNonUTC (8 tests)
# ==============================================================================
class TestAdversarialTimeBoundariesAndNonUTC:
    def test_spec_inverted_time_boundaries_start_after_end(self) -> None:
        with pytest.raises(ValidationError, match="time_start must be before time_end"):
            CachedEvaluationWindowSpec(
                window_id="oos-inverted",
                symbol="DOGEUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=START_TIME + timedelta(hours=2),
                time_end=START_TIME + timedelta(hours=1),
            )

    def test_spec_zero_duration_start_equals_end(self) -> None:
        with pytest.raises(ValidationError, match="time_start must be before time_end"):
            CachedEvaluationWindowSpec(
                window_id="oos-zero-duration",
                symbol="DOGEUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=START_TIME,
                time_end=START_TIME,
            )

    def test_spec_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware UTC"):
            CachedEvaluationWindowSpec(
                window_id="oos-naive",
                symbol="DOGEUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=datetime(2026, 1, 1, 0, 0),
                time_end=datetime(2026, 1, 1, 2, 0),
            )

    def test_spec_non_utc_timezone_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware UTC"):
            CachedEvaluationWindowSpec(
                window_id="oos-non-utc",
                symbol="DOGEUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=datetime(2026, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=8))),
                time_end=datetime(2026, 1, 1, 2, 0, tzinfo=timezone(timedelta(hours=8))),
            )

    def test_metrics_inverted_time_boundaries_rejected(self) -> None:
        cand = _make_candidate()
        w = _make_window("metrics-inverted", START_TIME, bars_count=30)
        res = simulate_candidate_window(
            cand,
            w.copy_frame(),
            symbol="DOGEUSDT",
            config=TradeSimulationConfig(
                starting_equity=Decimal("100"),
                position_fraction=Decimal("1"),
                taker_fee_rate=Decimal("0"),
                slippage_rate=Decimal("0"),
            ),
        )
        with pytest.raises(ValidationError, match="walk-forward window end must be after start"):
            WalkForwardWindowMetrics(
                window_id="oos-metrics-inv",
                symbol="DOGEUSDT",
                split="oos",
                window_start=START_TIME + timedelta(hours=2),
                window_end=START_TIME + timedelta(hours=1),
                metrics=calculate_performance_metrics(res),
            )

    def test_metrics_naive_datetime_rejected(self) -> None:
        cand = _make_candidate()
        w = _make_window("metrics-naive", START_TIME, bars_count=30)
        res = simulate_candidate_window(
            cand,
            w.copy_frame(),
            symbol="DOGEUSDT",
            config=TradeSimulationConfig(
                starting_equity=Decimal("100"),
                position_fraction=Decimal("1"),
                taker_fee_rate=Decimal("0"),
                slippage_rate=Decimal("0"),
            ),
        )
        with pytest.raises(ValidationError, match="timezone-aware UTC"):
            WalkForwardWindowMetrics(
                window_id="oos-metrics-naive",
                symbol="DOGEUSDT",
                split="oos",
                window_start=datetime(2026, 1, 1, 0, 0),
                window_end=datetime(2026, 1, 1, 2, 0),
                metrics=calculate_performance_metrics(res),
            )

    def test_overlapping_oos_windows_rejected_by_aggregation(self) -> None:
        w1 = _make_window("oos-1", START_TIME, bars_count=30)
        w2 = _make_window("oos-2", START_TIME + timedelta(minutes=120), bars_count=30)
        config = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        res1 = simulate_candidate_window(
            _make_candidate(), w1.copy_frame(), symbol="DOGEUSDT", config=config
        )
        res2 = simulate_candidate_window(
            _make_candidate(), w2.copy_frame(), symbol="DOGEUSDT", config=config
        )
        m1 = WalkForwardWindowMetrics(
            window_id="oos-1",
            symbol="DOGEUSDT",
            split="oos",
            window_start=w1.spec.time_start,
            window_end=w1.spec.time_end,
            metrics=calculate_performance_metrics(res1),
        )
        m2 = WalkForwardWindowMetrics(
            window_id="oos-2",
            symbol="DOGEUSDT",
            split="oos",
            window_start=w2.spec.time_start,
            window_end=w2.spec.time_end,
            metrics=calculate_performance_metrics(res2),
        )
        with pytest.raises(ValueError, match="overlapping OOS windows for symbol DOGEUSDT"):
            aggregate_walk_forward_metrics((m1, m2), required_symbols=("DOGEUSDT",))

    def test_disjoint_non_overlapping_gapped_windows_accepted(self) -> None:
        w1 = _make_window("oos-1", START_TIME, bars_count=30)
        w2 = _make_window("oos-2", w1.spec.time_end + timedelta(hours=2), bars_count=30)
        config = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        res1 = simulate_candidate_window(
            _make_candidate(), w1.copy_frame(), symbol="DOGEUSDT", config=config
        )
        res2 = simulate_candidate_window(
            _make_candidate(), w2.copy_frame(), symbol="DOGEUSDT", config=config
        )
        m1 = WalkForwardWindowMetrics(
            window_id="oos-1",
            symbol="DOGEUSDT",
            split="oos",
            window_start=w1.spec.time_start,
            window_end=w1.spec.time_end,
            metrics=calculate_performance_metrics(res1),
        )
        m2 = WalkForwardWindowMetrics(
            window_id="oos-2",
            symbol="DOGEUSDT",
            split="oos",
            window_start=w2.spec.time_start,
            window_end=w2.spec.time_end,
            metrics=calculate_performance_metrics(res2),
        )
        agg = aggregate_walk_forward_metrics((m1, m2), required_symbols=("DOGEUSDT",))
        assert agg.window_count == 2
        assert len(agg.windows) == 2


# ==============================================================================
# 6. TestAdversarialCryptographicHashDrift (8 tests)
# ==============================================================================
class TestAdversarialCryptographicHashDrift:
    def test_window_bundle_hash_drift_triggers_data_quality_error(self) -> None:
        candidate = _make_candidate()
        drifted_window = _make_window("drift-b", START_TIME, bars_count=30, bundle_hash="a" * 64)
        config = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        with pytest.raises(DataQualityError, match="bundle_hash does not match"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (drifted_window,),
                simulator=lambda c, f, w: simulate_candidate_window(
                    c, f, symbol=w.spec.symbol, config=config
                ),
            )

    def test_window_dataset_registry_hash_drift_triggers_data_quality_error(self) -> None:
        candidate = _make_candidate()
        drifted_window = _make_window(
            "drift-r", START_TIME, bars_count=30, dataset_registry_hash="b" * 64
        )
        config = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        with pytest.raises(DataQualityError, match="dataset_registry_hash does not match"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (drifted_window,),
                simulator=lambda c, f, w: simulate_candidate_window(
                    c, f, symbol=w.spec.symbol, config=config
                ),
            )

    def test_candidate_artifact_hash_drift_triggers_domain_violation(self, tmp_path: Path) -> None:
        candidate_file = tmp_path / "drift_cand.json"
        candidate = _make_candidate()
        payload = candidate.model_dump(mode="json")
        payload["artifact_hash"] = "c" * 64
        candidate_file.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(DomainViolation, match="hash mismatch"):
            eval_script.load_or_materialize_candidate(candidate_file)

    def test_candidate_bundle_hash_drift_triggers_domain_violation(self, tmp_path: Path) -> None:
        candidate_file = tmp_path / "drift_bundle_cand.json"
        drifted = eval_script.materialize_candidate_artifact(bundle_hash="d" * 64)
        eval_script.persist_phase_250_candidate_artifact(candidate_file, drifted)
        with pytest.raises(DomainViolation, match="bundle_hash mismatch"):
            eval_script.load_or_materialize_candidate(
                candidate_file, expected_artifact_hash=drifted.artifact_hash
            )

    def test_candidate_dataset_registry_hash_drift_triggers_domain_violation(
        self, tmp_path: Path
    ) -> None:
        candidate_file = tmp_path / "drift_reg_cand.json"
        drifted = eval_script.materialize_candidate_artifact(dataset_registry_hash="e" * 64)
        eval_script.persist_phase_250_candidate_artifact(candidate_file, drifted)
        with pytest.raises(DomainViolation, match="dataset_registry_hash mismatch"):
            eval_script.load_or_materialize_candidate(
                candidate_file, expected_artifact_hash=drifted.artifact_hash
            )

    def test_persisted_aggregation_hash_drift_triggers_domain_violation(
        self, tmp_path: Path
    ) -> None:
        candidate = _make_candidate()
        windows = eval_script.establish_oos_windows(count=2, bars_per_window=30)
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
        file_path = tmp_path / "agg-drift.json"
        write_walk_forward_aggregation(file_path, agg)

        data = json.loads(file_path.read_text(encoding="utf-8"))
        data["aggregation_hash"] = "f" * 64
        file_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(DomainViolation, match="aggregation hash mismatch"):
            read_walk_forward_aggregation(file_path)

    def test_qualification_artifact_hash_drift_triggers_domain_violation(
        self, tmp_path: Path
    ) -> None:
        candidate = _make_candidate()
        windows = eval_script.establish_oos_windows(count=2, bars_per_window=30)
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
            policy_id="policy-hash-test",
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
            evaluator_run_id="eval-hash-test",
            evaluator_version="1",
            evaluated_at=datetime.now(UTC),
        )
        file_path = tmp_path / "qual-drift.json"
        write_creator_candidate_qualification_artifact(file_path, qual)

        data = json.loads(file_path.read_text(encoding="utf-8"))
        data["qualification_hash"] = "0" * 64
        file_path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(DomainViolation, match="creator qualification artifact hash mismatch"):
            read_creator_candidate_qualification_artifact(file_path)

    def test_symbol_universe_mismatch_triggers_data_quality_error(self) -> None:
        candidate = _make_candidate()
        window = _make_window("symbol-drift", START_TIME, bars_count=30, symbol="BTCUSDT")
        config = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        with pytest.raises(DataQualityError, match="symbol is not present in candidate universe"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (window,),
                simulator=lambda c, f, w: simulate_candidate_window(
                    c, f, symbol=w.spec.symbol, config=config
                ),
            )


# ==============================================================================
# 7. TestAdversarialScriptCLIResilienceAndSecretSanitization (9 tests)
# ==============================================================================
class TestAdversarialScriptCLIResilienceAndSecretSanitization:
    def test_cli_zero_windows_count_exits_code_3(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = script_main(["--windows-count", "0"])
        assert code == 3
        data = json.loads(buf.getvalue())
        assert data["error_code"] == "evaluation_data_error"
        assert "requires at least one window" in data["message"]

    def test_cli_sub_minimum_bars_count_exits_code_3(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = script_main(["--bars-per-window", "15"])
        assert code == 3
        data = json.loads(buf.getvalue())
        assert data["error_code"] == "evaluation_data_error"
        assert "bars_count must be at least 25" in data["message"]

    def test_cli_out_of_bounds_fee_rate_exits_code_3(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = script_main(["--taker-fee-rate", "2.5"])
        assert code == 3
        data = json.loads(buf.getvalue())
        assert data["error_code"] == "evaluation_data_error"
        assert "less than or equal to 1" in data["message"]

    def test_cli_out_of_bounds_slippage_rate_exits_code_3(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = script_main(["--slippage-rate", "1.5"])
        assert code == 3
        data = json.loads(buf.getvalue())
        assert data["error_code"] == "evaluation_data_error"
        assert "less than or equal to 1" in data["message"]

    def test_cli_corrupted_candidate_json_file_exits_code_3(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("{{ malformed json content", encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = script_main(["--candidate-path", str(bad_file)])
        assert code == 3
        data = json.loads(buf.getvalue())
        assert data["error_code"] in ("evaluation_data_error", "unexpected_error")

    def test_cli_tampered_candidate_artifact_exits_code_3(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "tampered.json"
        other_id = "cand-0000000000000000000000000000000000000000000000000000000000000000"
        other_cand = eval_script.materialize_candidate_artifact(candidate_id=other_id)
        eval_script.persist_phase_250_candidate_artifact(bad_file, other_cand)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = script_main(["--candidate-path", str(bad_file)])
        assert code == 3
        data = json.loads(buf.getvalue())
        assert data["error_code"] == "evaluation_data_error"
        assert "candidate_id mismatch" in data["message"]

    def test_cli_artifact_immutability_conflict_exits_code_3(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "immut_test"
        cand_path = tmp_path / "cand.json"
        code1 = script_main(
            [
                "--output-dir",
                str(out_dir),
                "--candidate-path",
                str(cand_path),
                "--windows-count",
                "2",
                "--bars-per-window",
                "30",
            ]
        )
        assert code1 == 0

        buf = io.StringIO()
        with redirect_stdout(buf):
            code2 = script_main(
                [
                    "--output-dir",
                    str(out_dir),
                    "--candidate-path",
                    str(cand_path),
                    "--windows-count",
                    "3",
                    "--bars-per-window",
                    "30",
                ]
            )
        assert code2 == 3
        data = json.loads(buf.getvalue())
        assert data["error_code"] == "evaluation_data_error"
        assert "immutable" in data["message"]

    def test_cli_secret_sanitization_under_simulated_leak(self) -> None:
        hostile_msg = f"Hostile crash with {CANARY_SECRET} and {CANARY_BEARER}"
        with patch.object(eval_script, "run_evaluation", side_effect=RuntimeError(hostile_msg)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = script_main([])
            assert code == 3
            output = buf.getvalue()
            assert CANARY_SECRET not in output
            assert CANARY_BEARER not in output
            assert not _SECRET_PATTERN.search(output)
            assert "[REDACTED_API_KEY]" in output

    def test_cli_safety_invariants_strictly_maintained(self, tmp_path: Path) -> None:
        assert_offline_safety_invariants()
        out_dir = tmp_path / "safety_run"
        cand_path = tmp_path / "cand.json"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = script_main(
                [
                    "--output-dir",
                    str(out_dir),
                    "--candidate-path",
                    str(cand_path),
                    "--windows-count",
                    "2",
                    "--bars-per-window",
                    "30",
                ]
            )
        assert code == 0
        summary = json.loads(buf.getvalue())
        safety = summary["safety_state"]
        assert safety["orders"] == 0
        assert safety["exchange_access"] is False
        assert safety["execution_authority"] is False
        assert safety["promotion_state"] == "unpromoted"
        assert safety["paper_activation"] is False
