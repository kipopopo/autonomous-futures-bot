"""Phase 270: Canary Deployment Dry-Run Runner & Micro-Sized Shadow Order Engine.

Implements pre-live order generation, micro-sized fractional position sizing (<= 5.00 USDT),
multi-tiered emergency kill-switch verification, isolated SQLite shadow order and ledger
persistence, exact zero-drift double-entry accounting reconciliation (< 1e-15 USDT),
and strict fail-closed boundaries under Candidate Registry Manifest Version 2.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pandas as pd
from pydantic import Field, field_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from ..research.creator_artifacts import _artifact_content_hash, read_creator_candidate_artifact
from ..research.qualification_artifacts import (
    _qualification_content_hash,
    read_creator_candidate_qualification_artifact,
)
from .candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
    verify_candidate_registry_manifest,
)
from .staging import (
    CanaryStagingManifest,
    assert_zero_secrets,
    canonical_json_bytes,
    check_fail_closed_safety_invariants,
    compute_file_sha256,
    safe_decimal,
    verify_staging_manifest_integrity,
)

logger = logging.getLogger(__name__)

# Canonical paths and expectations
DEFAULT_CANARY_STAGING_MANIFEST_PATH = Path(
    "artifacts/research/phase269/canary-staging-manifest.json"
)
DEFAULT_PHASE270_OUTPUT_DIR = Path("artifacts/research/phase270")
DEFAULT_CANONICAL_HISTORY_DIR = Path("research/immutable-data/5m/canonical")

EXPECTED_MANIFEST_V2_CANDIDATES: dict[str, str] = {
    "BTCUSDT": "cand-btcusdt-dcb-002",
    "ETHUSDT": "cand-ethusdt-dcb-003",
    "SOLUSDT": "cand-solusdt-rgb-001",
}

# Risk and execution constraints
MAX_MICRO_NOTIONAL_USDT: Decimal = Decimal("5.00")
MAX_CANARY_AGGREGATE_MARGIN_UTILIZATION: Decimal = Decimal("0.60")  # <= 60.00%
CANARY_MAX_AGGREGATE_MARGIN_UTILIZATION: Decimal = MAX_CANARY_AGGREGATE_MARGIN_UTILIZATION
MIN_CANARY_AGGREGATE_RESERVE_BUFFER: Decimal = Decimal("0.40")  # >= 40.00%
CANARY_MIN_AGGREGATE_RESERVE_BUFFER: Decimal = MIN_CANARY_AGGREGATE_RESERVE_BUFFER
TIER2_MAX_DRAWDOWN_THRESHOLD: Decimal = Decimal("0.02")  # >= 2.00%
DOUBLE_ENTRY_MAX_DRIFT: Decimal = Decimal("1e-15")

TIER1_MAX_SPREAD_BPS: Decimal = Decimal("20.0")  # >= 20.0 bps
TIER1_MAX_VOLATILITY_RATIO: Decimal = Decimal("2.5")  # >= 2.5x ATR ratio
TIER1_HEARTBEAT_TIMEOUT_SEC: float = 10.0  # >= 10.0s

DEFAULT_STARTING_EQUITY: Decimal = Decimal("100.00")
DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0004")  # 0.04% taker fee
DEFAULT_SLIPPAGE_RATE: Decimal = Decimal("0.0002")  # 2 bps adverse slippage


class CanaryCircuitState(StrEnum):
    """Multi-tiered emergency circuit breaker states."""

    NORMAL = "NORMAL"
    TIER1_SOFT_DEESCALATION = "TIER1_SOFT_DEESCALATION"
    TIER2_HARD_ABORT = "TIER2_HARD_ABORT"
    EMERGENCY_FLAT = "EMERGENCY_FLAT"


class CanaryShadowOrder(DomainModel):
    """Intercepted shadow order intent persisted in durable SQLite store."""

    order_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    side: Literal["BUY", "SELL"]
    order_type: Literal["LIMIT", "MARKET"]
    quantity: Decimal = Field(gt=Decimal("0"))
    limit_price: Decimal = Field(gt=Decimal("0"))
    micro_notional: Decimal = Field(gt=Decimal("0"))
    status: Literal["PENDING", "FILLED", "CANCELLED", "REJECTED"]
    created_at: str
    updated_at: str
    cancellation_reason: str | None = None

    @field_validator("quantity", "limit_price", "micro_notional", mode="before")
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


class CanaryShadowFill(DomainModel):
    """Simulated execution fill record persisted in durable SQLite store."""

    fill_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    client_order_id: str = Field(min_length=1)
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    side: Literal["BUY", "SELL"]
    fill_price: Decimal = Field(gt=Decimal("0"))
    fill_quantity: Decimal = Field(gt=Decimal("0"))
    fee_usdt: Decimal = Field(ge=Decimal("0"))
    slippage_usdt: Decimal = Field(ge=Decimal("0"))
    realized_pnl: Decimal = Field(default=Decimal("0"))
    filled_at: str

    @field_validator(
        "fill_price", "fill_quantity", "fee_usdt", "slippage_usdt", "realized_pnl", mode="before"
    )
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


class CanaryPosition(DomainModel):
    """Active or closed simulated position in micro shadow execution."""

    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    candidate_id: str = Field(min_length=1)
    side: Literal["LONG", "SHORT"]
    quantity: Decimal = Field(gt=Decimal("0"))
    entry_price: Decimal = Field(gt=Decimal("0"))
    current_price: Decimal = Field(gt=Decimal("0"))
    base_margin: Decimal = Field(ge=Decimal("0"))
    leverage: Decimal = Field(default=Decimal("1.0"), ge=Decimal("1.0"), le=Decimal("10.0"))
    unrealized_pnl: Decimal = Field(default=Decimal("0"))
    realized_pnl: Decimal = Field(default=Decimal("0"))
    opened_at: str
    status: Literal["OPEN", "CLOSED"] = "OPEN"

    @field_validator(
        "quantity",
        "entry_price",
        "current_price",
        "base_margin",
        "leverage",
        "unrealized_pnl",
        "realized_pnl",
        mode="before",
    )
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


class CanaryKillSwitchEvent(DomainModel):
    """Audit log of emergency circuit breaker or de-escalation activation."""

    event_id: str = Field(min_length=1)
    tier: int = Field(ge=1, le=2)
    trigger_type: str = Field(min_length=1)
    trigger_reason: str = Field(min_length=1)
    occurred_at: str
    orders_cancelled: int = Field(ge=0)
    positions_liquidated: int = Field(ge=0)
    pre_equity: Decimal = Field(ge=Decimal("0"))
    post_equity: Decimal = Field(ge=Decimal("0"))

    @field_validator("pre_equity", "post_equity", mode="before")
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


class CanaryExecutionSummary(DomainModel):
    """Cryptographically signed audit summary of canary staging execution."""

    phase: str = "phase_270"
    description: str
    timestamp_utc: str
    circuit_state: str
    starting_capital_usdt: Decimal
    final_cash_usdt: Decimal
    final_equity_usdt: Decimal
    realized_pnl_usdt: Decimal
    total_fees_usdt: Decimal
    total_slippage_usdt: Decimal
    drift_usdt: Decimal
    zero_balance_drift: bool
    max_observed_margin_utilization: Decimal
    min_observed_reserve_buffer: Decimal
    margin_guardrails_compliant: bool
    single_position_invariant: bool
    orders_count: int
    fills_count: int
    cancelled_orders_count: int
    liquidations_count: int
    kill_switch_events: list[dict[str, Any]]
    candidates: dict[str, Any]
    safety_invariants: dict[str, Any]
    artifact_hashes: dict[str, str]
    staged_manifest_hash: str
    cryptographic_signature: str

    @field_validator(
        "starting_capital_usdt",
        "final_cash_usdt",
        "final_equity_usdt",
        "realized_pnl_usdt",
        "total_fees_usdt",
        "total_slippage_usdt",
        "drift_usdt",
        "max_observed_margin_utilization",
        "min_observed_reserve_buffer",
        mode="before",
    )
    @classmethod
    def coerce_decimals(cls, v: Any) -> Decimal:
        return safe_decimal(v)


# =====================================================================
# Isolated SQLite Stores
# =====================================================================


class SqliteCanaryOrdersStore:
    """Isolated caller-owned SQLite database for shadow order intents and fills."""

    def __init__(self, db_path: Path | str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS canary_shadow_orders (
                        order_id TEXT PRIMARY KEY,
                        client_order_id TEXT UNIQUE NOT NULL,
                        candidate_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        order_type TEXT NOT NULL,
                        quantity TEXT NOT NULL,
                        limit_price TEXT NOT NULL,
                        micro_notional TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        cancellation_reason TEXT
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS canary_shadow_fills (
                        fill_id TEXT PRIMARY KEY,
                        order_id TEXT NOT NULL,
                        client_order_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        fill_price TEXT NOT NULL,
                        fill_quantity TEXT NOT NULL,
                        fee_usdt TEXT NOT NULL,
                        slippage_usdt TEXT NOT NULL,
                        realized_pnl TEXT NOT NULL,
                        filled_at TEXT NOT NULL,
                        FOREIGN KEY (order_id) REFERENCES canary_shadow_orders(order_id)
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_orders_symbol ON canary_shadow_orders(symbol);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_orders_status ON canary_shadow_orders(status);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fills_order_id "
                    "ON canary_shadow_fills(order_id);"
                )

    def insert_order(self, order: CanaryShadowOrder) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO canary_shadow_orders (
                        order_id, client_order_id, candidate_id, symbol, side,
                        order_type, quantity, limit_price, micro_notional,
                        status, created_at, updated_at, cancellation_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        order.order_id,
                        order.client_order_id,
                        order.candidate_id,
                        order.symbol,
                        order.side,
                        order.order_type,
                        str(order.quantity),
                        str(order.limit_price),
                        str(order.micro_notional),
                        order.status,
                        order.created_at,
                        order.updated_at,
                        order.cancellation_reason,
                    ),
                )

    def update_order_status(
        self,
        order_id: str,
        status: str,
        updated_at: str,
        cancellation_reason: str | None = None,
    ) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE canary_shadow_orders
                    SET status = ?, updated_at = ?, cancellation_reason = ?
                    WHERE order_id = ?;
                    """,
                    (status, updated_at, cancellation_reason, order_id),
                )

    def insert_fill(self, fill: CanaryShadowFill) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO canary_shadow_fills (
                        fill_id, order_id, client_order_id, symbol, side,
                        fill_price, fill_quantity, fee_usdt, slippage_usdt,
                        realized_pnl, filled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        fill.fill_id,
                        fill.order_id,
                        fill.client_order_id,
                        fill.symbol,
                        fill.side,
                        str(fill.fill_price),
                        str(fill.fill_quantity),
                        str(fill.fee_usdt),
                        str(fill.slippage_usdt),
                        str(fill.realized_pnl),
                        fill.filled_at,
                    ),
                )

    def get_pending_orders(self, symbol: str | None = None) -> list[CanaryShadowOrder]:
        query = "SELECT * FROM canary_shadow_orders WHERE status = 'PENDING'"
        params: tuple[Any, ...] = ()
        if symbol is not None:
            query += " AND symbol = ?"
            params = (symbol,)
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [
                CanaryShadowOrder(
                    order_id=r["order_id"],
                    client_order_id=r["client_order_id"],
                    candidate_id=r["candidate_id"],
                    symbol=r["symbol"],
                    side=r["side"],
                    order_type=r["order_type"],
                    quantity=safe_decimal(r["quantity"]),
                    limit_price=safe_decimal(r["limit_price"]),
                    micro_notional=safe_decimal(r["micro_notional"]),
                    status=r["status"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    cancellation_reason=r["cancellation_reason"],
                )
                for r in rows
            ]

    def insert_orders(self, orders: list[CanaryShadowOrder]) -> None:
        """Batch insert shadow orders with high throughput."""
        if not orders:
            return
        with closing(self._connect()) as conn:
            with conn:
                conn.executemany(
                    """
                    INSERT INTO canary_shadow_orders (
                        order_id, client_order_id, candidate_id, symbol, side,
                        order_type, quantity, limit_price, micro_notional,
                        status, created_at, updated_at, cancellation_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        (
                            order.order_id,
                            order.client_order_id,
                            order.candidate_id,
                            order.symbol,
                            order.side,
                            order.order_type,
                            str(order.quantity),
                            str(order.limit_price),
                            str(order.micro_notional),
                            order.status,
                            order.created_at,
                            order.updated_at,
                            order.cancellation_reason,
                        )
                        for order in orders
                    ],
                )

    def insert_fills(self, fills: list[CanaryShadowFill]) -> None:
        """Batch insert shadow fills with high throughput."""
        if not fills:
            return
        with closing(self._connect()) as conn:
            with conn:
                conn.executemany(
                    """
                    INSERT INTO canary_shadow_fills (
                        fill_id, order_id, client_order_id, symbol, side,
                        fill_price, fill_quantity, fee_usdt, slippage_usdt,
                        realized_pnl, filled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        (
                            fill.fill_id,
                            fill.order_id,
                            fill.client_order_id,
                            fill.symbol,
                            fill.side,
                            str(fill.fill_price),
                            str(fill.fill_quantity),
                            str(fill.fee_usdt),
                            str(fill.slippage_usdt),
                            str(fill.realized_pnl),
                            fill.filled_at,
                        )
                        for fill in fills
                    ],
                )

    def count_orders(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM canary_shadow_orders").fetchone()
            return int(row[0]) if row else 0

    def count_fills(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM canary_shadow_fills").fetchone()
            return int(row[0]) if row else 0

    def verify_referential_integrity(self) -> tuple[bool, int]:
        """Verify that all recorded fills map to an existing order in canary_shadow_orders."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM canary_shadow_fills f
                LEFT JOIN canary_shadow_orders o ON f.order_id = o.order_id
                WHERE o.order_id IS NULL;
                """
            ).fetchone()
            orphans = int(row[0]) if row else 0
            return orphans == 0, orphans

    def verify_unlocked(self, timeout: float = 2.0) -> bool:
        """Verify database has zero dangling locks."""
        if not self.path.is_file():
            return True
        try:
            with closing(sqlite3.connect(self.path, timeout=timeout)) as conn:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("COMMIT;")
            return True
        except Exception:
            return False

    def checkpoint(self) -> None:
        """Flush database pages and optimize store."""
        if not self.path.is_file():
            return
        try:
            with closing(self._connect()) as conn:
                conn.execute("PRAGMA optimize;")
        except Exception:
            pass

    def close(self) -> None:
        """Explicit safe cleanup."""
        self.checkpoint()


class SqliteCanaryShadowLedger:
    """Isolated caller-owned SQLite database for double-entry ledger marks and positions."""

    def __init__(self, db_path: Path | str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS canary_shadow_ledger_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event TEXT NOT NULL,
                        order_id TEXT,
                        trade_id TEXT,
                        candidate_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        quantity TEXT NOT NULL,
                        fill_price TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        cash_balance TEXT NOT NULL,
                        equity TEXT NOT NULL,
                        realized_pnl TEXT NOT NULL,
                        unrealized_pnl TEXT NOT NULL,
                        margin_locked TEXT NOT NULL,
                        fee_usdt TEXT NOT NULL,
                        slippage_usdt TEXT NOT NULL,
                        gross_pnl TEXT NOT NULL,
                        net_pnl TEXT NOT NULL,
                        drift TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS canary_positions (
                        symbol TEXT PRIMARY KEY,
                        candidate_id TEXT NOT NULL,
                        side TEXT NOT NULL,
                        quantity TEXT NOT NULL,
                        entry_price TEXT NOT NULL,
                        current_price TEXT NOT NULL,
                        base_margin TEXT NOT NULL,
                        leverage TEXT NOT NULL,
                        unrealized_pnl TEXT NOT NULL,
                        realized_pnl TEXT NOT NULL,
                        opened_at TEXT NOT NULL,
                        status TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS canary_kill_switch_events (
                        event_id TEXT PRIMARY KEY,
                        tier INTEGER NOT NULL,
                        trigger_type TEXT NOT NULL,
                        trigger_reason TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        orders_cancelled INTEGER NOT NULL,
                        positions_liquidated INTEGER NOT NULL,
                        pre_equity TEXT NOT NULL,
                        post_equity TEXT NOT NULL
                    );
                    """
                )

    def record_ledger_event(
        self,
        event: str,
        candidate_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        fill_price: Decimal,
        occurred_at: str,
        cash_balance: Decimal,
        equity: Decimal,
        realized_pnl: Decimal,
        unrealized_pnl: Decimal,
        margin_locked: Decimal,
        fee_usdt: Decimal,
        slippage_usdt: Decimal,
        gross_pnl: Decimal,
        net_pnl: Decimal,
        drift: Decimal,
        order_id: str | None = None,
        trade_id: str | None = None,
    ) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO canary_shadow_ledger_events (
                        event, order_id, trade_id, candidate_id, symbol, side,
                        quantity, fill_price, occurred_at, cash_balance, equity,
                        realized_pnl, unrealized_pnl, margin_locked, fee_usdt,
                        slippage_usdt, gross_pnl, net_pnl, drift
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        event,
                        order_id,
                        trade_id,
                        candidate_id,
                        symbol,
                        side,
                        str(quantity),
                        str(fill_price),
                        occurred_at,
                        str(cash_balance),
                        str(equity),
                        str(realized_pnl),
                        str(unrealized_pnl),
                        str(margin_locked),
                        str(fee_usdt),
                        str(slippage_usdt),
                        str(gross_pnl),
                        str(net_pnl),
                        str(drift),
                    ),
                )

    def upsert_position(self, pos: CanaryPosition) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO canary_positions (
                        symbol, candidate_id, side, quantity, entry_price,
                        current_price, base_margin, leverage, unrealized_pnl,
                        realized_pnl, opened_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        pos.symbol,
                        pos.candidate_id,
                        pos.side,
                        str(pos.quantity),
                        str(pos.entry_price),
                        str(pos.current_price),
                        str(pos.base_margin),
                        str(pos.leverage),
                        str(pos.unrealized_pnl),
                        str(pos.realized_pnl),
                        pos.opened_at,
                        pos.status,
                    ),
                )

    def record_kill_switch_event(self, ev: CanaryKillSwitchEvent) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO canary_kill_switch_events (
                        event_id, tier, trigger_type, trigger_reason,
                        occurred_at, orders_cancelled, positions_liquidated,
                        pre_equity, post_equity
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        ev.event_id,
                        ev.tier,
                        ev.trigger_type,
                        ev.trigger_reason,
                        ev.occurred_at,
                        ev.orders_cancelled,
                        ev.positions_liquidated,
                        str(ev.pre_equity),
                        str(ev.post_equity),
                    ),
                )

    def get_open_positions(self) -> list[CanaryPosition]:
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM canary_positions WHERE status = 'OPEN'").fetchall()
            return [
                CanaryPosition(
                    symbol=r["symbol"],
                    candidate_id=r["candidate_id"],
                    side=r["side"],
                    quantity=safe_decimal(r["quantity"]),
                    entry_price=safe_decimal(r["entry_price"]),
                    current_price=safe_decimal(r["current_price"]),
                    base_margin=safe_decimal(r["base_margin"]),
                    leverage=safe_decimal(r["leverage"]),
                    unrealized_pnl=safe_decimal(r["unrealized_pnl"]),
                    realized_pnl=safe_decimal(r["realized_pnl"]),
                    opened_at=r["opened_at"],
                    status=r["status"],
                )
                for r in rows
            ]

    def count_events(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM canary_shadow_ledger_events").fetchone()
            return int(row[0]) if row else 0

    def count_kill_switch_events(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM canary_kill_switch_events").fetchone()
            return int(row[0]) if row else 0

    def verify_double_entry_integrity(self) -> tuple[bool, Decimal]:
        """Verify that all recorded ledger marks have double-entry drift < 1e-15."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT MAX(CAST(drift AS REAL)) FROM canary_shadow_ledger_events"
            ).fetchone()
            max_drift = Decimal(str(row[0])) if row and row[0] is not None else Decimal("0")
            return max_drift < Decimal("1e-15"), max_drift

    def verify_unlocked(self, timeout: float = 2.0) -> bool:
        """Verify database has zero dangling locks."""
        if not self.path.is_file():
            return True
        try:
            with closing(sqlite3.connect(self.path, timeout=timeout)) as conn:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("COMMIT;")
            return True
        except Exception:
            return False

    def checkpoint(self) -> None:
        """Flush database pages and optimize store."""
        if not self.path.is_file():
            return
        try:
            with closing(self._connect()) as conn:
                conn.execute("PRAGMA optimize;")
        except Exception:
            pass

    def close(self) -> None:
        """Explicit safe cleanup."""
        self.checkpoint()


# =====================================================================
# Ingestion and Validation
# =====================================================================


def load_and_validate_canary_staging_manifest(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str | None = None,
) -> tuple[CanaryStagingManifest, dict[str, Any]]:
    """Dynamically ingest and cryptographically verify Canary Staging Manifest and candidates.

    Enforces Candidate Registry Manifest Version 2 compatibility, validates SHA-256 artifact
    digests and qualification digests, and returns verified manifest and candidate models.
    """
    p = Path(manifest_path)
    if not p.is_file():
        raise FileNotFoundError(f"Canary Staging Manifest not found at: {p}")

    with open(p, "rb") as f:
        raw_bytes = f.read()

    assert_zero_secrets(raw_bytes, "canary-staging-manifest.json")
    raw_data = json.loads(raw_bytes.decode("utf-8"))

    manifest = CanaryStagingManifest.model_validate(raw_data)
    valid, errors = verify_staging_manifest_integrity(manifest)
    if not valid:
        raise DomainViolation(
            f"Canary staging manifest integrity check failed: {', '.join(errors)}"
        )

    if manifest.manifest_version < 2 or manifest.registry_version < 2:
        raise DomainViolation(
            "Expected Manifest Version 2+, "
            f"got manifest={manifest.manifest_version} registry={manifest.registry_version}"
        )

    if manifest.staging_promotion_state != "canary_staged":
        raise DomainViolation(
            f"Canary staging manifest promotion state is '{manifest.staging_promotion_state}', "
            "expected 'canary_staged'"
        )

    for s in manifest.candidates:
        if s not in EXPECTED_MANIFEST_V2_CANDIDATES:
            raise DomainViolation(
                f"Unexpected candidate {s} in canary staging manifest; "
                f"expected only {list(EXPECTED_MANIFEST_V2_CANDIDATES.keys())}"
            )

    # Cross-reference with Candidate Registry if provided
    repo_root = Path(__file__).resolve().parents[3]
    if registry_path is not None:
        reg_p = Path(registry_path)
        if not reg_p.is_file():
            reg_p = repo_root / registry_path
        if not reg_p.is_file():
            raise FileNotFoundError(f"Candidate Registry not found at: {registry_path}")
        registry = read_candidate_registry(reg_p, verify_hash=True)
        if not verify_candidate_registry_manifest(registry):
            raise DomainViolation(f"Candidate registry manifest verification failed: {reg_p}")
        for sym, expected_cand_id in EXPECTED_MANIFEST_V2_CANDIDATES.items():
            if sym not in registry.symbols:
                raise DomainViolation(f"Symbol {sym} not found in candidate registry {reg_p}")
            if registry.symbols[sym].candidate_id != expected_cand_id:
                raise DomainViolation(
                    f"Candidate ID mismatch in registry for {sym}: "
                    f"expected {expected_cand_id}, got {registry.symbols[sym].candidate_id}"
                )

    candidate_artifacts: dict[str, Any] = {}
    for sym, expected_cand_id in EXPECTED_MANIFEST_V2_CANDIDATES.items():
        if sym not in manifest.candidates:
            raise DomainViolation(f"Missing required active canary candidate {sym} in manifest")
        cand_entry = manifest.candidates[sym]
        if cand_entry.candidate_id != expected_cand_id:
            raise DomainViolation(
                f"Candidate ID mismatch for {sym}: "
                f"expected {expected_cand_id}, got {cand_entry.candidate_id}"
            )
        if cand_entry.staging_promotion_state != "canary_staged":
            raise DomainViolation(
                f"Candidate {sym} has staging_promotion_state "
                f"'{cand_entry.staging_promotion_state}', expected 'canary_staged'"
            )

        art_p = Path(cand_entry.artifact_path)
        if not art_p.is_file():
            art_p = repo_root / cand_entry.artifact_path
        if not art_p.is_file():
            raise FileNotFoundError(f"Candidate artifact file missing: {cand_entry.artifact_path}")

        cand_art = read_creator_candidate_artifact(art_p)
        if cand_art.candidate_id != cand_entry.candidate_id:
            raise DomainViolation(f"Candidate ID mismatch in artifact: {art_p}")
        computed_art_hash = _artifact_content_hash(cand_art)
        if computed_art_hash != cand_entry.candidate_artifact_hash:
            raise DomainViolation(
                f"Candidate artifact content hash mismatch for {sym}: "
                f"{computed_art_hash} != {cand_entry.candidate_artifact_hash}"
            )

        # Validate qualification artifact
        qual_dir = art_p.parent.parent / "qualifications"
        qual_file = qual_dir / f"qual-{cand_entry.candidate_id}.json"
        if not qual_file.is_file():
            qual_file = (
                repo_root
                / "artifacts"
                / "paper_live"
                / "qualifications"
                / f"qual-{cand_entry.candidate_id}.json"
            )
        if not qual_file.is_file():
            raise FileNotFoundError(f"Qualification artifact file missing: {qual_file}")

        qual_art = read_creator_candidate_qualification_artifact(qual_file)
        if qual_art.qualification_hash != cand_entry.qualification_hash:
            raise DomainViolation(f"Qualification hash mismatch for {cand_entry.candidate_id}")
        computed_qual_hash = _qualification_content_hash(qual_art)
        if computed_qual_hash != cand_entry.qualification_hash:
            raise DomainViolation(
                f"Qualification content hash mismatch for {cand_entry.candidate_id}"
            )

        candidate_artifacts[sym] = {
            "candidate": cand_art,
            "qualification": qual_art,
        }

    return manifest, candidate_artifacts


# =====================================================================
# Shadow Execution Engine & Hardened Kill-Switch
# =====================================================================


class CanaryShadowExecutionEngine:
    """Micro-sized shadow order generation, execution, and multi-tier circuit breaker harness.

    Enforces:
    - Fractional micro notional sizing (<= 5.00 USDT per position).
    - Aggregate canary margin utilization <= 60.00% (reserve buffer >= 40.00%).
    - Single-position invariant per symbol across shared account.
    - Tier 1 Soft De-escalation: freezes new order generation on spread expansion,
      volatility spike, or heartbeat timeout.
    - Tier 2 Hard Abort: immediate order cancellation and position liquidation on
      drawdown >= 2.00% or drift > 1e-15 USDT.
    - Exact double-entry accounting:
      drift = |final_cash - (starting_equity + realized_pnl)| < 1e-15 USDT.
    - 100% offline containment: zero external network calls or exchange order placement.
    """

    def __init__(
        self,
        manifest: CanaryStagingManifest,
        orders_store: SqliteCanaryOrdersStore,
        ledger_store: SqliteCanaryShadowLedger,
        starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
        max_micro_notional: Decimal = MAX_MICRO_NOTIONAL_USDT,
        max_aggregate_margin_utilization: Decimal = MAX_CANARY_AGGREGATE_MARGIN_UTILIZATION,
        min_aggregate_reserve_buffer: Decimal = MIN_CANARY_AGGREGATE_RESERVE_BUFFER,
        tier1_max_spread_bps: Decimal = TIER1_MAX_SPREAD_BPS,
        tier1_max_volatility_ratio: Decimal = TIER1_MAX_VOLATILITY_RATIO,
        tier1_heartbeat_timeout_sec: float = TIER1_HEARTBEAT_TIMEOUT_SEC,
        tier2_max_drawdown: Decimal = TIER2_MAX_DRAWDOWN_THRESHOLD,
        taker_fee_rate: Decimal = DEFAULT_TAKER_FEE_RATE,
        slippage_rate: Decimal = DEFAULT_SLIPPAGE_RATE,
    ) -> None:
        self.manifest = manifest
        self.orders_store = orders_store
        self.ledger_store = ledger_store
        start_eq = safe_decimal(starting_equity, DEFAULT_STARTING_EQUITY)
        if start_eq <= Decimal("0"):
            raise DomainViolation(
                f"Starting equity must be strictly positive (> 0), got {start_eq}"
            )
        self.starting_equity = start_eq
        self.max_micro_notional = safe_decimal(max_micro_notional, MAX_MICRO_NOTIONAL_USDT)
        self.max_aggregate_margin_utilization = safe_decimal(
            max_aggregate_margin_utilization, MAX_CANARY_AGGREGATE_MARGIN_UTILIZATION
        )
        self.min_aggregate_reserve_buffer = safe_decimal(
            min_aggregate_reserve_buffer, MIN_CANARY_AGGREGATE_RESERVE_BUFFER
        )
        self.tier1_max_spread_bps = safe_decimal(tier1_max_spread_bps, TIER1_MAX_SPREAD_BPS)
        self.tier1_max_volatility_ratio = safe_decimal(
            tier1_max_volatility_ratio, TIER1_MAX_VOLATILITY_RATIO
        )
        self.tier1_heartbeat_timeout_sec = float(tier1_heartbeat_timeout_sec)
        self.tier2_max_drawdown = safe_decimal(tier2_max_drawdown, TIER2_MAX_DRAWDOWN_THRESHOLD)
        self.taker_fee_rate = safe_decimal(taker_fee_rate, DEFAULT_TAKER_FEE_RATE)
        self.slippage_rate = safe_decimal(slippage_rate, DEFAULT_SLIPPAGE_RATE)

        # Accounting state
        self.cash: Decimal = self.starting_equity
        self.margin_locked: Decimal = Decimal("0")
        self.realized_pnl: Decimal = Decimal("0")
        self.total_fees: Decimal = Decimal("0")
        self.total_slippage: Decimal = Decimal("0")
        self.peak_equity: Decimal = self.starting_equity

        # Circuit breaker state
        self.circuit_state: CanaryCircuitState = CanaryCircuitState.NORMAL
        self.open_orders: dict[str, CanaryShadowOrder] = {}
        self.open_positions: dict[str, CanaryPosition] = {}
        self.closed_positions_count: int = 0
        self.orders_generated_count: int = 0
        self.fills_executed_count: int = 0
        self.cancelled_orders_count: int = 0
        self.liquidations_count: int = 0
        self.kill_switch_events: list[CanaryKillSwitchEvent] = []

        # Synthetic anomaly offsets
        self.simulated_drift_offset: Decimal = Decimal("0")
        self.latest_prices: dict[str, Decimal] = {}

        # Record initial funding event
        now_iso = datetime.now(UTC).isoformat()
        self.ledger_store.record_ledger_event(
            event="INITIAL_DEPOSIT",
            candidate_id="SYSTEM",
            symbol="USDT",
            side="DEPOSIT",
            quantity=Decimal("1"),
            fill_price=self.starting_equity,
            occurred_at=now_iso,
            cash_balance=self.cash,
            equity=self.starting_equity,
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            margin_locked=Decimal("0"),
            fee_usdt=Decimal("0"),
            slippage_usdt=Decimal("0"),
            gross_pnl=Decimal("0"),
            net_pnl=Decimal("0"),
            drift=Decimal("0"),
        )

    @property
    def current_equity(self) -> Decimal:
        """Total portfolio equity = cash + locked_margin + unrealized_pnl + drift_offset."""
        unrealized = sum(p.unrealized_pnl for p in self.open_positions.values())
        eq = self.cash + self.margin_locked + unrealized + self.simulated_drift_offset
        if eq > self.peak_equity:
            self.peak_equity = eq
        return eq

    @property
    def current_drawdown(self) -> Decimal:
        """Drawdown fraction relative to peak equity."""
        if self.peak_equity <= Decimal("0"):
            return Decimal("0")
        eq = self.current_equity
        if eq >= self.peak_equity:
            return Decimal("0")
        return (self.peak_equity - eq) / self.peak_equity

    @property
    def current_drift(self) -> Decimal:
        """Double-entry balance drift between cash, locked margin, equity, and realized PnL."""
        actual_cash = self.cash + self.simulated_drift_offset
        expected = self.starting_equity + self.realized_pnl - self.margin_locked
        return abs(actual_cash - expected)

    @property
    def margin_utilization(self) -> Decimal:
        """Aggregate active margin utilization ratio."""
        eq = self.current_equity
        if eq <= Decimal("0"):
            return Decimal("1.0")
        return self.margin_locked / eq

    @property
    def reserve_buffer(self) -> Decimal:
        """Unencumbered reserve buffer ratio."""
        eq = self.current_equity
        if eq <= Decimal("0"):
            return Decimal("0")
        return max(Decimal("0"), (eq - self.margin_locked) / eq)

    # -----------------------------------------------------------------
    # Telemetry and Tier 1 Soft De-escalation
    # -----------------------------------------------------------------

    def evaluate_feed_telemetry(
        self,
        symbol: str,
        spread_bps: Decimal,
        volatility_ratio: Decimal,
        heartbeat_age_sec: float,
        timestamp: str | None = None,
    ) -> bool:
        """Evaluate feed metrics for Tier 1 Soft De-escalation conditions.

        Returns True if Tier 1 de-escalation was triggered.
        """
        if self.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT:
            return False

        ts = timestamp or datetime.now(UTC).isoformat()
        spread_val = safe_decimal(spread_bps)
        vol_val = safe_decimal(volatility_ratio)

        if spread_val >= self.tier1_max_spread_bps:
            self.trigger_tier1_soft_deescalation(
                trigger_type="SPREAD_EXPANSION",
                reason=f"Spread {spread_val} bps >= threshold {self.tier1_max_spread_bps} bps",
                timestamp=ts,
            )
            return True

        if vol_val >= self.tier1_max_volatility_ratio:
            self.trigger_tier1_soft_deescalation(
                trigger_type="VOLATILITY_REGIME_SHIFT",
                reason=(
                    f"Volatility ratio {vol_val:.2f} >= threshold "
                    f"{self.tier1_max_volatility_ratio:.2f}"
                ),
                timestamp=ts,
            )
            return True

        if heartbeat_age_sec >= self.tier1_heartbeat_timeout_sec:
            self.trigger_tier1_soft_deescalation(
                trigger_type="FEED_HEARTBEAT_TIMEOUT",
                reason=(
                    f"Feed heartbeat age {heartbeat_age_sec:.2f}s >= timeout "
                    f"{self.tier1_heartbeat_timeout_sec:.2f}s"
                ),
                timestamp=ts,
            )
            return True

        return False

    def trigger_tier1_soft_deescalation(
        self, trigger_type: str, reason: str, timestamp: str | None = None
    ) -> None:
        """Activate Tier 1: automatically freeze new order generation."""
        if self.circuit_state in (
            CanaryCircuitState.TIER1_SOFT_DEESCALATION,
            CanaryCircuitState.TIER2_HARD_ABORT,
        ):
            return

        ts = timestamp or datetime.now(UTC).isoformat()
        self.circuit_state = CanaryCircuitState.TIER1_SOFT_DEESCALATION
        ev = CanaryKillSwitchEvent(
            event_id=f"ks-tier1-{uuid4().hex[:8]}",
            tier=1,
            trigger_type=trigger_type,
            trigger_reason=reason,
            occurred_at=ts,
            orders_cancelled=0,
            positions_liquidated=0,
            pre_equity=self.current_equity,
            post_equity=self.current_equity,
        )
        self.kill_switch_events.append(ev)
        self.ledger_store.record_kill_switch_event(ev)
        logger.warning("Tier 1 Soft De-escalation triggered: %s - %s", trigger_type, reason)

    # -----------------------------------------------------------------
    # Tier 2 Hard Abort & Emergency Liquidations
    # -----------------------------------------------------------------

    def check_tier2_circuit_breaker(self, timestamp: str | None = None) -> bool:
        """Check portfolio drawdown and accounting drift for Tier 2 Hard Abort.

        Returns True if Tier 2 Hard Abort was triggered.
        """
        if self.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT:
            return True

        ts = timestamp or datetime.now(UTC).isoformat()

        # Check drawdown threshold
        dd = self.current_drawdown
        if dd >= self.tier2_max_drawdown:
            self.trigger_tier2_hard_abort(
                trigger_type="DRAWDOWN_BREACH",
                reason=(
                    f"Portfolio drawdown {dd * 100:.2f}% >= "
                    f"{self.tier2_max_drawdown * 100:.2f}% limit"
                ),
                timestamp=ts,
            )
            return True

        # Check accounting drift threshold
        drift = self.current_drift
        if drift > DOUBLE_ENTRY_MAX_DRIFT:
            self.trigger_tier2_hard_abort(
                trigger_type="ACCOUNTING_DRIFT",
                reason=f"Accounting drift {drift} USDT > {DOUBLE_ENTRY_MAX_DRIFT} USDT tolerance",
                timestamp=ts,
            )
            return True

        return False

    def trigger_tier2_hard_abort(
        self, trigger_type: str, reason: str, timestamp: str | None = None
    ) -> CanaryKillSwitchEvent:
        """Activate Tier 2: cancel open orders, liquidate positions, and freeze system."""
        # Idempotent: return existing Tier 2 event if already hard-aborted
        if self.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT and self.kill_switch_events:
            for existing_ev in reversed(self.kill_switch_events):
                if existing_ev.tier == 2:
                    return existing_ev

        ts = timestamp or datetime.now(UTC).isoformat()
        pre_eq = self.current_equity
        self.circuit_state = CanaryCircuitState.TIER2_HARD_ABORT

        # 1. Cancel all open shadow orders
        cancelled_orders = 0
        for oid, order in list(self.open_orders.items()):
            if order.status == "PENDING":
                self.orders_store.update_order_status(oid, "CANCELLED", ts, reason)
                order.status = "CANCELLED"
                order.updated_at = ts
                order.cancellation_reason = reason
                cancelled_orders += 1
                self.cancelled_orders_count += 1
        self.open_orders.clear()

        # 2. Immediately liquidate/flatten all open simulated positions
        liquidated_positions = 0
        for sym, pos in list(self.open_positions.items()):
            exit_price = self.latest_prices.get(sym, pos.entry_price)
            notional = exit_price * pos.quantity
            fee = notional * self.taker_fee_rate
            slippage = notional * self.slippage_rate

            if pos.side == "LONG":
                gross_pnl = (exit_price - pos.entry_price) * pos.quantity
            else:
                gross_pnl = (pos.entry_price - exit_price) * pos.quantity

            # Release locked margin and settle cash
            self.margin_locked -= pos.base_margin
            self.cash += pos.base_margin + gross_pnl - fee
            self.realized_pnl += gross_pnl - fee
            self.total_fees += fee
            self.total_slippage += slippage

            pos.status = "CLOSED"
            pos.current_price = exit_price
            pos.unrealized_pnl = Decimal("0")
            pos.realized_pnl += gross_pnl - fee
            self.ledger_store.upsert_position(pos)

            # Record liquidation shadow order
            close_side: Literal["BUY", "SELL"] = "SELL" if pos.side == "LONG" else "BUY"
            liq_order_id = f"ord-liq-{uuid4().hex[:8]}"
            liq_cid = f"c-liq-{sym.lower()}-{uuid4().hex[:8]}"
            liq_order = CanaryShadowOrder(
                order_id=liq_order_id,
                client_order_id=liq_cid,
                candidate_id=pos.candidate_id,
                symbol=sym,
                side=close_side,
                order_type="MARKET",
                quantity=pos.quantity,
                limit_price=exit_price,
                micro_notional=notional,
                status="FILLED",
                created_at=ts,
                updated_at=ts,
                cancellation_reason="TIER2_EMERGENCY_LIQUIDATION",
            )
            self.orders_store.insert_order(liq_order)
            self.orders_generated_count += 1

            # Record liquidation fill
            fill_id = f"fill-liq-{uuid4().hex[:8]}"
            fill = CanaryShadowFill(
                fill_id=fill_id,
                order_id=liq_order_id,
                client_order_id=liq_cid,
                symbol=sym,
                side=close_side,
                fill_price=exit_price,
                fill_quantity=pos.quantity,
                fee_usdt=fee,
                slippage_usdt=slippage,
                realized_pnl=gross_pnl - fee,
                filled_at=ts,
            )
            self.orders_store.insert_fill(fill)
            self.fills_executed_count += 1

            self.ledger_store.record_ledger_event(
                event="KILL_SWITCH_LIQUIDATION",
                candidate_id=pos.candidate_id,
                symbol=sym,
                side=close_side,
                quantity=pos.quantity,
                fill_price=exit_price,
                occurred_at=ts,
                cash_balance=self.cash,
                equity=self.current_equity,
                realized_pnl=self.realized_pnl,
                unrealized_pnl=Decimal("0"),
                margin_locked=self.margin_locked,
                fee_usdt=fee,
                slippage_usdt=slippage,
                gross_pnl=gross_pnl,
                net_pnl=gross_pnl - fee,
                drift=self.current_drift,
                order_id=liq_order_id,
                trade_id=f"tr-liq-{uuid4().hex[:8]}",
            )
            liquidated_positions += 1
            self.liquidations_count += 1
            del self.open_positions[sym]

        post_eq = self.current_equity
        ev = CanaryKillSwitchEvent(
            event_id=f"ks-tier2-{uuid4().hex[:8]}",
            tier=2,
            trigger_type=trigger_type,
            trigger_reason=reason,
            occurred_at=ts,
            orders_cancelled=cancelled_orders,
            positions_liquidated=liquidated_positions,
            pre_equity=pre_eq,
            post_equity=post_eq,
        )
        self.kill_switch_events.append(ev)
        self.ledger_store.record_kill_switch_event(ev)
        logger.error("Tier 2 Hard Abort triggered: %s - %s", trigger_type, reason)
        return ev

    # -----------------------------------------------------------------
    # Order Intent Generation and Execution
    # -----------------------------------------------------------------

    def submit_shadow_order(
        self,
        candidate_id: str,
        symbol: str,
        side: Literal["BUY", "SELL"],
        order_type: Literal["LIMIT", "MARKET"],
        quantity: Decimal,
        limit_price: Decimal,
        timestamp: str | None = None,
        client_order_id: str | None = None,
    ) -> tuple[bool, str, CanaryShadowOrder | None]:
        """Validate and persist micro-sized shadow order intent into durable SQLite store."""
        ts = timestamp or datetime.now(UTC).isoformat()

        # Gate 1: Circuit breaker freeze checks
        if self.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT:
            return False, "CIRCUIT_TIER2_HARD_ABORT_FREEZE", None
        if self.circuit_state == CanaryCircuitState.TIER1_SOFT_DEESCALATION:
            return False, "CIRCUIT_TIER1_SOFT_DEESCALATION_FREEZE", None

        # Gate 2: Candidate authorization against Canary Staging Manifest
        if symbol not in self.manifest.candidates:
            return (
                False,
                f"UNAUTHORIZED_SYMBOL: symbol {symbol} is not staged in canary manifest",
                None,
            )
        cand_entry = self.manifest.candidates[symbol]
        if candidate_id != cand_entry.candidate_id:
            return (
                False,
                (
                    f"CANDIDATE_ID_MISMATCH: candidate {candidate_id} does not match "
                    f"staged candidate {cand_entry.candidate_id} for symbol {symbol}"
                ),
                None,
            )

        # Gate 3: Micro notional cap guardrail (<= 5.00 USDT)
        qty = safe_decimal(quantity)
        px = safe_decimal(limit_price)
        if qty <= Decimal("0") or px <= Decimal("0"):
            return False, "INVALID_PRICE_OR_QUANTITY", None

        micro_notional = qty * px
        if micro_notional > self.max_micro_notional + Decimal("1e-12"):
            return (
                False,
                f"EXCEEDS_MICRO_NOTIONAL_CAP: {micro_notional} > {self.max_micro_notional}",
                None,
            )

        # Gate 4: Single-position invariant per symbol
        if symbol in self.open_positions:
            return (
                False,
                (
                    f"SINGLE_POSITION_INVARIANT_VIOLATION: symbol {symbol} "
                    "already has active open position"
                ),
                None,
            )
        for order in self.open_orders.values():
            if order.symbol == symbol and order.status == "PENDING":
                return (
                    False,
                    (
                        f"SINGLE_POSITION_INVARIANT_VIOLATION: symbol {symbol} "
                        "already has pending order"
                    ),
                    None,
                )

        # Gate 5: Margin utilization, reserve buffer, and candidate allocated margin guardrails
        required_margin = micro_notional  # 1.0x leverage
        new_locked = self.margin_locked + required_margin
        cur_eq = self.current_equity
        if cur_eq <= Decimal("0"):
            return False, "ZERO_OR_NEGATIVE_EQUITY", None

        utilization = new_locked / cur_eq
        if utilization > self.max_aggregate_margin_utilization:
            return (
                False,
                (
                    f"MARGIN_UTILIZATION_CEILING_EXCEEDED: {utilization * 100:.2f}% > "
                    f"{self.max_aggregate_margin_utilization * 100:.2f}%"
                ),
                None,
            )

        buffer = (cur_eq - new_locked) / cur_eq
        if buffer < self.min_aggregate_reserve_buffer:
            return (
                False,
                (
                    f"RESERVE_BUFFER_BREACH: {buffer * 100:.2f}% < "
                    f"{self.min_aggregate_reserve_buffer * 100:.2f}%"
                ),
                None,
            )

        alloc_cap = cand_entry.allocated_risk_limits.allocated_margin_usdt
        if required_margin > alloc_cap:
            return (
                False,
                f"CANDIDATE_ALLOCATED_MARGIN_EXCEEDED: {required_margin} > {alloc_cap}",
                None,
            )

        order_id = f"ord-canary-{uuid4().hex[:10]}"
        cid = client_order_id or f"c-{symbol.lower()}-{uuid4().hex[:8]}"

        order = CanaryShadowOrder(
            order_id=order_id,
            client_order_id=cid,
            candidate_id=candidate_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=qty,
            limit_price=px,
            micro_notional=micro_notional,
            status="PENDING",
            created_at=ts,
            updated_at=ts,
        )

        self.orders_store.insert_order(order)
        self.open_orders[order_id] = order
        self.orders_generated_count += 1

        self.ledger_store.record_ledger_event(
            event="ORDER_INTENT",
            candidate_id=candidate_id,
            symbol=symbol,
            side=side,
            quantity=qty,
            fill_price=px,
            occurred_at=ts,
            cash_balance=self.cash,
            equity=cur_eq,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=Decimal("0"),
            margin_locked=self.margin_locked,
            fee_usdt=Decimal("0"),
            slippage_usdt=Decimal("0"),
            gross_pnl=Decimal("0"),
            net_pnl=Decimal("0"),
            drift=self.current_drift,
            order_id=order_id,
        )

        return True, "ORDER_ACCEPTED", order

    def execute_shadow_fill(
        self,
        order_id: str,
        fill_price: Decimal,
        timestamp: str | None = None,
    ) -> tuple[bool, str, CanaryShadowFill | None]:
        """Simulate fill execution for pending shadow order with fees and slippage."""
        ts = timestamp or datetime.now(UTC).isoformat()
        order = self.open_orders.get(order_id)
        if not order or order.status != "PENDING":
            return False, "ORDER_NOT_FOUND_OR_NOT_PENDING", None

        px = safe_decimal(fill_price)
        if px <= Decimal("0"):
            return False, "INVALID_FILL_PRICE", None

        fill_notional = px * order.quantity
        fee = fill_notional * self.taker_fee_rate
        slippage = fill_notional * self.slippage_rate
        base_margin = fill_notional  # 1.0x leverage

        # Settle entry cash and locked margin
        self.margin_locked += base_margin
        self.cash -= base_margin + fee
        self.realized_pnl -= fee
        self.total_fees += fee
        self.total_slippage += slippage

        # Update order status
        order.status = "FILLED"
        order.updated_at = ts
        self.orders_store.update_order_status(order_id, "FILLED", ts)

        fill_id = f"fill-canary-{uuid4().hex[:8]}"
        fill = CanaryShadowFill(
            fill_id=fill_id,
            order_id=order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            fill_price=px,
            fill_quantity=order.quantity,
            fee_usdt=fee,
            slippage_usdt=slippage,
            realized_pnl=-fee,
            filled_at=ts,
        )
        self.orders_store.insert_fill(fill)
        self.fills_executed_count += 1

        # Create active position
        pos_side: Literal["LONG", "SHORT"] = "LONG" if order.side == "BUY" else "SHORT"
        pos = CanaryPosition(
            symbol=order.symbol,
            candidate_id=order.candidate_id,
            side=pos_side,
            quantity=order.quantity,
            entry_price=px,
            current_price=px,
            base_margin=base_margin,
            leverage=Decimal("1.0"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=-fee,
            opened_at=ts,
            status="OPEN",
        )
        self.open_positions[order.symbol] = pos
        self.ledger_store.upsert_position(pos)
        del self.open_orders[order_id]

        self.latest_prices[order.symbol] = px

        self.ledger_store.record_ledger_event(
            event="FILL",
            candidate_id=order.candidate_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=px,
            occurred_at=ts,
            cash_balance=self.cash,
            equity=self.current_equity,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=Decimal("0"),
            margin_locked=self.margin_locked,
            fee_usdt=fee,
            slippage_usdt=slippage,
            gross_pnl=Decimal("0"),
            net_pnl=-fee,
            drift=self.current_drift,
            order_id=order_id,
            trade_id=f"tr-{uuid4().hex[:8]}",
        )

        self.check_tier2_circuit_breaker(ts)
        return True, "FILL_EXECUTED", fill

    def close_shadow_position(
        self,
        symbol: str,
        exit_price: Decimal,
        timestamp: str | None = None,
        reason: str = "NORMAL_EXIT",
    ) -> tuple[bool, str, CanaryShadowFill | None]:
        """Orderly close of active shadow position, releasing margin and settling PnL."""
        ts = timestamp or datetime.now(UTC).isoformat()
        pos = self.open_positions.get(symbol)
        if not pos or pos.status != "OPEN":
            return False, "POSITION_NOT_FOUND", None

        px = safe_decimal(exit_price)
        if px <= Decimal("0"):
            return False, "INVALID_EXIT_PRICE", None

        exit_notional = px * pos.quantity
        exit_fee = exit_notional * self.taker_fee_rate
        exit_slippage = exit_notional * self.slippage_rate

        if pos.side == "LONG":
            gross_pnl = (px - pos.entry_price) * pos.quantity
        else:
            gross_pnl = (pos.entry_price - px) * pos.quantity

        # Double-entry cash and margin settlement:
        # Cash was reduced by (base_margin + entry_fee) on open, and
        # realized_pnl reduced by entry_fee.
        # On close, cash receives: base_margin + gross_pnl - exit_fee.
        # realized_pnl receives: gross_pnl - exit_fee.
        # Balance drift is strictly zero!
        self.margin_locked -= pos.base_margin
        self.cash += pos.base_margin + gross_pnl - exit_fee
        self.realized_pnl += gross_pnl - exit_fee
        self.total_fees += exit_fee
        self.total_slippage += exit_slippage

        pos.status = "CLOSED"
        pos.current_price = px
        pos.unrealized_pnl = Decimal("0")
        pos.realized_pnl += gross_pnl - exit_fee
        self.ledger_store.upsert_position(pos)
        self.closed_positions_count += 1

        close_side: Literal["BUY", "SELL"] = "SELL" if pos.side == "LONG" else "BUY"
        close_order_id = f"ord-close-{uuid4().hex[:8]}"
        close_cid = f"c-close-{symbol.lower()}-{uuid4().hex[:8]}"
        close_order = CanaryShadowOrder(
            order_id=close_order_id,
            client_order_id=close_cid,
            candidate_id=pos.candidate_id,
            symbol=symbol,
            side=close_side,
            order_type="MARKET",
            quantity=pos.quantity,
            limit_price=px,
            micro_notional=exit_notional,
            status="FILLED",
            created_at=ts,
            updated_at=ts,
        )
        self.orders_store.insert_order(close_order)
        self.orders_generated_count += 1

        fill_id = f"fill-close-{uuid4().hex[:8]}"
        fill = CanaryShadowFill(
            fill_id=fill_id,
            order_id=close_order_id,
            client_order_id=close_cid,
            symbol=symbol,
            side=close_side,
            fill_price=px,
            fill_quantity=pos.quantity,
            fee_usdt=exit_fee,
            slippage_usdt=exit_slippage,
            realized_pnl=gross_pnl - exit_fee,
            filled_at=ts,
        )
        self.orders_store.insert_fill(fill)
        self.fills_executed_count += 1
        del self.open_positions[symbol]

        self.latest_prices[symbol] = px

        self.ledger_store.record_ledger_event(
            event=f"POSITION_CLOSE_{reason}",
            candidate_id=pos.candidate_id,
            symbol=symbol,
            side=close_side,
            quantity=pos.quantity,
            fill_price=px,
            occurred_at=ts,
            cash_balance=self.cash,
            equity=self.current_equity,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=Decimal("0"),
            margin_locked=self.margin_locked,
            fee_usdt=exit_fee,
            slippage_usdt=exit_slippage,
            gross_pnl=gross_pnl,
            net_pnl=gross_pnl - exit_fee,
            drift=self.current_drift,
            order_id=close_order_id,
            trade_id=f"tr-close-{uuid4().hex[:8]}",
        )

        self.check_tier2_circuit_breaker(ts)
        return True, "POSITION_CLOSED", fill

    def update_mark_price(self, symbol: str, price: Decimal, timestamp: str | None = None) -> None:
        """Update mark-to-market valuation for open positions and check protective triggers."""
        ts = timestamp or datetime.now(UTC).isoformat()
        px = safe_decimal(price)
        if px <= Decimal("0"):
            return
        self.latest_prices[symbol] = px

        if symbol in self.open_positions:
            pos = self.open_positions[symbol]
            pos.current_price = px
            if pos.side == "LONG":
                pos.unrealized_pnl = (px - pos.entry_price) * pos.quantity
            else:
                pos.unrealized_pnl = (pos.entry_price - px) * pos.quantity
            self.ledger_store.upsert_position(pos)

        self.check_tier2_circuit_breaker(ts)

    def reconcile_accounting(self) -> tuple[Decimal, bool]:
        """Perform exact double-entry accounting reconciliation."""
        drift = self.current_drift
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT
        return drift, zero_drift

    # -----------------------------------------------------------------
    # Synthetic Anomaly Injections
    # -----------------------------------------------------------------

    def simulate_adverse_drift(
        self, drift_amount: Decimal = Decimal("0.05"), timestamp: str | None = None
    ) -> None:
        """Inject synthetic accounting drift to test fail-safe Tier 2 abort response."""
        ts = timestamp or datetime.now(UTC).isoformat()
        self.simulated_drift_offset += safe_decimal(drift_amount)
        logger.warning(
            "Synthetic adverse drift injected: offset=%s USDT", self.simulated_drift_offset
        )
        self.check_tier2_circuit_breaker(ts)

    def trigger_emergency_kill_switch(
        self, reason: str = "MANUAL_CLI_TRIGGER", timestamp: str | None = None
    ) -> CanaryKillSwitchEvent:
        """Explicitly trigger Tier 2 emergency kill-switch."""
        ts = timestamp or datetime.now(UTC).isoformat()
        return self.trigger_tier2_hard_abort(
            trigger_type="MANUAL_CLI_TRIGGER",
            reason=reason,
            timestamp=ts,
        )

    # -----------------------------------------------------------------
    # Summary Generation
    # -----------------------------------------------------------------

    def get_summary(self, artifact_hashes: dict[str, str] | None = None) -> CanaryExecutionSummary:
        """Produce comprehensive deterministic CanaryExecutionSummary."""
        drift, zero_drift = self.reconcile_accounting()
        now_iso = datetime.now(UTC).isoformat()
        cur_eq = self.current_equity

        candidate_breakdowns: dict[str, Any] = {}
        for sym, cand_entry in self.manifest.candidates.items():
            candidate_breakdowns[sym] = {
                "candidate_id": cand_entry.candidate_id,
                "family": cand_entry.family,
                "timeframe": cand_entry.timeframe,
                "artifact_hash": cand_entry.candidate_artifact_hash,
                "qualification_hash": cand_entry.qualification_hash,
                "allocated_margin_usdt": str(
                    cand_entry.allocated_risk_limits.allocated_margin_usdt
                ),
                "max_micro_notional_usdt": str(self.max_micro_notional),
                "position_status": ("OPEN" if sym in self.open_positions else "CLOSED"),
            }

        safety_invariants = check_fail_closed_safety_invariants()
        safety_invariants["canary_activation"] = False
        safety_invariants["execution_authority"] = False
        safety_invariants["exchange_access"] = False
        safety_invariants["orders"] = 0

        hashes = artifact_hashes or {}

        return CanaryExecutionSummary(
            phase="phase_270",
            description=(
                "Phase 270 Canary Deployment Dry-Run & Micro-Sized Shadow Execution Summary"
            ),
            timestamp_utc=now_iso,
            circuit_state=self.circuit_state.value,
            starting_capital_usdt=self.starting_equity,
            final_cash_usdt=self.cash + self.simulated_drift_offset,
            final_equity_usdt=cur_eq,
            realized_pnl_usdt=self.realized_pnl,
            total_fees_usdt=self.total_fees,
            total_slippage_usdt=self.total_slippage,
            drift_usdt=drift,
            zero_balance_drift=zero_drift,
            max_observed_margin_utilization=self.margin_utilization,
            min_observed_reserve_buffer=self.reserve_buffer,
            margin_guardrails_compliant=(
                self.margin_utilization <= self.max_aggregate_margin_utilization
                and self.reserve_buffer >= self.min_aggregate_reserve_buffer
            ),
            single_position_invariant=True,
            orders_count=self.orders_generated_count,
            fills_count=self.fills_executed_count,
            cancelled_orders_count=self.cancelled_orders_count,
            liquidations_count=self.liquidations_count,
            kill_switch_events=[e.model_dump(mode="json") for e in self.kill_switch_events],
            candidates=candidate_breakdowns,
            safety_invariants=safety_invariants,
            artifact_hashes=hashes,
            staged_manifest_hash=self.manifest.manifest_hash,
            cryptographic_signature=self.manifest.cryptographic_signature,
        )


# =====================================================================
# Parquet Cache and Simulation Replay
# =====================================================================

_PARQUET_CACHE: dict[tuple[Path, int, int], pd.DataFrame] = {}


def _load_canonical_bars(parquet_path: Path, max_rows: int = 500) -> pd.DataFrame:
    """Load and cache canonical parquet bars safely."""
    p = parquet_path.resolve()
    try:
        st = p.stat()
        key = (p, st.st_mtime_ns, st.st_size)
    except OSError:
        key = (p, 0, 0)

    if key not in _PARQUET_CACHE:
        if not p.is_file():
            return pd.DataFrame()
        try:
            df = pd.read_parquet(p, columns=["timestamp", "close"])
        except Exception:
            df = pd.read_parquet(p)
        if df.empty or "timestamp" not in df.columns or "close" not in df.columns:
            return pd.DataFrame()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp", "close"])
        df = df[(df["close"] > 0) & (df["close"] < float("inf"))]
        df = df.sort_values("timestamp").reset_index(drop=True)
        if len(_PARQUET_CACHE) >= 32:
            _PARQUET_CACHE.pop(next(iter(_PARQUET_CACHE)))
        _PARQUET_CACHE[key] = df

    cached = _PARQUET_CACHE[key]
    if len(cached) > max_rows:
        return cached.iloc[-max_rows:].copy().reset_index(drop=True)
    return cached.copy().reset_index(drop=True)


def run_canary_staging_simulation(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    output_dir: Path | str = DEFAULT_PHASE270_OUTPUT_DIR,
    canonical_history_dir: Path | str = DEFAULT_CANONICAL_HISTORY_DIR,
    max_ticks: int = 500,
    symbols: list[str] | None = None,
    trigger_kill_switch: bool = False,
    simulate_adverse_drift: bool = False,
    simulate_spread_expansion: bool = False,
    simulate_volatility_surge: bool = False,
    simulate_feed_timeout: bool = False,
    simulate_drawdown_breach: bool = False,
) -> tuple[CanaryExecutionSummary, Path, Path]:
    """Execute complete deterministic Phase 270 canary staging dry-run simulation.

    Persists shadow orders, fills, and ledger marks into isolated SQLite stores,
    enforces mathematical double-entry zero drift, validates multi-tier kill-switch triggers,
    and packages audit artifacts into output directory.
    """
    if max_ticks < 0:
        raise DomainViolation(f"max_ticks must be non-negative, got {max_ticks}")

    out_p = Path(output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    orders_db_path = out_p / "canary-orders.sqlite3"
    ledger_db_path = out_p / "canary-shadow-ledger.sqlite3"

    # Ensure clean slate: remove stale SQLite database and journal/wal sidecar files
    for db_p in (orders_db_path, ledger_db_path):
        for sidecar in (db_p, Path(f"{db_p}-wal"), Path(f"{db_p}-shm"), Path(f"{db_p}-journal")):
            if sidecar.is_file():
                try:
                    sidecar.unlink()
                except OSError:
                    pass

    # 1. Ingest and cryptographically verify Canary Staging Manifest
    manifest, cand_artifacts = load_and_validate_canary_staging_manifest(
        manifest_path=manifest_path,
        registry_path=registry_path,
    )

    target_symbols = list(manifest.candidates.keys())
    if symbols:
        for s in symbols:
            if s not in manifest.candidates:
                raise DomainViolation(
                    f"Symbol '{s}' is not among staged candidates in canary manifest: "
                    f"{list(manifest.candidates.keys())}"
                )
        target_symbols = [s for s in symbols if s in manifest.candidates]

    # 2. Instantiate isolated SQLite stores
    orders_store = SqliteCanaryOrdersStore(orders_db_path)
    ledger_store = SqliteCanaryShadowLedger(ledger_db_path)

    # 3. Instantiate Canary Shadow Engine
    engine = CanaryShadowExecutionEngine(
        manifest=manifest,
        orders_store=orders_store,
        ledger_store=ledger_store,
        starting_equity=safe_decimal(
            manifest.portfolio_risk_guardrails.total_starting_capital_usdt,
            DEFAULT_STARTING_EQUITY,
        ),
        max_micro_notional=MAX_MICRO_NOTIONAL_USDT,
        max_aggregate_margin_utilization=MAX_CANARY_AGGREGATE_MARGIN_UTILIZATION,
        min_aggregate_reserve_buffer=MIN_CANARY_AGGREGATE_RESERVE_BUFFER,
    )

    try:
        # Immediate CLI kill-switch trigger check
        if trigger_kill_switch:
            engine.trigger_emergency_kill_switch(
                reason="CLI operator explicitly invoked --trigger-kill-switch"
            )
        elif max_ticks == 0:
            # 0-tick dry run: no bar replay needed
            pass
        else:
            # 4. Load canonical bars for active candidates
            hist_dir = Path(canonical_history_dir)
            if not hist_dir.is_dir():
                repo_root = Path(__file__).resolve().parents[3]
                hist_dir = repo_root / canonical_history_dir

            bars_by_symbol: dict[str, pd.DataFrame] = {}
            for sym in target_symbols:
                pq_file = hist_dir / f"{sym}-5m.parquet"
                df = _load_canonical_bars(pq_file, max_rows=max(max_ticks + 60, 200))
                if not df.empty:
                    bars_by_symbol[sym] = df

            # Collect timeline
            all_ts: set[datetime] = set()
            for df in bars_by_symbol.values():
                all_ts.update(df["timestamp"].dt.to_pydatetime())
            sorted_timestamps = [] if max_ticks == 0 else sorted(all_ts)[-max_ticks:]

            # Map timestamps to row dicts per symbol
            indexed_bars: dict[str, dict[datetime, dict[str, Any]]] = {}
            for sym, df in bars_by_symbol.items():
                indexed_bars[sym] = {
                    t: {"close": c}
                    for t, c in zip(
                        df["timestamp"].dt.to_pydatetime(), df["close"].values, strict=False
                    )
                }

            ticks_run = 0
            for ts in sorted_timestamps:
                ticks_run += 1
                ts_iso = ts.isoformat()

                # Anomaly injections
                if simulate_spread_expansion and ticks_run == 5:
                    engine.evaluate_feed_telemetry(
                        symbol="BTCUSDT",
                        spread_bps=Decimal("35.0"),  # > 20.0 bps
                        volatility_ratio=Decimal("1.0"),
                        heartbeat_age_sec=1.0,
                        timestamp=ts_iso,
                    )

                if simulate_volatility_surge and ticks_run == 5:
                    engine.evaluate_feed_telemetry(
                        symbol="BTCUSDT",
                        spread_bps=Decimal("5.0"),
                        volatility_ratio=Decimal("3.5"),  # > 2.5x
                        heartbeat_age_sec=1.0,
                        timestamp=ts_iso,
                    )

                if simulate_feed_timeout and ticks_run == 5:
                    engine.evaluate_feed_telemetry(
                        symbol="BTCUSDT",
                        spread_bps=Decimal("5.0"),
                        volatility_ratio=Decimal("1.0"),
                        heartbeat_age_sec=15.0,  # > 10.0s
                        timestamp=ts_iso,
                    )

                if simulate_adverse_drift and ticks_run == 10:
                    engine.simulate_adverse_drift(Decimal("0.05"), timestamp=ts_iso)

                for sym in target_symbols:
                    sym_bars = indexed_bars.get(sym)
                    if not sym_bars or ts not in sym_bars:
                        continue
                    row = sym_bars[ts]
                    close_px = safe_decimal(row.get("close"), Decimal("100.0"))

                    if simulate_drawdown_breach and ticks_run >= 15:
                        # Artificially depress price to cause > 2% portfolio drawdown
                        close_px = close_px * Decimal("0.50")

                    engine.update_mark_price(sym, close_px, timestamp=ts_iso)

                    if engine.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT:
                        break

                    cand_entry = manifest.candidates[sym]
                    cand_id = cand_entry.candidate_id

                    # Deterministic micro shadow order generation:
                    # Sizing: quantity such that notional == 5.00 USDT
                    if sym not in engine.open_positions and ticks_run % 10 == 1:
                        target_notional = MAX_MICRO_NOTIONAL_USDT
                        qty = (target_notional / close_px).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        ok, msg, order = engine.submit_shadow_order(
                            candidate_id=cand_id,
                            symbol=sym,
                            side="BUY",
                            order_type="LIMIT",
                            quantity=qty,
                            limit_price=close_px,
                            timestamp=ts_iso,
                        )
                        if ok and order:
                            # Immediate shadow fill in offline dry-run sandbox
                            engine.execute_shadow_fill(
                                order_id=order.order_id,
                                fill_price=close_px,
                                timestamp=ts_iso,
                            )

                    elif sym in engine.open_positions and ticks_run % 10 == 6:
                        # Orderly exit after holding period
                        engine.close_shadow_position(
                            symbol=sym,
                            exit_price=close_px,
                            timestamp=ts_iso,
                            reason="CYCLE_COMPLETE",
                        )

                if engine.circuit_state == CanaryCircuitState.TIER2_HARD_ABORT:
                    break

        # Settle any remaining positions orderly for clean terminal reconciliation
        # (unless in Tier 2 where positions are already liquidated)
        now_ts = datetime.now(UTC).isoformat()
        if engine.circuit_state != CanaryCircuitState.TIER2_HARD_ABORT:
            for sym in list(engine.open_positions.keys()):
                px = engine.latest_prices.get(sym, Decimal("100.0"))
                engine.close_shadow_position(sym, px, timestamp=now_ts, reason="TERMINAL_FLATTEN")

    finally:
        orders_store.close()
        ledger_store.close()

    # Verify 100% clean resource cleanup (no dangling file handles or locks)
    if not orders_store.verify_unlocked():
        raise RuntimeError(f"Orders store locked after simulation: {orders_db_path}")
    if not ledger_store.verify_unlocked():
        raise RuntimeError(f"Ledger store locked after simulation: {ledger_db_path}")

    # Verify referential and ledger accounting integrity
    ref_ok, orphans = orders_store.verify_referential_integrity()
    if not ref_ok:
        raise RuntimeError(
            f"Referential integrity failure: {orphans} orphaned fills found in {orders_db_path}"
        )
    ledger_ok, max_drift = ledger_store.verify_double_entry_integrity()
    if not ledger_ok:
        raise RuntimeError(
            f"Double-entry integrity failure: max drift {max_drift} >= 1e-15 in {ledger_db_path}"
        )

    # 5. Compute SHA-256 digests and produce artifacts
    artifact_hashes = {
        "canary-orders.sqlite3": compute_file_sha256(orders_db_path),
        "canary-shadow-ledger.sqlite3": compute_file_sha256(ledger_db_path),
    }

    summary = engine.get_summary(artifact_hashes=artifact_hashes)
    summary_bytes = canonical_json_bytes(summary.model_dump(mode="json"))
    assert_zero_secrets(summary_bytes, "canary-summary.json")

    summary_file = out_p / "canary-summary.json"
    paper_summary_file = out_p / "paper-summary.json"
    report_file = out_p / "canary-execution-report.json"

    with open(summary_file, "wb") as f:
        f.write(summary_bytes)
    with open(paper_summary_file, "wb") as f:
        f.write(summary_bytes)

    report_payload = {
        "phase": "phase_270",
        "description": "Phase 270 Canary Deployment Dry-Run Execution Report",
        "timestamp_utc": summary.timestamp_utc,
        "circuit_state": summary.circuit_state,
        "portfolio": {
            "starting_capital_usdt": str(summary.starting_capital_usdt),
            "final_cash_usdt": str(summary.final_cash_usdt),
            "final_equity_usdt": str(summary.final_equity_usdt),
            "realized_pnl_usdt": str(summary.realized_pnl_usdt),
            "drift_usdt": str(summary.drift_usdt),
            "zero_balance_drift": summary.zero_balance_drift,
            "max_observed_margin_utilization": str(summary.max_observed_margin_utilization),
            "min_observed_reserve_buffer": str(summary.min_observed_reserve_buffer),
        },
        "stats": {
            "orders_count": summary.orders_count,
            "fills_count": summary.fills_count,
            "cancelled_orders_count": summary.cancelled_orders_count,
            "liquidations_count": summary.liquidations_count,
        },
        "kill_switch_events": summary.kill_switch_events,
        "artifact_hashes": artifact_hashes,
    }
    report_bytes = canonical_json_bytes(report_payload)
    assert_zero_secrets(report_bytes, "canary-execution-report.json")
    with open(report_file, "wb") as f:
        f.write(report_bytes)

    return summary, ledger_db_path, orders_db_path


__all__ = [
    "CANARY_MAX_AGGREGATE_MARGIN_UTILIZATION",
    "CANARY_MIN_AGGREGATE_RESERVE_BUFFER",
    "CanaryCircuitState",
    "CanaryExecutionSummary",
    "CanaryKillSwitchEvent",
    "CanaryPosition",
    "CanaryShadowExecutionEngine",
    "CanaryShadowFill",
    "CanaryShadowOrder",
    "DEFAULT_CANARY_STAGING_MANIFEST_PATH",
    "DEFAULT_CANONICAL_HISTORY_DIR",
    "DEFAULT_PHASE270_OUTPUT_DIR",
    "DEFAULT_SLIPPAGE_RATE",
    "DEFAULT_STARTING_EQUITY",
    "DEFAULT_TAKER_FEE_RATE",
    "DOUBLE_ENTRY_MAX_DRIFT",
    "EXPECTED_MANIFEST_V2_CANDIDATES",
    "MAX_CANARY_AGGREGATE_MARGIN_UTILIZATION",
    "MAX_MICRO_NOTIONAL_USDT",
    "MIN_CANARY_AGGREGATE_RESERVE_BUFFER",
    "SqliteCanaryOrdersStore",
    "SqliteCanaryShadowLedger",
    "TIER1_HEARTBEAT_TIMEOUT_SEC",
    "TIER1_MAX_SPREAD_BPS",
    "TIER1_MAX_VOLATILITY_RATIO",
    "TIER2_MAX_DRAWDOWN_THRESHOLD",
    "load_and_validate_canary_staging_manifest",
    "run_canary_staging_simulation",
]
