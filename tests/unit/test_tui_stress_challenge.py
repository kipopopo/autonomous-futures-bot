"""Empirical stress testing and adversarial fuzzing suite for Phase 260 TUI components.

Adversarial challenge coverage:
1. Box alignment invariant fuzzing: arbitrary strings, ANSI codes, widths (40-200).
2. Cold start & missing directory/database resilience: empty dirs, corrupt files.
3. Dashboard rendering across multi-resolution matrix (compact, tall, wide).
4. SQLite read-only enforcement (?mode=ro, PRAGMA query_only=ON) and busy timeout.
5. CLI driver snapshot mode and parameter boundary validation.
"""

from __future__ import annotations

import json
import random
import sqlite3
import string
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from autonomous_futures.tui.dashboard import Dashboard
from autonomous_futures.tui.formatters import (
    Ansi,
    pad_visible,
    strip_ansi,
    truncate_visible,
    visible_len,
)
from autonomous_futures.tui.layout import (
    ASCII_BOX,
    DOUBLE_BOX,
    HEAVY_BOX,
    LIGHT_BOX,
    Panel,
    compose_horizontal_split,
    format_table_row,
)
from autonomous_futures.tui.telemetry import (
    DEFAULT_SYMBOLS,
    TelemetryReader,
    TuiTelemetrySnapshot,
)

# -----------------------------------------------------------------------------
# Challenge 1: Box Alignment Invariant Fuzzing & ANSI Handling
# -----------------------------------------------------------------------------


def test_strip_ansi_comprehensive_matrix() -> None:
    """Verify strip_ansi correctly removes all ANSI sequences while preserving text."""
    test_cases = [
        ("", ""),
        ("Plain ASCII text", "Plain ASCII text"),
        (f"{Ansi.RED}Red Text{Ansi.RESET}", "Red Text"),
        (f"{Ansi.BOLD}{Ansi.BRIGHT_GREEN}Bold Bright Green{Ansi.RESET}", "Bold Bright Green"),
        (f"{Ansi.BG_RED}{Ansi.WHITE}White on Red{Ansi.RESET}", "White on Red"),
        ("\033[1;32;40mCompound Color\033[0m", "Compound Color"),
        ("\033[?25hCursor Show\033[?25lCursor Hide", "Cursor ShowCursor Hide"),
        ("\033[2J\033[HClear Screen", "Clear Screen"),
        (
            f"{Ansi.RED}Part1{Ansi.RESET} Normal {Ansi.BLUE}Part2{Ansi.RESET}",
            "Part1 Normal Part2",
        ),
        ("No escapes at all 12345!@#$%", "No escapes at all 12345!@#$%"),
        ("Nested \033[31mRed \033[1mBold Red \033[0mReset", "Nested Red Bold Red Reset"),
    ]

    for raw, expected in test_cases:
        assert strip_ansi(raw) == expected
        assert visible_len(raw) == len(expected)


def test_truncate_visible_invariants() -> None:
    """Verify truncate_visible preserves length invariants and cleans ANSI codes."""
    # Text shorter than max_width is untouched
    assert truncate_visible("Short", 10) == "Short"
    assert truncate_visible(f"{Ansi.RED}Short{Ansi.RESET}", 10) == f"{Ansi.RED}Short{Ansi.RESET}"

    # Edge cases
    assert truncate_visible("Hello", 0) == ""
    assert truncate_visible("Hello", -5) == ""
    assert truncate_visible("Hello", 1) == "…"

    # Truncated string visible length is strictly <= max_width
    for w in range(2, 20):
        res = truncate_visible("This is a long test string that will be truncated", w)
        assert visible_len(res) <= w
        assert res.endswith("…")
        assert "\033" not in res

    # Styled string truncation
    styled = f"{Ansi.BRIGHT_GREEN}Supercalifragilisticexpialidocious{Ansi.RESET}"
    trunc_styled = truncate_visible(styled, 15)
    assert visible_len(trunc_styled) <= 15
    assert trunc_styled.endswith(f"…{Ansi.RESET}")


