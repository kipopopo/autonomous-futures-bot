import sqlite3
from pathlib import Path

from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger


def test_sqlite_paper_ledger_adds_accounting_columns_to_legacy_event_table(tmp_path: Path) -> None:
    path = tmp_path / "legacy-paper-ledger.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE paper_ledger_events (
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

    SqlitePaperLedger(path).load()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(paper_ledger_events)")}
    assert {"entry_fee", "exit_fee", "slippage_cost", "gross_pnl", "net_pnl"} <= columns
