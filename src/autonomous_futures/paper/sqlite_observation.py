"""Caller-owned append-only SQLite storage for paper observations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .observation import PaperObservation


class SqlitePaperObservations:
    """Persist and read observation snapshots without choosing a runtime path."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_observations (
                sequence INTEGER PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    def append(self, observation: PaperObservation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_observations (
                    candidate_id, candidate_artifact_hash, observed_at, payload
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    observation.candidate_id,
                    observation.candidate_artifact_hash,
                    observation.observed_at.isoformat(),
                    observation.model_dump_json(),
                ),
            )

    def read(self, candidate_id: str, candidate_artifact_hash: str) -> tuple[PaperObservation, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM paper_observations
                WHERE candidate_id = ? AND candidate_artifact_hash = ?
                ORDER BY sequence
                """,
                (candidate_id, candidate_artifact_hash),
            ).fetchall()
        return tuple(PaperObservation.model_validate_json(row[0]) for row in rows)
