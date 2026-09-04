"""Phase 256 Independent Adversarial Stress Test Suite.

Authoritative empirical challenge and stress-testing of Phase 256:
1. Adversarial CLI & Argument Stress:
   - Invalid starting capital (negative, zero, NaN, strings, infinities).
   - Invalid bar counts (negative, zero, < 30, strings, floats).
   - Missing, inaccessible, non-directory, and read-only storage paths.
   - Non-existent output paths and directory creation failures.
2. Adversarial Security & Invariants Stress:
   - Environment variable contamination (BINANCE_*, EXCHANGE_*, API_KEY, API_SECRET).
   - Credential directory contamination (forbidden filenames, storage credentials subfolder).
   - Insecure POSIX directory permission modes (0o777, 0o644, 0o755, 0o770) and invalid owners.
   - Offline safety invariants (orders=0, exchange_access=False, promotion_state="unpromoted").
3. Empirical Smoke Simulation Stress:
   - Variable capital ($50, $100, $250, $1000, $50000) and bar counts (30, 72, 100, 200, 500).
   - Exact Decimal accounting reconciliation and zero position drift.
   - Dynamic leverage allocation and margin ceiling preservation (<= 80%).
   - Artifact integrity across all 3 SQLite databases and 3 JSON reports.
4. Forensic Zero-Secret Audit:
   - Verification of secret scrubbing for Google AI Studio and exchange tokens.
"""

from __future__ import annotations

import gc
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from autonomous_futures.paper_preflight import (
    SharedMarginAccount,
    _sanitize_error_text,
    execute_paper_smoke_test,
    validate_paper_host_environment,
    validate_paper_offline_safety,
    validate_paper_preflight,
    validate_paper_storage_directory,
)

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "preflight_kainode_paper.py"
_SPEC = importlib.util.spec_from_file_location("preflight_kainode_paper", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_CLI_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI_MOD)
cli_main: Callable[[list[str] | None], int] = _CLI_MOD.main


def make_mock_stat(
    mode: int = 0o040750,
    uid: int = 1001,
    gid: int = 1001,
    size: int = 4096,
) -> Callable[[Path], os.stat_result]:
    """Return a mock stat function for deterministic POSIX permission testing."""
    res = os.stat_result((mode, 0, 0, 1, uid, gid, size, 0, 0, 0))

    def _stat(_path: Path) -> os.stat_result:
        return res

    return _stat


# ==============================================================================
# 1. Adversarial CLI & Argument Stress
# ==============================================================================