def test_pad_visible_invariants() -> None:
    """Verify pad_visible produces exact visible length across alignment modes."""
    styled = f"{Ansi.CYAN}Data{Ansi.RESET}"
    raw_vlen = visible_len(styled)
    assert raw_vlen == 4

    for target_w in range(4, 30):
        left_padded = pad_visible(styled, target_w, align="left")
        assert visible_len(left_padded) == target_w
        assert left_padded.startswith(styled)

        right_padded = pad_visible(styled, target_w, align="right")
        assert visible_len(right_padded) == target_w
        assert right_padded.endswith(styled)

        center_padded = pad_visible(styled, target_w, align="center")
        assert visible_len(center_padded) == target_w

    # If width <= visible_len, untouched
    assert pad_visible(styled, 2) == styled


@pytest.mark.parametrize("box_style", [LIGHT_BOX, HEAVY_BOX, DOUBLE_BOX, ASCII_BOX])
def test_panel_visible_width_invariant_fuzzing(box_style: Any) -> None:
    """Fuzz 300 random panels and assert visible_len(row) == width for 100% of rows."""
    rng = random.Random(42)

    ansi_colors = [
        "",
        Ansi.RED,
        Ansi.GREEN,
        Ansi.YELLOW,
        Ansi.BLUE,
        Ansi.BRIGHT_RED,
        Ansi.BRIGHT_GREEN,
        Ansi.BRIGHT_YELLOW,
        Ansi.DIM,
        Ansi.BOLD,
    ]

    for _ in range(300):
        width = rng.randint(40, 200)
        pad_content = rng.choice([True, False])
        border_col = rng.choice(ansi_colors)
        title_col = rng.choice(ansi_colors)

        # Generate title (empty, short, or long beyond width)
        title_type = rng.choice(["none", "short", "long", "styled"])
        if title_type == "none":
            title = ""
        elif title_type == "short":
            title = "Test Title"
        elif title_type == "long":
            title = "Extremely Long Panel Title That Exceeds Width " * 10
        else:
            title = f"{rng.choice(ansi_colors)}Styled Title{Ansi.RESET}"

        # Generate 0 to 8 lines with random contents
        num_lines = rng.randint(0, 8)
        lines: list[str] = []
        for _ in range(num_lines):
            line_len = rng.randint(0, 250)
            chars = "".join(
                rng.choices(string.ascii_letters + string.digits + " !@#$%", k=line_len)
            )
            if rng.random() > 0.5:
                color = rng.choice(ansi_colors)
                chars = f"{color}{chars}{Ansi.RESET}"
            lines.append(chars)

        panel = Panel(
            title=title,
            lines=lines,
            width=width,
            box_chars=box_style,
            border_color=border_col,
            title_color=title_col,
            pad_content=pad_content,
        )

        rendered_rows = panel.render()
        assert len(rendered_rows) == len(lines) + 2

        # 100% of rendered rows MUST have visible_len == width
        for row_idx, row in enumerate(rendered_rows):
            vlen = visible_len(row)
            assert vlen == width, (
                f"Row {row_idx} violation: visible_len={vlen} != width={width}\n"
                f"Row content: {repr(row)}\n"
                f"Stripped content: {repr(strip_ansi(row))}"
            )

        # Divider line invariant
        divider = panel.render_divider("Section Divider")
        assert visible_len(divider) == width
        empty_divider = panel.render_divider("")
        assert visible_len(empty_divider) == width


def test_compose_horizontal_split_invariants() -> None:
    """Verify horizontal split maintains uniform line widths across uneven column heights."""
    rng = random.Random(123)

    for _ in range(50):
        left_w = rng.randint(20, 60)
        right_w = rng.randint(20, 60)
        gap = rng.randint(1, 4)

        left_lines = [pad_visible(f"Left {i}", left_w) for i in range(rng.randint(1, 6))]
        right_lines = [pad_visible(f"Right {j}", right_w) for j in range(rng.randint(1, 6))]

        split_rows = compose_horizontal_split(left_lines, right_lines, gap=gap)
        expected_total_w = left_w + gap + right_w

        assert len(split_rows) == max(len(left_lines), len(right_lines))
        for r in split_rows:
            assert visible_len(r) == expected_total_w


