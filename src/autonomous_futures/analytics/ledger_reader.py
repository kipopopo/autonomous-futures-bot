"""Non-blocking read-only SQLite ledger reader.

Connects to paper trading SQLite ledgers strictly in read-only mode (?mode=ro,
PRAGMA query_only = ON, busy_timeout = 1000) and executes self-join queries to
reconstruct complete round-trip trade records with exact Decimal precision.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.analytics.models import TradeRecord

logger = logging.getLogger(__name__)


def _parse_utc_datetime(iso_str: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt


class ReadOnlyLedgerReader:
    """Thread-safe, non-blocking read-only reader for paper trading ledgers."""

    def __init__(self, storage_dir: Path | str) -> None:
        self.storage_dir = Path(storage_dir)
        self.ledger_db_path = self.storage_dir / "paper-ledger.sqlite3"
        self.lifecycle_db_path = self.storage_dir / "paper-lifecycle.sqlite3"
        self.observations_db_path = self.storage_dir / "paper-observations.sqlite3"

    def _connect_readonly(self, db_path: Path) -> sqlite3.Connection | None:
        """Open a SQLite database strictly in read-only mode with busy timeout."""
        if not db_path.is_file():
            return None
        try:
            uri_path = db_path.resolve().as_posix()
            uri = f"file:{uri_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=1.0)
            conn.execute("PRAGMA query_only = ON;")
            conn.execute("PRAGMA busy_timeout = 1000;")
            return conn
        except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError) as exc:
            logger.debug("Could not open read-only connection to %s: %s", db_path, exc)
            return None

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        """Check if a table exists in the connected database."""
        try:
            cur = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            )
            return cur.fetchone() is not None
        except sqlite3.Error:
            return False

    def _load_exit_reasons(self) -> dict[str, str]:
        """Attempt to read exit reasons from paper-lifecycle.sqlite3 if available."""
        exit_reasons: dict[str, str] = {}
        conn = self._connect_readonly(self.lifecycle_db_path)
        if conn is None:
            return exit_reasons

        try:
            if not self._table_exists(conn, "paper_lifecycle_marks"):
                return exit_reasons

            cur = conn.execute(
                "SELECT trade_id, payload FROM paper_lifecycle_marks ORDER BY sequence ASC"
            )
            for row in cur.fetchall():
                t_id = str(row[0])
                try:
                    payload = json.loads(row[1]) if isinstance(row[1], str) else {}
                    reason_codes = payload.get("reason_codes", [])
                    status = payload.get("lifecycle_status")
                    if status == "closed" or any(
                        "hit" in str(r) or "exit" in str(r) for r in reason_codes
                    ):
                        # Extract most specific exit reason
                        for r in reversed(reason_codes):
                            if r not in ("lifecycle_open", "normal"):
                                exit_reasons[t_id] = str(r)
                                break
                except json.JSONDecodeError, TypeError, KeyError:
                    continue
        except sqlite3.Error as exc:
            logger.debug("Could not read lifecycle marks: %s", exc)
        finally:
            conn.close()

        return exit_reasons

    def read_closed_trades(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        symbols: list[str] | set[str] | None = None,
    ) -> list[TradeRecord]:
        """Read all closed trades with entry and exit details via self-join query.

        Args:
            start_time: Optional start timestamp (inclusive, UTC).
            end_time: Optional end timestamp (exclusive, UTC).
            symbols: Optional symbol filter.

        Returns:
            Chronologically sorted list of TradeRecord objects.
        """
        conn = self._connect_readonly(self.ledger_db_path)
        if conn is None:
            return []

        trades: list[TradeRecord] = []
        try:
            if not self._table_exists(conn, "paper_ledger_events"):
                return []

            query = """
                SELECT
                    c.sequence AS close_sequence,
                    c.trade_id,
                    c.candidate_id,
                    c.candidate_artifact_hash,
                    c.symbol,
                    c.side,
                    c.quantity,
                    o.fill_price AS entry_price,
                    c.fill_price AS exit_price,
                    o.occurred_at AS opened_at,
                    c.occurred_at AS closed_at,
                    c.entry_fee,
                    c.exit_fee,
                    c.slippage_cost,
                    c.gross_pnl,
                    c.net_pnl,
                    o.approval_id AS open_approval_id,
                    c.approval_id AS close_approval_id
                FROM paper_ledger_events c
                INNER JOIN paper_ledger_events o
                    ON o.trade_id = c.trade_id AND o.event = 'open'
                WHERE c.event = 'close'
            """
            params: list[Any] = []

            if start_time is not None:
                query += " AND c.occurred_at >= ?"
                params.append(start_time.isoformat())

            if end_time is not None:
                query += " AND c.occurred_at < ?"
                params.append(end_time.isoformat())

            if symbols:
                placeholders = ",".join("?" for _ in symbols)
                query += f" AND c.symbol IN ({placeholders})"
                params.extend(symbols)

            query += " ORDER BY c.sequence ASC"

            cur = conn.execute(query, params)
            exit_reasons = self._load_exit_reasons()

            for row in cur.fetchall():
                try:
                    opened_at = _parse_utc_datetime(str(row[9]))
                    closed_at = _parse_utc_datetime(str(row[10]))
                    holding_duration = max(0.0, (closed_at - opened_at).total_seconds())

                    entry_fee = Decimal(str(row[11] or "0.0"))
                    exit_fee = Decimal(str(row[12] or "0.0"))
                    total_fees = entry_fee + exit_fee

                    trade_id = str(row[1])
                    exit_reason = exit_reasons.get(trade_id, "normal_close")

                    record = TradeRecord(
                        close_sequence=int(row[0]),
                        trade_id=trade_id,
                        candidate_id=str(row[2]),
                        candidate_artifact_hash=str(row[3]),
                        symbol=str(row[4]),
                        side=str(row[5]),
                        quantity=Decimal(str(row[6])),
                        entry_price=Decimal(str(row[7])),
                        exit_price=Decimal(str(row[8])),
                        opened_at=opened_at,
                        closed_at=closed_at,
                        holding_duration_seconds=holding_duration,
                        entry_fee=entry_fee,
                        exit_fee=exit_fee,
                        total_fees=total_fees,
                        slippage_cost=Decimal(str(row[13] or "0.0")),
                        gross_pnl=Decimal(str(row[14] or "0.0")),
                        net_pnl=Decimal(str(row[15] or "0.0")),
                        open_approval_id=str(row[16]) if row[16] else None,
                        close_approval_id=str(row[17]) if row[17] else None,
                        exit_reason=exit_reason,
                    )
                    trades.append(record)
                except (ValueError, TypeError, ArithmeticError) as exc:
                    logger.warning("Skipping corrupted trade row sequence %s: %s", row[0], exc)
                    continue

        except sqlite3.Error as exc:
            logger.warning("Error reading closed trades from ledger: %s", exc)
        finally:
            conn.close()

        return trades

    def read_open_trades_count(self) -> int:
        """Count active open positions without a matching close event."""
        conn = self._connect_readonly(self.ledger_db_path)
        if conn is None:
            return 0
        try:
            if not self._table_exists(conn, "paper_ledger_events"):
                return 0
            cur = conn.execute(
                """
                SELECT count(DISTINCT o.trade_id)
                FROM paper_ledger_events o
                LEFT JOIN paper_ledger_events c
                    ON c.trade_id = o.trade_id AND c.event = 'close'
                WHERE o.event = 'open' AND c.sequence IS NULL
                """
            )
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        except sqlite3.Error:
            return 0
        finally:
            conn.close()

    def calculate_reconciled_cash(self, starting_capital: Decimal = Decimal("100.00")) -> Decimal:
        """Calculate exact reconciled cash balance: C_0 + sum(net_pnl) - sum(open_entry_fees)."""
        conn = self._connect_readonly(self.ledger_db_path)
        if conn is None:
            return starting_capital
        try:
            if not self._table_exists(conn, "paper_ledger_events"):
                return starting_capital

            # Sum net realized PnL of all closed trades with exact Decimal
            cur_closed = conn.execute(
                "SELECT net_pnl FROM paper_ledger_events WHERE event = 'close'"
            )
            closed_net_pnl = sum(
                (Decimal(str(r[0])) for r in cur_closed.fetchall() if r[0] is not None),
                Decimal("0.00"),
            )

            # Sum entry fees of open trades with exact Decimal
            cur_open = conn.execute(
                """
                SELECT o.entry_fee
                FROM paper_ledger_events o
                LEFT JOIN paper_ledger_events c
                    ON c.trade_id = o.trade_id AND c.event = 'close'
                WHERE o.event = 'open' AND c.sequence IS NULL
                """
            )
            open_fees = sum(
                (Decimal(str(r[0])) for r in cur_open.fetchall() if r[0] is not None),
                Decimal("0.00"),
            )

            return starting_capital + closed_net_pnl - open_fees
        except sqlite3.Error, ArithmeticError:
            return starting_capital
        finally:
            conn.close()
