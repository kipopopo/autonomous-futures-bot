from __future__ import annotations

import json
import os
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import FastAPI, HTTPException, Query
from pydantic import Field

from ..data.bundle import DatasetBundle
from ..data.registry import DatasetKind, DatasetRegistry, DatasetRegistryEntry
from ..domain.contracts import DomainModel
from ..paper.admission import StrategyAdmissionDecider
from ..research.creator_artifacts import CreatorCandidateRegistry
from ..research.creator_epoch import read_creator_epoch_configuration
from ..research.learner_artifacts import LearnerArtifact
from ..research.learner_metric_quality_qualification import (
    LearnerMetricQualityQualificationEvidence,
)
from ..research.learner_qualification import LearnerQualificationEvidence
from ..research.learner_quality_review import LearnerQualityReviewEvidence
from ..research.learner_runs import LearnerRun
from ..research.learner_training_evidence import LearnerTrainingEvidence
from ..research.qualification_artifacts import (
    CreatorCandidateQualificationArtifact,
    QualificationDecision,
    QualificationSource,
)
from .artifacts import (
    ArtifactInspection,
    ArtifactIntegrityError,
    inspect_dataset_artifacts,
)
from .canary import (
    CanaryAccountingResponse,
    CanaryAutoEvolutionResponse,
    CanaryAutonomousLifecycleResponse,
    CanaryBracketPositionsResponse,
    CanaryCalibrationResponse,
    CanaryEnsembleResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    CanaryExecutionGuardResponse,
    CanaryHawkesResponse,
    CanaryKillSwitchResponse,
    CanaryLiveMarketResponse,
    CanaryOrchestratorResponse,
    CanaryPaperExecutionResponse,
    CanaryPortfolioRebalancingResponse,
    CanaryProductionLaunchResponse,
    CanaryRiskResponse,
    CanaryStrategyActivationResponse,
    CanaryStrategyMiningResponse,
    CanaryStressFaultInjectionResponse,
    CanarySummaryResponse,
    CanaryTestnetBridgeResponse,
    CanaryTestnetGatewayResponse,
    CandidatePromotionItem,
    CandidateSignalItem,
    LedgerReconciliationItem,
    VetoInterlockItem,
    load_verified_canary_accounting,
    load_verified_canary_auto_evolution,
    load_verified_canary_autonomous_lifecycle,
    load_verified_canary_bracket_positions,
    load_verified_canary_calibration,
    load_verified_canary_ensemble,
    load_verified_canary_execution_guard,
    load_verified_canary_hawkes,
    load_verified_canary_kill_switch,
    load_verified_canary_live_market,
    load_verified_canary_orchestrator,
    load_verified_canary_paper_execution,
    load_verified_canary_portfolio_rebalancing,
    load_verified_canary_production_launch,
    load_verified_canary_risk,
    load_verified_canary_strategy_activation,
    load_verified_canary_strategy_mining,
    load_verified_canary_stress_fault_injection,
    load_verified_canary_summary,
    load_verified_canary_testnet_bridge,
    load_verified_canary_testnet_gateway,
)
from .catalog import (
    DatasetCatalogIntegrityError,
    VerifiedDatasetCatalog,
    load_verified_dataset_catalog,
)
from .creator import (
    CreatorCandidateRegistryIntegrityError,
    CreatorCandidateRegistryNotFoundError,
    load_verified_creator_candidate_registry,
)
from .learner import (
    LearnerArtifactNotFoundError,
    LearnerEvidenceIntegrityError,
    LearnerQualificationEvidenceIntegrityError,
    LearnerQualificationEvidenceNotFoundError,
    LearnerQualityReviewEvidenceIntegrityError,
    LearnerQualityReviewEvidenceNotFoundError,
    LearnerRunNotFoundError,
    LearnerTrainingEvidenceIntegrityError,
    LearnerTrainingEvidenceNotFoundError,
    VerifiedLearnerEvidence,
    load_verified_learner_artifact,
    load_verified_learner_qualification_evidence,
    load_verified_learner_quality_review_evidence,
    load_verified_learner_run,
    load_verified_learner_training_evidence,
)
from .metric_quality_qualification import (
    LearnerMetricQualityQualificationEvidenceIntegrityError,
    LearnerMetricQualityQualificationEvidenceNotFoundError,
    load_verified_metric_quality_qualification_evidence,
)
from .qualification import (
    CreatorQualificationArtifactIntegrityError,
    CreatorQualificationArtifactNotFoundError,
    load_verified_creator_candidate_qualification,
    load_verified_creator_candidate_qualifications,
)
from .query import (
    MAX_QUERY_ROWS,
    JSONScalar,
    QueryDataIntegrityError,
    QueryError,
    query_component_rows,
)
from .strategy_router import (
    CandidateGenomeItem,
    IctSignalPairItem,
    IctSignalsResponse,
    PdArrayItem,
    TradeAutopsyItem,
    TwinsStateItem,
    register_strategy_routes,
    strategy_router,
)
from .telemetry_ws import (
    TelemetryBroadcastManager,
    register_telemetry_websocket,
)


class HealthResponse(DomainModel):
    status: Literal["ok"] = "ok"
    service: Literal["autonomous-futures-data-api"] = "autonomous-futures-data-api"
    paper_safe: Literal[True] = True
    execution_authority: Literal[False] = False


class BundleResponse(DomainModel):
    verified: Literal[True] = True
    registry_hash: str
    bundle_hash: str
    component_count: int
    bundle: DatasetBundle


class RegistryResponse(DomainModel):
    verified: Literal[True] = True
    registry: DatasetRegistry


class CreatorRegistryResponse(DomainModel):
    verified: Literal[True] = True
    registry_hash: str
    candidate_count: int
    registry: CreatorCandidateRegistry


class CreatorQualificationSummary(DomainModel):
    candidate_id: str
    decision: QualificationDecision
    source: QualificationSource
    qualification_hash: str
    evaluator_run_id: str
    evaluator_version: str
    windows_evaluated: int
    qualification_policy_id: str | None
    evaluated_at: datetime
    promotion_state: Literal["unpromoted"]
    execution_authority: Literal[False]


class CreatorQualificationsResponse(DomainModel):
    verified: Literal[True] = True
    candidate_count: int
    qualification_count: int
    missing_candidate_ids: tuple[str, ...]
    qualifications: tuple[CreatorQualificationSummary, ...]


class CreatorQualificationResponse(DomainModel):
    verified: Literal[True] = True
    artifact: CreatorCandidateQualificationArtifact


class LearnerArtifactResponse(DomainModel):
    verified: Literal[True] = True
    artifact: LearnerArtifact


class LearnerRunResponse(DomainModel):
    verified: Literal[True] = True
    run: LearnerRun


class LearnerTrainingEvidenceResponse(DomainModel):
    verified: Literal[True] = True
    evidence: LearnerTrainingEvidence


class LearnerQualityReviewEvidenceResponse(DomainModel):
    verified: Literal[True] = True
    evidence: LearnerQualityReviewEvidence


class LearnerQualificationEvidenceResponse(DomainModel):
    verified: Literal[True] = True
    evidence: LearnerQualificationEvidence


class LearnerMetricQualityQualificationEvidenceResponse(DomainModel):
    verified: Literal[True] = True
    evidence: LearnerMetricQualityQualificationEvidence


class ComponentsResponse(DomainModel):
    verified: Literal[True] = True
    component_count: int
    components: tuple[ArtifactInspection, ...]


class RowsResponse(DomainModel):
    verified: Literal[True] = True
    kind: DatasetKind
    symbol: str
    interval: str | None
    start: datetime
    end: datetime
    row_count: int
    limit: int
    rows: tuple[dict[str, JSONScalar], ...]


