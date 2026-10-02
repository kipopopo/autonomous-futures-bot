"""CLI authority faults stop before credentials, transport or outputs."""

from pathlib import Path

import pytest

import scripts.run_autonomous_cycle as cli
from autonomous_futures.research.creator_epoch import (
    create_creator_epoch,
    create_creator_epoch_control,
)


@pytest.mark.parametrize("fault", ["provider", "checkpoint", "policy", "journal", "ledger"])
def test_epoch_cli_preflight_has_no_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    journal = tmp_path / "journal.sqlite3"
    control = tmp_path / "control.sqlite3"
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = create_creator_epoch(journal, epoch_id="epoch-cli-guard", policy_hash="c" * 64)
    create_creator_epoch_control(control, journal, checkpoint)
    checkpoint_path.write_text(checkpoint.model_dump_json(), encoding="utf-8")
    if fault == "checkpoint":
        checkpoint_path.write_text("{}", encoding="utf-8")
    if fault == "policy":
        checkpoint_path.write_text(
            checkpoint.model_copy(update={"policy_hash": "d" * 64}).model_dump_json(),
            encoding="utf-8",
        )
    if fault == "journal":
        journal.unlink()
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("forbidden")
        raise AssertionError("preflight reached credentials or transport")

    monkeypatch.setattr(cli, "resolve_credential", forbidden)
    monkeypatch.setattr(cli, "make_demo_critic_transport", forbidden)
    monkeypatch.setattr(cli, "make_demo_creator_transport", forbidden)
    monkeypatch.setattr(cli.httpx, "Client", forbidden)
    output = tmp_path / "output"
    ledger = tmp_path / "runtime" / "ledger.sqlite3"
    argv = [
        "--symbol",
        "BTCUSDT",
        "--provider",
        "google_ai_studio" if fault == "provider" else "demo",
        "--output-dir",
        str(output),
        "--creator-epoch-journal",
        str(journal),
        "--creator-epoch-control",
        str(control),
        "--creator-epoch-checkpoint",
        str(checkpoint_path),
    ]
    if fault == "ledger":
        argv += ["--feedback-path", str(tmp_path / "absent-feedback.json")]
    else:
        argv += ["--ledger-db", str(ledger)]
    assert cli.main(argv) == 3
    assert calls == []
    assert not output.exists()
    assert not ledger.parent.exists()
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == before
