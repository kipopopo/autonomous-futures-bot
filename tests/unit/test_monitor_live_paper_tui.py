"""Unit tests for the CLI monitor runner script (scripts/monitor_live_paper_tui.py).

Covers:
1. Argument parser construction, environment variable defaults, and boundary validation.
2. Cross-platform terminal environment initialization and dimension resolution.
3. Non-blocking keyboard controller behavior.
4. Headless snapshot execution (--once) returning exit code 0.
5. End-to-end CLI driver subprocess execution.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repository root is on sys.path for scripts import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.monitor_live_paper_tui import (  # noqa: E402
    KeyboardInputController,
    build_arg_parser,
    init_terminal_environment,
    main,
    parse_cli_args,
    resolve_terminal_dimensions,
    run_snapshot_mode,
)


class TestCliArgumentParsing:
    """Tests for CLI arguments, environment variable defaults, and validation."""

    def test_default_cli_arguments(self) -> None:
        """build_arg_parser default values when no flags or env vars are supplied."""
        parser = build_arg_parser()
        args = parser.parse_args([])

        assert args.storage_dir == Path("artifacts/paper_live")
        assert args.refresh_rate == 1.0
        assert args.once is False
        assert args.no_color is False
        assert args.ascii_only is False
        assert args.width is None
        assert args.height is None

    def test_env_var_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables correctly seed CLI argument defaults."""
        monkeypatch.setenv("AUTONOMOUS_FUTURES_STORAGE_DIR", "custom/env/storage")
        monkeypatch.setenv("TUI_REFRESH_RATE", "2.5")
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("TUI_ASCII_ONLY", "1")

        parser = build_arg_parser()
        args = parser.parse_args([])

        assert args.storage_dir == Path("custom/env/storage")
        assert args.refresh_rate == 2.5
        assert args.no_color is True
        assert args.ascii_only is True

    def test_valid_cli_overrides(self) -> None:
        """Explicit command-line flags override defaults."""
        cmd = [
            "--storage-dir",
            "test/storage",
            "--refresh-rate",
            "0.5",
            "--once",
            "--no-color",
            "--ascii-only",
            "--width",
            "120",
            "--height",
            "35",
        ]
        parsed = parse_cli_args(cmd)
        assert parsed.storage_dir == Path("test/storage")
        assert parsed.refresh_rate == 0.5
        assert parsed.once is True
        assert parsed.no_color is True
        assert parsed.ascii_only is True
        assert parsed.width == 120
        assert parsed.height == 35

    def test_refresh_rate_boundary_validation(self) -> None:
        """refresh_rate <= 0.0 must raise parser error (SystemExit)."""
        with pytest.raises(SystemExit):
            parse_cli_args(["--refresh-rate", "0.0"])

        with pytest.raises(SystemExit):
            parse_cli_args(["--refresh-rate", "-0.5"])

    def test_dimension_boundary_validation(self) -> None:
        """Width < 40 or Height < 10 must raise parser error (SystemExit)."""
        with pytest.raises(SystemExit):
            parse_cli_args(["--width", "39"])

        with pytest.raises(SystemExit):
            parse_cli_args(["--height", "9"])


class TestTerminalEnvironmentAndDimensions:
    """Tests for terminal environment initialization and dimension resolution."""

    def test_init_terminal_environment_safety(self) -> None:
        """init_terminal_environment executes safely across platforms without raising."""
        init_terminal_environment()

    def test_resolve_terminal_dimensions_clamping(self) -> None:
        """resolve_terminal_dimensions enforces minimum 40x10 safety floor."""
        w, h = resolve_terminal_dimensions(override_width=20, override_height=5)
        assert w == 40
        assert h == 10

        w_norm, h_norm = resolve_terminal_dimensions(override_width=100, override_height=30)
        assert w_norm == 100
        assert h_norm == 30

    def test_keyboard_input_controller_poll(self) -> None:
        """KeyboardInputController.poll_key returns None when no keys are pending."""
        kbd = KeyboardInputController()
        key = kbd.poll_key()
        assert key is None or isinstance(key, str)


class TestSnapshotExecution:
    """Tests for headless snapshot mode execution and exit codes."""

    def test_run_snapshot_mode_direct(self, tmp_path: Path) -> None:
        """run_snapshot_mode renders single frame and returns 0."""
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            exit_code = run_snapshot_mode(
                storage_dir=tmp_path,
                color_enabled=False,
                ascii_only=True,
                width_override=80,
                height_override=24,
            )

        assert exit_code == 0
        output = captured_stdout.getvalue()
        assert "AUTONOMOUS FUTURES BOT" in output
        assert "PORTFOLIO MARGIN" in output

    def test_main_snapshot_mode(self, tmp_path: Path) -> None:
        """main() with --once flag exits cleanly with status 0."""
        captured_stdout = io.StringIO()
        with patch("sys.stdout", captured_stdout):
            ret = main(["--once", "--storage-dir", str(tmp_path), "--no-color"])

        assert ret == 0
        assert "AUTONOMOUS FUTURES BOT" in captured_stdout.getvalue()

    def test_e2e_cli_script_subprocess_execution(self, tmp_path: Path) -> None:
        """Execute scripts/monitor_live_paper_tui.py via subprocess verifying exit code 0."""
        script_path = Path("scripts/monitor_live_paper_tui.py").resolve()
        assert script_path.is_file()

        cmd = [
            sys.executable,
            str(script_path),
            "--once",
            "--storage-dir",
            str(tmp_path),
            "--no-color",
            "--ascii-only",
            "--width",
            "80",
            "--height",
            "24",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
        assert "AUTONOMOUS FUTURES BOT" in result.stdout
        assert "PORTFOLIO MARGIN" in result.stdout
        assert "SAFETY GUARDRAILS" in result.stdout
        assert "\033" not in result.stdout

    def test_e2e_cli_historical_phase259_snapshot(self) -> None:
        """Execute scripts/monitor_live_paper_tui.py against artifacts/research/phase259/."""
        phase259_dir = Path("artifacts/research/phase259").resolve()
        if not phase259_dir.is_dir():
            pytest.skip("artifacts/research/phase259 does not exist")

        script_path = Path("scripts/monitor_live_paper_tui.py").resolve()
        cmd = [
            sys.executable,
            str(script_path),
            "--once",
            "--storage-dir",
            str(phase259_dir),
            "--no-color",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        assert result.returncode == 0
        assert "SHUTDOWN_CLEAN" in result.stdout
        assert "162877" in result.stdout
        assert "100.00 USDT" in result.stdout
