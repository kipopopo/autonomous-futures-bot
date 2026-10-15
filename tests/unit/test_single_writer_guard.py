import subprocess

import pytest

from autonomous_futures.execution.single_writer_guard import LegacyWriterHandoffGuard

READY = """LoadState=loaded
UnitFileState=disabled
ActiveState=inactive
SubState=dead
MainPID=0
Restart=no
"""


def _guard(stdout: str = READY, returncode: int = 0) -> LegacyWriterHandoffGuard:
    def runner(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    return LegacyWriterHandoffGuard(
        command_runner=runner,
        systemctl_path="/usr/bin/systemctl",
        platform_name="linux",
    )


def test_handoff_requires_disabled_nonrestarting_inactive_legacy_unit() -> None:
    _guard().assert_legacy_inactive()


@pytest.mark.parametrize(
    "replacement",
    [
        ("UnitFileState", "enabled"),
        ("ActiveState", "active"),
        ("SubState", "running"),
        ("MainPID", "87549"),
        ("Restart", "always"),
    ],
)
def test_handoff_rejects_any_legacy_writer_or_restart_path(
    replacement: tuple[str, str],
) -> None:
    key, value = replacement
    status = "\n".join(
        f"{line.split('=', 1)[0]}={value if line.startswith(key + '=') else line.split('=', 1)[1]}"
        for line in READY.splitlines()
    )

    with pytest.raises(RuntimeError, match="must be disabled"):
        _guard(status).assert_legacy_inactive()


def test_handoff_fails_closed_when_systemd_status_is_unavailable() -> None:
    with pytest.raises(RuntimeError, match="must be disabled"):
        _guard(READY, returncode=1).assert_legacy_inactive()


@pytest.mark.parametrize(
    ("platform_name", "systemctl_path"),
    [("win32", "/usr/bin/systemctl"), ("linux", None)],
)
def test_handoff_fails_closed_without_linux_systemd(
    platform_name: str,
    systemctl_path: str | None,
) -> None:
    guard = LegacyWriterHandoffGuard(
        platform_name=platform_name,
        systemctl_path=systemctl_path,
    )

    with pytest.raises(RuntimeError, match="Cannot verify"):
        guard.assert_legacy_inactive()


def test_handoff_falls_back_to_user_scope_when_system_scope_is_not_found() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "--user" in cmd:
            return subprocess.CompletedProcess(cmd, 0, READY, "")
        return subprocess.CompletedProcess(
            cmd,
            0,
            "LoadState=not-found\nUnitFileState=\nActiveState=inactive\nSubState=dead\nMainPID=0\nRestart=no\n",
            "",
        )

    guard = LegacyWriterHandoffGuard(
        command_runner=runner,
        systemctl_path="/usr/bin/systemctl",
        platform_name="linux",
    )
    status = guard.inspect_legacy_status()
    assert status["scope"] == "user"
    assert status["LoadState"] == "loaded"
    assert status["UnitFileState"] == "disabled"
    assert len(calls) == 2
    assert "--user" not in calls[0]
    assert "--user" in calls[1]
    guard.assert_legacy_inactive()
    assert len(calls) == 4
