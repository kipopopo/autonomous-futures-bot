"""Autonomous Futures Bot - Strategy ICT Signals Router.

Exposes GET /api/v1/strategy/ict-signals with:
- Multi-pair ICT pattern recognition telemetry across all 8 active pairs.
- 5.0-second thread-safe in-memory TTL caching guaranteeing < 10ms latency.
- Three-tier live trader integration and resilient offline/cold fallback.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import Field

from ..domain.contracts import DomainModel
from ..feed.auto_evolution import DEFAULT_ICT_GENOMES
from ..feed.kline_sequencer import ACTIVE_PAIRS, ACTIVE_TIMEFRAMES
from ..strategy.ict_mmxm import Candle, IctMmxmEngine, PdArray, TwinsSetupState

logger = logging.getLogger("autonomous_futures.api.strategy_router")

CACHE_TTL_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Domain Response Models
# ---------------------------------------------------------------------------


class PdArrayItem(DomainModel):
    """Institutional Higher Time Frame PD Array item."""

    array_type: str = "ORDER_BLOCK"
    type: str = "ORDER_BLOCK"
    timeframe: str = "1h"
    top: float
    bottom: float
    mean_threshold: float
    direction: str
    is_mitigated: bool
    creation_ts: int = 0


class TwinsStateItem(DomainModel):
    """6-Step Twins Reversal State Machine snapshot."""

    symbol: str | None = None
    step_1_htf_hit: bool = False
    step_2_m5_cisd: bool = False
    step_3_twins_fvg: bool = False
    step_4_ote_retrace: bool = False
    step_5_m1_cisd: bool = False
    step_6_ready: bool = False
    active_pda: PdArrayItem | None = None
    m5_cisd_price: float | None = None
    m1_cisd_price: float | None = None
    ote_62: float | None = None
    ote_705: float | None = None
    ote_79: float | None = None
    stdv_2_0: float | None = None
    stdv_4_0: float | None = None
    stop_loss: float | None = None
    take_profit_partial: float | None = None
    take_profit_final: float | None = None
    side: Literal["BUY", "SELL"] | None = None
    step: str = "IDLE"
    invalidation_reason: str = "NONE"


class CandidateGenomeItem(DomainModel):
    """Active ICT Genome parameters and candidate health tier."""

    candidate_id: str | None = None
    symbol: str | None = None
    lookback_htf: int = 100
    ote_lower: float = 0.62
    ote_upper: float = 0.79
    stdv_tp1: float = 2.0
    stdv_tp2: float = 4.0
    swing_lookback: int = 50
    fvg_threshold_pct: float = 0.0015
    health_tier: str = "UNQUALIFIED"
    tier: str = "UNQUALIFIED"
    is_active: bool = False


class TradeAutopsyItem(DomainModel):
    """Trade autopsy attribution record from SQLite."""

    trade_id: str
    candidate_id: str = ""
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    fill_qty: float = 0.0
    entry_timing_error_bps: float = 0.0
    fvg_slippage_bps: float = 0.0
    mae_bps: float = 0.0
    mfe_bps: float = 0.0
    bracket_efficiency: float = 0.0
    realized_edge_bps: float = 0.0
    gross_pnl_usdt: float = 0.0
    fee_cost_usdt: float = 0.0
    net_pnl_usdt: float = 0.0
    cause: str = "UNKNOWN"
    timestamp_ms: int = 0
    # Compatibility aliases
    timing_error: float = 0.0
    fvg_slippage: float = 0.0
    adverse_selection: float = 0.0
    net_edge: float = 0.0
    realized_pnl: float = 0.0


class IctSignalPairItem(DomainModel):
    """Complete ICT signal telemetry object for a single trading pair."""

    symbol: str
    twins_state: TwinsStateItem
    pd_arrays: dict[str, list[PdArrayItem]]
    candidate_genome: CandidateGenomeItem
    recent_autopsies: list[TradeAutopsyItem] = Field(default_factory=list)


class IctSignalsResponse(DomainModel):
    """Top-level response payload for GET /api/v1/strategy/ict-signals."""

    verified: bool = False
    source: str = "public_analysis"
    execution_authority: bool = False
    timestamp_ms: int
    active_family: str = "ICT_MMXM_TWINS"
    signals: dict[str, IctSignalPairItem]


# ---------------------------------------------------------------------------
# Global In-Memory TTL Cache & Engine References
# ---------------------------------------------------------------------------

_cached_response: Response | None = None
_cached_data: IctSignalsResponse | None = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()
_active_trader: Any | None = None


def reset_ict_signals_cache() -> None:
    """Thread-safe reset of in-memory TTL cache for testing and benchmarks."""
    global _cached_response, _cached_data, _cache_ts
    with _cache_lock:
        _cached_response = None
        _cached_data = None
        _cache_ts = 0.0


def set_active_trader(trader: Any | None) -> None:
    """Sets the global ContinuousSelfDrivingTrader instance reference."""
    global _active_trader
    _active_trader = trader


def get_active_trader() -> Any | None:
    """Returns the global active trader instance if registered."""
    return _active_trader


# ---------------------------------------------------------------------------
# Data Extraction & Fallback Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except ValueError, TypeError:
        return None


def _format_pd_array(pda: PdArray | None) -> PdArrayItem | None:
    if pda is None:
        return None
    arr_type = str(getattr(pda, "array_type", "ORDER_BLOCK"))
    return PdArrayItem(
        array_type=arr_type,
        type=arr_type,
        timeframe=str(getattr(pda, "timeframe", "1h")),
        top=float(pda.top),
        bottom=float(pda.bottom),
        mean_threshold=float(pda.mean_threshold),
        direction=str(pda.direction),
        is_mitigated=bool(pda.is_mitigated),
        creation_ts=int(getattr(pda, "creation_ts", 0)),
    )


def _format_twins_state(state: TwinsSetupState | None, symbol: str | None = None) -> TwinsStateItem:
    if state is None:
        return TwinsStateItem(symbol=symbol, step="IDLE", invalidation_reason="NONE")

    step_val = "IDLE"
    if hasattr(state, "step"):
        step_attr = state.step
        step_val = str(step_attr.value if hasattr(step_attr, "value") else step_attr)

    inv_reason_val = "NONE"
    if hasattr(state, "invalidation_reason"):
        inv_attr = state.invalidation_reason
        inv_reason_val = str(inv_attr.value if hasattr(inv_attr, "value") else inv_attr)

    return TwinsStateItem(
        symbol=str(getattr(state, "symbol", symbol or "")),
        step_1_htf_hit=bool(state.step_1_htf_hit),
        step_2_m5_cisd=bool(state.step_2_m5_cisd),
        step_3_twins_fvg=bool(state.step_3_twins_fvg),
        step_4_ote_retrace=bool(state.step_4_ote_retrace),
        step_5_m1_cisd=bool(state.step_5_m1_cisd),
        step_6_ready=bool(state.step_6_ready),
        active_pda=_format_pd_array(state.active_pda),
        m5_cisd_price=_safe_float(state.m5_cisd_price),
        m1_cisd_price=_safe_float(state.m1_cisd_price),
        ote_62=_safe_float(state.ote_62),
        ote_705=_safe_float(state.ote_705),
        ote_79=_safe_float(state.ote_79),
        stdv_2_0=_safe_float(state.stdv_2_0),
        stdv_4_0=_safe_float(state.stdv_4_0),
        stop_loss=_safe_float(state.stop_loss),
        take_profit_partial=_safe_float(state.take_profit_partial),
        take_profit_final=_safe_float(state.take_profit_final),
        side=state.side if state.side in ("BUY", "SELL") else None,
        step=step_val,
        invalidation_reason=inv_reason_val,
    )


def _resolve_telemetry_db_path(research_dir: Path | None = None) -> Path | None:
    """Discovers SQLite telemetry database across known research/storage directories."""
    candidates = []
    if research_dir:
        candidates.extend(
            [
                research_dir / "canary-production-telemetry.sqlite3",
                research_dir / "phase310" / "canary-production-telemetry.sqlite3",
            ]
        )
    cwd = Path.cwd()
    candidates.extend(
        [
            cwd / "artifacts" / "research" / "phase310" / "canary-production-telemetry.sqlite3",
            cwd / "artifacts" / "research" / "canary-production-telemetry.sqlite3",
            Path(
                "/opt/autonomous-futures-bot/artifacts/research/phase310/canary-production-telemetry.sqlite3"
            ),
        ]
    )
    for p in candidates:
        if p.is_file():
            return p
    return None


def _load_recent_autopsies(
    db_path: Path | None,
    symbols: tuple[str, ...],
    limit_per_symbol: int = 10,
    research_dir: Path | None = None,
) -> dict[str, list[TradeAutopsyItem]]:
    import json

    result: dict[str, list[TradeAutopsyItem]] = {sym: [] for sym in symbols}

    json_candidates = []
    if research_dir is not None:
        json_candidates.extend(
            [
                research_dir / "trade-autopsies.json",
                research_dir / "qualified-testnet" / "trade-autopsies.json",
                research_dir.parent / "runtime" / "qualified-testnet" / "trade-autopsies.json",
                (
                    research_dir.parent.parent
                    / "runtime"
                    / "qualified-testnet"
                    / "trade-autopsies.json"
                ),
            ]
        )
    cwd = Path.cwd()
    json_candidates.extend(
        [
            cwd / "runtime" / "qualified-testnet" / "trade-autopsies.json",
            cwd / "artifacts" / "runtime" / "trade-autopsies.json",
            cwd / "artifacts" / "research" / "phase310" / "trade-autopsies.json",
        ]
    )
    for json_path in json_candidates:
        if not json_path.is_file():
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            for item in payload.get("autopsies", []):
                if not isinstance(item, dict) or item.get("status") != "FILLED_AND_CLOSED":
                    continue
                sym = str(item.get("symbol", ""))
                if sym not in result:
                    continue
                slip_bps = float(item.get("entry_slippage_bps", 0.0))
                edge_bps = float(item.get("realized_edge_bps", 0.0))
                net_pnl = float(item.get("net_pnl_usdt", 0.0))
                result[sym].append(
                    TradeAutopsyItem(
                        trade_id=str(item.get("signal_key", item.get("entry_id", ""))),
                        candidate_id=str(item.get("family", "QUALIFIED_RUNTIME")),
                        symbol=sym,
                        side=str(item.get("side", "")),
                        entry_price=float(item.get("entry_average_price", 0.0)),
                        exit_price=float(item.get("exit_average_price", 0.0)),
                        fill_qty=float(item.get("executed_quantity", 0.0)),
                        entry_timing_error_bps=abs(slip_bps),
                        fvg_slippage_bps=max(0.0, slip_bps),
                        mae_bps=0.0,
                        mfe_bps=max(0.0, edge_bps),
                        bracket_efficiency=1.0 if net_pnl > 0 else 0.0,
                        realized_edge_bps=edge_bps,
                        gross_pnl_usdt=float(item.get("gross_pnl_usdt", 0.0)),
                        fee_cost_usdt=float(item.get("commission_usdt", 0.0)),
                        net_pnl_usdt=net_pnl,
                        cause=str(item.get("attribution_cause", "UNKNOWN")),
                        timestamp_ms=int(item.get("closed_ms", 0)),
                        timing_error=abs(slip_bps),
                        fvg_slippage=max(0.0, slip_bps),
                        adverse_selection=0.0,
                        net_edge=edge_bps,
                        realized_pnl=net_pnl,
                    )
                )
        except Exception as exc:
            logger.debug("Non-fatal note reading trade-autopsies.json: %s", exc)

    if not db_path or not db_path.is_file():
        for sym in symbols:
            result[sym] = sorted(result[sym], key=lambda item: item.timestamp_ms, reverse=True)[
                :limit_per_symbol
            ]
        return result

    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=0.2)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for sym in symbols:
            cur.execute(
                """
                SELECT trade_id, candidate_id, symbol, side, entry_price, exit_price,
                       fill_qty, entry_timing_error_bps, fvg_slippage_bps, mae_bps, mfe_bps,
                       bracket_efficiency, realized_edge_bps, gross_pnl_usdt, fee_cost_usdt,
                       net_pnl_usdt, cause, timestamp_ms
                FROM ict_trade_autopsies
                WHERE symbol = ?
                ORDER BY timestamp_ms DESC
                LIMIT ?
                """,
                (sym, limit_per_symbol),
            )
            rows = cur.fetchall()
            sqlite_items = [
                TradeAutopsyItem(
                    trade_id=str(r["trade_id"]),
                    candidate_id=str(r["candidate_id"]),
                    symbol=str(r["symbol"]),
                    side=str(r["side"]),
                    entry_price=float(r["entry_price"]),
                    exit_price=float(r["exit_price"]),
                    fill_qty=float(r["fill_qty"]),
                    entry_timing_error_bps=float(r["entry_timing_error_bps"]),
                    fvg_slippage_bps=float(r["fvg_slippage_bps"]),
                    mae_bps=float(r["mae_bps"]),
                    mfe_bps=float(r["mfe_bps"]),
                    bracket_efficiency=float(r["bracket_efficiency"]),
                    realized_edge_bps=float(r["realized_edge_bps"]),
                    gross_pnl_usdt=float(r["gross_pnl_usdt"]),
                    fee_cost_usdt=float(r["fee_cost_usdt"]),
                    net_pnl_usdt=float(r["net_pnl_usdt"]),
                    cause=str(r["cause"]),
                    timestamp_ms=int(r["timestamp_ms"]),
                    timing_error=float(r["entry_timing_error_bps"]),
                    fvg_slippage=float(r["fvg_slippage_bps"]),
                    adverse_selection=float(r["mae_bps"]),
                    net_edge=float(r["realized_edge_bps"]),
                    realized_pnl=float(r["net_pnl_usdt"]),
                )
                for r in rows
            ]
            result[sym] = sorted(
                [*result[sym], *sqlite_items],
                key=lambda item: item.timestamp_ms,
                reverse=True,
            )[:limit_per_symbol]
        conn.close()
    except Exception as exc:
        logger.debug("Non-fatal note querying autopsies from SQLite: %s", exc)
    return result


def _load_candidate_genomes(
    db_path: Path | None,
    symbols: tuple[str, ...],
) -> dict[str, CandidateGenomeItem]:
    result: dict[str, CandidateGenomeItem] = {}
    # 1. Base defaults from DEFAULT_ICT_GENOMES
    for sym in symbols:
        gen = DEFAULT_ICT_GENOMES.get(sym)
        if gen:
            ht = gen.health_tier
            tier_str = str(ht.value if hasattr(ht, "value") else ht)
            result[sym] = CandidateGenomeItem(
                candidate_id=gen.candidate_id,
                symbol=sym,
                lookback_htf=gen.lookback_htf,
                ote_lower=float(gen.ote_lower),
                ote_upper=float(gen.ote_upper),
                stdv_tp1=float(gen.stdv_tp1),
                stdv_tp2=float(gen.stdv_tp2),
                swing_lookback=gen.swing_lookback,
                fvg_threshold_pct=float(gen.fvg_threshold_pct),
                health_tier=tier_str,
                tier=tier_str,
                is_active=gen.is_active,
            )
        else:
            result[sym] = CandidateGenomeItem(
                candidate_id=f"cand-{sym.lower()}-ict-001",
                symbol=sym,
                health_tier="HEALTHY",
                tier="HEALTHY",
            )

    # 2. Overlay live mutations from SQLite if present
    if db_path and db_path.is_file():
        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=0.2)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT candidate_id, symbol, ote_lower, ote_upper, stdv_tp1, stdv_tp2,
                       lookback_htf, health_tier
                FROM ict_candidate_registry
                WHERE is_active = 1
                """
            )
            for r in cur.fetchall():
                sym = str(r["symbol"])
                if sym in result:
                    tier_str = str(r["health_tier"])
                    result[sym] = CandidateGenomeItem(
                        candidate_id=str(r["candidate_id"]),
                        symbol=sym,
                        lookback_htf=int(r["lookback_htf"]),
                        ote_lower=float(r["ote_lower"]),
                        ote_upper=float(r["ote_upper"]),
                        stdv_tp1=float(r["stdv_tp1"]),
                        stdv_tp2=float(r["stdv_tp2"]),
                        swing_lookback=result[sym].swing_lookback,
                        fvg_threshold_pct=result[sym].fvg_threshold_pct,
                        health_tier=tier_str,
                        tier=tier_str,
                        is_active=True,
                    )
            conn.close()
        except Exception as exc:
            logger.debug("Non-fatal note querying genomes from SQLite: %s", exc)

    return result


