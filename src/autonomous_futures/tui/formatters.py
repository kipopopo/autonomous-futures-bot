"""ANSI color styling, visible length calculations, and numeric formatting.

Zero external dependencies - standard library only.
Strictly preserves visible length invariants across styled and unstyled strings.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

# Regex matches all VT100 / ECMA-48 CSI escape sequences
ANSI_REGEX: re.Pattern[str] = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


class Ansi:
    """VT100 / ANSI escape sequences for text styling and colors."""

    RESET: str = "\033[0m"
    BOLD: str = "\033[1m"
    DIM: str = "\033[2m"
    UNDERLINE: str = "\033[4m"
    INVERSE: str = "\033[7m"

    # Standard Colors
    BLACK: str = "\033[30m"
    RED: str = "\033[31m"
    GREEN: str = "\033[32m"
    YELLOW: str = "\033[33m"
    BLUE: str = "\033[34m"
    MAGENTA: str = "\033[35m"
    CYAN: str = "\033[36m"
    WHITE: str = "\033[37m"

    # High-Intensity / Bright Colors
    BRIGHT_BLACK: str = "\033[90m"  # Gray
    BRIGHT_RED: str = "\033[91m"
    BRIGHT_GREEN: str = "\033[92m"
    BRIGHT_YELLOW: str = "\033[93m"
    BRIGHT_BLUE: str = "\033[94m"
    BRIGHT_MAGENTA: str = "\033[95m"
    BRIGHT_CYAN: str = "\033[96m"
    BRIGHT_WHITE: str = "\033[97m"

    # Background Colors
    BG_RED: str = "\033[41m"
    BG_GREEN: str = "\033[42m"
    BG_YELLOW: str = "\033[43m"
    BG_BLUE: str = "\033[44m"


# Architectural alias
AnsiColor = Ansi

# Top-level style aliases for convenience
RESET: str = Ansi.RESET
BOLD: str = Ansi.BOLD
DIM: str = Ansi.DIM
UNDERLINE: str = Ansi.UNDERLINE
RED: str = Ansi.RED
GREEN: str = Ansi.GREEN
YELLOW: str = Ansi.YELLOW
BLUE: str = Ansi.BLUE
MAGENTA: str = Ansi.MAGENTA
CYAN: str = Ansi.CYAN
WHITE: str = Ansi.WHITE
GRAY: str = Ansi.BRIGHT_BLACK
BRIGHT_RED: str = Ansi.BRIGHT_RED
BRIGHT_GREEN: str = Ansi.BRIGHT_GREEN
BRIGHT_YELLOW: str = Ansi.BRIGHT_YELLOW


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape codes from string."""
    return ANSI_REGEX.sub("", text)


def visible_len(text: str) -> int:
    """Return the visible column count of a string, ignoring ANSI codes."""
    return len(strip_ansi(text))


# Architectural alias
visible_length = visible_len


def pad_visible(
    text: str,
    width: int,
    align: Literal["left", "right", "center"] = "left",
    fill_char: str = " ",
) -> str:
    """Pad a string to an exact visible width respecting embedded ANSI codes."""
    current_len = visible_len(text)
    pad_needed = max(0, width - current_len)
    if pad_needed == 0:
        return text

    if align == "right":
        return (fill_char * pad_needed) + text
    elif align == "center":
        pad_left = pad_needed // 2
        pad_right = pad_needed - pad_left
        return (fill_char * pad_left) + text + (fill_char * pad_right)
    return text + (fill_char * pad_needed)


def truncate_visible(text: str, max_width: int, ellipsis: str = "…") -> str:
    """Truncate a string to max visible width without breaking ANSI escapes.

    If text exceeds max_width, ANSI codes are stripped prior to clipping to
    guarantee that no escape sequences are left unclosed, and RESET is appended.
    """
    if visible_len(text) <= max_width:
        return text

    if max_width <= 0:
        return ""
    if max_width <= visible_len(ellipsis):
        return strip_ansi(ellipsis)[:max_width]

    has_ansi = visible_len(text) != len(text)
    plain = strip_ansi(text)
    clipped_plain = plain[: max_width - visible_len(ellipsis)]
    reset = Ansi.RESET if has_ansi else ""
    return f"{clipped_plain}{ellipsis}{reset}"


