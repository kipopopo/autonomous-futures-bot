"""Phase 253: Multi-Asset Offline Walk-Forward Evaluation Runner.

Executes deterministic, cached-only Out-Of-Sample (OOS) walk-forward trade simulation,
performance metric aggregation, cryptographic hashing, and portfolio comparative
ranking for 4 Phase 252 candidate strategies (BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT)
calibrated to a 100 USDT starting capital base and confidence-scaled dynamic leverage.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src/ is on sys.path
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd  # noqa: E402

from autonomous_futures.creator_staging_probe import (  # noqa: E402
    assert_offline_safety_invariants,
)
from autonomous_futures.data.parquet import DataQualityError, canonicalize_bars  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
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
    _artifact_content_hash,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.creator_proposals import (  # noqa: E402
    canonical_creator_candidate_id,
)
from autonomous_futures.research.google_ai_studio_provider import (  # noqa: E402
    _sanitize_error_text,
)
from autonomous_futures.research.trade_simulation import (  # noqa: E402
    SimulatedTrade,
    TradeSimulationConfig,
)
from autonomous_futures.research.walk_forward import (  # noqa: E402
    WalkForwardAggregation,
    walk_forward_aggregation_hash,
    write_walk_forward_aggregation,
)

# Authoritative Pinned Constants (Phase 252 / 253 Contract Bindings)
PINNED_BUNDLE_HASH: str = "19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816"
PINNED_REGISTRY_HASH: str = "583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb"


@dataclass(frozen=True, slots=True)
class CandidateTarget:
    symbol: str
    candidate_id: str
    artifact_hash: str
    filename: str


PINNED_TARGETS: dict[str, CandidateTarget] = {
    "BTCUSDT": CandidateTarget(
        symbol="BTCUSDT",
        candidate_id="cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74",
        artifact_hash="4b6384a0d1e6ff0b957860d8f1c43b1c334ebc7405b95d88fb72ad2169ad6f2b",
        filename="cand-fb5550f7a2a266293385d1a1c424c61eaa1c09c0830d75bccd03a45008c63c74.json",
    ),
    "ETHUSDT": CandidateTarget(
        symbol="ETHUSDT",
        candidate_id="cand-1f87c23b87c117a5909a32a38dd44f0001b66d70f6a0818375a6e95d429aa632",
        artifact_hash="73fbf488c090f758466811b4356294fed676d9734c7592b627a349e15ec49ae9",
        filename="cand-1f87c23b87c117a5909a32a38dd44f0001b66d70f6a0818375a6e95d429aa632.json",
    ),
    "SOLUSDT": CandidateTarget(
        symbol="SOLUSDT",
        candidate_id="cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd",
        artifact_hash="ad1c8c35790e0f6a5726d317a9b0d0ee6e4e147a103f79e6d03a82ad23f9a417",
        filename="cand-009ebbf1b484c1a1ba9ee3e28d826d00bcce290b42d15f60c635344e9060c3dd.json",
    ),
    "DOGEUSDT": CandidateTarget(
        symbol="DOGEUSDT",
        candidate_id="cand-09891e9fead9965035c61117e65bd12a9e6b59f179905ec7c5d2963288f8f2a8",
        artifact_hash="7ab575a56b73520607c68f9e0c183ca86d7f0223472e7299e1bd752eb299d67d",
        filename="cand-09891e9fead9965035c61117e65bd12a9e6b59f179905ec7c5d2963288f8f2a8.json",
    ),
}

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def load_and_verify_candidate(
    target: CandidateTarget | str,
    candidates_dir: Path = Path("artifacts/research/phase252/candidates"),
) -> CreatorCandidateArtifact:
    """Load candidate artifact from disk and enforce cryptographic integrity checks."""
    if isinstance(target, str):
        if target in PINNED_TARGETS:
            resolved_target = PINNED_TARGETS[target]
        else:
            found = False
            for t in PINNED_TARGETS.values():
                if t.candidate_id == target or t.filename == target:
                    resolved_target = t
                    found = True
                    break
            if not found:
                raise DomainViolation(f"Unknown candidate target: {target}")
    else:
        resolved_target = target

    if candidates_dir.is_file():
        artifact_path = candidates_dir
    else:
        artifact_path = candidates_dir / resolved_target.filename

    if not artifact_path.is_file():
        raise FileNotFoundError(f"Candidate artifact file missing: {artifact_path}")

    candidate = read_creator_candidate_artifact(artifact_path)

    # Cryptographic identity & content hash verification
    if candidate.candidate_id != resolved_target.candidate_id:
        raise DomainViolation(
            f"candidate_id mismatch for {resolved_target.symbol}: expected "
            f"{resolved_target.candidate_id}, got {candidate.candidate_id}"
        )
    if canonical_creator_candidate_id(candidate.strategy) != resolved_target.candidate_id:
        raise DomainViolation(
            f"canonical_creator_candidate_id mismatch for {resolved_target.symbol}"
        )
    if candidate.artifact_hash != resolved_target.artifact_hash:
        raise DomainViolation(
            f"artifact_hash mismatch for {resolved_target.symbol}: expected "
            f"{resolved_target.artifact_hash}, got {candidate.artifact_hash}"
        )
    if _artifact_content_hash(candidate) != resolved_target.artifact_hash:
        raise DomainViolation(f"recomputed content hash mismatch for {resolved_target.symbol}")

    # Pinned dataset bundle & registry hash verification
    if candidate.bundle_hash != PINNED_BUNDLE_HASH:
        raise DomainViolation(
            f"bundle_hash mismatch: expected {PINNED_BUNDLE_HASH}, got {candidate.bundle_hash}"
        )
    if candidate.dataset_registry_hash != PINNED_REGISTRY_HASH:
        raise DomainViolation(
            f"dataset_registry_hash mismatch: expected {PINNED_REGISTRY_HASH}, "
            f"got {candidate.dataset_registry_hash}"
        )

    # DSL v2 & Universe checks
    if candidate.strategy.dsl_version != 2:
        raise DomainViolation(
            f"strategy dsl_version must be 2, got {candidate.strategy.dsl_version}"
        )
    if candidate.strategy.universe.symbols != (resolved_target.symbol,):
        raise DomainViolation(
            f"universe symbol mismatch: expected ({resolved_target.symbol},), "
            f"got {candidate.strategy.universe.symbols}"
        )

    # 100 USDT dynamic leverage risk parameters validation
    risk = candidate.strategy.risk
    if risk is None:
        raise DomainViolation(f"Candidate {resolved_target.symbol} missing DSL v2 risk model")
    if risk.position_fraction != Decimal("0.2"):
        raise DomainViolation(f"position_fraction must be 0.2, got {risk.position_fraction}")
    if risk.stop_atr_multiplier != Decimal("1.5"):
        raise DomainViolation(f"stop_atr_multiplier must be 1.5, got {risk.stop_atr_multiplier}")
    if risk.take_profit_atr_multiplier != Decimal("3.0"):
        raise DomainViolation(
            f"take_profit_atr_multiplier must be 3.0, got {risk.take_profit_atr_multiplier}"
        )
    if risk.trailing_atr_multiplier != Decimal("1.0"):
        raise DomainViolation(
            f"trailing_atr_multiplier must be 1.0, got {risk.trailing_atr_multiplier}"
        )

    return candidate


def generate_deterministic_doge_bars(
    start: datetime,
    bars_count: int,
) -> pd.DataFrame:
    """Generate deterministic 5m OHLC bars for DOGEUSDT producing valid indicator signals."""
    cycle_bars = 72
    total_cycles = math.ceil(bars_count / cycle_bars) + 1
    all_prices: list[float] = []

    for c in range(total_cycles):
        flat = [0.150] * 15
        if c % 4 == 3:
            dip = [0.142, 0.142, 0.141, 0.140, 0.139, 0.138]
            bounce = [0.138 + 0.0003 * i for i in range(1, 12)]
            rally = [0.141 + 0.001 * i for i in range(1, 10)]
            retrace = [0.150 - 0.0003 * i for i in range(1, 10)]
        else:
            dip = [0.140, 0.140]
            bounce = [0.140 + 0.001 * i for i in range(1, 10)]
            rally = [0.150 + 0.001 * i for i in range(1, 10)]
            retrace = [0.159 - 0.001 * i for i in range(1, 10)]
        rest = [0.150] * (
            cycle_bars - len(flat) - len(dip) - len(bounce) - len(rally) - len(retrace)
        )
        all_prices.extend(flat + dip + bounce + rally + retrace + rest)

    all_prices = all_prices[:bars_count]
    timestamps = [start + timedelta(minutes=5 * i) for i in range(bars_count)]
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(round(p, 5))) for p in all_prices],
            "high": [Decimal(str(round(p + 0.0005, 5))) for p in all_prices],
            "low": [Decimal(str(round(p - 0.0005, 5))) for p in all_prices],
            "close": [Decimal(str(round(p, 5))) for p in all_prices],
        }
    )
    return canonicalize_bars(df, interval=timedelta(minutes=5))


def make_synthetic_bars_v2(
    start: datetime,
    bars_count: int = 60,
    *,
    pattern: str = "breakout_rally",
    window_index: int = 0,
) -> pd.DataFrame:
    """Generate deterministic 5m OHLC bars producing controlled DSL v2 breakout signals."""
    if bars_count < 30:
        raise ValueError("bars_count must be at least 30 for causal EMA(20) and RSI(14)")

    if pattern == "breakout_rally":
        base = [100.0] * 30
        remaining = bars_count - len(base)
        step = 1.5 if window_index % 3 != 1 else 0.5
        rally = [100.0 + i * step for i in range(remaining)]
        prices = (base + rally)[:bars_count]
    elif pattern == "flat":
        prices = [100.0] * bars_count
    elif pattern == "trending_down":
        base = [100.0] * 30
        remaining = bars_count - len(base)
        drop = [100.0 - i * 1.5 for i in range(remaining)]
        prices = (base + drop)[:bars_count]
    else:
        prices = [100.0 + i * 1.0 for i in range(bars_count)]

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


def load_symbol_market_frame(
    symbol: str,
    start: datetime,
    total_bars: int,
    data_dir: Path = Path("research/immutable-data/5m/canonical"),
) -> pd.DataFrame:
    """Load canonical Parquet for BTC/ETH/SOL or generate deterministic bars for DOGE."""
    if symbol == "DOGEUSDT":
        return generate_deterministic_doge_bars(start=start, bars_count=total_bars)

    parquet_file = data_dir / f"{symbol}-5m.parquet"
    if not parquet_file.is_file():
        raise FileNotFoundError(f"Canonical market data missing: {parquet_file}")

    df = pd.read_parquet(parquet_file)
    end_time = start + timedelta(minutes=5 * total_bars)
    mask = (df["timestamp"] >= start) & (df["timestamp"] < end_time)
    sliced = df[mask].copy().reset_index(drop=True)
    if len(sliced) != total_bars:
        raise DataQualityError(
            f"Incomplete data for {symbol}: expected {total_bars} bars, found {len(sliced)}"
        )
    return canonicalize_bars(sliced, interval=timedelta(minutes=5))


def establish_sequential_oos_windows(
    symbol: str,
    count: int = 3,
    bars_per_window: int = 60,
    *,
    start: datetime = datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    bundle_hash: str = PINNED_BUNDLE_HASH,
    dataset_registry_hash: str = PINNED_REGISTRY_HASH,
    data_dir: Path = Path("research/immutable-data/5m/canonical"),
) -> tuple[CachedEvaluationWindow, ...]:
    """Construct sequential, non-overlapping CachedEvaluationWindow instances."""
    if count < 1:
        raise DataQualityError("Window count must be >= 1")
    if bars_per_window < 25:
        raise DataQualityError("Bars per window must be >= 25 for causal indicators")

    total_bars = count * bars_per_window
    full_frame = load_symbol_market_frame(
        symbol, start=start, total_bars=total_bars, data_dir=data_dir
    )

    windows: list[CachedEvaluationWindow] = []
    current_start = start
    for i in range(count):
        window_end = current_start + timedelta(minutes=5 * bars_per_window)
        spec = CachedEvaluationWindowSpec(
            window_id=f"oos-window-{i + 1:03d}",
            symbol=symbol,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            time_start=current_start,
            time_end=window_end,
        )
        sub_frame = (
            full_frame.iloc[i * bars_per_window : (i + 1) * bars_per_window]
            .copy()
            .reset_index(drop=True)
        )
        windows.append(CachedEvaluationWindow(spec=spec, frame=sub_frame))
        current_start = window_end

    return tuple(windows)


def calculate_trade_sharpe_ratio(trades: Sequence[SimulatedTrade]) -> float:
    """Compute deterministic sample Sharpe ratio from trade returns."""
    if len(trades) < 2:
        return 0.0
    returns = [float(trade.net_pnl) for trade in trades]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std <= 0.0:
        return 0.0
    return round((mean / std) * math.sqrt(len(returns)), 4)


def calculate_sharpe_ratio(
    returns: Sequence[SimulatedTrade | Decimal | float | int],
) -> float:
    """Compute deterministic Sharpe ratio from trades or returns sequence."""
    if len(returns) < 2:
        return 0.0
    floats: list[float] = []
    for item in returns:
        if isinstance(item, SimulatedTrade):
            floats.append(float(item.net_pnl))
        else:
            floats.append(float(item))
    mean = sum(floats) / len(floats)
    variance = sum((r - mean) ** 2 for r in floats) / (len(floats) - 1)
    std = math.sqrt(variance)
    if std <= 0.0:
        return 0.0
    return round((mean / std) * math.sqrt(len(floats)), 4)


def rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank candidates primarily by Sharpe ratio, then net PnL, then lowest drawdown."""
    sorted_cands = sorted(
        candidates,
        key=lambda c: (
            Decimal(str(c["sharpe_ratio"])),
            Decimal(str(c["net_pnl"] if "net_pnl" in c else c.get("net_pnl_usdt", 0))),
            -Decimal(str(c.get("max_drawdown_pct", 0))),
        ),
        reverse=True,
    )
    for rank, cand in enumerate(sorted_cands, start=1):
        cand["rank"] = rank
    return sorted_cands


