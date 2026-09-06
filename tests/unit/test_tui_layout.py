"""Unit tests for TUI layout primitives, box characters, panels, and compositions.

Covers:
1. Box character presets (LIGHT_BOX, HEAVY_BOX, DOUBLE_BOX, ASCII_BOX).
2. Panel visible width invariants across all rows (visible_len == width).
3. Panel title and divider rendering with truncation and visible length preservation.
4. Vertical stack composition across lists of panels.
5. Horizontal split composition with asymmetric heights and exact row width preservation.
6. Table row column formatting with alignment, padding, and truncation.
7. Terminal dimensions detection, overrides, and safety clamping.
"""

from __future__ import annotations

from typing import Literal

import pytest

from autonomous_futures.tui.formatters import Ansi, visible_len
from autonomous_futures.tui.layout import (
    ASCII_BOX,
    DOUBLE_BOX,
    HEAVY_BOX,
    LIGHT_BOX,
    BoxChars,
    Panel,
    compose_horizontal_split,
    compose_vertical_stack,
    format_table_row,
    get_terminal_dimensions,
)


class TestBoxCharacterSets:
    """Tests for BoxChars dataclass and standard character presets."""

    def test_default_light_box_preset(self) -> None:
        """LIGHT_BOX default box-drawing characters."""
        bc = LIGHT_BOX
        assert bc.tl == "┌"
        assert bc.tr == "┐"
        assert bc.bl == "└"
        assert bc.br == "┘"
        assert bc.h == "─"
        assert bc.v == "│"
        assert bc.lt == "├"
        assert bc.rt == "┤"
        assert bc.tt == "┬"
        assert bc.bt == "┴"
        assert bc.cross == "┼"

    def test_heavy_and_double_presets(self) -> None:
        """HEAVY_BOX and DOUBLE_BOX character definitions."""
        assert HEAVY_BOX.tl == "┏"
        assert HEAVY_BOX.h == "━"
        assert HEAVY_BOX.v == "┃"

        assert DOUBLE_BOX.tl == "╔"
        assert DOUBLE_BOX.h == "═"
        assert DOUBLE_BOX.v == "║"

    def test_ascii_box_preset_pure_ascii(self) -> None:
        """ASCII_BOX must contain only ASCII characters (ord < 128)."""
        bc = ASCII_BOX
        assert bc.tl == "+"
        assert bc.tr == "+"
        assert bc.bl == "+"
        assert bc.br == "+"
        assert bc.h == "-"
        assert bc.v == "|"
        assert bc.lt == "+"
        assert bc.rt == "+"
        assert bc.tt == "+"
        assert bc.bt == "+"
        assert bc.cross == "+"
        # Ensure all fields are purely ASCII
        for field_name in (
            "tl",
            "tr",
            "bl",
            "br",
            "h",
            "v",
            "lt",
            "rt",
            "tt",
            "bt",
            "cross",
        ):
            val = getattr(bc, field_name)
            assert all(ord(c) < 128 for c in val)


class TestPanelRenderingInvariants:
    """Tests for Panel rendering and border visible length invariants."""

    @pytest.mark.parametrize(
        "box_style",
        [LIGHT_BOX, HEAVY_BOX, DOUBLE_BOX, ASCII_BOX],
    )
    @pytest.mark.parametrize("target_width", [6, 20, 50, 80, 110, 150])
    def test_panel_width_invariant_empty_and_filled(
        self, box_style: BoxChars, target_width: int
    ) -> None:
        """Every single rendered line must strictly satisfy visible_len == width."""
        lines = [
            "Normal content line",
            f"{Ansi.BRIGHT_GREEN}Styled content line with ANSI{Ansi.RESET}",
            "Very long content line that significantly exceeds width " * 5,
            "",
            "Short",
        ]
        panel = Panel(
            title="TEST TITLE",
            lines=lines,
            width=target_width,
            box_chars=box_style,
        )
        rendered = panel.render()
        assert len(rendered) == len(lines) + 2

        for idx, row in enumerate(rendered):
            vlen = visible_len(row)
            assert vlen == target_width, (
                f"Line {idx} width violation: got {vlen}, expected {target_width}: {row!r}"
            )

    def test_panel_without_title(self) -> None:
        """Panel with empty title renders simple solid top border of exact width."""
        w = 40
        panel = Panel(title="", lines=["Hello world"], width=w)
        rendered = panel.render()
        assert len(rendered) == 3
        for row in rendered:
            assert visible_len(row) == w
        assert rendered[0] == f"┌{'─' * (w - 2)}┐"
        assert rendered[-1] == f"└{'─' * (w - 2)}┘"

    def test_panel_with_long_and_styled_title(self) -> None:
        """Panel truncates long title cleanly while maintaining exact top bar width."""
        w = 30
        long_title = "Extremely Long Panel Title That Cannot Possibly Fit"
        panel = Panel(title=long_title, lines=["Line 1"], width=w)
        rendered = panel.render()
        top_bar = rendered[0]
        assert visible_len(top_bar) == w
        assert "…" in top_bar

        # Styled title
        styled_title = f"{Ansi.RED}Alert: {Ansi.BOLD}System Warning{Ansi.RESET}"
        panel_styled = Panel(title=styled_title, lines=["Line 1"], width=w)
        rendered_styled = panel_styled.render()
        assert visible_len(rendered_styled[0]) == w

    def test_panel_pad_content_flag(self) -> None:
        """pad_content=False uses inner_width = w - 2 instead of w - 4."""
        w = 30
        panel_padded = Panel(lines=["Content"], width=w, pad_content=True)
        panel_unpadded = Panel(lines=["Content"], width=w, pad_content=False)

        rendered_p = panel_padded.render()
        rendered_u = panel_unpadded.render()

        assert visible_len(rendered_p[1]) == w
        assert visible_len(rendered_u[1]) == w
        # Padded has space after vertical rail
        assert rendered_p[1].startswith("│ ")
        # Unpadded starts content directly after rail
        assert rendered_u[1].startswith("│Content")

    def test_panel_render_str(self) -> None:
        """render_str must return newline-joined rendered rows."""
        panel = Panel(title="TITLE", lines=["A", "B"], width=40)
        s = panel.render_str()
        assert isinstance(s, str)
        assert s == "\n".join(panel.render())

    def test_panel_render_divider(self) -> None:
        """render_divider must produce divider line of exact width with and without labels."""
        w = 50
        panel = Panel(width=w)

        # Without label
        div_plain = panel.render_divider()
        assert visible_len(div_plain) == w
        assert div_plain == f"├{'─' * (w - 2)}┤"

        # With short label
        div_label = panel.render_divider("METRICS")
        assert visible_len(div_label) == w
        assert div_label.startswith("├─ METRICS ──")
        assert div_label.endswith("┤")

        # With long label exceeding width
        div_long = panel.render_divider("VERY LONG LABEL " * 10)
        assert visible_len(div_long) == w
        assert "…" in div_long


