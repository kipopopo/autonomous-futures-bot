"""Empirical Challenger Test Suite for Phase 316 Milestone M1.

Challenger instance: teamwork_preview_challenger (challenger_m1_2)
Mission: Empirically stress-test schema backward-compatibility, concurrent API serialization,
and JSON serialization integrity for `src/autonomous_futures/api/canary.py`.

Requirements verified:
1. JSON serialization/deserialization compatibility (`json.dumps(res.model_dump())`).
2. Schema retention: `explanation_ms` key exists and is non-empty string in all serialized objects.
3. Concurrent requests safety: 50 parallel requests to `/canary/evolution` and `/canary/summary`.
4. Latency benchmarks: response latency is low (< 100ms) with zero data races or exceptions.
5. English localization integrity: zero residual Malay tokens in serialized API payloads.
"""

from __future__ import annotations

import concurrent.futures
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryAutoEvolutionResponse,
    MacroGatingStateItem,
    _build_macro_gating_state,
    load_verified_canary_auto_evolution,
)

BANNED_MALAY_TOKENS = [
    "penapis",
    "kemasukan",
    "posisi",
    "beli",
    "dibenarkan",
    "ditangguhkan",
    "sementara",
    "kerana",
    "melindungi",
    "rejim",
    "keadaan",
    "menunggu",
    "sampel",
    "transaksi",
    "selesai",
    "menguji",
    "semasa",
    "melepasi",
    "menilai",
    "promosi",
    "bayangan",
    "sedang",
    "diuji",
    "terhadap",
    "peningkatan",
    "degupan",
    "jantung",
    "pasaran",
    "penstriman",
    "disegerakkan",
    "pasangan",
    "lejar",
    "dwi-kemasukan",
    "berterusan",
    "baki",
    "disahkan",
    "sifar",
    "matematis",
    "penilaian",
    "kesihatan",
    "dinilai",
    "diarahkan",
    "mutasi",
    "dijana",
    "kelayakan",
    "diperoleh",
]


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    app = create_app()
    client = TestClient(app)
    # Warm up client and routes
    _ = client.get("/api/v1/canary/evolution")
    _ = client.get("/api/v1/canary/summary")
    return client


def test_json_serialization_roundtrip_compatibility() -> None:
    """Test full JSON serialization and deserialization roundtrip on CanaryAutoEvolutionResponse."""
    res = load_verified_canary_auto_evolution()
    assert isinstance(res, CanaryAutoEvolutionResponse)

    dumped = res.model_dump()
    assert isinstance(dumped, dict)

    # Validate strict RFC 8259 JSON serialization (no NaN / Infinity allowed)
    json_str = json.dumps(dumped, allow_nan=False)
    assert len(json_str) > 0

    reloaded = json.loads(json_str)
    assert isinstance(reloaded, dict)

    # Validate model reconstruction from deserialized JSON
    validated_model = CanaryAutoEvolutionResponse.model_validate(reloaded)
    assert validated_model.phase == res.phase
    assert validated_model.status == res.status
    assert validated_model.solvency.drift_usdt == res.solvency.drift_usdt
    assert validated_model.solvency.zero_balance_drift_verified is True
    assert validated_model.live_progress.daemon_pid == 87549


def test_explanation_ms_backward_compatibility_and_non_empty() -> None:
    """Validate that explanation_ms exists and is a non-empty string in all macro gating states."""
    # 1. Default model instance
    default_item = MacroGatingStateItem()
    assert hasattr(default_item, "explanation_ms")
    assert isinstance(default_item.explanation_ms, str)
    assert len(default_item.explanation_ms.strip()) > 0
    assert "Active BTC Macro Trend Filter" in default_item.explanation_ms
    assert "explanation_ms" in default_item.model_dump()

    # 2. Bullish regime
    bullish_item = _build_macro_gating_state("BULLISH")
    assert "explanation_ms" in bullish_item.model_dump()
    assert isinstance(bullish_item.explanation_ms, str)
    assert len(bullish_item.explanation_ms.strip()) > 0
    assert "Bullish Aligned" in bullish_item.explanation_ms
    assert "permitted" in bullish_item.explanation_ms

    # 3. Bearish regime
    bearish_item = _build_macro_gating_state("BEARISH")
    assert "explanation_ms" in bearish_item.model_dump()
    assert isinstance(bearish_item.explanation_ms, str)
    assert len(bearish_item.explanation_ms.strip()) > 0
    assert "Bearish regime" in bearish_item.explanation_ms
    assert "temporarily paused" in bearish_item.explanation_ms

    # 4. Neutral / Sideways regime
    neutral_item = _build_macro_gating_state("NEUTRAL")
    assert "explanation_ms" in neutral_item.model_dump()
    assert isinstance(neutral_item.explanation_ms, str)
    assert len(neutral_item.explanation_ms.strip()) > 0
    assert "Neutral/Sideways regime" in neutral_item.explanation_ms

    # 5. In live response
    res = load_verified_canary_auto_evolution()
    res_dump = res.model_dump()
    macro_state = res_dump["live_progress"]["macro_gating_state"]
    assert "explanation_ms" in macro_state
    assert isinstance(macro_state["explanation_ms"], str)
    assert len(macro_state["explanation_ms"].strip()) > 0


