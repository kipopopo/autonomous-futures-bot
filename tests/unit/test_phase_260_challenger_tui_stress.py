"""Phase 260 Milestone M1: Empirical Challenger & Stress-Testing Suite.

Adversarially tests and validates:
1. Numerical edge cases: negative cash/equity, zero capital, massive PnL,
   margin utilization at 0%, 80%, 150%, micro/massive spreads, extreme ATR.
2. CLI boundary testing: extreme dimensions (40x10, 80x24, 110x28, 300x100),
   out-of-bounds refresh rates, non-existent and corrupted storage directories.
3. Read-only verification: cryptographic proof of zero file modification,
   zero temporary/WAL file leakage, and read-only filesystem compatibility.
4. Empirical reproduction of layout off-by-one border width violations.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.tui.dashboard import Dashboard  # noqa: E402
from autonomous_futures.tui.formatters import (  # noqa: E402
    Ansi,
    format_atr,
    format_currency,
    format_pnl,
    format_spread_bps,
    format_utilization_meter,
    render_progress_bar,
    strip_ansi,
    visible_len,
)
from autonomous_futures.tui.layout import Panel  # noqa: E402
from autonomous_futures.tui.telemetry import (  # noqa: E402
    DEFAULT_SYMBOLS,
    TelemetryReader,
    TuiTelemetrySnapshot,
)
from scripts.monitor_live_paper_tui import (  # noqa: E402
    parse_cli_args,
    resolve_terminal_dimensions,
    run_snapshot_mode,
)


def _compute_dir_hashes(directory: Path) -> dict[str, str]:
    """Compute SHA-256 hashes for all files in directory."""
    hashes: dict[str, str] = {}
    if not directory.exists():
        return hashes
    for item in sorted(directory.iterdir()):
        if item.is_file():
            content = item.read_bytes()
            hashes[item.name] = hashlib.sha256(content).hexdigest()
    return hashes


def _populate_mock_storage(directory: Path) -> None:
    """Populate realistic mock JSON and SQLite databases in storage directory."""
    directory.mkdir(parents=True, exist_ok=True)

    # 1. Health JSON
    health_payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "daemon_status": "RUNNING",
        "pid": 222449,
        "uptime_seconds": 3600.0,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "last_heartbeat_utc": datetime.now(UTC).isoformat(),
        "symbols_monitored": list(DEFAULT_SYMBOLS),
        "feed_messages_received": 150000,
        "feed_reconnects_count": 0,
        "circuit_breaker_status": "NORMAL",
        "starting_capital_usdt": "100.00",
        "current_cash_usdt": "104.25",
        "current_equity_usdt": "106.80",
        "margin_utilization_pct": 24.5,
        "reserve_buffer_pct": 75.5,
        "zero_order_safety_invariants": {
            "orders_submitted": 0,
            "execution_authority": False,
            "live_trading_activation": False,
            "paper_activation": True,
            "promotion_state": "unpromoted",
            "zero_private_credentials": True,
        },
        "market_regimes": {
            "BTCUSDT": {
                "bid_price": "90500.00",
                "ask_price": "90500.80",
                "mid_price": "90500.40",
                "spread_bps": "0.09",
                "rolling_atr": "45.20",
            },
            "ETHUSDT": {
                "bid_price": "2650.00",
                "ask_price": "2650.20",
                "mid_price": "2650.10",
                "spread_bps": "0.75",
                "rolling_atr": "3.15",
            },
            "SOLUSDT": {
                "bid_price": "182.40",
                "ask_price": "182.45",
                "mid_price": "182.425",
                "spread_bps": "2.74",
                "rolling_atr": "0.85",
            },
            "DOGEUSDT": {
                "bid_price": "0.1520",
                "ask_price": "0.1521",
                "mid_price": "0.15205",
                "spread_bps": "6.58",
                "rolling_atr": "0.0012",
            },
        },
        "active_positions": {
            "BTCUSDT": {
                "side": "LONG",
                "quantity": "0.001",
                "entry_price": "90200.00",
                "leverage": "2.0",
            }
        },
    }
    json_bytes = json.dumps(health_payload).encode("utf-8")
    (directory / "paper-daemon-health.json").write_bytes(json_bytes)

    # 2. Ledger DB
    ledger_db = directory / "paper-ledger.sqlite3"
    with sqlite3.connect(ledger_db) as conn:
        conn.execute(
            """
            CREATE TABLE paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                trade_id TEXT,
                symbol TEXT,
                side TEXT,
                quantity TEXT,
                fill_price TEXT,
                occurred_at TEXT,
                event TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                net_pnl TEXT,
                approval_id TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 't1', 'BTCUSDT', 'LONG', '0.001', '90000.00', '2026-09-06T12:00:00Z',
             'close', '0.0360', '0.0362', '0.4500', 'app1'),
            (2, 't2', 'ETHUSDT', 'SHORT', '0.05', '2600.00', '2026-09-06T12:10:00Z',
             'close', '0.0520', '0.0521', '-0.2000', 'app2')
            """
        )

    # 3. Lifecycle DB
    lifecycle_db = directory / "paper-lifecycle.sqlite3"
    with sqlite3.connect(lifecycle_db) as conn:
        conn.execute(
            """
            CREATE TABLE paper_lifecycle_marks (
                sequence INTEGER PRIMARY KEY,
                trade_id TEXT,
                payload TEXT
            )
            """
        )
        mark_payload_1 = json.dumps(
            {
                "symbol": "BTCUSDT",
                "mark_price": "90500.00",
                "mark_to_market_pnl": "0.30",
                "pnl_pct": "0.0033",
                "trailing_stop_price": "89800.00",
                "reason_codes": ["take_profit_hit"],
            }
        )
        conn.execute("INSERT INTO paper_lifecycle_marks VALUES (1, 't1', ?)", (mark_payload_1,))

    # 4. Observations DB
    observations_db = directory / "paper-observations.sqlite3"
    with sqlite3.connect(observations_db) as conn:
        conn.execute(
            """
            CREATE TABLE paper_observations (
                sequence INTEGER PRIMARY KEY,
                payload TEXT
            )
            """
        )
        obs_payload = json.dumps({"peak_equity": "108.50"})
        conn.execute("INSERT INTO paper_observations VALUES (1, ?)", (obs_payload,))


# =============================================================================
# SUITE 1: NUMERICAL EDGE CASES
# =============================================================================


class TestNumericalEdgeCases:
    """Stress-test numerical edge cases across calculations, formatters, and rendering."""

    def test_negative_cash_and_equity(self) -> None:
        """Negative cash and negative equity must calculate correct PnL and format properly."""
        reader = TelemetryReader(Path("dummy_path"))
        health_raw: dict[str, Any] = {
            "starting_capital_usdt": "100.00",
            "current_cash_usdt": "-50.00",
            "current_equity_usdt": "-120.00",
            "margin_utilization_pct": 125.0,
            "reserve_buffer_pct": -25.0,
        }
        margin_snap = reader._parse_margin(health_raw, None)

        assert margin_snap.current_cash == Decimal("-50.00")
        assert margin_snap.current_equity == Decimal("-120.00")
        assert margin_snap.realized_pnl == Decimal("-150.00")  # -50 - 100
        assert margin_snap.realized_pnl_pct == Decimal("-150.0")  # (-150/100)*100
        assert margin_snap.unrealized_pnl == Decimal("-70.00")  # -120 - (-50)
        assert margin_snap.unrealized_pnl_pct == Decimal("-70.0")

        # Test formatters on negative values
        c_str = format_currency(margin_snap.current_cash, color=True)
        assert "-$50.00" in strip_ansi(c_str)
        pnl_str = format_pnl(margin_snap.realized_pnl, pct=margin_snap.realized_pnl_pct, color=True)
        assert "-$150.00 (-150.0%)" in strip_ansi(pnl_str)

        # Ensure Dashboard panel builder runs cleanly without exception
        snap = TuiTelemetrySnapshot(
            timestamp=datetime.now(UTC),
            storage_dir=Path("dummy_path"),
            is_stale=False,
            daemon=reader._build_offline_daemon_snapshot(datetime.now(UTC)),
            margin=margin_snap,
            regimes=reader._parse_regimes(None, {}),
            positions={},
            recent_closed_trades=(),
            safety=reader._parse_safety(None),
        )
        dashboard = Dashboard()
        panel = dashboard._build_margin_panel(snap, width=80)
        lines = panel.render()
        assert len(lines) >= 5
        # Body lines maintain width invariant
        for line in lines[1:-1]:
            assert visible_len(line) == 80

    def test_zero_starting_capital(self) -> None:
        """Zero starting capital must not raise ZeroDivisionError."""
        reader = TelemetryReader(Path("dummy_path"))
        health_raw: dict[str, Any] = {
            "starting_capital_usdt": "0.00",
            "current_cash_usdt": "15.00",
            "current_equity_usdt": "20.00",
            "margin_utilization_pct": 0.0,
            "reserve_buffer_pct": 100.0,
        }
        margin_snap = reader._parse_margin(health_raw, None)

        assert margin_snap.starting_capital == Decimal("0.00")
        assert margin_snap.realized_pnl == Decimal("15.00")
        assert margin_snap.realized_pnl_pct == Decimal("0")  # Protected division by zero
        assert margin_snap.unrealized_pnl == Decimal("5.00")
        assert margin_snap.unrealized_pnl_pct == Decimal("0")  # Protected division by zero

    def test_massive_pnl_values(self) -> None:
        """Massive PnL values must format properly with thousands grouping."""
        huge_val = Decimal("1234567890123.45")
        formatted = format_pnl(huge_val, color=False)
        assert formatted == "+$1,234,567,890,123.45"

        huge_neg = Decimal("-987654321098.76")
        formatted_neg = format_pnl(huge_neg, color=False)
        assert "-$987,654,321,098.76" in formatted_neg

        # Verify Panel interior lines obey inner width budget
        panel = Panel(
            title="MASSIVE PNL TEST",
            lines=[f"Cash: {formatted} │ PnL: {formatted_neg}"],
            width=80,
        )
        rendered = panel.render()
        # Interior line is padded/truncated strictly to width 80
        assert visible_len(rendered[1]) == 80
        assert visible_len(rendered[-1]) == 80

    def test_margin_utilization_meter_thresholds(self) -> None:
        """Test progress bar at 0%, 50%, 80%, 150%, and negative bounds."""
        # 1. 0%
        bar_0 = render_progress_bar(pct=0.0, width=10, color=False)
        assert bar_0 == "[░░░░░░░░░░]"
        meter_0 = format_utilization_meter(0.0, width=10, enabled=False)
        assert "  0.0% / 80.0% max" in meter_0

        # 2. 80% (Warning ceiling)
        bar_80 = render_progress_bar(pct=80.0, width=10, color=True, warn_pct=80.0)
        assert Ansi.BRIGHT_RED in bar_80
        assert "[████████░░]" in strip_ansi(bar_80)

        # 3. 150% (Exceeded cap - must clamp visual bar to 100% without crashing)
        bar_150 = render_progress_bar(pct=150.0, width=10, color=True, warn_pct=80.0)
        assert Ansi.BRIGHT_RED in bar_150
        assert "[██████████]" in strip_ansi(bar_150)
        meter_150 = format_utilization_meter(150.0, width=10, enabled=False)
        assert "150.0% / 80.0% max" in meter_150

        # 4. Negative utilization (Clamped to 0)
        bar_neg = render_progress_bar(pct=-25.0, width=10, color=False)
        assert bar_neg == "[░░░░░░░░░░]"

        # 5. ASCII-only mode
        bar_ascii = render_progress_bar(pct=60.0, width=10, color=False, ascii_only=True)
        assert bar_ascii == "[######----]"

    def test_micro_and_massive_spreads(self) -> None:
        """Test spreads ranging from micro-basis points to extreme volatility spikes."""
        # Micro spread: 0.00001 bps
        micro = format_spread_bps(Decimal("0.00001"), color=True)
        assert " 0.00 bps" in strip_ansi(micro)
        assert Ansi.BRIGHT_GREEN in micro

        # Warning spread: 5.50 bps
        warn = format_spread_bps(Decimal("5.50"), color=True)
        assert " 5.50 bps" in strip_ansi(warn)
        assert Ansi.BRIGHT_YELLOW in warn

        # Halt spread: 25.00 bps
        halt = format_spread_bps(Decimal("25.00"), color=True)
        assert "(HALT)" in strip_ansi(halt)
        assert Ansi.BRIGHT_RED in halt

        # Extreme spread: 50000 bps
        massive = format_spread_bps(Decimal("50000.0"), color=True)
        assert "50000.00 bps (HALT)" in strip_ansi(massive)
        assert Ansi.BRIGHT_RED in massive

        # Negative spread (crossed book)
        neg_spread = format_spread_bps(Decimal("-2.50"), color=False)
        assert neg_spread == "-2.50 bps"

    def test_extreme_atr_formatting(self) -> None:
        """ATR values at 0, microscopic, and massive scales with Decimal rounding."""
        assert format_atr(Decimal("0.0"), decimals=4) == "0.0000"
        assert format_atr(Decimal("0.00000001"), decimals=4) == "0.0000"
        # Arithmetic rounding (ROUND_HALF_UP): 5 rounds up to 7
        assert format_atr(Decimal("9999999.98765"), decimals=4) == "9999999.9877"
        assert format_atr(Decimal("9999999.98775"), decimals=4) == "9999999.9878"
        assert format_atr(Decimal("9999999.98766"), decimals=4) == "9999999.9877"


# =============================================================================
# SUITE 2: CLI BOUNDARY TESTING
# =============================================================================


class TestCliBoundaryExecution:
    """Stress-test CLI parsing, dimension handling, and invalid inputs."""

    def test_terminal_dimension_resolution(self) -> None:
        """resolve_terminal_dimensions enforces minimum safety constraints."""
        # Minimum allowed resolution is 40x10
        w, h = resolve_terminal_dimensions(override_width=10, override_height=5)
        assert w == 40
        assert h == 10

        # Normal resolution
        w, h = resolve_terminal_dimensions(override_width=120, override_height=35)
        assert w == 120
        assert h == 35

    def test_cli_argument_parser_boundaries(self) -> None:
        """Enforce strict parser validation for refresh-rate and dimensions."""
        # Valid arguments
        args = parse_cli_args(["--refresh-rate", "0.5", "--width", "80", "--height", "24"])
        assert args.refresh_rate == 0.5
        assert args.width == 80
        assert args.height == 24

        # Zero or negative refresh rate
        with pytest.raises(SystemExit):
            parse_cli_args(["--refresh-rate", "0.0"])

        with pytest.raises(SystemExit):
            parse_cli_args(["--refresh-rate", "-1.0"])

        # Sub-minimum width
        with pytest.raises(SystemExit):
            parse_cli_args(["--width", "39"])

        # Sub-minimum height
        with pytest.raises(SystemExit):
            parse_cli_args(["--height", "9"])

    def test_non_existent_storage_directory(self, tmp_path: Path) -> None:
        """Non-existent directory must return offline fallback snapshot with status code 0."""
        ghost_dir = tmp_path / "non_existent_dir_xyz_123"
        assert not ghost_dir.exists()

        reader = TelemetryReader(storage_dir=ghost_dir)
        snap = reader.poll()

        assert snap.is_stale is True
        assert snap.daemon.status == "OFFLINE"
        assert snap.margin.starting_capital == Decimal("100.00")
        assert len(snap.regimes) == 4

        # Snapshot mode must succeed and exit cleanly
        exit_code = run_snapshot_mode(
            storage_dir=ghost_dir,
            color_enabled=False,
            ascii_only=True,
            width_override=80,
            height_override=24,
        )
        assert exit_code == 0

    def test_corrupted_storage_artifacts(self, tmp_path: Path) -> None:
        """Malformed JSON and garbage SQLite files must be handled gracefully."""
        corrupt_dir = tmp_path / "corrupt_storage"
        corrupt_dir.mkdir()

        # Write invalid JSON
        (corrupt_dir / "paper-daemon-health.json").write_text(
            "{invalid_json: true,", encoding="utf-8"
        )

        # Write corrupt SQLite file (not a valid database)
        (corrupt_dir / "paper-ledger.sqlite3").write_bytes(
            b"THIS IS NOT A VALID SQLITE DATABASE FILE"
        )

        reader = TelemetryReader(storage_dir=corrupt_dir)
        snap = reader.poll()

        # Telemetry reader safely catches decode/db errors and returns fallback
        assert snap.is_stale is True
        assert snap.daemon.status == "OFFLINE"
        assert snap.recent_closed_trades == ()

        dashboard = Dashboard(storage_dir=corrupt_dir)
        rendered = dashboard.render(width=80, height=24)
        assert "AUTONOMOUS FUTURES BOT" in rendered


# =============================================================================
# SUITE 3: STRICT READ-ONLY STORAGE INVARIANCE
# =============================================================================


class TestReadOnlyStorageInvariance:
    """Cryptographically prove zero file modification in storage directory."""

    def test_storage_byte_and_hash_invariance(self, tmp_path: Path) -> None:
        """Zero file modifications or temporary artifacts created during continuous polling."""
        storage_dir = tmp_path / "storage_invariance"
        _populate_mock_storage(storage_dir)

        # Capture initial state
        initial_hashes = _compute_dir_hashes(storage_dir)
        initial_files = set(initial_hashes.keys())
        initial_mtimes = {f: (storage_dir / f).stat().st_mtime_ns for f in initial_files}

        assert "paper-daemon-health.json" in initial_files
        assert "paper-ledger.sqlite3" in initial_files
        assert "paper-lifecycle.sqlite3" in initial_files
        assert "paper-observations.sqlite3" in initial_files

        # Execute 50 sequential poll operations
        reader = TelemetryReader(storage_dir=storage_dir)
        for _ in range(50):
            snap = reader.poll()
            assert snap.daemon.status == "RUNNING"
            assert snap.margin.current_cash == Decimal("104.25")

        # Execute 50 dashboard render operations (compact and wide)
        dashboard = Dashboard(storage_dir=storage_dir)
        for _ in range(25):
            dashboard.render(width=80, height=24)
            dashboard.render(width=120, height=30)

        # Execute 5 snapshot mode runs
        for _ in range(5):
            run_snapshot_mode(
                storage_dir=storage_dir,
                color_enabled=False,
                ascii_only=False,
                width_override=80,
                height_override=24,
            )

        # Capture post-execution state
        post_hashes = _compute_dir_hashes(storage_dir)
        post_files = set(post_hashes.keys())
        post_mtimes = {f: (storage_dir / f).stat().st_mtime_ns for f in post_files}

        # 1. No new files created (zero -wal, zero -shm, zero lock files)
        assert post_files == initial_files, f"File set mutated: {post_files ^ initial_files}"

        # 2. SHA-256 hashes must be 100% byte-for-byte identical
        for fname in initial_files:
            assert post_hashes[fname] == initial_hashes[fname], (
                f"File {fname} hash changed from {initial_hashes[fname]} to {post_hashes[fname]}"
            )

        # 3. Modification timestamps must remain unaltered
        for fname in initial_files:
            assert post_mtimes[fname] == initial_mtimes[fname], (
                f"File {fname} was modified: mtime changed"
            )

    def test_filesystem_readonly_permission_enforcement(self, tmp_path: Path) -> None:
        """Reader functions perfectly when database files are marked read-only on disk."""
        ro_dir = tmp_path / "ro_storage"
        _populate_mock_storage(ro_dir)

        # Mark all database files read-only (chmod 444)
        for f in ro_dir.glob("*.sqlite3"):
            f.chmod(stat.S_IREAD)

        # Query via TelemetryReader
        reader = TelemetryReader(storage_dir=ro_dir)
        snap = reader.poll()

        assert snap.daemon.status == "RUNNING"
        assert len(snap.recent_closed_trades) == 2
        assert snap.recent_closed_trades[0].symbol == "ETHUSDT"
        assert snap.recent_closed_trades[1].symbol == "BTCUSDT"

        # Restore permissions for clean test cleanup
        for f in ro_dir.glob("*.sqlite3"):
            f.chmod(stat.S_IWRITE | stat.S_IREAD)


# =============================================================================
# SUITE 4: ADVERSARIAL REPRODUCTION OF LAYOUT OFF-BY-ONE DEFECTS
# =============================================================================


class TestLayoutOffByOneDefects:
    """Adversarial stress-testing proving border width invariant violations."""

    def test_panel_title_width_overflow_defect(self) -> None:
        """Panel.render() title line produces width + 1 due to fill_len = w - 4 - len."""
        target_w = 80
        p = Panel(title="TEST TITLE", width=target_w)
        lines = p.render()

        # Contractual claim in layout.py docstring:
        # "Every rendered line r satisfies: visible_len(r) == width"
        #
        # Empirical finding:
        # Top title line produces 81 columns (w + 1) because layout.py computes:
        # fill_len = max(0, w - 4 - title_vlen)
        # However, 5 fixed framing characters exist (tl, h, ' ', ' ', tr),
        # so fill_len must be max(0, w - 5 - title_vlen).
        top_line_len = visible_len(lines[0])
        bottom_line_len = visible_len(lines[-1])

        assert bottom_line_len == target_w, "Bottom line correctly matches target width"
        # Assert that the top line strictly matches target width
        assert top_line_len == target_w, f"Expected border width {target_w}, got {top_line_len}"

    def test_divider_label_width_overflow_defect(self) -> None:
        """Panel.render_divider() with label produces exact target width."""
        target_w = 80
        p = Panel(width=target_w)

        # Without label: correct width 80
        div_no_label = p.render_divider()
        assert visible_len(div_no_label) == target_w

        # With label: produces exact width 80
        div_with_label = p.render_divider("SECTION")
        assert visible_len(div_with_label) == target_w, (
            f"Expected divider width {target_w}, got {visible_len(div_with_label)}"
        )

    def test_dashboard_wide_split_compound_overflow(self, tmp_path: Path) -> None:
        """Wide 2-column dashboard layout strictly matches 110 terminal width."""
        _populate_mock_storage(tmp_path)
        dashboard = Dashboard(storage_dir=tmp_path)

        # On a 110-column terminal, wide layout activates:
        # left_w = (110 - 1) // 2 = 54
        # right_w = 110 - 54 - 1 = 55
        # compose_horizontal_split produces exact 110-column lines
        output = dashboard.render(width=110, height=28)
        rendered_lines = output.splitlines()

        # Find middle two-column lines (e.g. line 4: Portfolio Margin & Regimes)
        middle_line = rendered_lines[4]
        assert visible_len(middle_line) == 110, (
            f"Expected wide split width 110, got {visible_len(middle_line)}"
        )