class CandlestickPoint(DomainModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketKlinesResponse(DomainModel):
    symbol: str
    interval: str
    source: str
    timestamp_ms: int
    count: int
    candles: tuple[CandlestickPoint, ...]


class ExecutionOrderItem(DomainModel):
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    order_type: str = "LIMIT"
    price: float
    quantity: float
    notional_usdt: float
    status: str
    fill_price: float | None = None
    fee_usdt: float = 0.0
    realized_pnl_usdt: float = 0.0
    timestamp_ms: int
    is_maker: bool = True


class ExecutionSolvency(DomainModel):
    starting_equity_usdt: float | None = None
    cash_usdt: float = 100.0
    available_balance_usdt: float | None = None
    allocated_margin_usdt: float = 0.0
    unrealized_pnl_usdt: float = 0.0
    realized_pnl_usdt: float | None = None
    total_equity_usdt: float = 100.0
    drift_usdt: float | None = None
    zero_balance_drift_verified: bool = False
    cash_reserve_pct: float = 100.0
    unencumbered_cash_verified: bool = False
    starting_equity: float | None = None
    cash: float = 100.0
    allocated_margin: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float | None = None
    total_equity: float = 100.0
    drift: float | None = None
    zero_balance_drift: bool = False


class ExecutionDailyRisk(DomainModel):
    verified: bool = False
    day_start_equity_usdt: float | None = None
    limit_pct: float | None = None
    limit_usdt: float | None = None
    loss_usdt: float | None = None
    remaining_usdt: float | None = None
    breached: bool | None = None
    equity_basis: str | None = None


class ExecutionRuntimeHealth(DomainModel):
    observed: bool = False
    timestamp_ms: int | None = None
    last_protective_cycle_ms: int | None = None
    cycle_error_type: str | None = None
    last_account_refresh_error_type: str | None = None
    scan_error_type: str | None = None
    market_connected: bool = False
    market_error_type: str | None = None
    user_stream_connected: bool = False
    user_stream_reconciliation_required: bool = False
    user_stream_entry_block_reason: str | None = None
    user_stream_error_type: str | None = None
    user_stream_last_event_type: str | None = None
    user_stream_event_count: int = 0
    user_stream_gap: bool = False
    force_flatten_reason: str | None = None
    market_generation: int = 0
    calibration_window_ms: int | None = None
    beta_per_second: float | None = None
    arrival_count: int = 0
    fit_error: str | None = None
    spectral_radius: float | None = None
    baseline_boundary_symbols: list[str] = Field(default_factory=list)
    event_counts: dict[str, int] = Field(default_factory=dict)


class ExecutionScalperCriteria(DomainModel):
    symbol: str = "SOLUSDT"
    variant_id: str = "sol-2-hf"
    price_below_ema20_atr: float = 0.0
    price_below_ema_threshold: float = 0.8
    price_triggered: bool = False
    relative_volume: float = 1.0
    volume_threshold: float = 1.2
    volume_triggered: bool = False
    rsi_14: float = 50.0
    rsi_threshold: float = 42.0
    rsi_triggered: bool = False
    maker_fee_pct: float = 0.02


class PortfolioVariantChecklistItem(DomainModel):
    member_id: str
    symbol: str
    tier: str
    close_price: float
    ema20: float
    atr14: float
    dist_atr: float
    price_below_ema20_atr: float
    distance_threshold: float
    dist_triggered: bool
    relative_volume: float
    vol_spike_multiplier: float
    vol_triggered: bool
    rsi_14: float
    rsi_threshold: float
    rsi_triggered: bool
    macro_regime: str
    macro_aligned: bool
    gates_passed: int
    gates_total: int = 4
    signal_ready: bool = False


class ExecutionPortfolioScanner(DomainModel):
    observed: bool = False
    portfolio_id: str = "macro-scalper-uninspected-3sym-medium-frequency-v1"
    evaluated_at_ms: int | None = None
    source: str = "unavailable"
    btc_regime: str = "UNKNOWN"
    ema50_1h: float | None = None
    ema200_1h: float | None = None
    ema50_4h: float | None = None
    ema200_4h: float | None = None
    variants: list[PortfolioVariantChecklistItem] = Field(default_factory=list)


class ExecutionPositionItem(DomainModel):
    symbol: str
    position_qty: float = 0.0
    allocated_exposure_usdt: float = 0.0
    state: str = "STANDBY / SCANNING"
    status: str = "STANDBY / SCANNING"
    entry_price: float | None = None
    mark_price: float | None = None
    last_price: float | None = None
    unrealized_pnl_usdt: float = 0.0
    allocated_margin_usdt: float = 0.0
    take_profit_price: float | None = None
    stop_loss_price: float | None = None


class ExecutionStatusResponse(DomainModel):
    verified: bool = False
    status: str = "ACCOUNT_OBSERVED"
    engine_state: str = "MICRO_CAPITAL_ACTIVE"
    timestamp_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    solvency: ExecutionSolvency
    positions: dict[str, ExecutionPositionItem]
    candidate_allocations: list[ExecutionPositionItem] = Field(default_factory=list)
    aggregate_exposure_usdt: float = 0.0
    recent_orders: list[ExecutionOrderItem] = Field(default_factory=list)
    total_orders: int = 0
    interlock_blocks_count: int = 0
    intra_day_loss_usdt: float | None = None
    daily_risk: ExecutionDailyRisk = Field(default_factory=ExecutionDailyRisk)
    runtime_health: ExecutionRuntimeHealth = Field(default_factory=ExecutionRuntimeHealth)
    scalper_criteria: ExecutionScalperCriteria | None = None
    portfolio_scanner: ExecutionPortfolioScanner = Field(
        default_factory=ExecutionPortfolioScanner
    )


def _resolve_research_dir() -> Path:
    if env_dir := os.environ.get("AFBOT_RESEARCH_DIR"):
        return Path(env_dir)
    if env_storage := os.environ.get("AFBOT_STORAGE_DIR"):
        p = Path(env_storage)
        if (p / "research").exists():
            return p / "research"
        return p
    cwd_artifacts = Path("artifacts/research")
    if cwd_artifacts.exists():
        return cwd_artifacts
    repo_artifacts = Path(__file__).resolve().parents[3] / "artifacts" / "research"
    if repo_artifacts.exists():
        return repo_artifacts
    vps_artifacts = Path("/opt/autonomous-futures-bot/artifacts/research")
    if vps_artifacts.exists():
        return vps_artifacts
    return cwd_artifacts


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except ValueError, TypeError:
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except ValueError, TypeError:
        return default


def _compute_ema_series(series: list[float], span: int) -> list[float]:
    """Computes Exponential Moving Average using standard alpha = 2.0 / (span + 1.0)."""
    if not series:
        return []
    alpha = 2.0 / (span + 1.0)
    ema_vals = [series[0]]
    for val in series[1:]:
        ema_vals.append((val * alpha) + (ema_vals[-1] * (1.0 - alpha)))
    return ema_vals


_GLOBAL_BTC_MACRO_CACHE: dict[str, Any] = {"ts": 0.0, "data": None, "last_btc_price": None}
_GLOBAL_LIVE_PRICES_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_GLOBAL_PORTFOLIO_SCANNER_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}


def reset_live_market_cache() -> None:
    """Resets global price and macro caches for fresh telemetry ingress."""
    _GLOBAL_LIVE_PRICES_CACHE["ts"] = 0.0
    _GLOBAL_LIVE_PRICES_CACHE["data"] = None
    _GLOBAL_BTC_MACRO_CACHE["ts"] = 0.0
    _GLOBAL_BTC_MACRO_CACHE["data"] = None
    _GLOBAL_BTC_MACRO_CACHE["last_btc_price"] = None
    _GLOBAL_PORTFOLIO_SCANNER_CACHE["ts"] = 0.0
    _GLOBAL_PORTFOLIO_SCANNER_CACHE["data"] = None


def compute_authentic_btc_macro(
    current_btc_price: float,
    research_dir: Path | None = None,
) -> dict[str, Any]:
    """Computes authentic Bitcoin 1h EMA 50, EMA 200 and regime without fake linear multipliers."""
    now_sec = time.time()
    if (
        _GLOBAL_BTC_MACRO_CACHE["data"] is not None
        and (now_sec - _GLOBAL_BTC_MACRO_CACHE["ts"]) < 5.0
        and _GLOBAL_BTC_MACRO_CACHE.get("last_btc_price") is not None
        and abs(float(current_btc_price) - float(_GLOBAL_BTC_MACRO_CACHE["last_btc_price"])) < 0.5
    ):
        return cast(dict[str, Any], _GLOBAL_BTC_MACRO_CACHE["data"])

    closes: list[float] = []
    source = "binance_futures_live"

    # 1. Attempt live 1h klines from Binance Futures public REST endpoint
    try:
        import urllib.request

        url = "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=210"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AutonomousFuturesBot/1.0 (PublicRestClient; Unauth)"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            if isinstance(raw, list) and len(raw) >= 50:
                closes = [float(item[4]) for item in raw]
                source = "binance_futures_live"
    except Exception:
        closes = []

    # 2. Fallback: Local canonical Parquet file
    if len(closes) < 50:
        base_dir = research_dir if research_dir is not None else _resolve_research_dir()
        parquet_candidates = [
            Path("research/immutable-data/1h/canonical/BTCUSDT-1h.parquet"),
            Path(__file__).resolve().parents[3]
            / "research"
            / "immutable-data"
            / "1h"
            / "canonical"
            / "BTCUSDT-1h.parquet",
            base_dir.parent.parent
            / "research"
            / "immutable-data"
            / "1h"
            / "canonical"
            / "BTCUSDT-1h.parquet",
        ]
        for ppath in parquet_candidates:
            if ppath.is_file():
                try:
                    import pandas as pd

                    df = pd.read_parquet(ppath, columns=["close"])
                    if len(df) >= 50:
                        closes = [float(x) for x in df["close"].tail(250).tolist()]
                        source = "local_parquet_cache"
                        break
                except Exception:
                    pass

    # 3. Fallback: Local CSV file
    if len(closes) < 50:
        csv_candidates = [
            Path("research/data/BTCUSDT-1h.csv"),
            Path(__file__).resolve().parents[3] / "research" / "data" / "BTCUSDT-1h.csv",
        ]
        for cpath in csv_candidates:
            if cpath.is_file():
                try:
                    import csv

                    c_rows: list[float] = []
                    with open(cpath, encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for r in reader:
                            if "close" in r and r["close"]:
                                c_rows.append(float(r["close"]))
                    if len(c_rows) >= 50:
                        closes = c_rows[-250:]
                        source = "local_csv_history"
                        break
                except Exception:
                    pass

    if len(closes) < 200:
        return {
            "current_price": current_btc_price,
            "ema50_1h": None,
            "ema200_1h": None,
            "regime": "UNKNOWN",
            "source": "unavailable",
        }

    # Compute authentic EMAs over the full series
    ema50_series = _compute_ema_series(closes, 50)
    ema200_series = _compute_ema_series(closes, min(200, len(closes)))

    latest_ema50 = round(ema50_series[-1], 2)
    latest_ema200 = round(ema200_series[-1], 2)

    # Determine authentic regime
    if latest_ema50 > latest_ema200 and current_btc_price > latest_ema200:
        regime = "BULLISH ALIGNED"
    elif latest_ema50 < latest_ema200 and current_btc_price < latest_ema200:
        regime = "BEARISH"
    else:
        regime = "SIDEWAYS"

    macro_data = {
        "current_price": float(current_btc_price),
        "ema50_1h": latest_ema50,
        "ema200_1h": latest_ema200,
        "regime": regime,
        "source": source,
    }

    _GLOBAL_BTC_MACRO_CACHE["ts"] = now_sec
    _GLOBAL_BTC_MACRO_CACHE["data"] = macro_data
    _GLOBAL_BTC_MACRO_CACHE["last_btc_price"] = current_btc_price

    return macro_data


TARGET_PERPETUAL_SYMBOLS: list[str] = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "LINKUSDT",
    "APTUSDT",
    "ADAUSDT",
]


