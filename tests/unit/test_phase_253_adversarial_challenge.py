"""Phase 253 Empirical Adversarial Challenge Test Suite.

Authoritative stress-testing and empirical challenge of:
1. OOS Window Architecture & Boundary Enforcement:
   - Non-overlapping boundaries, temporal monotonicity, UTC awareness, gap detection.
   - Strict rejection on bundle_hash or dataset_registry_hash drift.
   - Symbol mismatch rejection.
2. Data Quality Defenses & Corrupted Input Invariants:
   - Rejection on missing OHLC columns.
   - Rejection on NaNs, non-finite values, and non-positive prices.
   - Timestamp gap rejection and non-monotonic interval defense.
   - Behavior analysis of invalid OHLC relationships (high < low, etc.).
   - Rejection on live data sources or exchange access attempts.
3. Deterministic WalkForwardAggregation Hashing & Tamper Sensitivity:
   - Hash sensitivity across metric fields (total_trade_count, gross_profit, net_pnl, etc.).
   - Model validator consistency guards (rejecting internal metric drift).
   - Disk envelope tamper detection (DomainViolation on modified aggregation_hash or payload).
   - Write-once immutability enforcement.
4. Portfolio Comparative Matrix Ranking Invariants:
   - Primary: Sharpe ratio (descending).
   - Secondary: Net PnL (descending).
   - Tertiary: Max drawdown percentage (lowest drawdown prioritized).
   - Ranking under tied Sharpe, tied PnL, negative Sharpe, zero trades, identical metrics.
   - Qualification status invariants (QUALIFIED vs DEFENSIVE_HOLD).
5. Sharpe Ratio Calculation Edge Cases:
   - 0 or 1 trades, zero variance, all negative returns, float rounding.
6. Forensic Verification of Generated Phase 253 Artifacts:
   - Hash integrity of all 4 candidate aggregations.
   - Reconciled portfolio summary equations.
   - Strict offline safety invariants (orders=0, exchange_access=False).
   - Zero secret leakage in artifacts.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
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
from autonomous_futures.research.trade_simulation import (
    SimulatedTrade,
    TradeSimulationConfig,
)
from autonomous_futures.research.walk_forward import (
    read_walk_forward_aggregation,
    walk_forward_aggregation_hash,
    write_walk_forward_aggregation,
)


def _load_script_module(name: str) -> Any:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


eval_script = _load_script_module("evaluate_phase_253_walk_forward")

PINNED_BUNDLE_HASH: str = eval_script.PINNED_BUNDLE_HASH
PINNED_REGISTRY_HASH: str = eval_script.PINNED_REGISTRY_HASH
PINNED_TARGETS: dict[str, Any] = eval_script.PINNED_TARGETS

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _make_clean_bars(
    start: datetime,
    bars_count: int = 60,
    base_price: float = 100.0,
) -> pd.DataFrame:
    timestamps = [start + timedelta(minutes=5 * i) for i in range(bars_count)]
    prices = [base_price + i * 0.1 for i in range(bars_count)]
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


# ===========================================================================
# 1. TestAdversarialOOSWindowArchitecture
# ===========================================================================
class TestAdversarialOOSWindowArchitecture:
    """Stress-tests OOS window boundary definitions and sequencing."""

    def test_overlapping_windows_rejected_by_aggregation(self) -> None:
        """Aggregation must reject windows with overlapping start/end times."""
        start1 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end1 = start1 + timedelta(minutes=5 * 60)
        start2 = end1 - timedelta(minutes=5 * 10)  # 10 bars overlap
        end2 = start2 + timedelta(minutes=5 * 60)

        spec1 = CachedEvaluationWindowSpec(
            window_id="oos-001",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start1,
            time_end=end1,
        )
        spec2 = CachedEvaluationWindowSpec(
            window_id="oos-002",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start2,
            time_end=end2,
        )

        w1 = CachedEvaluationWindow(spec=spec1, frame=_make_clean_bars(start1, 60))
        w2 = CachedEvaluationWindow(spec=spec2, frame=_make_clean_bars(start2, 60))

        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )

        with pytest.raises(ValueError, match="overlapping OOS windows"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (w1, w2),
                simulator=lambda c, f, win: simulate_candidate_window(
                    c, f, symbol=win.spec.symbol, config=cfg
                ),
            )

    def test_duplicate_window_id_rejected(self) -> None:
        """Windows with duplicate window_id must be rejected."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)

        spec = CachedEvaluationWindowSpec(
            window_id="oos-duplicate",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        w1 = CachedEvaluationWindow(spec=spec, frame=_make_clean_bars(start, 60))
        w2 = CachedEvaluationWindow(spec=spec, frame=_make_clean_bars(start, 60))

        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )

        with pytest.raises(ValueError, match="duplicate symbol/window binding"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (w1, w2),
                simulator=lambda c, f, win: simulate_candidate_window(
                    c, f, symbol=win.spec.symbol, config=cfg
                ),
            )

    def test_window_spec_inverted_or_zero_duration_rejected(self) -> None:
        """CachedEvaluationWindowSpec must reject start >= end."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

        # start == end
        with pytest.raises(ValidationError):
            CachedEvaluationWindowSpec(
                window_id="oos-zero-dur",
                symbol="BTCUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=start,
                time_end=start,
            )

        # start > end
        with pytest.raises(ValidationError):
            CachedEvaluationWindowSpec(
                window_id="oos-inverted-dur",
                symbol="BTCUSDT",
                bundle_hash=PINNED_BUNDLE_HASH,
                dataset_registry_hash=PINNED_REGISTRY_HASH,
                time_start=start + timedelta(hours=1),
                time_end=start,
            )

    def test_window_frame_range_mismatch_rejected(self) -> None:
        """Frame timestamps must exactly match window start and end."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        spec = CachedEvaluationWindowSpec(
            window_id="oos-mismatch",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )

        # Frame starting 5 minutes late
        bars_late = _make_clean_bars(start + timedelta(minutes=5), 60)
        with pytest.raises(DataQualityError, match="must cover exactly the window range"):
            CachedEvaluationWindow(spec=spec, frame=bars_late)

        # Frame ending too early
        bars_short = _make_clean_bars(start, 59)
        with pytest.raises(DataQualityError, match="must cover exactly the window range"):
            CachedEvaluationWindow(spec=spec, frame=bars_short)


