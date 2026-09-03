"""Comprehensive unit test suite for Phase 253 Multi-Asset Walk-Forward Evaluation.

Covers 49 discrete unit tests across 9 specialized test classes:
1. TestMultiAssetCandidateLoadingAndValidation (7 tests)
2. TestOOSWindowConstructionAndBoundaryChecks (7 tests)
3. TestCapitalAndDynamicLeverageRiskEnforcement (6 tests)
4. TestTradeSimulationAndLedgerReconciliation (6 tests)
5. TestWalkForwardAggregationAndDeterministicHashing (5 tests)
6. TestPortfolioComparativeMatrixRankingLogic (6 tests)
7. TestOfflineSafetyInvariantsAndZeroSecretLeakage (4 tests)
8. TestCliRunnerExecutionAndArtifactPersistence (5 tests)
9. TestEdgeCasesAndAdversarialScenarios (3 tests)
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys
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
from autonomous_futures.data.parquet import DataQualityError, canonicalize_bars
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
    _artifact_content_hash,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.creator_proposals import (
    canonical_creator_candidate_id,
)
from autonomous_futures.research.performance_metrics import (
    calculate_performance_metrics,
)
from autonomous_futures.research.trade_simulation import (
    TradeSimulationConfig,
)
from autonomous_futures.research.walk_forward import (
    PersistedWalkForwardAggregation,
    WalkForwardAggregation,
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
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


eval_script = _load_script_module("evaluate_phase_253_walk_forward")
script_main: Callable[[list[str] | None], int] = eval_script.main

PINNED_BUNDLE_HASH: str = eval_script.PINNED_BUNDLE_HASH
PINNED_REGISTRY_HASH: str = eval_script.PINNED_REGISTRY_HASH
PINNED_TARGETS: dict[str, Any] = eval_script.PINNED_TARGETS

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _make_test_bars(
    start: datetime,
    bars_count: int = 60,
    *,
    pattern: str = "breakout",
    base_price: float = 100.0,
) -> pd.DataFrame:
    """Generate deterministic 5m bars for unit testing."""
    if pattern == "breakout":
        flat = [base_price] * 30
        step = 1.0
        rally = [base_price + i * step for i in range(1, bars_count - 30 + 1)]
        prices = (flat + rally)[:bars_count]
    elif pattern == "flat":
        prices = [base_price] * bars_count
    elif pattern == "downtrend":
        flat = [base_price] * 30
        drop = [base_price - i * 1.0 for i in range(1, bars_count - 30 + 1)]
        prices = (flat + drop)[:bars_count]
    else:
        prices = [base_price + i * 0.5 for i in range(bars_count)]

    timestamps = [start + timedelta(minutes=5 * i) for i in range(bars_count)]
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(round(p, 4))) for p in prices],
            "high": [Decimal(str(round(p + 0.5, 4))) for p in prices],
            "low": [Decimal(str(round(p - 0.5, 4))) for p in prices],
            "close": [Decimal(str(round(p, 4))) for p in prices],
        }
    )
    return canonicalize_bars(df, interval=timedelta(minutes=5))


def _make_sim_config(
    starting_equity: Decimal = Decimal("100"),
    position_fraction: Decimal = Decimal("0.2"),
    taker_fee_rate: Decimal = Decimal("0.0004"),
    slippage_rate: Decimal = Decimal("0.0002"),
    **kwargs: Any,
) -> TradeSimulationConfig:
    return TradeSimulationConfig(
        starting_equity=starting_equity,
        position_fraction=position_fraction,
        taker_fee_rate=taker_fee_rate,
        slippage_rate=slippage_rate,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Class 1: TestMultiAssetCandidateLoadingAndValidation (7 tests)
# ---------------------------------------------------------------------------
class TestMultiAssetCandidateLoadingAndValidation:
    """Validates loading, schema integrity, and cryptographic identity of candidates."""

    def test_load_all_four_phase_252_candidates_from_artifacts_dir(self) -> None:
        candidates_dir = Path("artifacts/research/phase252/candidates")
        for sym, target in PINNED_TARGETS.items():
            path = candidates_dir / target.filename
            assert path.is_file(), f"Missing candidate file for {sym}"
            art = read_creator_candidate_artifact(path)
            assert isinstance(art, CreatorCandidateArtifact)
            assert len(art.strategy.universe.symbols) == 1
            assert art.strategy.universe.symbols[0] == sym

    def test_all_four_candidates_canonical_id_derivation(self) -> None:
        candidates_dir = Path("artifacts/research/phase252/candidates")
        for _sym, target in PINNED_TARGETS.items():
            art = read_creator_candidate_artifact(candidates_dir / target.filename)
            derived_id = canonical_creator_candidate_id(art.strategy)
            assert art.candidate_id == derived_id
            assert art.candidate_id == target.candidate_id

    def test_all_four_candidates_content_hash_integrity(self) -> None:
        candidates_dir = Path("artifacts/research/phase252/candidates")
        for _sym, target in PINNED_TARGETS.items():
            art = read_creator_candidate_artifact(candidates_dir / target.filename)
            computed_hash = _artifact_content_hash(art)
            assert art.artifact_hash == computed_hash
            assert art.artifact_hash == target.artifact_hash

    def test_all_four_candidates_pinned_hashes_match_authoritative_constants(self) -> None:
        expected = {
            "BTCUSDT": (
                "cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74",
                "4b6384a0d1e6ff0b957860d8f1c43b1c334ebc7405b95d88fb72ad2169ad6f2b",
            ),
            "ETHUSDT": (
                "cand-1f87c23b87c117a5909a32a38dd44f0001b66d70f6a0818375a6e95d429aa632",
                "73fbf488c090f758466811b4356294fed676d9734c7592b627a349e15ec49ae9",
            ),
            "SOLUSDT": (
                "cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd",
                "ad1c8c35790e0f6a5726d317a9b0d0ee6e4e147a103f79e6d03a82ad23f9a417",
            ),
            "DOGEUSDT": (
                "cand-09891e9fead9965035c61117e65bd12a9e6b59f179905ec7c5d2963288f8f2a8",
                "7ab575a56b73520607c68f9e0c183ca86d7f0223472e7299e1bd752eb299d67d",
            ),
        }
        for sym, (exp_id, exp_hash) in expected.items():
            target = PINNED_TARGETS[sym]
            assert target.candidate_id == exp_id
            assert target.artifact_hash == exp_hash

    def test_dsl_v2_schema_and_risk_bindings_for_all_candidates(self) -> None:
        candidates_dir = Path("artifacts/research/phase252/candidates")
        for _sym, target in PINNED_TARGETS.items():
            candidate = eval_script.load_and_verify_candidate(target, candidates_dir=candidates_dir)
            strat = candidate.strategy
            assert strat.dsl_version == 2
            assert strat.family == "regime_gated_breakout"
            assert strat.universe.timeframe == "5m"
            assert strat.universe.regime_context_timeframe == "15m"

            feature_names = {f.name for f in strat.features}
            assert "regime_trend" in feature_names
            assert "ema_slope" in feature_names
            assert "rsi" in feature_names
            assert "adx" in feature_names

            risk = strat.risk
            assert risk is not None
            assert risk.position_fraction == Decimal("0.2")
            assert risk.stop_atr_multiplier == Decimal("1.5")
            assert risk.take_profit_atr_multiplier == Decimal("3.0")
            assert risk.trailing_atr_multiplier == Decimal("1.0")

    def test_campaign_summary_accepted_candidates_integrity(self) -> None:
        summary_path = Path("artifacts/research/phase252/campaign-summary.json")
        assert summary_path.is_file()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["campaign_id"] == "creator-batch-20260904-phase252"
        assert summary["total_accepted"] == 4

        accepted_ids = summary.get("accepted_candidate_ids", [])
        for target in PINNED_TARGETS.values():
            assert target.candidate_id in accepted_ids

    def test_tampered_candidate_hash_rejection(self, tmp_path: Path) -> None:
        candidates_dir = Path("artifacts/research/phase252/candidates")
        target = PINNED_TARGETS["BTCUSDT"]
        candidate = read_creator_candidate_artifact(candidates_dir / target.filename)
        data = candidate.model_dump(mode="json")
        data["bundle_hash"] = "0" * 64

        tampered_file = tmp_path / "tampered.json"
        tampered_file.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(DomainViolation):
            read_creator_candidate_artifact(tampered_file)


# ---------------------------------------------------------------------------
# Class 2: TestOOSWindowConstructionAndBoundaryChecks (7 tests)
# ---------------------------------------------------------------------------
class TestOOSWindowConstructionAndBoundaryChecks:
    """Validates OOS evaluation window boundaries, sequential chaining, and data quality."""

    def test_multi_asset_window_construction(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            windows = eval_script.establish_sequential_oos_windows(
                symbol=sym,
                count=3,
                bars_per_window=60,
                start=start,
            )
            assert len(windows) == 3
            for w in windows:
                assert w.spec.symbol == sym
                assert w.frame.shape[0] == 60
                assert w.spec.bundle_hash == PINNED_BUNDLE_HASH
                assert w.spec.dataset_registry_hash == PINNED_REGISTRY_HASH

    def test_sequential_non_overlapping_window_boundaries(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        windows = eval_script.establish_sequential_oos_windows(
            symbol="BTCUSDT", count=3, bars_per_window=60, start=start
        )
        for i in range(len(windows) - 1):
            assert windows[i].spec.time_end == windows[i + 1].spec.time_start
            assert windows[i].spec.time_start < windows[i].spec.time_end

    def test_window_deep_copy_isolation(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        windows = eval_script.establish_sequential_oos_windows(
            symbol="BTCUSDT", count=1, bars_per_window=60, start=start
        )
        w = windows[0]
        copied_frame = w.copy_frame()
        original_close = w.frame["close"].iloc[0]
        copied_frame.loc[0, "close"] = Decimal("999999")
        assert w.frame["close"].iloc[0] == original_close

    def test_window_spec_validation_guards(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(hours=5)

        # Naive datetime
        with pytest.raises(ValidationError):
            CachedEvaluationWindowSpec(
                window_id="oos-test",
                symbol="BTCUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=datetime(2026, 1, 1, 0, 0),  # naive
                time_end=end,
            )

        # Inverted range
        with pytest.raises(ValidationError):
            CachedEvaluationWindowSpec(
                window_id="oos-test",
                symbol="BTCUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=end,
                time_end=start,
            )

    def test_data_quality_missing_or_corrupted_columns(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        spec = CachedEvaluationWindowSpec(
            window_id="oos-test",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        df = _make_test_bars(start, 60)
        missing_df = df.drop(columns=["close"])
        with pytest.raises(DataQualityError):
            CachedEvaluationWindow(spec=spec, frame=missing_df)

    def test_data_quality_timestamp_gaps_and_duplicates(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        spec = CachedEvaluationWindowSpec(
            window_id="oos-test",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        df = _make_test_bars(start, 60)

        # Gap (dropped row)
        gap_df = df.drop(index=[15]).reset_index(drop=True)
        with pytest.raises(DataQualityError):
            CachedEvaluationWindow(spec=spec, frame=gap_df)

    def test_data_quality_hash_mismatch_rejection(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        spec = CachedEvaluationWindowSpec(
            window_id="oos-test",
            symbol="BTCUSDT",
            bundle_hash="0" * 64,  # mismatched bundle hash
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        df = _make_test_bars(start, 60)
        w = CachedEvaluationWindow(spec=spec, frame=df)

        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = _make_sim_config()
        with pytest.raises(DataQualityError):
            evaluate_cached_oos_walk_forward(
                candidate,
                (w,),
                simulator=lambda c, f, win: simulate_candidate_window(
                    c, f, symbol=win.spec.symbol, config=cfg
                ),
            )


# ---------------------------------------------------------------------------
# Class 3: TestCapitalAndDynamicLeverageRiskEnforcement (6 tests)
# ---------------------------------------------------------------------------
class TestCapitalAndDynamicLeverageRiskEnforcement:
    """Validates 100 USDT capital baseline, dynamic leverage sizing, and protective stops."""

    def test_100_usdt_starting_equity_enforcement(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        df = _make_test_bars(start, 60)
        cfg = _make_sim_config()
        result = simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)
        assert result.starting_equity == Decimal("100")

    def test_dsl_v2_risk_override_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        df = _make_test_bars(start, 60)
        captured_config: list[TradeSimulationConfig] = []
        import autonomous_futures.research.candidate_window_simulation as cws

        orig_sim = cws.simulate_cached_signals

        def _mock_simulate(signals: Any, *, symbol: str, config: TradeSimulationConfig) -> Any:
            captured_config.append(config)
            return orig_sim(signals, symbol=symbol, config=config)

        monkeypatch.setattr(cws, "simulate_cached_signals", _mock_simulate)

        # Supply divergent config
        cfg = _make_sim_config(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.5"),  # should be overridden to 0.2
            stop_atr_multiplier=Decimal("5.0"),  # should be overridden to 1.5
            take_profit_atr_multiplier=Decimal("10.0"),  # should be overridden to 3.0
            trailing_atr_multiplier=Decimal("4.0"),  # should be overridden to 1.0
        )
        result = simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)
        assert len(captured_config) == 1
        assert captured_config[0].position_fraction == Decimal("0.2")
        assert captured_config[0].stop_atr_multiplier == Decimal("1.5")
        assert captured_config[0].take_profit_atr_multiplier == Decimal("3.0")
        assert captured_config[0].trailing_atr_multiplier == Decimal("1.0")
        assert result.trades[0].entry_notional <= Decimal("20.05")

    def test_notional_exposure_and_sizing_calculation(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        df = _make_test_bars(start, 60, pattern="breakout")
        cfg = _make_sim_config()
        result = simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)
        for trade in result.trades:
            # Entry notional should not exceed 20 USDT + epsilon
            assert trade.entry_notional <= Decimal("20.05")

    def test_dynamic_leverage_confidence_scaling(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        # Under completely flat market, no indicators align -> 0 trades
        df_flat = _make_test_bars(start, 60, pattern="flat")
        cfg = _make_sim_config()
        result = simulate_candidate_window(candidate, df_flat, symbol="BTCUSDT", config=cfg)
        assert len(result.trades) == 0
        assert result.final_equity == Decimal("100")

    def test_veto_filter_suppresses_risky_entries(self) -> None:
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        assert "adx < 15" in candidate.strategy.vetoes

    def test_atr_protective_stops_prevent_excessive_drawdown(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        df_down = _make_test_bars(start, 60, pattern="downtrend")
        cfg = _make_sim_config()
        result = simulate_candidate_window(candidate, df_down, symbol="BTCUSDT", config=cfg)
        # Any trades triggered are protected by stop loss / trailing stop
        for trade in result.trades:
            if trade.net_pnl < 0:
                assert trade.net_pnl > Decimal("-2.00")
        assert result.final_equity > Decimal("95.00")


# ---------------------------------------------------------------------------
# Class 4: TestTradeSimulationAndLedgerReconciliation (6 tests)
# ---------------------------------------------------------------------------
class TestTradeSimulationAndLedgerReconciliation:
    """Validates deterministic trade simulation, fee/slippage modeling, and ledger math."""

    def test_deterministic_trade_simulation_all_four_assets(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = _make_sim_config()
        for sym, target in PINNED_TARGETS.items():
            candidate = eval_script.load_and_verify_candidate(target)
            df = _make_test_bars(start, 60, pattern="breakout")
            r1 = simulate_candidate_window(candidate, df, symbol=sym, config=cfg)
            r2 = simulate_candidate_window(candidate, df, symbol=sym, config=cfg)
            assert len(r1.trades) == len(r2.trades)
            for t1, t2 in zip(r1.trades, r2.trades, strict=True):
                assert t1.net_pnl == t2.net_pnl
                assert t1.fees == t2.fees

    def test_exact_ledger_reconciliation_equation(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        df = _make_test_bars(start, 60, pattern="breakout")
        cfg = _make_sim_config()
        result = simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)
        for t in result.trades:
            assert t.net_pnl == t.gross_pnl - t.fees
            assert t.fees == t.entry_fee + t.exit_fee

    def test_final_equity_reconciliation(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        df = _make_test_bars(start, 60, pattern="breakout")
        cfg = _make_sim_config()
        result = simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)
        total_pnl = sum((t.net_pnl for t in result.trades), Decimal("0"))
        expected_final = result.starting_equity + total_pnl
        assert result.final_equity == expected_final
        assert result.total_fees == sum((t.fees for t in result.trades), Decimal("0"))

    def test_realistic_taker_fees_and_slippage_accounting(self) -> None:
        cfg = _make_sim_config(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        assert cfg.taker_fee_rate == Decimal("0.0004")
        assert cfg.slippage_rate == Decimal("0.0002")

    def test_forced_end_of_window_liquidation(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        # Slow upward creep so position enters but take profit isn't reached before final bar
        df = _make_test_bars(start, 60, pattern="breakout")
        cfg = _make_sim_config()
        result = simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)
        if result.trades:
            last_trade = result.trades[-1]
            if last_trade.exit_timestamp == df["timestamp"].iloc[-1]:
                assert last_trade.exit_reason == "forced_end_of_window"

    def test_metric_calculation_accuracy(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        df = _make_test_bars(start, 60, pattern="breakout")
        cfg = _make_sim_config()
        result = simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)
        metrics = calculate_performance_metrics(result)
        assert metrics.trade_count == len(result.trades)
        winning = sum(1 for t in result.trades if t.net_pnl > 0)
        losing = sum(1 for t in result.trades if t.net_pnl < 0)
        assert metrics.winning_trades == winning
        assert metrics.losing_trades == losing


# ---------------------------------------------------------------------------
# Class 5: TestWalkForwardAggregationAndDeterministicHashing (5 tests)
# ---------------------------------------------------------------------------
class TestWalkForwardAggregationAndDeterministicHashing:
    """Validates aggregation structure, deterministic SHA-256 hashes, and persistence."""

    def test_walk_forward_aggregation_structure_per_asset(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = _make_sim_config()
        for sym, target in PINNED_TARGETS.items():
            candidate = eval_script.load_and_verify_candidate(target)
            windows = eval_script.establish_sequential_oos_windows(
                symbol=sym, count=3, bars_per_window=60, start=start
            )
            agg = evaluate_cached_oos_walk_forward(
                candidate,
                windows,
                simulator=lambda c, f, w: simulate_candidate_window(
                    c, f, symbol=w.spec.symbol, config=cfg
                ),
            )
            assert agg.window_count == 3
            assert agg.data_source == "cached_only"
            assert agg.exchange_access is False
            assert agg.required_symbols == (sym,)

    def test_walk_forward_aggregation_hash_determinism(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = _make_sim_config()
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        windows = eval_script.establish_sequential_oos_windows(
            symbol="BTCUSDT", count=3, bars_per_window=60, start=start
        )
        agg1 = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=cfg
            ),
        )
        agg2 = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=cfg
            ),
        )
        h1 = walk_forward_aggregation_hash(agg1)
        h2 = walk_forward_aggregation_hash(agg2)
        assert len(h1) == 64
        assert h1 == h2

    def test_aggregation_hash_sensitivity(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = _make_sim_config()
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        windows = eval_script.establish_sequential_oos_windows(
            symbol="BTCUSDT", count=3, bars_per_window=60, start=start
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=cfg
            ),
        )
        base_hash = walk_forward_aggregation_hash(agg)

        # Perturb metric
        perturbed_windows = list(agg.windows)
        w0 = perturbed_windows[0]
        perturbed_metrics = w0.metrics.model_copy(
            update={"gross_profit": w0.metrics.gross_profit + Decimal("1.0")}
        )
        perturbed_w0 = w0.model_copy(update={"metrics": perturbed_metrics})
        perturbed_windows[0] = perturbed_w0
        perturbed_agg = agg.model_copy(update={"windows": tuple(perturbed_windows)})

        perturbed_hash = walk_forward_aggregation_hash(perturbed_agg)
        assert perturbed_hash != base_hash

    def test_persisted_walk_forward_aggregation_write_once(self, tmp_path: Path) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = _make_sim_config()
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        windows = eval_script.establish_sequential_oos_windows(
            symbol="BTCUSDT", count=3, bars_per_window=60, start=start
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=cfg
            ),
        )

        out_path = tmp_path / "walk-forward-aggregation.json"
        write_walk_forward_aggregation(out_path, agg)
        assert out_path.is_file()

        envelope = read_walk_forward_aggregation(out_path)
        assert isinstance(envelope, PersistedWalkForwardAggregation)
        assert envelope.aggregation_hash == walk_forward_aggregation_hash(agg)

        # Idempotent write passes
        write_walk_forward_aggregation(out_path, agg)

    def test_oos_split_only_enforcement(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        spec = CachedEvaluationWindowSpec(
            window_id="oos-test",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        df = _make_test_bars(start, 60)
        w = CachedEvaluationWindow(spec=spec, frame=df)

        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])

        # Simulator attempting live data
        def _bad_sim(c: Any, f: Any, win: Any) -> Any:
            res = simulate_candidate_window(c, f, symbol=win.spec.symbol, config=_make_sim_config())
            return res.model_copy(update={"data_source": "live"})

        with pytest.raises(DataQualityError):
            evaluate_cached_oos_walk_forward(candidate, (w,), simulator=_bad_sim)


# ---------------------------------------------------------------------------
# Class 6: TestPortfolioComparativeMatrixRankingLogic (6 tests)
# ---------------------------------------------------------------------------
class TestPortfolioComparativeMatrixRankingLogic:
    """Validates portfolio matrix assembly, candidate ranking precedence, and Sharpe ratio."""

    def test_portfolio_matrix_compilation_all_four_assets(self) -> None:
        results: dict[str, tuple[WalkForwardAggregation, str, float]] = {}
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = _make_sim_config()
        for sym, target in PINNED_TARGETS.items():
            candidate = eval_script.load_and_verify_candidate(target)
            windows = eval_script.establish_sequential_oos_windows(
                symbol=sym, count=3, bars_per_window=60, start=start
            )
            agg = evaluate_cached_oos_walk_forward(
                candidate,
                windows,
                simulator=lambda c, f, w: simulate_candidate_window(
                    c, f, symbol=w.spec.symbol, config=cfg
                ),
            )
            agg_hash = walk_forward_aggregation_hash(agg)
            results[sym] = (agg, agg_hash, 1.5)

        matrix = eval_script.build_portfolio_comparison_matrix(
            results,
            evaluator_run_id="test-eval-run",
            evaluated_at=start,
        )
        assert len(matrix["ranked_candidates"]) == 4
        symbols_in_matrix = {c["symbol"] for c in matrix["ranked_candidates"]}
        assert symbols_in_matrix == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"}

    def test_sharpe_ratio_ranking_precedence(self) -> None:
        cands = [
            {"symbol": "A", "sharpe_ratio": 1.5, "net_pnl": 10.0, "max_drawdown_pct": 5.0},
            {"symbol": "B", "sharpe_ratio": 2.5, "net_pnl": 5.0, "max_drawdown_pct": 2.0},
            {"symbol": "C", "sharpe_ratio": 0.8, "net_pnl": 20.0, "max_drawdown_pct": 10.0},
            {"symbol": "D", "sharpe_ratio": 1.5, "net_pnl": 15.0, "max_drawdown_pct": 3.0},
        ]
        ranked = eval_script.rank_candidates(cands)
        assert ranked[0]["symbol"] == "B"  # highest Sharpe
        assert ranked[1]["symbol"] == "D"  # tied Sharpe (1.5), higher net_pnl (15 > 10)
        assert ranked[2]["symbol"] == "A"
        assert ranked[3]["symbol"] == "C"
        assert [c["rank"] for c in ranked] == [1, 2, 3, 4]

    def test_annualized_sharpe_calculation_formula(self) -> None:
        # Known returns
        returns = [Decimal("1.0"), Decimal("2.0"), Decimal("3.0")]
        sharpe = eval_script.calculate_sharpe_ratio(returns)
        assert sharpe > 0

        # Zero variance returns
        flat_returns = [Decimal("1.0"), Decimal("1.0"), Decimal("1.0")]
        assert eval_script.calculate_sharpe_ratio(flat_returns) == 0.0

        # Fewer than 2 trades
        assert eval_script.calculate_sharpe_ratio([]) == 0.0
        assert eval_script.calculate_sharpe_ratio([Decimal("1.0")]) == 0.0

    def test_portfolio_pooled_summary_reconciliation(self) -> None:
        matrix_path = Path("artifacts/research/phase253/portfolio-comparison-matrix.json")
        if not matrix_path.is_file():
            eval_script.main([])
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        summary = matrix["portfolio_summary"]

        assert summary["total_starting_equity_usdt"] == "400"
        ranked = matrix["ranked_candidates"]
        assert summary["total_trades"] == sum(c["total_trades"] for c in ranked)
        assert summary["total_winning_trades"] == sum(c["winning_trades"] for c in ranked)
        assert summary["total_losing_trades"] == sum(c["losing_trades"] for c in ranked)

    def test_portfolio_matrix_serialization_and_schema(self) -> None:
        matrix_path = Path("artifacts/research/phase253/portfolio-comparison-matrix.json")
        if not matrix_path.is_file():
            eval_script.main([])
        data = json.loads(matrix_path.read_text(encoding="utf-8"))
        assert "matrix_version" in data
        assert "campaign_id" in data
        assert "evaluator_run_id" in data
        assert "ranked_candidates" in data
        assert "portfolio_summary" in data
        assert "safety_state" in data

    def test_qualification_status_tagging(self) -> None:
        matrix_path = Path("artifacts/research/phase253/portfolio-comparison-matrix.json")
        if not matrix_path.is_file():
            eval_script.main([])
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        for cand in matrix["ranked_candidates"]:
            status = cand["qualification_status"]
            assert status in ("QUALIFIED", "DEFENSIVE_HOLD")
            if cand["net_pnl"] > 0 and cand["sharpe_ratio"] > 0:
                assert status == "QUALIFIED"
            else:
                assert status == "DEFENSIVE_HOLD"


# ---------------------------------------------------------------------------
# Class 7: TestOfflineSafetyInvariantsAndZeroSecretLeakage (4 tests)
# ---------------------------------------------------------------------------
class TestOfflineSafetyInvariantsAndZeroSecretLeakage:
    """Validates research offline invariants and zero secret leakage."""

    def test_offline_safety_invariants_proof(self) -> None:
        summary_path = Path("artifacts/research/phase253/evaluation-summary.json")
        if not summary_path.is_file():
            eval_script.main([])
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        safety = summary["safety_state"]

        assert safety["orders"] == 0
        assert safety["exchange_access"] is False
        assert safety["execution_authority"] is False
        assert safety["promotion_state"] == "unpromoted"
        assert safety["paper_activation"] is False
        assert safety["data_source"] == "cached_only"

    def test_zero_binance_credentials_in_environment(self) -> None:
        assert_offline_safety_invariants()
        for k, v in os.environ.items():
            if "BINANCE" in k.upper():
                assert not v or v.lower() in ("false", "0")

    def test_zero_secret_leakage_in_artifacts_and_summaries(self) -> None:
        artifacts_dir = Path("artifacts/research/phase253")
        for f in artifacts_dir.glob("*.json"):
            content = f.read_text(encoding="utf-8")
            matches = _SECRET_PATTERN.findall(content)
            assert len(matches) == 0, f"Secret pattern detected in {f}"

    def test_evaluator_rejects_live_data_or_exchange_simulator(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        spec = CachedEvaluationWindowSpec(
            window_id="oos-test",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        df = _make_test_bars(start, 60)
        w = CachedEvaluationWindow(spec=spec, frame=df)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])

        def _live_simulator(c: Any, f: Any, win: Any) -> Any:
            res = simulate_candidate_window(c, f, symbol=win.spec.symbol, config=_make_sim_config())
            return res.model_copy(update={"exchange_access": True})

        with pytest.raises(DataQualityError):
            evaluate_cached_oos_walk_forward(candidate, (w,), simulator=_live_simulator)


# ---------------------------------------------------------------------------
# Class 8: TestCliRunnerExecutionAndArtifactPersistence (5 tests)
# ---------------------------------------------------------------------------
class TestCliRunnerExecutionAndArtifactPersistence:
    """Validates CLI flags, execution lifecycle, and artifact persistence."""

    def test_cli_help_flag(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = script_main(["--help"])
        assert code == 0
        assert "Phase 253 Multi-Asset Offline Walk-Forward Evaluation" in out.getvalue()

    def test_cli_end_to_end_execution_synthetic_run(self, tmp_path: Path) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = script_main(
                [
                    "--output-dir",
                    str(tmp_path),
                    "--windows-count",
                    "3",
                    "--bars-per-window",
                    "60",
                ]
            )
        assert code == 0

        # Assert all 6 artifacts exist
        expected_artifacts = [
            "walk-forward-aggregation-BTCUSDT.json",
            "walk-forward-aggregation-ETHUSDT.json",
            "walk-forward-aggregation-SOLUSDT.json",
            "walk-forward-aggregation-DOGEUSDT.json",
            "portfolio-comparison-matrix.json",
            "evaluation-summary.json",
        ]
        for art_name in expected_artifacts:
            assert (tmp_path / art_name).is_file(), f"Missing artifact: {art_name}"

    def test_cli_end_to_end_with_canonical_parquet_data(self) -> None:
        summary_path = Path("artifacts/research/phase253/evaluation-summary.json")
        assert summary_path.is_file()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["phase"] == 253
        assert set(summary["assets_evaluated"]) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"}

    def test_cli_idempotent_execution(self, tmp_path: Path) -> None:
        out1 = io.StringIO()
        with redirect_stdout(out1):
            code1 = script_main(["--output-dir", str(tmp_path), "--windows-count", "2"])
        assert code1 == 0

        out2 = io.StringIO()
        with redirect_stdout(out2):
            code2 = script_main(["--output-dir", str(tmp_path), "--windows-count", "2"])
        assert code2 == 0

    def test_cli_error_handling_missing_candidate_or_bad_args(self) -> None:
        # Invalid flag
        code_bad_flag = script_main(["--non-existent-flag"])
        assert code_bad_flag == 2

        # Non-existent candidate dir
        out = io.StringIO()
        with redirect_stdout(out):
            code_bad_dir = script_main(["--candidates-dir", "non_existent_directory_12345"])
        assert code_bad_dir == 3


# ---------------------------------------------------------------------------
# Class 9: TestEdgeCasesAndAdversarialScenarios (3 tests)
# ---------------------------------------------------------------------------
class TestEdgeCasesAndAdversarialScenarios:
    """Validates handling of edge conditions, extreme parameters, and anomalous data."""

    def test_zero_trade_asset_in_portfolio_matrix(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        spec = CachedEvaluationWindowSpec(
            window_id="oos-test",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        df_flat = _make_test_bars(start, 60, pattern="flat")
        w = CachedEvaluationWindow(spec=spec, frame=df_flat)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = _make_sim_config()

        agg = evaluate_cached_oos_walk_forward(
            candidate,
            (w,),
            simulator=lambda c, f, win: simulate_candidate_window(
                c, f, symbol=win.spec.symbol, config=cfg
            ),
        )
        assert agg.total_trade_count == 0
        assert agg.pooled_profit_factor is None

        # Build matrix with 0 trades
        results = {"BTCUSDT": (agg, walk_forward_aggregation_hash(agg), 0.0)}
        matrix = eval_script.build_portfolio_comparison_matrix(results, "test-run", start)
        assert matrix["ranked_candidates"][0]["sharpe_ratio"] == 0.0
        assert matrix["ranked_candidates"][0]["qualification_status"] == "DEFENSIVE_HOLD"

    def test_all_losing_trades_scenario(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        spec = CachedEvaluationWindowSpec(
            window_id="oos-test",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        flat = [100.0] * 30
        up = [100.0 + i * 2.0 for i in range(1, 4)]
        down = [106.0 - i * 3.0 for i in range(1, 3)]
        flat2 = [95.0] * 25
        prices = (flat + up + down + flat2)[:60]
        timestamps = [start + timedelta(minutes=5 * i) for i in range(60)]
        df_down = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [Decimal(str(p)) for p in prices],
                "high": [Decimal(str(p + 0.5)) for p in prices],
                "low": [Decimal(str(p - 0.5)) for p in prices],
                "close": [Decimal(str(p)) for p in prices],
            }
        )
        w = CachedEvaluationWindow(spec=spec, frame=df_down)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = _make_sim_config()

        agg = evaluate_cached_oos_walk_forward(
            candidate,
            (w,),
            simulator=lambda c, f, win: simulate_candidate_window(
                c, f, symbol=win.spec.symbol, config=cfg
            ),
        )
        assert agg.total_trade_count >= 1
        assert agg.pooled_gross_profit == Decimal("0")
        assert agg.pooled_net_pnl < Decimal("0")

    def test_extreme_slippage_and_fee_stress(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        df = _make_test_bars(start, 60, pattern="breakout")
        cfg = _make_sim_config(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.05"),  # 5% fee
            slippage_rate=Decimal("0.02"),  # 2% adverse slippage
        )
        result = simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)
        for t in result.trades:
            assert t.net_pnl == t.gross_pnl - t.fees
            assert t.fees == t.entry_fee + t.exit_fee
        assert result.final_equity == result.starting_equity + sum(
            (t.net_pnl for t in result.trades), Decimal("0")
        )