def test_format_table_row_invariants() -> None:
    """Verify format_table_row aligns columns to exact total width."""
    widths = [10, 15, 8, 12]
    cells = ["SYMBOL", "PRICE", "SPREAD", "STATUS"]
    row = format_table_row(cells, widths, sep=" ")
    expected_w = sum(widths) + (len(widths) - 1) * 1
    assert visible_len(row) == expected_w

    # Cells exceeding widths are safely clipped
    long_cells = ["BTCUSDT_VERY_LONG", "$999,999.999999", "123456789 bps", "TRIPPED_CIRCUIT"]
    row_clipped = format_table_row(long_cells, widths, sep=" ")
    assert visible_len(row_clipped) == expected_w


# -----------------------------------------------------------------------------
# Challenge 2: Cold Start, Missing Directories & File Corruption Resilience
# -----------------------------------------------------------------------------


def test_telemetry_reader_cold_start_empty_dir(tmp_path: Path) -> None:
    """Verify TelemetryReader on an empty directory gracefully yields default snapshot."""
    empty_dir = tmp_path / "empty_paper_dir"
    empty_dir.mkdir()

    reader = TelemetryReader(empty_dir)
    snapshot = reader.poll()

    assert isinstance(snapshot, TuiTelemetrySnapshot)
    assert snapshot.is_stale is True
    assert snapshot.daemon.status == "OFFLINE"
    assert snapshot.daemon.pid is None
    assert snapshot.daemon.feed_messages_received == 0
    assert snapshot.daemon.feed_throughput_per_sec == 0.0

    # Margin snapshot defaults
    assert snapshot.margin.starting_capital == Decimal("100.00")
    assert snapshot.margin.current_cash == Decimal("100.00")
    assert snapshot.margin.current_equity == Decimal("100.00")
    assert snapshot.margin.realized_pnl == Decimal("0.00")
    assert snapshot.margin.unrealized_pnl == Decimal("0.00")
    assert snapshot.margin.margin_utilization_pct == 0.0
    assert snapshot.margin.reserve_buffer_pct == 100.0

    # Regimes snapshot defaults
    for sym in DEFAULT_SYMBOLS:
        assert sym in snapshot.regimes
        assert snapshot.regimes[sym].status == "WARMUP"
        assert snapshot.regimes[sym].mid_price > Decimal("0")

    # Positions and trades defaults
    assert snapshot.positions == {}
    assert snapshot.recent_closed_trades == ()

    # Safety invariants defaults
    s = snapshot.safety
    assert s.volatility_cb == "NORMAL"
    assert s.spread_cb == "NORMAL"
    assert s.orders_submitted == 0
    assert s.execution_authority is False
    assert s.live_trading_activation is False
    assert s.paper_activation is True
    assert s.promotion_state == "unpromoted"
    assert s.zero_private_credentials is True
    assert s.all_invariants_pass is True


def test_telemetry_reader_nonexistent_directory(tmp_path: Path) -> None:
    """Verify TelemetryReader handles non-existent directory without exceptions."""
    non_existent = tmp_path / "non_existent_path_xyz"
    reader = TelemetryReader(non_existent)
    snapshot = reader.poll()
    assert isinstance(snapshot, TuiTelemetrySnapshot)
    assert snapshot.is_stale is True
    assert snapshot.daemon.status == "OFFLINE"


def test_telemetry_reader_corrupt_files_resilience(tmp_path: Path) -> None:
    """Verify TelemetryReader withstands 0-byte files, invalid JSON, and corrupt DBs."""
    corrupt_dir = tmp_path / "corrupt_data"
    corrupt_dir.mkdir()

    # 1. 0-byte health file
    health_file = corrupt_dir / "paper-daemon-health.json"
    health_file.write_text("", encoding="utf-8")

    # 2. Corrupt SQLite databases (random non-sqlite bytes)
    db_names = [
        "paper-ledger.sqlite3",
        "paper-lifecycle.sqlite3",
        "paper-observations.sqlite3",
    ]
    for db_name in db_names:
        db_file = corrupt_dir / db_name
        db_file.write_bytes(b"NOT_A_SQLITE_DATABASE_CORRUPT_HEADER_BYTES" * 10)

    reader = TelemetryReader(corrupt_dir)
    snapshot = reader.poll()
    assert isinstance(snapshot, TuiTelemetrySnapshot)
    assert snapshot.is_stale is True
    assert snapshot.recent_closed_trades == ()

    # 3. Truncated malformed JSON
    health_file.write_text('{"daemon_status": "RUNNING", "pid": ', encoding="utf-8")
    snapshot2 = reader.poll()
    assert isinstance(snapshot2, TuiTelemetrySnapshot)
    assert snapshot2.is_stale is True


