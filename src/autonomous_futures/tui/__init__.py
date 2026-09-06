"""Terminal User Interface (TUI) package for Autonomous Futures Bot.

Pure Python standard library ANSI/Unicode box-drawing live monitoring dashboard
and non-blocking read-only telemetry reader.
"""

from .dashboard import Dashboard
from .formatters import (
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
from .layout import (
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
from .telemetry import (
    ClosedTradeSnapshot,
    DaemonHealthSnapshot,
    MarginAccountSnapshot,
    MarketRegimeSnapshot,
    PositionSnapshot,
    SafetyInvariantsSnapshot,
    TelemetryReader,
    TuiTelemetrySnapshot,
)

__all__ = [
    # Dashboard
    "Dashboard",
    # Telemetry
    "TelemetryReader",
    "TuiTelemetrySnapshot",
    "DaemonHealthSnapshot",
    "MarginAccountSnapshot",
    "MarketRegimeSnapshot",
    "PositionSnapshot",
    "ClosedTradeSnapshot",
    "SafetyInvariantsSnapshot",
    # Layout
    "Panel",
    "BoxChars",
    "LIGHT_BOX",
    "HEAVY_BOX",
    "DOUBLE_BOX",
    "ASCII_BOX",
    "get_terminal_dimensions",
    "compose_vertical_stack",
    "compose_horizontal_split",
    "format_table_row",
    # Formatters
    "Ansi",
    "AnsiColor",
    "strip_ansi",
    "visible_len",
    "visible_length",
    "pad_visible",
    "truncate_visible",
    "format_currency",
    "format_pnl",
    "format_percent",
    "format_spread_bps",
    "format_atr",
    "format_uptime",
    "format_relative_time",
    "render_progress_bar",
    "format_utilization_meter",
]
