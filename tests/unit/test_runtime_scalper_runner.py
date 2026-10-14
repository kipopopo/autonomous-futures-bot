from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load_script(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scalper_runner_defaults_to_official_snapshot_and_its_funding(tmp_path):
    runner = _load_script("qualify_runtime_scalper.py")
    expected = runner.REPO / "research/immutable-data/runtime-official-20261013"

    assert runner.DEFAULT_CACHE == expected
    assert runner.resolve_funding_path(tmp_path, None, "ADAUSDT") == (
        tmp_path / "funding/ADAUSDT-funding.csv"
    )


def test_scalper_runner_binds_cli_source_into_report_hash():
    runner = _load_script("qualify_runtime_scalper.py")
    report = {"implementation": {"core.py": "a" * 64}, "report_hash": "stale"}

    sealed = runner.bind_runner_source(report)
    identity = sealed.pop("report_hash")

    assert (
        sealed["implementation"]["scripts/qualify_runtime_scalper.py"]
        == hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()
    )
    assert identity == runner.content_hash(sealed)
    assert report["report_hash"] == "stale"


def test_scalper_runners_respect_explicit_funding_and_custom_cache(tmp_path):
    main = _load_script("qualify_runtime_scalper.py")
    variant = _load_script("qualify_runtime_scalper_variant.py")
    custom_cache = tmp_path / "snapshot"
    explicit = tmp_path / "separate-funding.csv"

    for runner in (main, variant):
        assert runner.resolve_funding_path(custom_cache, None, "LINKUSDT") == (
            custom_cache / "funding/LINKUSDT-funding.csv"
        )
        assert runner.resolve_funding_path(custom_cache, explicit, "LINKUSDT") == explicit


def test_scalper_cli_freezes_and_binds_authenticated_equity_scenario(tmp_path, monkeypatch):
    runner = _load_script("qualify_runtime_scalper.py")
    repo = runner.REPO
    evidence = (
        repo
        / "artifacts/qualification/runtime-inputs/testnet-account-probe-20261014-1791918191661.json"
    )
    commissions = repo / (
        "artifacts/qualification/runtime-inputs/testnet-commissions-1791824521337.json"
    )
    output = tmp_path / "capital-scenario"
    captured = {}

    def replay(**kwargs):
        captured.update(kwargs)
        return {
            "implementation": {},
            "sources": {},
            "source_files": [],
            "policy": {
                "starting_equity": str(kwargs["policy"].starting_equity),
                "trade_risk_pct": str(kwargs["policy"].trade_risk_pct),
                "daily_loss_pct": str(kwargs["policy"].daily_loss_pct),
            },
            "decision": "REJECTED",
            "metrics": {},
            "gates": {},
            "rejection_reasons": {},
            "report_hash": "unsealed",
        }

    monkeypatch.setattr(runner, "qualify_scalper", replay)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "qualify_runtime_scalper.py",
            "--equity-evidence",
            str(evidence),
            "--commissions",
            str(commissions),
            "--output",
            str(output),
        ],
    )

    runner.main()

    policy = json.loads((output / "frozen-policy.json").read_text(encoding="utf-8"))
    report_path = next(output.glob("SOLUSDT-*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert captured["policy"].starting_equity == runner.Decimal("4224.09882354")
    assert captured["policy"].trade_risk_pct == runner.Decimal("0.5")
    assert captured["policy"].maker_fee == runner.Decimal("0.000200")
    assert captured["policy"].taker_fee == runner.Decimal("0.000400")
    assert policy["starting_equity"] == "4224.09882354"
    assert policy["trade_risk_pct"] == "0.5"
    assert policy["daily_loss_pct"] == "5"
    assert report["capital_scenario"]["utc_day_start_baseline_verified"] is False
    assert report["sources"]["capital_scenario"]["path"].endswith(
        "testnet-account-probe-20261014-1791918191661.json"
    )
    body = dict(report)
    identity = body.pop("report_hash")
    assert identity == runner.content_hash(body)