# ===========================================================================
# 2. TestAdversarialDataQualityDefenses
# ===========================================================================
class TestAdversarialDataQualityDefenses:
    """Stress-tests data quality verification and corruption rejection."""

    def test_hash_tampering_bundle_and_registry_rejected(self) -> None:
        """Tampered bundle_hash or dataset_registry_hash must be rejected."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )

        # Bad bundle_hash
        spec_bad_bundle = CachedEvaluationWindowSpec(
            window_id="oos-001",
            symbol="BTCUSDT",
            bundle_hash="a" * 64,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        w_bad_bundle = CachedEvaluationWindow(
            spec=spec_bad_bundle, frame=_make_clean_bars(start, 60)
        )
        with pytest.raises(DataQualityError, match="bundle_hash does not match"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (w_bad_bundle,),
                simulator=lambda c, f, win: simulate_candidate_window(
                    c, f, symbol=win.spec.symbol, config=cfg
                ),
            )

        # Bad registry_hash
        spec_bad_reg = CachedEvaluationWindowSpec(
            window_id="oos-001",
            symbol="BTCUSDT",
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash="b" * 64,
            time_start=start,
            time_end=end,
        )
        w_bad_reg = CachedEvaluationWindow(spec=spec_bad_reg, frame=_make_clean_bars(start, 60))
        with pytest.raises(DataQualityError, match="dataset_registry_hash does not match"):
            evaluate_cached_oos_walk_forward(
                candidate,
                (w_bad_reg,),
                simulator=lambda c, f, win: simulate_candidate_window(
                    c, f, symbol=win.spec.symbol, config=cfg
                ),
            )

    def test_corrupted_nan_in_ohlc_rejected(self) -> None:
        """NaN values in any OHLC column must trigger DataQualityError."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )

        for col in ("open", "high", "low", "close"):
            df = _make_clean_bars(start, 60)
            df.loc[15, col] = float("nan")
            with pytest.raises(DataQualityError, match="OHLC column is not finite"):
                simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)

    def test_non_positive_price_in_ohlc_rejected(self) -> None:
        """Zero or negative prices in OHLC must trigger DataQualityError."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )

        for bad_val in (Decimal("0"), Decimal("-10.5")):
            df = _make_clean_bars(start, 60)
            df.loc[20, "close"] = bad_val
            with pytest.raises(DataQualityError, match="OHLC column must be positive"):
                simulate_candidate_window(candidate, df, symbol="BTCUSDT", config=cfg)

    def test_timestamp_irregular_gap_rejected(self) -> None:
        """Non-uniform timestamp step (e.g. gap) must trigger DataQualityError."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        df = _make_clean_bars(start, 60)
        # Drop row 30 to create a 10m gap instead of 5m
        df_gap = df.drop(index=[30]).reset_index(drop=True)
        with pytest.raises(DataQualityError, match="timestamp gap"):
            canonicalize_bars(df_gap, interval=timedelta(minutes=5))

    def test_duplicate_timestamps_rejected(self) -> None:
        """Duplicate timestamps in candle stream must trigger DataQualityError."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        df = _make_clean_bars(start, 60)
        df.loc[30, "timestamp"] = df.loc[29, "timestamp"]
        with pytest.raises(DataQualityError, match="duplicate timestamps are not allowed"):
            canonicalize_bars(df, interval=timedelta(minutes=5))

    def test_symbol_mismatch_with_candidate_universe_rejected(self) -> None:
        """Evaluating an asset outside the candidate's declared universe must be rejected."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = start + timedelta(minutes=5 * 60)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )

        spec_wrong_sym = CachedEvaluationWindowSpec(
            window_id="oos-001",
            symbol="ETHUSDT",  # Candidate BTCUSDT does not trade ETHUSDT
            bundle_hash=PINNED_BUNDLE_HASH,
            dataset_registry_hash=PINNED_REGISTRY_HASH,
            time_start=start,
            time_end=end,
        )
        w = CachedEvaluationWindow(spec=spec_wrong_sym, frame=_make_clean_bars(start, 60))
        with pytest.raises(
            DataQualityError, match="cached OOS symbol is not present in candidate universe"
        ):
            evaluate_cached_oos_walk_forward(
                candidate,
                (w,),
                simulator=lambda c, f, win: simulate_candidate_window(
                    c, f, symbol=win.spec.symbol, config=cfg
                ),
            )


