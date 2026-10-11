"""Adversarial Empirical Challenge for Phase 316 Milestone M1.

Empirical verification of:
1. Macro gating regimes under all standard and adversarial conditions.
2. Recursive JSON payload audit against 70+ banned Malay/Indonesian root words.
3. Strict double-entry solvency zero-drift invariant (|Δ| = 0.00 < 10^-15 USDT).
4. Continuous daemon PID 87549 and 'ONLINE 24/7' status invariants.
5. Exact institutional English titles and details across all 5 recent_events.
6. Dynamic OOS gate qualification transitions and hurdle progression.
7. Backward-compatible schema preservation ('explanation_ms', 'oos_gate', 'recent_events').
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api import create_app
from autonomous_futures.api.canary import (
    MacroGatingStateItem,
    OOSQualificationGateItem,
    _build_macro_gating_state,
    load_verified_canary_auto_evolution,
)

# Comprehensive list of 70+ banned Malay/Indonesian root words and phrases
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


def extract_all_strings_recursively(obj: Any) -> list[str]:
    """Recursively traverses arbitrary Python data structures and extracts all string values."""
    found: list[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                found.append(k)
            found.extend(extract_all_strings_recursively(v))
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            found.extend(extract_all_strings_recursively(item))
    elif hasattr(obj, "__dict__"):
        for v in vars(obj).values():
            found.extend(extract_all_strings_recursively(v))
    elif hasattr(obj, "model_dump"):
        found.extend(extract_all_strings_recursively(obj.model_dump()))
    return found


def find_banned_tokens(text: str, banned_list: tuple[str, ...]) -> list[str]:
    """Checks a string against the banned token list and returns matches."""
    text_lower = text.lower()
    matches: list[str] = []
    for token in banned_list:
        token_lower = token.lower()
        if " " in token_lower or "-" in token_lower:
            if token_lower in text_lower:
                matches.append(token)
        else:
            if token_lower in text_lower:
                matches.append(token)
    return matches


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client fixture."""
    app = create_app()
    return TestClient(app)


# ==============================================================================
# 1. MACRO GATING REGIMES HARNESS
# ==============================================================================


