"""Validation logic and models for Kainode paper daemon preflight diagnostic tooling."""

from __future__ import annotations

import gc
import json
import os
import re
import sqlite3
import stat
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import Field, model_validator

from .data.quality import canonicalize_bars
from .domain.contracts import DomainModel, PaperExecutionRequest
from .paper.cohort import summarize_paper_cohort
from .paper.health import aggregate_paper_health
from .paper.lifecycle import PaperLifecycleTelemetry, mark_paper_position
from .paper.observation import (
    PaperObservation,
    PaperObservationBinding,
    observe_paper_ledger,
)
from .paper.reconciliation import reconcile_paper_positions
from .paper.runtime import PaperRuntime
from .paper.safety import PaperActionApproval, PaperSafetyEvidence
from .paper.sqlite_ledger import SqlitePaperLedger
from .paper.sqlite_lifecycle import SqlitePaperLifecycle
from .paper.sqlite_observation import SqlitePaperObservations

DEFAULT_STORAGE_DIR = Path("/opt/autonomous-futures-bot/artifacts/paper")
DEFAULT_STARTING_EQUITY = Decimal("100.00")
DEFAULT_BARS = 200

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _sanitize_error_text(text: str) -> str:
    """Strip potential secret tokens or sensitive values from error text."""
    return _SECRET_PATTERN.sub("[REDACTED_SECRET]", text)


class PaperHostEnvironmentReport(DomainModel):
    platform: str
    os_name: str | None = None
    python_version: str
    python_version_valid: bool
    current_uid: int
    current_user: str
    user_valid: bool
    in_systemd: bool
    validation_error: str | None = None


class PaperStorageDirectoryReport(DomainModel):
    path: str
    exists: bool
    is_directory: bool
    mode_octal: str | None = None
    mode_valid: bool
    owner_uid: int | None = None
    owner_name: str | None = None
    owner_valid: bool
    read_write_capable: bool
    validation_error: str | None = None


class PaperOfflineSafetyReport(DomainModel):
    exchange_access: Literal[False] = False
    execution_authority: Literal[False] = False
    orders: Literal[0] = 0
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    live_credentials_forbidden: Literal[True] = True
    credentials_detected: tuple[str, ...] = ()
    validation_error: str | None = None


class PaperSmokeTestReport(DomainModel):
    executed: bool
    total_bars: int
    trades_executed: int
    positions_reconciled: bool
    balance_reconciled: bool
    health_status: str | None = None
    cohort_status: str | None = None
    validation_error: str | None = None


class PaperPreflightReport(DomainModel):
    ready: bool
    status: Literal["ready_for_paper_daemon", "blocked"]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    host_environment: PaperHostEnvironmentReport
    storage_directory: PaperStorageDirectoryReport
    offline_safety: PaperOfflineSafetyReport
    smoke_test: PaperSmokeTestReport
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_consistency(self) -> PaperPreflightReport:
        if self.ready and self.status != "ready_for_paper_daemon":
            raise ValueError("ready report must have status 'ready_for_paper_daemon'")
        if self.ready and self.errors:
            raise ValueError("ready report cannot have errors")
        if not self.ready and self.status != "blocked":
            raise ValueError("unready report must have status 'blocked'")
        return self