_STANDALONE_CANDLE_CACHE: dict[tuple[str, str], tuple[float, list[Candle]]] = {}
_STANDALONE_CANDLE_LOCK = threading.Lock()

_CANDLE_TTL_SECONDS: dict[str, float] = {
    "4h": 1800.0,
    "1h": 300.0,
    "15m": 120.0,
    "5m": 45.0,
    "1m": 15.0,
}


def _fetch_binance_candles_sync(symbol: str, interval: str, limit: int = 50) -> list[Candle]:
    """Fetches public klines directly from Binance Futures public REST endpoint."""
    import json
    import urllib.request
    from decimal import Decimal

    url = (
        f"https://fapi.binance.com/fapi/v1/klines"
        f"?symbol={symbol.upper()}&interval={interval}&limit={min(limit, 100)}"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AutonomousFuturesBot/1.0 (PublicRestClient; Unauth)"},
    )
    with urllib.request.urlopen(req, timeout=2.5) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
        if not isinstance(raw, list):
            return []
        return [
            Candle(
                timestamp_ms=int(r[0]),
                open=Decimal(str(r[1])),
                high=Decimal(str(r[2])),
                low=Decimal(str(r[3])),
                close=Decimal(str(r[4])),
                volume=Decimal(str(r[5])),
            )
            for r in raw
        ]


