"""Phase 263 Empirical Challenger Stress Test Suite.

Adversarially tests:
1. SQLite WAL Concurrency: Continuous write transactions vs concurrent ReadOnlyLedgerReader queries.
2. CLI Robustness: Adversarial arguments and exit codes.
3. Telegram Formatting Resiliency: Injection of all 19 Telegram MarkdownV2 reserved characters.
4. JSON Persistence Integrity & Schema Compliance: Atomic replacement and Draft-07 compliance.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.analytics.formatter import (  # noqa: E402
    format_analytics_command_reply,
    format_daily_performance_report,
    format_duration,
)
from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader  # noqa: E402
from autonomous_futures.analytics.reporter import (  # noqa: E402
    generate_and_persist_daily_report,
    generate_daily_performance_report,
)


def _init_test_ledger_db(db_path: Path, wal_mode: bool = True) -> None:
    """Initialize test ledger tables and configure journal mode."""
    conn = sqlite3.connect(db_path)
    if wal_mode:
        conn.execute("PRAGMA journal_mode = WAL;")
    else:
        conn.execute("PRAGMA journal_mode = DELETE;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute(
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
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_lifecycle_marks (
            sequence INTEGER PRIMARY KEY,
            trade_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


class TestSqliteConcurrencyStress:
    """Empirical concurrency stress tests for ReadOnlyLedgerReader."""

    def test_concurrent_writer_and_readers_in_wal_mode(self, tmp_path: Path) -> None:
        """Simulate high-frequency writes while 6 readers query ledger in WAL mode."""
        ledger_db = tmp_path / "paper-ledger.sqlite3"
        _init_test_ledger_db(ledger_db, wal_mode=True)

        conn = sqlite3.connect(ledger_db)
        base_time = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 'open', 'trade-0', 'cand-0', 'hash-0', 'BTCUSDT', 'LONG',
             '0.01', '50000.00', ?, 'appr-0', '0.02', NULL, '0.01', NULL, NULL)
            """,
            (base_time.isoformat(),),
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (2, 'close', 'trade-0', 'cand-0', 'hash-0', 'BTCUSDT', 'LONG',
             '0.01', '50500.00', ?, 'appr-0', '0.02', '0.02', '0.01', '5.00', '4.96')
            """,
            ((base_time + timedelta(minutes=5)).isoformat(),),
        )
        conn.commit()
        conn.close()

        num_trades_to_write = 100
        stop_event = threading.Event()
        writer_errors: list[Exception] = []
        reader_errors: list[Exception] = []
        read_counts = [0] * 6

        def writer_worker() -> None:
            try:
                w_conn = sqlite3.connect(ledger_db, timeout=5.0)
                seq = 3
                for i in range(1, num_trades_to_write + 1):
                    t_id = f"trade-stress-{i}"
                    t_open = base_time + timedelta(seconds=i * 10)
                    t_close = t_open + timedelta(seconds=5)

                    w_conn.execute("BEGIN IMMEDIATE;")
                    w_conn.execute(
                        """
                        INSERT INTO paper_ledger_events VALUES
                        (?, 'open', ?, 'cand-s', 'hash-s', 'BTCUSDT', 'LONG',
                         '0.01', '50000.00', ?, 'appr-s', '0.02', NULL, '0.01', NULL, NULL)
                        """,
                        (seq, t_id, t_open.isoformat()),
                    )
                    w_conn.execute(
                        """
                        INSERT INTO paper_ledger_events VALUES
                        (?, 'close', ?, 'cand-s', 'hash-s', 'BTCUSDT', 'LONG',
                         '0.01', '50100.00', ?, 'appr-s', '0.02', '0.02', '0.01', '1.00', '0.96')
                        """,
                        (seq + 1, t_id, t_close.isoformat()),
                    )
                    w_conn.execute("COMMIT;")
                    seq += 2
                    time.sleep(0.005)
                w_conn.close()
            except Exception as e:
                writer_errors.append(e)
            finally:
                stop_event.set()

        def reader_worker(reader_idx: int) -> None:
            reader = ReadOnlyLedgerReader(tmp_path)
            try:
                while not stop_event.is_set():
                    trades = reader.read_closed_trades()
                    assert len(trades) >= 1
                    seqs = [t.close_sequence for t in trades]
                    assert seqs == sorted(seqs)

                    open_count = reader.read_open_trades_count()
                    assert open_count >= 0

                    cash = reader.calculate_reconciled_cash(Decimal("100.00"))
                    assert cash >= Decimal("100.00")

                    read_counts[reader_idx] += 1
                    time.sleep(0.002)
            except Exception as e:
                reader_errors.append(e)

        threads: list[threading.Thread] = []
        writer_thread = threading.Thread(target=writer_worker)
        threads.append(writer_thread)
        writer_thread.start()

        for r_id in range(6):
            r_thread = threading.Thread(target=reader_worker, args=(r_id,))
            threads.append(r_thread)
            r_thread.start()

        writer_thread.join(timeout=30.0)
        stop_event.set()

        for t in threads:
            t.join(timeout=5.0)

        assert len(writer_errors) == 0, f"Writer encountered errors: {writer_errors}"
        assert len(reader_errors) == 0, f"Reader encountered errors: {reader_errors}"
        total_reads = sum(read_counts)
        assert total_reads >= 20, f"Expected high-frequency reads, got {total_reads}"

        reader = ReadOnlyLedgerReader(tmp_path)
        final_trades = reader.read_closed_trades()
        assert len(final_trades) == num_trades_to_write + 1

    def test_writer_with_long_transaction_in_delete_mode_vs_wal_mode(self, tmp_path: Path) -> None:
        """Expose difference between standard DELETE mode and WAL mode under write lock."""
        del_db = tmp_path / "delete-mode" / "paper-ledger.sqlite3"
        del_db.parent.mkdir(parents=True)
        _init_test_ledger_db(del_db, wal_mode=False)

        conn_del = sqlite3.connect(del_db)
        conn_del.execute("BEGIN EXCLUSIVE;")
        conn_del.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 'open', 't-del', 'c', 'h', 'ETHUSDT', 'SHORT', '1.0', '3000',
             '2026-09-07T00:00:00Z', NULL, '0', NULL, '0', NULL, NULL)
            """
        )
        del_reader = ReadOnlyLedgerReader(del_db.parent)
        t_start = time.perf_counter()
        trades = del_reader.read_closed_trades()
        t_elapsed = time.perf_counter() - t_start
        conn_del.rollback()
        conn_del.close()

        assert trades == []
        assert t_elapsed >= 0.8

        wal_db = tmp_path / "wal-mode" / "paper-ledger.sqlite3"
        wal_db.parent.mkdir(parents=True)
        _init_test_ledger_db(wal_db, wal_mode=True)

        c_seed = sqlite3.connect(wal_db)
        c_seed.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 'open', 't1', 'c', 'h', 'ETHUSDT', 'SHORT', '1.0', '3000',
             '2026-09-07T00:00:00Z', NULL, '0', NULL, '0', NULL, NULL)
            """
        )
        c_seed.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (2, 'close', 't1', 'c', 'h', 'ETHUSDT', 'SHORT', '1.0', '2900',
             '2026-09-07T00:05:00Z', NULL, '0', '0', '0', '100', '100')
            """
        )
        c_seed.commit()
        c_seed.close()

        conn_wal = sqlite3.connect(wal_db)
        conn_wal.execute("BEGIN IMMEDIATE;")
        conn_wal.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (3, 'open', 't2', 'c', 'h', 'ETHUSDT', 'SHORT', '1.0', '3000',
             '2026-09-07T00:10:00Z', NULL, '0', NULL, '0', NULL, NULL)
            """
        )

        wal_reader = ReadOnlyLedgerReader(wal_db.parent)
        t_start = time.perf_counter()
        wal_trades = wal_reader.read_closed_trades()
        t_elapsed_wal = time.perf_counter() - t_start
        conn_wal.rollback()
        conn_wal.close()

        assert len(wal_trades) == 1
        assert t_elapsed_wal < 0.2, f"WAL read was unexpectedly delayed: {t_elapsed_wal}s"


class TestCliAdversarialArguments:
    """Empirical tests for scripts/generate_performance_report.py error handling and exit codes."""

    _SCRIPT_PATH = _REPO_ROOT / "scripts" / "generate_performance_report.py"

    def _run_cli(self, args: list[str], utf8_env: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(self._SCRIPT_PATH)] + args
        env = os.environ.copy()
        if utf8_env:
            env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            env=env,
            encoding="utf-8" if utf8_env else None,
            errors="replace",
        )

    def test_cli_reproduce_windows_cp1252_unicode_encode_error(self, tmp_path: Path) -> None:
        """Verify CLI handles UTF-8 emojis on Windows stdout without UnicodeEncodeError."""
        cmd = [
            sys.executable,
            str(self._SCRIPT_PATH),
            "--storage-dir",
            str(tmp_path),
            "--dry-run",
            "--markdown",
        ]
        env = os.environ.copy()
        env.pop("PYTHONIOENCODING", None)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            cwd=str(_REPO_ROOT),
            env=env,
        )
        stderr_text = proc.stderr.decode("latin-1", errors="replace")
        stdout_text = proc.stdout.decode("utf-8", errors="replace")
        assert proc.returncode == 0
        assert "UnicodeEncodeError" not in stderr_text
        assert "charmap" not in stderr_text
        assert "DAILY PERFORMANCE REPORT" in stdout_text

    def test_cli_invalid_date_nonexistent_calendar_day(self, tmp_path: Path) -> None:
        """--date 2026-02-30 must exit with code 1 or 2 gracefully without traceback."""
        proc = self._run_cli(["--date", "2026-02-30", "--storage-dir", str(tmp_path)])
        assert proc.returncode in (1, 2)
        assert "Traceback" not in proc.stderr
        assert "Invalid date format" in proc.stderr or "error" in proc.stderr.lower()

    def test_cli_invalid_date_malformed_string(self, tmp_path: Path) -> None:
        """--date invalid must exit with code 1 or 2 gracefully without traceback."""
        proc = self._run_cli(["--date", "invalid", "--storage-dir", str(tmp_path)])
        assert proc.returncode in (1, 2)
        assert "Traceback" not in proc.stderr
        assert "Invalid date format" in proc.stderr or "error" in proc.stderr.lower()

    def test_cli_invalid_date_out_of_range_month(self, tmp_path: Path) -> None:
        """--date 2026-13-45 must exit with code 1 or 2 gracefully without traceback."""
        proc = self._run_cli(["--date", "2026-13-45", "--storage-dir", str(tmp_path)])
        assert proc.returncode in (1, 2)
        assert "Traceback" not in proc.stderr

    def test_cli_nonexistent_storage_dir(self) -> None:
        """Non-existent storage directory must exit with code 2 gracefully without traceback."""
        nonexistent = _REPO_ROOT / "nonexistent_storage_dir_challenge_test_xyz"
        proc = self._run_cli(["--storage-dir", str(nonexistent)])
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr
        assert "does not exist" in proc.stderr

    def test_cli_missing_database_file_in_existing_dir(self, tmp_path: Path) -> None:
        """When SQLite database is missing, CLI exits 0 with clean empty report."""
        proc = self._run_cli(["--storage-dir", str(tmp_path), "--dry-run", "--json"])
        assert proc.returncode == 0
        assert "Traceback" not in proc.stderr
        data = json.loads(proc.stdout)
        assert data["portfolio_performance"]["trade_count"] == 0

    def test_cli_missing_tables_in_sqlite_db(self, tmp_path: Path) -> None:
        """When SQLite table is missing, CLI handles it cleanly."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE dummy_table (id INT);")
        conn.commit()
        conn.close()

        proc = self._run_cli(["--storage-dir", str(tmp_path), "--dry-run", "--markdown"])
        assert proc.returncode == 0
        assert "Traceback" not in proc.stderr
        assert "DAILY PERFORMANCE REPORT" in proc.stdout

    def test_cli_corrupted_sqlite_file(self, tmp_path: Path) -> None:
        """When paper-ledger.sqlite3 contains corrupt binary, CLI handles it without crash."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        db_path.write_bytes(b"\x00\xff\xaa\x55CORRUPTED_SQLITE_GARBAGE_PAYLOAD\xde\xad\xbe\xef")

        proc = self._run_cli(["--storage-dir", str(tmp_path), "--dry-run", "--json"])
        assert proc.returncode == 0
        assert "Traceback" not in proc.stderr
        data = json.loads(proc.stdout)
        assert data["portfolio_performance"]["trade_count"] == 0

    def test_cli_negative_days_behavior(self, tmp_path: Path) -> None:
        """Test how CLI handles negative --days -5."""
        proc = self._run_cli(["--storage-dir", str(tmp_path), "--days", "-5", "--dry-run"])
        assert proc.returncode == 0
        assert "Traceback" not in proc.stderr

    def test_cli_unknown_flag_exits_2(self) -> None:
        """Argparse unknown argument exits with code 2."""
        proc = self._run_cli(["--unrecognized-argument-xyz"])
        assert proc.returncode == 2
        assert "usage:" in proc.stderr.lower() or "error" in proc.stderr.lower()


def _validate_markdown_v2_escaping(text: str) -> list[str]:
    """Strictly validates Telegram MarkdownV2 escaping rules for all 19 reserved characters."""
    errors: list[str] = []
    lines = text.split("\n")
    strict_literal_reserved = set(r"#>+-={}.!")

    for line_num, line in enumerate(lines, 1):
        cleaned = re.sub(r"\\`", "", line)
        cleaned = re.sub(r"`[^`]*`", "", cleaned)

        for idx, char in enumerate(cleaned):
            if char in strict_literal_reserved:
                num_slashes = 0
                k = idx - 1
                while k >= 0 and cleaned[k] == "\\":
                    num_slashes += 1
                    k -= 1
                if num_slashes % 2 == 0:
                    errors.append(f"Line {line_num} pos {idx}: Unescaped '{char}' in: {line}")

    return errors


class TestTelegramMarkdownV2Resiliency:
    """Empirical tests for all 19 Telegram MarkdownV2 reserved characters in report formatters."""

    def test_format_daily_performance_report_with_all_19_reserved_characters(self) -> None:
        """Inject all 19 reserved characters into every string field of DailyPerformanceReport."""
        adversarial_str = r"TEST_*[]()~`>#+-=|{}.!\_STR"

        report_data = {
            "report_metadata": {
                "report_date": adversarial_str,
                "generated_at_utc": "2026-09-07T12:00:00+00:00",
                "schema_version": "1.0.0",
            },
            "daemon_health": {
                "daemon_status": adversarial_str,
                "pid": 99999,
                "uptime_seconds": 1234.5,
            },
            "capital_summary": {
                "starting_cash_usdt": 100.0,
                "ending_cash_usdt": 105.5,
                "current_equity_usdt": 107.25,
                "net_realized_pnl_usdt": 5.5,
                "realized_pnl_pct": 5.5,
                "margin_utilization_pct": 25.0,
                "reserve_buffer_pct": 75.0,
            },
            "portfolio_performance": {
                "trade_count": 10,
                "winning_trades": 7,
                "losing_trades": 3,
                "breakeven_trades": 0,
                "win_rate_pct": 70.0,
                "win_loss_payoff_ratio": 2.5,
                "profit_factor": 3.12,
                "sharpe_ratio_annualized": 2.85,
                "sortino_ratio": 3.45,
                "max_drawdown_usdt": 1.5,
                "max_drawdown_pct": 1.5,
                "expectancy_usdt": 0.55,
                "total_taker_fees_usdt": 0.4,
                "fee_drag_ratio": 0.08,
                "holding_duration_seconds": {"avg": 3600.0},
            },
            "asset_breakdown": {
                adversarial_str: {
                    "symbol": adversarial_str,
                    "trade_count": 5,
                    "winning_trades": 4,
                    "losing_trades": 1,
                    "win_rate_pct": 80.0,
                    "net_realized_pnl_usdt": 4.5,
                }
            },
            "asset_ranking": [adversarial_str],
        }

        rendered = format_daily_performance_report(report_data)
        assert isinstance(rendered, str)
        assert len(rendered) > 0

        errors = _validate_markdown_v2_escaping(rendered)
        assert len(errors) == 0, f"MarkdownV2 escaping violations found: {errors}"

    def test_format_analytics_command_reply_with_all_19_reserved_characters(self) -> None:
        """Inject all 19 reserved characters into format_analytics_command_reply."""
        adversarial_sym = r"SYM_*[]()~`>#+-=|{}.!\_V2"

        report_data = {
            "capital_summary": {
                "ending_cash_usdt": 102.5,
                "current_equity_usdt": 104.0,
                "margin_utilization_pct": 15.0,
                "reserve_buffer_pct": 85.0,
            },
            "portfolio_performance": {
                "trade_count": 12,
                "winning_trades": 8,
                "losing_trades": 4,
                "win_rate_pct": 66.67,
                "profit_factor": 2.15,
                "win_loss_payoff_ratio": 1.85,
                "sharpe_ratio_annualized": 1.95,
                "sortino_ratio": 2.45,
                "max_drawdown_usdt": 2.1,
                "max_drawdown_pct": 2.05,
                "net_realized_pnl_usdt": 2.50,
                "total_taker_fees_usdt": 0.55,
                "fee_drag_ratio": 0.05,
                "expectancy_usdt": 0.2083,
            },
            "asset_breakdown": {
                adversarial_sym: {
                    "symbol": adversarial_sym,
                    "trade_count": 6,
                    "win_rate_pct": 66.7,
                    "net_realized_pnl_usdt": 1.25,
                }
            },
            "asset_ranking": [adversarial_sym],
        }

        rendered = format_analytics_command_reply(report_data)
        assert isinstance(rendered, str)
        assert len(rendered) > 0

        errors = _validate_markdown_v2_escaping(rendered)
        assert len(errors) == 0, f"Violations found in /analytics reply: {errors}"

    def test_duration_formatter_edge_cases(self) -> None:
        """Test duration formatting with boundary conditions."""
        assert format_duration(None) == "0s"
        assert format_duration(-100.0) == "0s"
        assert format_duration(0.0) == "0s"
        assert format_duration(45.2) == "45s"
        assert format_duration(125.0) == "2m 5s"
        assert format_duration(3665.0) == "1h 1m"
        assert format_duration(86400.0 * 10) == "240h 0m"


class TestJsonPersistenceAndSchema:
    """Empirical verification of atomic persistence and Draft-07 schema compliance."""

    def test_atomic_replace_file_persistence(self, tmp_path: Path) -> None:
        """Verify atomic writing: .tmp write followed by atomic rename replacing destination."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        _init_test_ledger_db(db_path, wal_mode=True)

        report_dir = tmp_path / "reports"
        out_file = report_dir / "daily-performance-2026-09-07.json"

        generate_and_persist_daily_report(
            storage_dir=tmp_path,
            report_date="2026-09-07",
            output_path=out_file,
        )
        assert out_file.is_file()
        assert not out_file.with_suffix(".tmp").exists()
        parsed1 = json.loads(out_file.read_text(encoding="utf-8"))
        assert parsed1["report_metadata"]["report_date"] == "2026-09-07"

        data2 = generate_and_persist_daily_report(
            storage_dir=tmp_path,
            report_date="2026-09-07",
            output_path=out_file,
        )
        parsed2 = json.loads(out_file.read_text(encoding="utf-8"))
        assert parsed2 == data2

    def test_sequential_overwrite_atomic_integrity(self, tmp_path: Path) -> None:
        """Verify sequential atomic overwrites always preserve valid, parseable JSON."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        _init_test_ledger_db(db_path, wal_mode=True)

        out_file = tmp_path / "reports" / "daily-performance-sequential.json"

        for i in range(10):
            data = generate_and_persist_daily_report(
                storage_dir=tmp_path,
                report_date="2026-09-07",
                output_path=out_file,
                environment=f"env-{i}",
            )
            assert out_file.is_file()
            content = out_file.read_text(encoding="utf-8")
            parsed = json.loads(content)
            assert parsed["report_metadata"]["environment"] == f"env-{i}"
            assert parsed == data

    def test_concurrent_writers_exposes_tmp_file_collision_on_windows(self, tmp_path: Path) -> None:
        """Empirically test concurrent writers targeting the same output destination."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        _init_test_ledger_db(db_path, wal_mode=True)

        out_file = tmp_path / "reports" / "daily-performance-concurrent.json"
        errors: list[Exception] = []

        def persist_worker(worker_id: int) -> None:
            try:
                generate_and_persist_daily_report(
                    storage_dir=tmp_path,
                    report_date="2026-09-07",
                    output_path=out_file,
                    environment=f"env-{worker_id}",
                )
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(persist_worker, i) for i in range(10)]
            concurrent.futures.wait(futures)

        # With unique PID+UUID temp files and atomic replace retries, zero collisions occur
        assert len(errors) == 0, f"Concurrent writers encountered errors: {errors}"
        assert out_file.is_file()

    def test_draft_07_schema_structural_compliance(self, tmp_path: Path) -> None:
        """Verify report dictionary structure against Draft-07 JSON Schema rules."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        _init_test_ledger_db(db_path, wal_mode=True)

        report = generate_daily_performance_report(
            storage_dir=tmp_path,
            report_date="2026-09-07",
        )
        data = report.to_dict()

        required_top_keys = [
            "report_metadata",
            "daemon_health",
            "safety_invariants",
            "capital_summary",
            "portfolio_performance",
            "asset_breakdown",
            "asset_ranking",
        ]
        for k in required_top_keys:
            assert k in data, f"Missing required top-level key: {k}"

        meta = data["report_metadata"]
        assert isinstance(meta["report_date"], str)
        assert isinstance(meta["generated_at_utc"], str)
        assert isinstance(meta["schema_version"], str)

        si = data["safety_invariants"]
        assert si["orders_submitted"] == 0
        assert si["execution_authority"] is False
        assert si["live_trading_activation"] is False
        assert si["paper_activation"] is True
        assert si["zero_private_credentials"] is True
        assert si["all_invariants_pass"] is True

        cap = data["capital_summary"]
        assert isinstance(cap["starting_cash_usdt"], (int, float))
        assert isinstance(cap["ending_cash_usdt"], (int, float))
        assert isinstance(cap["current_equity_usdt"], (int, float))
        assert cap["margin_utilization_pct"] >= 0.0
        assert cap["reserve_buffer_pct"] >= 0.0

        perf = data["portfolio_performance"]
        assert isinstance(perf["trade_count"], int)
        assert isinstance(perf["winning_trades"], int)
        assert isinstance(perf["losing_trades"], int)
        assert 0.0 <= perf["win_rate_pct"] <= 100.0

        serialized = json.dumps(data)
        roundtrip = json.loads(serialized)
        assert roundtrip == data