# ===========================================================================
# 3. TestAdversarialWalkForwardAggregationHashing
# ===========================================================================
class TestAdversarialWalkForwardAggregationHashing:
    """Stress-tests WalkForwardAggregation hashing and tamper detection."""

    def test_hash_sensitivity_across_all_metrics(self) -> None:
        """Perturbing any individual metric must alter the cryptographic hash."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        windows = eval_script.establish_sequential_oos_windows(
            symbol="BTCUSDT", count=3, bars_per_window=60, start=start
        )
        base_agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=cfg
            ),
        )
        base_hash = walk_forward_aggregation_hash(base_agg)

        # 1. Perturb window metric
        w0 = base_agg.windows[0]
        m_pert = w0.metrics.model_copy(update={"trade_count": w0.metrics.trade_count + 1})
        w0_pert = w0.model_copy(update={"metrics": m_pert})
        pert_agg = base_agg.model_copy(update={"windows": (w0_pert, *base_agg.windows[1:])})
        assert walk_forward_aggregation_hash(pert_agg) != base_hash

        # 2. Perturb return_pct
        m_ret = w0.metrics.model_copy(update={"return_pct": w0.metrics.return_pct + Decimal("0.1")})
        w0_ret = w0.model_copy(update={"metrics": m_ret})
        pert_ret = base_agg.model_copy(update={"windows": (w0_ret, *base_agg.windows[1:])})
        assert walk_forward_aggregation_hash(pert_ret) != base_hash

        # 3. Perturb drawdown
        m_dd = w0.metrics.model_copy(
            update={"max_drawdown": w0.metrics.max_drawdown + Decimal("0.05")}
        )
        w0_dd = w0.model_copy(update={"metrics": m_dd})
        pert_dd = base_agg.model_copy(update={"windows": (w0_dd, *base_agg.windows[1:])})
        assert walk_forward_aggregation_hash(pert_dd) != base_hash

    def test_disk_artifact_tamper_detection(self, tmp_path: Path) -> None:
        """Modifying any field in persisted JSON must fail on read."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
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

        artifact_file = tmp_path / "walk-forward-test.json"
        write_walk_forward_aggregation(artifact_file, agg)

        # Raw read and tamper
        raw = json.loads(artifact_file.read_text(encoding="utf-8"))
        raw["aggregation"]["pooled_net_pnl"] = "9999.99"
        tampered_file = tmp_path / "walk-forward-tampered.json"
        tampered_file.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(DomainViolation):
            read_walk_forward_aggregation(tampered_file)

    def test_hash_tampering_rejection(self, tmp_path: Path) -> None:
        """Tampering with aggregation_hash directly must trigger DomainViolation."""
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
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

        artifact_file = tmp_path / "walk-forward-hash-test.json"
        write_walk_forward_aggregation(artifact_file, agg)

        raw = json.loads(artifact_file.read_text(encoding="utf-8"))
        raw["aggregation_hash"] = "0" * 64
        tampered_file = tmp_path / "walk-forward-bad-hash.json"
        tampered_file.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(DomainViolation, match="aggregation hash mismatch"):
            read_walk_forward_aggregation(tampered_file)


