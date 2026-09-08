"""Caller-owned SQLite storage for append-only paper-ledger events."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from autonomous_futures.research.creator_artifacts import _artifact_content_hash

from .ledger import PaperLedger, PaperLedgerEntry, PaperRestartRecoveryError

_POSITION_STATE_KEYS = {
    "state_version",
    "trade_id",
    "candidate_id",
    "candidate_artifact_hash",
    "symbol",
    "side",
    "quantity",
    "base_margin",
    "leverage",
    "watermark",
    "peak_pnl",
    "stop_price",
    "target_price",
    "trailing_atr_multiplier",
    "current_atr",
    "opened_at",
    "trailing_stop_price",
    "strategy_json",
}
_POSITION_DECIMAL_KEYS = {
    "quantity",
    "base_margin",
    "leverage",
    "watermark",
    "peak_pnl",
    "stop_price",
    "target_price",
    "trailing_atr_multiplier",
    "current_atr",
    "trailing_stop_price",
}


def validate_position_state(
    raw: dict[str, Any], *, sql_trade_id: str | None = None, sql_state_version: int | None = None
) -> dict[str, Any]:
    """Validate and normalize untrusted durable position evidence."""
    if not isinstance(raw, dict) or set(raw) != _POSITION_STATE_KEYS:
        raise PaperRestartRecoveryError("invalid paper position state schema")
    if raw["state_version"] != 1 or (sql_state_version is not None and sql_state_version != 1):
        raise PaperRestartRecoveryError("unsupported paper position state version")
    if sql_trade_id is not None and raw["trade_id"] != sql_trade_id:
        raise PaperRestartRecoveryError("paper position SQL identity mismatch")
    for key in ("trade_id", "candidate_id", "symbol", "side", "opened_at", "strategy_json"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise PaperRestartRecoveryError("invalid paper position state schema")
    if not re.fullmatch(r"[0-9a-f]{64}", raw["candidate_artifact_hash"]):
        raise PaperRestartRecoveryError("invalid paper position artifact hash")
    if raw["side"] not in ("LONG", "SHORT"):
        raise PaperRestartRecoveryError("invalid paper position side")
    try:
        opened_at = datetime.fromisoformat(raw["opened_at"])
        if opened_at.tzinfo is None or opened_at.utcoffset() != UTC.utcoffset(opened_at):
            raise ValueError("opened_at is not UTC")
    except (TypeError, ValueError) as exc:
        raise PaperRestartRecoveryError("invalid paper position timestamp") from exc
    for key in _POSITION_DECIMAL_KEYS:
        if raw[key] is None and key not in {"target_price", "trailing_stop_price"}:
            raise PaperRestartRecoveryError("invalid paper position decimal")
        if raw[key] is not None:
            try:
                value = Decimal(str(raw[key]))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise PaperRestartRecoveryError("invalid paper position decimal") from exc
            if not value.is_finite() or (key != "peak_pnl" and value <= 0):
                raise PaperRestartRecoveryError("invalid paper position decimal range")
            raw[key] = value
    try:
        strategy = json.loads(raw["strategy_json"])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PaperRestartRecoveryError("invalid persisted strategy content") from exc
    if not isinstance(strategy, dict):
        raise PaperRestartRecoveryError("invalid persisted strategy schema")
    raw["opened_at"] = opened_at.astimezone(UTC).isoformat()
    return raw


class SqlitePaperLedger:
    """Persist and rehydrate paper events without choosing a runtime storage path."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                approval_id TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                slippage_cost TEXT,
                gross_pnl TEXT,
                net_pnl TEXT
            )
            """
        )
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(paper_ledger_events)")
        }
        for column in (
            "approval_id",
            "entry_fee",
            "exit_fee",
            "slippage_cost",
            "gross_pnl",
            "net_pnl",
        ):
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE paper_ledger_events ADD COLUMN {column} TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_position_state (
                trade_id TEXT PRIMARY KEY,
                state_version INTEGER NOT NULL,
                state_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_position_update_intent (
                trade_id TEXT PRIMARY KEY,
                intent TEXT NOT NULL
            )
            """
        )
        return connection

    def begin_position_update(self, trade_id: str, intent: str = "mutable_state") -> None:
        """Commit a write-ahead dirty marker before changing runtime state."""
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO paper_position_update_intent("
                "trade_id, intent) VALUES (?, ?)",
                (trade_id, intent),
            )

    def clear_position_update(self, trade_id: str) -> None:
        """Clear a dirty marker only after durable and memory updates complete."""
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM paper_position_update_intent WHERE trade_id = ?", (trade_id,)
            )

    def require_no_position_update_intents(self) -> None:
        """Reject recovery when any previously committed update did not finish."""
        if not self._path.exists():
            return
        with self._connect() as connection:
            row = connection.execute(
                "SELECT trade_id FROM paper_position_update_intent ORDER BY trade_id LIMIT 1"
            ).fetchone()
        if row is not None:
            raise PaperRestartRecoveryError(
                f"dirty paper position update intent remains for trade {row[0]}"
            )

    def save_position_state(self, state: dict[str, Any]) -> None:
        """Persist the complete validated runtime state for one open trade."""
        payload = dict(state)
        payload.setdefault("state_version", 1)
        payload = validate_position_state(payload)
        for key in _POSITION_DECIMAL_KEYS:
            if payload[key] is not None:
                payload[key] = str(payload[key])
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO paper_position_state("
                "trade_id,state_version,state_json) VALUES(?,?,?)",
                (
                    str(payload["trade_id"]),
                    1,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )

    def delete_position_state(self, trade_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM paper_position_state WHERE trade_id = ?", (trade_id,))

    def load_position_states(self) -> tuple[dict[str, Any], ...]:
        if not self._path.exists():
            return ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT trade_id,state_version,state_json "
                "FROM paper_position_state "
                "ORDER BY trade_id"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for sql_trade_id, sql_state_version, raw in rows:
            try:
                state = validate_position_state(
                    json.loads(raw),
                    sql_trade_id=str(sql_trade_id),
                    sql_state_version=sql_state_version,
                )
            except (PaperRestartRecoveryError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise PaperRestartRecoveryError("corrupt paper position state") from exc
            result.append(state)
        return tuple(result)

    def require_recoverable_position_states(
        self, open_trade_ids: set[str], candidate_by_id: dict[str, Any]
    ) -> tuple[dict[str, Any], ...]:
        states = self.load_position_states()
        state_by_trade = {str(state["trade_id"]): state for state in states}
        if len(state_by_trade) != len(states):
            raise PaperRestartRecoveryError("ambiguous paper position state")
        if set(state_by_trade) != open_trade_ids:
            raise PaperRestartRecoveryError(
                "missing or orphan paper position state; no persisted protective state"
            )
        for state in states:
            candidate = candidate_by_id.get(state["candidate_id"])
            if (
                candidate is None
                or candidate.artifact_hash != state["candidate_artifact_hash"]
                or _artifact_content_hash(candidate) != state["candidate_artifact_hash"]
            ):
                raise PaperRestartRecoveryError("stale or incompatible paper strategy state")
            if json.loads(state["strategy_json"]) != candidate.model_dump(mode="json"):
                raise PaperRestartRecoveryError("persisted strategy content mismatch")
        return states

    @staticmethod
    def _entry(row: tuple[object, ...]) -> PaperLedgerEntry:
        return PaperLedgerEntry.model_validate(
            {
                "event": row[0],
                "trade_id": row[1],
                "candidate_id": row[2],
                "candidate_artifact_hash": row[3],
                "symbol": row[4],
                "side": row[5],
                "quantity": Decimal(str(row[6])),
                "fill_price": Decimal(str(row[7])),
                "occurred_at": row[8],
                "approval_id": row[9],
                "entry_fee": None if row[10] is None else Decimal(str(row[10])),
                "exit_fee": None if row[11] is None else Decimal(str(row[11])),
                "slippage_cost": None if row[12] is None else Decimal(str(row[12])),
                "gross_pnl": None if row[13] is None else Decimal(str(row[13])),
                "net_pnl": None if row[14] is None else Decimal(str(row[14])),
            }
        )

    def _entries(self, connection: sqlite3.Connection) -> tuple[PaperLedgerEntry, ...]:
        rows = connection.execute(
            """
            SELECT event, trade_id, candidate_id, candidate_artifact_hash, symbol,
                   side, quantity, fill_price, occurred_at, approval_id, entry_fee, exit_fee,
                   slippage_cost, gross_pnl, net_pnl
            FROM paper_ledger_events
            ORDER BY sequence
            """
        ).fetchall()
        return tuple(self._entry(row) for row in rows)

    def load(self) -> PaperLedger:
        if not self._path.exists():
            return PaperLedger()
        with self._connect() as connection:
            return PaperLedger(self._entries(connection))

    def append(self, entry: PaperLedgerEntry) -> None:
        with self._connect() as connection:
            ledger = PaperLedger(self._entries(connection))
            ledger.append(entry)
            connection.execute(
                """
                INSERT INTO paper_ledger_events (
                    event, trade_id, candidate_id, candidate_artifact_hash, symbol,
                    side, quantity, fill_price, occurred_at, approval_id, entry_fee, exit_fee,
                    slippage_cost, gross_pnl, net_pnl
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.event,
                    entry.trade_id,
                    entry.candidate_id,
                    entry.candidate_artifact_hash,
                    entry.symbol,
                    entry.side,
                    str(entry.quantity),
                    str(entry.fill_price),
                    entry.occurred_at.isoformat(),
                    entry.approval_id,
                    None if entry.entry_fee is None else str(entry.entry_fee),
                    None if entry.exit_fee is None else str(entry.exit_fee),
                    None if entry.slippage_cost is None else str(entry.slippage_cost),
                    None if entry.gross_pnl is None else str(entry.gross_pnl),
                    None if entry.net_pnl is None else str(entry.net_pnl),
                ),
            )
