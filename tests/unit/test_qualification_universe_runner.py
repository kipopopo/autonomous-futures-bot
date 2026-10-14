from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts/qualify_runtime_universe.py"
    spec = importlib.util.spec_from_file_location("qualify_runtime_universe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_includes_partition_workers_without_overlap() -> None:
    runner = _load_runner()

    first = runner.select_symbols("ict", ["NEARUSDT", "LINKUSDT"], [])
    second = runner.select_symbols("ict", ["APTUSDT", "ADAUSDT"], [])

    assert first == ["NEARUSDT", "LINKUSDT"]
    assert second == ["APTUSDT", "ADAUSDT"]
    assert set(first).isdisjoint(second)


def test_default_universe_respects_strategy_eligibility() -> None:
    runner = _load_runner()

    ict_symbols = runner.select_symbols("ict", None, [])
    scalper_symbols = runner.select_symbols("scalper", None, [])

    assert len(ict_symbols) == 12
    assert len(scalper_symbols) == 11
    assert "BTCUSDT" not in scalper_symbols


def test_ict_entry_mode_is_passed_to_frozen_pair_runner(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_runner()
    captured: dict[str, object] = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner.run(
        "NEARUSDT",
        "ict",
        Path("commissions.json"),
        tmp_path,
        worker_count=1,
        entry_mode="reclaim_retest",
        equity_evidence_path=Path("account-equity.json"),
    )
    command = captured["command"]

    assert isinstance(command, list)
    assert command[command.index("--entry-mode") + 1] == "reclaim_retest"
    assert command[command.index("--equity-evidence") + 1] == "account-equity.json"
    assert result["entry_mode"] == "reclaim_retest"
    assert result["equity_evidence"] == "account-equity.json"
    capsys.readouterr()


def test_scalper_orchestration_binds_commission_input(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_runner()
    captured: dict[str, object] = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner.run(
        "ADAUSDT",
        "scalper",
        Path("commissions.json"),
        tmp_path,
        worker_count=1,
        starting_equity=Decimal("4224.09882354"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--symbol") + 1] == "ADAUSDT"
    assert Path(command[command.index("--cache") + 1]) == (
        runner.REPO / "research/immutable-data/runtime-official-20261013"
    )
    assert command[command.index("--commissions") + 1] == "commissions.json"
    assert command[command.index("--starting-equity") + 1] == "4224.09882354"
    assert result["starting_equity"] == "4224.09882354"
    assert result["exit_code"] == 0
    capsys.readouterr()


def test_ict_orchestration_requires_commission_input(tmp_path) -> None:
    runner = _load_runner()

    with pytest.raises(ValueError, match="requires commission data"):
        runner.run("ADAUSDT", "ict", None, tmp_path, worker_count=1)


def test_scalper_orchestration_requires_commission_input(tmp_path) -> None:
    runner = _load_runner()

    with pytest.raises(ValueError, match="requires commission data"):
        runner.run("ADAUSDT", "scalper", None, tmp_path, worker_count=1)


def test_universe_runner_rejects_ambiguous_capital_inputs(tmp_path) -> None:
    runner = _load_runner()

    with pytest.raises(ValueError, match="Choose either"):
        runner.run(
            "ADAUSDT",
            "scalper",
            Path("commissions.json"),
            tmp_path,
            worker_count=1,
            starting_equity=Decimal("100"),
            equity_evidence_path=Path("account-equity.json"),
        )


@pytest.mark.parametrize(
    ("family", "include", "exclude", "message"),
    [
        ("ict", ["NEARUSDT"], ["NEARUSDT"], "both included and excluded"),
        ("ict", ["NOT-A-PAIR"], [], "Unknown universe symbols"),
        ("ict", ["NEARUSDT", "NEARUSDT"], [], "duplicate symbols"),
        ("scalper", ["BTCUSDT"], [], "unavailable to scalper"),
        ("ict", [], [], "partition is empty"),
        ("unknown", ["BTCUSDT"], [], "Unsupported qualification family"),
    ],
)
def test_invalid_partition_fails_closed(
    family: str, include: list[str], exclude: list[str], message: str
) -> None:
    runner = _load_runner()

    with pytest.raises(ValueError, match=message):
        runner.select_symbols(family, include, exclude)