def get_live_market_data(
    research_dir: Path | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Retrieves live market prices (last price, mark price, basis) and authentic macro
    indicators with 5s caching.
    """
    now_sec = time.time()
    if (
        not force_refresh
        and _GLOBAL_LIVE_PRICES_CACHE["data"] is not None
        and (now_sec - _GLOBAL_LIVE_PRICES_CACHE["ts"]) < 5.0
    ):
        return cast(dict[str, Any], _GLOBAL_LIVE_PRICES_CACHE["data"])

    target_syms = TARGET_PERPETUAL_SYMBOLS
    target_syms_set = set(target_syms)

    # 1. Primary: Binance Futures live ticker (Last Traded Price) + premiumIndex (Mark Price)
    try:
        import urllib.request
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_last_prices() -> list[dict[str, Any]]:
            url = "https://fapi.binance.com/fapi/v1/ticker/price"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "AutonomousFuturesBot/1.0 (PublicRestClient; Unauth)"},
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                return cast(list[dict[str, Any]], json.loads(resp.read().decode("utf-8")))

        def _fetch_mark_prices() -> list[dict[str, Any]]:
            url = "https://fapi.binance.com/fapi/v1/premiumIndex"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "AutonomousFuturesBot/1.0 (PublicRestClient; Unauth)"},
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                return cast(list[dict[str, Any]], json.loads(resp.read().decode("utf-8")))

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_last = executor.submit(_fetch_last_prices)
            fut_mark = executor.submit(_fetch_mark_prices)
            raw_last = fut_last.result()
            raw_mark = fut_mark.result()

        if isinstance(raw_last, list) and len(raw_last) > 0:
            last_prices = {
                item["symbol"]: float(item["price"])
                for item in raw_last
                if isinstance(item, dict) and item.get("symbol") in target_syms_set
            }
            mark_dict = {
                item["symbol"]: item
                for item in raw_mark
                if isinstance(item, dict) and item.get("symbol") in target_syms_set
            }
            if not target_syms_set.issubset(last_prices) or not target_syms_set.issubset(mark_dict):
                raise ValueError("Incomplete exchange price response")
            mark_prices: dict[str, float] = {}
            index_prices: dict[str, float] = {}
            funding_rates: dict[str, float] = {}
            pair_tickers: list[dict[str, Any]] = []

            for sym in target_syms:
                lp = last_prices.get(sym, 0.0)
                p_data = mark_dict.get(sym, {})
                mp = float(p_data["markPrice"])
                ip = float(p_data["indexPrice"])
                fr = float(p_data["lastFundingRate"])
                if lp <= 0.0 and mp > 0.0:
                    lp = mp
                if mp <= 0.0 and lp > 0.0:
                    mp = lp
                last_prices[sym] = lp
                mark_prices[sym] = mp
                index_prices[sym] = ip
                funding_rates[sym] = fr
                basis = round(lp - mp, 4)
                basis_pct = round(((lp - mp) / mp) * 100.0, 4) if mp > 0 else 0.0
                pair_tickers.append(
                    {
                        "symbol": sym,
                        "last_price": lp,
                        "mark_price": mp,
                        "index_price": ip,
                        "funding_rate": fr,
                        "basis": basis,
                        "basis_pct": basis_pct,
                    }
                )

            btc = last_prices["BTCUSDT"]
            macro = compute_authentic_btc_macro(btc, research_dir)
            res_data = {
                "timestamp_ms": int(now_sec * 1000),
                "prices": last_prices,
                "last_prices": last_prices,
                "mark_prices": mark_prices,
                "index_prices": index_prices,
                "funding_rates": funding_rates,
                "pair_tickers": pair_tickers,
                "BTCUSDT": last_prices["BTCUSDT"],
                "ETHUSDT": last_prices["ETHUSDT"],
                "SOLUSDT": last_prices["SOLUSDT"],
                "DOGEUSDT": last_prices["DOGEUSDT"],
                "BNBUSDT": last_prices["BNBUSDT"],
                "XRPUSDT": last_prices["XRPUSDT"],
                "SUIUSDT": last_prices["SUIUSDT"],
                "AVAXUSDT": last_prices["AVAXUSDT"],
                "NEARUSDT": last_prices["NEARUSDT"],
                "LINKUSDT": last_prices["LINKUSDT"],
                "APTUSDT": last_prices["APTUSDT"],
                "ADAUSDT": last_prices["ADAUSDT"],
                "btc_macro": macro,
                "source": "binance_futures_live",
            }
            _GLOBAL_LIVE_PRICES_CACHE["ts"] = now_sec
            _GLOBAL_LIVE_PRICES_CACHE["data"] = res_data
            return res_data
    except Exception:
        pass

    raise HTTPException(status_code=503, detail="Live market prices unavailable")


def _baseline_execution_status(timestamp_ms: int | None = None) -> ExecutionStatusResponse:
    raise HTTPException(status_code=503, detail="Fresh exchange account evidence unavailable")


def _load_runtime_health(account_path: Path) -> tuple[ExecutionRuntimeHealth, str, int]:
    health_path = account_path.parent / "runtime-health.json"
    if not health_path.is_file():
        return ExecutionRuntimeHealth(), "UNKNOWN", 0
    try:
        raw = json.loads(health_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("source") != "runtime_observation":
            return ExecutionRuntimeHealth(), "UNKNOWN", 0
        ts_ms = raw.get("timestamp_ms")
        if not isinstance(ts_ms, int) or abs(int(time.time() * 1000) - ts_ms) > 30_000:
            return ExecutionRuntimeHealth(), "UNKNOWN", 0
        micro = raw.get("microstructure")
        if not isinstance(micro, dict):
            micro = {}
        fit_raw = micro.get("fit")
        fit: dict[str, Any] | None = fit_raw if isinstance(fit_raw, dict) else None
        cal_raw = micro.get("calibration")
        cal: dict[str, Any] = cal_raw if isinstance(cal_raw, dict) else {}
        raw_sr = fit.get("spectral_radius") if fit is not None else None
        spectral_radius = float(raw_sr) if isinstance(raw_sr, (int, float)) else None
        raw_beta = (
            fit.get("beta_per_second")
            if fit is not None and fit.get("beta_per_second") is not None
            else cal.get("beta_per_second")
        )
        beta_per_second = float(raw_beta) if isinstance(raw_beta, (int, float)) else None
        raw_counts = fit.get("event_counts") if fit is not None else {}
        event_counts = (
            {str(k): int(v) for k, v in raw_counts.items() if isinstance(v, (int, float))}
            if isinstance(raw_counts, dict)
            else {}
        )
        raw_boundary = fit.get("baseline_boundary_symbols") if isinstance(fit, dict) else []
        baseline_boundary_symbols = (
            [str(s) for s in raw_boundary if isinstance(s, str)]
            if isinstance(raw_boundary, list)
            else []
        )
        fit_error = str(micro["fit_error"]) if isinstance(micro.get("fit_error"), str) else None
        streams_healthy = (
            bool(raw.get("market_connected"))
            and bool(raw.get("user_stream_connected"))
            and not bool(raw.get("user_stream_reconciliation_required"))
            and not bool(raw.get("user_stream_gap"))
            and raw.get("force_flatten_reason") is None
            and raw.get("cycle_error_type") is None
            and raw.get("last_account_refresh_error_type") is None
            and raw.get("scan_error_type") is None
        )
        hawkes_ready = (
            isinstance(fit, dict)
            and fit_error is None
            and spectral_radius is not None
            and 0.0 <= spectral_radius < 1.0
            and not baseline_boundary_symbols
        )
        is_hawkes_warmup = fit_error is not None and any(
            token in fit_error.lower() for token in ("span", "observed arrivals", "dimension")
        )
        if streams_healthy and hawkes_ready:
            engine_state = "QUALIFIED_PORTFOLIO_ACTIVE"
        elif streams_healthy and is_hawkes_warmup:
            engine_state = "QUALIFIED_PORTFOLIO_WARMUP"
        else:
            engine_state = "QUALIFIED_PORTFOLIO_DEGRADED"
        interlock_blocks = sum(
            1
            for cond in (
                not bool(raw.get("market_connected")),
                not bool(raw.get("user_stream_connected")),
                bool(raw.get("user_stream_reconciliation_required")),
                bool(raw.get("user_stream_gap")),
                raw.get("force_flatten_reason") is not None,
                fit_error is not None,
                spectral_radius is not None and spectral_radius >= 1.0,
            )
            if cond
        )
        runtime_health = ExecutionRuntimeHealth(
            observed=True,
            timestamp_ms=ts_ms,
            last_protective_cycle_ms=(
                int(raw["last_protective_cycle_ms"])
                if isinstance(raw.get("last_protective_cycle_ms"), int)
                else None
            ),
            cycle_error_type=(
                str(raw["cycle_error_type"])
                if isinstance(raw.get("cycle_error_type"), str)
                else None
            ),
            last_account_refresh_error_type=(
                str(raw["last_account_refresh_error_type"])
                if isinstance(raw.get("last_account_refresh_error_type"), str)
                else None
            ),
            scan_error_type=(
                str(raw["scan_error_type"]) if isinstance(raw.get("scan_error_type"), str) else None
            ),
            market_connected=bool(raw.get("market_connected")),
            market_error_type=(
                str(raw["market_error_type"])
                if isinstance(raw.get("market_error_type"), str)
                else None
            ),
            user_stream_connected=bool(raw.get("user_stream_connected")),
            user_stream_reconciliation_required=bool(
                raw.get("user_stream_reconciliation_required")
            ),
            user_stream_entry_block_reason=(
                str(raw["user_stream_entry_block_reason"])
                if isinstance(raw.get("user_stream_entry_block_reason"), str)
                else None
            ),
            user_stream_error_type=(
                str(raw["user_stream_error_type"])
                if isinstance(raw.get("user_stream_error_type"), str)
                else None
            ),
            user_stream_last_event_type=(
                str(raw["user_stream_last_event_type"])
                if isinstance(raw.get("user_stream_last_event_type"), str)
                else None
            ),
            user_stream_event_count=_safe_int(raw.get("user_stream_event_count"), 0),
            user_stream_gap=bool(raw.get("user_stream_gap")),
            force_flatten_reason=(
                str(raw["force_flatten_reason"])
                if isinstance(raw.get("force_flatten_reason"), str)
                else None
            ),
            market_generation=_safe_int(raw.get("market_generation"), 0),
            calibration_window_ms=(
                int(micro["calibration_window_ms"])
                if isinstance(micro.get("calibration_window_ms"), int)
                else None
            ),
            beta_per_second=beta_per_second,
            arrival_count=_safe_int(micro.get("arrival_count"), 0),
            fit_error=fit_error,
            spectral_radius=spectral_radius,
            baseline_boundary_symbols=baseline_boundary_symbols,
            event_counts=event_counts,
        )
        return runtime_health, engine_state, interlock_blocks
    except OSError, ValueError, KeyError, TypeError:
        return ExecutionRuntimeHealth(), "UNKNOWN", 0


_PORTFOLIO_VARIANTS_SPEC: tuple[tuple[str, str, str, float, float, float], ...] = (
    ("avax-1-deep", "AVAXUSDT", "DEEP", -2.2, 2.0, 28.0),
    ("avax-2-hf", "AVAXUSDT", "HF", -0.8, 1.2, 42.0),
    ("eth-1-deep", "ETHUSDT", "DEEP", -2.2, 2.0, 28.0),
    ("eth-2-hf", "ETHUSDT", "HF", -0.8, 1.2, 42.0),
    ("sol-1-deep", "SOLUSDT", "DEEP", -2.2, 2.0, 28.0),
    ("sol-2-hf", "SOLUSDT", "HF", -0.8, 1.2, 42.0),
)


def _load_ohlcv_bars_for_scanner(
    symbol: str,
    interval: str,
    limit: int,
    research_dir: Path | None = None,
) -> tuple[list[Any], str]:
    import urllib.request

    from autonomous_futures.strategy.macro_liquidity_scalper import Candle

    now_ms = int(time.time() * 1000)
    is_unmocked_pytest = (
        "PYTEST_CURRENT_TEST" in os.environ
        and getattr(urllib.request.urlopen, "__module__", "") == "urllib.request"
    )
    if not is_unmocked_pytest:
        try:
            url = (
                f"https://fapi.binance.com/fapi/v1/klines?"
                f"symbol={symbol}&interval={interval}&limit={limit}"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "AutonomousFuturesBot/1.0 (PublicRestClient; Unauth)"},
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                if isinstance(raw, list) and len(raw) >= 20:
                    rows = (
                        raw[:-1]
                        if len(raw) > 20
                        and isinstance(raw[-1], list)
                        and len(raw[-1]) > 6
                        and int(raw[-1][6]) > now_ms
                        else raw
                    )
                    bars = [
                        Candle(
                            timestamp_ms=int(item[0]),
                            open=Decimal(str(item[1])),
                            high=Decimal(str(item[2])),
                            low=Decimal(str(item[3])),
                            close=Decimal(str(item[4])),
                            volume=Decimal(str(item[5])),
                        )
                        for item in rows
                    ]
                    return bars, "binance_futures_live"
        except Exception:
            pass

    repo_root = Path(__file__).resolve().parents[3]
    source_interval = "1h" if interval == "4h" else interval
    source_limit = limit * 4 if interval == "4h" else limit
    candidates = [
        Path("research/immutable-data")
        / source_interval
        / "canonical"
        / f"{symbol}-{source_interval}.parquet",
        Path("research/immutable-data/runtime-official-20261013")
        / source_interval
        / "canonical"
        / f"{symbol}-{source_interval}.parquet",
        repo_root
        / "research"
        / "immutable-data"
        / source_interval
        / "canonical"
        / f"{symbol}-{source_interval}.parquet",
        repo_root
        / "research"
        / "immutable-data"
        / "runtime-official-20261013"
        / source_interval
        / "canonical"
        / f"{symbol}-{source_interval}.parquet",
    ]
    if research_dir is not None:
        candidates.append(
            research_dir.parent.parent
            / "research"
            / "immutable-data"
            / source_interval
            / "canonical"
            / f"{symbol}-{source_interval}.parquet"
        )
    for ppath in candidates:
        if ppath.is_file():
            try:
                import pandas as pd

                df = pd.read_parquet(
                    ppath, columns=["open", "high", "low", "close", "volume"]
                ).tail(source_limit)
                if len(df) >= 20:
                    raw_bars = [
                        Candle(
                            timestamp_ms=idx * 60_000,
                            open=Decimal(str(float(r["open"]))),
                            high=Decimal(str(float(r["high"]))),
                            low=Decimal(str(float(r["low"]))),
                            close=Decimal(str(float(r["close"]))),
                            volume=Decimal(str(float(r["volume"]))),
                        )
                        for idx, (_, r) in enumerate(df.iterrows())
                    ]
                    if interval == "4h":
                        agg_bars: list[Any] = []
                        for i in range(0, len(raw_bars) - 3, 4):
                            chunk = raw_bars[i : i + 4]
                            agg_bars.append(
                                Candle(
                                    timestamp_ms=chunk[-1].timestamp_ms,
                                    open=chunk[0].open,
                                    high=max(c.high for c in chunk),
                                    low=min(c.low for c in chunk),
                                    close=chunk[-1].close,
                                    volume=sum((c.volume for c in chunk), Decimal("0")),
                                )
                            )
                        if len(agg_bars) >= 20:
                            return agg_bars, "local_parquet_cache"
                    else:
                        return raw_bars, "local_parquet_cache"
            except Exception:
                pass
    return [], "unavailable"


def _compute_portfolio_scanner_telemetry(
    research_dir: Path | None,
    runtime_observed: bool,
) -> tuple[ExecutionScalperCriteria | None, ExecutionPortfolioScanner]:
    if not runtime_observed:
        return None, ExecutionPortfolioScanner()

    now_sec = time.time()
    cached = _GLOBAL_PORTFOLIO_SCANNER_CACHE.get("data")
    if cached is not None and (now_sec - float(_GLOBAL_PORTFOLIO_SCANNER_CACHE["ts"])) < 15.0:
        return cast(tuple[ExecutionScalperCriteria | None, ExecutionPortfolioScanner], cached)

    from concurrent.futures import ThreadPoolExecutor

    from autonomous_futures.strategy.macro_liquidity_scalper import (
        compute_atr,
        compute_ema,
        compute_rsi,
        compute_sma,
    )

    tasks = (
        ("BTCUSDT", "1h", 220),
        ("BTCUSDT", "4h", 220),
        ("AVAXUSDT", "15m", 60),
        ("ETHUSDT", "15m", 60),
        ("SOLUSDT", "15m", 60),
    )
    results: dict[tuple[str, str], tuple[list[Any], str]] = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            (sym, iv): executor.submit(_load_ohlcv_bars_for_scanner, sym, iv, lim, research_dir)
            for sym, iv, lim in tasks
        }
        for key, fut in futures.items():
            try:
                results[key] = fut.result()
            except Exception:
                results[key] = ([], "unavailable")

    btc_1h, src_1h = results.get(("BTCUSDT", "1h"), ([], "unavailable"))
    btc_4h, _ = results.get(("BTCUSDT", "4h"), ([], "unavailable"))

    ema50_1h: float | None = None
    ema200_1h: float | None = None
    ema50_4h: float | None = None
    ema200_4h: float | None = None
    btc_regime = "UNKNOWN"
    macro_aligned = False

    if len(btc_1h) >= 50:
        closes_1h = [c.close for c in btc_1h]
        e50_1h = float(compute_ema(closes_1h, 50)[-1])
        e200_1h = float(compute_ema(closes_1h, min(200, len(closes_1h)))[-1])
        ema50_1h = round(e50_1h, 2)
        ema200_1h = round(e200_1h, 2)
        close_1h = float(closes_1h[-1])
        if len(btc_4h) >= 50:
            closes_4h = [c.close for c in btc_4h]
            e50_4h = float(compute_ema(closes_4h, 50)[-1])
            e200_4h = float(compute_ema(closes_4h, min(200, len(closes_4h)))[-1])
            ema50_4h = round(e50_4h, 2)
            ema200_4h = round(e200_4h, 2)
            close_4h = float(closes_4h[-1])
            bull_1h = close_1h > e50_1h and e50_1h > e200_1h
            bull_4h = close_4h > e50_4h and e50_4h > e200_4h
            bear_1h = close_1h < e50_1h and e50_1h < e200_1h
            bear_4h = close_4h < e50_4h and e50_4h < e200_4h
            if bull_1h and bull_4h:
                btc_regime = "BULLISH ALIGNED"
                macro_aligned = True
            elif bear_1h and bear_4h:
                btc_regime = "BEARISH"
                macro_aligned = True
            else:
                btc_regime = "SIDEWAYS"
                macro_aligned = False
        else:
            if close_1h > e50_1h and e50_1h > e200_1h:
                btc_regime = "BULLISH ALIGNED"
                macro_aligned = True
            elif close_1h < e50_1h and e50_1h < e200_1h:
                btc_regime = "BEARISH"
                macro_aligned = True
            else:
                btc_regime = "SIDEWAYS"
                macro_aligned = False

    symbol_metrics: dict[str, dict[str, float]] = {}
    scanner_source = src_1h
    for sym in ("AVAXUSDT", "ETHUSDT", "SOLUSDT"):
        bars_15m, sym_src = results.get((sym, "15m"), ([], "unavailable"))
        if scanner_source == "unavailable" and sym_src != "unavailable":
            scanner_source = sym_src
        if len(bars_15m) < 25:
            continue
        closes = [b.close for b in bars_15m]
        volumes = [b.volume for b in bars_15m]
        ema20 = float(compute_ema(closes, 20)[-1])
        atr14 = float(compute_atr(bars_15m, 14)[-1])
        vol_sma20 = float(compute_sma(volumes, 20)[-1])
        rsi14 = float(compute_rsi(closes, 14)[-1])
        last_close = float(bars_15m[-1].close)
        last_vol = float(bars_15m[-1].volume)
        dist_atr = (last_close - ema20) / atr14 if atr14 > 0 else 0.0
        rel_vol = last_vol / vol_sma20 if vol_sma20 > 0 else 0.0
        symbol_metrics[sym] = {
            "close": round(last_close, 4),
            "ema20": round(ema20, 4),
            "atr14": round(atr14, 4),
            "dist_atr": round(dist_atr, 3),
            "price_below_ema20_atr": round(max(0.0, -dist_atr), 2),
            "relative_volume": round(rel_vol, 2),
            "rsi_14": round(rsi14, 1),
        }

    variants: list[PortfolioVariantChecklistItem] = []
    for member_id, sym, tier, dist_thresh, vol_mult, rsi_thresh in _PORTFOLIO_VARIANTS_SPEC:
        m = symbol_metrics.get(sym)
        if m is None:
            continue
        abs_thresh = abs(dist_thresh)
        dist_val = m["dist_atr"]
        rel_vol_val = m["relative_volume"]
        rsi_val = m["rsi_14"]
        dist_triggered = (
            (dist_val > abs_thresh) if btc_regime == "BEARISH" else (dist_val < -abs_thresh)
        )
        vol_triggered = rel_vol_val > vol_mult
        rsi_triggered = (
            (rsi_val > (100.0 - rsi_thresh)) if btc_regime == "BEARISH" else (rsi_val < rsi_thresh)
        )
        gates_passed = (
            int(macro_aligned) + int(dist_triggered) + int(vol_triggered) + int(rsi_triggered)
        )
        variants.append(
            PortfolioVariantChecklistItem(
                member_id=member_id,
                symbol=sym,
                tier=tier,
                close_price=m["close"],
                ema20=m["ema20"],
                atr14=m["atr14"],
                dist_atr=dist_val,
                price_below_ema20_atr=m["price_below_ema20_atr"],
                distance_threshold=dist_thresh,
                dist_triggered=dist_triggered,
                relative_volume=rel_vol_val,
                vol_spike_multiplier=vol_mult,
                vol_triggered=vol_triggered,
                rsi_14=rsi_val,
                rsi_threshold=rsi_thresh,
                rsi_triggered=rsi_triggered,
                macro_regime=btc_regime,
                macro_aligned=macro_aligned,
                gates_passed=gates_passed,
                gates_total=4,
                signal_ready=bool(
                    macro_aligned and dist_triggered and vol_triggered and rsi_triggered
                ),
            )
        )

    if not variants:
        return None, ExecutionPortfolioScanner()

    best = max(
        variants,
        key=lambda v: (
            v.gates_passed,
            (v.price_below_ema20_atr / abs(v.distance_threshold)) if v.distance_threshold else 0.0,
            1 if v.member_id == "sol-2-hf" else 0,
        ),
    )
    scalper_criteria = ExecutionScalperCriteria(
        symbol=best.symbol,
        variant_id=best.member_id,
        price_below_ema20_atr=best.price_below_ema20_atr,
        price_below_ema_threshold=round(abs(best.distance_threshold), 2),
        price_triggered=best.dist_triggered,
        relative_volume=best.relative_volume,
        volume_threshold=round(best.vol_spike_multiplier, 2),
        volume_triggered=best.vol_triggered,
        rsi_14=best.rsi_14,
        rsi_threshold=round(best.rsi_threshold, 1),
        rsi_triggered=best.rsi_triggered,
        maker_fee_pct=0.02,
    )
    scanner = ExecutionPortfolioScanner(
        observed=True,
        portfolio_id="macro-scalper-uninspected-3sym-medium-frequency-v1",
        evaluated_at_ms=int(now_sec * 1000),
        source=scanner_source,
        btc_regime=btc_regime,
        ema50_1h=ema50_1h,
        ema200_1h=ema200_1h,
        ema50_4h=ema50_4h,
        ema200_4h=ema200_4h,
        variants=variants,
    )
    out = (scalper_criteria, scanner)
    _GLOBAL_PORTFOLIO_SCANNER_CACHE["ts"] = now_sec
    _GLOBAL_PORTFOLIO_SCANNER_CACHE["data"] = out
    return out


def load_execution_status(research_dir: Path | None = None) -> ExecutionStatusResponse:
    """Account observations never imply reconciled execution or a verified ledger."""
    from autonomous_futures.execution.account_evidence import (
        SNAPSHOT_NAME,
        finite_decimal,
        read_account,
    )

    base = research_dir or _resolve_research_dir()
    path = base / SNAPSHOT_NAME
    if not path.is_file():
        candidates = [
            base / "qualified-testnet" / SNAPSHOT_NAME,
            base.parent / "runtime" / "qualified-testnet" / SNAPSHOT_NAME,
            base.parent.parent / "runtime" / "qualified-testnet" / SNAPSHOT_NAME,
            base / "phase310" / SNAPSHOT_NAME,
        ]
        existing = [p for p in candidates if p.is_file()]
        path = (
            max(existing, key=lambda p: p.stat().st_mtime_ns)
            if existing
            else base / "phase310" / SNAPSHOT_NAME
        )
    try:
        data = read_account(path)
        account = data["account"]
        wallet = finite_decimal(account["totalWalletBalance"])
        margin = finite_decimal(account["totalInitialMargin"])
        equity = finite_decimal(account["totalMarginBalance"])
        available = finite_decimal(account["availableBalance"])
        upnl = finite_decimal(account["totalUnrealizedProfit"])
        reserve = available / equity * 100 if equity > 0 else Decimal("0")
        # Include every observed exchange symbol, not just dashboard candidates.
        positions = {}
        aggregate = Decimal("0")
        for item in data["positions"]:
            symbol = str(item["symbol"])
            qty = finite_decimal(item["positionAmt"])
            mark = finite_decimal(item["markPrice"])
            exposure = abs(qty * mark)
            aggregate += exposure
            key = (
                symbol
                if item.get("positionSide", "BOTH") == "BOTH"
                else (symbol + ":" + str(item["positionSide"]))
            )
            positions[key] = ExecutionPositionItem(
                symbol=symbol,
                position_qty=float(qty),
                allocated_exposure_usdt=float(exposure),
                entry_price=float(finite_decimal(item["entryPrice"])) if qty else None,
                mark_price=float(mark),
                unrealized_pnl_usdt=float(finite_decimal(item["unRealizedProfit"])),
                state="OPEN" if qty else "FLAT",
                status="OPEN" if qty else "FLAT",
            )
        orders = []
        for item in data["open_orders"]:
            qty = finite_decimal(item["origQty"])
            price = finite_decimal(item["price"])
            executed = finite_decimal(item.get("executedQty", "0"))
            avg = finite_decimal(item.get("avgPrice", "0"))
            orders.append(
                ExecutionOrderItem(
                    order_id=str(item["orderId"]),
                    client_order_id=str(item["clientOrderId"]),
                    symbol=str(item["symbol"]),
                    side=str(item["side"]),
                    order_type=str(item["type"]),
                    price=float(price),
                    quantity=float(qty),
                    notional_usdt=float(price * qty),
                    status=str(item["status"]),
                    fill_price=float(avg) if executed > 0 and avg > 0 else None,
                    timestamp_ms=int(item.get("time", data["timestamp_ms"])),
                    is_maker=item.get("timeInForce") == "GTX",
                )
            )
        reconciliation = data.get("reconciliation", {})
        daily_risk_data = data.get("daily_risk", {})
        if not isinstance(daily_risk_data, dict):
            daily_risk_data = {}
        daily_risk_verified = (
            daily_risk_data.get("verified") is True
            and daily_risk_data.get("observed_ms") == data["timestamp_ms"]
            and daily_risk_data.get("equity_basis") == "ACCOUNT"
        )
        daily_risk = ExecutionDailyRisk(
            verified=daily_risk_verified,
            day_start_equity_usdt=(
                float(finite_decimal(daily_risk_data["day_start_equity"]))
                if daily_risk_verified
                else None
            ),
            limit_pct=(
                float(finite_decimal(daily_risk_data["limit_pct"])) if daily_risk_verified else None
            ),
            limit_usdt=(
                float(finite_decimal(daily_risk_data["limit_usdt"]))
                if daily_risk_verified
                else None
            ),
            loss_usdt=(
                float(finite_decimal(daily_risk_data["loss_usdt"])) if daily_risk_verified else None
            ),
            remaining_usdt=(
                float(finite_decimal(daily_risk_data["remaining_usdt"]))
                if daily_risk_verified
                else None
            ),
            breached=(daily_risk_data.get("breached") if daily_risk_verified else None),
            equity_basis=(daily_risk_data.get("equity_basis") if daily_risk_verified else None),
        )
        verified = reconciliation.get("verified") is True
        drift = (
            max(
                abs(finite_decimal(reconciliation["wallet_drift"])),
                abs(finite_decimal(reconciliation["equity_drift"])),
            )
            if reconciliation
            else None
        )
        runtime_health, engine_state, interlock_blocks = _load_runtime_health(path)
        scalper_criteria, portfolio_scanner = _compute_portfolio_scanner_telemetry(
            base, runtime_health.observed
        )
        return ExecutionStatusResponse(
            verified=verified,
            status="ACCOUNT_RECONCILED" if verified else "ACCOUNT_UNRECONCILED",
            engine_state=engine_state,
            timestamp_ms=data["timestamp_ms"],
            solvency=ExecutionSolvency(
                cash_usdt=float(wallet),
                cash=float(wallet),
                available_balance_usdt=float(available),
                allocated_margin_usdt=float(margin),
                allocated_margin=float(margin),
                unrealized_pnl_usdt=float(upnl),
                unrealized_pnl=float(upnl),
                total_equity_usdt=float(equity),
                total_equity=float(equity),
                cash_reserve_pct=float(reserve),
                unencumbered_cash_verified=True,
                starting_equity_usdt=float(finite_decimal(reconciliation["starting_equity"]))
                if reconciliation
                else None,
                starting_equity=float(finite_decimal(reconciliation["starting_equity"]))
                if reconciliation
                else None,
                realized_pnl_usdt=float(finite_decimal(reconciliation["net_realized_pnl"]))
                if reconciliation
                else None,
                realized_pnl=float(finite_decimal(reconciliation["net_realized_pnl"]))
                if reconciliation
                else None,
                drift_usdt=float(drift) if drift is not None else None,
                drift=float(drift) if drift is not None else None,
                zero_balance_drift_verified=verified,
                zero_balance_drift=verified,
            ),
            positions=positions,
            candidate_allocations=list(positions.values()),
            aggregate_exposure_usdt=float(aggregate),
            recent_orders=orders,
            total_orders=len(orders),
            interlock_blocks_count=interlock_blocks,
            intra_day_loss_usdt=daily_risk.loss_usdt,
            daily_risk=daily_risk,
            runtime_health=runtime_health,
            scalper_criteria=scalper_criteria,
            portfolio_scanner=portfolio_scanner,
        )
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        raise HTTPException(
            status_code=503, detail="Fresh exchange account evidence unavailable"
        ) from exc


def _configured_path(environment_name: str, default: str) -> Path:
    return Path(os.environ.get(environment_name, default))


def create_app(
    *,
    bundle_path: Path | None = None,
    registry_path: Path | None = None,
    artifact_root: Path | None = None,
    creator_candidate_registry_path: Path | None = None,
    creator_candidate_artifact_root: Path | None = None,
    qualification_artifact_root: Path | None = None,
    creator_epoch_journal: Path | None = None,
    creator_epoch_control: Path | None = None,
    creator_epoch_checkpoint: Path | None = None,
    learner_artifact_path: Path | None = None,
    learner_model_root: Path | None = None,
    learner_run_path: Path | None = None,
    learner_training_evidence_path: Path | None = None,
    learner_training_artifact_root: Path | None = None,
    learner_quality_review_evidence_path: Path | None = None,
    learner_qualification_evidence_path: Path | None = None,
    learner_qualification_policy_path: Path | None = None,
    learner_metric_evaluation_path: Path | None = None,
    learner_metric_quality_review_evidence_path: Path | None = None,
    learner_metric_quality_decision_path: Path | None = None,
    learner_metric_quality_policy_path: Path | None = None,
    learner_metric_quality_qualification_evidence_path: Path | None = None,
    learner_metric_quality_qualification_policy_path: Path | None = None,
    canary_phase_dir: Path | None = None,
    research_dir: Path | None = None,
    telemetry_broadcaster: TelemetryBroadcastManager | None = None,
    frontend_dist_path: Path | None = None,
    trader: Any | None = None,
) -> FastAPI:
    if (
        creator_epoch_journal is None
        and (value := os.environ.get("AFBOT_CREATOR_EPOCH_JOURNAL")) is not None
    ):
        creator_epoch_journal = Path(value)
    if (
        creator_epoch_control is None
        and (value := os.environ.get("AFBOT_CREATOR_EPOCH_CONTROL")) is not None
    ):
        creator_epoch_control = Path(value)
    if (
        creator_epoch_checkpoint is None
        and (value := os.environ.get("AFBOT_CREATOR_EPOCH_CHECKPOINT")) is not None
    ):
        creator_epoch_checkpoint = Path(value)
    epoch_checkpoint = read_creator_epoch_configuration(
        creator_epoch_journal, creator_epoch_control, creator_epoch_checkpoint
    )
    creator_admission_decider = StrategyAdmissionDecider(
        epoch_path=creator_epoch_journal,
        epoch_checkpoint=epoch_checkpoint,
        epoch_control=creator_epoch_control,
    )
    configured_bundle_path = bundle_path or _configured_path(
        "AFBOT_DATASET_BUNDLE_PATH", "data/dataset-bundle.json"
    )
    configured_registry_path = registry_path or _configured_path(
        "AFBOT_DATASET_REGISTRY_PATH", "data/dataset-registry.json"
    )
    configured_artifact_root = artifact_root or _configured_path(
        "AFBOT_DATASET_ARTIFACT_ROOT", "data"
    )
    configured_creator_registry_path = creator_candidate_registry_path or _configured_path(
        "AFBOT_CREATOR_CANDIDATE_REGISTRY_PATH", "data/creator-candidate-registry.json"
    )
    configured_creator_artifact_root = creator_candidate_artifact_root or _configured_path(
        "AFBOT_CREATOR_CANDIDATE_ARTIFACT_ROOT", "data"
    )
    configured_qualification_artifact_root = qualification_artifact_root or _configured_path(
        "AFBOT_QUALIFICATION_ARTIFACT_ROOT", "data/qualifications"
    )
    configured_learner_artifact_path = learner_artifact_path or _configured_path(
        "AFBOT_LEARNER_ARTIFACT_PATH", "data/learner-artifact.json"
    )
    configured_learner_model_root = learner_model_root or _configured_path(
        "AFBOT_LEARNER_MODEL_ROOT", "data/models"
    )
    configured_learner_run_path = learner_run_path or _configured_path(
        "AFBOT_LEARNER_RUN_PATH", "data/learner-run.json"
    )
    configured_learner_training_evidence_path = learner_training_evidence_path or _configured_path(
        "AFBOT_LEARNER_TRAINING_EVIDENCE_PATH", "data/learner-training-evidence.json"
    )
    configured_learner_training_artifact_root = learner_training_artifact_root or _configured_path(
        "AFBOT_LEARNER_TRAINING_ARTIFACT_ROOT", "data"
    )
    configured_learner_quality_review_evidence_path = (
        learner_quality_review_evidence_path
        or _configured_path(
            "AFBOT_LEARNER_QUALITY_REVIEW_EVIDENCE_PATH",
            "data/learner-quality-review-evidence.json",
        )
    )
    configured_learner_qualification_evidence_path = (
        learner_qualification_evidence_path
        or _configured_path(
            "AFBOT_LEARNER_QUALIFICATION_EVIDENCE_PATH",
            "data/learner-qualification-evidence.json",
        )
    )
    configured_learner_qualification_policy_path = (
        learner_qualification_policy_path
        or _configured_path(
            "AFBOT_LEARNER_QUALIFICATION_POLICY_PATH",
            "data/learner-qualification-policy.json",
        )
    )
    configured_learner_metric_evaluation_path = learner_metric_evaluation_path or _configured_path(
        "AFBOT_LEARNER_METRIC_EVALUATION_PATH", "data/learner-metric-evaluation.json"
    )
    configured_learner_metric_quality_review_evidence_path = (
        learner_metric_quality_review_evidence_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_REVIEW_EVIDENCE_PATH",
            "data/learner-metric-quality-review-evidence.json",
        )
    )
    configured_learner_metric_quality_decision_path = (
        learner_metric_quality_decision_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_DECISION_PATH",
            "data/learner-metric-quality-decision.json",
        )
    )
    configured_learner_metric_quality_policy_path = (
        learner_metric_quality_policy_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_POLICY_PATH",
            "data/learner-metric-quality-policy.json",
        )
    )
    configured_learner_metric_quality_qualification_evidence_path = (
        learner_metric_quality_qualification_evidence_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_QUALIFICATION_EVIDENCE_PATH",
            "data/learner-metric-quality-qualification-evidence.json",
        )
    )
    configured_learner_metric_quality_qualification_policy_path = (
        learner_metric_quality_qualification_policy_path
        or _configured_path(
            "AFBOT_LEARNER_METRIC_QUALITY_QUALIFICATION_POLICY_PATH",
            "data/learner-metric-quality-qualification-policy.json",
        )
    )
    configured_canary_phase_dir = canary_phase_dir or _configured_path(
        "AFBOT_CANARY_PHASE_DIR", "artifacts/research/phase291"
    )
    configured_research_dir = research_dir or _resolve_research_dir()

    app = FastAPI(
        title="Autonomous Futures Data API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    def verified_catalog() -> VerifiedDatasetCatalog:
        try:
            return load_verified_dataset_catalog(
                bundle_path=configured_bundle_path,
                registry_path=configured_registry_path,
            )
        except DatasetCatalogIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="dataset catalog integrity verification failed",
            ) from exc

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    def verified_learner_artifact() -> VerifiedLearnerEvidence:
        try:
            return load_verified_learner_artifact(
                artifact_path=configured_learner_artifact_path,
                model_root=configured_learner_model_root,
                bundle_path=configured_bundle_path,
                registry_path=configured_registry_path,
                candidate_registry_path=configured_creator_registry_path,
                candidate_artifact_root=configured_creator_artifact_root,
            )
        except LearnerArtifactNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner artifact unavailable",
            ) from exc
        except LearnerEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner artifact integrity verification failed",
            ) from exc

    @app.get("/api/v1/learner/artifact", response_model=LearnerArtifactResponse)
    def learner_artifact() -> LearnerArtifactResponse:
        verified = verified_learner_artifact()
        return LearnerArtifactResponse(artifact=verified.artifact)

    @app.get("/api/v1/learner/run", response_model=LearnerRunResponse)
    def learner_run() -> LearnerRunResponse:
        if not configured_learner_run_path.exists():
            raise HTTPException(status_code=404, detail="learner run unavailable")
        verified_artifact = verified_learner_artifact()
        try:
            run = load_verified_learner_run(
                run_path=configured_learner_run_path,
                learner_evidence=verified_artifact,
            )
        except LearnerRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="learner run unavailable") from exc
        except LearnerEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner run integrity verification failed",
            ) from exc
        return LearnerRunResponse(run=run)

    @app.get(
        "/api/v1/learner/training-evidence",
        response_model=LearnerTrainingEvidenceResponse,
    )
    def learner_training_evidence() -> LearnerTrainingEvidenceResponse:
        if not configured_learner_training_evidence_path.exists():
            raise HTTPException(
                status_code=404,
                detail="learner training evidence unavailable",
            )
        try:
            verified_artifact = verified_learner_artifact()
            evidence = load_verified_learner_training_evidence(
                evidence_path=configured_learner_training_evidence_path,
                run_root=configured_learner_run_path.parent,
                artifact_root=configured_learner_training_artifact_root,
                model_root=configured_learner_model_root,
                candidate=verified_artifact.candidate,
            )
        except LearnerTrainingEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner training evidence unavailable",
            ) from exc
        except LearnerTrainingEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner training evidence integrity verification failed",
            ) from exc
        except HTTPException as exc:
            raise HTTPException(
                status_code=404 if exc.status_code == 404 else 503,
                detail=(
                    "learner training evidence unavailable"
                    if exc.status_code == 404
                    else "learner training evidence integrity verification failed"
                ),
            ) from exc
        return LearnerTrainingEvidenceResponse(evidence=evidence)

    @app.get(
        "/api/v1/learner/quality-review",
        response_model=LearnerQualityReviewEvidenceResponse,
    )
    def learner_quality_review() -> LearnerQualityReviewEvidenceResponse:
        if not configured_learner_quality_review_evidence_path.exists():
            raise HTTPException(
                status_code=404,
                detail="learner quality review unavailable",
            )
        try:
            verified_artifact = verified_learner_artifact()
            evidence = load_verified_learner_quality_review_evidence(
                evidence_path=configured_learner_quality_review_evidence_path,
                training_evidence_path=configured_learner_training_evidence_path,
                run_root=configured_learner_run_path.parent,
                artifact_root=configured_learner_training_artifact_root,
                model_root=configured_learner_model_root,
                candidate=verified_artifact.candidate,
            )
        except LearnerQualityReviewEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner quality review unavailable",
            ) from exc
        except LearnerQualityReviewEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner quality review integrity verification failed",
            ) from exc
        except HTTPException as exc:
            raise HTTPException(
                status_code=404 if exc.status_code == 404 else 503,
                detail=(
                    "learner quality review unavailable"
                    if exc.status_code == 404
                    else "learner quality review integrity verification failed"
                ),
            ) from exc
        return LearnerQualityReviewEvidenceResponse(evidence=evidence)

    @app.get(
        "/api/v1/learner/qualification",
        response_model=LearnerQualificationEvidenceResponse,
    )
    def learner_qualification() -> LearnerQualificationEvidenceResponse:
        if not configured_learner_qualification_evidence_path.exists():
            raise HTTPException(
                status_code=404,
                detail="learner qualification unavailable",
            )
        try:
            verified_artifact = verified_learner_artifact()
            evidence = load_verified_learner_qualification_evidence(
                evidence_path=configured_learner_qualification_evidence_path,
                policy_path=configured_learner_qualification_policy_path,
                quality_review_path=configured_learner_quality_review_evidence_path,
                training_evidence_path=configured_learner_training_evidence_path,
                run_root=configured_learner_run_path.parent,
                artifact_root=configured_learner_training_artifact_root,
                model_root=configured_learner_model_root,
                candidate=verified_artifact.candidate,
            )
        except LearnerQualificationEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner qualification unavailable",
            ) from exc
        except LearnerQualificationEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="learner qualification integrity verification failed",
            ) from exc
        except HTTPException as exc:
            raise HTTPException(
                status_code=404 if exc.status_code == 404 else 503,
                detail=(
                    "learner qualification unavailable"
                    if exc.status_code == 404
                    else "learner qualification integrity verification failed"
                ),
            ) from exc
        return LearnerQualificationEvidenceResponse(evidence=evidence)

    @app.get(
        "/api/v1/learner/metric-quality-qualification",
        response_model=LearnerMetricQualityQualificationEvidenceResponse,
    )
    def learner_metric_quality_qualification() -> LearnerMetricQualityQualificationEvidenceResponse:
        if not configured_learner_metric_quality_qualification_evidence_path.exists():
            raise HTTPException(
                status_code=404,
                detail="learner metric-quality qualification evidence unavailable",
            )
        try:
            verified_artifact = verified_learner_artifact()
            evidence = load_verified_metric_quality_qualification_evidence(
                qualification_evidence_path=(
                    configured_learner_metric_quality_qualification_evidence_path
                ),
                decision_path=configured_learner_metric_quality_decision_path,
                review_path=configured_learner_metric_quality_review_evidence_path,
                metric_evaluation_path=configured_learner_metric_evaluation_path,
                source_policy_path=configured_learner_metric_quality_policy_path,
                qualification_policy_path=(
                    configured_learner_metric_quality_qualification_policy_path
                ),
                learner=verified_artifact.artifact,
                candidate=verified_artifact.candidate,
            )
        except LearnerMetricQualityQualificationEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="learner metric-quality qualification evidence unavailable",
            ) from exc
        except LearnerMetricQualityQualificationEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "learner metric-quality qualification evidence integrity verification failed"
                ),
            ) from exc
        except HTTPException as exc:
            raise HTTPException(
                status_code=404 if exc.status_code == 404 else 503,
                detail=(
                    "learner metric-quality qualification evidence unavailable"
                    if exc.status_code == 404
                    else (
                        "learner metric-quality qualification evidence integrity "
                        "verification failed"
                    )
                ),
            ) from exc
        return LearnerMetricQualityQualificationEvidenceResponse(evidence=evidence)

    @app.get("/api/v1/dataset/bundle", response_model=BundleResponse)
    def dataset_bundle() -> BundleResponse:
        catalog = verified_catalog()
        return BundleResponse(
            registry_hash=catalog.registry.registry_hash,
            bundle_hash=catalog.bundle.bundle_hash,
            component_count=len(catalog.bundle.components),
            bundle=catalog.bundle,
        )

    @app.get("/api/v1/dataset/registry", response_model=RegistryResponse)
    def dataset_registry() -> RegistryResponse:
        catalog = verified_catalog()
        return RegistryResponse(registry=catalog.registry)

    @app.get("/api/v1/creator/registry", response_model=CreatorRegistryResponse)
    def creator_registry() -> CreatorRegistryResponse:
        try:
            verified = load_verified_creator_candidate_registry(
                registry_path=configured_creator_registry_path,
                artifact_root=configured_creator_artifact_root,
                admission_decider=creator_admission_decider,
            )
        except CreatorCandidateRegistryNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="creator candidate registry unavailable",
            ) from exc
        except CreatorCandidateRegistryIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator candidate registry integrity verification failed",
            ) from exc
        return CreatorRegistryResponse(
            registry_hash=verified.registry.registry_hash,
            candidate_count=len(verified.registry.entries),
            registry=verified.registry,
        )

    @app.get(
        "/api/v1/creator/qualifications",
        response_model=CreatorQualificationsResponse,
    )
    def creator_qualifications() -> CreatorQualificationsResponse:
        try:
            verified = load_verified_creator_candidate_qualifications(
                registry_path=configured_creator_registry_path,
                candidate_artifact_root=configured_creator_artifact_root,
                qualification_root=configured_qualification_artifact_root,
                admission_decider=creator_admission_decider,
            )
        except CreatorCandidateRegistryNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="creator candidate registry unavailable",
            ) from exc
        except CreatorCandidateRegistryIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator candidate registry integrity verification failed",
            ) from exc
        except CreatorQualificationArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator qualification artifact integrity verification failed",
            ) from exc
        summaries = tuple(
            CreatorQualificationSummary(
                candidate_id=item.qualification.candidate_id,
                decision=item.qualification.decision,
                source=item.qualification.source,
                qualification_hash=item.qualification.qualification_hash,
                evaluator_run_id=item.qualification.evaluator_run_id,
                evaluator_version=item.qualification.evaluator_version,
                windows_evaluated=item.qualification.windows_evaluated,
                qualification_policy_id=item.qualification.qualification_policy_id,
                evaluated_at=item.qualification.evaluated_at,
                promotion_state=item.qualification.promotion_state,
                execution_authority=item.qualification.execution_authority,
            )
            for item in verified.qualifications
        )
        return CreatorQualificationsResponse(
            candidate_count=len(verified.registry.entries),
            qualification_count=len(summaries),
            missing_candidate_ids=verified.missing_candidate_ids,
            qualifications=summaries,
        )

    @app.get(
        "/api/v1/creator/qualifications/{candidate_id}",
        response_model=CreatorQualificationResponse,
    )
    def creator_qualification(candidate_id: str) -> CreatorQualificationResponse:
        try:
            verified = load_verified_creator_candidate_qualification(
                registry_path=configured_creator_registry_path,
                candidate_artifact_root=configured_creator_artifact_root,
                qualification_root=configured_qualification_artifact_root,
                candidate_id=candidate_id,
                admission_decider=creator_admission_decider,
            )
        except CreatorCandidateRegistryNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="creator candidate registry unavailable",
            ) from exc
        except CreatorCandidateRegistryIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator candidate registry integrity verification failed",
            ) from exc
        except CreatorQualificationArtifactNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="creator qualification artifact unavailable",
            ) from exc
        except CreatorQualificationArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="creator qualification artifact integrity verification failed",
            ) from exc
        return CreatorQualificationResponse(artifact=verified.qualification)

    @app.get("/api/v1/dataset/components", response_model=ComponentsResponse)
    def dataset_components() -> ComponentsResponse:
        catalog = verified_catalog()
        try:
            components = inspect_dataset_artifacts(configured_artifact_root, catalog)
        except ArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="dataset artifact integrity verification failed",
            ) from exc
        return ComponentsResponse(component_count=len(components), components=components)

    @app.get("/api/v1/dataset/rows", response_model=RowsResponse)
    def dataset_rows(
        *,
        kind: Literal["kline", "funding_rate", "mark_price"],
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_QUERY_ROWS)] = 100,
    ) -> RowsResponse:
        if not symbol or symbol != symbol.upper():
            raise HTTPException(status_code=422, detail="symbol must be uppercase")
        if kind == "funding_rate" and interval is not None:
            raise HTTPException(status_code=422, detail="funding_rate interval must be null")
        if kind != "funding_rate" and interval not in {"5m", "15m"}:
            raise HTTPException(status_code=422, detail="kline and mark_price require interval")

        catalog = verified_catalog()
        try:
            components = inspect_dataset_artifacts(configured_artifact_root, catalog)
        except ArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="dataset artifact integrity verification failed",
            ) from exc

        selected: tuple[DatasetRegistryEntry, ArtifactInspection] | None = None
        for entry, inspection in zip(catalog.bundle.components, components, strict=True):
            if entry.kind == kind and entry.symbols == (symbol,) and entry.interval == interval:
                selected = (entry, inspection)
                break
        if selected is None:
            raise HTTPException(status_code=404, detail="dataset component not found")

        entry, inspection = selected
        try:
            rows = query_component_rows(
                configured_artifact_root,
                entry,
                inspection,
                start=start,
                end=end,
                limit=limit,
            )
        except QueryDataIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="dataset query integrity verification failed",
            ) from exc
        except QueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RowsResponse(
            kind=entry.kind,
            symbol=symbol,
            interval=entry.interval,
            start=start,
            end=end,
            row_count=len(rows),
            limit=limit,
            rows=rows,
        )

    @app.get("/api/v1/canary/summary", response_model=CanarySummaryResponse)
    def canary_summary() -> CanarySummaryResponse:
        try:
            return load_verified_canary_summary(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    @app.get("/api/v1/canary/hawkes", response_model=CanaryHawkesResponse)
    def canary_hawkes() -> CanaryHawkesResponse:
        try:
            return load_verified_canary_hawkes(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    @app.get("/api/v1/canary/risk", response_model=CanaryRiskResponse)
    def canary_risk() -> CanaryRiskResponse:
        try:
            return load_verified_canary_risk(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    @app.get("/api/v1/canary/accounting", response_model=CanaryAccountingResponse)
    def canary_accounting() -> CanaryAccountingResponse:
        try:
            return load_verified_canary_accounting(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    @app.get("/api/v1/canary/live-market", response_model=CanaryLiveMarketResponse)
    def canary_live_market() -> CanaryLiveMarketResponse:
        try:
            return load_verified_canary_live_market(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="canary evidence unavailable") from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evidence integrity verification failed",
            ) from exc

    # Phase 294: Live Paper-Safe Execution Engine & Zero-Drift Matching Simulator
    @app.get("/api/v1/canary/paper-execution", response_model=CanaryPaperExecutionResponse)
    def canary_paper_execution() -> CanaryPaperExecutionResponse:
        try:
            return load_verified_canary_paper_execution(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="canary paper execution evidence unavailable"
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary paper execution integrity verification failed",
            ) from exc

    # Phase 295: Live Strategy Activation & Walk-Forward OOS Promotion Gates
    @app.get(
        "/api/v1/canary/strategy-activation",
        response_model=CanaryStrategyActivationResponse,
    )
    def canary_strategy_activation() -> CanaryStrategyActivationResponse:
        try:
            return load_verified_canary_strategy_activation(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary strategy activation evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary strategy activation integrity verification failed",
            ) from exc

    # Phase 296: Full Autonomous Lifecycle Orchestration & Multi-Session Longevity
    @app.get(
        "/api/v1/canary/autonomous-lifecycle",
        response_model=CanaryAutonomousLifecycleResponse,
    )
    def canary_autonomous_lifecycle() -> CanaryAutonomousLifecycleResponse:
        try:
            return load_verified_canary_autonomous_lifecycle(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary autonomous lifecycle evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary autonomous lifecycle integrity verification failed",
            ) from exc

    # Phase 297: Extreme Market Stress, Flash Crash Simulation & Fault Injection Resilience
    @app.get(
        "/api/v1/canary/stress-fault-injection",
        response_model=CanaryStressFaultInjectionResponse,
    )
    def canary_stress_fault_injection() -> CanaryStressFaultInjectionResponse:
        try:
            return load_verified_canary_stress_fault_injection(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary stress fault injection evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary stress fault injection integrity verification failed",
            ) from exc

    # Phase 298: Dynamic Strategy Mining, Auto-Evolution & Microstructure Mutation Engine
    @app.get(
        "/api/v1/canary/strategy-mining",
        response_model=CanaryStrategyMiningResponse,
    )
    def canary_strategy_mining() -> CanaryStrategyMiningResponse:
        try:
            return load_verified_canary_strategy_mining(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary strategy mining evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary strategy mining integrity verification failed",
            ) from exc

    # Phase 299: Dynamic Multi-Asset Risk Orchestration & Portfolio Rebalancing Engine
    @app.get(
        "/api/v1/canary/portfolio-rebalancing",
        response_model=CanaryPortfolioRebalancingResponse,
    )
    def canary_portfolio_rebalancing() -> CanaryPortfolioRebalancingResponse:
        try:
            return load_verified_canary_portfolio_rebalancing(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary portfolio rebalancing evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary portfolio rebalancing integrity verification failed",
            ) from exc

    # Phase 300: Testnet Exchange Connectivity & Multi-Sig Order Gateway
    @app.get(
        "/api/v1/canary/testnet-gateway",
        response_model=CanaryTestnetGatewayResponse,
    )
    def canary_testnet_gateway() -> CanaryTestnetGatewayResponse:
        try:
            return load_verified_canary_testnet_gateway(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary testnet gateway evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary testnet gateway integrity verification failed",
            ) from exc

    # Phase 301: Live User Data Stream Ingress, Dynamic Position & Bracket Order Management
    @app.get(
        "/api/v1/canary/bracket-positions",
        response_model=CanaryBracketPositionsResponse,
    )
    def canary_bracket_positions() -> CanaryBracketPositionsResponse:
        try:
            return load_verified_canary_bracket_positions(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary bracket positions evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary bracket positions integrity verification failed",
            ) from exc

    # Phase 302: Real-Time Toxic Flow Defense, Adverse Selection Guard
    # & Dynamic Microstructure Slippage Attribution
    @app.get(
        "/api/v1/canary/execution-guard",
        response_model=CanaryExecutionGuardResponse,
    )
    def canary_execution_guard() -> CanaryExecutionGuardResponse:
        try:
            return load_verified_canary_execution_guard(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary execution guard evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary execution guard integrity verification failed",
            ) from exc

    # Phase 303: Autonomous End-to-End Closed-Loop Paper Trading Orchestrator
    # & Shadow Execution Engine
    @app.get(
        "/api/v1/canary/orchestrator",
        response_model=CanaryOrchestratorResponse,
    )
    def canary_orchestrator() -> CanaryOrchestratorResponse:
        try:
            return load_verified_canary_orchestrator(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary orchestrator evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary orchestrator integrity verification failed",
            ) from exc

    # Phase 304: Autonomous Self-Calibrating Parameter Adaptation
    # & Online Regime Learning Engine
    @app.get(
        "/api/v1/canary/calibration",
        response_model=CanaryCalibrationResponse,
    )
    def canary_calibration() -> CanaryCalibrationResponse:
        try:
            return load_verified_canary_calibration(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary calibration evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary calibration integrity verification failed",
            ) from exc

    # Phase 305: Autonomous Multi-Horizon Alpha Ensemble & Meta-Policy Blending Engine
    @app.get(
        "/api/v1/canary/ensemble",
        response_model=CanaryEnsembleResponse,
    )
    def canary_ensemble() -> CanaryEnsembleResponse:
        try:
            return load_verified_canary_ensemble(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary ensemble evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary ensemble integrity verification failed",
            ) from exc

    # Phase 306: Continuous Self-Learning Loop, Strategy Autopsy & Auto-Evolution Daemon
    @app.get(
        "/api/v1/canary/evolution",
        response_model=CanaryAutoEvolutionResponse,
    )
    def canary_evolution() -> CanaryAutoEvolutionResponse:
        try:
            return load_verified_canary_auto_evolution(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary evolution evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary evolution integrity verification failed",
            ) from exc

    # Phase 307: Binance Futures Testnet Live API Integration & Order Dispatch Bridge
    @app.get(
        "/api/v1/canary/testnet-bridge",
        response_model=CanaryTestnetBridgeResponse,
    )
    def canary_testnet_bridge() -> CanaryTestnetBridgeResponse:
        try:
            return load_verified_canary_testnet_bridge(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary testnet bridge evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary testnet bridge integrity verification failed",
            ) from exc

    # Phase 308: Capital Safety Governance, Multi-Signature & Hardware/OS Kill-Switch
    @app.get(
        "/api/v1/canary/kill-switch",
        response_model=CanaryKillSwitchResponse,
    )
    def canary_kill_switch() -> CanaryKillSwitchResponse:
        try:
            return load_verified_canary_kill_switch(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary kill switch evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary kill switch integrity verification failed",
            ) from exc

    # Phase 309: Autonomous Live Production Launch & Micro-Capital Self-Driving Trading Engine
    @app.get(
        "/api/v1/canary/production-launch",
        response_model=CanaryProductionLaunchResponse,
    )
    def canary_production_launch() -> CanaryProductionLaunchResponse:
        try:
            return load_verified_canary_production_launch(configured_canary_phase_dir)
        except CanaryEvidenceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="canary production launch evidence unavailable",
            ) from exc
        except CanaryEvidenceIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="canary production launch integrity verification failed",
            ) from exc

    # Live Market Prices & Macro EMA Telemetry (Milestone 1 / Phase 314)
    @app.get("/api/v1/market/prices")
    def market_prices() -> dict[str, Any]:
        """Provides real-time mark prices and authentic BTC macro EMA levels from Binance."""
        return get_live_market_data(configured_canary_phase_dir)

    # Live Market Candlestick Klines (Phase 312 R1)
    live_klines_cache: dict[tuple[str, str, int], tuple[float, MarketKlinesResponse]] = {}

    @app.get("/api/v1/market/klines", response_model=MarketKlinesResponse)
    def market_klines(
        symbol: Annotated[str, Query(description="Trading pair symbol")] = "SOLUSDT",
        interval: Annotated[str, Query(description="Candlestick interval (15m, 1h)")] = "15m",
        limit: Annotated[int, Query(ge=1, le=1000, description="Candle limit")] = 100,
    ) -> MarketKlinesResponse:
        """Provides normalized OHLCV candlestick records with 5s TTL in-memory caching."""
        import urllib.request

        norm_sym = symbol.strip().upper()
        if interval not in {"1m", "3m", "5m", "15m", "1h", "4h", "1d"}:
            raise HTTPException(status_code=422, detail=f"Unsupported interval: {interval}")

        now_sec = time.time()
        cache_key = (norm_sym, interval, limit)
        if cache_key in live_klines_cache:
            cache_ts, cached_res = live_klines_cache[cache_key]
            if (now_sec - cache_ts) < 5.0:
                return cached_res

        # 1. Primary: Binance Futures public REST query
        try:
            url = (
                f"https://fapi.binance.com/fapi/v1/klines?"
                f"symbol={norm_sym}&interval={interval}&limit={limit}"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "AutonomousFuturesBot/1.0 (PublicRestClient; Unauth)"},
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                if isinstance(raw, list) and len(raw) > 0:
                    candles = [
                        CandlestickPoint(
                            timestamp=int(item[0] // 1000),
                            open=float(item[1]),
                            high=float(item[2]),
                            low=float(item[3]),
                            close=float(item[4]),
                            volume=float(item[5]),
                        )
                        for item in raw
                    ]
                    res = MarketKlinesResponse(
                        symbol=norm_sym,
                        interval=interval,
                        source="binance_futures_live",
                        timestamp_ms=int(now_sec * 1000),
                        count=len(candles),
                        candles=tuple(candles),
                    )
                    live_klines_cache[cache_key] = (now_sec, res)
                    return res
        except Exception:
            pass

        # 2. Fallback: Local canonical Parquet files
        try:
            parquet_candidates = [
                Path("research/immutable-data")
                / interval
                / "canonical"
                / f"{norm_sym}-{interval}.parquet",
                Path(__file__).resolve().parents[3]
                / "research"
                / "immutable-data"
                / interval
                / "canonical"
                / f"{norm_sym}-{interval}.parquet",
                Path("research/immutable-data/approved-public-20261007-segment-b/klines")
                / interval
                / norm_sym
                / "canonical"
                / f"{norm_sym}-{interval}.parquet",
                Path(__file__).resolve().parents[3]
                / "research"
                / "immutable-data"
                / "approved-public-20261007-segment-b"
                / "klines"
                / interval
                / norm_sym
                / "canonical"
                / f"{norm_sym}-{interval}.parquet",
            ]
            for ppath in parquet_candidates:
                if ppath.is_file():
                    import pandas as pd

                    df = pd.read_parquet(ppath)
                    required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
                    if not df.empty and required_cols.issubset(df.columns):
                        tail_df = df.tail(limit)
                        p_candles = []
                        for _, r in tail_df.iterrows():
                            ts_val = r["timestamp"]
                            if hasattr(ts_val, "timestamp"):
                                ts_sec = int(ts_val.timestamp())
                            elif isinstance(ts_val, (int, float)):
                                ts_sec = (
                                    int(ts_val // 1000) if ts_val > 10_000_000_000 else int(ts_val)
                                )
                            else:
                                ts_sec = int(pd.to_datetime(ts_val).timestamp())
                            p_candles.append(
                                CandlestickPoint(
                                    timestamp=ts_sec,
                                    open=float(r["open"]),
                                    high=float(r["high"]),
                                    low=float(r["low"]),
                                    close=float(r["close"]),
                                    volume=float(r["volume"]),
                                )
                            )
                        if p_candles:
                            res = MarketKlinesResponse(
                                symbol=norm_sym,
                                interval=interval,
                                source="local_parquet_cache",
                                timestamp_ms=int(now_sec * 1000),
                                count=len(p_candles),
                                candles=tuple(p_candles),
                            )
                            live_klines_cache[cache_key] = (now_sec, res)
                            return res
        except Exception:
            pass

        raise HTTPException(status_code=503, detail="Market candles unavailable")

    @app.get("/api/v1/execution/status", response_model=ExecutionStatusResponse)
    def execution_status() -> ExecutionStatusResponse:
        return load_execution_status(configured_research_dir)

    # Milestone 5: ICT Strategy Signals Endpoint & Confluence Radar
    register_strategy_routes(app, trader=trader, research_dir=configured_research_dir)

    # Phase 293: Real-Time Telemetry Streaming & WebSocket Push
    register_telemetry_websocket(app, broadcaster=telemetry_broadcaster)

    # Serve production frontend single-page application if dist exists
    default_frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    configured_frontend_dist = frontend_dist_path or Path(
        os.environ.get("AFBOT_FRONTEND_DIST_PATH", str(default_frontend_dist))
    )
    if configured_frontend_dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount(
            "/",
            StaticFiles(directory=str(configured_frontend_dist), html=True),
            name="frontend",
        )

    return app


app = create_app()


__all__ = [
    "BundleResponse",
    "CanaryAccountingResponse",
    "CanaryAutonomousLifecycleResponse",
    "CanaryBracketPositionsResponse",
    "CanaryCalibrationResponse",
    "CanaryExecutionGuardResponse",
    "CanaryHawkesResponse",
    "CanaryLiveMarketResponse",
    "CanaryOrchestratorResponse",
    "CanaryPaperExecutionResponse",
    "CanaryProductionLaunchResponse",
    "CanaryRiskResponse",
    "CanaryStrategyActivationResponse",
    "CanaryStrategyMiningResponse",
    "CanaryStressFaultInjectionResponse",
    "CanarySummaryResponse",
    "CanaryTestnetGatewayResponse",
    "CandidatePromotionItem",
    "CandidateSignalItem",
    "CandlestickPoint",
    "ComponentsResponse",
    "CreatorRegistryResponse",
    "CreatorQualificationResponse",
    "CreatorQualificationSummary",
    "CreatorQualificationsResponse",
    "ExecutionOrderItem",
    "ExecutionPositionItem",
    "ExecutionSolvency",
    "ExecutionStatusResponse",
    "HealthResponse",
    "LearnerArtifactResponse",
    "LearnerMetricQualityQualificationEvidenceResponse",
    "LearnerRunResponse",
    "LearnerQualificationEvidenceResponse",
    "LearnerTrainingEvidenceResponse",
    "LedgerReconciliationItem",
    "MarketKlinesResponse",
    "RegistryResponse",
    "RowsResponse",
    "TelemetryBroadcastManager",
    "VetoInterlockItem",
    "app",
    "create_app",
    "load_execution_status",
    "register_telemetry_websocket",
    "strategy_router",
    "register_strategy_routes",
    "IctSignalsResponse",
    "IctSignalPairItem",
    "TwinsStateItem",
    "PdArrayItem",
    "CandidateGenomeItem",
    "TradeAutopsyItem",
]