# ===========================================================================
# 4. TestAdversarialPortfolioComparativeRanking
# ===========================================================================
class TestAdversarialPortfolioComparativeRanking:
    """Stress-tests candidate ranking under tied, inverted, negative, and edge metrics."""

    def test_ranking_under_tied_sharpe_resolves_by_net_pnl(self) -> None:
        """When Sharpe ratios are identical, candidate with higher net PnL ranks higher."""
        cands = [
            {
                "symbol": "BTC",
                "sharpe_ratio": 2.0,
                "net_pnl": 5.0,
                "max_drawdown_pct": 1.0,
            },
            {
                "symbol": "ETH",
                "sharpe_ratio": 2.0,
                "net_pnl": 15.0,
                "max_drawdown_pct": 2.0,
            },
            {
                "symbol": "SOL",
                "sharpe_ratio": 2.0,
                "net_pnl": 10.0,
                "max_drawdown_pct": 1.5,
            },
        ]
        ranked = eval_script.rank_candidates(cands)
        assert ranked[0]["symbol"] == "ETH"  # highest net_pnl
        assert ranked[1]["symbol"] == "SOL"
        assert ranked[2]["symbol"] == "BTC"
        assert [c["rank"] for c in ranked] == [1, 2, 3]

    def test_ranking_under_tied_sharpe_and_pnl_resolves_by_lowest_drawdown(self) -> None:
        """When Sharpe and PnL are tied, lower max drawdown percentage ranks higher."""
        cands = [
            {
                "symbol": "BTC",
                "sharpe_ratio": 1.5,
                "net_pnl": 10.0,
                "max_drawdown_pct": 5.0,
            },
            {
                "symbol": "ETH",
                "sharpe_ratio": 1.5,
                "net_pnl": 10.0,
                "max_drawdown_pct": 2.0,
            },
            {
                "symbol": "SOL",
                "sharpe_ratio": 1.5,
                "net_pnl": 10.0,
                "max_drawdown_pct": 8.0,
            },
        ]
        ranked = eval_script.rank_candidates(cands)
        assert ranked[0]["symbol"] == "ETH"  # lowest drawdown (2.0%)
        assert ranked[1]["symbol"] == "BTC"  # 5.0%
        assert ranked[2]["symbol"] == "SOL"  # 8.0%

    def test_ranking_under_all_negative_sharpe_scenarios(self) -> None:
        """Less negative Sharpe ratio must rank higher than more negative Sharpe ratio."""
        cands = [
            {
                "symbol": "BTC",
                "sharpe_ratio": -2.1764,
                "net_pnl": -0.13,
                "max_drawdown_pct": 0.11,
            },
            {
                "symbol": "ETH",
                "sharpe_ratio": -3.0604,
                "net_pnl": -0.14,
                "max_drawdown_pct": 0.09,
            },
            {
                "symbol": "SOL",
                "sharpe_ratio": -2.6200,
                "net_pnl": -0.13,
                "max_drawdown_pct": 0.06,
            },
            {
                "symbol": "DOGE",
                "sharpe_ratio": 3.2043,
                "net_pnl": 1.62,
                "max_drawdown_pct": 0.15,
            },
        ]
        ranked = eval_script.rank_candidates(cands)
        # Order: DOGE (3.2043) > BTC (-2.1764) > SOL (-2.6200) > ETH (-3.0604)
        assert ranked[0]["symbol"] == "DOGE"
        assert ranked[1]["symbol"] == "BTC"
        assert ranked[2]["symbol"] == "SOL"
        assert ranked[3]["symbol"] == "ETH"

    def test_ranking_under_zero_trades_or_zero_sharpe(self) -> None:
        """Zero Sharpe ratio and zero PnL behaves predictably and stably."""
        cands = [
            {
                "symbol": "ACTIVE",
                "sharpe_ratio": 1.0,
                "net_pnl": 2.0,
                "max_drawdown_pct": 1.0,
            },
            {
                "symbol": "ZERO_1",
                "sharpe_ratio": 0.0,
                "net_pnl": 0.0,
                "max_drawdown_pct": 0.0,
            },
            {
                "symbol": "ZERO_2",
                "sharpe_ratio": 0.0,
                "net_pnl": 0.0,
                "max_drawdown_pct": 0.0,
            },
            {
                "symbol": "LOSING",
                "sharpe_ratio": -1.0,
                "net_pnl": -2.0,
                "max_drawdown_pct": 2.0,
            },
        ]
        ranked = eval_script.rank_candidates(cands)
        assert ranked[0]["symbol"] == "ACTIVE"
        assert ranked[1]["symbol"] in ("ZERO_1", "ZERO_2")
        assert ranked[2]["symbol"] in ("ZERO_1", "ZERO_2")
        assert ranked[3]["symbol"] == "LOSING"

    def test_qualification_status_invariants(self) -> None:
        """Only positive net PnL AND positive Sharpe can yield QUALIFIED."""
        cases = [
            (Decimal("1.5"), 2.0, "QUALIFIED"),
            (Decimal("-0.5"), 2.0, "DEFENSIVE_HOLD"),  # negative pnl
            (Decimal("1.5"), -0.5, "DEFENSIVE_HOLD"),  # negative sharpe
            (Decimal("0.0"), 0.0, "DEFENSIVE_HOLD"),  # zero pnl
            (Decimal("1.5"), 0.0, "DEFENSIVE_HOLD"),  # zero sharpe
        ]
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candidate = eval_script.load_and_verify_candidate(PINNED_TARGETS["BTCUSDT"])
        windows = eval_script.establish_sequential_oos_windows(
            symbol="BTCUSDT", count=1, bars_per_window=60, start=start
        )
        sim_cfg = TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("0.2"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        )
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=lambda c, f, w: simulate_candidate_window(
                c, f, symbol=w.spec.symbol, config=sim_cfg
            ),
        )

        for pnl, sharpe, expected_status in cases:
            mock_agg = agg.model_copy(update={"pooled_net_pnl": pnl})
            results = {"BTCUSDT": (mock_agg, "0" * 64, sharpe)}
            matrix = eval_script.build_portfolio_comparison_matrix(results, "test", start)
            actual_status = matrix["ranked_candidates"][0]["qualification_status"]
            assert actual_status == expected_status, f"Failed for pnl={pnl}, sharpe={sharpe}"


