"""Receipt integrity regressions; process stubs never call a provider or exchange."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

import scripts.run_autonomous_scheduler as scheduler_module
from autonomous_futures.pipeline.autonomous_cycle import _build_cycle_result
from scripts.run_autonomous_cycle import build_cycle_audit


@pytest.mark.parametrize(
    "receipt",
    [
        "missing",
        "malformed",
        "empty_result",
        "empty_audit",
        "foreign_cycle",
        "foreign_symbol",
        "wrong_hash",
        "failed",
        "conflicting_audit",
        "valid_result",
        "valid_pair",
        "valid_skip",
    ],
)
def test_scheduler_requires_bound_success_receipt(tmp_path, monkeypatch, receipt):
    candidate = tmp_path / "candidate.json"
    candidate.write_text("{}", encoding="utf-8")
    args = scheduler_module.build_parser().parse_args(
        [
            "--symbol",
            "BTCUSDT",
            "--provider",
            "demo",
            "--output-dir",
            str(tmp_path / "s"),
            "--ledger-db",
            str(tmp_path / "missing.sqlite3"),
            "--candidate-id",
            "cand-receipt-test",
            "--candidate-path",
            str(candidate),
            "--parquet-path",
            str(tmp_path / "missing.parquet"),
        ]
    )

    class ProcessStub:
        returncode = 0

        def __init__(self, command, **kwargs):
            root = Path(command[command.index("--output-dir") + 1])
            cycle_id = command[command.index("--cycle-id") + 1]
            if receipt == "missing":
                return
            if receipt in {"malformed", "empty_result", "empty_audit"}:
                filename = (
                    "cycle-audit.json"
                    if receipt == "empty_audit"
                    else "autonomous-cycle-result.json"
                )
                (root / filename).write_text(
                    "invalid JSON" if receipt == "malformed" else "{}", encoding="utf-8"
                )
                return
            result = _build_cycle_result(
                cycle_id="cycle-foreign" if receipt == "foreign_cycle" else cycle_id,
                symbol="ETHUSDT" if receipt == "foreign_symbol" else "BTCUSDT",
                cycle_status="failed" if receipt == "failed" else "completed_unadmitted",
                active_candidate_id="cand-receipt-test",
                completed_at=datetime.now(UTC),
            )
            data = result.model_dump(mode="json")
            if receipt == "wrong_hash":
                data["cycle_hash"] = "0" * 64
            if receipt != "valid_skip":
                (root / "autonomous-cycle-result.json").write_text(
                    json.dumps(data), encoding="utf-8"
                )
            if receipt in {"valid_pair", "conflicting_audit", "valid_skip"}:
                audit = build_cycle_audit(result, args)
                if receipt == "conflicting_audit":
                    audit["cycle_hash"] = "0" * 64
                if receipt == "valid_skip":
                    audit["cycle_status"] = "skipped_no_breaches"
                    audit["lineage"]["stop_reasons"] = ["skipped_no_breaches"]
                raw = json.dumps(
                    {k: v for k, v in audit.items() if k != "audit_hash"},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                audit["audit_hash"] = sha256(raw).hexdigest()
                (root / "cycle-audit.json").write_text(json.dumps(audit), encoding="utf-8")

        def poll(self):
            return 0

        def communicate(self):
            return "", ""

    monkeypatch.setattr(scheduler_module.subprocess, "Popen", ProcessStub)
    scheduler = scheduler_module.AutonomousSchedulerDaemon(args)
    exit_code = scheduler._execute_cycle("manual_once")
    valid = receipt in {"valid_result", "valid_pair", "valid_skip"}
    assert (exit_code == 0) is valid
    assert scheduler.consecutive_failures == (0 if valid else 1)
    assert scheduler.admitted_candidates_count == 0
    assert scheduler.last_cycle_result is not None
    if not valid:
        assert scheduler.last_cycle_result.status == "failed"
