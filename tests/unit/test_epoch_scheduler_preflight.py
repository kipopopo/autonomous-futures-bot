"""Scheduler pin faults block before outputs or launching a child."""

from pathlib import Path

import pytest

import scripts.run_autonomous_scheduler as scheduler
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.research.creator_epoch import (
    create_creator_epoch,
    create_creator_epoch_control,
)


@pytest.mark.parametrize(
    "fault", ["partial", "control", "provider", "base", "launch_control", "child_control"]
)
def test_scheduler_epoch_preflight_blocks_without_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    journal = tmp_path / "epoch.sqlite3"
    control = tmp_path / "control.sqlite3"
    pin = tmp_path / "pin.json"
    checkpoint = create_creator_epoch(journal, epoch_id="epoch-scheduler", policy_hash="c" * 64)
    create_creator_epoch_control(control, journal, checkpoint)
    pin.write_text(checkpoint.model_dump_json(), encoding="utf-8")
    output = tmp_path / "output"
    argv = [
        "--symbol",
        "BTCUSDT",
        "--output-dir",
        str(output),
        "--ledger-db",
        str(tmp_path / "ledger.sqlite3"),
        "--creator-epoch-journal",
        str(journal),
    ]
    if fault != "partial":
        argv += ["--creator-epoch-control", str(control), "--creator-epoch-checkpoint", str(pin)]
    if fault == "provider":
        argv += ["--provider", "google_ai_studio"]
    if fault == "base":
        argv += [
            "--research-candidate-artifact",
            "candidate.json",
            "--research-qualification-artifact",
            "qualification.json",
            "--bundle-hash",
            "a" * 64,
            "--dataset-registry-hash",
            "b" * 64,
        ]
    if fault == "control":
        control.unlink()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("child")
        raise AssertionError("preflight launched child")

    monkeypatch.setattr(scheduler.subprocess, "Popen", forbidden)
    args = scheduler.build_parser().parse_args(argv)
    if fault == "child_control":
        import scripts.run_autonomous_cycle as cycle_cli

        Path(args.ledger_db).touch()

        class RejectedChild:
            returncode = 3

            def __init__(self, command, **kwargs):
                calls.append("child")
                control.unlink()
                assert cycle_cli.main(command[2:]) == 3

            def poll(self):
                return self.returncode

            def communicate(self):
                return "", "epoch state rejected"

        monkeypatch.setattr(scheduler.subprocess, "Popen", RejectedChild)
        daemon = scheduler.AutonomousSchedulerDaemon(args)
        assert daemon._execute_cycle("manual_once") == 3
        assert calls == ["child"]
        assert not (output / "cycles").exists()
        return
    if fault == "launch_control":
        daemon = scheduler.AutonomousSchedulerDaemon(args)
        assert list(output.iterdir()) == []
        control.unlink()
        with pytest.raises(DomainViolation):
            daemon._execute_cycle("manual_once")
        assert list(output.iterdir()) == []
    else:
        with pytest.raises((DomainViolation, ValueError)):
            scheduler.AutonomousSchedulerDaemon(args)
        assert not output.exists()
    assert calls == []
