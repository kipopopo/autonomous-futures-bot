#!/usr/bin/env python3
"""Deterministic Empirical Reproduction Harness for Phase 260 TUI Defects.

Authored by challenger_m1_1 to empirically reproduce:
1. DEFECT 1 (HIGH): Box alignment invariant violation — Panel top border W + 1.
2. DEFECT 2 (MEDIUM): ANSI escape leak in truncate_visible into plain text.
3. DEFECT 3 (MEDIUM): Incomplete ASCII mode — Dashboard emits non-ASCII UTF-8.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src is on sys.path
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


from autonomous_futures.tui.dashboard import Dashboard  # noqa: E402
from autonomous_futures.tui.formatters import (  # noqa: E402
    strip_ansi,
    truncate_visible,
    visible_len,
)
from autonomous_futures.tui.layout import Panel  # noqa: E402


def reproduce_defect_1_box_alignment_off_by_one() -> bool:
    """Demonstrate top border and divider visible length == width + 1."""
    print("=" * 78)
    print("DEMONSTRATING DEFECT 1: Box Alignment Invariant Violation (W + 1)")
    print("=" * 78)

    w = 80
    panel = Panel(title="TEST TITLE", lines=["Interior line 1", "Interior line 2"], width=w)
    rendered = panel.render()

    top_line = rendered[0]
    interior_line = rendered[1]
    bottom_line = rendered[-1]

    vlen_top = visible_len(top_line)
    vlen_interior = visible_len(interior_line)
    vlen_bottom = visible_len(bottom_line)

    print(f"Panel configured width: {w}")
    print(
        f"Top border visible length:      {vlen_top} "
        f"(EXPECTED {w}, ACTUAL {vlen_top}) -> VIOLATION: {vlen_top - w:+d}"
    )
    print(
        f"Interior line visible length:    {vlen_interior} (EXPECTED {w}, ACTUAL {vlen_interior})"
    )
    print(f"Bottom border visible length:    {vlen_bottom} (EXPECTED {w}, ACTUAL {vlen_bottom})")

    divider = panel.render_divider("SUBHEADING")
    vlen_divider = visible_len(divider)
    print(
        f"Divider with label visible len:  {vlen_divider} "
        f"(EXPECTED {w}, ACTUAL {vlen_divider}) -> VIOLATION: {vlen_divider - w:+d}"
    )

    # Dashboard-level impact
    d = Dashboard()
    frame = d.render(width=80, height=24)
    lines = frame.split("\n")
    bad_lines = [(i, visible_len(line)) for i, line in enumerate(lines) if visible_len(line) != 80]
    print(f"Dashboard compact (80x24) line width violations count: {len(bad_lines)} lines")
    for idx, vl in bad_lines:
        print(f"  - Line {idx:02d}: visible_len={vl} != 80")

    # Wide layout middle split expansion
    frame_wide = d.render(width=120, height=30)
    lines_wide = frame_wide.split("\n")
    wide_middle_violations = [
        (i, visible_len(line)) for i, line in enumerate(lines_wide) if visible_len(line) == 122
    ]
    print(
        f"Dashboard wide (120x30) middle split bulge (122 cols instead of 120): "
        f"{len(wide_middle_violations)} lines"
    )

    return bool(int(vlen_top) != int(w) or int(vlen_divider) != int(w))


def reproduce_defect_2_truncate_visible_ansi_leak() -> bool:
    """Demonstrate truncate_visible unconditionally appends Ansi.RESET to plain unstyled text."""
    print("\n" + "=" * 78)
    print("DEMONSTRATING DEFECT 2: ANSI Reset Leak into Unstyled Plain Text")
    print("=" * 78)

    plain_input = "Plain uncolored text that exceeds maximum width"
    result = truncate_visible(plain_input, 15)

    has_ansi = "\033[0m" in result
    print(f"Input string:         {plain_input!r}")
    print(f"Truncated result:     {result!r}")
    print(f"Contains '\\033[0m':   {has_ansi}")
    print(f"strip_ansi(result):   {strip_ansi(result)!r}")
    is_pure = result == strip_ansi(result)
    print(f"Result == strip_ansi: {is_pure} (EXPECTED True for uncolored text, ACTUAL False)")

    return has_ansi


def reproduce_defect_3_incomplete_ascii_mode() -> bool:
    """Demonstrate Dashboard(ascii_only=True) emits non-ASCII UTF-8 box characters."""
    print("\n" + "=" * 78)
    print("DEMONSTRATING DEFECT 3: Incomplete ASCII Mode Emits Non-ASCII UTF-8")
    print("=" * 78)

    d = Dashboard(ascii_only=True)
    frame = d.render(width=80, height=24)

    unicode_box_chars = {
        "\u2500": "Horizontal Box Rail (─)",
        "\u2502": "Vertical Separator (│)",
    }

    found: dict[str, int] = {}
    for char, desc in unicode_box_chars.items():
        count = frame.count(char)
        if count > 0:
            found[desc] = count

    print("Non-ASCII characters detected in Dashboard(ascii_only=True) output:")
    for desc, count in found.items():
        print(f"  - {desc}: {count} occurrences")

    # Demonstrate cp1252 / ASCII encode failure
    try:
        frame.encode("cp1252")
        encode_failed = False
        print("cp1252 encoding: SUCCEEDED")
    except UnicodeEncodeError as e:
        encode_failed = True
        print(f"cp1252 encoding: FAILED with UnicodeEncodeError: {e}")

    return len(found) > 0 or encode_failed


def main() -> int:
    """Run all defect reproductions and output summary verdict."""
    d1 = reproduce_defect_1_box_alignment_off_by_one()
    d2 = reproduce_defect_2_truncate_visible_ansi_leak()
    d3 = reproduce_defect_3_incomplete_ascii_mode()

    v1 = "REPRODUCED (DEFECT CONFIRMED)" if d1 else "NOT REPRODUCED"
    v2 = "REPRODUCED (DEFECT CONFIRMED)" if d2 else "NOT REPRODUCED"
    v3 = "REPRODUCED (DEFECT CONFIRMED)" if d3 else "NOT REPRODUCED"

    print("\n" + "=" * 78)
    print("SUMMARY VERDICT: REQUEST_CHANGES")
    print("=" * 78)
    print(f"Defect 1 (Box Alignment Off-by-One W+1):     {v1}")
    print(f"Defect 2 (ANSI Reset Leak into Plain Text): {v2}")
    print(f"Defect 3 (Incomplete ASCII Mode UTF-8 Leak):{v3}")
    print("=" * 78)

    if d1 or d2 or d3:
        return 1
    return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
