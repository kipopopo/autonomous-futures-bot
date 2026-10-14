from types import SimpleNamespace

from scripts.probe_persistent_market_feed import _source_routes


def test_probe_source_routes_record_market_and_public_depth_endpoints() -> None:
    feed = SimpleNamespace(
        market_endpoint="wss://testnet.binance.example/market/stream",
        public_endpoint="wss://testnet.binance.example/public/stream",
    )

    assert _source_routes(feed) == {
        "market": "wss://testnet.binance.example/market/stream",
        "public_depth": "wss://testnet.binance.example/public/stream",
    }
