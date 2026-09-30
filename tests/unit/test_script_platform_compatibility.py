"""Cross-platform behavior contracts for Python scripts included in CI mypy checks."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.monitor_live_paper_tui import KeyboardInputController  # noqa: E402
from scripts.run_autonomous_scheduler import _child_process_creation_flags  # noqa: E402


def test_windows_keyboard_controller_rejects_non_text_key_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    msvcrt = types.ModuleType("msvcrt")
    msvcrt.kbhit = lambda: True  # type: ignore[attr-defined]
    msvcrt.getwch = lambda: object()  # type: ignore[attr-defined]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", msvcrt)

    assert KeyboardInputController().poll_key() is None


def test_process_creation_flags_are_zero_on_posix() -> None:
    assert _child_process_creation_flags("linux") == 0


def test_process_creation_flags_use_windows_constant_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)

    assert _child_process_creation_flags("win32") == 512