class SharedMarginAccount:
    """Manages single pooled portfolio margin, dynamic leverage, and capital allocation."""

    def __init__(
        self,
        starting_capital: Decimal = DEFAULT_STARTING_EQUITY,
        max_utilization: Decimal = Decimal("0.80"),
        base_allocation_fraction: Decimal = Decimal("0.20"),
    ) -> None:
        self.starting_capital = starting_capital
        self.max_utilization = max_utilization
        self.base_allocation_fraction = base_allocation_fraction
        self.cash = starting_capital
        self._locked_margin_by_trade: dict[str, Decimal] = {}
        self._trade_leverage: dict[str, Decimal] = {}
        self.peak_portfolio_equity = starting_capital
        self.max_observed_utilization = Decimal("0.0")

    def total_locked_margin(self) -> Decimal:
        return sum(self._locked_margin_by_trade.values(), Decimal("0"))

    def current_equity(self, active_unrealized_pnl: Decimal = Decimal("0")) -> Decimal:
        return self.cash + active_unrealized_pnl

    def margin_utilization(self, equity: Decimal) -> Decimal:
        if equity <= 0:
            return Decimal("1.0")
        return self.total_locked_margin() / equity

    def available_margin(self, equity: Decimal) -> Decimal:
        max_allowed = equity * self.max_utilization
        locked = self.total_locked_margin()
        return max(Decimal("0"), max_allowed - locked)

    def allocate_order(
        self,
        symbol: str,
        confidence: Decimal,
        mark_price: Decimal,
        current_equity: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal] | None:
        """Calculate margin allocation, confidence-scaled dynamic leverage, and trade quantity."""
        if current_equity <= 0:
            return None

        base_margin = current_equity * self.base_allocation_fraction
        locked_after = self.total_locked_margin() + base_margin
        utilization_after = locked_after / current_equity

        # Utilization cap <= 80% (preserves >= 20% cash reserve buffer)
        if utilization_after > self.max_utilization:
            return None

        # Cash buffer for taker fees
        if self.cash < base_margin * Decimal("0.005"):
            return None

        leverage = calculate_dynamic_leverage(confidence)
        notional = base_margin * leverage
        raw_quantity = notional / mark_price
        quantity = Decimal(f"{raw_quantity:.6f}")
        if quantity <= 0:
            return None

        return base_margin, leverage, quantity

    def record_open(
        self,
        trade_id: str,
        margin_allocated: Decimal,
        leverage: Decimal,
        entry_fee: Decimal,
        equity: Decimal,
    ) -> None:
        self._locked_margin_by_trade[trade_id] = margin_allocated
        self._trade_leverage[trade_id] = leverage
        self.cash -= entry_fee
        current_util = self.margin_utilization(equity)
        if current_util > self.max_observed_utilization:
            self.max_observed_utilization = current_util

    def record_close(self, trade_id: str, gross_pnl: Decimal, exit_fee: Decimal) -> None:
        if trade_id in self._locked_margin_by_trade:
            del self._locked_margin_by_trade[trade_id]
        if trade_id in self._trade_leverage:
            del self._trade_leverage[trade_id]
        self.cash += gross_pnl - exit_fee


def calculate_dynamic_leverage(confidence: Decimal) -> Decimal:
    """Scale dynamic leverage linearly from 1.0x to 3.0x based on confidence [0.0, 1.0]."""
    clamped = min(Decimal("1.0"), max(Decimal("0.0"), confidence))
    return Decimal("1.0") + clamped * Decimal("2.0")


def generate_deterministic_5m_bars(
    start: datetime = datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    total_bars: int = 200,
) -> pd.DataFrame:
    """Generate deterministic 5m OHLC bars producing mean-reversion signals for smoke testing."""
    if total_bars < 30:
        raise ValueError(f"total_bars must be at least 30, got {total_bars}")

    prices: list[float] = []
    # Build deterministic price series around 0.150:
    # 0..9: flat baseline at 0.150
    # 10..14: dip to 0.138 (entry dip)
    # 15..19: bounce to 0.155 (exit bounce)
    # 20..total_bars-1: return to 0.150
    for i in range(total_bars):
        if i < 10:
            prices.append(0.150)
        elif i == 10:
            prices.append(0.145)
        elif i == 11:
            prices.append(0.141)
        elif i == 12:
            prices.append(0.138)
        elif i == 13:
            prices.append(0.139)
        elif i == 14:
            prices.append(0.142)
        elif i == 15:
            prices.append(0.147)
        elif i == 16:
            prices.append(0.151)
        elif i == 17:
            prices.append(0.155)
        elif i == 18:
            prices.append(0.154)
        elif i == 19:
            prices.append(0.151)
        else:
            prices.append(0.150)

    timestamps = [start + timedelta(minutes=5 * i) for i in range(total_bars)]
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [Decimal(str(round(p, 5))) for p in prices],
            "high": [Decimal(str(round(p + 0.0005, 5))) for p in prices],
            "low": [Decimal(str(round(p - 0.0005, 5))) for p in prices],
            "close": [Decimal(str(round(p, 5))) for p in prices],
        }
    )
    return canonicalize_bars(df, interval=timedelta(minutes=5))


