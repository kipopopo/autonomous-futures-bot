"""Unit tests for TUI formatters, ANSI handling, and numeric formatting.

Covers:
1. ANSI escape stripping and visible length invariants (strip_ansi, visible_len, visible_length).
2. Visible padding and truncation with conditional ANSI reset preservation.
3. Currency, PnL, and percentage formatting with exact Decimal precision.
4. Progress bar rendering: standard threshold vs lower_is_worse threshold and ASCII fallback.
5. Utilization meter formatting and visual warning thresholds.
6. Spread basis points formatting with HALT/WARN triggers.
7. ATR formatting enforcing arithmetic ROUND_HALF_UP quantization.
8. Uptime and relative timestamp humanization.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from autonomous_futures.tui.formatters import (
    Ansi,
    AnsiColor,
    format_atr,
    format_currency,
    format_percent,
    format_pnl,
    format_relative_time,
    format_spread_bps,
    format_uptime,
    format_utilization_meter,
    pad_visible,
    render_progress_bar,
    strip_ansi,
    truncate_visible,
    visible_len,
    visible_length,
)


class TestAnsiAndVisibleLength:
    """Tests for ANSI escape sequences stripping and visible column calculations."""

    def test_ansi_color_alias(self) -> None:
        """AnsiColor must be identical to Ansi."""
        assert AnsiColor is Ansi
        assert Ansi.RESET == "\033[0m"
        assert Ansi.BOLD == "\033[1m"
        assert Ansi.BRIGHT_GREEN == "\033[92m"
        assert Ansi.BRIGHT_RED == "\033[91m"

    @pytest.mark.parametrize(
        ("input_text", "expected_plain", "expected_vlen"),
        [
            ("", "", 0),
            ("Simple Text", "Simple Text", 11),
            (f"{Ansi.RED}Red{Ansi.RESET}", "Red", 3),
            (f"{Ansi.BOLD}{Ansi.BRIGHT_GREEN}Success{Ansi.RESET}", "Success", 7),
            (f"{Ansi.BG_RED}{Ansi.WHITE}Alert{Ansi.RESET}", "Alert", 5),
            ("\033[2J\033[HClearScreen", "ClearScreen", 11),
            ("\033[?25hCursor\033[?25l", "Cursor", 6),
            (
                f"{Ansi.CYAN}Part1{Ansi.RESET} and {Ansi.YELLOW}Part2{Ansi.RESET}",
                "Part1 and Part2",
                15,
            ),
            ("Nested \033[31mRed \033[1mBoldRed \033[0mReset", "Nested Red BoldRed Reset", 24),
        ],
    )
    def test_strip_ansi_and_visible_len(
        self, input_text: str, expected_plain: str, expected_vlen: int
    ) -> None:
        """strip_ansi must remove all ANSI sequences and visible_len must match visible count."""
        assert strip_ansi(input_text) == expected_plain
        assert visible_len(input_text) == expected_vlen
        # Check alias visible_length
        assert visible_length(input_text) == expected_vlen


class TestPaddingAndTruncation:
    """Tests for pad_visible and truncate_visible invariants."""

    def test_pad_visible_alignments(self) -> None:
        """pad_visible must pad correctly to target width across alignments."""
        text = "Test"
        # Left alignment (default)
        assert pad_visible(text, 10, align="left") == "Test      "
        # Right alignment
        assert pad_visible(text, 10, align="right") == "      Test"
        # Center alignment (even padding)
        assert pad_visible(text, 10, align="center") == "   Test   "
        # Center alignment (odd padding)
        assert pad_visible(text, 9, align="center") == "  Test   "

    def test_pad_visible_with_ansi(self) -> None:
        """pad_visible must respect embedded ANSI sequences and pad to exact visible width."""
        styled = f"{Ansi.BRIGHT_GREEN}Active{Ansi.RESET}"
        padded = pad_visible(styled, 12, align="left")
        assert visible_len(padded) == 12
        assert padded.endswith("      ")

        right_padded = pad_visible(styled, 12, align="right")
        assert visible_len(right_padded) == 12
        assert right_padded.startswith("      ")

    def test_pad_visible_no_op_when_sufficient_width(self) -> None:
        """pad_visible must return text untouched if width <= visible_len."""
        text = "AlreadyWide"
        assert pad_visible(text, 5) == text
        assert pad_visible(text, len(text)) == text

    def test_truncate_visible_plain_text_no_leak(self) -> None:
        """truncate_visible on plain text must NOT leak ANSI.RESET sequences."""
        plain = "Plain uncolored text exceeding width"
        truncated = truncate_visible(plain, 10)
        assert visible_len(truncated) == 10
        assert truncated == "Plain unc…"
        assert "\033" not in truncated

    def test_truncate_visible_styled_text_appends_reset(self) -> None:
        """truncate_visible on styled text must append Ansi.RESET to prevent style leakage."""
        styled = f"{Ansi.BRIGHT_RED}Long Error Message Exceeding Budget{Ansi.RESET}"
        truncated = truncate_visible(styled, 15)
        assert visible_len(truncated) == 15
        assert truncated.endswith(f"…{Ansi.RESET}")
        assert strip_ansi(truncated) == "Long Error Mes…"

    def test_truncate_visible_boundary_cases(self) -> None:
        """Boundary values (0, negative, width <= len(ellipsis))."""
        assert truncate_visible("Short", 10) == "Short"
        assert truncate_visible("AnyText", 0) == ""
        assert truncate_visible("AnyText", -5) == ""
        assert truncate_visible("AnyText", 1) == "…"
        assert truncate_visible("AnyText", 1, ellipsis="...") == "."


class TestNumericFormatters:
    """Tests for currency, PnL, percentage, spread, and ATR formatters."""

    def test_format_currency(self) -> None:
        """format_currency must format decimals with comma grouping and prefix."""
        # Positive
        assert format_currency(Decimal("1234567.89"), prefix="$", decimals=2) == "$1,234,567.89"
        # Negative
        assert format_currency(Decimal("-45.67"), prefix="USDT ", decimals=2) == "-USDT 45.67"
        # Zero
        assert format_currency(0, prefix="$", decimals=2) == "$0.00"
        # Custom decimals
        assert format_currency(Decimal("0.12346"), prefix="", decimals=4) == "0.1235"
        # Colored
        pos_color = format_currency(100.0, color=True)
        assert Ansi.BRIGHT_GREEN in pos_color
        neg_color = format_currency(-100.0, color=True)
        assert Ansi.BRIGHT_RED in neg_color
        zero_color = format_currency(0.0, color=True)
        assert Ansi.DIM in zero_color

    def test_format_pnl(self) -> None:
        """format_pnl must format signed profit-and-loss values with green/red styling."""
        # Positive with sign
        assert format_pnl(Decimal("12.34"), color=False) == "+$12.34"
        # Positive without sign
        assert format_pnl(Decimal("12.34"), include_sign=False, color=False) == "$12.34"
        # Negative
        assert format_pnl(Decimal("-8.50"), color=False) == "-$8.50"
        # Zero
        assert format_pnl(Decimal("0.00"), color=False) == "$0.00"
        # With percentage
        pnl_pct = format_pnl(Decimal("5.00"), pct=Decimal("5.0"), color=False)
        assert pnl_pct == "+$5.00 (+5.0%)"
        # Enabled parameter alias
        colored = format_pnl(Decimal("10.0"), enabled=True)
        assert Ansi.BRIGHT_GREEN in colored
        uncolored = format_pnl(Decimal("10.0"), enabled=False)
        assert Ansi.BRIGHT_GREEN not in uncolored

    def test_format_percent(self) -> None:
        """format_percent must format percentage strings with sign and color."""
        assert format_percent(Decimal("12.5"), color=False) == "+12.5%"
        assert format_percent(Decimal("-3.42"), decimals=2, color=False) == "-3.42%"
        assert format_percent(Decimal("0.0"), color=False) == "0.0%"
        assert format_percent(Decimal("15.0"), include_sign=False, color=False) == "15.0%"

        colored_pos = format_percent(5.0, color=True)
        assert Ansi.BRIGHT_GREEN in colored_pos
        colored_neg = format_percent(-5.0, color=True)
        assert Ansi.BRIGHT_RED in colored_neg

    def test_format_spread_bps(self) -> None:
        """format_spread_bps triggers warning and halt thresholds."""
        # Normal spread < 5.0 bps
        norm = format_spread_bps(Decimal("0.75"), color=True)
        assert " 0.75 bps" in strip_ansi(norm)
        assert Ansi.BRIGHT_GREEN in norm

        # Warning spread >= 5.0 bps
        warn = format_spread_bps(Decimal("5.50"), color=True)
        assert " 5.50 bps" in strip_ansi(warn)
        assert Ansi.BRIGHT_YELLOW in warn

        # Halt spread >= 20.0 bps
        halt = format_spread_bps(Decimal("22.50"), color=True)
        assert "(HALT)" in strip_ansi(halt)
        assert Ansi.BRIGHT_RED in halt

        # Color disabled
        uncolored = format_spread_bps(Decimal("25.0"), color=False)
        assert uncolored == "25.00 bps"

    def test_format_atr_arithmetic_round_half_up(self) -> None:
        """format_atr must strictly use arithmetic ROUND_HALF_UP rounding."""
        # Arithmetic rounding: 0.00005 rounds UP to 0.0001 (unlike banker's round-to-even)
        assert format_atr(Decimal("0.00005"), decimals=4) == "0.0001"
        assert format_atr(Decimal("0.00004"), decimals=4) == "0.0000"
        # Banker's rounding would round 9999999.98765 down to .9876,
        # but arithmetic ROUND_HALF_UP rounds UP to .9877
        assert format_atr(Decimal("9999999.98765"), decimals=4) == "9999999.9877"
        assert format_atr(Decimal("9999999.98775"), decimals=4) == "9999999.9878"
        # Zero decimals
        assert format_atr(Decimal("45.5"), decimals=0) == "46"
        assert format_atr(Decimal("45.4"), decimals=0) == "45"


class TestProgressBarsAndMeters:
    """Tests for render_progress_bar and format_utilization_meter."""

    def test_render_progress_bar_standard(self) -> None:
        """render_progress_bar in standard mode (higher is worse)."""
        # 0%
        bar_0 = render_progress_bar(0.0, width=10, color=False)
        assert bar_0 == "[░░░░░░░░░░]"

        # 50%
        bar_50 = render_progress_bar(50.0, width=10, color=False)
        assert bar_50 == "[█████░░░░░]"

        # 100%
        bar_100 = render_progress_bar(100.0, width=10, color=False)
        assert bar_100 == "[██████████]"

        # Clamping
        assert render_progress_bar(-10.0, width=10, color=False) == "[░░░░░░░░░░]"
        assert render_progress_bar(150.0, width=10, color=False) == "[██████████]"

    def test_render_progress_bar_color_thresholds(self) -> None:
        """render_progress_bar standard coloring: green -> yellow -> red."""
        # Low: green
        low = render_progress_bar(30.0, width=10, warn_pct=80.0, color=True)
        assert Ansi.BRIGHT_GREEN in low

        # Moderate (>= warn_pct * 0.625 = 50%): yellow
        mid = render_progress_bar(55.0, width=10, warn_pct=80.0, color=True)
        assert Ansi.BRIGHT_YELLOW in mid

        # High (>= 80%): red
        high = render_progress_bar(85.0, width=10, warn_pct=80.0, color=True)
        assert Ansi.BRIGHT_RED in high

    def test_render_progress_bar_lower_is_worse(self) -> None:
        """render_progress_bar with lower_is_worse=True (e.g. reserve buffer)."""
        # Reserve buffer: min 20%
        # Below 20%: Red
        crit = render_progress_bar(15.0, width=10, warn_pct=20.0, color=True, lower_is_worse=True)
        assert Ansi.BRIGHT_RED in crit

        # Between 20% and 30% (warn_pct * 1.5): Yellow
        warn = render_progress_bar(25.0, width=10, warn_pct=20.0, color=True, lower_is_worse=True)
        assert Ansi.BRIGHT_YELLOW in warn

        # Above 30%: Green
        good = render_progress_bar(70.0, width=10, warn_pct=20.0, color=True, lower_is_worse=True)
        assert Ansi.BRIGHT_GREEN in good

    def test_render_progress_bar_ascii_only(self) -> None:
        """render_progress_bar ascii_only uses '#' and '-'."""
        bar = render_progress_bar(50.0, width=10, color=False, ascii_only=True)
        assert bar == "[#####-----]"

    def test_format_utilization_meter(self) -> None:
        """format_utilization_meter displays progress bar and percentage readout."""
        meter = format_utilization_meter(45.0, width=10, enabled=False)
        assert "[████░░░░░░]" in meter or "[█████░░░░░]" in meter
        assert "45.0% / 80.0% max" in meter

        # Warning color >= 50%
        meter_warn = format_utilization_meter(55.0, enabled=True)
        assert Ansi.BRIGHT_YELLOW in meter_warn

        # Danger color >= 80%
        meter_dang = format_utilization_meter(82.0, enabled=True)
        assert Ansi.BRIGHT_RED in meter_dang


class TestTimeFormatters:
    """Tests for format_uptime and format_relative_time."""

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "0s"),
            (45, "45s"),
            (60, "1m 00s"),
            (125, "2m 05s"),
            (3600, "1h 00m 00s"),
            (3665, "1h 01m 05s"),
            (86400, "1d 00h 00m 00s"),
            (90061, "1d 01h 01m 01s"),
            (-10, "0s"),
        ],
    )
    def test_format_uptime(self, seconds: float, expected: str) -> None:
        """format_uptime formats durations into human-readable compact strings."""
        assert format_uptime(seconds) == expected

    def test_format_relative_time(self) -> None:
        """format_relative_time calculates elapsed time from ISO timestamp or datetime."""
        now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

        # Negative difference
        future = now + timedelta(seconds=10)
        assert format_relative_time(future, reference=now) == "just now"

        # Seconds ago (< 60s)
        t_sec = now - timedelta(seconds=12.4)
        assert format_relative_time(t_sec, reference=now) == "12.4s ago"

        # Minutes ago (< 60m)
        t_min = now - timedelta(minutes=5, seconds=3)
        assert format_relative_time(t_min, reference=now) == "5m 03s ago"

        # Hours ago
        t_hr = now - timedelta(hours=3, minutes=15)
        assert format_relative_time(t_hr, reference=now) == "3h 15m ago"

        # ISO string with Z
        iso_str = "2026-09-06T11:59:55Z"
        assert format_relative_time(iso_str, reference=now) == "5.0s ago"

        # Invalid ISO string fallback
        assert format_relative_time("not-a-timestamp") == "not-a-timestamp"
