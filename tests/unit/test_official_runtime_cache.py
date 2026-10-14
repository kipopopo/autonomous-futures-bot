import hashlib
import json
import zipfile
from decimal import Decimal as D
from pathlib import Path

import pyarrow.parquet as pq

import autonomous_futures.research.official_market_data as market_data
import scripts.build_official_runtime_cache as runtime_cache
from autonomous_futures.research.official_market_data import HEADER
from scripts.build_official_runtime_cache import build


def test_decimal_cache_preserves_small_price_increment_and_omits_partial_htf(tmp_path):
    root = tmp_path / "source"
    directory = root / "TESTUSDT"
    directory.mkdir(parents=True)
    archive = directory / "TESTUSDT-1m-2023-01.zip"
    rows = [
        f"{i * 60000},1.000000000000000001,2,1,1.5,10,{i * 60000 + 59999},15,3,5,7.5,0"
        for i in range(5)
    ]
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("TESTUSDT-1m-2023-01.csv", ",".join(HEADER) + "\n" + "\n".join(rows))
    manifest = {
        "symbol": "TESTUSDT",
        "timeframe": "1m",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    archive.with_suffix(".zip.manifest.json").write_text(json.dumps(manifest))
    output = tmp_path / "immutable"
    build(root, output, "TESTUSDT")
    table = pq.read_table(output / "5m/canonical/TESTUSDT-5m.parquet")
    assert table.num_rows == 1
    assert table.column("open")[0].as_py() == D("1.000000000000000001")
    assert table.column("volume")[0].as_py() == D("50")
    assert pq.read_table(output / "1h/canonical/TESTUSDT-1h.parquet").num_rows == 0
    manifest = json.loads((output / "5m/manifests/TESTUSDT-5m.manifest.json").read_text())
    assert (
        manifest["builder_sha256"]
        == hashlib.sha256(Path(runtime_cache.__file__).read_bytes()).hexdigest()
    )
    assert (
        manifest["market_data_parser_sha256"]
        == hashlib.sha256(Path(market_data.__file__).read_bytes()).hexdigest()
    )
