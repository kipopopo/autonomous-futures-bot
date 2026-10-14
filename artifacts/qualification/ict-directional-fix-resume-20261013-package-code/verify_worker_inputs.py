from __future__ import annotations

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
manifest_path = root / "artifacts/qualification/ict-directional-fix-resume-worker-input-manifest-20261013.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assert manifest["schema"] == "afb-ict-directional-fix-worker-inputs-v1"
assert manifest["symbols"] == ["NEARUSDT", "LINKUSDT", "APTUSDT", "ADAUSDT"]
assert manifest["qualification_interval"] == "2024-01-01 through 2026-08-01 exclusive"
assert manifest["reserved_holdout"].startswith("2026-08-01 through 2026-10-01")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


for item in manifest["inputs"]:
    path = (root / item["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise SystemExit(f"missing or escaped manifest input: {item['path']}")
    if sha256(path) != item["sha256"]:
        raise SystemExit(f"manifest SHA-256 mismatch: {item['path']}")

months = set()
year, month = 2023, 12
while (year, month) <= (2026, 7):
    months.add(f"{year:04d}-{month:02d}")
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
for symbol in manifest["symbols"]:
    archives = sorted((root / "research/official-archives/1m" / symbol).glob(f"{symbol}-1m-*.zip"))
    observed = {"-".join(path.stem.split("-")[-2:]) for path in archives}
    if len(archives) != 32 or observed != months:
        raise SystemExit(f"{symbol}: monthly archive coverage mismatch")

if list(root.rglob(".env")):
    raise SystemExit("unexpected .env file in isolated worker")
cache = root / "research/immutable-data/runtime-official-20261013"
if not cache.is_symlink() or not cache.exists():
    raise SystemExit("verified runtime cache link is missing")
print(f"INPUT_DATA_VERIFIED files={len(manifest['inputs'])} archives=128 interval=2023-12..2026-07 holdout_excluded=true")
