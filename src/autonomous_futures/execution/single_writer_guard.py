"""Fail-closed handoff gate for reusing the protected legacy Testnet API key."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
_UNSET = object()


class LegacyWriterHandoffGuard:
    """Require systemd to prove the legacy unit cannot restart or submit orders."""

    def __init__(
        self,
        service_name: str = "autonomous-futures-trader.service",
        *,
        command_runner: CommandRunner | None = None,
        systemctl_path: str | None | object = _UNSET,
        platform_name: str | None = None,
    ) -> None:
        self.service_name = service_name
        self.command_runner = command_runner or subprocess.run
        if systemctl_path is _UNSET:
            self.systemctl_path: str | None = shutil.which("systemctl")
        else:
            self.systemctl_path = systemctl_path if isinstance(systemctl_path, str) else None
        self.platform_name = sys.platform if platform_name is None else platform_name

    def assert_legacy_inactive(self) -> None:
        if self.platform_name != "linux" or self.systemctl_path is None:
            raise RuntimeError("Cannot verify the legacy writer state; same-key trading is blocked")

        try:
            result = self.command_runner(
                [
                    self.systemctl_path,
                    "show",
                    self.service_name,
                    "--no-page",
                    "--property=LoadState",
                    "--property=UnitFileState",
                    "--property=ActiveState",
                    "--property=SubState",
                    "--property=MainPID",
                    "--property=Restart",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(
                "Cannot verify the legacy writer state; same-key trading is blocked"
            ) from exc

        properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        disabled = properties.get("UnitFileState") in {"disabled", "masked"}
        inactive = (
            properties.get("LoadState") == "loaded"
            and properties.get("ActiveState") == "inactive"
            and properties.get("SubState") == "dead"
            and properties.get("MainPID") == "0"
            and properties.get("Restart") == "no"
        )
        if result.returncode != 0 or not disabled or not inactive:
            raise RuntimeError(
                "Legacy trader must be disabled, configured not to restart, and fully inactive "
                "before the existing Testnet key can be used"
            )