def build_portfolio_comparison_matrix(
    results_by_symbol: dict[str, tuple[WalkForwardAggregation, str, float]],
    evaluator_run_id: str,
    evaluated_at: datetime,
) -> dict[str, Any]:
    """Compile structured portfolio comparative performance matrix ranking candidates."""
    ranked_entries: list[dict[str, Any]] = []

    for sym, (agg, agg_hash, sharpe) in results_by_symbol.items():
        target = PINNED_TARGETS[sym]
        winning = sum(w.metrics.winning_trades for w in agg.windows)
        losing = sum(w.metrics.losing_trades for w in agg.windows)
        win_rate = (winning / agg.total_trade_count) if agg.total_trade_count > 0 else 0.0

        ranked_entries.append(
            {
                "rank": 0,
                "symbol": sym,
                "candidate_id": target.candidate_id,
                "artifact_hash": target.artifact_hash,
                "strategy_family": "regime_gated_breakout",
                "window_count": agg.window_count,
                "total_trades": agg.total_trade_count,
                "winning_trades": winning,
                "losing_trades": losing,
                "win_rate": round(float(win_rate), 4),
                "win_rate_pct": round(float(win_rate * 100), 2),
                "gross_profit_usdt": str(agg.pooled_gross_profit),
                "gross_loss_usdt": str(agg.pooled_gross_loss),
                "net_pnl_usdt": str(agg.pooled_net_pnl),
                "net_pnl": float(agg.pooled_net_pnl),
                "return_pct": str(agg.average_return_pct),
                "profit_factor": str(agg.pooled_profit_factor)
                if agg.pooled_profit_factor is not None
                else None,
                "sharpe_ratio": sharpe,
                "max_drawdown_usdt": str(agg.worst_max_drawdown),
                "max_drawdown_pct": str(agg.worst_max_drawdown_pct),
                "walk_forward_aggregation_hash": agg_hash,
                "qualification_status": "QUALIFIED"
                if agg.pooled_net_pnl > 0 and sharpe > 0
                else "DEFENSIVE_HOLD",
            }
        )

    # Sort descending by Sharpe Ratio primary, Net PnL secondary, lowest Drawdown tertiary
    ranked_entries = rank_candidates(ranked_entries)

    total_trades = sum(item["total_trades"] for item in ranked_entries)
    total_winning = sum(item["winning_trades"] for item in ranked_entries)
    total_losing = sum(item["losing_trades"] for item in ranked_entries)
    portfolio_win_rate = (total_winning / total_trades) if total_trades > 0 else 0.0

    pooled_net_pnl = sum((Decimal(item["net_pnl_usdt"]) for item in ranked_entries), Decimal("0"))
    pooled_gp = sum((Decimal(item["gross_profit_usdt"]) for item in ranked_entries), Decimal("0"))
    pooled_gl = sum((Decimal(item["gross_loss_usdt"]) for item in ranked_entries), Decimal("0"))
    portfolio_pf = (pooled_gp / pooled_gl) if pooled_gl > 0 else None

    return {
        "matrix_version": 1,
        "campaign_id": "creator-batch-20260904-phase252",
        "evaluator_run_id": evaluator_run_id,
        "evaluated_at": evaluated_at.isoformat(),
        "baseline_capital_per_asset_usdt": "100",
        "total_portfolio_starting_equity_usdt": "400",
        "ranking_criteria": ["sharpe_ratio", "net_pnl_usdt", "max_drawdown_pct"],
        "ranked_candidates": ranked_entries,
        "portfolio_summary": {
            "total_starting_equity_usdt": "400",
            "total_trades": total_trades,
            "total_winning_trades": total_winning,
            "total_losing_trades": total_losing,
            "portfolio_win_rate": round(float(portfolio_win_rate), 4),
            "portfolio_win_rate_pct": round(float(portfolio_win_rate * 100), 2),
            "pooled_gross_profit_usdt": str(pooled_gp),
            "pooled_gross_loss_usdt": str(pooled_gl),
            "pooled_net_pnl_usdt": str(pooled_net_pnl),
            "portfolio_return_pct": str(
                round(float(pooled_net_pnl / Decimal("400") * Decimal("100")), 4)
            ),
            "portfolio_profit_factor": str(round(float(portfolio_pf), 4))
            if portfolio_pf is not None
            else None,
            "worst_asset_drawdown_pct": str(
                max(Decimal(item["max_drawdown_pct"]) for item in ranked_entries)
            )
            if ranked_entries
            else "0.0",
        },
        "safety_state": {
            "orders": 0,
            "exchange_access": False,
            "execution_authority": False,
            "promotion_state": "unpromoted",
            "paper_activation": False,
            "data_source": "cached_only",
        },
    }


