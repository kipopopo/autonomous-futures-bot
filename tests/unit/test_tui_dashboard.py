"""Unit tests for the TUI Dashboard coordinator and responsive layout rendering.

Covers:
1. Accurate rendering of all 6 panels (Header, Margin, Regimes, Positions, Closed Trades, Safety).
2. Compact single-column vertical layout (80x24) with responsive height reflow.
3. Wide two-column split layout (>= 110x28) with exact row alignment.
4. Pure ASCII-only mode invariant (zero non-ASCII UTF-8 box characters).
5. Pure No-color mode invariant (zero ANSI escape sequences).
6. Line width invariant enforcement across arbitrary terminal dimensions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.tui.dashboard import Dashboard
from autonomous_futures.tui.formatters import strip_ansi, visible_len
from autonomous_futures.tui.telemetry import (
    ClosedTradeSnapshot,
    DaemonHealthSnapshot,
    MarginAccountSnapshot,
    MarketRegimeSnapshot,
    PositionSnapshot,
    SafetyInvariantsSnapshot,
    TelemetryReader,
    TuiTelemetrySnapshot,
)


@pytest.fixture
def mock_telemetry_snapshot(tmp_path: Path) -> TuiTelemetrySnapshot:
    """Construct a populated TuiTelemetrySnapshot fixture for deterministic testing."""
    now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

    daemon = DaemonHealthSnapshot(
        status="RUNNING",
        pid=222449,
        uptime_seconds=3600.0,
        started_at_utc=now.isoformat(),
        last_heartbeat_utc=now.isoformat(),
        heartbeat_age_seconds=0.5,
        symbols_monitored=("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"),
        feed_messages_received=150000,
        feed_throughput_per_sec=41.7,
        feed_reconnects_count=0,
        circuit_breaker_status="NORMAL",
        zero_order_invariants={
            "orders_submitted": 0,
            "execution_authority": False,
            "live_trading_activation": False,
            "paper_activation": True,
            "promotion_state": "unpromoted",
            "zero_private_credentials": True,
        },
    )

    margin = MarginAccountSnapshot(
        starting_capital=Decimal("100.00"),
        current_cash=Decimal("102.50"),
        current_equity=Decimal("105.75"),
        realized_pnl=Decimal("2.50"),
        realized_pnl_pct=Decimal("2.5"),
        unrealized_pnl=Decimal("3.25"),
        unrealized_pnl_pct=Decimal("3.25"),
        margin_utilization_pct=25.0,
        reserve_buffer_pct=75.0,
        peak_equity=Decimal("108.00"),
    )

    regimes = {
        "BTCUSDT": MarketRegimeSnapshot(
            symbol="BTCUSDT",
            best_bid=Decimal("90500.00"),
            best_ask=Decimal("90500.50"),
            mid_price=Decimal("90500.25"),
            spread_bps=Decimal("0.06"),
            rolling_atr=Decimal("45.20"),
            status="NORMAL",
        ),
        "ETHUSDT": MarketRegimeSnapshot(
            symbol="ETHUSDT",
            best_bid=Decimal("2650.00"),
            best_ask=Decimal("2650.25"),
            mid_price=Decimal("2650.125"),
            spread_bps=Decimal("0.94"),
            rolling_atr=Decimal("3.15"),
            status="NORMAL",
        ),
        "SOLUSDT": MarketRegimeSnapshot(
            symbol="SOLUSDT",
            best_bid=Decimal("182.40"),
            best_ask=Decimal("182.50"),
            mid_price=Decimal("182.45"),
            spread_bps=Decimal("5.48"),
            rolling_atr=Decimal("0.85"),
            status="WIDE_SPREAD",
        ),
        "DOGEUSDT": MarketRegimeSnapshot(
            symbol="DOGEUSDT",
            best_bid=Decimal("0.15200"),
            best_ask=Decimal("0.15235"),
            mid_price=Decimal("0.152175"),
            spread_bps=Decimal("23.00"),
            rolling_atr=Decimal("0.0012"),
            status="HALTED",
        ),
    }

    positions = {
        "BTCUSDT": PositionSnapshot(
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("0.001"),
            entry_price=Decimal("90000.00"),
            mark_price=Decimal("90500.25"),
            unrealized_pnl=Decimal("0.50025"),
            pnl_pct=Decimal("0.56"),
            leverage=Decimal("2.0"),
            liquidation_distance_pct=Decimal("50.0"),
            stop_loss_price=Decimal("89500.00"),
            trailing_stop_price=Decimal("89800.00"),
        )
    }

    trades = (
        ClosedTradeSnapshot(
            sequence=1,
            trade_id="t1",
            symbol="ETHUSDT",
            side="SHORT",
            quantity=Decimal("0.05"),
            fill_price=Decimal("2640.00"),
            occurred_at="2026-09-06T11:45:00Z",
            net_pnl=Decimal("0.50"),
            entry_fee=Decimal("0.0528"),
            exit_fee=Decimal("0.0528"),
            total_fees=Decimal("0.1056"),
            exit_reason="take_profit",
        ),
    )

    safety = SafetyInvariantsSnapshot(
        volatility_cb="NORMAL",
        spread_cb="NORMAL",
        orders_submitted=0,
        execution_authority=False,
        live_trading_activation=False,
        paper_activation=True,
        promotion_state="unpromoted",
        zero_private_credentials=True,
        all_invariants_pass=True,
    )

    return TuiTelemetrySnapshot(
        timestamp=now,
        storage_dir=tmp_path,
        is_stale=False,
        daemon=daemon,
        margin=margin,
        regimes=regimes,
        positions=positions,
        recent_closed_trades=trades,
        safety=safety,
    )


class MockReader:
    """Mock reader returning pre-configured snapshot."""

    def __init__(self, snapshot: TuiTelemetrySnapshot) -> None:
        self.snapshot = snapshot

    def poll(self) -> TuiTelemetrySnapshot:
        return self.snapshot


class TestPanelBuilders:
    """Tests for individual panel generation routines within Dashboard."""

    def test_build_header_panel(self, mock_telemetry_snapshot: TuiTelemetrySnapshot) -> None:
        """Header panel reflects daemon PID, uptime, throughput, and status."""
        dashboard = Dashboard()
        panel = dashboard._build_header_panel(mock_telemetry_snapshot, width=80)
        rendered = panel.render()

        plain = "\n".join(strip_ansi(line) for line in rendered)
        assert "AUTONOMOUS FUTURES BOT" in plain
        assert "Status: RUNNING" in plain
        assert "PID 222449" in plain
        assert "Uptime: 1h 00m 00s" in plain
        assert "150,000" in plain

    def test_build_margin_panel(self, mock_telemetry_snapshot: TuiTelemetrySnapshot) -> None:
        """Margin panel reflects cash, equity, realized/unrealized PnL, and meters."""
        dashboard = Dashboard()
        panel = dashboard._build_margin_panel(mock_telemetry_snapshot, width=80)
        rendered = panel.render()

        plain = "\n".join(strip_ansi(line) for line in rendered)
        assert "PORTFOLIO MARGIN" in plain
        assert "Cash: $102.50 USDT" in plain
        assert "Equity: $105.75 USDT" in plain
        assert "Realized PnL: +$2.50 (+2.5%)" in plain
        assert "Margin Util:" in plain
        assert "Reserve Buf:" in plain
        assert "Peak Equity: $108.00 USDT" in plain

    def test_build_regimes_panel(self, mock_telemetry_snapshot: TuiTelemetrySnapshot) -> None:
        """Regimes panel renders all 4 symbols with prices, spreads, ATR, and status."""
        dashboard = Dashboard()
        # Wide regimes (>= 72 width)
        panel_wide = dashboard._build_regimes_panel(mock_telemetry_snapshot, width=80)
        plain_w = "\n".join(strip_ansi(line) for line in panel_wide.render())
        assert "MULTI-ASSET MARKET REGIMES" in plain_w
        assert "BTCUSDT" in plain_w
        assert "ETHUSDT" in plain_w
        assert "SOLUSDT" in plain_w
        assert "DOGEUSDT" in plain_w
        assert "90,500.00" in plain_w
        assert "HALT" in plain_w
        assert "WIDE" in plain_w

        # Compact regimes (< 72 width)
        panel_compact = dashboard._build_regimes_panel(mock_telemetry_snapshot, width=50)
        plain_c = "\n".join(strip_ansi(line) for line in panel_compact.render())
        assert "BTCUSDT" in plain_c
        assert "MID PRICE" in plain_c

    def test_build_positions_panel_empty_and_populated(
        self, mock_telemetry_snapshot: TuiTelemetrySnapshot
    ) -> None:
        """Positions panel handles empty and active position states."""
        dashboard = Dashboard()

        # Populated
        panel_pop = dashboard._build_positions_panel(mock_telemetry_snapshot, width=80)
        plain_p = "\n".join(strip_ansi(line) for line in panel_pop.render())
        assert "ACTIVE PAPER POSITIONS" in plain_p
        assert "BTC" in plain_p
        assert "LONG" in plain_p
        assert "90,000.00" in plain_p
        assert "2.0x" in plain_p

        # Empty
        snap_empty = TuiTelemetrySnapshot(
            timestamp=mock_telemetry_snapshot.timestamp,
            storage_dir=mock_telemetry_snapshot.storage_dir,
            is_stale=False,
            daemon=mock_telemetry_snapshot.daemon,
            margin=mock_telemetry_snapshot.margin,
            regimes=mock_telemetry_snapshot.regimes,
            positions={},
            recent_closed_trades=mock_telemetry_snapshot.recent_closed_trades,
            safety=mock_telemetry_snapshot.safety,
        )
        panel_empty = dashboard._build_positions_panel(snap_empty, width=80)
        plain_e = "\n".join(strip_ansi(line) for line in panel_empty.render())
        assert "No Active Positions" in plain_e

    def test_build_trades_panel_empty_and_populated(
        self, mock_telemetry_snapshot: TuiTelemetrySnapshot
    ) -> None:
        """Trades panel handles empty and populated trade history states."""
        dashboard = Dashboard()

        # Populated
        panel_pop = dashboard._build_trades_panel(mock_telemetry_snapshot, width=80)
        plain_p = "\n".join(strip_ansi(line) for line in panel_pop.render())
        assert "RECENT CLOSED TRADES" in plain_p
        assert "ETH" in plain_p
        assert "SHORT" in plain_p
        assert "take_profit" in plain_p

        # Empty
        snap_empty = TuiTelemetrySnapshot(
            timestamp=mock_telemetry_snapshot.timestamp,
            storage_dir=mock_telemetry_snapshot.storage_dir,
            is_stale=False,
            daemon=mock_telemetry_snapshot.daemon,
            margin=mock_telemetry_snapshot.margin,
            regimes=mock_telemetry_snapshot.regimes,
            positions=mock_telemetry_snapshot.positions,
            recent_closed_trades=(),
            safety=mock_telemetry_snapshot.safety,
        )
        panel_empty = dashboard._build_trades_panel(snap_empty, width=80)
        plain_e = "\n".join(strip_ansi(line) for line in panel_empty.render())
        assert "No closed trades recorded in paper ledger yet" in plain_e

    def test_build_safety_panel(self, mock_telemetry_snapshot: TuiTelemetrySnapshot) -> None:
        """Safety panel displays zero-order verification and CB status."""
        dashboard = Dashboard()
        panel = dashboard._build_safety_panel(mock_telemetry_snapshot, width=80)
        plain = "\n".join(strip_ansi(line) for line in panel.render())

        assert "SAFETY GUARDRAILS & ZERO-ORDER INVARIANTS" in plain
        assert "Orders: 0 (PASS)" in plain
        assert "Exec Authority: FALSE" in plain
        assert "Live Trading: FALSE" in plain
        assert "Promotion: UNPROMOTED" in plain
        assert "Zero Keys: VERIFIED" in plain
        assert "Mode: PAPER ACTIVE" in plain


class TestDashboardLayoutModes:
    """Tests for compact vs wide layout modes and reflow invariants."""

    def test_compact_layout_reflow(self, mock_telemetry_snapshot: TuiTelemetrySnapshot) -> None:
        """Compact layout renders single vertical stack for 80x24."""
        reader = MockReader(mock_telemetry_snapshot)
        dashboard = Dashboard(reader=reader)  # type: ignore[arg-type]

        # 80x24: Trades panel omitted (height < 28)
        frame_24 = dashboard.render(width=80, height=24)
        assert "AUTONOMOUS FUTURES BOT" in frame_24
        assert "RECENT CLOSED TRADES" not in frame_24

        # Check visible width invariant on every line
        for line in frame_24.split("\n"):
            assert visible_len(line) == 80

        # 80x30: Trades panel included (height >= 28)
        frame_30 = dashboard.render(width=80, height=30)
        assert "RECENT CLOSED TRADES" in frame_30
        for line in frame_30.split("\n"):
            assert visible_len(line) == 80

    def test_wide_layout_two_column_split(
        self, mock_telemetry_snapshot: TuiTelemetrySnapshot
    ) -> None:
        """Wide layout activates at >= 110x28 and maintains exact line widths."""
        reader = MockReader(mock_telemetry_snapshot)
        dashboard = Dashboard(reader=reader)  # type: ignore[arg-type]

        frame_wide = dashboard.render(width=120, height=30)
        assert "PORTFOLIO MARGIN" in frame_wide
        assert "MULTI-ASSET MARKET REGIMES" in frame_wide

        for idx, line in enumerate(frame_wide.split("\n")):
            vlen = visible_len(line)
            assert vlen == 120, f"Wide line {idx} width violation: got {vlen} != 120"


class TestPurityAndInvariants:
    """Tests for ASCII-only and No-color output purity."""

    def test_ascii_only_mode_purity(self, mock_telemetry_snapshot: TuiTelemetrySnapshot) -> None:
        """ascii_only=True must emit zero non-ASCII characters across the entire frame."""
        reader = MockReader(mock_telemetry_snapshot)
        dashboard = Dashboard(reader=reader, ascii_only=True)  # type: ignore[arg-type]

        unicode_box_chars = ["┌", "┐", "└", "┘", "─", "│", "├", "┤", "█", "░", "━", "┃", "═", "║"]

        # 1. Compact 80x24: 100% pure ASCII (all characters ord < 128)
        frame_compact = dashboard.render(width=80, height=24)
        for char in frame_compact:
            assert ord(char) < 128, (
                f"Non-ASCII character {char!r} (U+{ord(char):04X}) detected in compact ascii_only"
            )
        for bc in unicode_box_chars:
            assert bc not in frame_compact

        # 2. Wide layout: zero Unicode box-drawing characters
        frame_wide = dashboard.render(width=120, height=30)
        for bc in unicode_box_chars:
            assert bc not in frame_wide, f"Unicode box char {bc!r} leaked in wide ascii_only"

    def test_no_color_mode_purity(self, mock_telemetry_snapshot: TuiTelemetrySnapshot) -> None:
        """no_color=True must emit zero ANSI escape codes across the entire frame."""
        reader = MockReader(mock_telemetry_snapshot)
        dashboard = Dashboard(reader=reader, no_color=True)  # type: ignore[arg-type]

        frame_compact = dashboard.render(width=80, height=24)
        assert "\033" not in frame_compact
        assert strip_ansi(frame_compact) == frame_compact

        frame_wide = dashboard.render(width=120, height=30)
        assert "\033" not in frame_wide
        assert strip_ansi(frame_wide) == frame_wide

    def test_reader_initialization_options(self, tmp_path: Path) -> None:
        """Dashboard initialization with path, reader, or default."""
        d1 = Dashboard(storage_dir=tmp_path)
        assert isinstance(d1.reader, TelemetryReader)
        assert d1.reader.storage_dir == tmp_path

        r = TelemetryReader(tmp_path)
        d2 = Dashboard(reader=r)
        assert d2.reader is r

        d3 = Dashboard(color_enabled=False)
        assert d3.no_color is True
