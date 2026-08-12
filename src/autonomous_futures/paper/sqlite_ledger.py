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
                occurred_at TEXT NOT NULL
            )
            """
        )
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
            }
        )

    def load(self) -> PaperLedger:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event, trade_id, candidate_id, candidate_artifact_hash, symbol,
                       side, quantity, fill_price, occurred_at
                FROM paper_ledger_events
                ORDER BY sequence
                """
            ).fetchall()
        return PaperLedger(tuple(self._entry(row) for row in rows))

    def append(self, entry: PaperLedgerEntry) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event, trade_id, candidate_id, candidate_artifact_hash, symbol,
                       side, quantity, fill_price, occurred_at
                FROM paper_ledger_events
                ORDER BY sequence
                """
            ).fetchall()
            ledger = PaperLedger(tuple(self._entry(row) for row in rows))
            ledger.append(entry)
            connection.execute(
                """
                INSERT INTO paper_ledger_events (
                    event, trade_id, candidate_id, candidate_artifact_hash, symbol,
                    side, quantity, fill_price, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