def validate_paper_host_environment(
    *,
    stat_fn: Callable[[Path], os.stat_result] | None = None,
    platform: str = sys.platform,
    allowed_uids: set[int] | None = None,
    skip_host_check: bool = False,
) -> PaperHostEnvironmentReport:
    """Verify Python >= 3.12, Linux OS baseline, and unprivileged user afbot."""
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ver_valid = sys.version_info >= (3, 12)

    os_name: str | None = None
    if platform == "linux":
        try:
            os_release = Path("/etc/os-release")
            if os_release.exists():
                for line in os_release.read_text(encoding="utf-8").splitlines():
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip("\"'")
                        break
        except OSError:
            pass

    in_systemd = "INVOCATION_ID" in os.environ or "JOURNAL_STREAM" in os.environ

    if platform == "win32" and stat_fn is None:
        current_uid = 1001
        current_user = "afbot" if skip_host_check else "windows_user"
        user_valid = True if skip_host_check else True
    else:
        if stat_fn is not None:
            st = stat_fn(Path("."))
            current_uid = st.st_uid
        else:
            current_uid = os.getuid() if hasattr(os, "getuid") else 1001

        uids: set[int] = {1000, 1001} if allowed_uids is None else set(allowed_uids)
        current_user = (
            "root" if current_uid == 0 else ("afbot" if current_uid in (1000, 1001) else "unknown")
        )

        try:
            import importlib

            pwd_mod: Any = importlib.import_module("pwd")
            try:
                afbot_entry = pwd_mod.getpwnam("afbot")
                uids.add(afbot_entry.pw_uid)
                if current_uid == afbot_entry.pw_uid:
                    current_user = "afbot"
            except KeyError, AttributeError:
                pass
            if current_user == "unknown":
                try:
                    current_user = pwd_mod.getpwuid(current_uid).pw_name
                except KeyError, AttributeError:
                    current_user = f"uid_{current_uid}"
        except ImportError:
            pass

        # Execution must be strictly non-root and match unprivileged afbot
        user_valid = current_uid != 0 and (current_uid in uids or current_user == "afbot")

    errs: list[str] = []
    if not py_ver_valid:
        errs.append(f"unsupported_python_version_{py_ver}_must_be_gte_3.12")
    if not skip_host_check:
        if platform != "linux":
            errs.append(f"unsupported_platform_{platform}_must_be_linux")
        if not user_valid:
            errs.append(f"invalid_execution_user_{current_user}_uid_{current_uid}_must_be_afbot")

    return PaperHostEnvironmentReport(
        platform=platform,
        os_name=os_name,
        python_version=py_ver,
        python_version_valid=py_ver_valid,
        current_uid=current_uid,
        current_user=current_user,
        user_valid=user_valid,
        in_systemd=in_systemd,
        validation_error="; ".join(errs) if errs else None,
    )