class TestMacroGatingRegimesAdversarial:
    """Empirical probe verifying macro gating states under standard and adversarial inputs."""

    @pytest.mark.parametrize(
        ("input_regime", "expected_norm", "expected_longs_filtered", "expected_longs_allowed"),
        [
            ("BULLISH", "BULLISH_ALIGNED", False, True),
            ("BULLISH_ALIGNED", "BULLISH_ALIGNED", False, True),
            ("bullish", "BULLISH_ALIGNED", False, True),
            ("  Bullish  ", "BULLISH_ALIGNED", False, True),
            ("BEARISH", "BEARISH", True, False),
            ("bearish", "BEARISH", True, False),
            ("\tBearish\n", "BEARISH", True, False),
            ("NEUTRAL", "NEUTRAL", True, False),
            ("neutral", "NEUTRAL", True, False),
            ("SIDEWAYS", "NEUTRAL", True, False),
            ("sideways", "NEUTRAL", True, False),
            ("CHOPPY", "NEUTRAL", True, False),
            ("UNKNOWN_REGIME", "NEUTRAL", True, False),
            ("", "NEUTRAL", True, False),
            ("   ", "NEUTRAL", True, False),
        ],
    )
    def test_macro_gating_normalization_and_filtering(
        self,
        input_regime: str,
        expected_norm: str,
        expected_longs_filtered: bool,
        expected_longs_allowed: bool,
    ) -> None:
        """Verifies regime normalization, filtering flag, and permission flag."""
        gating = _build_macro_gating_state(regime=input_regime)
        assert gating.regime == expected_norm
        assert gating.longs_filtered is expected_longs_filtered
        assert gating.is_long_allowed is expected_longs_allowed

    def test_macro_gating_bullish_english_explanation(self) -> None:
        """Verifies Bullish regime explanation strings are 100% clean English."""
        gating = _build_macro_gating_state(regime="BULLISH")
        expected_ms = (
            "Active BTC Macro Trend Filter: Long entries permitted because "
            "BTC 1h/4h trend is Bullish Aligned (EMA 50 > EMA 200)."
        )
        expected_en = (
            "Long scalper entries permitted: BTC 1h/4h Bullish regime confirmed (EMA 50 > EMA 200)."
        )
        assert gating.explanation_ms == expected_ms
        assert gating.explanation == expected_en
        matches = find_banned_tokens(gating.explanation_ms, BANNED_MALAY_TOKENS)
        assert matches == [], f"Found banned tokens in Bullish explanation_ms: {matches}"
        matches_en = find_banned_tokens(gating.explanation, BANNED_MALAY_TOKENS)
        assert matches_en == [], f"Found banned tokens in Bullish explanation: {matches_en}"

    def test_macro_gating_bearish_english_explanation(self) -> None:
        """Verifies Bearish regime explanation strings are 100% clean English."""
        gating = _build_macro_gating_state(regime="BEARISH")
        expected_ms = (
            "Active BTC Macro Trend Filter: Long entries temporarily paused because "
            "BTC 1h/4h trend is in a Bearish regime (EMA 50 < EMA 200) "
            "to protect bot micro-capital."
        )
        expected_en = (
            "Long entries temporarily paused by BTC 1h/4h Bearish regime filter "
            "for capital protection (EMA 50 < EMA 200)."
        )
        assert gating.explanation_ms == expected_ms
        assert gating.explanation == expected_en
        matches = find_banned_tokens(gating.explanation_ms, BANNED_MALAY_TOKENS)
        assert matches == [], f"Found banned tokens in Bearish explanation_ms: {matches}"
        matches_en = find_banned_tokens(gating.explanation, BANNED_MALAY_TOKENS)
        assert matches_en == [], f"Found banned tokens in Bearish explanation: {matches_en}"

    def test_macro_gating_neutral_sideways_english_explanation(self) -> None:
        """Verifies Neutral and Sideways regime explanation strings are 100% clean English."""
        expected_ms = (
            "Active BTC Macro Trend Filter: Long entries temporarily paused because "
            "BTC 1h/4h trend is in a Neutral/Sideways regime to protect bot micro-capital."
        )
        expected_en = "Long entries temporarily paused: BTC macro regime transitional / sideways."
        for reg in ("NEUTRAL", "SIDEWAYS", "UNKNOWN"):
            gating = _build_macro_gating_state(regime=reg)
            assert gating.explanation_ms == expected_ms
            assert gating.explanation == expected_en
            matches = find_banned_tokens(gating.explanation_ms, BANNED_MALAY_TOKENS)
            assert matches == [], f"Found banned tokens in {reg} explanation_ms: {matches}"
            matches_en = find_banned_tokens(gating.explanation, BANNED_MALAY_TOKENS)
            assert matches_en == [], f"Found banned tokens in {reg} explanation: {matches_en}"

    def test_macro_gating_model_defaults(self) -> None:
        """Verifies MacroGatingStateItem default field values are 100% clean English."""
        default_item = MacroGatingStateItem()
        assert default_item.regime == "BEARISH"
        assert default_item.longs_filtered is True
        assert default_item.is_long_allowed is False
        assert (
            "Active BTC Macro Trend Filter: Long entries temporarily paused"
            in default_item.explanation_ms
        )
        assert (
            "Long entries temporarily paused by BTC 1h/4h Bearish regime filter"
            in default_item.explanation
        )
        matches = find_banned_tokens(default_item.explanation_ms, BANNED_MALAY_TOKENS)
        assert matches == [], f"Found banned tokens in default MacroGatingStateItem: {matches}"


# ==============================================================================
# 2. RECURSIVE JSON PAYLOAD 50+ BANNED MALAY ROOT WORDS AUDIT
# ==============================================================================


