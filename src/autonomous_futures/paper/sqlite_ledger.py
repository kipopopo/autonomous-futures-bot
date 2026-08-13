"""Caller-owned SQLite storage for append-only paper-ledger events."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from .ledger import PaperLedger, PaperLedgerEntry


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
        return connection

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
