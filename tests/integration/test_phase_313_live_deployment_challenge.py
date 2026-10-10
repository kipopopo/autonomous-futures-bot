"""Empirical Challenger Suite: Live Deployment Verification for Phase 313.

Targets:
- https://futures.semua.dev/api/v1/execution/status
- https://futures.semua.dev/
- Production JS Bundle (/assets/index-*.js)

Tests:
1. HTTP 200 OK on /api/v1/execution/status
2. aggregate_exposure_usdt == 0.0
3. solvency.cash_reserve_pct == 100.0 & zero drift
4. Candidate positions (BTC, ETH, SOL) in STANDBY / SCANNING with 0.0 qty
5. recent_orders: contains authentic Phase 310/311 drill orders and 0 ord-p309- orders
6. Frontend root HTTP 200 OK
7. Production JS bundle contains 5th tab `🧠 Pembelajaran & Autopsi` (`#/evolution`)
   and Strategy Evolution Radar components.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

import pytest

BASE_URL = "https://futures.semua.dev"


def _http_get(url: str, timeout: float = 10.0) -> tuple[int, dict[str, str], str]:
    """Perform an HTTP GET request with standard headers."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "EmpiricalChallenger/Phase313",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        code = resp.getcode()
        headers = dict(resp.headers)
        body = resp.read().decode("utf-8", errors="replace")
        return code, headers, body


class TestLiveDeploymentExecutionStatus:
    """Empirical challenge against live /api/v1/execution/status."""

    def test_execution_status_http_200(self) -> None:
        url = f"{BASE_URL}/api/v1/execution/status?_cb={int(time.time() * 1000)}"
        code, headers, body = _http_get(url)
        assert code == 200, f"Expected 200 OK, got {code}"
        assert "application/json" in headers.get("Content-Type", "").lower()
        data = json.loads(body)
        assert isinstance(data, dict)
        assert data.get("verified") is True

    def test_aggregate_exposure_zero(self) -> None:
        url = f"{BASE_URL}/api/v1/execution/status"
        code, _, body = _http_get(url)
        assert code == 200
        data = json.loads(body)
        exposure = data.get("aggregate_exposure_usdt")
        assert exposure == 0.0, f"Expected aggregate_exposure_usdt == 0.0, got {exposure}"

    def test_solvency_cash_reserve_full_and_zero_drift(self) -> None:
        url = f"{BASE_URL}/api/v1/execution/status"
        code, _, body = _http_get(url)
        assert code == 200
        data = json.loads(body)
        solvency = data.get("solvency", {})
        assert isinstance(solvency, dict)
        assert solvency.get("cash_reserve_pct") == 100.0, (
            f"Expected cash_reserve_pct == 100.0, got {solvency.get('cash_reserve_pct')}"
        )
        assert solvency.get("cash_usdt") == 100.0
        assert solvency.get("allocated_margin_usdt") == 0.0
        assert solvency.get("unrealized_pnl_usdt") == 0.0
        assert solvency.get("drift_usdt") == 0.0
        assert solvency.get("zero_balance_drift_verified") is True
        assert solvency.get("unencumbered_cash_verified") is True

    def test_candidate_positions_standby_scanning_zero_qty(self) -> None:
        url = f"{BASE_URL}/api/v1/execution/status"
        code, _, body = _http_get(url)
        assert code == 200
        data = json.loads(body)
        positions = data.get("positions", {})
        assert isinstance(positions, dict)
        expected_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        for sym in expected_symbols:
            assert sym in positions, f"Missing symbol {sym} in positions"
            pos = positions[sym]
            assert pos.get("position_qty") == 0.0, (
                f"Expected {sym} position_qty == 0.0, got {pos.get('position_qty')}"
            )
            assert pos.get("allocated_exposure_usdt") == 0.0
            assert pos.get("state") == "STANDBY / SCANNING"
            assert pos.get("status") == "STANDBY / SCANNING"
            assert pos.get("allocated_margin_usdt") == 0.0
            assert pos.get("unrealized_pnl_usdt") == 0.0

    def test_recent_orders_authenticity_and_no_p309(self) -> None:
        url = f"{BASE_URL}/api/v1/execution/status"
        code, _, body = _http_get(url)
        assert code == 200
        data = json.loads(body)
        recent_orders = data.get("recent_orders", [])
        assert isinstance(recent_orders, list)
        assert len(recent_orders) > 0, "recent_orders should not be empty"

        # Assert zero ord-p309 orders
        p309_matches = [
            o for o in recent_orders if "ord-p309" in str(o.get("client_order_id", ""))
        ]
        assert len(p309_matches) == 0, f"Found stale p309 orders: {p309_matches}"

        # Assert authentic Phase 310 or 311 drill orders
        for o in recent_orders:
            cid = str(o.get("client_order_id", ""))
            assert "p310" in cid or "p311" in cid, (
                f"Order {cid} is neither Phase 310 nor Phase 311"
            )
            assert o.get("symbol") in ["SOLUSDT", "ETHUSDT", "BTCUSDT"]
            assert o.get("side") in ["BUY", "SELL"]

        # Assert sorted in descending chronological order
        timestamps = [o.get("timestamp_ms", 0) for o in recent_orders]
        assert timestamps == sorted(timestamps, reverse=True), (
            f"Recent orders are not sorted newest first: {timestamps}"
        )