class TestLayoutComposition:
    """Tests for compose_vertical_stack and compose_horizontal_split."""

    def test_compose_vertical_stack(self) -> None:
        """compose_vertical_stack combines list of string lists or strings sequentially."""
        p1 = ["Row 1", "Row 2"]
        p2 = ["Row 3", "Row 4"]
        p3 = "Row 5"

        stacked = compose_vertical_stack([p1, p2, p3])  # type: ignore[arg-type]
        assert stacked == ["Row 1", "Row 2", "Row 3", "Row 4", "Row 5"]

        # Empty stack
        assert compose_vertical_stack([]) == []

    def test_compose_horizontal_split_equal_and_unequal_heights(self) -> None:
        """compose_horizontal_split aligns two columns side-by-side with padding."""
        left = ["L1", "L2", "L3"]
        right = ["R1", "R2"]
        gap = 2

        split = compose_horizontal_split(left, right, gap=gap)
        assert len(split) == 3

        # Left width is 2 ("L1"), right width is 2 ("R1"), gap is 2
        # Total line width should be 2 + 2 + 2 = 6
        for row in split:
            assert visible_len(row) == 6

        assert split[0] == "L1  R1"
        assert split[1] == "L2  R2"
        # Shorter column right is padded with spaces
        assert split[2] == "L3    "

    def test_compose_horizontal_split_with_ansi(self) -> None:
        """compose_horizontal_split correctly preserves widths when columns have ANSI escapes."""
        left = [f"{Ansi.BRIGHT_GREEN}Left{Ansi.RESET}"]
        right = [f"{Ansi.BRIGHT_RED}RightCol{Ansi.RESET}"]

        split = compose_horizontal_split(left, right, gap=1)
        assert len(split) == 1
        # Left visible len is 4, right visible len is 8, gap is 1 -> total visible 13
        assert visible_len(split[0]) == 13


class TestTableFormatting:
    """Tests for format_table_row."""

    def test_format_table_row_alignment(self) -> None:
        """format_table_row aligns columns according to specified alignments."""
        cells = ["BTC", "90500.00", "0.5"]
        widths = [6, 10, 6]
        alignments: list[Literal["left", "right", "center"]] = ["left", "right", "center"]

        row = format_table_row(cells, widths, alignments=alignments, sep=" | ")
        assert visible_len(row) == 6 + 3 + 10 + 3 + 6  # 28
        parts = row.split(" | ")
        assert parts[0] == "BTC   "
        assert parts[1] == "  90500.00"
        assert parts[2] == " 0.5  "

    def test_format_table_row_clipping(self) -> None:
        """format_table_row truncates cells that exceed column widths."""
        cells = ["VERY_LONG_SYMBOL_NAME", "123456789.00"]
        widths = [8, 6]
        row = format_table_row(cells, widths, sep=" ")
        assert visible_len(row) == 8 + 1 + 6  # 15
        parts = row.split(" ")
        assert parts[0] == "VERY_LO…"
        assert parts[1] == "12345…"


class TestTerminalDimensions:
    """Tests for get_terminal_dimensions."""

    def test_get_terminal_dimensions_overrides_and_minimums(self) -> None:
        """get_terminal_dimensions enforces min_cols and min_lines safety floors."""
        # Overrides above minimums
        cols, lines = get_terminal_dimensions(override_cols=100, override_lines=30)
        assert cols == 100
        assert lines == 30

        # Sub-minimum overrides clamped to minimums
        cols_low, lines_low = get_terminal_dimensions(override_cols=50, override_lines=10)
        assert cols_low == 80
        assert lines_low == 24

        # Custom minimums
        cols_custom, lines_custom = get_terminal_dimensions(
            override_cols=30, override_lines=15, min_cols=40, min_lines=10
        )
        assert cols_custom == 40
        assert lines_custom == 15
