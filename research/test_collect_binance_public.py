from __future__ import annotations

import collect_binance_public as collector


def test_research_timeframe_contract_is_5m_primary_and_15m_context() -> None:
    assert collector.PRIMARY_INTERVAL == "5m"
    assert collector.CONTEXT_INTERVAL == "15m"
    assert collector.INTERVALS == {"5m": 300_000, "15m": 900_000}
    assert "1h" not in collector.INTERVALS


def test_fully_closed_cutoff_excludes_the_in_progress_candle() -> None:
    # 10:07:12 UTC with a 5-minute candle: the 10:00 candle is the last fully closed bar.
    now_ms = 10 * 60 * 60 * 1000 + 7 * 60 * 1000 + 12 * 1000
    assert collector.fully_closed_end_ms(now_ms, 300_000) == 10 * 60 * 60 * 1000 + 5 * 60 * 1000 - 1


def test_snapshot_name_is_timeframe_specific() -> None:
    assert collector.snapshot_path(("5m", "15m")).name == "snapshot-5m-15m.json"