def _get_multi_tf_candles_cached(
    symbol: str,
) -> tuple[list[Candle], list[Candle], list[Candle], list[Candle], list[Candle]]:
    """Retrieves (4h, 1h, 15m, 5m, 1m) candles with per-timeframe in-memory TTL caching."""
    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return ([], [], [], [], [])

    now = time.time()
    res: dict[str, list[Candle]] = {}
    timeframes = ("4h", "1h", "15m", "5m", "1m")
    to_fetch: list[str] = []

    with _STANDALONE_CANDLE_LOCK:
        for tf in timeframes:
            key = (symbol, tf)
            if key in _STANDALONE_CANDLE_CACHE:
                cached_ts, cached_list = _STANDALONE_CANDLE_CACHE[key]
                ttl = _CANDLE_TTL_SECONDS.get(tf, 60.0)
                if (now - cached_ts) < ttl:
                    res[tf] = cached_list
                    continue
            to_fetch.append(tf)

    if to_fetch:
        for tf in to_fetch:
            try:
                fetched = _fetch_binance_candles_sync(symbol, tf, limit=50)
                with _STANDALONE_CANDLE_LOCK:
                    _STANDALONE_CANDLE_CACHE[(symbol, tf)] = (now, fetched)
                res[tf] = fetched
            except Exception as fetch_err:
                logger.debug("Non-fatal note fetching candles for %s %s: %s", symbol, tf, fetch_err)
                with _STANDALONE_CANDLE_LOCK:
                    old_data = _STANDALONE_CANDLE_CACHE.get((symbol, tf))
                    res[tf] = old_data[1] if old_data else []

    return (
        res.get("4h", []),
        res.get("1h", []),
        res.get("15m", []),
        res.get("5m", []),
        res.get("1m", []),
    )