class TestRecursiveJsonPayloadBannedMalayWordsAudit:
    """Empirical audit recursively probing /api/v1/canary/evolution for banned Malay tokens."""

    @pytest.mark.parametrize("regime", ["BULLISH", "BEARISH", "NEUTRAL", "SIDEWAYS"])
    def test_canary_auto_evolution_object_purged_across_regimes(self, regime: str) -> None:
        """Verifies zero banned Malay tokens across all macro regimes in Python model."""
        res = load_verified_canary_auto_evolution(simulated_macro_regime=regime)
        all_strings = extract_all_strings_recursively(res)
        assert len(all_strings) > 30, f"Expected rich string set, got {len(all_strings)}"

        violations: list[tuple[str, list[str]]] = []
        for text in all_strings:
            matches = find_banned_tokens(text, BANNED_MALAY_TOKENS)
            if matches:
                violations.append((text, matches))

        assert violations == [], f"Found Malay violations under regime {regime}: {violations}"

    @pytest.mark.parametrize("closed_trades", [0, 1, 3, 5, 8, 20])
    def test_canary_auto_evolution_object_purged_across_trade_samples(
        self, closed_trades: int
    ) -> None:
        """Verifies zero banned Malay tokens across varying closed trade sample counts."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=closed_trades)
        all_strings = extract_all_strings_recursively(res)

        violations: list[tuple[str, list[str]]] = []
        for text in all_strings:
            matches = find_banned_tokens(text, BANNED_MALAY_TOKENS)
            if matches:
                violations.append((text, matches))

        assert violations == [], (
            f"Found Malay token violations with {closed_trades} trades: {violations}"
        )

    def test_api_endpoint_json_payload_recursively_purged(self, client: TestClient) -> None:
        """Verifies zero banned Malay tokens across JSON response of /api/v1/canary/evolution."""
        resp = client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        payload = resp.json()

        all_strings = extract_all_strings_recursively(payload)
        assert len(all_strings) > 30

        violations: list[tuple[str, list[str]]] = []
        for text in all_strings:
            matches = find_banned_tokens(text, BANNED_MALAY_TOKENS)
            if matches:
                violations.append((text, matches))

        assert violations == [], f"Found Malay token violations in API response: {violations}"


# ==============================================================================
# 3. RECENT EVENTS DETAILS & SPECIFICATION INTEGRITY
# ==============================================================================


class TestRecentEventsDetailsAndStructure:
    """Empirical verification of recent_events structure, titles, details, and statuses."""

    def test_recent_events_count_and_types(self) -> None:
        """Verifies exactly 5 recent events with expected types."""
        res = load_verified_canary_auto_evolution()
        events = res.live_progress.recent_events
        assert len(events) == 5

        expected_types = [
            "HEARTBEAT_INGRESS",
            "SOLVENCY_AUDIT",
            "CANDIDATE_HEALTH",
            "MUTATION_STAGING",
            "SHADOW_OOS_GATE",
        ]
        actual_types = [e.event_type for e in events]
        assert actual_types == expected_types

    def test_recent_event_0_heartbeat_ingress(self) -> None:
        """Verifies Event 0 (Heartbeat & Market Ingress) title, detail, and status."""
        res = load_verified_canary_auto_evolution()
        ev = res.live_progress.recent_events[0]
        assert ev.event_type == "HEARTBEAT_INGRESS"
        assert ev.title == "Heartbeat & Market Ingress"
        expected_detail = (
            "Binance Futures 15m & 1h klines streaming synchronized "
            "(8 pairs: BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX)"
        )
        assert ev.detail == expected_detail
        assert ev.status == "HEALTHY"
        assert ev.latency_ms == 42.0

    def test_recent_event_1_solvency_audit(self) -> None:
        """Verifies Event 1 (Continuous Double-Entry Ledger Audit) title, detail, and status."""
        res = load_verified_canary_auto_evolution()
        ev = res.live_progress.recent_events[1]
        assert ev.event_type == "SOLVENCY_AUDIT"
        assert ev.title == "Continuous Double-Entry Ledger Audit"
        expected_detail = (
            "Balance $100.12 USDT verified with zero mathematical drift (|Δ| = 0.00 < 10^-15 USDT)"
        )
        assert ev.detail == expected_detail
        assert ev.status == "VERIFIED"
        assert ev.latency_ms == 0.5

    def test_recent_event_2_candidate_health(self) -> None:
        """Verifies Event 2 (Candidate Strategy Health Evaluation) title, detail, and status."""
        res = load_verified_canary_auto_evolution()
        ev = res.live_progress.recent_events[2]
        assert ev.event_type == "CANDIDATE_HEALTH"
        assert ev.title == "Candidate Strategy Health Evaluation"
        expected_detail = (
            "BTCUSDT & ETHUSDT evaluated as ELITE; "
            "SOLUSDT evaluated as DEGRADED and routed to mutation"
        )
        assert ev.detail == expected_detail
        assert ev.status == "EVALUATED"

    def test_recent_event_3_mutation_staging(self) -> None:
        """Verifies Event 3 (Parameter Genome Mutation) title, detail, and status."""
        res = load_verified_canary_auto_evolution()
        ev = res.live_progress.recent_events[3]
        assert ev.event_type == "MUTATION_STAGING"
        assert ev.title == "Parameter Genome Mutation (Gen #2)"
        assert (
            ev.detail
            == "cand-ethusdt-evo-002 generated with Donchian period 24, ATR 2.5x, Hawkes 0.65"
        )
        assert ev.status == "STAGED"

    @pytest.mark.parametrize(
        ("trades", "expected_status", "expected_detail_prefix"),
        [
            (
                0,
                "WAITING",
                "OOS Gate: 0/5 samples acquired, Sharpe hurdle >= 15.0% (WAITING_FOR_SAMPLES)",
            ),
            (
                4,
                "WAITING",
                "OOS Gate: 4/5 samples acquired, Sharpe hurdle >= 15.0% (WAITING_FOR_SAMPLES)",
            ),
            (
                5,
                "QUALIFIED",
                "OOS Gate: 5/5 samples acquired, Sharpe hurdle >= 15.0% (QUALIFIED)",
            ),
            (
                8,
                "QUALIFIED",
                "OOS Gate: 8/5 samples acquired, Sharpe hurdle >= 15.0% (QUALIFIED)",
            ),
        ],
    )
    def test_recent_event_4_shadow_oos_gate_dynamic(
        self, trades: int, expected_status: str, expected_detail_prefix: str
    ) -> None:
        """Verifies Event 4 (Shadow OOS Promotion Gate) title, status, and dynamic detail."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=trades)
        ev = res.live_progress.recent_events[4]
        assert ev.event_type == "SHADOW_OOS_GATE"
        assert ev.title == "Shadow Simulation & OOS Promotion Gate"
        assert ev.status == expected_status
        assert ev.detail == expected_detail_prefix


