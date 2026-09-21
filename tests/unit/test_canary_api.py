from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from fastapi import FastAPI

from autonomous_futures.api import create_app


def _request(app: FastAPI, method: str, path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(send())


PHASE_291_DIR = Path("artifacts/research/phase291")


def test_canary_endpoints_with_valid_phase_291() -> None:
    app = create_app(canary_phase_dir=PHASE_291_DIR)

    # 1. Summary Endpoint
    res_sum = _request(app, "GET", "/api/v1/canary/summary")
    assert res_sum.status_code == 200
    sum_data = res_sum.json()
    assert sum_data["verified"] is True
    assert sum_data["phase"] == "phase_291"
    assert sum_data["daemon_status"] == "HAWKES_CASCADES_VERIFIED"
    assert sum_data["candidates"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert sum_data["circuit_state"] == "NORMAL"
    assert sum_data["compliance"]["zero_balance_drift"] is True
    assert sum_data["compliance"]["read_only_safety_compliant"] is True

    # 2. Hawkes Endpoint
    res_hwk = _request(app, "GET", "/api/v1/canary/hawkes")
    assert res_hwk.status_code == 200
    hwk_data = res_hwk.json()
    assert hwk_data["verified"] is True
    assert hwk_data["phase"] == "phase_291"
    assert len(hwk_data["snapshots"]) >= 5
    assert hwk_data["max_spectral_radius"] > 0
    assert hwk_data["candidates"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    # 3. Risk Endpoint
    res_risk = _request(app, "GET", "/api/v1/canary/risk")
    assert res_risk.status_code == 200
    risk_data = res_risk.json()
    assert risk_data["verified"] is True
    assert risk_data["aggregate_exposure_cap_usdt"] == "60.00"
    assert risk_data["individual_micro_notional_cap_usdt"] == "5.00"
    assert risk_data["intra_phase_loss_ceiling_usdt"] == "7.0"
    assert len(risk_data["heartbeats"]) >= 4
    assert len(risk_data["interlock_events"]) >= 10
    assert risk_data["total_interlock_blocks"] >= 1

    # 4. Accounting Endpoint
    res_acc = _request(app, "GET", "/api/v1/canary/accounting")
    assert res_acc.status_code == 200
    acc_data = res_acc.json()
    assert acc_data["verified"] is True
    assert acc_data["drift_usdt"] == "0E-8"
    assert acc_data["zero_balance_drift"] is True
    assert len(acc_data["tracks"]) == 4
    assert len(acc_data["recent_balance_snapshots"]) >= 20
    assert acc_data["starting_capital_usdt"] == "100.00"
    assert acc_data["final_cash_usdt"] == "99.99460000"


def test_canary_endpoints_missing_phase_fails_404(tmp_path: Path) -> None:
    app = create_app(canary_phase_dir=tmp_path / "non_existent_phase")

    assert _request(app, "GET", "/api/v1/canary/summary").status_code == 404
    assert _request(app, "GET", "/api/v1/canary/hawkes").status_code == 404
    assert _request(app, "GET", "/api/v1/canary/risk").status_code == 404
    assert _request(app, "GET", "/api/v1/canary/accounting").status_code == 404


def test_canary_endpoints_tampered_artifact_fails_503(tmp_path: Path) -> None:
    phase_dir = tmp_path / "tampered_phase"
    phase_dir.mkdir()

    # Create dummy summary referencing another file with invalid hash
    (phase_dir / "target.txt").write_text("legitimate content", encoding="utf-8")
    summary = {
        "artifact_hashes": {
            "target.txt": "deadbeef" * 8,
        },
        "phase": "tampered",
    }
    (phase_dir / "hawkes-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    app = create_app(canary_phase_dir=phase_dir)
    res = _request(app, "GET", "/api/v1/canary/summary")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]