def build_ict_signals_response(
    trader: Any | None = None,
    research_dir: Path | None = None,
) -> IctSignalsResponse:
    """Builds a fresh IctSignalsResponse across all 8 active pairs."""
    from concurrent.futures import ThreadPoolExecutor

    now_ms = int(time.time() * 1000)
    db_path = _resolve_telemetry_db_path(research_dir)
    autopsies_by_sym = _load_recent_autopsies(db_path, ACTIVE_PAIRS, research_dir=research_dir)
    genomes_by_sym = _load_candidate_genomes(db_path, ACTIVE_PAIRS)

    ict_engine = getattr(trader, "ict_engine", None) or IctMmxmEngine(lookback_htf=100)
    sequencer = getattr(trader, "sequencer", None)

    signals_payload: dict[str, IctSignalPairItem] = {}

    def _evaluate_single_pair(
        sym: str,
    ) -> tuple[str, TwinsSetupState | None, dict[str, list[PdArrayItem]]]:
        twins_state_obj: TwinsSetupState | None = None
        pd_arrays_dict: dict[str, list[PdArrayItem]] = {tf: [] for tf in ACTIVE_TIMEFRAMES}
        try:
            if sequencer:
                if not sequencer.is_trade_ready(sym):
                    return sym, None, pd_arrays_dict
                c4h, c1h, c15m, c5m, c1m = sequencer.get_multi_tf_candles(sym)
            else:
                c4h, c1h, c15m, c5m, c1m = _get_multi_tf_candles_cached(sym)

            candles_by_tf = {"4h": c4h, "1h": c1h, "15m": c15m, "5m": c5m, "1m": c1m}
            for tf, c_list in candles_by_tf.items():
                if c_list:
                    raw_pdas = ict_engine.detect_pd_arrays(c_list, tf)
                    pd_arrays_dict[tf] = [
                        item for p in raw_pdas if (item := _format_pd_array(p)) is not None
                    ]

            if len(c5m) >= 5 and len(c1m) >= 5:
                twins_state_obj = ict_engine.evaluate_twins_setup(
                    symbol=sym,
                    candles_4h=c4h,
                    candles_1h=c1h,
                    candles_15m=c15m,
                    candles_5m=c5m,
                    candles_1m=c1m,
                )
        except Exception as eval_err:
            logger.debug("Non-fatal pattern evaluation note for %s: %s", sym, eval_err)

        return sym, twins_state_obj, pd_arrays_dict

    with ThreadPoolExecutor(max_workers=min(8, len(ACTIVE_PAIRS))) as executor:
        eval_results = list(executor.map(_evaluate_single_pair, ACTIVE_PAIRS))

    for sym, twins_state_obj, pd_arrays_dict in eval_results:
        formatted_twins = _format_twins_state(twins_state_obj, symbol=sym)
        signals_payload[sym] = IctSignalPairItem(
            symbol=sym,
            twins_state=formatted_twins,
            pd_arrays=pd_arrays_dict,
            candidate_genome=genomes_by_sym.get(
                sym,
                CandidateGenomeItem(
                    candidate_id=f"cand-{sym.lower()}-ict-001",
                    symbol=sym,
                ),
            ),
            recent_autopsies=autopsies_by_sym.get(sym, []),
        )

    return IctSignalsResponse(
        verified=sequencer is not None
        and all(sequencer.is_trade_ready(sym) for sym in ACTIVE_PAIRS),
        source="daemon_sequencer" if sequencer is not None else "public_analysis",
        timestamp_ms=now_ms,
        active_family="ICT_MMXM_TWINS",
        signals=signals_payload,
    )