# ==============================================================================
# 4. SOLVENCY ZERO-DRIFT INVARIANT HARNESS
# ==============================================================================


class TestSolvencyZeroDriftInvariant:
    """Empirical verification of strict double-entry mathematical zero-drift conservation."""

    def test_solvency_exact_zero_drift_python_model(self) -> None:
        """Verifies drift_usdt == 0.0 and zero_balance_drift_verified is True."""
        res = load_verified_canary_auto_evolution()
        solvency = res.solvency
        assert solvency.drift_usdt == 0.0
        assert solvency.zero_balance_drift_verified is True
        assert solvency.tolerance_ceiling_usdt == 1e-15
        assert abs(solvency.drift_usdt) < 1e-15

        # Check ledger item
        ledger = res.ledger
        assert ledger.drift == 0.0
        assert ledger.zero_balance_drift is True

        # Check balance conservation: cash + margin == starting_equity + realized_pnl
        cash = Decimal(str(solvency.cash_usdt))
        margin = Decimal(str(solvency.allocated_margin_usdt))
        starting = Decimal(str(solvency.starting_equity_usdt))
        realized = Decimal(str(solvency.realized_pnl_usdt))

        calculated_drift = abs(cash + margin - starting - realized)
        assert calculated_drift < Decimal("1e-15")
        assert solvency.drift_usdt == 0.0

    def test_solvency_zero_drift_api_response(self, client: TestClient) -> None:
        """Verifies solvency zero-drift invariant in /api/v1/canary/evolution API response."""
        resp = client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        solv = resp.json()["solvency"]
        assert solv["drift_usdt"] == 0.0
        assert solv["zero_balance_drift_verified"] is True
        assert abs(solv["drift_usdt"]) < 1e-15


# ==============================================================================
# 5. DAEMON PID & ONLINE STATUS INVARIANT HARNESS
# ==============================================================================


class TestDaemonPIDAndStatusInvariant:
    """Empirical verification of background trader daemon PID 87549 and 'ONLINE 24/7' continuity."""

    def test_daemon_pid_and_status_in_model(self) -> None:
        """Verifies PID 87549 and 'ONLINE 24/7' in LiveEvolutionProgressItem."""
        res = load_verified_canary_auto_evolution()
        prog = res.live_progress
        assert prog.daemon_pid == 87549
        assert prog.daemon_status == "ONLINE 24/7"
        assert prog.is_live_daemon_active is True

    def test_daemon_pid_and_status_in_api_response(self, client: TestClient) -> None:
        """Verifies PID 87549 and 'ONLINE 24/7' in /api/v1/canary/evolution JSON response."""
        resp = client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        data = resp.json()
        assert data["live_progress"]["daemon_pid"] == 87549
        assert data["live_progress"]["daemon_status"] == "ONLINE 24/7"
        assert data["live_progress"]["is_live_daemon_active"] is True


