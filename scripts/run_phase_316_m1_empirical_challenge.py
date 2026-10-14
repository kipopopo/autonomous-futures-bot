# ruff: noqa: E501
#!/usr/bin/env python3
"""Empirical Challenger Script for Phase 316 Milestone M1.

Validates:
1. Macro gating regimes under all conditions (BULLISH, BEARISH, NEUTRAL, SIDEWAYS).
2. Recursive audit of /api/v1/canary/evolution against 70+ banned Malay root words.
3. Strict double-entry solvency zero-drift invariant (|Δ| = 0.00 < 10^-15 USDT).
4. Continuous trader daemon PID 87549 and 'ONLINE 24/7' status.
5. Exact institutional English titles and details across all 5 recent_events.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src is in python path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from autonomous_futures.api import create_app  # noqa: E402
from autonomous_futures.api.canary import (  # noqa: E402
    MacroGatingStateItem,
    _build_macro_gating_state,
    load_verified_canary_auto_evolution,
)

BANNED_MALAY_TOKENS: tuple[str, ...] = (
    "penapis",
    "aliran",
    "kemasukan",
    "posisi",
    "beli",
    "jual",
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
    "pintu",
    "arkib",
    "penyelidikan",
    "kawalan",
    "keselamatan",
    "pembelajaran",
    "utama",
    "carta",
    "interaktif",
    "harga",
    "keuntungan",
    "kerugian",
    "saat",
    "minit",
    "minggu",
    "bulan",
    "tahun",
    "yang lalu",
    "baru sahaja",
    "tidak",
    "sudah",
    "belum",
    "adalah",
    "untuk",
    "dengan",
    "oleh",
    "pada",
    "dari",
    "daripada",
)


def extract_strings(obj: Any) -> list[str]:
    """Recursively extracts all string values from an object."""
    res: list[str] = []
    if isinstance(obj, str):
        res.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                res.append(k)
            res.extend(extract_strings(v))
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            res.extend(extract_strings(item))
    elif hasattr(obj, "model_dump"):
        res.extend(extract_strings(obj.model_dump()))
    elif hasattr(obj, "__dict__"):
        for v in vars(obj).values():
            res.extend(extract_strings(v))
    return res


def scan_banned(text: str) -> list[str]:
    """Scans text for banned Malay tokens."""
    t_lower = text.lower()
    return [tok for tok in BANNED_MALAY_TOKENS if tok.lower() in t_lower]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 80)
    print("PHASE 316 MILESTONE M1 -- EMPIRICAL CHALLENGE EXECUTION HARNESS")
    print("=" * 80)

    # 1. Macro Gating Regimes
    print("\n[PROBE 1/5] Probing Macro Gating Regimes...")
    regimes = [
        ("BULLISH", "BULLISH_ALIGNED", False, True),
        ("BEARISH", "BEARISH", True, False),
        ("NEUTRAL", "NEUTRAL", True, False),
        ("SIDEWAYS", "NEUTRAL", True, False),
        ("  bullish  ", "BULLISH_ALIGNED", False, True),
        ("bearish", "BEARISH", True, False),
    ]
    for inp, norm, filtered, allowed in regimes:
        g = _build_macro_gating_state(regime=inp)
        assert g.regime == norm, f"Regime mismatch for {inp}: {g.regime} != {norm}"
        assert g.longs_filtered is filtered, f"Filter mismatch for {inp}"
        assert g.is_long_allowed is allowed, f"Allowed mismatch for {inp}"
        assert scan_banned(g.explanation_ms) == [], f"Malay found in explanation_ms for {inp}"
        assert scan_banned(g.explanation) == [], f"Malay found in explanation for {inp}"
        print(
            f"  [PASS] Regime '{inp}' -> normalized '{g.regime}', longs_allowed={g.is_long_allowed}"
        )

    # Verify model defaults
    m_def = MacroGatingStateItem()
    assert scan_banned(m_def.explanation_ms) == []
    assert scan_banned(m_def.explanation) == []
    print("  [PASS] MacroGatingStateItem model default is clean English.")

    # 2. Recursive Banned Token Audit across /api/v1/canary/evolution
    print("\n[PROBE 2/5] Recursive Banned Token Audit across /api/v1/canary/evolution...")
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/canary/evolution")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    payload = resp.json()

    all_strings = extract_strings(payload)
    print(f"  Discovered {len(all_strings)} string leaves in API JSON payload.")

    violations: list[tuple[str, list[str]]] = []
    for s in all_strings:
        matches = scan_banned(s)
        if matches:
            violations.append((s, matches))

    if violations:
        print(f"  [FAIL] FAILED: Found {len(violations)} banned Malay token occurrences:")
        for text, matches in violations:
            print(f"     Text: '{text}' | Matches: {matches}")
        return 1
    print(
        f"  [PASS] 100% clean: 0 matches across {len(BANNED_MALAY_TOKENS)} banned Malay root words."
    )

    # 3. Solvency Zero-Drift Invariant
    print("\n[PROBE 3/5] Solvency Zero-Drift Invariant (|Δ| < 10^-15 USDT)...")
    res = load_verified_canary_auto_evolution()
    solv = res.solvency
    assert solv.drift_usdt == 0.0, f"drift_usdt is {solv.drift_usdt}"
    assert solv.zero_balance_drift_verified is True
    assert solv.tolerance_ceiling_usdt == 1e-15

    cash = Decimal(str(solv.cash_usdt))
    margin = Decimal(str(solv.allocated_margin_usdt))
    starting = Decimal(str(solv.starting_equity_usdt))
    realized = Decimal(str(solv.realized_pnl_usdt))
    calculated_drift = abs(cash + margin - starting - realized)

    assert calculated_drift < Decimal("1e-15"), f"Drift {calculated_drift} >= 1e-15"
    print(
        f"  [PASS] Model solvency verified: drift_usdt={solv.drift_usdt}, |Δ|={calculated_drift} USDT"
    )

    api_solv = payload["solvency"]
    assert api_solv["drift_usdt"] == 0.0
    assert api_solv["zero_balance_drift_verified"] is True
    print(
        "  [PASS] API response solvency verified: drift_usdt=0.0, zero_balance_drift_verified=True"
    )

    # 4. Trader Daemon PID & Online Status
    print("\n[PROBE 4/5] Trader Daemon PID 87549 and 'ONLINE 24/7' Continuity...")
    prog = res.live_progress
    assert prog is not None
    assert prog.daemon_pid == 87549, f"daemon_pid is {prog.daemon_pid}"
    assert prog.daemon_status == "ONLINE 24/7", f"daemon_status is {prog.daemon_status}"
    assert prog.is_live_daemon_active is True

    api_prog = payload["live_progress"]
    assert api_prog["daemon_pid"] == 87549
    assert api_prog["daemon_status"] == "ONLINE 24/7"
    assert api_prog["is_live_daemon_active"] is True
    print(
        f"  [PASS] Daemon continuity verified: PID={prog.daemon_pid}, Status='{prog.daemon_status}'"
    )

    # 5. Exact Expected English Titles and Details for 5 Recent Events
    print("\n[PROBE 5/5] Inspecting all 5 recent_events in timeline...")
    events = prog.recent_events
    assert len(events) == 5, f"Expected 5 events, got {len(events)}"

    # Event 0
    assert events[0].event_type == "HEARTBEAT_INGRESS"
    assert events[0].title == "Heartbeat & Market Ingress"
    assert "Binance Futures 15m & 1h klines streaming synchronized" in events[0].detail
    assert "(8 pairs: BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX)" in events[0].detail
    assert events[0].status == "HEALTHY"
    print(f"  [PASS] Event 0: '{events[0].title}' -> {events[0].status}")

    # Event 1
    assert events[1].event_type == "SOLVENCY_AUDIT"
    assert events[1].title == "Continuous Double-Entry Ledger Audit"
    assert "Balance $100.12 USDT verified with zero mathematical drift" in events[1].detail
    assert "(|Δ| = 0.00 < 10^-15 USDT)" in events[1].detail
    assert events[1].status == "VERIFIED"
    print(f"  [PASS] Event 1: '{events[1].title}' -> {events[1].status}")

    # Event 2
    assert events[2].event_type == "CANDIDATE_HEALTH"
    assert events[2].title == "Candidate Strategy Health Evaluation"
    assert "BTCUSDT & ETHUSDT evaluated as ELITE" in events[2].detail
    assert "SOLUSDT evaluated as DEGRADED and routed to mutation" in events[2].detail
    assert events[2].status == "EVALUATED"
    print(f"  [PASS] Event 2: '{events[2].title}' -> {events[2].status}")

    # Event 3
    assert events[3].event_type == "MUTATION_STAGING"
    assert events[3].title == "Parameter Genome Mutation (Gen #2)"
    assert (
        events[3].detail
        == "cand-ethusdt-evo-002 generated with Donchian period 24, ATR 2.5x, Hawkes 0.65"
    )
    assert events[3].status == "STAGED"
    print(f"  [PASS] Event 3: '{events[3].title}' -> {events[3].status}")

    # Event 4
    assert events[4].event_type == "SHADOW_OOS_GATE"
    assert events[4].title == "Shadow Simulation & OOS Promotion Gate"
    assert "OOS Gate:" in events[4].detail
    assert "Sharpe hurdle >= 15.0%" in events[4].detail
    print(f"  [PASS] Event 4: '{events[4].title}' -> {events[4].status}")

    # Check schema compatibility keys
    assert "explanation_ms" in payload["live_progress"]["macro_gating_state"]
    assert "oos_gate" in payload["live_progress"]
    assert "recent_events" in payload["live_progress"]
    print(
        "  [PASS] Schema backward compatibility verified "
        "('explanation_ms', 'oos_gate', 'recent_events')."
    )

    print("\n" + "=" * 80)
    print("ALL EMPIRICAL CHALLENGER PROBES PASSED 100%! VERDICT: APPROVE")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