def test_zero_residual_malay_tokens_in_serialized_payload(api_client: TestClient) -> None:
    """Empirically prove zero residual Malay tokens in serialized canary evolution API response."""
    response = api_client.get("/api/v1/canary/evolution")
    assert response.status_code == 200
    payload_text = response.text.lower()

    found_tokens: list[str] = []
    for token in BANNED_MALAY_TOKENS:
        if token in payload_text:
            found_tokens.append(token)

    assert not found_tokens, f"Found residual Malay tokens in /canary/evolution: {found_tokens}"


def test_concurrent_api_requests_evolution_50_parallel(api_client: TestClient) -> None:
    """Empirically stress-test 50 parallel requests to /api/v1/canary/evolution."""
    request_count = 50

    def _fetch_evolution(idx: int) -> dict[str, Any]:
        t0 = time.perf_counter()
        resp = api_client.get("/api/v1/canary/evolution")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert resp.status_code == 200, f"Request {idx} failed with {resp.status_code}"
        data = resp.json()
        assert "live_progress" in data
        assert data["solvency"]["drift_usdt"] == 0.0
        assert data["live_progress"]["daemon_pid"] == 87549
        assert "explanation_ms" in data["live_progress"]["macro_gating_state"]
        return {"idx": idx, "latency_ms": elapsed_ms, "data": data}

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(_fetch_evolution, i) for i in range(request_count)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == request_count
    # Verify zero data races: all responses returned identical phase and zero-drift solvency
    for r in results:
        assert r["data"]["phase"] == "phase_306"
        assert r["data"]["solvency"]["zero_balance_drift_verified"] is True


def test_concurrent_api_requests_summary_50_parallel(api_client: TestClient) -> None:
    """Empirically stress-test 50 parallel requests to /api/v1/canary/summary."""
    request_count = 50

    def _fetch_summary(idx: int) -> dict[str, Any]:
        t0 = time.perf_counter()
        resp = api_client.get("/api/v1/canary/summary")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert resp.status_code == 200, f"Request {idx} failed with {resp.status_code}"
        data = resp.json()
        assert data["verified"] is True
        return {"idx": idx, "latency_ms": elapsed_ms, "data": data}

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(_fetch_summary, i) for i in range(request_count)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == request_count


def test_concurrent_interleaved_requests_stress(api_client: TestClient) -> None:
    """Stress-test 100 concurrent requests interleaved between /evolution and /summary."""
    total_requests = 100
    endpoints = ["/api/v1/canary/evolution", "/api/v1/canary/summary"]

    def _fetch_endpoint(idx: int) -> int:
        endpoint = endpoints[idx % 2]
        resp = api_client.get(endpoint)
        assert resp.status_code == 200
        return int(resp.status_code)

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        futures = [executor.submit(_fetch_endpoint, i) for i in range(total_requests)]
        codes = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(codes) == total_requests
    assert all(code == 200 for code in codes)


def test_sequential_api_latency_below_100ms(api_client: TestClient) -> None:
    """Measure sequential API response latencies to confirm baseline latency is well below 100ms."""
    evo_latencies: list[float] = []
    for _ in range(30):
        t0 = time.perf_counter()
        resp = api_client.get("/api/v1/canary/evolution")
        lat = (time.perf_counter() - t0) * 1000.0
        assert resp.status_code == 200
        evo_latencies.append(lat)

    sum_latencies: list[float] = []
    for _ in range(30):
        t0 = time.perf_counter()
        resp = api_client.get("/api/v1/canary/summary")
        lat = (time.perf_counter() - t0) * 1000.0
        assert resp.status_code == 200
        sum_latencies.append(lat)

    avg_evo = sum(evo_latencies) / len(evo_latencies)
    avg_sum = sum(sum_latencies) / len(sum_latencies)

    # Confirm average latency is strictly under 100ms
    assert avg_evo < 100.0, f"Average evolution latency {avg_evo:.2f}ms exceeds 100ms"
    assert avg_sum < 100.0, f"Average summary latency {avg_sum:.2f}ms exceeds 100ms"


def test_adversarial_regime_fuzzing_and_schema_retention() -> None:
    """Adversarially fuzz regime inputs to ensure explanation_ms never vanishes or breaks schema."""
    adversarial_inputs = [
        "",
        "   ",
        "bullish",
        "BEARISH",
        "nEuTrAl",
        "TRANSITIONAL",
        "EXTREME_VOLATILITY",
        "CRASH_RISK",
        "!@#$%^&*()_+",
        "SELECT * FROM trades;",
        "<script>alert(1)</script>",
        "中文测试",
        "A" * 1000,
    ]

    for regime_input in adversarial_inputs:
        state = _build_macro_gating_state(regime_input)
        assert isinstance(state, MacroGatingStateItem)
        assert hasattr(state, "explanation_ms")
        assert isinstance(state.explanation_ms, str)
        assert len(state.explanation_ms.strip()) > 0

        # Validate that serialization roundtrips cleanly without JSON error
        dumped = state.model_dump()
        assert "explanation_ms" in dumped
        json_output = json.dumps(dumped)
        reloaded = json.loads(json_output)
        assert reloaded["explanation_ms"] == state.explanation_ms


def test_continuous_solvency_invariant_across_simulated_cycles() -> None:
    """Verify that solvency zero-drift invariant holds across multiple simulated cycles."""
    for cycle_sec in range(15):
        sim_ms = 1710000000000 + cycle_sec * 1000
        res = load_verified_canary_auto_evolution(simulated_timestamp_ms=sim_ms)
        assert res.solvency.drift_usdt == 0.0
        assert res.solvency.zero_balance_drift_verified is True
        assert abs(res.solvency.drift_usdt) < 1e-15
