from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from decimal import Decimal
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/diagnose_ict_confirmation_displacement.py"
SPEC = importlib.util.spec_from_file_location("ict_confirmation_displacement", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
DIAGNOSTIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTIC)


def test_verified_archive_bars_accepts_relative_minute_root(tmp_path, monkeypatch) -> None:
    symbol = "DOGEUSDT"
    month = "2026-07"
    relative_minute_root = Path("research/official-archives/1m")
    archive_name = f"{symbol}-1m-{month}.zip"
    symbol_dir = tmp_path / relative_minute_root / symbol
    symbol_dir.mkdir(parents=True)
    archive_path = symbol_dir / archive_name
    timestamp_ms = 1_783_000_800_000
    row = f"{timestamp_ms},0.1000,0.1010,0.0990,0.1005,100,{timestamp_ms + 59_999},10,3,50,5,0\n"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{symbol}-1m-{month}.csv", row)
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (symbol_dir / f"{archive_name}.manifest.json").write_text(
        json.dumps(
            {
                "symbol": symbol,
                "timeframe": "1m",
                "month": month,
                "sha256": archive_hash,
            }
        ),
        encoding="utf-8",
    )
    (symbol_dir / f"{archive_name}.CHECKSUM").write_text(
        f"{archive_hash} *{archive_name}\n", encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(DIAGNOSTIC, "REPO", tmp_path.resolve())
    archive_hashes: dict[str, str] = {}

    bars = DIAGNOSTIC.verified_archive_bars(relative_minute_root, symbol, month, archive_hashes)

    assert len(bars) == 1
    assert bars[0].timestamp_ms == timestamp_ms
    assert bars[0].close == Decimal("0.1005")
    archive_relative_path = f"{relative_minute_root.as_posix()}/{symbol}/{archive_name}"
    assert archive_hashes[archive_relative_path] == archive_hash
