#!/usr/bin/env python3
"""Autonomous Futures Bot: Real-Time Telegram Telemetry & Trade Alerts Sidecar.

Runs as a completely decoupled background sidecar daemon observing live paper
trading state via read-only SQLite ledgers (?mode=ro) and JSON health checkpoints.
Dispatches formatted trade alerts, circuit breaker warnings, and periodic digests.
Also listens for authorized read-only Telegram commands (/status, /positions, /pnl, etc.).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure repository root / src is on sys.path for direct script execution
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.notify.telegram import (  # noqa: E402
    TelegramConfig,
    TelegramNotifierClient,
    escape_markdown_v2,
    resolve_telegram_credentials,
)
from autonomous_futures.tui.telemetry import TelemetryReader  # noqa: E402

logger = logging.getLogger("telegram_notifier")


class CheckpointState:
    """Manages persistent checkpointing for the Telegram notifier."""

    def __init__(self, checkpoint_path: Path) -> None:
        self.path = checkpoint_path
        self.last_sequence: int = 0
        self.last_cb_status: str = "NORMAL"
        self.last_margin_alerted: bool = False
        self.last_digest_timestamp: float = 0.0
        self.last_update_id: int = 0
        self.last_daily_report_date: str = ""
        self.load()

    def load(self) -> None:
        """Load state from JSON file if present."""
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.last_sequence = int(data.get("last_sequence") or 0)
                self.last_cb_status = str(data.get("last_cb_status") or "NORMAL")
                self.last_margin_alerted = bool(data.get("last_margin_alerted") or False)
                self.last_digest_timestamp = float(data.get("last_digest_timestamp") or 0.0)
                self.last_update_id = int(data.get("last_update_id") or 0)
                self.last_daily_report_date = str(data.get("last_daily_report_date") or "")
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not read checkpoint file %s: %s", self.path, exc)

    def save(self) -> None:
        """Save state atomically to JSON file."""
        data = {
            "last_sequence": self.last_sequence,
            "last_cb_status": self.last_cb_status,
            "last_margin_alerted": self.last_margin_alerted,
            "last_digest_timestamp": self.last_digest_timestamp,
            "last_update_id": self.last_update_id,
            "last_daily_report_date": self.last_daily_report_date,
            "saved_at_utc": datetime.now(UTC).isoformat(),
        }
        tmp_path = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(self.path)
        except OSError as exc:
            logger.warning("Failed to save checkpoint to %s: %s", self.path, exc)


class TelegramNotifierDaemon:
    """Decoupled sidecar daemon monitoring live paper trading telemetry."""

    def __init__(
        self,
        config: TelegramConfig,
        storage_dir: Path,
        checkpoint_path: Path | None = None,
        poll_interval: float = 3.0,
        digest_interval: float = 3600.0,
        daily_report_utc_hour: int = 0,
        daily_report_enabled: bool = True,
        client: TelegramNotifierClient | None = None,
    ) -> None:
        self.config = config
        self.storage_dir = Path(storage_dir)
        self.poll_interval = max(poll_interval, 0.5)
        self.digest_interval = max(digest_interval, 10.0)
        self.daily_report_utc_hour = daily_report_utc_hour
        self.daily_report_enabled = daily_report_enabled

        cp_path = checkpoint_path or (self.storage_dir / "telegram-checkpoint.json")
        self.checkpoint = CheckpointState(cp_path)

        self.telemetry_reader = TelemetryReader(self.storage_dir)
        self.client = client or TelegramNotifierClient(self.config)
        self._shutdown_requested = False

    def request_shutdown(self) -> None:
        """Signal the daemon to stop gracefully."""
        self._shutdown_requested = True

    def _connect_readonly(self, db_path: Path) -> sqlite3.Connection | None:
        """Open a SQLite database strictly in read-only mode."""
        if not db_path.is_file():
            return None
        try:
            uri_path = db_path.resolve().as_posix()
            uri = f"file:{uri_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=1.0)
            conn.execute("PRAGMA query_only = ON;")
            conn.execute("PRAGMA busy_timeout = 1000;")
            return conn
        except sqlite3.Error as exc:
            logger.debug("Could not open read-only connection to %s: %s", db_path, exc)
            return None

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        """Check if a table exists in the database."""
        try:
            cur = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            )
            return cur.fetchone() is not None
        except sqlite3.Error:
            return False

    def poll_new_ledger_events(self) -> int:
        """Query paper-ledger.sqlite3 for new trades and dispatch alerts."""
        ledger_db = self.storage_dir / "paper-ledger.sqlite3"
        conn = self._connect_readonly(ledger_db)
        if conn is None:
            return 0

        dispatched_count = 0
        try:
            if not self._table_exists(conn, "paper_ledger_events"):
                return 0

            cursor = conn.execute(
                """
                SELECT sequence, event, trade_id, symbol, side, quantity,
                       fill_price, occurred_at, approval_id, entry_fee, exit_fee,
                       slippage_cost, gross_pnl, net_pnl
                FROM paper_ledger_events
                WHERE sequence > ?
                ORDER BY sequence ASC
                """,
                (self.checkpoint.last_sequence,),
            )

            rows = cursor.fetchall()
            for row in rows:
                seq = int(row[0])
                ev_type = str(row[1]).lower()
                trade_id = str(row[2])
                symbol = str(row[3])
                side = str(row[4])
                quantity = str(row[5])
                fill_price = str(row[6])
                occurred_at = str(row[7])
                approval_id = str(row[8] or "")
                entry_fee = str(row[9] or "0.0")
                exit_fee = str(row[10] or "0.0")
                slippage_cost = str(row[11] or "0.0")
                gross_pnl = str(row[12] or "0.0")
                net_pnl = str(row[13] or "0.0")

                payload: dict[str, Any] = {
                    "sequence": seq,
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "fill_price": fill_price,
                    "occurred_at": occurred_at,
                    "approval_id": approval_id,
                    "entry_fee": entry_fee,
                    "exit_fee": exit_fee,
                    "slippage_cost": slippage_cost,
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                }

                if ev_type == "open":
                    logger.info("Dispatching Trade Opened alert for %s (seq %d)", trade_id, seq)
                    self.client.send_alert("trade_open", payload)
                    dispatched_count += 1
                elif ev_type == "close":
                    logger.info("Dispatching Trade Closed alert for %s (seq %d)", trade_id, seq)
                    self.client.send_alert("trade_close", payload)
                    dispatched_count += 1

                self.checkpoint.last_sequence = seq

            if rows:
                self.checkpoint.save()

        except sqlite3.Error as exc:
            logger.warning("Error reading ledger events: %s", exc)
        finally:
            conn.close()

        return dispatched_count

    def poll_circuit_breaker_and_margin(self) -> None:
        """Check daemon health for circuit breaker transitions and margin utilization."""
        snapshot = self.telemetry_reader.poll()
        if snapshot.is_stale and not snapshot.daemon.pid:
            return

        current_status = snapshot.daemon.circuit_breaker_status
        # Circuit Breaker transition check
        if current_status != self.checkpoint.last_cb_status:
            logger.warning(
                "Circuit breaker transition detected: %s -> %s",
                self.checkpoint.last_cb_status,
                current_status,
            )
            if current_status in ("HALTED", "THROTTLED"):
                self.client.send_alert(
                    "circuit_breaker",
                    {
                        "status": current_status,
                        "breaker_type": "Circuit Breaker Tripped",
                        "metric_name": "Volatility / Spread Risk",
                        "current_value": current_status,
                        "threshold_value": "NORMAL",
                        "action_taken": "Trading throttled or halted by risk supervisor.",
                    },
                )
            elif (
                self.checkpoint.last_cb_status in ("HALTED", "THROTTLED")
                and current_status == "NORMAL"
            ):
                self.client.send_alert(
                    "circuit_breaker",
                    {
                        "status": "NORMAL",
                        "breaker_type": "Risk Supervison Normal",
                        "metric_name": "Circuit Breaker Restored",
                        "current_value": "NORMAL",
                        "threshold_value": "NORMAL",
                        "action_taken": "Normal paper trading operations resumed.",
                    },
                )
            self.checkpoint.last_cb_status = current_status
            self.checkpoint.save()

        # Margin Utilization Hysteresis Check
        util_pct = snapshot.margin.margin_utilization_pct
        if util_pct >= 70.0 and not self.checkpoint.last_margin_alerted:
            logger.warning("Margin utilization high (%.1f%% >= 70%%)", util_pct)
            self.client.send_alert(
                "margin_warning",
                {
                    "margin_utilization_pct": util_pct,
                    "reserve_buffer_pct": snapshot.margin.reserve_buffer_pct,
                    "current_cash": snapshot.margin.current_cash,
                    "current_equity": snapshot.margin.current_equity,
                    "message": "Margin utilization exceeded 70% threshold.",
                },
            )
            self.checkpoint.last_margin_alerted = True
            self.checkpoint.save()
        elif util_pct < 65.0 and self.checkpoint.last_margin_alerted:
            # Cooled down below 65% floor: reset hysteresis
            self.checkpoint.last_margin_alerted = False
            self.checkpoint.save()

    def poll_periodic_digest(self) -> None:
        """Emit periodic portfolio digest alert if interval has elapsed."""
        now = time.time()
        # Initialize if never run
        if self.checkpoint.last_digest_timestamp == 0.0:
            self.checkpoint.last_digest_timestamp = now
            self.checkpoint.save()
            return

        if now - self.checkpoint.last_digest_timestamp >= self.digest_interval:
            logger.info(
                "Dispatching periodic portfolio digest (interval %.1fs)", self.digest_interval
            )
            snapshot = self.telemetry_reader.poll()
            health_payload: dict[str, Any] = {
                "daemon_status": snapshot.daemon.status,
                "pid": snapshot.daemon.pid,
                "uptime_seconds": snapshot.daemon.uptime_seconds,
                "current_equity": snapshot.margin.current_equity,
                "current_cash": snapshot.margin.current_cash,
                "realized_pnl": snapshot.margin.realized_pnl,
                "margin_utilization_pct": snapshot.margin.margin_utilization_pct,
                "reserve_buffer_pct": snapshot.margin.reserve_buffer_pct,
                "feed_throughput_per_sec": snapshot.daemon.feed_throughput_per_sec,
            }
            positions_payload: list[dict[str, Any]] = [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "mark_price": p.mark_price,
                    "leverage": p.leverage,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for p in snapshot.positions.values()
            ]

            self.client.send_alert(
                "portfolio_digest",
                {"health": health_payload, "positions": positions_payload},
            )
            self.checkpoint.last_digest_timestamp = now
            self.checkpoint.save()

    def poll_daily_performance_report(self) -> bool:
        """Evaluate 00:00 UTC schedule and dispatch daily report once per calendar day."""
        if not self.daily_report_enabled:
            return False

        now_utc = datetime.now(UTC)
        if now_utc.hour != self.daily_report_utc_hour:
            return False

        # Evaluation date: yesterday's trading day when triggered at 00:xx UTC
        report_date = (
            now_utc.date()
            if self.daily_report_utc_hour > 0
            else (now_utc - timedelta(days=1)).date()
        ).isoformat()

        if self.checkpoint.last_daily_report_date == report_date:
            return False

        logger.info(
            "Triggering scheduled daily performance report for %s at %s",
            report_date,
            now_utc.isoformat(),
        )
        try:
            from autonomous_futures.analytics import (
                format_daily_performance_report,
                generate_and_persist_daily_report,
            )

            report_data = generate_and_persist_daily_report(
                storage_dir=self.storage_dir,
                report_date=report_date,
            )
            text = format_daily_performance_report(report_data)
            self.client.send_message(text)
            self.checkpoint.last_daily_report_date = report_date
            self.checkpoint.save()
            return True
        except Exception as exc:
            logger.error(
                "Failed to generate or dispatch daily performance report: %s",
                exc,
                exc_info=True,
            )
            return False

    def handle_interactive_commands(self) -> int:
        """Poll Telegram getUpdates and respond to authorized commands."""
        offset = self.checkpoint.last_update_id + 1 if self.checkpoint.last_update_id else None
        updates = self.client.get_updates(offset=offset, timeout=0)
        handled = 0

        for update in updates:
            try:
                upd_id = update.get("update_id")
                if upd_id is not None:
                    self.checkpoint.last_update_id = max(
                        self.checkpoint.last_update_id, int(upd_id)
                    )

                msg = update.get("message") or update.get("channel_post")
                if not isinstance(msg, dict):
                    continue

                chat_obj = msg.get("chat")
                if not isinstance(chat_obj, dict):
                    continue
                sender_chat_id = str(chat_obj.get("id", "") or "")
                text = str(msg.get("text", "")).strip()

                # Security: chat ID whitelist enforcement
                allowed_chat_id = str(self.config.chat_id).strip()
                if sender_chat_id != allowed_chat_id:
                    logger.warning(
                        "Ignored Telegram command from unauthorized chat_id=%s (configured: %s)",
                        sender_chat_id,
                        allowed_chat_id,
                    )
                    continue

                if not text.startswith("/"):
                    continue

                cmd = text.split()[0].lower().split("@")[0]
                reply = self._execute_command(cmd)
                self.client.send_message(reply, chat_id=sender_chat_id)
                handled += 1
            except Exception as exc:
                logger.warning("Failed to process Telegram update: %s", exc)
                continue

        if updates:
            self.checkpoint.save()

        return handled

    def _execute_command(self, cmd: str) -> str:
        """Execute a read-only Telegram command and return formatted text."""
        snapshot = self.telemetry_reader.poll()

        if cmd == "/status":
            d = snapshot.daemon
            m = snapshot.margin
            s = snapshot.safety
            hours = int(d.uptime_seconds // 3600)
            mins = int((d.uptime_seconds % 3600) // 60)
            return (
                f"🤖 *DAEMON STATUS*\n"
                f"─────────────────────────\n"
                f"• *Status*: *{escape_markdown_v2(d.status)}* (PID {escape_markdown_v2(d.pid)})\n"
                f"• *Uptime*: {escape_markdown_v2(f'{hours}h {mins}m')}\n"
                f"• *Cash*: ${escape_markdown_v2(m.current_cash)} USDT\n"
                f"• *Equity*: ${escape_markdown_v2(m.current_equity)} USDT\n"
                f"• *Margin Utilization*: {escape_markdown_v2(m.margin_utilization_pct)}%\n"
                f"• *Reserve Buffer*: {escape_markdown_v2(m.reserve_buffer_pct)}%\n"
                f"• *Circuit Breaker*: {escape_markdown_v2(d.circuit_breaker_status)}\n"
                f"• *Zero Orders Invariant*: {escape_markdown_v2(str(s.orders_submitted == 0))}"
            )

        if cmd == "/positions":
            if not snapshot.positions:
                return "ℹ️ *No active paper positions.*"
            msg = "📈 *ACTIVE PAPER POSITIONS*\n─────────────────────────\n"
            for pos in snapshot.positions.values():
                msg += (
                    f"• *{escape_markdown_v2(pos.symbol)}*: {escape_markdown_v2(pos.side)} "
                    f"{escape_markdown_v2(pos.quantity)} @ ${escape_markdown_v2(pos.entry_price)} "
                    f"({escape_markdown_v2(pos.leverage)}x)\n"
                    f"  Unrealized PnL: ${escape_markdown_v2(pos.unrealized_pnl)} "
                    f"({escape_markdown_v2(pos.pnl_pct)}%)\n"
                )
            return msg

        if cmd == "/analytics":
            ledger_db = self.storage_dir / "paper-ledger.sqlite3"
            conn = self._connect_readonly(ledger_db)
            if conn is None or not self._table_exists(conn, "paper_ledger_events"):
                return "ℹ️ *QUANTITATIVE ANALYTICS*\n• No closed trades recorded yet."
            conn.close()
            try:
                from autonomous_futures.analytics import (
                    format_analytics_command_reply,
                    generate_daily_performance_report,
                )

                report = generate_daily_performance_report(
                    storage_dir=self.storage_dir,
                    days=7,
                )
                return format_analytics_command_reply(report.to_dict())
            except Exception as exc:
                logger.warning("Error generating analytics report: %s", exc)
                return f"⚠️ Analytics temporarily unavailable: {escape_markdown_v2(str(exc))}"

        if cmd == "/pnl":
            ledger_db = self.storage_dir / "paper-ledger.sqlite3"
            conn = self._connect_readonly(ledger_db)
            if conn is None or not self._table_exists(conn, "paper_ledger_events"):
                return "ℹ️ *PNL SUMMARY*\n• Closed Trades: 0\n• Realized PnL: $0.00 USDT"
            try:
                cur = conn.execute(
                    """
                    SELECT count(*),
                           sum(CASE WHEN cast(net_pnl as real) > 0 THEN 1 ELSE 0 END),
                           sum(cast(net_pnl as real)),
                           sum(cast(entry_fee as real) + cast(exit_fee as real))
                    FROM paper_ledger_events
                    WHERE event = 'close'
                    """
                )
                row = cur.fetchone()
                total = int(row[0] or 0)
                wins = int(row[1] or 0)
                net_pnl = float(row[2] or 0.0)
                fees = float(row[3] or 0.0)
                win_rate = (wins / total * 100.0) if total > 0 else 0.0

                # Per-asset breakdown
                cur_assets = conn.execute(
                    """
                    SELECT symbol,
                           count(*),
                           sum(CASE WHEN cast(net_pnl as real) > 0 THEN 1 ELSE 0 END),
                           sum(cast(net_pnl as real)),
                           sum(cast(entry_fee as real) + cast(exit_fee as real))
                    FROM paper_ledger_events
                    WHERE event = 'close'
                    GROUP BY symbol
                    ORDER BY sum(cast(net_pnl as real)) DESC
                    """
                )
                asset_rows = cur_assets.fetchall()
                asset_lines: list[str] = []
                for a_row in asset_rows:
                    sym = str(a_row[0])
                    a_trades = int(a_row[1] or 0)
                    a_wins = int(a_row[2] or 0)
                    a_pnl = float(a_row[3] or 0.0)
                    a_win_rate = (a_wins / a_trades * 100.0) if a_trades > 0 else 0.0
                    a_sign = "\\+" if a_pnl >= 0 else "\\-"
                    a_pnl_str = escape_markdown_v2(f"{abs(a_pnl):.4f}")
                    sym_esc = escape_markdown_v2(sym)
                    asset_lines.append(
                        f"• *{sym_esc}*: {a_sign}${a_pnl_str} USDT "
                        f"\\({escape_markdown_v2(str(a_trades))} trades, "
                        f"{escape_markdown_v2(f'{a_win_rate:.1f}')}% win\\)"
                    )

                asset_section = ""
                if asset_lines:
                    asset_section = "\n\n*Per\\-Asset Realized PnL*:\n" + "\n".join(asset_lines)

                pnl_sign = "\\+" if net_pnl >= 0 else "\\-"
                pnl_abs = escape_markdown_v2(f"{abs(net_pnl):.4f}")

                return (
                    f"📊 *PNL & PERFORMANCE SUMMARY*\n"
                    f"─────────────────────────\n"
                    f"• *Closed Trades*: {escape_markdown_v2(str(total))}\n"
                    f"• *Winning Trades*: {escape_markdown_v2(str(wins))}\n"
                    f"• *Win Rate*: {escape_markdown_v2(f'{win_rate:.1f}')}%\n"
                    f"• *Net Realized PnL*: {pnl_sign}${pnl_abs} USDT\n"
                    f"• *Total Fees Paid*: ${escape_markdown_v2(f'{fees:.4f}')} USDT"
                    f"{asset_section}"
                )
            except sqlite3.Error as exc:
                return f"⚠️ PnL summary temporarily unavailable: {escape_markdown_v2(str(exc))}"
            finally:
                conn.close()

        if cmd == "/ping":
            now_iso = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
            return f"🏓 *Pong\\!* Latency: <1ms \\| UTC: {escape_markdown_v2(now_iso)}"

        if cmd == "/help":
            return (
                "🤖 *Autonomous Futures Bot — Command Center*\n"
                "─────────────────────────\n"
                "Available Commands:\n"
                "• `/status` — Live daemon health, cash, equity & margin\n"
                "• `/positions` — Currently active paper positions\n"
                "• `/pnl` — Realized PnL summary and per-asset breakdown\n"
                "• `/analytics` — Institutional quantitative risk metrics & asset rankings\n"
                "• `/ping` — Latency probe and health confirmation\n"
                "• `/help` — Show this command reference\n"
                "• `/kill` — Emergency shutdown notice (read-only)"
            )

        if cmd == "/kill":
            return (
                "⚠️ *SAFETY INVARIANT NOTICE*\n"
                "─────────────────────────\n"
                "Remote execution commands like `/kill` are disabled by design.\n"
                "The Autonomous Futures Bot enforces strict zero-order execution authority.\n"
                "To stop the daemon, access Kainode VPS via SSH and execute:\n"
                "`sudo systemctl stop autonomous-futures-paper-live.service`"
            )

        return (
            f"❓ Unknown command `{escape_markdown_v2(cmd)}`. Use `/help` for available commands."
        )

    def run_single_cycle(self) -> None:
        """Run a single execution cycle (for --once flag or loop iteration)."""
        self.poll_new_ledger_events()
        self.poll_circuit_breaker_and_margin()
        self.poll_periodic_digest()
        self.poll_daily_performance_report()
        self.handle_interactive_commands()

    def run(self) -> int:
        """Run continuous sidecar polling loop until shutdown signal."""
        logger.info(
            "Starting Telegram Notifier Sidecar [storage_dir=%s, dry_run=%s, poll_interval=%.1fs]",
            self.storage_dir,
            self.client.is_dry_run,
            self.poll_interval,
        )

        while not self._shutdown_requested:
            try:
                self.run_single_cycle()
            except Exception as exc:
                logger.error("Error in sidecar polling cycle: %s", exc, exc_info=True)

            # Sleep in short increments for responsive signal handling
            sleep_remaining = self.poll_interval
            while sleep_remaining > 0 and not self._shutdown_requested:
                step = min(sleep_remaining, 0.5)
                time.sleep(step)
                sleep_remaining -= step

        logger.info("Telegram Notifier Sidecar shut down cleanly.")
        self.checkpoint.save()
        self.client.close()
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Telegram notifier sidecar."""
    parser = argparse.ArgumentParser(
        prog="run_telegram_notifier.py",
        description="Autonomous Futures Bot: Real-Time Telegram Telemetry & Trade Alerts Sidecar",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path(os.environ.get("AUTONOMOUS_FUTURES_STORAGE_DIR", "artifacts/paper_live")),
        help="Path to paper trading storage directory containing SQLite ledgers and health JSON",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("TELEGRAM_POLL_INTERVAL", "3.0")),
        help="Polling interval in seconds for ledger and health checkpoints",
    )
    parser.add_argument(
        "--digest-interval",
        type=float,
        default=float(os.environ.get("TELEGRAM_DIGEST_INTERVAL", "3600.0")),
        help="Periodic digest report interval in seconds",
    )
    parser.add_argument(
        "--bot-token",
        type=str,
        default=None,
        help="Telegram bot token (overrides environment variables)",
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=None,
        help="Authorized Telegram chat ID (overrides environment variables)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=bool(os.environ.get("TELEGRAM_DRY_RUN")),
        help="Operate in dry-run/mock mode without sending live Telegram HTTP requests",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Execute a single telemetry ingestion cycle and command check, then exit",
    )
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        default=None,
        help=(
            "Custom path to persist sequence checkpoint state "
            "(defaults to storage_dir/telegram-checkpoint.json)"
        ),
    )
    parser.add_argument(
        "--daily-report-utc-hour",
        type=int,
        default=int(os.environ.get("TELEGRAM_DAILY_REPORT_HOUR_UTC", "0")),
        help="UTC hour (0-23) to trigger daily performance report dispatch",
    )
    parser.add_argument(
        "--disable-daily-report",
        action="store_true",
        default=bool(os.environ.get("TELEGRAM_DISABLE_DAILY_REPORT", False)),
        help="Disable automatic 00:00 UTC daily performance report dispatch",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level",
    )
    return parser


def main() -> int:
    """CLI entrypoint for Telegram notifier sidecar."""
    parser = build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = resolve_telegram_credentials(
        bot_token=args.bot_token,
        chat_id=args.chat_id,
        dry_run=args.dry_run,
        storage_dir=args.storage_dir,
    )

    daemon = TelegramNotifierDaemon(
        config=config,
        storage_dir=args.storage_dir,
        checkpoint_path=args.checkpoint_file,
        poll_interval=args.poll_interval,
        digest_interval=args.digest_interval,
        daily_report_utc_hour=args.daily_report_utc_hour,
        daily_report_enabled=not args.disable_daily_report,
    )

    # Set up signal handlers for graceful shutdown
    def _handle_signal(signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received termination signal %s. Initiating graceful shutdown...", sig_name)
        daemon.request_shutdown()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if args.once:
        logger.info("Executing single telemetry and command cycle (--once)")
        daemon.run_single_cycle()
        daemon.client.close()
        logger.info("Single cycle completed successfully.")
        return 0

    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