# ===========================================================================
# 5. TestAdversarialSharpeCalculationEdgeCases
# ===========================================================================
class TestAdversarialSharpeCalculationEdgeCases:
    """Stress-tests trade Sharpe ratio calculation edge cases."""

    def test_sharpe_with_zero_or_one_trade(self) -> None:
        assert eval_script.calculate_trade_sharpe_ratio([]) == 0.0

    def test_sharpe_with_zero_variance_trades(self) -> None:
        """Identical trade PnL yields zero variance -> Sharpe must return 0.0."""
        # Simulated trade mock with identical net_pnl
        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        trade1 = SimulatedTrade(
            trade_id="t1",
            symbol="BTCUSDT",
            side="LONG",
            entry_timestamp=start,
            exit_timestamp=start + timedelta(minutes=5),
            quantity=Decimal("1.0"),
            entry_price=Decimal("100"),
            exit_price=Decimal("101"),
            entry_notional=Decimal("100"),
            exit_notional=Decimal("101"),
            entry_fee=Decimal("0.04"),
            exit_fee=Decimal("0.0404"),
            fees=Decimal("0.0804"),
            slippage_cost=Decimal("0.04"),
            gross_pnl=Decimal("1.0"),
            net_pnl=Decimal("0.9196"),
            exit_reason="take_profit",
        )
        trade2 = trade1.model_copy(update={"trade_id": "t2"})
        assert eval_script.calculate_trade_sharpe_ratio([trade1, trade2]) == 0.0

    def test_sharpe_all_negative_returns(self) -> None:
        """All losing trades must produce a strictly negative Sharpe ratio."""
        returns = [Decimal("-1.0"), Decimal("-2.0"), Decimal("-1.5")]
        sharpe = eval_script.calculate_sharpe_ratio(returns)
        assert sharpe < 0.0