class TestLiveFrontendBundleAndNavigation:
    """Empirical challenge against live frontend index.html and production JS bundle."""

    def test_frontend_index_http_200(self) -> None:
        url = f"{BASE_URL}/"
        code, headers, body = _http_get(url)
        assert code == 200, f"Expected 200 OK, got {code}"
        assert "<html" in body.lower()
        assert "<script" in body.lower()

    def test_frontend_js_bundle_contains_pembelajaran_and_radar(self) -> None:
        url = f"{BASE_URL}/"
        code, _, html = _http_get(url)
        assert code == 200

        # Find JS bundles in script tags
        script_paths = re.findall(r'src=["\']([^"\']+\.js)["\']', html)
        assert len(script_paths) > 0, "No JavaScript bundle found in index.html"

        bundle_checked = False
        for path in script_paths:
            full_js_url = BASE_URL.rstrip("/") + "/" + path.lstrip("/")
            js_code, _, js_content = _http_get(full_js_url)
            assert js_code == 200, f"Failed to fetch bundle {full_js_url}"

            # Only inspect primary application bundle (size > 100KB)
            if len(js_content) > 100_000:
                bundle_checked = True

                # Assert 5th navigation tab references
                assert "#/evolution" in js_content or "#evolution" in js_content, (
                    "Missing #/evolution route in production JS bundle"
                )
                assert "Pembelajaran & Autopsi" in js_content, (
                    "Missing 'Pembelajaran & Autopsi' tab title in production JS bundle"
                )

                # Assert Strategy Evolution Radar component references
                assert "Status Pembelajaran & Autopsi Strategi" in js_content, (
                    "Missing 'Status Pembelajaran & Autopsi Strategi' header in bundle"
                )

                # Assert that sanitization filter is active in bundle
                assert "ord-p309-" in js_content, "Sanitization filter for ord-p309- missing in bundle"

                # Check Walk-Forward OOS Gates or related telemetry
                assert "OOS" in js_content or "Walk-Forward" in js_content or "Mining" in js_content, (
                    "Missing OOS or Mining references in production JS bundle"
                )
                print(f"\n[Bundle Verified] {full_js_url} (size: {len(js_content):,} bytes)")
                print("  - Route #/evolution: FOUND")
                print("  - Tab 'Pembelajaran & Autopsi': FOUND")
                print("  - Header 'Status Pembelajaran & Autopsi Strategi': FOUND")
                print("  - ord-p309- filter guard: ACTIVE")

        assert bundle_checked, "Did not encounter the main app JS bundle"


class TestLiveApiAuxiliaryEndpoints:
    """Adversarial stress against related live endpoints."""

    def test_market_klines_endpoint(self) -> None:
        url = f"{BASE_URL}/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=10"
        code, _, body = _http_get(url)
        assert code == 200
        data = json.loads(body)
        assert isinstance(data, dict)
        assert data.get("source") == "binance_futures_live"
        candles = data.get("candles", [])
        assert isinstance(candles, list)
        assert len(candles) > 0
        candle = candles[0]
        for key in ["timestamp", "open", "high", "low", "close", "volume"]:
            assert key in candle

    def test_canary_summary_consistency(self) -> None:
        url = f"{BASE_URL}/api/v1/canary/summary"
        code, _, body = _http_get(url)
        assert code == 200
        data = json.loads(body)
        assert isinstance(data, dict)


class TestLiveAdversarialStress:
    """Adversarial stress harness attacking live deployment boundaries."""

    def test_concurrent_execution_status_burst(self) -> None:
        """Fires 10 concurrent requests to test for race conditions or lock contention."""
        import concurrent.futures

        def _fetch(i: int) -> int:
            url = f"{BASE_URL}/api/v1/execution/status?burst={i}"
            c, _, _ = _http_get(url, timeout=5.0)
            return c

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_fetch, i) for i in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert all(r == 200 for r in results), f"Expected all 200 OK under burst, got {results}"

    def test_unexpected_query_params_sanitization(self) -> None:
        """Sends adversarial query parameters to verify robust parameter parsing."""
        url = f"{BASE_URL}/api/v1/execution/status?symbol=%3Cscript%3Ealert(1)%3C/script%3E&null=%00"
        code, _, body = _http_get(url)
        assert code == 200
        assert "<script>" not in body
        data = json.loads(body)
        assert data.get("verified") is True

    def test_post_disallowed_on_read_only_endpoint(self) -> None:
        """Verifies read-only status endpoint rejects mutative POST requests with 405."""
        req = urllib.request.Request(
            f"{BASE_URL}/api/v1/execution/status",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                status_code = resp.getcode()
        except urllib.error.HTTPError as e:
            status_code = e.code

        assert status_code in (403, 405), f"Expected 403/405 rejection, got {status_code}"
