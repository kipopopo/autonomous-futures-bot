"""Unicode box-drawing primitives, panel containers, and layout reflow.

Zero external dependencies - standard library only.
Strictly preserves visible length invariants across terminal widths.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Literal

from .formatters import (
    Ansi,
    pad_visible,
    truncate_visible,
    visible_len,
)


@dataclass(slots=True, frozen=True)
class BoxChars:
    """Character set for framing rectangular panels and table grids."""

    tl: str = "┌"  # Top-left corner
    tr: str = "┐"  # Top-right corner
    bl: str = "└"  # Bottom-left corner
    br: str = "┘"  # Bottom-right corner
    h: str = "─"  # Horizontal rail
    v: str = "│"  # Vertical rail
    lt: str = "├"  # Left T-junction (divider start)
    rt: str = "┤"  # Right T-junction (divider end)
    tt: str = "┬"  # Top T-junction (column divider)
    bt: str = "┴"  # Bottom T-junction (column divider)
    cross: str = "┼"  # Interior cross junction


# Standard Character Set Presets
LIGHT_BOX = BoxChars()
HEAVY_BOX = BoxChars(
    tl="┏",
    tr="┓",
    bl="┗",
    br="┛",
    h="━",
    v="┃",
    lt="┣",
    rt="┫",
    tt="┳",
    bt="┻",
    cross="╋",
)
DOUBLE_BOX = BoxChars(
    tl="╔",
    tr="╗",
    bl="╚",
    br="╝",
    h="═",
    v="║",
    lt="╠",
    rt="╣",
    tt="╦",
    bt="╩",
    cross="╬",
)
ASCII_BOX = BoxChars(
    tl="+",
    tr="+",
    bl="+",
    br="+",
    h="-",
    v="|",
    lt="+",
    rt="+",
    tt="+",
    bt="+",
    cross="+",
)


def get_terminal_dimensions(
    default_cols: int = 80,
    default_lines: int = 24,
    override_cols: int | None = None,
    override_lines: int | None = None,
    min_cols: int = 80,
    min_lines: int = 24,
) -> tuple[int, int]:
    """Detect current terminal size with overrides and minimum boundaries."""
    size = shutil.get_terminal_size(fallback=(default_cols, default_lines))
    cols = override_cols if override_cols is not None else size.columns
    lines = override_lines if override_lines is not None else size.lines

    return max(cols, min_cols), max(lines, min_lines)


@dataclass(slots=True)
class Panel:
    """Framed rectangular panel with title, borders, and width invariant enforcement."""

    title: str = ""
    lines: list[str] = field(default_factory=list)
    width: int = 80
    box_chars: BoxChars = LIGHT_BOX
    title_color: str = ""
    border_color: str = ""
    pad_content: bool = True

    def render(self) -> list[str]:
        """Render panel into framed rows strictly adhering to visible length invariant.

        Every rendered line r satisfies: visible_len(r) == width.
        Every interior line c satisfies: visible_len(c) == width - 2.
        """
        w = max(self.width, 6)
        bc = self.box_chars
        b_color = self.border_color
        t_color = self.title_color
        reset = Ansi.RESET if (b_color or t_color) else ""

        output: list[str] = []

        # 1. Render Top Border with optional Title
        if not self.title:
            top_bar = f"{bc.tl}{bc.h * (w - 2)}{bc.tr}"
            output.append(f"{b_color}{top_bar}{reset}")
        else:
            # Title header format: ┌─ TITLE ──────┐
            max_title_len = max(0, w - 6)
            title_text = truncate_visible(self.title, max_title_len)
            title_vlen = visible_len(title_text)
            fill_len = max(0, w - 5 - title_vlen)

            top_line = (
                f"{b_color}{bc.tl}{bc.h} {reset}"
                f"{t_color}{title_text}{reset}"
                f"{b_color} {bc.h * fill_len}{bc.tr}{reset}"
            )
            output.append(top_line)

        # 2. Render Interior Content Lines
        inner_width = (w - 4) if self.pad_content else (w - 2)
        for raw_line in self.lines:
            # Normalization: clip to inner budget, then pad
            truncated = truncate_visible(raw_line, inner_width)
            padded = pad_visible(truncated, inner_width, align="left")

            if self.pad_content:
                interior = f" {padded} "
            else:
                interior = padded

            # Guaranteed: visible_len(interior) == w - 2
            framed = f"{b_color}{bc.v}{reset}{interior}{b_color}{bc.v}{reset}"
            output.append(framed)

        # 3. Render Bottom Border
        bot_bar = f"{bc.bl}{bc.h * (w - 2)}{bc.br}"
        output.append(f"{b_color}{bot_bar}{reset}")

        return output

    def render_str(self) -> str:
        """Render panel as a newline-joined string."""
        return "\n".join(self.render())

    def render_divider(self, label: str = "") -> str:
        """Render a horizontal divider line of exact panel width."""
        w = max(self.width, 6)
        bc = self.box_chars
        b_color = self.border_color
        reset = Ansi.RESET if b_color else ""

        if not label:
            div = f"{bc.lt}{bc.h * (w - 2)}{bc.rt}"
            return f"{b_color}{div}{reset}"

        max_label_len = max(0, w - 6)
        label_text = truncate_visible(label, max_label_len)
        label_vlen = visible_len(label_text)
        fill_len = max(0, w - 5 - label_vlen)

        return (
            f"{b_color}{bc.lt}{bc.h} {reset}{label_text}{b_color} {bc.h * fill_len}{bc.rt}{reset}"
        )


def compose_vertical_stack(panels: list[list[str]] | list[str]) -> list[str]:
    """Combine discrete panel line collections vertically into a single list."""
    combined: list[str] = []
    for item in panels:
        if isinstance(item, list):
            combined.extend(item)
        else:
            combined.append(item)
    return combined


def compose_horizontal_split(
    left: list[str],
    right: list[str],
    gap: int = 1,
    fill_char: str = " ",
) -> list[str]:
    """Combine two columns side-by-side ensuring exact row alignment.

    Pads the shorter column with empty lines matching its visible width.
    """
    left_width = max((visible_len(line) for line in left), default=0)
    right_width = max((visible_len(line) for line in right), default=0)
    total_lines = max(len(left), len(right))

    spacer = fill_char * gap
    result: list[str] = []

    for i in range(total_lines):
        l_line = left[i] if i < len(left) else ""
        r_line = right[i] if i < len(right) else ""

        padded_l = pad_visible(l_line, left_width, align="left", fill_char=fill_char)
        padded_r = pad_visible(r_line, right_width, align="left", fill_char=fill_char)

        result.append(f"{padded_l}{spacer}{padded_r}")

    return result


def format_table_row(
    cells: list[str],
    col_widths: list[int],
    alignments: list[Literal["left", "right", "center"]] | None = None,
    sep: str = " ",
) -> str:
    """Format table columns with per-cell alignment, clipping, and padding."""
    aligns = alignments or ["left"] * len(cells)
    formatted_cells: list[str] = []

    for i, width in enumerate(col_widths):
        cell_text = cells[i] if i < len(cells) else ""
        align = aligns[i] if i < len(aligns) else "left"

        clipped = truncate_visible(cell_text, width)
        padded = pad_visible(clipped, width, align=align)
        formatted_cells.append(padded)

    return sep.join(formatted_cells)