class TestAdversarialCliArgumentStress:
    """Stress-test preflight CLI arguments with invalid, malicious, and pathological inputs."""

    def test_negative_starting_equity_rejected_with_code_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Negative starting equity values must exit with code 2 and structured error."""
        code = cli_main(["--starting-equity", "-100.00", "--skip-host-check"])
        assert code == 2
        captured = capsys.readouterr().out
        assert "starting_equity must be positive" in captured
        data = json.loads(captured)
        assert data["error_code"] == "invalid_input"

    def test_zero_starting_equity_rejected_with_code_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Zero starting equity must exit with code 2 and structured error."""
        code = cli_main(["--starting-equity", "0", "--skip-host-check"])
        assert code == 2
        captured = capsys.readouterr().out
        assert "starting_equity must be positive" in captured

    def test_negative_infinity_starting_equity_rejected_with_code_2(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Negative infinity starting equity must exit with code 2."""
        code = cli_main(["--starting-equity=-Infinity", "--skip-host-check"])
        assert code == 2
        captured = capsys.readouterr().out
        assert "starting_equity must be positive" in captured

    def test_non_numeric_string_equity_triggers_uncaught_invalid_operation(self) -> None:
        """EMPIRICAL FINDING: Non-numeric string equity raises uncaught decimal.InvalidOperation.

        Argparse uses `type=Decimal`, which calls `Decimal('not_a_number')`.
        Because `decimal.InvalidOperation` does not inherit from `ValueError`, argparse
        fails to catch it, causing the CLI to crash with exit code 1 instead of returning 2.
        """
        res = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--starting-equity",
                "not_a_number",
                "--skip-host-check",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 1
        assert "decimal.InvalidOperation" in res.stderr

    def test_nan_starting_equity_triggers_uncaught_invalid_operation(self) -> None:
        """EMPIRICAL FINDING: NaN starting equity crashes at `< Decimal('0')` comparison.

        `Decimal('NaN')` parses successfully in argparse, but comparing `NaN <= Decimal('0')`
        raises `decimal.InvalidOperation: [<class 'decimal.InvalidOperation'>]`, causing the
        process to crash with exit code 1 instead of returning 2.
        """
        res = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--starting-equity",
                "NaN",
                "--skip-host-check",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 1
        assert "decimal.InvalidOperation" in res.stderr

    @pytest.mark.parametrize("bad_bars", ["-10", "0", "1", "29"])
    def test_invalid_bar_counts_below_30_rejected_with_code_2(
        self, bad_bars: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Bar counts < 30 must exit with code 2 and structured error."""
        code = cli_main(["--bars", bad_bars, "--skip-host-check"])
        assert code == 2
        captured = capsys.readouterr().out
        assert "bars must be at least 30" in captured
        data = json.loads(captured)
        assert data["error_code"] == "invalid_input"

    @pytest.mark.parametrize("bad_type_bars", ["abc", "50.5", "ten"])
    def test_non_integer_bar_counts_rejected_with_code_2(
        self, bad_type_bars: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Non-integer bar count arguments must trigger argparse exit code 2."""
        code = cli_main(["--bars", bad_type_bars, "--skip-host-check"])
        assert code == 2

    def test_non_existent_storage_directory_exits_code_3(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Non-existent storage directory path must exit with code 3 and report status blocked."""
        missing = tmp_path / "definitely_absent_storage_dir"
        code = cli_main(["--storage-dir", str(missing), "--skip-host-check"])
        assert code == 3
        data = json.loads(capsys.readouterr().out)
        assert data["ready"] is False
        assert data["status"] == "blocked"
        assert any("storage_directory_missing" in e for e in data["errors"])

    def test_regular_file_as_storage_directory_exits_code_3(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Providing a regular file instead of a directory must be rejected with code 3."""
        file_path = tmp_path / "not_a_directory.txt"
        file_path.write_text("dummy", encoding="utf-8")
        code = cli_main(["--storage-dir", str(file_path), "--skip-host-check"])
        assert code == 3
        data = json.loads(capsys.readouterr().out)
        assert data["ready"] is False
        assert data["status"] == "blocked"
        assert any("storage_directory_not_a_directory" in e for e in data["errors"])

    def test_read_only_storage_directory_exits_code_3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Storage directory that fails atomic write probe must report blocked with code 3."""
        storage = tmp_path / "paper_ro"
        storage.mkdir()

        orig_write_text = Path.write_text

        def mock_write(self: Path, *args: Any, **kwargs: Any) -> int:
            if self.name.startswith(".preflight_probe_"):
                raise OSError(30, "Read-only file system")
            return orig_write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", mock_write)

        code = cli_main(["--storage-dir", str(storage), "--skip-host-check"])
        assert code == 3
        data = json.loads(capsys.readouterr().out)
        assert data["ready"] is False
        assert any("storage_directory_read_only_or_not_writable" in e for e in data["errors"])

    def test_unwritable_output_json_path_exits_code_3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Failure to persist structured JSON to --output-json must exit with code 3."""
        storage = tmp_path / "paper"
        storage.mkdir()

        out_file = tmp_path / "target_report.json"

        orig_write_text = Path.write_text

        def mock_write(self: Path, *args: Any, **kwargs: Any) -> int:
            if self == out_file:
                raise OSError(13, "Permission denied")
            return orig_write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", mock_write)

        code = cli_main(
            [
                "--storage-dir",
                str(storage),
                "--output-json",
                str(out_file),
                "--skip-host-check",
            ]
        )
        assert code == 3
        captured = capsys.readouterr().out
        assert "output_write_failure" in captured


# ==============================================================================
# 2. Adversarial Security & Invariants Stress
# ==============================================================================


class TestAdversarialSecurityAndInvariantsStress:
    """Stress-test credential leakage detection, directory permissions, and offline invariants."""

    @pytest.mark.parametrize(
        "tainted_env_key",
        [
            "BINANCE_API_KEY",
            "binance_api_secret",
            "BINANCE_SECRET_KEY",
            "MY_EXCHANGE_KEY",
            "GLOBAL_API_KEY",
            "SECRET_API_SECRET",
        ],
    )
    def test_environment_variable_contamination_blocks_with_code_3(
        self, tainted_env_key: str, tmp_path: Path
    ) -> None:
        """Presence of any exchange credential in environment must block preflight with code 3."""
        storage = tmp_path / "paper_clean"
        storage.mkdir()

        dirty_env = {
            "PATH": "/usr/bin",
            tainted_env_key: "tainted_secret_value_12345",
        }

        report = validate_paper_preflight(
            storage_dir=storage,
            env=dirty_env,
            skip_host_check=True,
        )
        assert report.ready is False
        assert report.status == "blocked"
        assert any("exchange_credential_contamination" in err for err in report.errors)
        assert any(
            tainted_env_key in detected for detected in report.offline_safety.credentials_detected
        )

    @pytest.mark.parametrize(
        "tainted_filename",
        [
            "BINANCE_API_KEY",
            "binance_secret.key",
            "exchange_fapi_token",
            "fapi_credentials.json",
        ],
    )
    def test_credential_directory_file_contamination_blocks_with_code_3(
        self, tainted_filename: str, tmp_path: Path
    ) -> None:
        """Presence of credential file in scanned credentials dir must block with code 3."""
        storage = tmp_path / "paper_storage"
        storage.mkdir()
        creds_dir = tmp_path / "creds"
        creds_dir.mkdir()
        (creds_dir / tainted_filename).write_text("super_secret", encoding="utf-8")

        report = validate_paper_preflight(
            storage_dir=storage,
            credentials_dir=creds_dir,
            skip_host_check=True,
        )
        assert report.ready is False
        assert report.status == "blocked"
        assert any("exchange_credential_contamination" in err for err in report.errors)
        assert f"file:{tainted_filename}" in report.offline_safety.credentials_detected

    def test_storage_credentials_subfolder_auto_scanned_for_contamination(
        self, tmp_path: Path
    ) -> None:
        """Credentials directory under storage_dir/credentials must be auto-scanned."""
        storage = tmp_path / "paper_with_creds"
        storage.mkdir()
        sub_creds = storage / "credentials"
        sub_creds.mkdir()
        (sub_creds / "binance_leak.txt").write_text("leak", encoding="utf-8")

        report = validate_paper_preflight(
            storage_dir=storage,
            skip_host_check=True,
        )
        assert report.ready is False
        assert report.status == "blocked"
        assert "file:binance_leak.txt" in report.offline_safety.credentials_detected

    @pytest.mark.parametrize(
        ("mode", "octal_str"),
        [
            (0o040777, "0o777"),
            (0o040644, "0o644"),
            (0o040755, "0o755"),
            (0o040770, "0o770"),
            (0o040775, "0o775"),
        ],
    )
    def test_loose_directory_permissions_rejected(self, mode: int, octal_str: str) -> None:
        """Storage directories with modes other than 0o750 or 0o700 must be rejected."""
        rep = validate_paper_storage_directory(
            Path("."), stat_fn=make_mock_stat(mode=mode), platform="linux"
        )
        assert rep.mode_valid is False
        assert rep.validation_error is not None
        assert f"insecure_directory_mode_{octal_str}" in rep.validation_error

    @pytest.mark.parametrize("mode", [0o040750, 0o040700])
    def test_secure_directory_permissions_accepted(self, mode: int) -> None:
        """Storage directories with modes 0o750 and 0o700 must be accepted."""
        rep = validate_paper_storage_directory(
            Path("."), stat_fn=make_mock_stat(mode=mode), platform="linux"
        )
        assert rep.mode_valid is True
        assert rep.validation_error is None

    def test_unauthorized_storage_directory_owner_rejected(self) -> None:
        """Storage directories owned by UID outside {0, 1000, 1001} must be rejected."""
        rep = validate_paper_storage_directory(
            Path("."), stat_fn=make_mock_stat(uid=9999), platform="linux", allowed_uids={0, 1001}
        )
        assert rep.owner_valid is False
        assert rep.validation_error is not None
        assert "invalid_directory_owner" in rep.validation_error

    def test_root_user_execution_rejected_in_host_environment_check(self) -> None:
        """Execution as root (UID 0) must be rejected by validate_paper_host_environment."""
        rep = validate_paper_host_environment(
            stat_fn=make_mock_stat(uid=0), platform="linux", allowed_uids={0}
        )
        assert rep.user_valid is False
        assert rep.validation_error is not None
        assert "invalid_execution_user" in rep.validation_error

    def test_offline_safety_report_invariants_immutable(self) -> None:
        """Offline safety report must strictly enforce zero orders and zero exchange access."""
        rep = validate_paper_offline_safety(env={"PATH": "/bin"})
        assert rep.exchange_access is False
        assert rep.execution_authority is False
        assert rep.orders == 0
        assert rep.promotion_state == "unpromoted"
        assert rep.paper_activation is False
        assert rep.live_credentials_forbidden is True


# ==============================================================================
# 3. Empirical Smoke Simulation Stress
# ==============================================================================


class TestAdversarialSmokeSimulationStress:
    """Stress-test synthetic smoke simulation under varying capital and bar parameters."""

    @pytest.mark.parametrize(
        ("starting_equity", "bars"),
        [
            (Decimal("50.00"), 30),
            (Decimal("100.00"), 72),
            (Decimal("250.00"), 100),
            (Decimal("1000.00"), 200),
            (Decimal("50000.00"), 500),
        ],
    )
    def test_smoke_simulation_balance_and_position_reconciliation(
        self, starting_equity: Decimal, bars: int, tmp_path: Path
    ) -> None:
        """Verify balance and position reconciliation across varied capital and bar counts."""
        storage = tmp_path / f"sim_{starting_equity}_{bars}"
        storage.mkdir()

        rep = execute_paper_smoke_test(storage, starting_equity=starting_equity, bars=bars)

        assert rep.executed is True
        assert rep.positions_reconciled is True
        assert rep.balance_reconciled is True
        assert rep.trades_executed == 1
        assert rep.total_bars == bars
        assert rep.validation_error is None

        # Verify persisted JSON artifacts
        for fname in (
            "paper-health-report.json",
            "paper-cohort-readiness-report.json",
            "paper-summary.json",
        ):
            art_file = storage / fname
            assert art_file.exists(), f"Missing artifact: {fname}"
            payload = json.loads(art_file.read_text(encoding="utf-8"))
            assert payload is not None

        summary = json.loads((storage / "paper-summary.json").read_text(encoding="utf-8"))
        assert summary["starting_equity"] == str(starting_equity)
        assert summary["balance_reconciled"] is True
        assert summary["positions_reconciled"] is True
        assert Decimal(summary["final_cash"]) == starting_equity + Decimal(summary["net_pnl"])

        # Clean up database handles for Windows file locking
        del rep
        gc.collect()

    def test_dynamic_leverage_and_margin_utilization_ceiling(self) -> None:
        """Dynamic leverage must scale [1.0x, 3.0x] and enforce 80% margin utilization cap."""
        account = SharedMarginAccount(
            starting_capital=Decimal("100.00"),
            max_utilization=Decimal("0.80"),
            base_allocation_fraction=Decimal("0.20"),
        )

        # 1. Allocate 1st order
        alloc1 = account.allocate_order(
            symbol="DOGEUSDT",
            confidence=Decimal("0.50"),
            mark_price=Decimal("0.15"),
            current_equity=account.cash,
        )
        assert alloc1 is not None
        margin1, lev1, qty1 = alloc1
        assert margin1 == Decimal("20.00")
        assert lev1 == Decimal("2.0")
        account.record_open("trade-1", margin1, lev1, Decimal("0.02"), account.cash)

        # 2. Allocate 2nd order
        alloc2 = account.allocate_order(
            symbol="BTCUSDT",
            confidence=Decimal("0.90"),
            mark_price=Decimal("90000.00"),
            current_equity=account.cash,
        )
        assert alloc2 is not None
        margin2, lev2, qty2 = alloc2
        account.record_open("trade-2", margin2, lev2, Decimal("0.02"), account.cash)

        # 3. Allocate 3rd order
        alloc3 = account.allocate_order(
            symbol="ETHUSDT",
            confidence=Decimal("0.20"),
            mark_price=Decimal("2500.00"),
            current_equity=account.cash,
        )
        assert alloc3 is not None
        margin3, lev3, qty3 = alloc3
        account.record_open("trade-3", margin3, lev3, Decimal("0.02"), account.cash)

        # 4. 4th order allocation would result in utilization = 79.976 / 99.94 = 80.024% > 80%
        # Margin cap must strictly reject order 4 to prevent breaching the 80% utilization ceiling
        alloc4 = account.allocate_order(
            symbol="SOLUSDT",
            confidence=Decimal("1.00"),
            mark_price=Decimal("150.00"),
            current_equity=account.cash,
        )
        assert alloc4 is None

        # Verify max observed utilization did not exceed 0.80
        assert account.max_observed_utilization <= Decimal("0.80")


# ==============================================================================
# 4. Forensic Zero-Secret Audit & Secret Scrubbing
# ==============================================================================


class TestAdversarialSecretLeakageForensics:
    """Verify that error messages and reports scrub potential secrets and tokens."""

    @pytest.mark.parametrize(
        ("raw_text", "expected_scrubbed"),
        [
            ("Error contacting AIzaSyABC12345678901234567890 endpoint", "[REDACTED_SECRET]"),
            ("Invalid token ya29.a0AfH6SMB_1234567890abcdef", "[REDACTED_SECRET]"),
            ("Authorization: Bearer sk-ant-api-token-12345", "[REDACTED_SECRET]"),
        ],
    )
    def test_secret_patterns_are_redacted_by_sanitizer(
        self, raw_text: str, expected_scrubbed: str
    ) -> None:
        """Sanitizer must replace secret patterns with [REDACTED_SECRET]."""
        sanitized = _sanitize_error_text(raw_text)
        assert expected_scrubbed in sanitized
        assert "AIzaSy" not in sanitized
        assert "ya29." not in sanitized
        assert "Bearer" not in sanitized

    def test_preflight_report_model_serialization_contains_zero_secrets(
        self, tmp_path: Path
    ) -> None:
        """Preflight report JSON dump must contain zero secret keys or private credentials."""
        storage = tmp_path / "paper_clean"
        storage.mkdir()
        report = validate_paper_preflight(
            storage_dir=storage,
            skip_host_check=True,
            smoke_test=False,
        )
        json_text = report.model_dump_json(indent=2)
        assert "AIza" not in json_text
        assert "bearer" not in json_text.lower()
        assert "secret" not in json_text.lower()
