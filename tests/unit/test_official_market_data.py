import hashlib
import zipfile
from decimal import Decimal as D

import pytest

from autonomous_futures.research.official_market_data import (
    HEADER,
    aggregate_minutes,
    archive_minutes,
)
from autonomous_futures.strategy.ict_mmxm import Candle


def archive(tmp_path, rows, *, with_header=True):
    path = tmp_path / "TESTUSDT-1m-2023-01.zip"
    header = ",".join(HEADER) + "\n" if with_header else ""
    with zipfile.ZipFile(path, "w") as handle:
        handle.writestr("TESTUSDT-1m-2023-01.csv", header + "\n".join(rows))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def row(timestamp):
    return f"{timestamp},1.000000000000000001,2,1,1.5,10,{timestamp + 59999},15,3,5,7.5,0"


def test_exact_decimal_candles_and_continuity(tmp_path):
    path, sha = archive(tmp_path, [row(0), row(60000)])
    bars = list(archive_minutes(path, sha))
    assert bars[0].open == D("1.000000000000000001")
    assert bars[1].timestamp_ms == 60000


def test_headerless_official_kline_archive_is_supported(tmp_path):
    path, sha = archive(tmp_path, [row(0), row(60000)], with_header=False)
    bars = list(archive_minutes(path, sha))
    assert [bar.timestamp_ms for bar in bars] == [0, 60000]


def test_checksum_and_missing_minutes_are_not_repaired(tmp_path):
    path, sha = archive(tmp_path, [row(0), row(120000)])
    with pytest.raises(ValueError, match="checksum"):
        list(archive_minutes(path, "0" * 64))
    with pytest.raises(ValueError, match="gapped"):
        list(archive_minutes(path, sha))


def test_higher_timeframe_requires_a_complete_observed_bucket():
    bars = [Candle(i * 60000, D("1"), D("2"), D("1"), D("1.5"), D("10")) for i in range(5)]
    higher = list(aggregate_minutes(iter(bars), 300000))
    assert len(higher) == 1
    assert higher[0].volume == D("50")
    assert not list(aggregate_minutes(iter(bars[1:]), 300000))
    assert not list(aggregate_minutes(iter([bars[0], *bars[2:]]), 300000))
