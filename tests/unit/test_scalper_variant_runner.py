from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts/qualify_runtime_scalper_variant.py"
    spec = importlib.util.spec_from_file_location("qualify_runtime_scalper_variant", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_development_report_cannot_grant_admission() -> None:
    runner = _load_runner()
    report = {
        "decision": "QUALIFIED",
        "execution_authority": True,
        "report_hash": "stale-hash",
        "gates": {"stress_positive": True},
    }

    marked = runner.mark_development_only(report, {"status": "development_only_not_admissible"})

    unhashed = dict(marked)
    claimed_hash = unhashed.pop("report_hash")
    assert marked["candidate_decision_on_development_sample"] == "QUALIFIED"
    assert marked["decision"] == "DEVELOPMENT_ONLY"
    assert marked["execution_authority"] is False
    assert marked["gates"] == {"stress_positive": True}
    assert claimed_hash == runner.qualification.content_hash(unhashed)
    assert report["decision"] == "QUALIFIED"


def test_variant_cli_binds_authenticated_equity_as_research_sizing_seed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    runner = _load_runner()
    reference = tmp_path / "reference.json"
    reference.write_text(
        json.dumps({"family": "MACRO_SCALPER", "symbol": "LINKUSDT", "decision": "REJECTED"}),
        encoding="utf-8",
    )
    output = tmp_path / "reports"
    evidence = runner.REPO / (
        "artifacts/qualification/runtime-inputs/testnet-account-probe-20261014-1791918191661.json"
    )
    commissions = runner.REPO / (
        "artifacts/qualification/runtime-inputs/testnet-commissions-1791824521337.json"
    )
    captured = {}

    def qualify(**kwargs):
        captured.update(kwargs)
        return {
            "family": "MACRO_SCALPER",
            "symbol": "LINKUSDT",
            "policy": {"starting_equity": str(kwargs["policy"].starting_equity)},
            "implementation": {},
            "decision": "REJECTED",
            "execution_authority": False,
            "gates": {},
            "metrics": {},
            "windows": [],
        }

    monkeypatch.setattr(runner.qualification, "qualify_scalper", qualify)
    monkeypatch.setattr(
        runner.qualification,
        "bind_equity_scenario",
        lambda report, scenario, repo: {**report, "capital_scenario": scenario},
    )
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "qualify_runtime_scalper_variant.py",
            "--symbol",
            "LINKUSDT",
            "--reference-report",
            str(reference),
            "--distance-threshold",
            "-2.5",
            "--target-atr-multiplier",
            "2.0",
            "--equity-evidence",
            str(evidence),
            "--commissions",
            str(commissions),
            "--output",
            str(output),
        ],
    )

    runner.main()
    capsys.readouterr()

    assert (
        captured["policy"].starting_equity.as_tuple() == runner.Decimal("4224.09882354").as_tuple()
    )
    assert captured["policy"].trade_risk_pct == runner.Decimal("0.5")
    assert captured["policy"].maker_fee == runner.Decimal("0.000200")
    assert captured["policy"].taker_fee == runner.Decimal("0.000400")
    report = json.loads(next(output.glob("LINKUSDT-*.json")).read_text(encoding="utf-8"))
    assert report["capital_scenario"]["execution_authority"] is False
    assert report["decision"] == "DEVELOPMENT_ONLY"