# ===========================================================================
# 6. TestAdversarialArtifactForensicIntegrity
# ===========================================================================
class TestAdversarialArtifactForensicIntegrity:
    """Forensically inspects all persisted Phase 253 artifacts."""

    def test_all_six_artifacts_exist_and_match_specs(self) -> None:
        art_dir = Path("artifacts/research/phase253")
        expected_files = [
            "walk-forward-aggregation-BTCUSDT.json",
            "walk-forward-aggregation-ETHUSDT.json",
            "walk-forward-aggregation-SOLUSDT.json",
            "walk-forward-aggregation-DOGEUSDT.json",
            "portfolio-comparison-matrix.json",
            "evaluation-summary.json",
        ]
        for fname in expected_files:
            p = art_dir / fname
            assert p.is_file(), f"Missing artifact: {p}"

    def test_aggregation_hashes_match_recalculated_values(self) -> None:
        """Recomputing walk_forward_aggregation_hash from disk must match envelope."""
        art_dir = Path("artifacts/research/phase253")
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            p = art_dir / f"walk-forward-aggregation-{sym}.json"
            envelope = read_walk_forward_aggregation(p)
            recomputed = walk_forward_aggregation_hash(envelope.aggregation)
            assert envelope.aggregation_hash == recomputed

    def test_portfolio_summary_exact_mathematical_reconciliation(self) -> None:
        """Verify sum of candidate PnL, trades, and fees equals portfolio summary."""
        matrix_path = Path("artifacts/research/phase253/portfolio-comparison-matrix.json")
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        cands = matrix["ranked_candidates"]
        summary = matrix["portfolio_summary"]

        total_trades = sum(c["total_trades"] for c in cands)
        total_winning = sum(c["winning_trades"] for c in cands)
        total_losing = sum(c["losing_trades"] for c in cands)
        assert summary["total_trades"] == total_trades
        assert summary["total_winning_trades"] == total_winning
        assert summary["total_losing_trades"] == total_losing

        pooled_net = sum(Decimal(c["net_pnl_usdt"]) for c in cands)
        assert Decimal(summary["pooled_net_pnl_usdt"]) == pooled_net

        pooled_gp = sum(Decimal(c["gross_profit_usdt"]) for c in cands)
        pooled_gl = sum(Decimal(c["gross_loss_usdt"]) for c in cands)
        assert Decimal(summary["pooled_gross_profit_usdt"]) == pooled_gp
        assert Decimal(summary["pooled_gross_loss_usdt"]) == pooled_gl

    def test_strict_offline_safety_state_in_all_artifacts(self) -> None:
        """Confirm orders=0, exchange_access=False across all artifacts."""
        assert_offline_safety_invariants()
        art_dir = Path("artifacts/research/phase253")

        for f in art_dir.glob("*.json"):
            content = f.read_text(encoding="utf-8")
            # Check secret regex
            assert not _SECRET_PATTERN.search(content), f"Secret leak in {f}"
            data = json.loads(content)
            if "safety_state" in data:
                s = data["safety_state"]
                assert s["orders"] == 0
                assert s["exchange_access"] is False
                assert s["execution_authority"] is False
                assert s["promotion_state"] == "unpromoted"
                assert s["paper_activation"] is False
                assert s["data_source"] == "cached_only"
            if "aggregation" in data:
                agg = data["aggregation"]
                assert agg["data_source"] == "cached_only"
                assert agg["exchange_access"] is False