def format_currency(
    val: Decimal | float | int,
    prefix: str = "$",
    decimals: int = 2,
    color: bool = False,
) -> str:
    """Format numeric value as currency with optional coloring."""
    v = Decimal(str(val))
    is_negative = v < 0
    abs_v = abs(v)
    formatted = f"{abs_v:,.{decimals}f}"

    if is_negative:
        result = f"-{prefix}{formatted}"
    else:
        result = f"{prefix}{formatted}"

    if not color:
        return result
    if v > 0:
        return f"{Ansi.BRIGHT_GREEN}{result}{Ansi.RESET}"
    elif v < 0:
        return f"{Ansi.BRIGHT_RED}{result}{Ansi.RESET}"
    return f"{Ansi.DIM}{result}{Ansi.RESET}"


def format_pnl(
    val: Decimal | float | int,
    prefix: str = "$",
    decimals: int = 2,
    include_sign: bool = True,
    color: bool = True,
    pct: Decimal | float | None = None,
    enabled: bool | None = None,
) -> str:
    """Format signed profit-and-loss value with green/red coloring."""
    if enabled is not None:
        color = enabled

    v = Decimal(str(val))
    abs_v = abs(v)
    formatted = f"{abs_v:,.{decimals}f}"

    if v > 0:
        sign = "+" if include_sign else ""
        text = f"{sign}{prefix}{formatted}"
    elif v < 0:
        text = f"-{prefix}{formatted}"
    else:
        text = f"{prefix}{formatted}"

    if pct is not None:
        pct_text = format_percent(pct, decimals=1, include_sign=True, color=False)
        text = f"{text} ({pct_text})"

    if not color:
        return text

    if v > 0:
        return f"{Ansi.BRIGHT_GREEN}{text}{Ansi.RESET}"
    elif v < 0:
        return f"{Ansi.BRIGHT_RED}{text}{Ansi.RESET}"
    return f"{Ansi.DIM}{text}{Ansi.RESET}"


def format_percent(
    val: Decimal | float | int,
    decimals: int = 1,
    include_sign: bool = True,
    color: bool = False,
) -> str:
    """Format numeric value as percentage string."""
    v = Decimal(str(val))
    abs_v = abs(v)
    formatted = f"{abs_v:.{decimals}f}%"

    if v > 0:
        sign = "+" if include_sign else ""
        text = f"{sign}{formatted}"
        return f"{Ansi.BRIGHT_GREEN}{text}{Ansi.RESET}" if color else text
    elif v < 0:
        text = f"-{formatted}"
        return f"{Ansi.BRIGHT_RED}{text}{Ansi.RESET}" if color else text
    return f"{formatted}"


def render_progress_bar(
    pct: float,
    width: int = 10,
    fill_char: str = "█",
    empty_char: str = "░",
    warn_pct: float = 80.0,
    color: bool = True,
    enabled: bool | None = None,
    ascii_only: bool = False,
    lower_is_worse: bool = False,
) -> str:
    """Render a visual progress bar with threshold color styling.

    Contractual function required by Phase 260 M1.
    """
    if enabled is not None:
        color = enabled

    if ascii_only:
        if fill_char == "█":
            fill_char = "#"
        if empty_char == "░":
            empty_char = "-"

    clamped_pct = max(0.0, min(100.0, float(pct)))
    filled_chars = int(round((clamped_pct / 100.0) * width))
    filled_chars = max(0, min(width, filled_chars))
    empty_chars = width - filled_chars

    bar = f"[{fill_char * filled_chars}{empty_char * empty_chars}]"
    if not color:
        return bar

    if lower_is_worse:
        if pct <= warn_pct:
            return f"{Ansi.BRIGHT_RED}{bar}{Ansi.RESET}"
        elif pct <= (warn_pct * 1.5):
            return f"{Ansi.BRIGHT_YELLOW}{bar}{Ansi.RESET}"
        return f"{Ansi.BRIGHT_GREEN}{bar}{Ansi.RESET}"
    else:
        if pct >= warn_pct:
            return f"{Ansi.BRIGHT_RED}{bar}{Ansi.RESET}"
        elif pct >= (warn_pct * 0.625):  # e.g. 50% when warn_pct=80
            return f"{Ansi.BRIGHT_YELLOW}{bar}{Ansi.RESET}"
        return f"{Ansi.BRIGHT_GREEN}{bar}{Ansi.RESET}"