def validate_paper_storage_directory(
    path: Path,
    *,
    stat_fn: Callable[[Path], os.stat_result] | None = None,
    platform: str = sys.platform,
    allowed_uids: set[int] | None = None,
) -> PaperStorageDirectoryReport:
    """Verify storage directory existence, mode (750/700), owner (root/afbot), and RW probe."""
    path_str = str(path)
    if not path.exists():
        return PaperStorageDirectoryReport(
            path=path_str,
            exists=False,
            is_directory=False,
            mode_valid=False,
            owner_valid=False,
            read_write_capable=False,
            validation_error=f"storage_directory_missing: directory not found at {path_str}",
        )

    if not path.is_dir() or path.is_symlink():
        return PaperStorageDirectoryReport(
            path=path_str,
            exists=True,
            is_directory=False,
            mode_valid=False,
            owner_valid=False,
            read_write_capable=False,
            validation_error=(
                f"storage_directory_not_a_directory: path is not a directory at {path_str}"
            ),
        )

    st = stat_fn(path) if stat_fn is not None else path.stat()
    mode_int = stat.S_IMODE(st.st_mode)
    mode_octal = oct(mode_int)

    owner_uid: int | None
    owner_name: str | None
    if platform == "win32" and stat_fn is None:
        mode_valid = True
        owner_uid = getattr(st, "st_uid", 1001)
        owner_name = "windows_user"
        owner_valid = True
    else:
        # Strictly mode 0o750 or 0o700
        mode_valid = mode_int in (0o750, 0o700)
        owner_uid = st.st_uid
        uids: set[int] = {0, 1000, 1001} if allowed_uids is None else set(allowed_uids)
        owner_name = "root" if owner_uid == 0 else ("afbot" if owner_uid in (1000, 1001) else None)

        try:
            import importlib

            pwd_mod: Any = importlib.import_module("pwd")
            try:
                afbot_entry = pwd_mod.getpwnam("afbot")
                uids.add(afbot_entry.pw_uid)
                if owner_uid == afbot_entry.pw_uid:
                    owner_name = "afbot"
            except KeyError, AttributeError:
                pass
            if owner_name is None:
                try:
                    owner_name = pwd_mod.getpwuid(owner_uid).pw_name
                except KeyError, AttributeError:
                    owner_name = f"uid_{owner_uid}"
        except ImportError:
            pass

        owner_valid = owner_uid in uids or owner_name in ("root", "afbot")

    errs: list[str] = []
    if not mode_valid:
        errs.append(f"insecure_directory_mode_{mode_octal}_expected_0o750_or_0o700")
    if not owner_valid:
        errs.append(f"invalid_directory_owner_{owner_name or owner_uid}_expected_root_or_afbot")

    # Atomic sentinel write/read/unlink test
    sentinel = path / f".preflight_probe_{uuid.uuid4().hex}.tmp"
    canary = "afbot-paper-preflight-probe"
    read_write_capable = False
    try:
        sentinel.write_text(canary, encoding="utf-8")
        read_back = sentinel.read_text(encoding="utf-8")
        read_write_capable = read_back == canary
        sentinel.unlink(missing_ok=True)
    except (OSError, PermissionError) as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        read_write_capable = False
        errs.append(f"storage_directory_read_only_or_not_writable: {sanitized}")

    return PaperStorageDirectoryReport(
        path=path_str,
        exists=True,
        is_directory=True,
        mode_octal=mode_octal,
        mode_valid=mode_valid,
        owner_uid=owner_uid,
        owner_name=owner_name,
        owner_valid=owner_valid,
        read_write_capable=read_write_capable,
        validation_error="; ".join(errs) if errs else None,
    )


def validate_paper_offline_safety(
    *,
    env: Mapping[str, str] | None = None,
    credentials_dir: Path | None = None,
) -> PaperOfflineSafetyReport:
    """Verify zero live Binance/exchange credentials in environment or filesystem."""
    environ = env if env is not None else os.environ
    detected: list[str] = []

    for key in environ:
        k_upper = key.upper()
        if any(token in k_upper for token in ("BINANCE", "EXCHANGE", "API_KEY", "API_SECRET")):
            detected.append(f"env:{key}")

    if credentials_dir is not None and credentials_dir.is_dir():
        try:
            for item in credentials_dir.iterdir():
                name_lower = item.name.lower()
                if any(token in name_lower for token in ("binance", "exchange", "fapi")):
                    detected.append(f"file:{item.name}")
        except OSError:
            pass

    detected_tuple = tuple(sorted(detected))
    err = (
        "exchange_credential_contamination: exchange credentials detected: "
        f"{', '.join(detected_tuple)}"
        if detected_tuple
        else None
    )

    return PaperOfflineSafetyReport(
        exchange_access=False,
        execution_authority=False,
        orders=0,
        promotion_state="unpromoted",
        paper_activation=False,
        live_credentials_forbidden=True,
        credentials_detected=detected_tuple,
        validation_error=err,
    )


