#!/usr/bin/env python3
"""Autonomous Futures Bot: 24/7 Live Paper Trading Terminal UI (TUI) Dashboard.

Provides real-time interactive monitoring and headless snapshot inspection
of the 24/7 background live paper trading daemon on Kainode VPS. Aggregates
portfolio margin, 4-asset market regimes, active positions, closed trade fills,
and zero-order safety invariants with zero external dependencies.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Ensure repository root / src is on sys.path for direct script execution
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.tui.dashboard import Dashboard  # noqa: E402
from autonomous_futures.tui.telemetry import TelemetryReader  # noqa: E402


def init_terminal_environment() -> None:
    """Initialize cross-platform terminal settings (VT100 & UTF-8)."""
    # Reconfigure stdout encoding to UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Windows-specific VT100 initialization
    if sys.platform == "win32":
        try:
            os.system("")
        except Exception:
            pass

        try:
            import ctypes
            from ctypes import wintypes

            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                kernel32 = windll.kernel32
                std_output_handle = -11
                enable_vt = 0x0004

                h_stdout = kernel32.GetStdHandle(std_output_handle)
                if h_stdout and h_stdout != -1:
                    mode = wintypes.DWORD()
                    if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
                        new_mode = mode.value | enable_vt
                        kernel32.SetConsoleMode(h_stdout, new_mode)
        except Exception:
            pass


def resolve_terminal_dimensions(
    override_width: int | None = None,
    override_height: int | None = None,
    fallback: tuple[int, int] = (80, 24),
) -> tuple[int, int]:
    """Resolve current visible terminal dimensions with minimum safety clamping."""
    detected = shutil.get_terminal_size(fallback=fallback)
    w = override_width if override_width is not None else detected.columns
    h = override_height if override_height is not None else detected.lines
    return max(w, 40), max(h, 10)


class KeyboardInputController:
    """Cross-platform non-blocking keyboard input listener."""

    def __init__(self) -> None:
        self._is_win = sys.platform == "win32"

    def poll_key(self) -> str | None:
        """Poll for a single pending keystroke without blocking."""
        if self._is_win:
            try:
                import msvcrt

                if msvcrt.kbhit():
                    return msvcrt.getwch()
            except Exception:
                return None
        else:
            try:
                import select

                if sys.stdin.isatty():
                    r, _, _ = select.select([sys.stdin], [], [], 0.0)
                    if r:
                        return sys.stdin.read(1)
            except Exception:
                return None
        return None


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for the Live Paper TUI Dashboard."""
    parser = argparse.ArgumentParser(
        prog="monitor_live_paper_tui.py",
        description=(
            "Autonomous Futures Bot: 24/7 Live Paper Trading Terminal UI (TUI) Dashboard. "
            "Monitors portfolio margin, market regimes, active positions, and safety invariants."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path(os.environ.get("AUTONOMOUS_FUTURES_STORAGE_DIR", "artifacts/paper_live")),
        help="Directory containing daemon health JSON and SQLite ledgers",
    )
    parser.add_argument(
        "--refresh-rate",
        type=float,
        default=float(os.environ.get("TUI_REFRESH_RATE", "1.0")),
        help="Refresh interval in seconds for interactive auto-refresh mode",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Headless snapshot mode: render a single frame to stdout and exit cleanly",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=bool(os.environ.get("NO_COLOR")),
        help="Disable ANSI color codes and formatting escapes",
    )
    parser.add_argument(
        "--ascii-only",
        action="store_true",
        default=bool(os.environ.get("TUI_ASCII_ONLY")),
        help="Use ASCII borders (+ - |) instead of UTF-8 Unicode box characters",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Override terminal width in columns (default: auto-detect)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=None,
        help="Override terminal height in lines (default: auto-detect)",
    )
    return parser


def parse_cli_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse and validate CLI arguments, enforcing range constraints."""
    parser = build_arg_parser()
    parsed = parser.parse_args(args)

    if parsed.refresh_rate <= 0.0:
        parser.error("--refresh-rate must be greater than 0.0 seconds")
    if parsed.width is not None and parsed.width < 40:
        parser.error("--width must be at least 40 columns")
    if parsed.height is not None and parsed.height < 10:
        parser.error("--height must be at least 10 lines")

    return parsed


def run_snapshot_mode(
    storage_dir: Path,
    color_enabled: bool,
    ascii_only: bool,
    width_override: int | None,
    height_override: int | None,
) -> int:
    """Execute single-pass headless snapshot and exit cleanly."""
    reader = TelemetryReader(storage_dir=storage_dir)
    dashboard = Dashboard(
        reader=reader,
        color_enabled=color_enabled,
        ascii_only=ascii_only,
    )
    width, height = resolve_terminal_dimensions(width_override, height_override)
    frame = dashboard.render(width=width, height=height)
    sys.stdout.write(frame + "\n")
    sys.stdout.flush()
    return 0


def run_interactive_mode(
    storage_dir: Path,
    refresh_rate: float,
    color_enabled: bool,
    ascii_only: bool,
    width_override: int | None,
    height_override: int | None,
) -> int:
    """Run interactive continuous TUI dashboard with auto-refresh."""
    reader = TelemetryReader(storage_dir=storage_dir)
    dashboard = Dashboard(
        reader=reader,
        color_enabled=color_enabled,
        ascii_only=ascii_only,
    )
    kbd = KeyboardInputController()
    stop_requested = threading.Event()

    def _sig_handler(signum: int, frame: Any) -> None:
        stop_requested.set()

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)

    try:
        # Hide terminal cursor
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        while not stop_requested.is_set():
            width, height = resolve_terminal_dimensions(width_override, height_override)
            frame = dashboard.render(width=width, height=height)

            # Clear screen and draw frame at home position
            sys.stdout.write("\033[2J\033[H" + frame)
            sys.stdout.flush()

            # Responsive sub-tick sleep checking for keypresses
            sub_tick = 0.05
            elapsed = 0.0
            while elapsed < refresh_rate and not stop_requested.is_set():
                key = kbd.poll_key()
                if key in ("q", "Q", "\x03"):  # 'q' or Ctrl+C
                    stop_requested.set()
                    break
                elif key in ("r", "R"):  # force immediate refresh
                    break
                time.sleep(min(sub_tick, refresh_rate - elapsed))
                elapsed += sub_tick

    except KeyboardInterrupt:
        stop_requested.set()
    finally:
        # Unconditional cursor restore and styling reset
        sys.stdout.write("\033[?25h\033[0m\n")
        sys.stdout.flush()

    return 0


def main(args: list[str] | None = None) -> int:
    """CLI driver entry point."""
    init_terminal_environment()
    parsed = parse_cli_args(args)

    # Determine whether color output is active
    color_enabled = not parsed.no_color
    if os.environ.get("NO_COLOR"):
        color_enabled = False

    if parsed.once:
        return run_snapshot_mode(
            storage_dir=parsed.storage_dir,
            color_enabled=color_enabled,
            ascii_only=parsed.ascii_only,
            width_override=parsed.width,
            height_override=parsed.height,
        )

    return run_interactive_mode(
        storage_dir=parsed.storage_dir,
        refresh_rate=parsed.refresh_rate,
        color_enabled=color_enabled,
        ascii_only=parsed.ascii_only,
        width_override=parsed.width,
        height_override=parsed.height,
    )


if __name__ == "__main__":
    sys.exit(main())