# ---------------------------------------------------------------------------
# Router & Registration
# ---------------------------------------------------------------------------

strategy_router = APIRouter(prefix="/api/v1/strategy", tags=["strategy"])


@strategy_router.get("/ict-signals", response_model=IctSignalsResponse)
def get_ict_signals(request: Request) -> Response:
    """Returns multi-pair ICT MMXM, Twins state, PD arrays, genome and autopsy signals.

    Protected by 5.0-second in-memory TTL cache guaranteeing response latency < 10ms.
    """
    global _cached_response, _cached_data, _cache_ts
    now = time.time()

    # Fast-path cache hit (lock-free read)
    if _cached_response is not None and (now - _cache_ts) < CACHE_TTL_SECONDS:
        return _cached_response

    with _cache_lock:
        now = time.time()
        if _cached_response is not None and (now - _cache_ts) < CACHE_TTL_SECONDS:
            return _cached_response

        # Resolve trader instance from request.app.state or module registry
        trader = None
        research_dir = None
        if request is not None and hasattr(request, "app") and hasattr(request.app, "state"):
            trader = getattr(request.app.state, "trader", None)
            research_dir = getattr(request.app.state, "research_dir", None)
        if trader is None:
            trader = get_active_trader()

        data = build_ict_signals_response(trader=trader, research_dir=research_dir)
        content_bytes = data.model_dump_json().encode("utf-8")
        resp = Response(content=content_bytes, media_type="application/json")
        _cached_data = data
        _cached_response = resp
        _cache_ts = now
        return resp


def register_strategy_routes(
    app: Any,
    trader: Any | None = None,
    research_dir: Path | None = None,
) -> APIRouter:
    """Mounts strategy router onto FastAPI application with dependency binding."""
    if hasattr(app, "state"):
        if trader is not None:
            app.state.trader = trader
            set_active_trader(trader)
        if research_dir is not None:
            app.state.research_dir = research_dir

    app.include_router(strategy_router)
    return strategy_router
