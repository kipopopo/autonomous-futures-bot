from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from autonomous_futures.research.runtime_qualification import content_hash


def _load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts/qualify_runtime_ict.py"
    spec = importlib.util.spec_from_file_location("qualify_runtime_ict", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ict_cli_freezes_and_binds_authenticated_equity_scenario(tmp_path, monkeypatch, capsys):
    runner = _load_runner()
    repo = runner.REPO
    evidence = (
        repo
        / "artifacts/qualification/runtime-inputs/testnet-account-probe-20261014-1791918191661.json"
    )
    output = tmp_path / "capital-scenario"
    captured = {}

    def replay(**kwargs):
        captured.update(kwargs)
        policy = kwargs["policy"]
        return {
            "family": "ICT_TWINS",
            "symbol": "ETHUSDT",
            "policy": {
                "starting_equity": str(policy.starting_equity),
                "trade_risk_pct": str(policy.trade_risk_pct),
                "daily_loss_pct": str(policy.daily_loss_pct),
            },
            "sources": {},
            "source_files": [],
            "decision": "REJECTED",
            "metrics": {},
            "gates": {},
            "report_hash": "unsealed",
        }

    monkeypatch.setattr(runner, "qualify_ict", replay)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "qualify_runtime_ict.py",
            "--symbol",
            "ETHUSDT",
            "--commissions",
            "fees.json",
            "--equity-evidence",
            str(evidence),
            "--output",
            str(output),
        ],
    )

    runner.main()
    capsys.readouterr()

    frozen = json.loads((output / "frozen-policy.json").read_text(encoding="utf-8"))
    report_path = next(output.glob("ETHUSDT-*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert captured["policy"].starting_equity == runner.Decimal("4224.09882354")
    assert frozen["policy"]["starting_equity"] == "4224.09882354"
    assert frozen["policy"]["trade_risk_pct"] == "0.5"
    assert frozen["policy"]["daily_loss_pct"] == "5"
    assert report["capital_scenario"]["utc_day_start_baseline_verified"] is False
    assert report["sources"]["capital_scenario"]["path"].endswith(
        "testnet-account-probe-20261014-1791918191661.json"
    )
    body = dict(report)
    identity = body.pop("report_hash")
    assert identity == content_hash(body)


def test_ict_cli_passes_lumitraders_qualification_modes(tmp_path, monkeypatch, capsys):
    runner = _load_runner()
    output = tmp_path / "lumitraders-modes"
    captured = {}

    def replay(**kwargs):
        captured.update(kwargs)
        policy = kwargs["policy"]
        return {
            "family": "ICT_TWINS",
            "symbol": "BTCUSDT",
            "policy": {
                "starting_equity": str(policy.starting_equity),
                "trade_risk_pct": str(policy.trade_risk_pct),
                "daily_loss_pct": str(policy.daily_loss_pct),
            },
            "sources": {},
            "source_files": [],
            "decision": "REJECTED",
            "metrics": {},
            "gates": {},
            "report_hash": "unsealed",
        }

    monkeypatch.setattr(runner, "qualify_ict", replay)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "qualify_runtime_ict.py",
            "--symbol",
            "BTCUSDT",
            "--commissions",
            "fees.json",
            "--entry-mode",
            "reclaim_retest",
            "--invalidation-mode",
            "stop_only",
            "--stop-loss-mode",
            "ote_79_adaptive",
            "--time-filter-mode",
            "killzones",
            "--output",
            str(output),
        ],
    )

    runner.main()
    capsys.readouterr()

    assert captured["entry_mode"] == "reclaim_retest"
    assert captured["invalidation_mode"] == "stop_only"
    assert captured["stop_loss_mode"] == "ote_79_adaptive"
    assert captured["time_filter_mode"] == "killzones"