def test_telemetry_reader_sqlite_schema_evolution(tmp_path: Path) -> None:
    """Verify TelemetryReader against databases that exist but have unexpected/empty schema."""
    db_dir = tmp_path / "schema_test"
    db_dir.mkdir()

    # Create empty SQLite databases (tables do not exist)
    db_names = [
        "paper-ledger.sqlite3",
        "paper-lifecycle.sqlite3",
        "paper-observations.sqlite3",
    ]
    for db_name in db_names:
        conn = sqlite3.connect(db_dir / db_name)
        conn.execute("CREATE TABLE dummy_table (id INTEGER PRIMARY KEY);")
        conn.close()

    reader = TelemetryReader(db_dir)
    snapshot = reader.poll()
    assert isinstance(snapshot, TuiTelemetrySnapshot)
    assert snapshot.recent_closed_trades == ()


# -----------------------------------------------------------------------------
# Challenge 3: Multi-Resolution Dashboard Rendering Matrix
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("w", "h"),
    [
        (80, 24),  # Standard terminal
        (80, 20),  # Short terminal
        (60, 20),  # Compact narrow
        (40, 10),  # Ultra-compact boundary
        (80, 35),  # Tall compact (includes closed trades)
        (110, 28),  # Wide 2-column boundary transition
        (120, 30),  # Wide terminal
        (140, 40),  # High-resolution monitor
        (200, 60),  # Ultra-wide
    ],
)
def test_dashboard_render_matrix_cold_start(tmp_path: Path, w: int, h: int) -> None:
    """Verify Dashboard.render() executes without crash across dimensions on cold start."""
    reader = TelemetryReader(tmp_path / "empty")
    dashboard = Dashboard(reader=reader)

    # Color enabled
    frame_color = dashboard.render(width=w, height=h)
    assert isinstance(frame_color, str)
    assert len(frame_color) > 0


def test_truncate_visible_no_color_purity() -> None:
    """Verify that truncate_visible on plain text does NOT inject ANSI escape sequences."""
    plain = "Plain uncolored text exceeding width"
    truncated = truncate_visible(plain, 10)
    assert "\033" not in truncated


def test_dashboard_no_color_wide_purity(tmp_path: Path) -> None:
    """Verify that Dashboard(no_color=True) contains zero ANSI escape sequences in wide layout."""
    reader = TelemetryReader(tmp_path / "empty")
    dashboard_no_color = Dashboard(reader=reader, no_color=True)
    frame_no_color = dashboard_no_color.render(width=140, height=40)
    assert strip_ansi(frame_no_color) == frame_no_color


def test_dashboard_ascii_only_purity(tmp_path: Path) -> None:
    """Verify that Dashboard(ascii_only=True) contains zero non-ASCII UTF-8 box characters."""
    reader = TelemetryReader(tmp_path / "empty")
    dashboard_ascii = Dashboard(reader=reader, ascii_only=True)
    frame_ascii = dashboard_ascii.render(width=80, height=24)
    for char in ["┌", "┐", "└", "┘", "─", "│", "├", "┤"]:
        assert char not in frame_ascii


