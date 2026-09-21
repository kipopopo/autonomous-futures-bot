"""Unit tests for Phase 292: Live Public Market Ingress (Binance USDⓈ-M).

Tests wire parsers, stream sequencer, exponential backoff with jitter, server clock skew,
gateway latency health, strict Decimal precision, paper safety invariants, and verification runner.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.api.canary import (  # noqa: E402
    CanaryEvidenceIntegrityError,
    load_verified_canary_live_market,
    verify_canary_phase_integrity,
)
from autonomous_futures.feed.client import (  # noqa: E402
    BinancePublicFeedClient,
    PublicMarketStreamSequencer,
)
from autonomous_futures.feed.models import (  # noqa: E402
    AggregateTrade,
    OrderBookLevel,
    parse_binance_agg_trade,
    parse_binance_depth5,
    parse_binance_mark_price,
)
from scripts.run_phase_292_live_ingress import run_phase_292_live_ingress  # noqa: E402

# =====================================================================
# 1. Wire Parser Tests
# =====================================================================


def test_parse_binance_depth5_valid() -> None:
    payload = {
        "e": "depthUpdate",
        "E": 1726912800000,
        "T": 1726912800000,
        "s": "BTCUSDT",
        "U": 1000,
        "u": 1005,
        "pu": 999,
        "b": [
            ["65000.50", "1.250"],
            ["65000.00", "2.500"],
            ["64999.50", "0.750"],
            ["64999.00", "3.000"],
            ["64998.50", "1.100"],
        ],
        "a": [
            ["65001.00", "0.850"],
            ["65001.50", "1.500"],
            ["65002.00", "2.100"],
            ["65002.50", "0.500"],
            ["65003.00", "4.000"],
        ],
    }

    snap = parse_binance_depth5(payload)
    assert snap.symbol == "BTCUSDT"
    assert snap.last_update_id == 1005
    assert snap.prev_last_update_id == 999
    assert snap.best_bid_price == Decimal("65000.50")
    assert snap.best_ask_price == Decimal("65001.00")
    assert snap.spread == Decimal("0.50")
    assert snap.spread_bps > Decimal("0")
    assert len(snap.bids) == 5
    assert len(snap.asks) == 5
    assert isinstance(snap.bids[0].price, Decimal)
    assert isinstance(snap.bids[0].quantity, Decimal)


def test_parse_binance_depth5_crossed_book_rejection() -> None:
    payload = {
        "s": "BTCUSDT",
        "u": 1005,
        "b": [["65005.00", "1.000"]],
        "a": [["65000.00", "1.000"]],
        "E": 1726912800000,
    }
    with pytest.raises(ValueError, match="crossed book"):
        parse_binance_depth5(payload)


def test_parse_binance_depth5_missing_fields_rejection() -> None:
    # Missing 's' (symbol)
    with pytest.raises((ValueError, KeyError)):
        parse_binance_depth5({"u": 100, "b": [], "a": []})

    # Missing 'u' (update ID)
    with pytest.raises((ValueError, KeyError)):
        parse_binance_depth5({"s": "BTCUSDT", "b": [], "a": []})


def test_parse_binance_agg_trade_valid() -> None:
    payload = {
        "e": "aggTrade",
        "E": 1726912800100,
        "s": "ETHUSDT",
        "a": 892341,
        "p": "3450.75",
        "q": "2.450",
        "f": 100001,
        "l": 100003,
        "T": 1726912800095,
        "m": True,
    }

    trade = parse_binance_agg_trade(payload)
    assert trade.symbol == "ETHUSDT"
    assert trade.aggregate_trade_id == 892341
    assert trade.price == Decimal("3450.75")
    assert trade.quantity == Decimal("2.450")
    assert trade.is_buyer_maker is True
    assert trade.trade_time == datetime.fromtimestamp(1726912800095 / 1000.0, tz=UTC)


def test_parse_binance_agg_trade_missing_fields_rejection() -> None:
    # Missing 'p'
    with pytest.raises((ValueError, KeyError)):
        parse_binance_agg_trade({"s": "ETHUSDT", "a": 1, "q": "1.0", "T": 1000, "m": False})


def test_parse_binance_mark_price_valid() -> None:
    payload = {
        "e": "markPriceUpdate",
        "E": 1726912800000,
        "s": "SOLUSDT",
        "p": "148.85000000",
        "i": "148.82000000",
        "P": "148.90000000",
        "r": "0.00010000",
        "T": 1726934400000,
    }

    mark = parse_binance_mark_price(payload)
    assert mark.symbol == "SOLUSDT"
    assert mark.mark_price == Decimal("148.85000000")
    assert mark.index_price == Decimal("148.82000000")
    assert mark.estimated_settle_price == Decimal("148.90000000")
    assert mark.funding_rate == Decimal("0.00010000")
    assert mark.next_funding_time == datetime.fromtimestamp(1726934400000 / 1000.0, tz=UTC)


def test_float_input_rejected_in_models() -> None:
    # OrderBookLevel must reject float
    with pytest.raises(ValueError, match="forbidden"):
        OrderBookLevel(price=65000.5, quantity=Decimal("1.0"))  # type: ignore[arg-type]

    # AggregateTrade must reject float
    now_utc = datetime.now(UTC)
    with pytest.raises(ValueError, match="forbidden"):
        AggregateTrade(
            symbol="BTCUSDT",
            aggregate_trade_id=1,
            price=65000.5,  # type: ignore[arg-type]
            quantity=Decimal("1.0"),
            trade_time=now_utc,
            is_buyer_maker=False,
        )


# =====================================================================
# 2. Sequencer & Deduplication Tests
# =====================================================================


def test_sequencer_depth_processing_and_deduplication() -> None:
    sequencer = PublicMarketStreamSequencer()

    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=100)
    assert is_dup is False
    assert is_gap is False

    # Duplicate or stale update (u <= 100)
    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=100)
    assert is_dup is True
    assert is_gap is False

    # Gap detection: last_u was 100, next snap claims prev was 105
    is_dup, is_gap = sequencer.check_depth("BTCUSDT", u=110, pu=105)
    assert is_dup is False
    assert is_gap is True
    assert sequencer.sequence_gap_count == 1
    assert sequencer.duplicate_count == 1


def test_sequencer_agg_trade_deduplication() -> None:
    sequencer = PublicMarketStreamSequencer()

    assert sequencer.check_agg_trade("BTCUSDT", a=501) is False
    # Duplicate trade ID
    assert sequencer.check_agg_trade("BTCUSDT", a=501) is True
    assert sequencer.duplicate_count == 1

    # New trade ID
    assert sequencer.check_agg_trade("BTCUSDT", a=502) is False


def test_sequencer_mark_price_deduplication() -> None:
    sequencer = PublicMarketStreamSequencer()

    assert sequencer.check_mark_price("SOLUSDT", event_time_ms=1726912800000) is False
    # Duplicate with same event_time_ms
    assert sequencer.check_mark_price("SOLUSDT", event_time_ms=1726912800000) is True
    assert sequencer.duplicate_count == 1


# =====================================================================
# 3. Client Backoff, Reconnection & Server Time Sync
# =====================================================================


def test_client_backoff_curve_and_jitter() -> None:
    client = BinancePublicFeedClient(symbols=["BTCUSDT"])

    # Base: 0.5s, 2x multiplier, 8.0s ceiling, +0.1..0.4s jitter
    d0 = client.compute_backoff_delay(attempt=0, jitter=0.2)
    assert d0 == pytest.approx(0.5 + 0.2)

    d1 = client.compute_backoff_delay(attempt=1, jitter=0.2)
    assert d1 == pytest.approx(0.5 + 0.2)

    d2 = client.compute_backoff_delay(attempt=2, jitter=0.2)
    assert d2 == pytest.approx(1.0 + 0.2)

    d3 = client.compute_backoff_delay(attempt=3, jitter=0.2)
    assert d3 == pytest.approx(2.0 + 0.2)

    d4 = client.compute_backoff_delay(attempt=4, jitter=0.2)
    assert d4 == pytest.approx(4.0 + 0.2)

    d5 = client.compute_backoff_delay(attempt=5, jitter=0.2)
    assert d5 == pytest.approx(8.0 + 0.2)

    # Reaches ceiling at 8.0 + jitter
    d10 = client.compute_backoff_delay(attempt=10, jitter=0.3)
    assert d10 == pytest.approx(8.0 + 0.3)


def test_client_server_time_sync_mock() -> None:
    client = BinancePublicFeedClient(symbols=["BTCUSDT"])

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"serverTime": 1726912800500}
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        skew = asyncio.run(client.sync_server_time())
        assert client.clock_skew_ms == skew
        assert isinstance(skew, float)


# =====================================================================
# 4. Strict Paper-Safe Invariants
# =====================================================================


def test_strict_read_only_invariants() -> None:
    # Confirm client has no private key parameters
    client = BinancePublicFeedClient(symbols=["BTCUSDT"])
    assert not hasattr(client, "api_key") or getattr(client, "api_key", None) is None
    assert not hasattr(client, "api_secret") or getattr(client, "api_secret", None) is None


# =====================================================================
# 5. Verification Runner Execution & Schema Persistence
# =====================================================================


def test_verification_runner_offline_execution(tmp_path: Path) -> None:
    out_dir = tmp_path / "phase292_test"
    res = run_phase_292_live_ingress(
        output_dir=out_dir,
        offline_replay=True,
        candidates=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    )

    assert res["status"] == "PASS"
    assert res["zero_balance_drift"] is True
    assert (out_dir / "canary-market-telemetry.sqlite3").is_file()
    assert (out_dir / "canary-live-market-report.json").is_file()
    assert (out_dir / "live-market-summary.json").is_file()
    assert (out_dir / "paper-summary.json").is_file()

    # Verify SHA-256 DAG hash chain
    summary_data = verify_canary_phase_integrity(out_dir)
    assert summary_data["phase"] == "phase_292"
    assert summary_data["zero_balance_drift"] is True

    # Test API loader
    api_model = load_verified_canary_live_market(out_dir)
    assert api_model.verified is True
    assert api_model.phase == "phase_292"
    assert api_model.paper_safe is True
    assert api_model.execution_authority is False
    assert set(api_model.candidates) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert "BTCUSDT" in api_model.orderbooks
    assert len(api_model.recent_trades) >= 1
    assert "BTCUSDT" in api_model.mark_prices
    assert api_model.gateway_health.is_healthy is True


def test_tampered_hash_chain_fails_integrity(tmp_path: Path) -> None:
    out_dir = tmp_path / "phase292_tampered"
    run_phase_292_live_ingress(
        output_dir=out_dir,
        offline_replay=True,
    )

    # Tamper with sqlite3 db
    db_file = out_dir / "canary-market-telemetry.sqlite3"
    db_file.write_bytes(db_file.read_bytes() + b"\x00")

    with pytest.raises(CanaryEvidenceIntegrityError, match="Hash mismatch"):
        verify_canary_phase_integrity(out_dir)

    with pytest.raises(CanaryEvidenceIntegrityError):
        load_verified_canary_live_market(out_dir)
