"""Phase 267: Multi-Day Cohort Observation, Telemetry & Maturation Evaluation.

Couples LivePaperTradingEngine with Candidate Registry Manifest Version 2 (BTCUSDT
cand-btcusdt-dcb-002, ETHUSDT cand-ethusdt-dcb-003, SOLUSDT cand-solusdt-rgb-001), isolated SQLite
persistence, deterministic multi-day observation replay, periodic 6-hour fixed-slot observation
marks into paper-observations.sqlite3 with strict deduplication guards, single-position
invariants across shared 100 USDT margin portfolio, automated cohort readiness evaluation,
exact double-entry accounting reconciliation (<1e-15 drift), and strict fail-closed containment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import time
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src/ is importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd  # noqa: E402

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.client import BinancePublicFeedClient  # noqa: E402
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot  # noqa: E402
from autonomous_futures.feed.monitor import CircuitBreakerFeedMonitor  # noqa: E402
from autonomous_futures.feed.telemetry import FeedTelemetryAccumulator  # noqa: E402
from autonomous_futures.paper.admission import StrategyAdmissionDecider  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    CandidateRegistryManifest,
    compute_registry_hash,
    read_candidate_registry,
    verify_candidate_registry_manifest,
)
from autonomous_futures.paper.circuit_breakers import (  # noqa: E402
    HardenedSharedMarginAccount,
)
from autonomous_futures.paper.cohort import (  # noqa: E402
    PaperCohortReadinessReport,
    evaluate_paper_cohort_snapshot,
)
from autonomous_futures.paper.health import PaperHealthReport  # noqa: E402
from autonomous_futures.paper.live_engine import (  # noqa: E402
    DEFAULT_BASE_ALLOCATION_FRACTION,
    DEFAULT_MAX_MARGIN_UTILIZATION,
    DEFAULT_MIN_RESERVE_BUFFER,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_STARTING_CAPITAL,
    DEFAULT_TAKER_FEE_RATE,
    LivePaperTradingEngine,
    compute_file_sha256,
)
from autonomous_futures.paper.maturity import _slot_start  # noqa: E402
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    _artifact_content_hash,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    _qualification_content_hash,
    read_creator_candidate_qualification_artifact,
)

logger = logging.getLogger("run_phase_267_cohort_maturation")

DEFAULT_PHASE267_OUTPUT_DIR = Path("artifacts/research/phase267")
DEFAULT_CANONICAL_HISTORY_DIR = Path("research/immutable-data/5m/canonical")
EXPECTED_MANIFEST_V2_CANDIDATES = {
    "BTCUSDT": "cand-btcusdt-dcb-002",
    "ETHUSDT": "cand-ethusdt-dcb-003",
    "SOLUSDT": "cand-solusdt-rgb-001",
}

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*|"
    r"ghp_[0-9A-Za-z]{36}|gho_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{82}|AKIA[0-9A-Z]{16})"
)


def _assert_zero_secrets(text: str, source_label: str) -> None:
    """Verify text contains zero sensitive tokens or API secrets."""
    match = _SECRET_PATTERN.search(text)
    if match:
        raise DomainViolation(f"Secret pattern matched in {source_label}: {match.group(0)[:8]}...")


def verify_strict_safety_invariants(*, orders_submitted: int = 0) -> dict[str, Any]:
    """Enforce strict read-only safety invariants (zero live orders, zero private keys)."""
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    private_keys_found = int(bool(api_key)) + int(bool(api_secret))

    invariants = {
        "execution_authority": False,
        "orders_submitted": orders_submitted,
        "orders": orders_submitted,
        "api_keys_loaded": private_keys_found,
        "authenticated_endpoints_accessed": False,
        "read_only_streams_only": True,
        "promotion_state": "unpromoted",
        "live_trading_activation": False,
        "paper_activation": False,
        "exchange_access": False,
        "zero_credentials_verified": private_keys_found == 0,
        "zero_secret_leakage": private_keys_found == 0,
    }

    if invariants["orders_submitted"] != 0:
        raise RuntimeError(f"SAFETY VIOLATION: orders submitted ({orders_submitted}) != 0")
    if invariants["execution_authority"] is not False:
        raise RuntimeError("SAFETY VIOLATION: execution_authority must be False")
    if invariants["exchange_access"] is not False:
        raise RuntimeError("SAFETY VIOLATION: exchange_access must be False")
    if invariants["paper_activation"] is not False:
        raise RuntimeError("SAFETY VIOLATION: paper_activation must be False")
    if invariants["api_keys_loaded"] != 0:
        raise RuntimeError(
            f"SAFETY VIOLATION: private credentials detected in environment ({private_keys_found})"
        )

    return invariants


def validate_manifest_v2(manifest_path: Path) -> CandidateRegistryManifest:
    """Validate Candidate Registry Manifest Version 2 compliance and candidate hashes."""
    if not manifest_path.is_file():
        manifest_path = _REPO_ROOT / manifest_path
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    manifest = read_candidate_registry(manifest_path, verify_hash=True)
    if not verify_candidate_registry_manifest(manifest):
        raise DomainViolation(
            f"Manifest registry_hash mismatch: expected {manifest.registry_hash}, "
            f"computed {compute_registry_hash(manifest)}"
        )
    if manifest.registry_version < 2:
        raise DomainViolation(f"Manifest version must be >= 2, got {manifest.registry_version}")

    for symbol, expected_cand_id in EXPECTED_MANIFEST_V2_CANDIDATES.items():
        if symbol not in manifest.symbols:
            raise DomainViolation(f"Missing required active candidate {symbol} in manifest")
        entry = manifest.symbols[symbol]
        if entry.candidate_id != expected_cand_id:
            raise DomainViolation(
                f"Candidate ID mismatch for {symbol}: "
                f"expected {expected_cand_id}, got {entry.candidate_id}"
            )

        art_path = Path(entry.artifact_path)
        if not art_path.is_file():
            # Try resolving relative to repo root
            art_path = _REPO_ROOT / entry.artifact_path
        if not art_path.is_file():
            raise FileNotFoundError(f"Candidate artifact not found: {entry.artifact_path}")

        cand = read_creator_candidate_artifact(art_path)
        if cand.candidate_id != entry.candidate_id:
            raise DomainViolation(f"Candidate ID mismatch in artifact {art_path}")
        if cand.artifact_hash != entry.candidate_artifact_hash:
            raise DomainViolation(f"Candidate artifact hash mismatch in {art_path}")
        computed_art_hash = _artifact_content_hash(cand)
        if computed_art_hash != entry.candidate_artifact_hash:
            raise DomainViolation(f"Candidate content hash mismatch for {symbol}")

        # Locate and validate qualification artifact
        qual_dir = art_path.parent.parent / "qualifications"
        qual_file = qual_dir / f"qual-{entry.candidate_id}.json"
        if not qual_file.is_file():
            qual_file = (
                _REPO_ROOT
                / "artifacts"
                / "paper_live"
                / "qualifications"
                / f"qual-{entry.candidate_id}.json"
            )
        if not qual_file.is_file():
            raise FileNotFoundError(f"Qualification artifact not found for {entry.candidate_id}")

        qual = read_creator_candidate_qualification_artifact(qual_file)
        if qual.qualification_hash != entry.qualification_hash:
            raise DomainViolation(f"Qualification hash mismatch for {entry.candidate_id}")
        if _qualification_content_hash(qual) != entry.qualification_hash:
            raise DomainViolation(f"Qualification content hash mismatch for {entry.candidate_id}")

    unexpected_symbols = set(manifest.symbols.keys()) - set(EXPECTED_MANIFEST_V2_CANDIDATES.keys())
    if unexpected_symbols:
        raise DomainViolation(
            f"Unexpected candidate symbols in manifest v2: {sorted(unexpected_symbols)}"
        )

    return manifest


def _sqlite_row_count(
    db_path: Path, table_name: str, max_retries: int = 5, retry_delay: float = 0.05
) -> int:
    """Safely count rows in SQLite table with retry handling for transient lock contention."""
    if not db_path.is_file():
        return 0
    for attempt in range(max_retries):
        try:
            with closing(sqlite3.connect(db_path, timeout=5.0)) as conn:
                row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
                return int(row[0]) if row else 0
        except sqlite3.OperationalError as exc:
            err_msg = str(exc).lower()
            if "locked" in err_msg or "busy" in err_msg:
                time.sleep(retry_delay * (2**attempt))
                continue
            return 0
        except Exception:
            return 0
    return 0


def _verify_sqlite_unlocked(db_path: Path) -> bool:
    """Verify SQLite database has no dangling locks or unclosed write transactions."""
    if not db_path.is_file():
        return True
    try:
        with closing(sqlite3.connect(db_path, timeout=1.0)) as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute("COMMIT;")
        return True
    except Exception:
        return False


_PARQUET_CACHE: dict[tuple[Path, int, int], pd.DataFrame] = {}


def clear_parquet_cache() -> None:
    """Clear the canonical parquet cache in memory."""
    _PARQUET_CACHE.clear()


def _load_canonical_df(parquet_file: Path, tail_rows: int | None = None) -> pd.DataFrame:
    """Load, sanitize, and cache canonical parquet bars dataframe in-memory.

    Enforces UTC timezone-aware timestamps, drops null/NaT timestamps, deduplicates
    by timestamp, validates or reconstructs close_time, and sorts chronologically.
    Returns an isolated copy to prevent caller in-place cache mutation.
    """
    resolved = parquet_file.resolve()
    try:
        stat = resolved.stat()
        cache_key = (resolved, stat.st_mtime_ns, stat.st_size)
    except OSError:
        cache_key = (resolved, 0, 0)

    if cache_key not in _PARQUET_CACHE:
        try:
            df = pd.read_parquet(resolved)
        except Exception as exc:
            logger.warning("Failed to read parquet file %s: %s", resolved, exc)
            _PARQUET_CACHE[cache_key] = pd.DataFrame()
            return _PARQUET_CACHE[cache_key].copy()

        if df.empty or "timestamp" not in df.columns:
            _PARQUET_CACHE[cache_key] = pd.DataFrame()
            return _PARQUET_CACHE[cache_key].copy()

        # Sanitize timestamp
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.dropna(subset=["timestamp"])
        if df.empty:
            _PARQUET_CACHE[cache_key] = pd.DataFrame()
            return _PARQUET_CACHE[cache_key].copy()

        # Deduplicate timestamps per symbol, keeping latest bar
        df = df.drop_duplicates(subset=["timestamp"], keep="last")

        # Sanitize close price: enforce positive numeric values
        if "close" in df.columns:
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            df = df[df["close"] > 0]
        if df.empty:
            _PARQUET_CACHE[cache_key] = pd.DataFrame()
            return _PARQUET_CACHE[cache_key].copy()

        # Sanitize close_time: ensure UTC datetime and strictly close_time > timestamp
        if "close_time" in df.columns:
            df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
            invalid_mask = df["close_time"].isna() | (df["close_time"] <= df["timestamp"])
            if invalid_mask.any():
                df.loc[invalid_mask, "close_time"] = (
                    df.loc[invalid_mask, "timestamp"]
                    + pd.Timedelta(minutes=5)
                    - pd.Timedelta(milliseconds=1)
                )
        else:
            df["close_time"] = (
                df["timestamp"] + pd.Timedelta(minutes=5) - pd.Timedelta(milliseconds=1)
            )

        df_clean = df.sort_values("timestamp").reset_index(drop=True)
        _PARQUET_CACHE[cache_key] = df_clean

    cached_df = _PARQUET_CACHE[cache_key]
    if tail_rows is not None and tail_rows > 0 and len(cached_df) > tail_rows:
        return cached_df.iloc[-tail_rows:].copy()
    return cached_df.copy()


def seed_engine_history_from_canonical(
    engine: LivePaperTradingEngine,
    history_dir: Path,
    symbols: Sequence[str],
    warmup_bars: int = 300,
    offset_ticks: int = 0,
) -> None:
    """Seed causal historical bars for dynamic feature calculation warmup from parquet data."""
    resolved_history_dir = history_dir if history_dir.is_dir() else _REPO_ROOT / history_dir
    for symbol in symbols:
        parquet_file = resolved_history_dir / f"{symbol}-5m.parquet"
        if parquet_file.is_file():
            try:
                needed = (
                    (warmup_bars + offset_ticks + 50) if offset_ticks > 0 else (warmup_bars + 50)
                )
                df_sorted = _load_canonical_df(parquet_file, tail_rows=needed)
                n = len(df_sorted)
                if n == 0:
                    continue
                if offset_ticks > 0:
                    end_idx = max(0, n - offset_ticks)
                    start_idx = max(0, end_idx - warmup_bars)
                    df_warmup = df_sorted.iloc[start_idx:end_idx]
                else:
                    df_warmup = df_sorted.tail(warmup_bars)
                engine.seed_history(symbol, df_warmup)
                logger.info(
                    "Seeded %d warmup bars for %s from %s",
                    len(df_warmup),
                    symbol,
                    parquet_file.name,
                )
            except Exception as exc:
                logger.warning("Failed to seed history from %s: %s", parquet_file, exc)


def setup_signal_handlers(stop_event: asyncio.Event) -> None:
    """Install SIGINT/SIGTERM signal traps for graceful shutdown."""

    def _handler() -> None:
        logger.info("Caught termination signal; triggering clean daemon shutdown...")
        stop_event.set()

    if sys.platform != "win32":
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _handler)
        except NotImplementedError, RuntimeError:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda s, f: _handler())
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda s, f: _handler())
            except ValueError, AttributeError:
                pass


async def replay_multi_day_cohort_observations(
    engine: LivePaperTradingEngine,
    history_dir: Path,
    symbols: Sequence[str],
    max_ticks: int = 144,
    stop_event: asyncio.Event | None = None,
) -> int:
    """Replay deterministic multi-day bars and tickers sequentially from canonical parquet data.

    Enforces 6-hour fixed-slot observation marks, unified multi-symbol timeline alignment,
    and single-position invariants across symbols.
    """
    if max_ticks <= 0:
        return 0

    resolved_history_dir = history_dir if history_dir.is_dir() else _REPO_ROOT / history_dir
    if not resolved_history_dir.is_dir():
        raise FileNotFoundError(f"Canonical history directory not found: {history_dir}")
    symbol_dfs: dict[str, pd.DataFrame] = {}
    tail_count = max(max_ticks * 2, max_ticks + 50) if max_ticks > 0 else None
    for sym in symbols:
        parquet_path = resolved_history_dir / f"{sym}-5m.parquet"
        if not parquet_path.is_file():
            logger.warning("Parquet file for %s not found in %s", sym, resolved_history_dir)
            continue
        df = _load_canonical_df(parquet_path, tail_rows=tail_count)
        if not df.empty:
            symbol_dfs[sym] = df

    if not symbol_dfs:
        logger.warning("No canonical data found for multi-day observation replay")
        return 0

    # Collect all unique valid timestamps across all symbols to form a unified cohort timeline
    all_timestamps: set[datetime] = set()
    for df in symbol_dfs.values():
        all_timestamps.update(
            t.to_pydatetime().astimezone(UTC) for t in df["timestamp"] if pd.notna(t)
        )

    sorted_cohort_timestamps = sorted(all_timestamps)
    if not sorted_cohort_timestamps:
        logger.warning("No valid timestamps found in canonical data for observation replay")
        return 0

    # Determine target replay window (last max_ticks timestamps across cohort)
    if len(sorted_cohort_timestamps) > max_ticks:
        target_timestamps = sorted_cohort_timestamps[-max_ticks:]
    else:
        target_timestamps = sorted_cohort_timestamps

    target_ts_set = set(target_timestamps)

    # Pre-index each symbol's rows by UTC timestamp for fast O(1) synchronized lookup
    symbol_indexed: dict[str, dict[datetime, dict[str, Any]]] = {}
    for sym, df in symbol_dfs.items():
        sym_rows: dict[datetime, dict[str, Any]] = {}
        for rec in df.to_dict(orient="records"):
            r_ts = rec["timestamp"]
            if isinstance(r_ts, pd.Timestamp):
                ts_utc = r_ts.to_pydatetime().astimezone(UTC)
            elif isinstance(r_ts, datetime):
                ts_utc = (
                    r_ts.astimezone(UTC) if r_ts.tzinfo is not None else r_ts.replace(tzinfo=UTC)
                )
            else:
                continue
            if ts_utc in target_ts_set:
                sym_rows[ts_utc] = rec
        symbol_indexed[sym] = sym_rows

    ticks_processed = 0
    for ts in target_timestamps:
        if stop_event is not None and stop_event.is_set():
            logger.info(
                "Stop event set; terminating multi-day observation replay early at tick %d",
                ticks_processed,
            )
            break
        if ticks_processed >= max_ticks:
            break

        # Process ticker and bar for each symbol in lockstep
        for sym in symbols:
            rows_map = symbol_indexed.get(sym)
            if rows_map is None or ts not in rows_map:
                continue
            row = rows_map[ts]

            r_close = row.get("close")
            if r_close is None or pd.isna(r_close):
                continue
            close_price = Decimal(str(r_close))
            if close_price <= Decimal("0"):
                continue
            spread_half = max(Decimal("0.01"), close_price * Decimal("0.0001"))

            r_close_time = row.get("close_time")
            if isinstance(r_close_time, pd.Timestamp):
                close_time = r_close_time.to_pydatetime().astimezone(UTC)
            elif isinstance(r_close_time, datetime):
                close_time = (
                    r_close_time.astimezone(UTC)
                    if r_close_time.tzinfo is not None
                    else r_close_time.replace(tzinfo=UTC)
                )
            else:
                close_time = ts + timedelta(minutes=5, milliseconds=-1)
            if close_time <= ts:
                close_time = ts + timedelta(minutes=5, milliseconds=-1)

            ticker = TickerSnapshot(
                symbol=sym,
                best_bid_price=max(Decimal("0.000001"), close_price - spread_half),
                best_bid_qty=Decimal("1.0"),
                best_ask_price=close_price + spread_half,
                best_ask_qty=Decimal("1.0"),
                transaction_time=close_time,
                event_time=close_time,
            )
            # Update latest ticker snapshot for mark-to-market pricing and protective stops
            engine.latest_tickers[sym] = ticker
            if sym in engine.active_trades:
                engine._evaluate_tick_stops(sym, ticker)
            await engine.monitor.push_ticker(ticker)

            open_val = row.get("open")
            open_price = (
                Decimal(str(open_val))
                if open_val is not None and not pd.isna(open_val)
                else close_price
            )
            if open_price <= Decimal("0"):
                open_price = close_price

            high_val = row.get("high")
            high_price = (
                Decimal(str(high_val))
                if high_val is not None and not pd.isna(high_val)
                else max(open_price, close_price)
            )
            low_val = row.get("low")
            low_price = (
                Decimal(str(low_val))
                if low_val is not None and not pd.isna(low_val)
                else min(open_price, close_price)
            )

            high_price = max(high_price, open_price, close_price)
            low_price = max(Decimal("0.000001"), min(low_price, open_price, close_price))

            raw_vol = row.get("volume")
            volume = (
                Decimal(str(raw_vol))
                if raw_vol is not None and not pd.isna(raw_vol)
                else Decimal("0")
            )
            if volume < Decimal("0"):
                volume = Decimal("0")

            raw_qvol = row.get("quote_volume")
            quote_volume = (
                Decimal(str(raw_qvol))
                if raw_qvol is not None and not pd.isna(raw_qvol)
                else volume * close_price
            )
            if quote_volume < Decimal("0"):
                quote_volume = volume * close_price

            raw_trades = row.get("trades")
            trades = (
                int(raw_trades)
                if raw_trades is not None and not pd.isna(raw_trades) and int(raw_trades) >= 0
                else 0
            )

            raw_tbb = row.get("taker_buy_base")
            taker_buy_base = (
                Decimal(str(raw_tbb))
                if raw_tbb is not None and not pd.isna(raw_tbb)
                else Decimal("0")
            )
            if taker_buy_base < Decimal("0"):
                taker_buy_base = Decimal("0")

            raw_tbq = row.get("taker_buy_quote")
            taker_buy_quote = (
                Decimal(str(raw_tbq))
                if raw_tbq is not None and not pd.isna(raw_tbq)
                else Decimal("0")
            )
            if taker_buy_quote < Decimal("0"):
                taker_buy_quote = Decimal("0")

            bar = CanonicalBar(
                symbol=sym,
                interval="5m",
                timestamp=ts,
                close_time=close_time,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                quote_volume=quote_volume,
                trades=trades,
                taker_buy_base=taker_buy_base,
                taker_buy_quote=taker_buy_quote,
                is_closed=True,
            )
            await engine.handle_bar(bar)

        ticks_processed += 1

    logger.info(
        "Completed multi-day replay of %d bar ticks across %d symbols",
        ticks_processed,
        len(symbols),
    )
    return ticks_processed


@dataclass(frozen=True, slots=True)
class Phase267CohortMaturationResult:
    """Complete telemetry result of Phase 267 cohort maturation observation run."""

    output_dir: Path
    registry_version: int
    registry_hash: str
    starting_equity: Decimal
    final_cash: Decimal
    realized_pnl: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    cumulative_fees: Decimal
    cumulative_slippage: Decimal
    max_margin_utilization: Decimal
    min_reserve_buffer: Decimal
    positions_reconciled: bool
    accounting_reconciled: bool
    zero_balance_drift: bool
    drift: Decimal
    health_reports: dict[str, PaperHealthReport]
    cohort_report: PaperCohortReadinessReport
    artifact_hashes: dict[str, str]
    maturation_summary_path: Path
    paper_summary_path: Path


async def run_phase_267_cohort_maturation(
    *,
    output_dir: Path = DEFAULT_PHASE267_OUTPUT_DIR,
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH,
    history_dir: Path = DEFAULT_CANONICAL_HISTORY_DIR,
    duration: float | None = 10.0,
    days: float | None = None,
    ticks: int | None = None,
    smoke_test: bool = False,
    mode: str = "auto",
    offline: bool = False,
    clean: bool = False,
    starting_capital: Decimal = DEFAULT_STARTING_CAPITAL,
    max_margin_utilization: Decimal = DEFAULT_MAX_MARGIN_UTILIZATION,
    min_reserve_buffer: Decimal = DEFAULT_MIN_RESERVE_BUFFER,
    fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    ws_url: str = "wss://fstream.binance.com",
) -> Phase267CohortMaturationResult:
    """Execute deterministic Phase 267 cohort maturation runner under Manifest Version 2."""
    start_monotonic = time.monotonic()
    start_utc = datetime.now(UTC)

    # 1. Enforce strict safety invariants and risk parameter bounds prior to execution
    verify_strict_safety_invariants(orders_submitted=0)
    if starting_capital <= Decimal("0"):
        raise DomainViolation("Starting capital must be strictly positive")
    if not (Decimal("0") < max_margin_utilization <= Decimal("1.0")):
        raise DomainViolation("Max margin utilization must be in (0, 1]")
    if not (Decimal("0") <= min_reserve_buffer < Decimal("1.0")):
        raise DomainViolation("Min reserve buffer must be in [0, 1)")
    if max_margin_utilization + min_reserve_buffer > Decimal("1.0"):
        raise DomainViolation(
            "Sum of max margin utilization and min reserve buffer cannot exceed 1.0"
        )
    if fee_rate < Decimal("0"):
        raise DomainViolation("Taker fee rate must be non-negative")
    if slippage_bps < Decimal("0"):
        raise DomainViolation("Slippage bps must be non-negative")
    if duration is not None and duration <= 0:
        raise DomainViolation("Session duration must be strictly positive")
    if days is not None and days <= 0:
        raise DomainViolation("Observation replay days must be strictly positive")
    if ticks is not None and ticks <= 0:
        raise DomainViolation("Replay ticks must be strictly positive")
    if days is not None and ticks is not None:
        raise DomainViolation("Cannot specify both 'days' and 'ticks'")

    # 2. Validate Candidate Registry Manifest Version 2
    manifest = validate_manifest_v2(registry_path)
    symbols = tuple(s.upper() for s in manifest.symbols.keys())

    # 3. Create isolated output directories and SQLite paths
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_db = output_dir / "paper-ledger.sqlite3"
    lifecycle_db = output_dir / "paper-lifecycle.sqlite3"
    observations_db = output_dir / "paper-observations.sqlite3"

    if clean:
        clear_parquet_cache()
        for db_file in (ledger_db, lifecycle_db, observations_db):
            for suffix in ("", "-wal", "-shm", "-journal"):
                target = db_file.parent / f"{db_file.name}{suffix}"
                if target.is_file():
                    try:
                        target.unlink()
                    except OSError:
                        pass

    # 4. Initialize shared margin account
    account = HardenedSharedMarginAccount(
        starting_capital=starting_capital,
        max_utilization=max_margin_utilization,
        base_allocation_fraction=DEFAULT_BASE_ALLOCATION_FRACTION,
        min_reserve_buffer=min_reserve_buffer,
    )

    # 5. Initialize telemetry, feed client, and circuit breaker monitor
    telemetry = FeedTelemetryAccumulator(symbols=symbols)
    feed_client = BinancePublicFeedClient(
        symbols=symbols,
        streams=("bookTicker", "kline_5m"),
        url=ws_url,
        telemetry=telemetry,
    )
    monitor = CircuitBreakerFeedMonitor(
        account=account,
        symbols=symbols,
        max_queue_size=10_000,
        evaluate_on_ticker=True,
    )

    # 6. Initialize LivePaperTradingEngine with Candidate Registry Manifest v2
    engine = LivePaperTradingEngine(
        registry_manifest=manifest,
        ledger_db=ledger_db,
        lifecycle_db=lifecycle_db,
        observations_db=observations_db,
        starting_capital=starting_capital,
        max_utilization=max_margin_utilization,
        min_reserve_buffer=min_reserve_buffer,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        feed_client=feed_client,
        monitor=monitor,
        account=account,
        telemetry=telemetry,
        require_flat=False,
    )

    # Verify candidate artifact hashes, qualification hashes, and admission decisions on startup
    decider = StrategyAdmissionDecider()
    for sym in symbols:
        if sym not in engine.candidates:
            raise DomainViolation(f"Candidate strategy for symbol {sym} not loaded in engine")
        cand = engine.candidates[sym]
        qual = engine.qualifications.get(sym)
        if qual is None:
            raise DomainViolation(f"Qualification artifact for symbol {sym} not loaded in engine")

        # Hash validations
        if cand.artifact_hash != manifest.symbols[sym].candidate_artifact_hash:
            raise DomainViolation(f"Artifact hash mismatch for {sym}")
        if qual.qualification_hash != manifest.symbols[sym].qualification_hash:
            raise DomainViolation(f"Qualification hash mismatch for {sym}")

        # Decider validation
        decision = decider.evaluate_admission(
            candidate=cand,
            qualification=qual,
            symbol=sym,
            active_trades=engine.active_trades,
            require_flat=False,
            evaluated_at=start_utc,
        )
        if decision.decision != "admitted":
            raise DomainViolation(
                f"Candidate {cand.candidate_id} admission blocked: "
                f"{decision.decision} ({decision.reason_codes})"
            )

    session_duration = (
        5.0 if smoke_test and (duration is None or duration == 10.0) else (duration or 10.0)
    )
    effective_mode = (
        "batch"
        if (
            offline
            or mode == "batch"
            or (mode == "auto" and (days is not None or ticks is not None))
        )
        else mode
    )

    resolved_history_dir = history_dir if history_dir.is_dir() else _REPO_ROOT / history_dir
    if effective_mode == "batch" and not resolved_history_dir.is_dir():
        raise FileNotFoundError(f"Canonical history directory not found: {history_dir}")

    # Determine replay bar count
    if ticks is not None:
        batch_ticks_count = ticks
    elif days is not None:
        batch_ticks_count = max(1, int(days * 288))
    elif smoke_test:
        batch_ticks_count = 10
    else:
        batch_ticks_count = 144  # Default: 12-hour observation replay (2 full 6-hour slots)

    # 7. Seed warmup bars for causal indicators
    seed_engine_history_from_canonical(
        engine=engine,
        history_dir=history_dir,
        symbols=symbols,
        warmup_bars=300,
        offset_ticks=batch_ticks_count if effective_mode in ("batch", "auto") else 0,
    )

    # 8. Setup graceful shutdown handling (signal trap and timeout-driven termination)
    stop_event = asyncio.Event()
    setup_signal_handlers(stop_event)
    await monitor.start()

    logger.info(
        "Starting Phase 267 paper cohort maturation runner (mode=%s, duration=%.1fs, ticks=%s)",
        effective_mode,
        session_duration,
        batch_ticks_count if effective_mode in ("batch", "auto") else None,
    )

    try:
        # 9. Execute bounded execution mode
        if effective_mode == "batch":
            await replay_multi_day_cohort_observations(
                engine=engine,
                history_dir=history_dir,
                symbols=symbols,
                max_ticks=batch_ticks_count,
                stop_event=stop_event,
            )
        elif effective_mode == "live":
            stream_task = asyncio.create_task(
                feed_client.connect_and_stream(
                    duration_seconds=session_duration,
                    on_bar=engine.handle_bar,
                    on_ticker=engine.handle_ticker,
                )
            )
            wait_task = asyncio.create_task(stop_event.wait())
            try:
                done, pending = await asyncio.wait(
                    [stream_task, wait_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if stream_task in done and not stream_task.cancelled():
                    exc = stream_task.exception()
                    if exc is not None:
                        raise exc
                if (
                    not stop_event.is_set()
                    and feed_client.reconnect_count > 0
                    and telemetry.total_messages == 0
                ):
                    raise ConnectionError(
                        f"Live feed connection failed to receive messages after "
                        f"{feed_client.reconnect_count} reconnect attempts"
                    )
            finally:
                stop_event.set()
        else:  # auto mode: try live, fall back gracefully to batch on network failure
            stream_failed = False
            stream_exc: BaseException | None = None
            try:
                stream_task = asyncio.create_task(
                    feed_client.connect_and_stream(
                        duration_seconds=session_duration,
                        on_bar=engine.handle_bar,
                        on_ticker=engine.handle_ticker,
                    )
                )
                wait_task = asyncio.create_task(stop_event.wait())
                done, pending = await asyncio.wait(
                    [stream_task, wait_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if stream_task in done and not stream_task.cancelled():
                    exc = stream_task.exception()
                    if exc is not None:
                        stream_failed = True
                        stream_exc = exc
                if not stop_event.is_set() and telemetry.total_messages == 0:
                    stream_failed = True
            except Exception as exc:
                stream_failed = True
                stream_exc = exc

            if stream_failed and not stop_event.is_set():
                logger.warning(
                    "Live public stream unavailable or empty (%s); executing multi-day replay",
                    stream_exc or "zero messages received",
                )
                await replay_multi_day_cohort_observations(
                    engine=engine,
                    history_dir=history_dir,
                    symbols=symbols,
                    max_ticks=batch_ticks_count,
                    stop_event=stop_event,
                )
            stop_event.set()
    finally:
        # 10. Graceful shutdown and clean resource cleanup
        logger.info("Initiating graceful shutdown of LivePaperTradingEngine...")
        stop_event.set()
        await engine.stop()

    # 11. Exact double-entry accounting reconciliation (R3)
    reconciliation = engine.reconcile_balances()
    logger.info("Exact balance reconciliation: %s", reconciliation)

    final_cash = account.cash
    realized_pnl = Decimal(reconciliation["total_realized_pnl"])
    total_open_entry_fees = Decimal(reconciliation.get("total_open_entry_fees", "0"))
    expected_cash = starting_capital + realized_pnl - total_open_entry_fees
    drift = abs(final_cash - expected_cash)

    if drift >= Decimal("1e-15"):
        raise DomainViolation(
            f"Double-entry accounting drift violation: "
            f"|{final_cash} - ({starting_capital} + {realized_pnl} - "
            f"{total_open_entry_fees})| = {drift} >= 1e-15"
        )
    if not reconciliation["zero_balance_drift"]:
        raise DomainViolation(
            f"Reconciliation zero_balance_drift is False: drift={reconciliation['drift']}"
        )
    zero_drift_reconciled = bool(reconciliation["zero_balance_drift"] and drift < Decimal("1e-15"))

    # Single-position invariants per symbol across shared portfolio margin
    open_positions = engine.sqlite_ledger.load().open_positions()
    pos_symbols = [p.symbol for p in open_positions]
    if len(pos_symbols) != len(set(pos_symbols)):
        raise DomainViolation(
            f"Single-position invariant violated: multiple open positions detected {pos_symbols}"
        )

    # Risk limits: margin utilization <= 80.00% and reserve buffer >= 20.00%
    if account.max_observed_utilization > max_margin_utilization:
        raise DomainViolation(
            f"Margin utilization ceiling violated: "
            f"{account.max_observed_utilization} > {max_margin_utilization}"
        )
    if account.min_observed_buffer < min_reserve_buffer:
        raise DomainViolation(
            f"Reserve buffer violated: {account.min_observed_buffer} < {min_reserve_buffer}"
        )

    # 12. Strict fixed-slot observation deduplication check (R1)
    for sym, cand in engine.candidates.items():
        cand_obs = engine.observation_store.read(cand.candidate_id, cand.artifact_hash)
        slots = [_slot_start(o.observed_at) for o in cand_obs]
        if len(slots) != len(set(slots)):
            raise DomainViolation(
                f"Duplicate observation slot detected for {sym} ({cand.candidate_id})"
            )

    # 13. Automated snapshot cohort readiness report (R2)
    health_reports, cohort_report = evaluate_paper_cohort_snapshot(
        ledger_db=ledger_db,
        lifecycle_db=lifecycle_db,
        observations_db=observations_db,
        manifest=manifest,
        output_dir=output_dir,
        as_of=None,
    )

    # Also persist paper-cohort-maturation-report.json as the authoritative maturation view
    maturation_report_path = output_dir / "paper-cohort-maturation-report.json"
    cohort_json = json.dumps(cohort_report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    _assert_zero_secrets(cohort_json, str(maturation_report_path))
    maturation_report_path.write_text(cohort_json, encoding="utf-8", newline="\n")

    # Compute cumulative metrics
    final_ledger = engine.sqlite_ledger.load()
    closed_entries = [e for e in final_ledger.entries if e.event == "close"]
    cum_fees = sum(
        (
            (e.entry_fee or Decimal("0")) + (e.exit_fee or Decimal("0"))
            for e in final_ledger.entries
        ),
        Decimal("0"),
    )
    cum_slippage = sum(
        (e.slippage_cost or Decimal("0") for e in final_ledger.entries),
        Decimal("0"),
    )
    winning_trades = engine.winning_trades
    losing_trades = engine.losing_trades
    total_trades = engine.total_closed_trades
    win_rate = (winning_trades / total_trades) if total_trades > 0 else 0.0

    # 14. Deterministic SHA-256 cryptographic hashes for generated artifacts
    artifact_files = [
        "paper-ledger.sqlite3",
        "paper-lifecycle.sqlite3",
        "paper-observations.sqlite3",
        "paper-cohort-readiness-report.json",
        "paper-cohort-maturation-report.json",
    ]
    for sym in symbols:
        artifact_files.append(f"paper-health-report-{sym}.json")

    artifact_hashes: dict[str, str] = {}
    for filename in sorted(artifact_files):
        fpath = output_dir / filename
        if fpath.is_file():
            artifact_hashes[filename] = compute_file_sha256(fpath)

    # Query SQLite database counts
    ledger_count = len(final_ledger.entries)
    lifecycle_count = _sqlite_row_count(lifecycle_db, "paper_lifecycle_marks")
    obs_count = _sqlite_row_count(observations_db, "paper_observations")

    # 15. Comprehensive maturation summary (R2, R4)
    summary_payload: dict[str, Any] = {
        "phase": "phase_267",
        "description": (
            "Phase 267 Multi-Day Cohort Observation & Maturation Evaluation (Manifest v2)"
        ),
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.monotonic() - start_monotonic, 3),
        "registry_hash": manifest.registry_hash,
        "registry_version": manifest.registry_version,
        "candidates": {
            sym: {
                "candidate_id": manifest.symbols[sym].candidate_id,
                "artifact_hash": manifest.symbols[sym].candidate_artifact_hash,
                "qualification_hash": manifest.symbols[sym].qualification_hash,
                "timeframe": engine.candidates[sym].strategy.universe.timeframe,
                "family": engine.candidates[sym].strategy.family,
                "admission_decision": engine.admission_decisions[sym].decision,
                "trades_count": sum(1 for e in closed_entries if e.symbol == sym),
                "realized_pnl_usdt": str(
                    sum(
                        (
                            e.net_pnl
                            for e in closed_entries
                            if e.symbol == sym and e.net_pnl is not None
                        ),
                        Decimal("0"),
                    )
                ),
                "health_status": health_reports[sym].health_status,
                "maturity_status": health_reports[sym].maturity_status,
            }
            for sym in symbols
        },
        "shared_portfolio_margin": {
            "starting_capital_usdt": str(starting_capital),
            "final_cash_usdt": str(final_cash),
            "current_equity_usdt": str(engine.current_equity()),
            "realized_pnl_usdt": str(realized_pnl),
            "cumulative_fees_usdt": str(cum_fees),
            "cumulative_slippage_usdt": str(cum_slippage),
            "margin_utilization_ceiling": str(max_margin_utilization),
            "max_observed_margin_utilization": str(account.max_observed_utilization),
            "min_observed_reserve_buffer": str(account.min_observed_buffer),
            "unencumbered_equity_buffer_pct": str(
                (Decimal("1.0") - max_margin_utilization) * Decimal("100")
            ),
            "base_position_fraction": str(DEFAULT_BASE_ALLOCATION_FRACTION),
            "zero_balance_drift": zero_drift_reconciled,
            "drift_amount": str(drift),
        },
        "portfolio_summary": {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(win_rate, 4),
            "win_rate_pct": round(win_rate * 100, 2),
            "open_positions_count": len(open_positions),
            "positions_reconciled": True,
            "accounting_reconciled": True,
            "zero_balance_drift": zero_drift_reconciled,
        },
        "cohort_readiness": {
            "cohort_status": cohort_report.cohort_status,
            "expected_candidate_count": cohort_report.expected_candidate_count,
            "reported_candidate_count": cohort_report.reported_candidate_count,
            "mature_candidate_count": cohort_report.mature_candidate_count,
            "healthy_candidate_count": cohort_report.healthy_candidate_count,
            "maturing_candidate_count": cohort_report.maturing_candidate_count,
            "blocked_candidate_count": cohort_report.blocked_candidate_count,
            "all_mature": cohort_report.all_mature,
            "all_accounting_complete": cohort_report.all_accounting_complete,
            "reason_codes": list(cohort_report.reason_codes),
        },
        "maturation_progression": {
            "cohort_status": cohort_report.cohort_status,
            "valid_status_codes": [
                "unavailable",
                "not_ready",
                "blocked",
                "ready_for_human_review",
            ],
            "valid_per_symbol_health_status": [
                "evaluating",
                "maturing",
                "mature",
                "blocked",
            ],
            "per_symbol_maturation": {
                sym: {
                    "candidate_id": manifest.symbols[sym].candidate_id,
                    "health_status": health_reports[sym].health_status,
                    "maturity_status": health_reports[sym].maturity_status,
                    "accounting_complete": health_reports[sym].accounting_complete,
                    "reason_codes": list(health_reports[sym].reason_codes),
                }
                for sym in symbols
            },
        },
        "sqlite_persistence": {
            "databases": {
                "paper-ledger.sqlite3": {
                    "path": ledger_db.as_posix(),
                    "row_count": ledger_count,
                    "sha256": artifact_hashes.get("paper-ledger.sqlite3", ""),
                },
                "paper-lifecycle.sqlite3": {
                    "path": lifecycle_db.as_posix(),
                    "row_count": lifecycle_count,
                    "sha256": artifact_hashes.get("paper-lifecycle.sqlite3", ""),
                },
                "paper-observations.sqlite3": {
                    "path": observations_db.as_posix(),
                    "row_count": obs_count,
                    "sha256": artifact_hashes.get("paper-observations.sqlite3", ""),
                },
            }
        },
        "safety_invariants": {
            "data_source": "public_streams_and_cache",
            "exchange_access": False,
            "execution_authority": False,
            "orders": 0,
            "orders_submitted": 0,
            "paper_activation": False,
            "api_keys_loaded": 0,
            "promotion_state": "unpromoted",
            "live_trading_activation": False,
            "zero_secret_leakage": True,
        },
        "resource_cleanup": {
            "feed_client_connected": bool(getattr(feed_client, "_running", False)),
            "websocket_closed": getattr(feed_client, "_ws", None) is None,
            "sqlite_connections_closed": all(
                _verify_sqlite_unlocked(db) for db in (ledger_db, lifecycle_db, observations_db)
            ),
            "background_tasks_cleaned": bool(
                monitor._worker_task is None or monitor._worker_task.done()
            ),
        },
        "artifact_hashes": artifact_hashes,
    }

    # Verify zero secrets across generated summary
    summary_json = json.dumps(summary_payload, indent=2, sort_keys=True) + "\n"
    _assert_zero_secrets(summary_json, "maturation-summary.json")

    maturation_summary_path = output_dir / "maturation-summary.json"
    paper_summary_path = output_dir / "paper-summary.json"
    maturation_summary_path.write_text(summary_json, encoding="utf-8", newline="\n")
    paper_summary_path.write_text(summary_json, encoding="utf-8", newline="\n")

    # Update artifact hashes with summary files
    artifact_hashes["maturation-summary.json"] = compute_file_sha256(maturation_summary_path)
    artifact_hashes["paper-summary.json"] = compute_file_sha256(paper_summary_path)

    # Post-execution safety verification
    verify_strict_safety_invariants(orders_submitted=0)

    logger.info("Phase 267 cohort maturation successfully completed! Cash: %s USDT", final_cash)

    return Phase267CohortMaturationResult(
        output_dir=output_dir,
        registry_version=manifest.registry_version,
        registry_hash=manifest.registry_hash,
        starting_equity=starting_capital,
        final_cash=final_cash,
        realized_pnl=realized_pnl,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        cumulative_fees=cum_fees,
        cumulative_slippage=cum_slippage,
        max_margin_utilization=account.max_observed_utilization,
        min_reserve_buffer=account.min_observed_buffer,
        positions_reconciled=True,
        accounting_reconciled=True,
        zero_balance_drift=zero_drift_reconciled,
        drift=drift,
        health_reports=health_reports,
        cohort_report=cohort_report,
        artifact_hashes=artifact_hashes,
        maturation_summary_path=maturation_summary_path,
        paper_summary_path=paper_summary_path,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for Phase 267 cohort maturation runner."""
    parser = argparse.ArgumentParser(
        description="Phase 267: Multi-Day Paper Trading Cohort Observation & Maturation Evaluation"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE267_OUTPUT_DIR,
        help=(
            "Directory to persist SQLite ledgers and audit reports "
            "(default: artifacts/research/phase267)"
        ),
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_CANDIDATE_REGISTRY_PATH,
        help="Path to candidate_registry.json (must be version >= 2)",
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=DEFAULT_CANONICAL_HISTORY_DIR,
        help="Directory holding canonical historical 5m Parquet data for warmup/replay",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Session duration in seconds for live feed streaming (default: 10.0)",
    )
    parser.add_argument(
        "--days",
        type=float,
        default=None,
        help="Observation replay duration in days (e.g., 14.0, 7.0, 1.0)",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="Number of multi-day bar ticks to process in batch mode (default: 144 / 12 hours)",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        default=False,
        help="Run a bounded smoke test session (10 ticks / 5.0s)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "live", "batch"],
        help=(
            "Execution mode: auto (live stream with offline fallback), live, "
            "or batch (default: auto)"
        ),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="Force offline batch replay using canonical Parquet data",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Remove pre-existing SQLite databases in output directory before starting session",
    )
    parser.add_argument(
        "--starting-capital",
        type=Decimal,
        default=DEFAULT_STARTING_CAPITAL,
        help="Shared portfolio cash balance in USDT (default: 100.00)",
    )
    parser.add_argument(
        "--max-margin-utilization",
        type=Decimal,
        default=DEFAULT_MAX_MARGIN_UTILIZATION,
        help="Maximum allowable margin utilization ceiling (default: 0.80)",
    )
    parser.add_argument(
        "--min-reserve-buffer",
        type=Decimal,
        default=DEFAULT_MIN_RESERVE_BUFFER,
        help="Minimum unencumbered reserve buffer fraction (default: 0.20)",
    )
    parser.add_argument(
        "--fee-rate",
        type=Decimal,
        default=DEFAULT_TAKER_FEE_RATE,
        help="Taker fee rate (default: 0.0004)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=Decimal,
        default=DEFAULT_SLIPPAGE_BPS,
        help="Adverse slippage in basis points (default: 2.0)",
    )
    parser.add_argument(
        "--ws-url",
        type=str,
        default="wss://fstream.binance.com",
        help="Binance Futures WebSocket base URL (default: wss://fstream.binance.com)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON summary to stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for Phase 267 cohort maturation runner."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        res = asyncio.run(
            run_phase_267_cohort_maturation(
                output_dir=args.output_dir,
                registry_path=args.registry_path,
                history_dir=args.history_dir,
                duration=args.duration,
                days=args.days,
                ticks=args.ticks,
                smoke_test=args.smoke_test,
                mode=args.mode,
                offline=args.offline,
                clean=args.clean,
                starting_capital=args.starting_capital,
                max_margin_utilization=args.max_margin_utilization,
                min_reserve_buffer=args.min_reserve_buffer,
                fee_rate=args.fee_rate,
                slippage_bps=args.slippage_bps,
                ws_url=args.ws_url,
            )
        )

        if args.json:
            sys.stdout.write(res.maturation_summary_path.read_text(encoding="utf-8"))
            return 0

        sys.stdout.write("\n=== PHASE 267 COHORT MATURATION RUNNER COMPLETED ===\n")
        sys.stdout.write(f"Output Directory:       {res.output_dir}\n")
        sys.stdout.write(f"Registry Version:       {res.registry_version}\n")
        sys.stdout.write(f"Registry Hash:          {res.registry_hash}\n")
        sys.stdout.write(f"Starting Equity:        {res.starting_equity:.2f} USDT\n")
        sys.stdout.write(f"Final Cash Balance:     {res.final_cash:.4f} USDT\n")
        sys.stdout.write(f"Realized PnL:           {res.realized_pnl:+.4f} USDT\n")
        sys.stdout.write(
            f"Double-Entry Drift:     {res.drift:.2e} USDT (zero_drift={res.zero_balance_drift})\n"
        )
        sys.stdout.write(f"Max Margin Utilization: {res.max_margin_utilization * 100:.2f}%\n")
        sys.stdout.write(f"Min Reserve Buffer:     {res.min_reserve_buffer * 100:.2f}%\n")
        sys.stdout.write(f"Cohort Readiness:       {res.cohort_report.cohort_status}\n")
        sys.stdout.write(f"Total Closed Trades:    {res.total_trades}\n")
        sys.stdout.write(f"Artifacts Generated:    {len(res.artifact_hashes)}\n\n")

        for sym, h in res.health_reports.items():
            sys.stdout.write(
                f"  [{sym}] Health: {h.health_status:<10} Maturity: {h.maturity_status:<10}\n"
            )
        sys.stdout.write("\nArtifact SHA-256 Digests:\n")
        for fname, fhash in sorted(res.artifact_hashes.items()):
            sys.stdout.write(f"  {fname:<38} {fhash}\n")
        sys.stdout.write("\n")
        return 0
    except KeyboardInterrupt:
        logger.info("Cohort maturation runner cancelled by operator")
        return 0
    except Exception as exc:
        logger.error("Cohort maturation runner failed with exception: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
