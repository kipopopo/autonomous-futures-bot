"""Resolve and verify actual report source bytes without changing research decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.execution.qualification_receipts import verify_source_index  # noqa: E402
from autonomous_futures.research.runtime_qualification import content_hash  # noqa: E402


def attest(report_path: Path, output: Path, repo: Path = REPO) -> Path:
    raw = report_path.read_bytes()
    report = json.loads(raw)
    identity = report.pop("report_hash")
    if content_hash(report) != identity:
        raise ValueError("Original research report hash mismatch")
    required: set[str] = set()
    candidates: set[Path] = set()

    def collect(item: Any) -> None:
        if isinstance(item, str) and len(item) == 64 and all(c in "0123456789abcdef" for c in item):
            required.add(item)
        elif isinstance(item, dict):
            if "path" in item:
                path = (repo / item["path"]).resolve()
                if not path.is_relative_to(repo.resolve()):
                    raise ValueError("Report source path is outside the repository")
                candidates.add(path)
                if path.suffix == ".parquet":
                    cache = path.parents[2]
                    candidates.update(cache.glob("*/manifests/*.json"))
                    candidates.update((cache / "funding").glob("*"))
            for value in item.values():
                collect(value)
        elif isinstance(item, list):
            for value in item:
                collect(value)

    collect(report["sources"])
    candidates.update((repo / "artifacts/qualification/runtime-inputs").glob("*.json"))
    candidates.update(
        (repo / "research/official-archives/1m" / report["symbol"]).glob("*.manifest.json")
    )
    files = []
    for path in sorted(candidates):
        if not path.is_file():
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha in required:
            files.append({"path": path.relative_to(repo).as_posix(), "sha256": sha})
    verify_source_index(report["sources"], files, repo)
    body = {
        "schema": "runtime-report-source-attestation-v1",
        "report_path": report_path.resolve().relative_to(repo.resolve()).as_posix(),
        "report_sha256": hashlib.sha256(raw).hexdigest(),
        "original_report_hash": identity,
        "original_decision": report["decision"],
        "source_files": files,
        "execution_authority": False,
    }
    encoded = json.dumps(body, sort_keys=True, indent=2).encode()
    sha = hashlib.sha256(encoded).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{report['symbol']}-source-attestation-{sha[:16]}.json"
    if target.exists():
        if target.read_bytes() != encoded:
            raise ValueError("Source attestation identity collision")
    else:
        with target.open("xb") as destination:
            destination.write(encoded)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(attest(args.report, args.output), flush=True)


if __name__ == "__main__":
    main()
