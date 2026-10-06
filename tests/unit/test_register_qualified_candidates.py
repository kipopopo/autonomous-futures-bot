"""Unit tests for register_qualified_candidates script and manifest publication."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomous_futures.data.quality import DataQualityError  # noqa: E402
from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    write_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    WalkForwardQualificationPolicy,
    read_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from scripts.explore_offline_strategies import (  # noqa: E402
    DEFAULT_BUNDLE_HASH,
    DEFAULT_REGISTRY_HASH,
)
from scripts.register_qualified_candidates import (  # noqa: E402
    DEFAULT_QUALIFIED_TARGETS,
    main,
    register_qualified_candidates,
    verify_existing_registry,
)
from tests.paper_fixtures import write_qualified_paper_fixture  # noqa: E402
from tests.strategy_fixtures import synthetic_rsi_candidate  # noqa: E402


@pytest.fixture
def synthetic_registration_inputs(tmp_path):
    """Artifact-IO fixtures only; no historical qualification or market-readiness claim."""
    cand_dir = tmp_path / "candidates"
    qual_dir = tmp_path / "qualifications"
    targets = []
    for original in DEFAULT_QUALIFIED_TARGETS:
        candidate = synthetic_rsi_candidate(
            symbol=original["symbol"],
            timeframe=original["timeframe"],
            bundle_hash=DEFAULT_BUNDLE_HASH,
            dataset_registry_hash=DEFAULT_REGISTRY_HASH,
        )
        assert candidate.candidate_id != original["candidate_id"]
        candidate_path = cand_dir / f"{candidate.candidate_id}.json"
        write_creator_candidate_artifact(candidate_path, candidate)
        qualification_hash = write_qualified_paper_fixture(tmp_path / "fixture.json", candidate)
        qualification = read_creator_candidate_qualification_artifact(
            qual_dir / f"{qualification_hash}.json"
        )
        write_creator_candidate_qualification_artifact(
            qual_dir / f"qual-{candidate.candidate_id}.json", qualification
        )
        targets.append({**original, "candidate_id": candidate.candidate_id})
    return targets, cand_dir, qual_dir


def test_register_prequalified_synthetic_candidates(
    tmp_path: Path, synthetic_registration_inputs
) -> None:
    targets, cand_dir, qual_dir = synthetic_registration_inputs
    reg_path = tmp_path / "candidate_registry.json"

    manifest, records = register_qualified_candidates(
        targets,
        registry_path=reg_path,
        candidates_dir=cand_dir,
        qualifications_dir=qual_dir,
    )

    assert reg_path.is_file()
    assert len(manifest.symbols) == 3
    assert manifest.registry_version == 2
    assert "BTCUSDT" in manifest.symbols
    assert "ETHUSDT" in manifest.symbols
    assert "SOLUSDT" in manifest.symbols
    assert {symbol: entry.candidate_id for symbol, entry in manifest.symbols.items()} == {
        target["symbol"]: target["candidate_id"] for target in targets
    }

    assert len(records) == 3
    assert all(r["status"] == "admitted" for r in records)

    # Check that candidate artifacts were written
    for _sym, entry in manifest.symbols.items():
        assert Path(entry.artifact_path).is_file()
        qualification = read_creator_candidate_qualification_artifact(
            qual_dir / f"qual-{entry.candidate_id}.json"
        )
        assert entry.qualification_hash == qualification.qualification_hash
        assert entry.candidate_artifact_hash == qualification.candidate_artifact_hash
        assert qualification.evaluator_run_id == "fixture-only-evaluator"
        assert qualification.execution_authority is False

    # Read back and validate manifest
    loaded_manifest, artifacts = verify_existing_registry(reg_path)
    assert loaded_manifest.registry_hash == manifest.registry_hash
    assert loaded_manifest.registry_version == 2
    assert set(artifacts.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


def test_register_qualified_candidates_fails_closed_without_verified_funding(
    tmp_path: Path, synthetic_registration_inputs
) -> None:
    targets, cand_dir, qual_dir = synthetic_registration_inputs
    reg_path = tmp_path / "candidate_registry.json"
    target = targets[0]
    qualification_path = qual_dir / f"qual-{target['candidate_id']}.json"
    qualification_path.unlink()  # Exercise the real cached evaluator, not fixture qualification.
    candidate_path = cand_dir / f"{target['candidate_id']}.json"
    candidate_bytes = candidate_path.read_bytes()

    impossible_policy = WalkForwardQualificationPolicy(
        policy_id="impossible-policy",
        minimum_windows=1,
        minimum_trades=5,
        minimum_profit_factor=Decimal("999.0"),
        maximum_drawdown_pct=Decimal("0.001"),
        minimum_average_return_pct=Decimal("0.0"),
    )

    with pytest.raises(DomainViolation, match="cached funding events"):
        register_qualified_candidates(
            targets[:1],
            registry_path=reg_path,
            candidates_dir=cand_dir,
            qualifications_dir=qual_dir,
            policy=impossible_policy,
        )
    assert not reg_path.exists()
    assert not qualification_path.exists()
    assert candidate_path.read_bytes() == candidate_bytes


def test_cli_check_only_and_json(
    synthetic_paper_registry: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reg_path = synthetic_paper_registry
    manifest, artifacts = verify_existing_registry(reg_path)
    paths = [reg_path, *(Path(entry.artifact_path) for entry in manifest.symbols.values())]
    original_bytes = {path: path.read_bytes() for path in paths}

    # CLI check-only with JSON
    code = main(["--registry-path", str(reg_path), "--check-only", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "verified"
    assert data["registry_version"] == 2
    assert "ETHUSDT" in data["symbols"]
    assert set(data["symbols"]) == set(artifacts)
    assert {path: path.read_bytes() for path in paths} == original_bytes


@pytest.mark.parametrize("target", DEFAULT_QUALIFIED_TARGETS, ids=lambda target: target["symbol"])
def test_legacy_registration_fails_closed_without_verified_funding(
    tmp_path: Path, synthetic_paper_registry: Path, target
) -> None:
    registry_bytes = synthetic_paper_registry.read_bytes()
    cand_dir = tmp_path / "legacy-candidates"
    qual_dir = tmp_path / "legacy-qualifications"
    with pytest.raises(DataQualityError, match="cached funding events"):
        register_qualified_candidates(
            (target,),
            registry_path=synthetic_paper_registry,
            candidates_dir=cand_dir,
            qualifications_dir=qual_dir,
        )
    assert synthetic_paper_registry.read_bytes() == registry_bytes
    assert not tuple(cand_dir.iterdir())
    assert not tuple(qual_dir.iterdir())


def test_cli_legacy_registration_denies_without_publication(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reg_path = tmp_path / "legacy-registry.json"
    code = main(
        [
            "--registry-path",
            str(reg_path),
            "--candidates-dir",
            str(tmp_path / "legacy-candidates"),
            "--qualifications-dir",
            str(tmp_path / "legacy-qualifications"),
            "--json",
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cached funding events" in captured.err
    assert not reg_path.exists()
    assert not tuple((tmp_path / "legacy-candidates").iterdir())
    assert not tuple((tmp_path / "legacy-qualifications").iterdir())
