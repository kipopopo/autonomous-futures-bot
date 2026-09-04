"""Comprehensive unit tests for Kainode paper daemon preflight logic and CLI."""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from autonomous_futures.paper_preflight import (
    PaperPreflightReport,
    calculate_dynamic_leverage,
    generate_deterministic_5m_bars,
    validate_paper_host_environment,
    validate_paper_offline_safety,
    validate_paper_preflight,
    validate_paper_storage_directory,
)


def _load_cli_main() -> Callable[[list[str] | None], int]:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "preflight_kainode_paper.py"
    spec = importlib.util.spec_from_file_location("preflight_kainode_paper", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main  # type: ignore[no-any-return]


cli_main = _load_cli_main()


def make_mock_stat(
    mode: int = 0o040750,
    uid: int = 1001,
    gid: int = 1001,
    size: int = 4096,
) -> Callable[[Path], os.stat_result]:
    """Return a mock stat function for deterministic permission testing."""
    res = os.stat_result((mode, 0, 0, 1, uid, gid, size, 0, 0, 0))

    def _stat(_path: Path) -> os.stat_result:
        return res

    return _stat


def test_preflight_valid_environment_and_smoke_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    storage_dir = tmp_path / "artifacts" / "paper"
    storage_dir.mkdir(parents=True)
    storage_dir.chmod(0o750)
    stat_fn = make_mock_stat(mode=0o040750, uid=1001)

    clean_env: dict[str, str] = {"PATH": "/usr/bin"}

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        starting_equity=Decimal("100.00"),
        bars=200,
        smoke_test=True,
        stat_fn=stat_fn,
        platform="linux",
        env=clean_env,
        allowed_uids={1001},
        skip_host_check=True,
    )

    assert report.ready is True
    assert report.status == "ready_for_paper_daemon"
    assert report.errors == ()
    assert report.offline_safety.exchange_access is False
    assert report.offline_safety.orders == 0
    assert report.smoke_test.executed is True
    assert report.smoke_test.total_bars == 200
    assert report.smoke_test.trades_executed == 1
    assert report.smoke_test.positions_reconciled is True
    assert report.smoke_test.balance_reconciled is True

    # Verify SQLite database files created
    assert (storage_dir / "paper-ledger.sqlite3").exists()
    assert (storage_dir / "paper-lifecycle.sqlite3").exists()
    assert (storage_dir / "paper-observations.sqlite3").exists()

    # Verify JSON telemetry reports created
    assert (storage_dir / "paper-health-report.json").exists()
    assert (storage_dir / "paper-cohort-readiness-report.json").exists()
    assert (storage_dir / "paper-summary.json").exists()

    # Verify CLI runner execution
    code = cli_main(
        [
            "--storage-dir",
            str(storage_dir),
            "--starting-equity",
            "100.00",
            "--bars",
            "200",
            "--smoke-test",
            "--skip-host-check",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "ready_for_paper_daemon"
    assert data["ready"] is True
    assert data["smoke_test"]["executed"] is True
    assert data["smoke_test"]["positions_reconciled"] is True
    assert data["smoke_test"]["balance_reconciled"] is True


def test_preflight_missing_storage_directory(tmp_path: Path) -> None:
    missing_dir = tmp_path / "non_existent_paper_dir"

    report = validate_paper_preflight(
        storage_dir=missing_dir,
        skip_host_check=True,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("storage_directory_missing" in err for err in report.errors)

    code = cli_main(
        [
            "--storage-dir",
            str(missing_dir),
            "--skip-host-check",
        ]
    )
    assert code == 3


def test_preflight_storage_not_a_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "not_a_dir"
    file_path.write_text("just_a_file", encoding="utf-8")

    report = validate_paper_preflight(
        storage_dir=file_path,
        skip_host_check=True,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("storage_directory_not_a_directory" in err for err in report.errors)

    code = cli_main(
        [
            "--storage-dir",
            str(file_path),
            "--skip-host-check",
        ]
    )
    assert code == 3


def test_preflight_loose_permissions_mode_644(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_644"
    storage_dir.mkdir()
    stat_fn = make_mock_stat(mode=0o040644, uid=1001)

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        stat_fn=stat_fn,
        platform="linux",
        skip_host_check=True,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("insecure_directory_mode" in err for err in report.errors)


def test_preflight_loose_permissions_mode_777(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_777"
    storage_dir.mkdir()
    stat_fn = make_mock_stat(mode=0o040777, uid=1001)

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        stat_fn=stat_fn,
        platform="linux",
        skip_host_check=True,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("insecure_directory_mode" in err for err in report.errors)


def test_preflight_invalid_directory_owner(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_bad_owner"
    storage_dir.mkdir()
    # UID 9999 is neither root (0) nor afbot (1000/1001)
    stat_fn = make_mock_stat(mode=0o040750, uid=9999)

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        stat_fn=stat_fn,
        platform="linux",
        skip_host_check=True,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("invalid_directory_owner" in err for err in report.errors)


def test_preflight_non_writable_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage_dir = tmp_path / "paper_ro"
    storage_dir.mkdir()
    storage_dir.chmod(0o750)

    original_write_text = Path.write_text

    def mock_write_text(self: Path, *args: object, **kwargs: object) -> int:
        if self.name.startswith(".preflight_probe_"):
            raise PermissionError("Read-only file system")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", mock_write_text)

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        skip_host_check=True,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("storage_directory_read_only_or_not_writable" in err for err in report.errors)


def test_preflight_credential_contamination_env(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_clean"
    storage_dir.mkdir()
    storage_dir.chmod(0o750)

    dirty_env = {
        "PATH": "/usr/bin",
        "BINANCE_API_KEY": "fake_live_key_should_not_exist",
    }

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        env=dirty_env,
        skip_host_check=True,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("exchange_credential_contamination" in err for err in report.errors)
    assert "env:BINANCE_API_KEY" in report.offline_safety.credentials_detected


def test_preflight_credential_contamination_file(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_clean"
    storage_dir.mkdir()
    storage_dir.chmod(0o750)

    creds_dir = tmp_path / "creds"
    creds_dir.mkdir()
    (creds_dir / "binance_live_api_key").write_text("secret_data", encoding="utf-8")

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        credentials_dir=creds_dir,
        skip_host_check=True,
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("exchange_credential_contamination" in err for err in report.errors)
    assert "file:binance_live_api_key" in report.offline_safety.credentials_detected


def test_preflight_offline_safety_invariants() -> None:
    safety = validate_paper_offline_safety(env={"PATH": "/usr/bin"})
    assert safety.exchange_access is False
    assert safety.execution_authority is False
    assert safety.orders == 0
    assert safety.promotion_state == "unpromoted"
    assert safety.paper_activation is False
    assert safety.live_credentials_forbidden is True
    assert safety.credentials_detected == ()
    assert safety.validation_error is None


def test_preflight_host_environment_checks() -> None:
    # 1. Clean Linux host check
    stat_fn = make_mock_stat(uid=1001)
    rep = validate_paper_host_environment(stat_fn=stat_fn, platform="linux", allowed_uids={1001})
    assert rep.platform == "linux"
    assert rep.python_version_valid is True
    assert rep.user_valid is True
    assert rep.validation_error is None

    # 2. Non-linux platform without skip_host_check fails
    rep_non_linux = validate_paper_host_environment(
        stat_fn=stat_fn, platform="darwin", allowed_uids={1001}
    )
    assert rep_non_linux.validation_error is not None
    assert "unsupported_platform_darwin_must_be_linux" in rep_non_linux.validation_error

    # 3. Root execution (uid 0) fails user validity
    stat_root = make_mock_stat(uid=0)
    rep_root = validate_paper_host_environment(
        stat_fn=stat_root, platform="linux", allowed_uids={0}
    )
    assert rep_root.user_valid is False
    assert rep_root.validation_error is not None
    assert "invalid_execution_user" in rep_root.validation_error


def test_preflight_smoke_test_custom_bars_and_capital(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_72"
    storage_dir.mkdir()
    storage_dir.chmod(0o750)

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        starting_equity=Decimal("500.00"),
        bars=72,
        smoke_test=True,
        skip_host_check=True,
    )
    assert report.ready is True
    assert report.smoke_test.total_bars == 72
    assert report.smoke_test.trades_executed == 1
    assert report.smoke_test.positions_reconciled is True
    assert report.smoke_test.balance_reconciled is True


def test_preflight_no_smoke_test_flag(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_no_smoke"
    storage_dir.mkdir()
    storage_dir.chmod(0o750)

    report = validate_paper_preflight(
        storage_dir=storage_dir,
        smoke_test=False,
        skip_host_check=True,
    )
    assert report.ready is True
    assert report.smoke_test.executed is False
    assert report.smoke_test.trades_executed == 0

    code = cli_main(
        [
            "--storage-dir",
            str(storage_dir),
            "--no-smoke-test",
            "--skip-host-check",
        ]
    )
    assert code == 0


def test_preflight_cli_invalid_arguments_exit_code_2(capsys: pytest.CaptureFixture[str]) -> None:
    # 1. Invalid option
    assert cli_main(["--non-existent-option"]) == 2

    # 2. Negative starting equity
    assert cli_main(["--starting-equity", "-100.00"]) == 2
    err_out = capsys.readouterr().out
    assert "starting_equity must be positive" in err_out

    # 3. Bar count below 30
    assert cli_main(["--bars", "20"]) == 2
    err_out = capsys.readouterr().out
    assert "bars must be at least 30" in err_out


def test_preflight_cli_output_json(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_cli"
    storage_dir.mkdir()
    storage_dir.chmod(0o750)
    out_json = tmp_path / "telemetry" / "preflight.json"

    code = cli_main(
        [
            "--storage-dir",
            str(storage_dir),
            "--output-json",
            str(out_json),
            "--skip-host-check",
        ]
    )
    assert code == 0
    assert out_json.exists()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["status"] == "ready_for_paper_daemon"
    assert data["ready"] is True


def test_preflight_report_model_consistency(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_dummy"
    storage_dir.mkdir()
    storage_dir.chmod(0o750)
    report = validate_paper_preflight(storage_dir=storage_dir, skip_host_check=True)

    # ready report cannot have blocked status
    with pytest.raises(ValueError, match="ready report must have status 'ready_for_paper_daemon'"):
        PaperPreflightReport(
            ready=True,
            status="blocked",
            host_environment=report.host_environment,
            storage_directory=report.storage_directory,
            offline_safety=report.offline_safety,
            smoke_test=report.smoke_test,
        )

    # ready report cannot have errors
    with pytest.raises(ValueError, match="ready report cannot have errors"):
        PaperPreflightReport(
            ready=True,
            status="ready_for_paper_daemon",
            errors=("some_error",),
            host_environment=report.host_environment,
            storage_directory=report.storage_directory,
            offline_safety=report.offline_safety,
            smoke_test=report.smoke_test,
        )

    # unready report cannot have ready status
    with pytest.raises(ValueError, match="unready report must have status 'blocked'"):
        PaperPreflightReport(
            ready=False,
            status="ready_for_paper_daemon",
            errors=("some_error",),
            host_environment=report.host_environment,
            storage_directory=report.storage_directory,
            offline_safety=report.offline_safety,
            smoke_test=report.smoke_test,
        )


def test_deterministic_5m_bars_generation() -> None:
    df = generate_deterministic_5m_bars(total_bars=100)
    assert len(df) == 100
    assert set(df.columns) >= {"timestamp", "open", "high", "low", "close"}
    # Verify monotonic 5m delta
    diffs = df["timestamp"].diff().dropna()
    assert all(d.total_seconds() == 300 for d in diffs)

    with pytest.raises(ValueError, match="total_bars must be at least 30"):
        generate_deterministic_5m_bars(total_bars=20)


def test_dynamic_leverage_scaling() -> None:
    assert calculate_dynamic_leverage(Decimal("0.0")) == Decimal("1.0")
    assert calculate_dynamic_leverage(Decimal("0.5")) == Decimal("2.0")
    assert calculate_dynamic_leverage(Decimal("1.0")) == Decimal("3.0")
    assert calculate_dynamic_leverage(Decimal("1.5")) == Decimal("3.0")
    assert calculate_dynamic_leverage(Decimal("-0.5")) == Decimal("1.0")


def test_validate_paper_storage_directory_direct(tmp_path: Path) -> None:
    storage_dir = tmp_path / "paper_direct"
    storage_dir.mkdir()
    stat_fn = make_mock_stat(mode=0o040750, uid=1001)
    rep = validate_paper_storage_directory(
        storage_dir, stat_fn=stat_fn, platform="linux", allowed_uids={1001}
    )
    assert rep.exists is True
    assert rep.is_directory is True
    assert rep.mode_valid is True
    assert rep.owner_valid is True
    assert rep.read_write_capable is True
    assert rep.validation_error is None
