"""Unit tests for the staged qualified runtime systemd service and fail-closed preparation CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autonomous_futures.execution import single_writer_guard
from scripts import prepare_portfolio_cutover

REPO = Path(__file__).resolve().parents[2]


def test_qualified_runtime_systemd_unit_is_fail_closed_and_portfolio_wired() -> None:
    unit_path = REPO / "deploy" / "systemd" / "autonomous-futures-qualified-runtime.service"
    content = unit_path.read_text(encoding="utf-8")

    # Never use Conflicts= because systemd would stop the protected legacy daemon on start;
    # instead ExecStartPre must fail closed without touching the legacy daemon.
    assert "Conflicts=" not in content
    assert "WorkingDirectory=/opt/autonomous-futures-bot/releases/qualified-runtime" in content
    assert (
        "Environment=PYTHONPATH=/opt/autonomous-futures-bot/releases/qualified-runtime/src"
        in content
    )
    assert "EnvironmentFile=-/opt/autonomous-futures-bot/.env" in content
    assert "EnvironmentFile=/opt/autonomous-futures-bot/.env.qualified-runtime" in content

    exec_start_pre_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("ExecStartPre=")
    ]
    assert len(exec_start_pre_lines) == 2
    assert "scripts/prepare_portfolio_cutover.py" in exec_start_pre_lines[0]
    assert "--require-legacy-inactive" in exec_start_pre_lines[0]
    assert "--apply-leverage" in exec_start_pre_lines[0]
    assert "--bootstrap-daily-risk" in exec_start_pre_lines[0]

    assert "scripts/preflight_qualified_runtime.py" in exec_start_pre_lines[1]
    assert "--check-systemd" in exec_start_pre_lines[1]
    assert "--allow-blocked" not in exec_start_pre_lines[1]

    exec_start_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("ExecStart=")
    ]
    assert len(exec_start_lines) == 1
    assert "scripts/run_qualified_runtime.py" in exec_start_lines[0]
    assert (
        "--portfolio-id macro-scalper-uninspected-3sym-medium-frequency-v1"
        in exec_start_lines[0]
    )
    assert "NoNewPrivileges=true" in content
    assert "PrivateTmp=true" in content


def test_prepare_portfolio_cutover_require_legacy_inactive_fails_before_api_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail_legacy_check(self: object) -> None:
        raise RuntimeError(
            "Legacy trader must be disabled, configured not to restart, and fully inactive "
            "before the existing Testnet key can be used"
        )

    called_api = False

    async def _unexpected_prepare(**_: object) -> dict[str, object]:
        nonlocal called_api
        called_api = True
        return {}

    monkeypatch.setattr(
        single_writer_guard.LegacyWriterHandoffGuard,
        "assert_legacy_inactive",
        _fail_legacy_check,
    )
    monkeypatch.setattr(
        prepare_portfolio_cutover,
        "prepare_portfolio_cutover",
        _unexpected_prepare,
    )

    rc = prepare_portfolio_cutover.main(
        [
            "--storage-dir",
            str(tmp_path),
            "--require-legacy-inactive",
            "--apply-leverage",
            "--bootstrap-daily-risk",
        ]
    )
    assert rc == 1
    assert called_api is False
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "error_type": "RuntimeError",
        "preparation_failed": True,
        "reason": (
            "Legacy trader must be disabled, configured not to restart, and fully inactive "
            "before the existing Testnet key can be used"
        ),
    }
