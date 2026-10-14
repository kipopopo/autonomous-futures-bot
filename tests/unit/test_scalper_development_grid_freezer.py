from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_freezer():
    path = Path(__file__).resolve().parents[2] / "scripts/freeze_scalper_development_grid.py"
    spec = importlib.util.spec_from_file_location("freeze_scalper_development_grid", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_freezer_binds_real_inputs_and_rejected_reference(tmp_path: Path) -> None:
    freezer = _load_freezer()
    repo = tmp_path
    (repo / "research/qualification-holdout-2026-08-2026-09").mkdir(parents=True)
    holdout = {
        "status": "partially_consumed",
        "consumption": {"uninspected_target_symbols": ["LINKUSDT"]},
    }
    (repo / "research/qualification-holdout-2026-08-2026-09/holdout-index.json").write_text(
        json.dumps(holdout), encoding="utf-8"
    )
    for source in freezer.SOURCE_PATHS:
        path = repo / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    cache = repo / "nested/cache.bin"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"frozen-cache")
    commissions = repo / "commissions.json"
    commissions.write_text("authenticated-rates", encoding="utf-8")
    equity = repo / "equity.json"
    equity.write_text("sizing-seed", encoding="utf-8")
    reference_dir = repo / "references"
    reference_dir.mkdir()
    report = {
        "family": "MACRO_SCALPER",
        "symbol": "LINKUSDT",
        "decision": "REJECTED",
        "execution_authority": False,
        "policy": {"trade_risk_pct": "0.5", "daily_loss_pct": "5"},
    }
    report["report_hash"] = freezer.content_hash(report)
    (reference_dir / "LINKUSDT.json").write_text(json.dumps(report), encoding="utf-8")
    (reference_dir / "process-results.json").write_text("[]", encoding="utf-8")
    base = {
        "status": "FROZEN_BEFORE_EVALUATION",
        "symbols": ["LINKUSDT"],
        "inputs": {"cache": "nested", "filters": "filters.json", "funding_directory": "funding"},
        "input_fingerprints": [{"path": "nested/cache.bin", "sha256": freezer.digest(cache)}],
        "selection_interval": {"start": "2024-01-01", "end_exclusive": "2026-08-01"},
        "reserved_validation_interval": {"start": "2026-08-01", "end_exclusive": "2026-10-01"},
        "distance_thresholds": ["-2.5"],
        "target_atr_multipliers": ["2.0"],
        "candidate_selection_rule": {},
        "required_gates": [],
    }
    base_path = repo / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")

    protocol = freezer.freeze(
        base_protocol_path=base_path,
        reference_reports_dir=reference_dir,
        commissions_path=commissions,
        equity_evidence_path=equity,
        output_path=repo / "frozen.json",
        output_directory="output",
        repo=repo,
    )

    assert protocol["research_variant"] == "macro_scalper_symmetric_short_v1"
    assert protocol["excluded_combinations"] == []
    assert protocol["inputs"]["commissions"] == "commissions.json"
    assert protocol["inputs"]["equity_evidence"] == "equity.json"
    assert protocol["reference_reports"]["LINKUSDT"]["path"] == "references/LINKUSDT.json"
    assert protocol["reference_reports"]["LINKUSDT"]["sha256"] == freezer.digest(
        reference_dir / "LINKUSDT.json"
    )
    assert {item["path"] for item in protocol["input_fingerprints"]} >= {
        "scripts/freeze_scalper_development_grid.py",
        "research/qualification-holdout-2026-08-2026-09/holdout-index.json",
        "commissions.json",
        "equity.json",
        "references/LINKUSDT.json",
    }