def execute_paper_smoke_test(
    storage_dir: Path,
    *,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
    bars: int = DEFAULT_BARS,
    symbol: str = "DOGEUSDT",
) -> PaperSmokeTestReport:
    """Execute bounded synthetic bar simulation under 100 USDT shared margin baseline."""
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = storage_dir / "paper-ledger.sqlite3"
        lifecycle_path = storage_dir / "paper-lifecycle.sqlite3"
        observation_path = storage_dir / "paper-observations.sqlite3"

        gc.collect()
        for p in (ledger_path, lifecycle_path, observation_path):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    try:
                        conn = sqlite3.connect(p)
                        tables = [
                            row[0]
                            for row in conn.execute(
                                "SELECT name FROM sqlite_master WHERE type = 'table'"
                            ).fetchall()
                        ]
                        for table in tables:
                            conn.execute(f"DELETE FROM {table}")
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass

        ledger_store = SqlitePaperLedger(ledger_path)
        lifecycle_store = SqlitePaperLifecycle(lifecycle_path)
        observation_store = SqlitePaperObservations(observation_path)
        runtime = PaperRuntime(ledger_store)

        margin_account = SharedMarginAccount(starting_capital=starting_equity)
        fee_rate = Decimal("0.0004")
        slippage_bps = Decimal("2")

        candidate_id = "cand-0000000000000000000000000000000000000000000000000000000000000001"
        candidate_artifact_hash = "0" * 64
        qualification_hash = "1" * 64

        evidence = PaperSafetyEvidence(
            candidate_id=candidate_id,
            candidate_artifact_hash=candidate_artifact_hash,
            qualification_hash=qualification_hash,
            qualification_decision="qualified",
            zero_oos_liquidations=True,
        )
        binding = PaperObservationBinding(
            candidate_id=candidate_id,
            candidate_artifact_hash=candidate_artifact_hash,
        )

        bars_df = generate_deterministic_5m_bars(
            start=datetime(2026, 1, 1, 0, 0, tzinfo=UTC), total_bars=bars
        )
        trade_id = "smoke-trade-0001"
        open_executed = False
        close_executed = False
        active_open_entry = None
        peak_pnl = Decimal("0")
        observations: list[PaperObservation] = []
        lifecycle_marks: list[PaperLifecycleTelemetry] = []

        for idx, row in bars_df.iterrows():
            bar_ts: datetime = row["timestamp"]
            bar_close: Decimal = row["close"]

            if not open_executed and idx >= 10:
                alloc = margin_account.allocate_order(
                    symbol=symbol,
                    confidence=Decimal("0.75"),
                    mark_price=bar_close,
                    current_equity=margin_account.cash,
                )
                if alloc is not None:
                    margin_alloc, leverage, quantity = alloc
                    open_req = PaperExecutionRequest(
                        candidate_id=candidate_id,
                        candidate_artifact_hash=candidate_artifact_hash,
                        qualified_symbols=(symbol,),
                        symbol=symbol,
                        side="LONG",
                        mark_price=bar_close,
                        quantity=quantity,
                        fee_rate=fee_rate,
                        slippage_bps=slippage_bps,
                    )
                    approval = PaperActionApproval(
                        approval_id="apprv-smoke-open-0001",
                        candidate_id=candidate_id,
                        candidate_artifact_hash=candidate_artifact_hash,
                        trade_id=trade_id,
                        action="open",
                        approved_at=bar_ts,
                        expires_at=bar_ts + timedelta(minutes=10),
                    )
                    res = runtime.open(
                        open_req, evidence, approval, trade_id=trade_id, occurred_at=bar_ts
                    )
                    if res.status == "opened" and res.entry_fee is not None:
                        margin_account.record_open(
                            trade_id=trade_id,
                            margin_allocated=margin_alloc,
                            leverage=leverage,
                            entry_fee=res.entry_fee,
                            equity=margin_account.cash,
                        )
                        open_executed = True
                        active_open_entry = ledger_store.load().open_positions()[0]
                        mark = mark_paper_position(
                            active_open_entry,
                            mark_price=bar_close,
                            marked_at=bar_ts,
                            previous_peak_pnl=peak_pnl,
                        )
                        peak_pnl = mark.peak_pnl
                        lifecycle_store.append(mark)
                        lifecycle_marks.append(mark)
            elif open_executed and not close_executed:
                assert active_open_entry is not None
                mark = mark_paper_position(
                    active_open_entry,
                    mark_price=bar_close,
                    marked_at=bar_ts,
                    previous_peak_pnl=peak_pnl,
                )
                peak_pnl = mark.peak_pnl
                lifecycle_store.append(mark)
                lifecycle_marks.append(mark)

                if idx >= 17 or idx == len(bars_df) - 1:
                    close_req = PaperExecutionRequest(
                        candidate_id=candidate_id,
                        candidate_artifact_hash=candidate_artifact_hash,
                        qualified_symbols=(symbol,),
                        symbol=symbol,
                        side="LONG",
                        mark_price=bar_close,
                        quantity=active_open_entry.quantity,
                        fee_rate=fee_rate,
                        slippage_bps=slippage_bps,
                    )
                    approval = PaperActionApproval(
                        approval_id="apprv-smoke-close-0001",
                        candidate_id=candidate_id,
                        candidate_artifact_hash=candidate_artifact_hash,
                        trade_id=trade_id,
                        action="close",
                        approved_at=bar_ts,
                        expires_at=bar_ts + timedelta(minutes=10),
                    )
                    close_res = runtime.close(
                        close_req,
                        evidence,
                        approval,
                        trade_id=trade_id,
                        exit_mark_price=bar_close,
                        occurred_at=bar_ts,
                    )
                    if (
                        close_res.status == "closed"
                        and close_res.gross_pnl is not None
                        and close_res.exit_fee is not None
                    ):
                        margin_account.record_close(
                            trade_id=trade_id,
                            gross_pnl=close_res.gross_pnl,
                            exit_fee=close_res.exit_fee,
                        )
                        close_executed = True
                        active_open_entry = None

            if idx == len(bars_df) - 1:
                obs = observe_paper_ledger(
                    ledger_store.load(),
                    candidate_id=candidate_id,
                    candidate_artifact_hash=candidate_artifact_hash,
                    starting_equity=starting_equity,
                    previous_peak_equity=starting_equity,
                    mark_prices={symbol: bar_close},
                    observed_at=bar_ts,
                )
                observation_store.append(obs)
                observations.append(obs)

        # Reconcile positions and balance
        reconcile_res = reconcile_paper_positions(ledger_store.load(), runtime_open_trade_ids=())
        positions_reconciled = reconcile_res.reconciled

        ledger = ledger_store.load()
        net_pnl = sum(
            (e.net_pnl for e in ledger.entries if e.event == "close" and e.net_pnl is not None),
            Decimal("0"),
        )
        expected_cash = starting_equity + net_pnl
        balance_reconciled = margin_account.cash == expected_cash

        trades_executed = 1 if (open_executed and close_executed) else 0

        terminal_ts = bars_df.iloc[-1]["timestamp"]
        health_report = aggregate_paper_health(
            observations=observations,
            lifecycle_marks=lifecycle_marks,
            candidate_id=candidate_id,
            candidate_artifact_hash=candidate_artifact_hash,
            as_of=terminal_ts,
            max_mark_age_seconds=86400,
            required_days=1,
        )
        cohort_report = summarize_paper_cohort(reports=[health_report], expected_bindings=[binding])

        # Write telemetry JSON reports to storage_dir
        (storage_dir / "paper-health-report.json").write_text(
            health_report.model_dump_json(indent=2), encoding="utf-8"
        )
        (storage_dir / "paper-cohort-readiness-report.json").write_text(
            cohort_report.model_dump_json(indent=2), encoding="utf-8"
        )
        summary_payload = {
            "total_bars": bars,
            "trades_executed": trades_executed,
            "starting_equity": str(starting_equity),
            "final_cash": str(margin_account.cash),
            "net_pnl": str(net_pnl),
            "positions_reconciled": positions_reconciled,
            "balance_reconciled": balance_reconciled,
            "health_status": health_report.health_status,
            "cohort_status": cohort_report.cohort_status,
        }
        (storage_dir / "paper-summary.json").write_text(
            json.dumps(summary_payload, indent=2), encoding="utf-8"
        )

        return PaperSmokeTestReport(
            executed=True,
            total_bars=bars,
            trades_executed=trades_executed,
            positions_reconciled=positions_reconciled,
            balance_reconciled=balance_reconciled,
            health_status=health_report.health_status,
            cohort_status=cohort_report.cohort_status,
            validation_error=None,
        )
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        return PaperSmokeTestReport(
            executed=False,
            total_bars=bars,
            trades_executed=0,
            positions_reconciled=False,
            balance_reconciled=False,
            validation_error=f"smoke_test_failure: {sanitized}",
        )