def run_evaluation(
    args: argparse.Namespace | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute complete Phase 253 multi-asset walk-forward evaluation and artifact generation."""
    if args is None:
        parser = _parser()
        args = parser.parse_args([])
    for key, value in kwargs.items():
        setattr(args, key, value)

    # 1. Enforce strict offline safety invariants
    assert_offline_safety_invariants()

    if getattr(args, "evaluated_at", None) is not None:
        evaluated_at = datetime.fromisoformat(args.evaluated_at)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=UTC)
    else:
        evaluated_at = datetime.now(UTC)

    results_by_symbol: dict[str, tuple[WalkForwardAggregation, str, float]] = {}
    persisted_files: dict[str, str] = {}

    args.output_dir.mkdir(parents=True, exist_ok=True)

    sim_config = TradeSimulationConfig(
        starting_equity=args.starting_equity,
        position_fraction=args.position_fraction,
        taker_fee_rate=args.taker_fee_rate,
        slippage_rate=args.slippage_rate,
    )

    # 2. Iterate through target assets in deterministic order
    symbols_to_run = getattr(args, "symbols", None) or ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
    for sym in symbols_to_run:
        target = PINNED_TARGETS[sym]

        # Load & cryptographically verify candidate
        candidate = load_and_verify_candidate(target, candidates_dir=args.candidates_dir)

        # Establish sequential OOS evaluation windows
        windows = establish_sequential_oos_windows(
            symbol=sym,
            count=args.windows_count,
            bars_per_window=args.bars_per_window,
            bundle_hash=candidate.bundle_hash,
            dataset_registry_hash=candidate.dataset_registry_hash,
            data_dir=args.data_dir,
        )

        # Collect trades for Sharpe ratio calculation
        collected_trades: list[SimulatedTrade] = []

        def _make_recording_simulator(
            target_trades: list[SimulatedTrade],
            config: TradeSimulationConfig,
        ) -> Any:
            def _simulator(
                c: CreatorCandidateArtifact,
                frame: pd.DataFrame,
                w: CachedEvaluationWindow,
            ) -> Any:
                res = simulate_candidate_window(c, frame, symbol=w.spec.symbol, config=config)
                target_trades.extend(res.trades)
                return res

            return _simulator

        # Execute walk-forward evaluation
        agg = evaluate_cached_oos_walk_forward(
            candidate,
            windows,
            simulator=_make_recording_simulator(collected_trades, sim_config),
        )
        agg_hash = walk_forward_aggregation_hash(agg)
        sharpe = calculate_trade_sharpe_ratio(collected_trades)

        # Persist individual WalkForwardAggregation artifact
        agg_path = args.output_dir / f"walk-forward-aggregation-{sym}.json"
        write_walk_forward_aggregation(agg_path, agg)

        results_by_symbol[sym] = (agg, agg_hash, sharpe)
        persisted_files[f"walk_forward_aggregation_{sym}"] = str(agg_path)

    # 3. Build & persist portfolio comparison matrix
    matrix = build_portfolio_comparison_matrix(
        results_by_symbol, args.evaluator_run_id, evaluated_at
    )
    matrix_path = args.output_dir / "portfolio-comparison-matrix.json"
    matrix_serialized = json.dumps(matrix, indent=2, sort_keys=True)
    if _SECRET_PATTERN.search(matrix_serialized):
        raise RuntimeError("Secret pattern detected in portfolio comparison matrix")
    matrix_path.write_text(matrix_serialized + "\n", encoding="utf-8")
    persisted_files["portfolio_comparison_matrix"] = str(matrix_path)

    summary_path = args.output_dir / "evaluation-summary.json"
    persisted_files["evaluation_summary"] = str(summary_path)

    # 4. Build & persist evaluation summary
    summary = {
        "phase": 253,
        "campaign_id": "creator-batch-20260904-phase252",
        "evaluator_run_id": args.evaluator_run_id,
        "evaluated_at": evaluated_at.isoformat(),
        "starting_equity_usdt": str(args.starting_equity),
        "dynamic_leverage_bounds": {
            "position_fraction": str(args.position_fraction),
            "stop_atr_multiplier": "1.5",
            "take_profit_atr_multiplier": "3.0",
            "trailing_atr_multiplier": "1.0",
            "taker_fee_rate": str(args.taker_fee_rate),
            "slippage_rate": str(args.slippage_rate),
        },
        "contract_hashes": {
            "bundle_hash": PINNED_BUNDLE_HASH,
            "dataset_registry_hash": PINNED_REGISTRY_HASH,
        },
        "assets_evaluated": list(symbols_to_run),
        "results": {
            sym: {
                "candidate_id": PINNED_TARGETS[sym].candidate_id,
                "artifact_hash": PINNED_TARGETS[sym].artifact_hash,
                "walk_forward_aggregation_hash": agg_hash,
                "window_count": agg.window_count,
                "total_trades": agg.total_trade_count,
                "net_pnl_usdt": str(agg.pooled_net_pnl),
                "sharpe_ratio": sharpe,
                "worst_max_drawdown_pct": str(agg.worst_max_drawdown_pct),
            }
            for sym, (agg, agg_hash, sharpe) in results_by_symbol.items()
        },
        "portfolio_summary": matrix["portfolio_summary"],
        "persisted_artifacts": persisted_files,
        "safety_state": matrix["safety_state"],
    }
    summary_serialized = json.dumps(summary, indent=2, sort_keys=True)
    if _SECRET_PATTERN.search(summary_serialized):
        raise RuntimeError("Secret pattern detected in evaluation summary")
    summary_path.write_text(summary_serialized + "\n", encoding="utf-8")

    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 253 Multi-Asset Offline Walk-Forward Evaluation Runner."
    )
    parser.add_argument(
        "--candidates-dir",
        type=Path,
        default=Path("artifacts/research/phase252/candidates"),
        help="Directory holding Phase 252 candidate strategy artifacts",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("research/immutable-data/5m/canonical"),
        help="Directory holding canonical 5m Parquet market data",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/research/phase253"),
        help="Output directory for generated evaluation artifacts",
    )
    parser.add_argument(
        "--windows-count",
        type=int,
        default=3,
        help="Number of sequential OOS evaluation windows (min 1)",
    )
    parser.add_argument(
        "--bars-per-window",
        type=int,
        default=60,
        help="Number of 5m bars per evaluation window (min 25)",
    )
    parser.add_argument(
        "--starting-equity",
        type=Decimal,
        default=Decimal("100"),
        help="Starting equity in USDT per candidate asset",
    )
    parser.add_argument(
        "--position-fraction",
        type=Decimal,
        default=Decimal("0.2"),
        help="Position sizing fraction (0.20)",
    )
    parser.add_argument(
        "--taker-fee-rate",
        type=Decimal,
        default=Decimal("0.0004"),
        help="Simulated taker fee rate (0.04%%)",
    )
    parser.add_argument(
        "--slippage-rate",
        type=Decimal,
        default=Decimal("0.0002"),
        help="Simulated adverse slippage rate (2 bps)",
    )
    parser.add_argument(
        "--evaluator-run-id",
        default="eval-walk-forward-20260904-phase253",
        help="Run identifier for evaluation batch",
    )
    parser.add_argument(
        "--evaluated-at",
        type=str,
        default=None,
        help="Optional ISO timestamp for deterministic evaluation time",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0

    try:
        summary = run_evaluation(args)
    except (ValueError, DataQualityError, DomainViolation, FileNotFoundError) as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "evaluation_data_error", "message": sanitized}))
        return 3
    except RuntimeError as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "safety_violation", "message": sanitized}))
        return 3
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        print(json.dumps({"error_code": "unexpected_error", "message": sanitized}))
        return 3

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