# ==============================================================================
# 6. DYNAMIC OOS GATE & HURDLE EXPLANATION HARNESS
# ==============================================================================


class TestDynamicOOSGateAndHurdles:
    """Empirical verification of dynamic OOS gate explanation and status progression."""

    def test_oos_gate_waiting_for_samples(self) -> None:
        """Verifies OOS gate waiting state with explanation string."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=0)
        gate = res.live_progress.oos_gate
        assert gate.status == "WAITING_FOR_SAMPLES"
        assert gate.samples_acquired == 0
        assert gate.samples_required == 5
        expected_explanation = (
            "Waiting for 5 completed trade samples to evaluate out-of-sample Sharpe "
            "(current: 0/5, hurdle >= 15.0%)."
        )
        assert gate.explanation == expected_explanation
        matches = find_banned_tokens(gate.explanation, BANNED_MALAY_TOKENS)
        assert matches == [], f"Found banned tokens in OOS explanation: {matches}"

    def test_oos_gate_partial_samples(self) -> None:
        """Verifies OOS gate partial sample count reflects in explanation."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=3)
        gate = res.live_progress.oos_gate
        assert gate.status == "WAITING_FOR_SAMPLES"
        assert gate.samples_acquired == 3
        expected_explanation = (
            "Waiting for 5 completed trade samples to evaluate out-of-sample Sharpe "
            "(current: 3/5, hurdle >= 15.0%)."
        )
        assert gate.explanation == expected_explanation

    def test_oos_gate_qualified(self) -> None:
        """Verifies OOS gate qualified status when trades >= 5 and improvement >= 15.0%."""
        res = load_verified_canary_auto_evolution(simulated_closed_trades=5)
        gate = res.live_progress.oos_gate
        assert gate.status == "QUALIFIED"
        assert gate.samples_acquired == 5
        assert "Candidate cleared out-of-sample Sharpe hurdle" in gate.explanation
        matches = find_banned_tokens(gate.explanation, BANNED_MALAY_TOKENS)
        assert matches == [], f"Found banned tokens in qualified explanation: {matches}"

    def test_oos_gate_model_defaults(self) -> None:
        """Verifies OOSQualificationGateItem default explanation is English."""
        default_gate = OOSQualificationGateItem()
        assert default_gate.status == "WAITING_FOR_SAMPLES"
        expected_explanation = (
            "Waiting for 5 completed trade samples to evaluate out-of-sample Sharpe "
            "(hurdle >= 15.0%)."
        )
        assert default_gate.explanation == expected_explanation
        matches = find_banned_tokens(default_gate.explanation, BANNED_MALAY_TOKENS)
        assert matches == [], f"Found banned tokens in default OOS gate: {matches}"


# ==============================================================================
# 7. BACKWARD COMPATIBILITY SCHEMA PRESERVATION
# ==============================================================================


class TestBackwardCompatibilitySchemaPreservation:
    """Empirical verification that legacy keys like 'explanation_ms' are preserved."""

    def test_explanation_ms_key_present_in_model_dict(self) -> None:
        """Verifies explanation_ms is present in macro_gating_state model dictionary."""
        res = load_verified_canary_auto_evolution()
        res_dict = res.model_dump()
        macro_dict = res_dict["live_progress"]["macro_gating_state"]
        assert "explanation_ms" in macro_dict
        assert "Active BTC Macro Trend Filter:" in macro_dict["explanation_ms"]

    def test_explanation_ms_key_present_in_api_json(self, client: TestClient) -> None:
        """Verifies explanation_ms is present in /api/v1/canary/evolution JSON response."""
        resp = client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        data = resp.json()
        macro = data["live_progress"]["macro_gating_state"]
        assert "explanation_ms" in macro
        assert "Active BTC Macro Trend Filter:" in macro["explanation_ms"]

    def test_oos_gate_and_recent_events_keys_present_in_api_json(self, client: TestClient) -> None:
        """Verifies oos_gate and recent_events keys exist in live_progress."""
        resp = client.get("/api/v1/canary/evolution")
        assert resp.status_code == 200
        prog = resp.json()["live_progress"]
        assert "oos_gate" in prog
        assert "recent_events" in prog
        assert isinstance(prog["recent_events"], list)
        assert len(prog["recent_events"]) == 5
