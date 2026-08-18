"""Caller-owned write-once SQLite storage for paper review checkpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .review import PaperReviewCheckpoint


class SqlitePaperReviews:
    """Persist immutable human-review checkpoints without choosing a path."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_review_checkpoints (
                sequence INTEGER PRIMARY KEY,
                review_id TEXT NOT NULL UNIQUE,
                reviewed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'paper_review_checkpoints'"
        ).fetchone()
        return row is not None

    def append(self, checkpoint: PaperReviewCheckpoint) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM paper_review_checkpoints WHERE review_id = ?",
                (checkpoint.review_id,),
            ).fetchone()
            if existing is not None:
                stored = PaperReviewCheckpoint.model_validate_json(existing[0])
                if stored != checkpoint:
                    raise ValueError("conflicting review ID")
                return
            connection.execute(
                """
                INSERT INTO paper_review_checkpoints (
                    review_id, reviewed_at, payload
                ) VALUES (?, ?, ?)
                """,
                (
                    checkpoint.review_id,
                    checkpoint.reviewed_at.isoformat(),
                    checkpoint.model_dump_json(),
                ),
            )

    def get(self, review_id: str) -> PaperReviewCheckpoint | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM paper_review_checkpoints WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return None if row is None else PaperReviewCheckpoint.model_validate_json(row[0])

    def read(self) -> tuple[PaperReviewCheckpoint, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM paper_review_checkpoints ORDER BY sequence"
            ).fetchall()
        return tuple(PaperReviewCheckpoint.model_validate_json(row[0]) for row in rows)