def validate_paper_preflight(
    *,
    storage_dir: Path = DEFAULT_STORAGE_DIR,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
    bars: int = DEFAULT_BARS,
    smoke_test: bool = True,
    skip_host_check: bool = False,
    stat_fn: Callable[[Path], os.stat_result] | None = None,
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    allowed_uids: set[int] | None = None,
    credentials_dir: Path | None = None,
) -> PaperPreflightReport:
    """Execute complete paper preflight verification returning structured PaperPreflightReport."""
    errors: list[str] = []
    warnings: list[str] = []

    host_report = validate_paper_host_environment(
        stat_fn=stat_fn,
        platform=platform,
        allowed_uids=allowed_uids,
        skip_host_check=skip_host_check,
    )
    if host_report.validation_error:
        errors.append(host_report.validation_error)

    storage_report = validate_paper_storage_directory(
        path=storage_dir,
        stat_fn=stat_fn,
        platform=platform,
        allowed_uids=allowed_uids,
    )
    if storage_report.validation_error:
        errors.append(storage_report.validation_error)

    cred_scan_dir = (
        credentials_dir
        if credentials_dir is not None
        else (storage_dir / "credentials" if (storage_dir / "credentials").is_dir() else None)
    )
    safety_report = validate_paper_offline_safety(
        env=env,
        credentials_dir=cred_scan_dir,
    )
    if safety_report.validation_error:
        errors.append(safety_report.validation_error)

    if smoke_test:
        if (
            storage_report.exists
            and storage_report.is_directory
            and storage_report.read_write_capable
        ):
            smoke_report = execute_paper_smoke_test(
                storage_dir=storage_dir,
                starting_equity=starting_equity,
                bars=bars,
            )
            if smoke_report.validation_error:
                errors.append(smoke_report.validation_error)
            if not smoke_report.positions_reconciled:
                errors.append("smoke_test_positions_unreconciled")
            if not smoke_report.balance_reconciled:
                errors.append("smoke_test_balance_unreconciled")
        else:
            smoke_err = "smoke_test_aborted: storage directory invalid or not writable"
            smoke_report = PaperSmokeTestReport(
                executed=False,
                total_bars=bars,
                trades_executed=0,
                positions_reconciled=False,
                balance_reconciled=False,
                validation_error=smoke_err,
            )
            errors.append(smoke_err)
    else:
        smoke_report = PaperSmokeTestReport(
            executed=False,
            total_bars=0,
            trades_executed=0,
            positions_reconciled=True,
            balance_reconciled=True,
        )

    ready = len(errors) == 0
    status: Literal["ready_for_paper_daemon", "blocked"] = (
        "ready_for_paper_daemon" if ready else "blocked"
    )

    return PaperPreflightReport(
        ready=ready,
        status=status,
        errors=tuple(errors),
        warnings=tuple(warnings),
        host_environment=host_report,
        storage_directory=storage_report,
        offline_safety=safety_report,
        smoke_test=smoke_report,
        metadata={
            "timestamp": datetime.now(UTC).isoformat(),
            "storage_dir": str(storage_dir),
            "starting_equity": str(starting_equity),
            "bars": bars,
            "smoke_test_requested": smoke_test,
        },
    )


__all__ = [
    "DEFAULT_BARS",
    "DEFAULT_STARTING_EQUITY",
    "DEFAULT_STORAGE_DIR",
    "PaperHostEnvironmentReport",
    "PaperOfflineSafetyReport",
    "PaperPreflightReport",
    "PaperSmokeTestReport",
    "PaperStorageDirectoryReport",
    "SharedMarginAccount",
    "calculate_dynamic_leverage",
    "execute_paper_smoke_test",
    "generate_deterministic_5m_bars",
    "validate_paper_host_environment",
    "validate_paper_offline_safety",
    "validate_paper_preflight",
    "validate_paper_storage_directory",
]
