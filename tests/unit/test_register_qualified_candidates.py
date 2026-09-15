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

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    WalkForwardQualificationPolicy,
)
from scripts.register_qualified_candidates import (  # noqa: E402
    DEFAULT_QUALIFIED_TARGETS,
    main,
    register_qualified_candidates,
    verify_existing_registry,
)


def test_register_qualified_candidates_execution(tmp_path: Path) -> None:
    reg_path = tmp_path / "candidate_registry.json"
    cand_dir = tmp_path / "candidates"
    qual_dir = tmp_path / "qualifications"

    manifest, records = register_qualified_candidates(
        DEFAULT_QUALIFIED_TARGETS,
        registry_path=reg_path,
        candidates_dir=cand_dir,
        qualifications_dir=qual_dir,
    )

    assert reg_path.is_file()
    assert len(manifest.symbols) == 3
    assert "BTCUSDT" in manifest.symbols
    assert "ETHUSDT" in manifest.symbols
    assert "SOLUSDT" in manifest.symbols

    assert len(records) == 3
    assert all(r["status"] == "admitted" for r in records)

    # Check that candidate artifacts were written
    for _sym, entry in manifest.symbols.items():
        assert Path(entry.artifact_path).is_file()

    # Read back and validate manifest
    loaded_manifest, artifacts = verify_existing_registry(reg_path)
    assert loaded_manifest.registry_hash == manifest.registry_hash
    assert set(artifacts.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


def test_register_qualified_candidates_rejects_unqualified(tmp_path: Path) -> None:
    reg_path = tmp_path / "candidate_registry.json"
    cand_dir = tmp_path / "candidates"
    qual_dir = tmp_path / "qualifications"

    impossible_policy = WalkForwardQualificationPolicy(
        policy_id="impossible-policy",
        minimum_windows=1,
        minimum_trades=5,
        minimum_profit_factor=Decimal("999.0"),
        maximum_drawdown_pct=Decimal("0.001"),
        minimum_average_return_pct=Decimal("0.0"),
    )

    with pytest.raises(DomainViolation, match="failed qualification"):
        register_qualified_candidates(
            DEFAULT_QUALIFIED_TARGETS[:1],
            registry_path=reg_path,
            candidates_dir=cand_dir,
            qualifications_dir=qual_dir,
            policy=impossible_policy,
        )


def test_cli_check_only_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reg_path = tmp_path / "candidate_registry.json"
    cand_dir = tmp_path / "candidates"
    qual_dir = tmp_path / "qualifications"

    # Register first
    register_qualified_candidates(
        DEFAULT_QUALIFIED_TARGETS,
        registry_path=reg_path,
        candidates_dir=cand_dir,
        qualifications_dir=qual_dir,
    )

    # CLI check-only with JSON
    code = main(["--registry-path", str(reg_path), "--check-only", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "verified"
    assert "ETHUSDT" in data["symbols"]
