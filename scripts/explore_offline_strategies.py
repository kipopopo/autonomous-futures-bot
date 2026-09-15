"""Offline strategy-family exploration across canonical Parquet data.

Executes deterministic, causal walk-forward trade simulation across
canonical 5m Parquet data for multiple strategy families and parameterizations,
without network calls, API credentials, or provider spending.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src/ is on sys.path
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.data.parquet import (  # noqa: E402
    DataQualityError,
    read_canonical_parquet,
)
from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.cached_evaluation import (  # noqa: E402
    CachedEvaluationWindow,
    CachedEvaluationWindowSpec,
)
from autonomous_futures.research.cached_oos_walk_forward import (  # noqa: E402
    evaluate_cached_oos_walk_forward,
)
from autonomous_futures.research.candidate_window_simulation import (  # noqa: E402
    simulate_candidate_window,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    CreatorCandidateQualificationArtifact,
    WalkForwardQualificationPolicy,
    build_walk_forward_qualification_artifact,
)
from autonomous_futures.research.trade_simulation import (  # noqa: E402
    TradeSimulationConfig,
    TradeSimulationResult,
)

logger = logging.getLogger(__name__)

DEFAULT_BUNDLE_HASH = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
DEFAULT_REGISTRY_HASH = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"

FORBIDDEN_CREDENTIAL_FLAGS: tuple[str, ...] = (
    "--api-key",
    "--apikey",
    "--api_key",
    "--gemini-api-key",
    "--gemini_api_key",
    "--google-ai-studio-api-key",
    "--token",
    "--api-token",
    "-k",
    "--secret",
    "--secret-key",
    "--secret_key",
    "--password",
    "--bearer",
    "--auth-token",
    "--auth_token",
    "--binance-api-key",
    "--binance_api_key",
    "--binance-api-secret",
    "--binance_api_secret",
)


def _check_forbidden_credential_flags(argv: Sequence[str]) -> bool:
    """Inspect CLI arguments for forbidden credential flags."""
    for arg in argv:
        prefix = arg.lower().split("=")[0].strip()
        if prefix in FORBIDDEN_CREDENTIAL_FLAGS:
            return True
    return False


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    if timeframe == "5m":
        return timedelta(minutes=5)
    if timeframe == "15m":
        return timedelta(minutes=15)
    if timeframe == "1h":
        return timedelta(hours=1)
    raise DataQualityError(f"unsupported timeframe: {timeframe}")


def _default_context_timeframe(timeframe: str) -> str:
    if timeframe == "5m":
        return "15m"
    if timeframe == "15m":
        return "1h"
    if timeframe == "1h":
        return "4h"
    return "15m"


def load_and_slice_windows(
    parquet_path: Path,
    *,
    symbol: str,
    timeframe: str = "5m",
    bundle_hash: str = DEFAULT_BUNDLE_HASH,
    dataset_registry_hash: str = DEFAULT_REGISTRY_HASH,
    windows_count: int = 3,
    bars_per_window: int = 288,
) -> tuple[CachedEvaluationWindow, ...]:
    """Slice canonical Parquet into contiguous historical walk-forward windows."""
    if not parquet_path.is_file():
        raise FileNotFoundError(f"Canonical Parquet file not found: {parquet_path}")

    delta = _timeframe_to_timedelta(timeframe)
    df = read_canonical_parquet(parquet_path, interval=delta)
    total_bars = windows_count * bars_per_window
    if len(df) < total_bars:
        raise DataQualityError(
            f"Insufficient bars in {parquet_path}: requested {total_bars} "
            f"({windows_count}x{bars_per_window}), found {len(df)}"
        )

    selected = df.iloc[-total_bars:].copy().reset_index(drop=True)
    windows: list[CachedEvaluationWindow] = []
    for i in range(windows_count):
        start_idx = i * bars_per_window
        end_idx = (i + 1) * bars_per_window
        sub = selected.iloc[start_idx:end_idx].copy().reset_index(drop=True)
        time_start = sub["timestamp"].iloc[0].to_pydatetime()
        time_end = sub["timestamp"].iloc[-1].to_pydatetime() + delta
        spec = CachedEvaluationWindowSpec(
            window_id=f"window-{symbol.lower()}-{i + 1:03d}",
            symbol=symbol,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            time_start=time_start,
            time_end=time_end,
            timeframe=timeframe,  # type: ignore[arg-type]
        )
        windows.append(CachedEvaluationWindow(spec=spec, frame=sub))
    return tuple(windows)


def generate_candidate_catalog(
    symbol: str,
    *,
    timeframe: str = "5m",
    bundle_hash: str = DEFAULT_BUNDLE_HASH,
    dataset_registry_hash: str = DEFAULT_REGISTRY_HASH,
    created_at: datetime | None = None,
) -> tuple[CreatorCandidateArtifact, ...]:
    """Generate a diverse catalog of causal candidate strategies across multiple families."""
    now = created_at or datetime.now(UTC)
    catalog: list[CreatorCandidateArtifact] = []
    context_tf = _default_context_timeframe(timeframe)
    universe = StrategyUniverse(
        symbols=(symbol,),
        timeframe=timeframe,  # type: ignore[arg-type]
        regime_context_timeframe=context_tf,  # type: ignore[arg-type]
    )

    # 1. Range Mean Reversion (Bollinger Z-Score + RSI)
    spec_rmr_1 = StrategySpec(
        dsl_version=2,
        strategy_id=f"cand-{symbol.lower()}-rmr-001",
        family="range_mean_reversion",
        universe=universe,
        features=(
            FeatureRef(name="bollinger_zscore", lookback=20, shift=1),
            FeatureRef(name="rsi", lookback=14, shift=1),
        ),
        entry=EntryExit(
            long="bollinger_zscore < -1.8 and rsi < 35.0",
            short="bollinger_zscore > 1.8 and rsi > 65.0",
        ),
        exit=EntryExit(
            long="bollinger_zscore > 0.0",
            short="bollinger_zscore < 0.0",
        ),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("2.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    catalog.append(
        build_creator_candidate_artifact(
            candidate_id=spec_rmr_1.strategy_id,
            strategy=spec_rmr_1,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id="explore-offline-001",
            research_seed=101,
            created_at=now,
        )
    )

    # 2. Donchian Channel Breakout (Trend Following, 20-bar)
    spec_dcb_1 = StrategySpec(
        dsl_version=2,
        strategy_id=f"cand-{symbol.lower()}-dcb-001",
        family="donchian_channel_breakout",
        universe=universe,
        features=(FeatureRef(name="donchian_breakout", lookback=20, shift=1),),
        entry=EntryExit(
            long="donchian_breakout > 0.0",
            short="donchian_breakout < 0.0",
        ),
        exit=EntryExit(
            long="donchian_breakout < 0.0",
            short="donchian_breakout > 0.0",
        ),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("2.0"),
            take_profit_atr_multiplier=Decimal("4.0"),
            trailing_atr_multiplier=Decimal("1.5"),
        ),
    )
    catalog.append(
        build_creator_candidate_artifact(
            candidate_id=spec_dcb_1.strategy_id,
            strategy=spec_dcb_1,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id="explore-offline-001",
            research_seed=102,
            created_at=now,
        )
    )

    # 3. Donchian Channel Breakout (Slower Trend Following, 50-bar)
    spec_dcb_2 = StrategySpec(
        dsl_version=2,
        strategy_id=f"cand-{symbol.lower()}-dcb-002",
        family="donchian_channel_breakout",
        universe=universe,
        features=(FeatureRef(name="donchian_breakout", lookback=50, shift=1),),
        entry=EntryExit(
            long="donchian_breakout > 0.0",
            short="donchian_breakout < 0.0",
        ),
        exit=EntryExit(
            long="donchian_breakout < 0.0",
            short="donchian_breakout > 0.0",
        ),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("2.5"),
            take_profit_atr_multiplier=Decimal("5.0"),
            trailing_atr_multiplier=Decimal("2.0"),
        ),
    )
    catalog.append(
        build_creator_candidate_artifact(
            candidate_id=spec_dcb_2.strategy_id,
            strategy=spec_dcb_2,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id="explore-offline-001",
            research_seed=103,
            created_at=now,
        )
    )

    # 4. Volatility Compression Breakout (Bollinger Squeeze + Breakout)
    spec_vcb_1 = StrategySpec(
        dsl_version=2,
        strategy_id=f"cand-{symbol.lower()}-vcb-001",
        family="volatility_compression_breakout",
        universe=universe,
        features=(
            FeatureRef(name="donchian_breakout", lookback=20, shift=1),
            FeatureRef(name="bollinger_width", lookback=20, shift=1),
        ),
        entry=EntryExit(
            long="donchian_breakout > 0.0 and bollinger_width < 0.04",
            short="donchian_breakout < 0.0 and bollinger_width < 0.04",
        ),
        exit=EntryExit(
            long="donchian_breakout < 0.0",
            short="donchian_breakout > 0.0",
        ),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("2.0"),
            take_profit_atr_multiplier=Decimal("3.5"),
            trailing_atr_multiplier=Decimal("1.2"),
        ),
    )
    catalog.append(
        build_creator_candidate_artifact(
            candidate_id=spec_vcb_1.strategy_id,
            strategy=spec_vcb_1,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id="explore-offline-001",
            research_seed=104,
            created_at=now,
        )
    )

    # 5. Volume-Confirmed Momentum (Momentum + Volume Spike)
    spec_vcm_1 = StrategySpec(
        dsl_version=2,
        strategy_id=f"cand-{symbol.lower()}-vcm-001",
        family="volume_confirmed_momentum",
        universe=universe,
        features=(
            FeatureRef(name="returns", lookback=3, shift=1),
            FeatureRef(name="relative_volume", lookback=20, shift=1),
        ),
        entry=EntryExit(
            long="returns > 0.0015 and relative_volume > 1.6",
            short="returns < -0.0015 and relative_volume > 1.6",
        ),
        exit=EntryExit(
            long="returns < -0.001",
            short="returns > 0.001",
        ),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("3.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    catalog.append(
        build_creator_candidate_artifact(
            candidate_id=spec_vcm_1.strategy_id,
            strategy=spec_vcm_1,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id="explore-offline-001",
            research_seed=105,
            created_at=now,
        )
    )

    # 6. Regime Gated Breakout (ADX Trend Strength Filter + Breakout)
    spec_rgb_1 = StrategySpec(
        dsl_version=2,
        strategy_id=f"cand-{symbol.lower()}-rgb-001",
        family="regime_gated_breakout",
        universe=universe,
        features=(
            FeatureRef(name="donchian_breakout", lookback=20, shift=1),
            FeatureRef(name="adx", lookback=14, shift=1),
        ),
        entry=EntryExit(
            long="donchian_breakout > 0.0 and adx > 25.0",
            short="donchian_breakout < 0.0 and adx > 25.0",
        ),
        exit=EntryExit(
            long="donchian_breakout < 0.0",
            short="donchian_breakout > 0.0",
        ),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("2.0"),
            take_profit_atr_multiplier=Decimal("4.0"),
            trailing_atr_multiplier=Decimal("1.5"),
        ),
    )
    catalog.append(
        build_creator_candidate_artifact(
            candidate_id=spec_rgb_1.strategy_id,
            strategy=spec_rgb_1,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id="explore-offline-001",
            research_seed=106,
            created_at=now,
        )
    )

    # 7. VWAP Reclaim Reversal (Experimental)
    spec_vwap_1 = StrategySpec(
        dsl_version=2,
        strategy_id=f"cand-{symbol.lower()}-vwap-001",
        family="experimental",
        universe=universe,
        features=(
            FeatureRef(name="vwap_reclaim", lookback=24, shift=1),
            FeatureRef(name="relative_volume", lookback=20, shift=1),
        ),
        entry=EntryExit(
            long="vwap_reclaim > 0.0 and relative_volume > 1.2",
            short="vwap_reclaim < 0.0 and relative_volume > 1.2",
        ),
        exit=EntryExit(
            long="vwap_reclaim < 0.0",
            short="vwap_reclaim > 0.0",
        ),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("2.5"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    catalog.append(
        build_creator_candidate_artifact(
            candidate_id=spec_vwap_1.strategy_id,
            strategy=spec_vwap_1,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id="explore-offline-001",
            research_seed=107,
            created_at=now,
        )
    )

    # 8. Failed Breakout Re-entry (Experimental)
    spec_fbr_1 = StrategySpec(
        dsl_version=2,
        strategy_id=f"cand-{symbol.lower()}-fbr-001",
        family="experimental",
        universe=universe,
        features=(
            FeatureRef(name="failed_breakout_reentry", lookback=20, shift=1),
            FeatureRef(name="bollinger_width", lookback=20, shift=1),
        ),
        entry=EntryExit(
            long="failed_breakout_reentry > 0.0 and bollinger_width < 0.06",
            short="failed_breakout_reentry < 0.0 and bollinger_width < 0.06",
        ),
        exit=EntryExit(
            long="failed_breakout_reentry < 0.0",
            short="failed_breakout_reentry > 0.0",
        ),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.10"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("3.0"),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    catalog.append(
        build_creator_candidate_artifact(
            candidate_id=spec_fbr_1.strategy_id,
            strategy=spec_fbr_1,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            creator_run_id="explore-offline-001",
            research_seed=108,
            created_at=now,
        )
    )

    return tuple(catalog)


def evaluate_candidate_offline(
    candidate: CreatorCandidateArtifact,
    windows: tuple[CachedEvaluationWindow, ...],
    policy: WalkForwardQualificationPolicy,
    *,
    simulation_config: TradeSimulationConfig | None = None,
    evaluator_run_id: str = "explore-evaluator-001",
    evaluator_version: str = "1.0.0",
) -> tuple[CreatorCandidateQualificationArtifact, dict[str, Any]]:
    """Evaluate one candidate across windows and produce qualification artifact and summary dict."""
    config = simulation_config or TradeSimulationConfig(
        starting_equity=Decimal("100.00"),
        position_fraction=Decimal("0.10"),
        taker_fee_rate=Decimal("0.0004"),
        slippage_rate=Decimal("0.0002"),
        atr_lookback=14,
        stop_atr_multiplier=Decimal("2.0"),
        take_profit_atr_multiplier=Decimal("3.0"),
        trailing_atr_multiplier=Decimal("1.0"),
    )

    def _sim(
        c: CreatorCandidateArtifact, f: Any, w: CachedEvaluationWindow
    ) -> TradeSimulationResult:
        return simulate_candidate_window(c, f, symbol=w.spec.symbol, config=config)

    aggregation = evaluate_cached_oos_walk_forward(candidate, windows, simulator=_sim)
    now = datetime.now(UTC)

    qualification = build_walk_forward_qualification_artifact(
        candidate=candidate,
        aggregation=aggregation,
        policy=policy,
        evaluator_run_id=evaluator_run_id,
        evaluator_version=evaluator_version,
        evaluated_at=now,
    )

    failed_gate_ids = [g.gate_id for g in qualification.gates if not g.passed]
    summary = {
        "candidate_id": candidate.candidate_id,
        "family": candidate.strategy.family,
        "symbol": candidate.strategy.universe.symbols[0],
        "decision": qualification.decision,
        "trades_count": aggregation.total_trade_count,
        "profit_factor": (
            str(aggregation.pooled_profit_factor)
            if aggregation.pooled_profit_factor is not None
            else "None"
        ),
        "pooled_net_pnl": str(aggregation.pooled_net_pnl),
        "worst_drawdown_pct": str(aggregation.worst_max_drawdown_pct),
        "average_return_pct": str(aggregation.average_return_pct),
        "windows_evaluated": aggregation.window_count,
        "failed_gate_ids": failed_gate_ids,
        "qualification_hash": qualification.qualification_hash,
    }
    return qualification, summary


def run_strategy_exploration(
    symbols: Sequence[str] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    parquet_dir: Path | str | None = None,
    *,
    timeframe: str = "5m",
    windows_count: int = 3,
    bars_per_window: int | None = None,
    policy: WalkForwardQualificationPolicy | None = None,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Execute complete offline strategy exploration across symbols."""
    pdir = (
        Path(parquet_dir)
        if parquet_dir is not None
        else Path(f"research/immutable-data/{timeframe}/canonical")
    )
    if bars_per_window is None:
        if timeframe == "5m":
            actual_bars_per_window = 288
        elif timeframe == "15m":
            actual_bars_per_window = 192
        elif timeframe == "1h":
            actual_bars_per_window = 168
        else:
            actual_bars_per_window = 288
    else:
        actual_bars_per_window = bars_per_window

    qual_policy = policy or WalkForwardQualificationPolicy(
        policy_id="policy-offline-exploration-001",
        minimum_windows=1,
        minimum_trades=5,
        minimum_profit_factor=Decimal("1.05"),
        maximum_drawdown_pct=Decimal("15.0"),
        minimum_average_return_pct=Decimal("0.0"),
    )

    leaderboard: list[dict[str, Any]] = []
    qualifications: dict[str, CreatorCandidateQualificationArtifact] = {}
    candidates_map: dict[str, CreatorCandidateArtifact] = {}

    for symbol in symbols:
        parquet_file = pdir / f"{symbol}-{timeframe}.parquet"
        if not parquet_file.is_file():
            logger.warning("Parquet data not found for %s at %s, skipping", symbol, parquet_file)
            continue

        windows = load_and_slice_windows(
            parquet_file,
            symbol=symbol,
            timeframe=timeframe,
            windows_count=windows_count,
            bars_per_window=actual_bars_per_window,
        )

        catalog = generate_candidate_catalog(symbol, timeframe=timeframe)
        for cand in catalog:
            candidates_map[cand.candidate_id] = cand
            qual, summary = evaluate_candidate_offline(cand, windows, qual_policy)
            qualifications[cand.candidate_id] = qual
            leaderboard.append(summary)

    # Sort leaderboard: qualified first, then profit factor desc, then net P&L desc
    def _sort_key(item: dict[str, Any]) -> tuple[int, float, float]:
        is_qual = 1 if item["decision"] == "qualified" else 0
        try:
            pf = float(item["profit_factor"]) if item["profit_factor"] != "None" else -1.0
        except ValueError:
            pf = -1.0
        try:
            pnl = float(item["pooled_net_pnl"])
        except ValueError:
            pnl = -9999.0
        return (is_qual, pf, pnl)

    leaderboard.sort(key=_sort_key, reverse=True)

    qualified_count = sum(1 for item in leaderboard if item["decision"] == "qualified")
    rejected_count = len(leaderboard) - qualified_count

    result: dict[str, Any] = {
        "status": "completed",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "timeframe": timeframe,
        "symbols_evaluated": list(symbols),
        "total_candidates": len(leaderboard),
        "qualified_count": qualified_count,
        "rejected_count": rejected_count,
        "policy": qual_policy.model_dump(mode="json"),
        "leaderboard": leaderboard,
        "data_source": "cached_only",
        "exchange_access": False,
        "execution_authority": False,
        "paper_activation": False,
    }

    if output_dir is not None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        summary_file = out_path / "exploration_summary.json"
        summary_file.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        logger.info("Saved exploration summary to %s", summary_file)

    return result


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for offline strategy exploration."""
    args_list = list(argv if argv is not None else sys.argv[1:])
    if _check_forbidden_credential_flags(args_list):
        sys.stderr.write("FATAL: credential flags are strictly forbidden in offline exploration\n")
        return 2

    parser = argparse.ArgumentParser(
        description="Deterministic offline strategy-family exploration tool."
    )
    parser.add_argument(
        "--timeframe",
        choices=["5m", "15m", "1h"],
        default="5m",
        help="Bar interval for exploration (default: 5m)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        help="Symbols to screen (default: BTCUSDT ETHUSDT SOLUSDT)",
    )
    parser.add_argument(
        "--parquet-dir",
        type=Path,
        default=None,
        help="Path to canonical parquet directory (default: derived from timeframe)",
    )
    parser.add_argument(
        "--windows-count",
        type=int,
        default=3,
        help="Number of contiguous walk-forward windows (default: 3)",
    )
    parser.add_argument(
        "--bars-per-window",
        type=int,
        default=None,
        help="Number of bars per window (default: 288 for 5m, 192 for 15m, 168 for 1h)",
    )
    parser.add_argument(
        "--min-profit-factor",
        type=Decimal,
        default=Decimal("1.05"),
        help="Qualification minimum profit factor (default: 1.05)",
    )
    parser.add_argument(
        "--max-drawdown-pct",
        type=Decimal,
        default=Decimal("15.0"),
        help="Qualification maximum drawdown pct (default: 15.0)",
    )
    parser.add_argument(
        "--min-average-return-pct",
        type=Decimal,
        default=Decimal("0.0"),
        help="Qualification minimum average return pct (default: 0.0)",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=5,
        help="Qualification minimum trades (default: 5)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to store exploration artifacts",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human table",
    )

    args = parser.parse_args(args_list)

    policy = WalkForwardQualificationPolicy(
        policy_id="policy-offline-screen-001",
        minimum_windows=1,
        minimum_trades=args.min_trades,
        minimum_profit_factor=args.min_profit_factor,
        maximum_drawdown_pct=args.max_drawdown_pct,
        minimum_average_return_pct=args.min_average_return_pct,
    )

    out_dir = (
        args.output_dir
        if args.output_dir is not None
        else Path(f"data/research/strategy-exploration-{args.timeframe}")
    )
    results = run_strategy_exploration(
        symbols=args.symbols,
        parquet_dir=args.parquet_dir,
        timeframe=args.timeframe,
        windows_count=args.windows_count,
        bars_per_window=args.bars_per_window,
        policy=policy,
        output_dir=out_dir,
    )

    if args.json:
        sys.stdout.write(json.dumps(results, indent=2, sort_keys=True) + "\n")
        return 0

    # Format human-readable table
    actual_bpw = (
        args.bars_per_window
        if args.bars_per_window is not None
        else (192 if args.timeframe == "15m" else (168 if args.timeframe == "1h" else 288))
    )
    sys.stdout.write("\n=== OFFLINE STRATEGY EXPLORATION LEADERBOARD ===\n")
    sys.stdout.write(
        f"Symbols: {', '.join(results['symbols_evaluated'])} | "
        f"Timeframe: {args.timeframe} | "
        f"Windows: {args.windows_count} x {actual_bpw} bars | "
        f"Total: {results['total_candidates']} | "
        f"Qualified: {results['qualified_count']} | "
        f"Rejected: {results['rejected_count']}\n"
    )
    sys.stdout.write("-" * 110 + "\n")
    header = (
        f"{'Candidate ID':<24} {'Symbol':<8} {'Family':<26} {'Decision':<10} "
        f"{'Trades':<7} {'PF':<8} {'MaxDD %':<8} {'Net PnL':<10}"
    )
    sys.stdout.write(header + "\n")
    sys.stdout.write("-" * 110 + "\n")

    for item in results["leaderboard"]:
        pf_display = item["profit_factor"][:6] if item["profit_factor"] != "None" else "N/A"
        dd_display = item["worst_drawdown_pct"][:6]
        pnl_display = item["pooled_net_pnl"][:8]
        line = (
            f"{item['candidate_id']:<24} {item['symbol']:<8} {item['family']:<26} "
            f"{item['decision']:<10} {item['trades_count']:<7} {pf_display:<8} "
            f"{dd_display:<8} {pnl_display:<10}"
        )
        sys.stdout.write(line + "\n")

    sys.stdout.write("-" * 110 + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