def test_dashboard_render_with_populated_mock_data(tmp_path: Path) -> None:
    """Verify Dashboard renders realistic populated telemetry with active positions and trades."""
    data_dir = tmp_path / "populated"
    data_dir.mkdir()

    health = {
        "daemon_status": "RUNNING",
        "pid": 12345,
        "uptime_seconds": 3600.0,
        "started_at_utc": "2026-09-06T12:00:00+00:00",
        "last_heartbeat_utc": "2026-09-06T13:00:00+00:00",
        "symbols_monitored": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"],
        "feed_messages_received": 54321,
        "feed_reconnects_count": 0,
        "circuit_breaker_status": "NORMAL",
        "starting_capital_usdt": "100.00",
        "current_cash_usdt": "98.50",
        "current_equity_usdt": "102.30",
        "margin_utilization_pct": 45.2,
        "reserve_buffer_pct": 54.8,
        "active_positions": {
            "BTCUSDT": {
                "side": "LONG",
                "quantity": "0.001",
                "entry_price": "90000.00",
                "leverage": "2.0",
            },
            "ETHUSDT": {
                "side": "SHORT",
                "quantity": "0.05",
                "entry_price": "2600.00",
                "leverage": "1.5",
            },
        },
        "zero_order_safety_invariants": {
            "orders_submitted": 0,
            "execution_authority": False,
            "live_trading_activation": False,
            "paper_activation": True,
            "promotion_state": "unpromoted",
            "zero_private_credentials": True,
        },
    }
    (data_dir / "paper-daemon-health.json").write_text(json.dumps(health), encoding="utf-8")

    # Create SQLite ledger with closed trades
    ledger_db = data_dir / "paper-ledger.sqlite3"
    conn = sqlite3.connect(ledger_db)
    conn.execute(
        """
        CREATE TABLE paper_ledger_events (
            sequence INTEGER PRIMARY KEY,
            trade_id TEXT,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            fill_price REAL,
            occurred_at TEXT,
            entry_fee REAL,
            exit_fee REAL,
            net_pnl REAL,
            approval_id TEXT,
            event TEXT
        );
        """
    )
    conn.execute(
        """
        INSERT INTO paper_ledger_events VALUES
        (1, 't1', 'BTCUSDT', 'LONG', 0.001, 91000.0, '2026-09-06T12:30:00Z',
         0.036, 0.036, 1.25, 'app-1', 'close'),
        (2, 't2', 'SOLUSDT', 'SHORT', 0.1, 185.0, '2026-09-06T12:45:00Z',
         0.007, 0.007, -0.45, 'app-2', 'close');
        """
    )
    conn.commit()
    conn.close()

    # Lifecycle marks DB
    lifecycle_db = data_dir / "paper-lifecycle.sqlite3"
    conn = sqlite3.connect(lifecycle_db)
    conn.execute(
        """
        CREATE TABLE paper_lifecycle_marks (
            sequence INTEGER PRIMARY KEY,
            trade_id TEXT,
            payload TEXT
        );
        """
    )
    lifecycle_payload = json.dumps(
        {
            "symbol": "BTCUSDT",
            "mark_price": "91200.00",
            "mark_to_market_pnl": "1.20",
            "pnl_pct": "0.013",
            "reason_codes": ["take_profit_hit"],
        }
    )
    conn.execute(
        "INSERT INTO paper_lifecycle_marks VALUES (1, 't1', ?);",
        (lifecycle_payload,),
    )
    conn.commit()
    conn.close()

    dashboard = Dashboard(storage_dir=data_dir)
    rendered_compact = dashboard.render(width=80, height=35)
    assert "BTC" in rendered_compact
    assert "ETH" in rendered_compact
    assert "take_profit" in rendered_compact

    rendered_wide = dashboard.render(width=120, height=30)
    assert "PORTFOLIO MARGIN" in rendered_wide
    assert "MULTI-ASSET MARKET REGIMES" in rendered_wide


# -----------------------------------------------------------------------------
# Challenge 4: SQLite Read-Only & Busy Timeout Enforcement
# -----------------------------------------------------------------------------


def test_sqlite_readonly_enforcement(tmp_path: Path) -> None:
    """Verify _connect_readonly strictly rejects any write/insert operation."""
    db_path = tmp_path / "test_ro.sqlite3"
    conn_setup = sqlite3.connect(db_path)
    conn_setup.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT);")
    conn_setup.commit()
    conn_setup.close()

    reader = TelemetryReader(tmp_path)
    conn_ro = reader._connect_readonly(db_path)
    assert conn_ro is not None

    # Read operation succeeds
    cur = conn_ro.execute("SELECT count(*) FROM test_table;")
    assert cur.fetchone()[0] == 0

    # Write operation MUST fail with OperationalError
    with pytest.raises(sqlite3.OperationalError, match=r"readonly|query_only"):
        conn_ro.execute("INSERT INTO test_table VALUES (1, 'attack');")

    conn_ro.close()


