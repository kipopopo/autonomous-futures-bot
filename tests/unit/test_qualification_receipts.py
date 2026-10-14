import hashlib
import json
from pathlib import Path

import pytest

from autonomous_futures.execution.qualification_receipts import (
    verify_historical_report,
    verify_runtime_report,
    verify_source_index,
)
from autonomous_futures.research.runtime_qualification import content_hash


def test_actual_rejected_scalper_evidence_cannot_grant_admission():
    repo = Path(__file__).resolve().parents[2]
    path = repo / "tests/fixtures/runtime-qualification/rejected-link-scalper.json"
    with pytest.raises(ValueError):
        verify_historical_report(path, repo=repo, family="MACRO_SCALPER", symbol="LINKUSDT")


def test_changing_only_qualified_flag_cannot_turn_rejection_into_authority(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    original = repo / "tests/fixtures/runtime-qualification/rejected-link-scalper.json"
    data = json.loads(original.read_text())
    data["decision"] = "QUALIFIED"
    target = tmp_path / "forged.json"
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_historical_report(target, repo=repo, family="MACRO_SCALPER", symbol="LINKUSDT")


def test_rehashed_edited_report_cannot_replace_independently_pinned_bytes(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    original = repo / "tests/fixtures/runtime-qualification/rejected-link-scalper.json"
    (tmp_path / "deploy").mkdir()
    manifest = {
        "schema": "runtime-qualification-admission-v1",
        "approved_reports": [
            {
                "family": "MACRO_SCALPER",
                "symbol": "LINKUSDT",
                "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            }
        ],
    }
    (tmp_path / "deploy/qualification-admission.json").write_text(json.dumps(manifest))
    data = json.loads(original.read_bytes())
    data.pop("report_hash")
    data["decision"] = "QUALIFIED"
    data["gates"] = {key: True for key in data["gates"]}
    data["report_hash"] = content_hash(data)
    target = tmp_path / "edited.json"
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="reviewed deployment admission"):
        verify_runtime_report(target, repo=tmp_path, family="MACRO_SCALPER", symbol="LINKUSDT")
    # Even pinning genuine bytes never substitutes for passing research gates.
    with pytest.raises(ValueError, match="qualification gates"):
        verify_runtime_report(original, repo=tmp_path, family="MACRO_SCALPER", symbol="LINKUSDT")


def test_runtime_report_has_no_self_admission_when_manifest_is_empty():
    repo = Path(__file__).resolve().parents[2]
    original = repo / "tests/fixtures/runtime-qualification/rejected-link-scalper.json"
    with pytest.raises(ValueError, match="No reviewed deployment admission"):
        verify_runtime_report(original, repo=repo, family="MACRO_SCALPER", symbol="LINKUSDT")


def test_source_index_must_cover_manifest_and_cost_hashes(tmp_path):
    price, cost = tmp_path / "prices", tmp_path / "commissions"
    price.write_bytes(b"explicit recorded-price fixture")
    cost.write_bytes(b"explicit recorded-commission fixture")
    ph, ch = (hashlib.sha256(path.read_bytes()).hexdigest() for path in (price, cost))
    sources = {"five": {"path": "prices", "sha256": ph}, "commissions_sha256": ch}
    index = [{"path": "prices", "sha256": ph}]
    with pytest.raises(ValueError, match="omits claimed"):
        verify_source_index(sources, index, tmp_path)
    index.append({"path": "commissions", "sha256": ch})
    verify_source_index(sources, index, tmp_path)
    cost.write_bytes(b"changed fixture bytes")
    with pytest.raises(ValueError, match="source bytes changed"):
        verify_source_index(sources, index, tmp_path)


def test_matching_manifest_cannot_hide_changed_archive_bytes(tmp_path):
    archive = tmp_path / "sample.zip"
    archive.write_bytes(b"explicit archive-byte fixture")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = tmp_path / "sample.zip.CHECKSUM"
    checksum.write_text(sha + "  sample.zip\n")
    manifest = tmp_path / "sample.zip.manifest.json"
    manifest.write_text(json.dumps({"sha256": sha}))
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    sources = {"minute_manifests": {manifest.name: manifest_sha}}
    files = [{"path": manifest.name, "sha256": manifest_sha}]
    verify_source_index(sources, files, tmp_path)
    archive.write_bytes(b"altered archive bytes")
    with pytest.raises(ValueError, match="archive bytes changed"):
        verify_source_index(sources, files, tmp_path)


def test_ict_report_must_bind_strategy_index_and_daily_risk_implementation(tmp_path):
    repo = tmp_path / "repo"
    source_paths = (
        "src/autonomous_futures/execution/trade_plan.py",
        "src/autonomous_futures/execution/daily_risk.py",
        "src/autonomous_futures/strategy/ict_mmxm.py",
        "src/autonomous_futures/strategy/pd_array_touch_index.py",
    )
    implementation = {}
    for relative in source_paths:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
        implementation[relative] = hashlib.sha256(path.read_bytes()).hexdigest()

    market = repo / "market.json"
    market.write_text("verified recorded market bytes", encoding="utf-8")
    market_sha = hashlib.sha256(market.read_bytes()).hexdigest()
    windows = [
        {
            "start_ms": index * 60_000,
            "end_ms": (index + 1) * 60_000,
            "trades": [{"net_pnl": "1", "stress_net_pnl": "0.5"}],
        }
        for index in range(5)
    ]
    report = {
        "family": "ICT_TWINS",
        "symbol": "SOLUSDT",
        "decision": "QUALIFIED",
        "gates": {"recorded_evidence": True},
        "implementation": implementation,
        "sources": {"market": {"path": "market.json", "sha256": market_sha}},
        "source_files": [{"path": "market.json", "sha256": market_sha}],
        "policy": {
            "windows": 5,
            "minimum_trades": 5,
            "minimum_profitable_windows": 3,
            "minimum_profit_factor": "1.10",
            "maximum_drawdown_pct": "5",
            "starting_equity": "100",
            "daily_loss_pct": "5",
            "trade_risk_pct": "0.5",
        },
        "windows": windows,
        "metrics": {"drawdown_usdt": "0"},
        "configuration": {},
    }

    def write_report(
        omitted_dependency: str | None = None,
        trade_risk_pct: str | None = "0.5",
        daily_loss_pct: str | None = "5",
    ) -> Path:
        candidate = dict(report)
        candidate["implementation"] = {
            path: sha for path, sha in implementation.items() if path != omitted_dependency
        }
        candidate["policy"] = dict(report["policy"])
        if trade_risk_pct is None:
            candidate["policy"].pop("trade_risk_pct")
        else:
            candidate["policy"]["trade_risk_pct"] = trade_risk_pct
        if daily_loss_pct is None:
            candidate["policy"].pop("daily_loss_pct")
        else:
            candidate["policy"]["daily_loss_pct"] = daily_loss_pct
        candidate["report_hash"] = content_hash(candidate)
        if omitted_dependency is not None:
            name = omitted_dependency.rsplit("/", 1)[-1]
        elif trade_risk_pct == "0.5" and daily_loss_pct == "5":
            name = "complete"
        else:
            name = f"risk-{trade_risk_pct}-daily-{daily_loss_pct}"
        path = tmp_path / f"ict-{name}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        return path

    for omitted in (source_paths[1], source_paths[3]):
        with pytest.raises(ValueError, match="implementation binding is incomplete"):
            verify_historical_report(
                write_report(omitted), repo=repo, family="ICT_TWINS", symbol="SOLUSDT"
            )
    verified = verify_historical_report(
        write_report(), repo=repo, family="ICT_TWINS", symbol="SOLUSDT"
    )
    assert verified.family == "ICT_TWINS"
    for risk, daily_loss in ((None, "5"), ("0.25", "5"), ("0.5", None), ("0.5", "4")):
        with pytest.raises(ValueError, match="risk policy"):
            verify_historical_report(
                write_report(trade_risk_pct=risk, daily_loss_pct=daily_loss),
                repo=repo,
                family="ICT_TWINS",
                symbol="SOLUSDT",
            )
