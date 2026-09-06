"""Unit tests for deploy/autonomous-futures-paper-live.service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SERVICE_UNIT_PATH = (
    Path(__file__).resolve().parents[2] / "deploy" / "autonomous-futures-paper-live.service"
)


@dataclass(frozen=True)
class SystemdUnit:
    sections: dict[str, dict[str, list[str]]]

    def get_entries(self, section: str, directive: str) -> list[str]:
        return self.sections.get(section, {}).get(directive, [])

    def get_one(self, section: str, directive: str) -> str | None:
        entries = self.get_entries(section, directive)
        return entries[0] if entries else None

    def has_section(self, section: str) -> bool:
        return section in self.sections

    def has_directive(self, section: str, directive: str) -> bool:
        return bool(self.get_entries(section, directive))


def parse_systemd_unit(content: str) -> SystemdUnit:
    sections: dict[str, dict[str, list[str]]] = {}
    current_section: str | None = None
    for line_idx, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            if not current_section:
                raise ValueError(f"Empty section name at line {line_idx}")
            if current_section not in sections:
                sections[current_section] = {}
            continue
        if line.startswith("[") and not line.endswith("]"):
            raise ValueError(f"Unclosed section header at line {line_idx}: {line}")
        if "=" not in line:
            raise ValueError(f"Directive missing '=' delimiter at line {line_idx}: {line}")
        if current_section is None:
            raise ValueError(f"Directive before section header at line {line_idx}: {line}")
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        sections[current_section].setdefault(key, []).append(val)
    return SystemdUnit(sections=sections)


def test_live_paper_service_file_exists() -> None:
    assert SERVICE_UNIT_PATH.exists(), f"Missing {SERVICE_UNIT_PATH}"
    assert SERVICE_UNIT_PATH.is_file(), f"Not a regular file {SERVICE_UNIT_PATH}"
    assert SERVICE_UNIT_PATH.stat().st_size > 0


def test_live_paper_service_sections_present() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    assert unit.has_section("Unit")
    assert unit.has_section("Service")
    assert unit.has_section("Install")


def test_live_paper_service_unit_directives() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    desc = unit.get_one("Unit", "Description") or ""
    assert "paper" in desc.lower()
    assert unit.get_one("Unit", "After") == "network-online.target"
    assert unit.get_one("Unit", "Wants") == "network-online.target"
    assert "README.md" in (unit.get_one("Unit", "Documentation") or "")


def test_live_paper_service_user_and_group_non_root() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    user = unit.get_one("Service", "User")
    group = unit.get_one("Service", "Group")
    assert user == "afbot"
    assert group == "afbot"
    assert user not in ("root", "afbot-admin", "daemon")
    assert group not in ("root", "afbot-admin", "daemon")


def test_live_paper_service_sandboxing_directives() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    assert unit.get_one("Service", "ProtectSystem") == "strict"
    assert unit.get_one("Service", "ProtectHome") == "read-only"
    assert unit.get_one("Service", "PrivateTmp") == "yes"
    assert unit.get_one("Service", "NoNewPrivileges") == "yes"
    assert unit.get_one("Service", "ProtectKernelModules") == "yes"
    assert unit.get_one("Service", "ProtectKernelTunables") == "yes"
    assert unit.get_one("Service", "ProtectControlGroups") == "yes"
    assert unit.get_one("Service", "RestrictAddressFamilies") == "AF_INET AF_INET6 AF_UNIX"
    assert unit.get_one("Service", "PrivateNetwork") is None


def test_live_paper_service_storage_read_write_paths() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    rw_paths = unit.get_entries("Service", "ReadWritePaths")
    assert rw_paths, "ReadWritePaths directive missing from Service section"
    assert any("artifacts/paper_live" in p for p in rw_paths)


def test_live_paper_service_type_and_restart_policy() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    assert unit.get_one("Service", "Type") == "simple"
    assert unit.get_one("Service", "Restart") in ("always", "on-failure")
    assert unit.get_one("Service", "RestartSec") in ("5s", "10s", "5", "10")
    assert unit.get_one("Service", "TimeoutStopSec") in ("30s", "60s", "30", "60")


def test_live_paper_service_resource_envelope() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    quota = unit.get_one("Service", "CPUQuota")
    memory = unit.get_one("Service", "MemoryMax")
    assert quota is not None and quota.endswith("%")
    assert memory is not None and (memory.endswith("G") or memory.endswith("M"))


def test_live_paper_service_working_directory_and_environment() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    assert unit.get_one("Service", "WorkingDirectory") == "/opt/autonomous-futures-bot"
    env_vars = unit.get_entries("Service", "Environment")
    assert "PYTHONPATH=/opt/autonomous-futures-bot/src" in env_vars
    assert "PYTHONUNBUFFERED=1" in env_vars


def test_live_paper_service_exec_start_command() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    exec_start = unit.get_one("Service", "ExecStart") or ""
    assert exec_start.startswith("/opt/autonomous-futures-bot/.venv/bin/python")
    assert "scripts/run_phase_259_live_paper_daemon.py" in exec_start
    assert "--storage-dir /opt/autonomous-futures-bot/artifacts/paper_live" in exec_start
    assert "--starting-capital 100.00" in exec_start
    assert "--symbols BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT" in exec_start


def test_live_paper_service_absence_of_exchange_credentials() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    assert not unit.has_directive("Service", "LoadCredentialEncrypted")
    raw_content = content.lower()
    assert "api_key" not in raw_content
    assert "secret_key" not in raw_content


def test_live_paper_service_install_hook() -> None:
    content = SERVICE_UNIT_PATH.read_text(encoding="utf-8")
    unit = parse_systemd_unit(content)
    assert unit.get_one("Install", "WantedBy") == "multi-user.target"