def format_utilization_meter(
    utilization_pct: float,
    width: int = 16,
    enabled: bool = True,
    ascii_only: bool = False,
) -> str:
    """Format margin utilization meter with bar and percentage readout."""
    fill_sym = "#" if ascii_only else "█"
    empty_sym = "-" if ascii_only else "░"
    bar = render_progress_bar(
        pct=utilization_pct,
        width=width,
        fill_char=fill_sym,
        empty_char=empty_sym,
        warn_pct=80.0,
        color=enabled,
    )
    pct_str = f"{utilization_pct:5.1f}% / 80.0% max"
    if not enabled:
        return f"{bar} {pct_str}"
    if utilization_pct >= 80.0:
        return f"{bar} {Ansi.BRIGHT_RED}{pct_str}{Ansi.RESET}"
    elif utilization_pct >= 50.0:
        return f"{bar} {Ansi.BRIGHT_YELLOW}{pct_str}{Ansi.RESET}"
    return f"{bar} {Ansi.BRIGHT_GREEN}{pct_str}{Ansi.RESET}"


def format_spread_bps(
    spread_bps: Decimal | float | int,
    warn_bps: float = 5.0,
    halt_bps: float = 20.0,
    color: bool = True,
    enabled: bool | None = None,
) -> str:
    """Format instantaneous bid-ask spread in basis points."""
    if enabled is not None:
        color = enabled

    s = float(spread_bps)
    text = f"{s:5.2f} bps"
    if not color:
        return text

    if s >= halt_bps:
        return f"{Ansi.BRIGHT_RED}{Ansi.BOLD}{text} (HALT){Ansi.RESET}"
    elif s >= warn_bps:
        return f"{Ansi.BRIGHT_YELLOW}{text}{Ansi.RESET}"
    return f"{Ansi.BRIGHT_GREEN}{text}{Ansi.RESET}"


def format_atr(atr: Decimal | float | int, decimals: int = 4) -> str:
    """Format rolling Average True Range."""
    v = Decimal(str(atr))
    target_exp = Decimal(f"1e-{decimals}") if decimals > 0 else Decimal("1")
    quantized = v.quantize(target_exp, rounding=ROUND_HALF_UP)
    return f"{quantized:.{decimals}f}"


def format_uptime(seconds: float | int) -> str:
    """Format cumulative runtime into compact human-readable duration."""
    total_sec = max(0, int(seconds))
    if total_sec < 60:
        return f"{total_sec}s"
    minutes, sec = divmod(total_sec, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m {sec:02d}s"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h {minutes:02d}m {sec:02d}s"


def format_relative_time(
    dt_or_iso: datetime | str,
    reference: datetime | None = None,
) -> str:
    """Format relative elapsed time from timestamp (e.g. '0.8s ago')."""
    if isinstance(dt_or_iso, str):
        try:
            target = datetime.fromisoformat(dt_or_iso.replace("Z", "+00:00"))
        except ValueError:
            return dt_or_iso
    else:
        target = dt_or_iso

    now = reference or datetime.now(UTC)
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)

    diff_sec = (now - target).total_seconds()
    if diff_sec < 0:
        return "just now"
    if diff_sec < 60:
        return f"{diff_sec:.1f}s ago"
    minutes = int(diff_sec // 60)
    rem_sec = int(diff_sec % 60)
    if minutes < 60:
        return f"{minutes}m {rem_sec:02d}s ago"
    hours = int(minutes // 60)
    rem_min = int(minutes % 60)
    return f"{hours}h {rem_min:02d}m ago"