def test_sqlite_lock_contention_and_busy_timeout(tmp_path: Path) -> None:
    """Verify TelemetryReader does not hang indefinitely when database is write-locked."""
    db_path = tmp_path / "paper-ledger.sqlite3"
    conn_setup = sqlite3.connect(db_path)
    conn_setup.execute(
        "CREATE TABLE paper_ledger_events (sequence INTEGER PRIMARY KEY, event TEXT);"
    )
    conn_setup.commit()
    conn_setup.close()

    # Acquire exclusive write lock in background thread
    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def _lock_holder() -> None:
        conn = sqlite3.connect(db_path)
        conn.execute("BEGIN EXCLUSIVE;")
        lock_acquired.set()
        release_lock.wait(timeout=5.0)
        conn.rollback()
        conn.close()

    t = threading.Thread(target=_lock_holder, daemon=True)
    t.start()
    assert lock_acquired.wait(timeout=2.0)

    try:
        reader = TelemetryReader(tmp_path)
        start_t = time.perf_counter()

        # Polling under lock contention: must return cleanly within ~1.5s
        snapshot = reader.poll()
        elapsed = time.perf_counter() - start_t

        assert isinstance(snapshot, TuiTelemetrySnapshot)
        assert elapsed < 3.0, f"Reader hung for {elapsed:.2f}s on locked SQLite database"
    finally:
        release_lock.set()
        t.join(timeout=2.0)


# -----------------------------------------------------------------------------
# Challenge 5: CLI Driver Snapshot Mode (--once) and Boundary Arguments
# -----------------------------------------------------------------------------


def test_cli_snapshot_mode_e2e(tmp_path: Path) -> None:
    """Execute scripts/monitor_live_paper_tui.py via subprocess verifying --once and exit code 0."""
    script_path = Path("scripts/monitor_live_paper_tui.py").resolve()

    # Test 1: standard --once
    cmd = [
        sys.executable,
        str(script_path),
        "--once",
        "--storage-dir",
        str(tmp_path),
        "--width",
        "80",
        "--height",
        "24",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res.returncode == 0, f"Failed with stderr: {res.stderr}"
    assert "AUTONOMOUS FUTURES BOT" in res.stdout
    assert "PORTFOLIO MARGIN" in res.stdout

    # Test 2: --no-color flag
    cmd_no_color = [
        sys.executable,
        str(script_path),
        "--once",
        "--storage-dir",
        str(tmp_path),
        "--no-color",
    ]
    res_nc = subprocess.run(
        cmd_no_color, capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert res_nc.returncode == 0
    assert strip_ansi(res_nc.stdout) == res_nc.stdout

    # Test 3: --ascii-only flag
    cmd_ascii = [
        sys.executable,
        str(script_path),
        "--once",
        "--storage-dir",
        str(tmp_path),
        "--ascii-only",
    ]
    res_ascii = subprocess.run(
        cmd_ascii, capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert res_ascii.returncode == 0
    assert "+" in res_ascii.stdout

    # Test 4: Argument validation failures
    # Invalid refresh rate <= 0
    res_bad_rate = subprocess.run(
        [sys.executable, str(script_path), "--refresh-rate", "0"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res_bad_rate.returncode == 2

    # Invalid width < 40
    res_bad_width = subprocess.run(
        [sys.executable, str(script_path), "--width", "35"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res_bad_width.returncode == 2

    # Invalid height < 10
    res_bad_height = subprocess.run(
        [sys.executable, str(script_path), "--height", "5"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res_bad_height.returncode == 2


def test_dashboard_line_width_invariant(tmp_path: Path) -> None:
    """Verify that every rendered row of Dashboard strictly matches the requested width."""
    reader = TelemetryReader(tmp_path / "empty")
    dashboard = Dashboard(reader=reader)

    # Test compact layout: width=80
    frame_80 = dashboard.render(width=80, height=24)
    for idx, line in enumerate(frame_80.split("\n")):
        vlen = visible_len(line)
        assert vlen == 80, f"Compact row {idx} has visible_len {vlen} != 80: {line!r}"

    # Test wide layout: width=120
    frame_120 = dashboard.render(width=120, height=30)
    for idx, line in enumerate(frame_120.split("\n")):
        vlen = visible_len(line)
        assert vlen == 120, f"Wide row {idx} has visible_len {vlen} != 120: {line!r}"
