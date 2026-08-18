"""Caller-owned append-only SQLite storage for paper lifecycle marks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .lifecycle import PaperLifecycleTelemetry


class SqlitePaperLifecycle:
    """Persist lifecycle marks without choosing a path or obtaining marks."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_lifecycle_marks (
                sequence INTEGER PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                marked_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'paper_lifecycle_marks'"
        ).fetchone()
        return row is not None

    def append(self, telemetry: PaperLifecycleTelemetry) -> None:
        with self._connect_for_append() as connection:
            connection.execute(
                """
                INSERT INTO paper_lifecycle_marks (
                    candidate_id, candidate_artifact_hash, trade_id, marked_at, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    telemetry.candidate_id,
                    telemetry.candidate_artifact_hash,
                    telemetry.trade_id,
                    telemetry.marked_at.isoformat(),
                    telemetry.model_dump_json(),
                ),
            )

    def read(
        self,
        *,
        candidate_id: str,
        candidate_artifact_hash: str,
        trade_id: str,
    ) -> tuple[PaperLifecycleTelemetry, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                """
                SELECT payload
                FROM paper_lifecycle_marks
                WHERE candidate_id = ? AND candidate_artifact_hash = ? AND trade_id = ?
                ORDER BY sequence
                """,
                (candidate_id, candidate_artifact_hash, trade_id),
            ).fetchall()
        return tuple(PaperLifecycleTelemetry.model_validate_json(row[0]) for row in rows)

    def latest(
        self,
        *,
        candidate_id: str,
        candidate_artifact_hash: str,
        trade_id: str,
    ) -> PaperLifecycleTelemetry | None:
        rows = self.read(
            candidate_id=candidate_id,
            candidate_artifact_hash=candidate_artifact_hash,
            trade_id=trade_id,
        )
        return rows[-1] if rows else None
