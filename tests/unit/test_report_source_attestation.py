import hashlib
import json

import pytest

from autonomous_futures.research.runtime_qualification import content_hash
from scripts.attest_runtime_report_sources import attest


def report_fixture(root):
    source = root / "observed.csv"
    source.write_bytes(b"explicit source-byte fixture")
    body = {
        "symbol": "SOLUSDT",
        "decision": "REJECTED",
        "sources": {
            "prices": {
                "path": source.name,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        },
    }
    body["report_hash"] = content_hash(body)
    path = root / "report.json"
    path.write_text(json.dumps(body))
    return path, source


def test_attestation_preserves_rejection_and_original_report_bytes(tmp_path):
    path, _ = report_fixture(tmp_path)
    before = path.read_bytes()
    result = attest(path, tmp_path / "attestations", tmp_path)
    evidence = json.loads(result.read_bytes())
    assert evidence["original_decision"] == "REJECTED"
    assert evidence["execution_authority"] is False
    assert path.read_bytes() == before
    assert attest(path, tmp_path / "attestations", tmp_path) == result


def test_changed_source_cannot_receive_an_attestation(tmp_path):
    path, source = report_fixture(tmp_path)
    source.write_bytes(b"changed bytes")
    with pytest.raises(ValueError):
        attest(path, tmp_path / "attestations", tmp_path)
    assert not (tmp_path / "attestations").exists()
