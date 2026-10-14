from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts/qualify_frozen_scalper_candidate.py"
    spec = importlib.util.spec_from_file_location("qualify_frozen_scalper_candidate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_holdout_interval_must_not_overlap_selection() -> None:
    runner = _load_runner()

    with pytest.raises(ValueError, match="overlaps"):
        runner.validate_intervals(
            {"start": "2024-01-01", "end_exclusive": "2026-08-01"},
            {"start": "2023-12-01", "end_exclusive": "2024-02-01"},
        )


def test_holdout_report_preserves_decision_without_execution_authority(tmp_path: Path) -> None:
    runner = _load_runner()
    script = Path(runner.__file__)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text("{}", encoding="utf-8")
    funding_path = tmp_path / "LINKUSDT-funding.csv"
    funding_path.write_text("symbol,fundingTime,fundingRate,markPrice\n", encoding="utf-8")
    funding_manifest_path = tmp_path / "LINKUSDT-funding.manifest.json"
    funding_manifest_path.write_text(
        json.dumps(
            {
                "symbol": "LINKUSDT",
                "sha256": runner.digest(funding_path),
                "official_archives": [{"month": "2021-01", "sha256": "funding-hash"}],
            }
        ),
        encoding="utf-8",
    )
    candidate = {
        "candidate_id": "test-candidate",
        "family": "MACRO_SCALPER",
        "symbol": "LINKUSDT",
        "parameters": {"distance_threshold": "-3.5", "target_atr_multiplier": "2.2"},
        "selection_reports": [],
        "validation_interval": {"start": "2021-01-01", "end_exclusive": "2024-01-01"},
    }
    start_ms = 1609459200000
    end_ms = 1704067200000
    sources = {}
    for role, timeframe, symbol in (
        ("market", "15m", "LINKUSDT"),
        ("execution", "5m", "LINKUSDT"),
        ("macro", "1h", "BTCUSDT"),
    ):
        timeframe_root = tmp_path / role / timeframe
        canonical = timeframe_root / "canonical" / f"{symbol}-{timeframe}.parquet"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(f"{role}-bars".encode())
        manifest = timeframe_root / "manifests" / f"{symbol}-{timeframe}.manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "builder_sha256": "a" * 64,
                    "market_data_parser_sha256": "b" * 64,
                    "official_archives": [{"month": "2021-01", "sha256": role}],
                }
            ),
            encoding="utf-8",
        )
        sources[role] = {
            "path": str(canonical),
            "sha256": runner.digest(canonical),
            "manifest_sha256": runner.digest(manifest),
        }
    report = {
        "family": "MACRO_SCALPER",
        "symbol": "LINKUSDT",
        "decision": "QUALIFIED",
        "execution_authority": True,
        "windows": [{"start_ms": start_ms}, {"end_ms": end_ms}],
        "sources": {
            **sources,
            "funding": {"path": str(funding_path), "sha256": runner.digest(funding_path)},
        },
        "implementation": {},
        "report_hash": "stale",
    }

    sealed = runner.seal_holdout_report(
        report, candidate, candidate_path, funding_manifest_path, funding_path
    )

    assert sealed["decision"] == "QUALIFIED"
    assert sealed["execution_authority"] is False
    assert sealed["candidate_validation"]["evidence_class"] == "INDEPENDENT_HISTORICAL_HOLDOUT"
    assert (
        sealed["candidate_validation"]["market_archive_provenance"]["market"][
            "market_data_parser_sha256"
        ]
        == "b" * 64
    )
    assert sealed["implementation"]["scripts/qualify_frozen_scalper_candidate.py"] == runner.digest(
        script
    )
    unhashed = dict(sealed)
    claimed_hash = unhashed.pop("report_hash")
    assert claimed_hash == runner.qualification.content_hash(unhashed)


def test_frozen_xrp_candidate_manifest_binds_aggregate_selection_and_shared_context() -> None:
    runner = _load_runner()
    repo = Path(__file__).resolve().parents[2]
    manifest_path = (
        repo
        / "research/qualification-development-2024-2026"
        / "frozen-xrp-symmetric-short-candidate-v1.json"
    )
    candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
    unhashed = dict(candidate)
    manifest_hash = unhashed.pop("manifest_hash")
    assert manifest_hash == runner.qualification.content_hash(unhashed)
    assert candidate["status"] == "FROZEN_BEFORE_VALIDATION"
    assert candidate["execution_authority"] is False
    assert candidate["symbol"] == "XRPUSDT"
    assert candidate["parameters"] == {
        "distance_threshold": "-4.0",
        "target_atr_multiplier": "3.0",
    }
    assert candidate["policy_binding"]["starting_equity"] == "4224.09882354"
    assert candidate["holdout_partition_ledger"]["status"] == "partially_consumed"
    assert candidate["holdout_partition_ledger"]["target_symbol_uninspected_before_freeze"] is True

    # Because holdout-index.json was updated after the single XRP holdout evaluation,
    # re-validating against the live index must fail closed on pre_evaluation_index_sha256.
    with pytest.raises(ValueError, match="Holdout partition index changed since candidate freeze"):
        runner.load_candidate(manifest_path, repo=repo)


def test_frozen_sui_candidate_manifest_binds_selection_and_shared_context() -> None:
    runner = _load_runner()
    repo = Path(__file__).resolve().parents[2]
    manifest_path = (
        repo
        / "research/qualification-development-2024-2026"
        / "frozen-sui-symmetric-short-candidate-v1.json"
    )
    candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
    unhashed = dict(candidate)
    manifest_hash = unhashed.pop("manifest_hash")
    assert manifest_hash == runner.qualification.content_hash(unhashed)
    assert candidate["status"] == "FROZEN_BEFORE_VALIDATION"
    assert candidate["execution_authority"] is False
    assert candidate["symbol"] == "SUIUSDT"
    assert candidate["parameters"] == {
        "distance_threshold": "-3.4",
        "target_atr_multiplier": "4.5",
    }
    assert candidate["policy_binding"]["starting_equity"] == "4224.09882354"
    assert candidate["holdout_partition_ledger"]["status"] == "partially_consumed"
    assert candidate["holdout_partition_ledger"]["target_symbol_uninspected_before_freeze"] is True

    with pytest.raises(ValueError, match="Holdout partition index changed since candidate freeze"):
        runner.load_candidate(manifest_path, repo=repo)




