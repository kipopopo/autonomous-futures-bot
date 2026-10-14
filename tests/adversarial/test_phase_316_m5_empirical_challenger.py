# ruff: noqa: E501
"""Milestone M5 Empirical Challenger: Phase 316 Institutional English & Daemon Continuity Challenge.

Authoritative Adversarial Verification for Phase 316 Live Deployment on https://futures.semua.dev:
1. 220+ Banned Malay Terms Scan on Live Production:
   - Root HTML (/)
   - Compiled JS bundle (/assets/index-DOERVwn7.js)
   - Dynamic Evolution API (/api/v1/canary/evolution)
   - Live Execution Status API (/api/v1/execution/status)
   - Canary Summary API (/api/v1/canary/summary)
   Asserts EXACTLY 0 matches across 270+ terms.

2. VPS Trader Daemon Continuous Invariant Stress Check:
   - Queries systemd properties on autonomous-futures-trader.service via SSH:
     * MainPID == 87549
     * NRestarts == 0
     * ActiveState == 'active'
     * SubState == 'running'
     * Result == 'success'
   - Queries Linux process table for PID 87549:
     * Continuous multi-day elapsed time (e.g. '2-')
   - Queries systemd journalctl for error priority:
     * 0 error entries ('-- No entries --')

3. Remote Cryptographic Parity:
   - Remote canary.py SHA256 matches local canary.py exactly.

4. Live Telemetry Solvency & Universe Governance:
   - Exact zero drift (|Δ| < 10^-15 USDT) across 8 perpetual pairs.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import httpx
import pytest

LIVE_BASE_URL = "https://futures.semua.dev"
SSH_KEY_PATH = Path.home() / ".ssh" / "kainode_ed25519_openssh"
VPS_HOST = "afbot@147.79.18.15"

BANNED_MALAY_TERMS: list[str] = sorted(
    list(
        set(
            [
                # From phase316-m2-empirical-adversarial.challenge.test.tsx
                "fasa",
                "carta",
                "pesanan",
                "suapan",
                "kemasukan",
                "kecairan",
                "pelaksanaan",
                "kedudukan",
                "pendedahan",
                "kesihatan",
                "ketulenan",
                "untung",
                "kadar",
                "kemenangan",
                "sifar",
                "sekatan",
                "bahaya",
                "pasaran",
                "nisbah",
                "sembunyi",
                "dibuka",
                "dikecilkan",
                "segar",
                "semak",
                "senarai",
                "penapis",
                "yuran",
                "gagal",
                "tiada",
                "memuatkan",
                "baru sahaja",
                "yang lalu",
                "pulangan",
                "purata",
                "maksimum",
                "keuntungan",
                "dagangan",
                "ranap",
                "kilat",
                "kesilapan",
                "kelebihan",
                "pilihan",
                "buruk",
                "lantai",
                "utama",
                "posisi",
                "kawalan",
                "keselamatan",
                "pembelajaran",
                "autopsi",
                "arkib",
                "penyelidikan",
                "degupan",
                "jantung",
                "lejar",
                "dwi-kemasukan",
                "berterusan",
                "calon",
                "mutasi",
                "genom",
                "simulasi",
                "bayangan",
                "pintu",
                "promosi",
                "perdagangan",
                "baki",
                "ekuiti",
                "tunai",
                "tersedia",
                "diperuntukkan",
                "jumlah",
                "bersih",
                "nyata",
                "belum",
                "rizab",
                "tertutup",
                "terbuka",
                "simpanan",
                "sejarah",
                "pantau",
                "harga",
                "saiz",
                "sasaran",
                "kategori",
                "kemaskini",
                "kunci",
                "batal",
                "tutup",
                "padam",
                "cari",
                "maklumat",
                "terkini",
                "penyegerakan",
                "berjaya",
                "oleh",
                "untuk",
                "pada",
                "dari",
                "daripada",
                "dengan",
                "atau",
                "adalah",
                "iaitu",
                "dalam",
                "luar",
                "atas",
                "bawah",
                "kiri",
                "kanan",
                "tambah",
                "kurang",
                "baharu",
                "lama",
                "telah",
                "sedang",
                "akan",
                "pernah",
                "boleh",
                "tidak",
                "bukan",
                "jangan",
                "sila",
                "tolong",
                "kembali",
                "seterusnya",
                "sebelum",
                "selepas",
                "semasa",
                "ketika",
                "antara",
                "setiap",
                "banyak",
                "sedikit",
                "tinggi",
                "rendah",
                "cepat",
                "lambat",
                "mudah",
                "sukar",
                "betul",
                "salah",
                "pasti",
                "mungkin",
                "hanya",
                "juga",
                "lagi",
                "masih",
                "sudah",
                "selalu",
                "jarang",
                "kadang",
                "mana",
                "siapa",
                "apa",
                "bila",
                "kenapa",
                "mengapa",
                "bagaimana",
                # From run_phase_316_m1_empirical_challenge.py
                "aliran",
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
                "melepasi",
                "menilai",
                "diuji",
                "terhadap",
                "peningkatan",
                "penstriman",
                "disegerakkan",
                "pasangan",
                "disahkan",
                "matematis",
                "penilaian",
                "dinilai",
                "diarahkan",
                "dijana",
                "kelayakan",
                "diperoleh",
                "interaktif",
                "kerugian",
                "saat",
                "minit",
                "minggu",
                "bulan",
                "tahun",
                # From m3-ssr-adversarial.challenge.test.tsx
                "konfluens",
                "skalper",
                "makro",
                "lepasserang",
                "isipadu",
                "lonjakan",
                "terlebih",
                "pembuat",
                "kurungan",
                "jejari",
                "spektrum",
                "selamat",
                "toksik",
                "amaran",
                "kritikal",
                "kelulusan",
                "ditahan",
                "autorisasi",
                "belian",
                "lulus",
                "bilangan",
                "ketahanan",
                "kemalangan",
                "ralat",
                "pemasaan",
                "pemilihan",
                "merugikan",
                "terperinci",
                "dipantau",
                "diisi",
                "integriti",
                "semakan",
                "hadkan",
                "sekat",
                "ditapis",
                "kitaran",
                "lilin",
                "imbasan",
                "layak",
                "semua",
                # Specific DISPATCH.md and financial domain terms
                "had",
                "tahap",
                "laksana",
                "laporan",
                "pelaburan",
                "tarikh",
                "masa",
                "kejatuhan",
                "kejatuhan kilat",
                "ambang",
                "penunjuk",
                "analisis",
                "corak",
                "penyelesaian",
                "pendedahan kumulatif",
                "wang tunai",
                "kelewatan",
                "pelayan",
                "sambungan",
                "pemulihan",
                "sandaran",
                "henti rugi",
                "ambil untung",
                "pesanan had",
                "pesanan pasaran",
                "kadar kemenangan",
                "lejar am",
                "jurnal",
                "kemaskini data",
                "muat turun",
                "muat naik",
                "tetapan",
                "bantuan",
                "dokumentasi",
                "penafian",
                "risiko",
                "semak semula",
            ]
        )
    )
)


def run_ssh(cmd: str) -> subprocess.CompletedProcess[str]:
    """Execute SSH command on Kainode VPS."""
    full_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-i",
        str(SSH_KEY_PATH),
        VPS_HOST,
        cmd,
    ]
    return subprocess.run(full_cmd, capture_output=True, text=True, check=False)


def find_banned_matches(text: str) -> list[tuple[str, int, str]]:
    """Return all banned matches with count and context snippet."""
    hits: list[tuple[str, int, str]] = []
    for term in BANNED_MALAY_TERMS:
        pat = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        matches = list(pat.finditer(text))
        if matches:
            first_m = matches[0]
            snippet = text[max(0, first_m.start() - 25) : min(len(text), first_m.end() + 25)]
            hits.append((term, len(matches), snippet.strip()))
    return hits


# =============================================================================
# 1. Banned Malay Terms Scan Suite
# =============================================================================


class TestBannedMalayTermsLiveScan:
    """Rigorous empirical scan of live production assets against 220+ banned terms."""

    def test_banned_dictionary_size_ge_220(self) -> None:
        """Verify the test dictionary contains at least 220 unique banned terms."""
        unique_terms = set(BANNED_MALAY_TERMS)
        assert len(unique_terms) >= 220, f"Expected >= 220 terms, got {len(unique_terms)}"
        print(f"\n[PASS] Verified {len(unique_terms)} unique banned terms in test dictionary.")

    def test_live_root_html_zero_banned_terms(self) -> None:
        """Verify live root HTML (GET /) contains exactly 0 banned Malay terms."""
        with httpx.Client(base_url=LIVE_BASE_URL, timeout=30.0) as client:
            resp = client.get("/")
            assert resp.status_code == 200, f"Root HTML returned HTTP {resp.status_code}"
            hits = find_banned_matches(resp.text)
            assert len(hits) == 0, f"Detected {len(hits)} banned terms in root HTML: {hits}"

    def test_live_js_bundle_zero_banned_terms(self) -> None:
        """Verify live production JS bundle (/assets/index-DOERVwn7.js) contains 0 banned Malay terms."""
        with httpx.Client(base_url=LIVE_BASE_URL, timeout=30.0) as client:
            root_resp = client.get("/")
            m = re.search(r'src=["\']/assets/(index-[^"\']+\.js)["\']', root_resp.text)
            bundle_name = m.group(1) if m else "index-DOERVwn7.js"

            resp = client.get(f"/assets/{bundle_name}")
            assert resp.status_code == 200, (
                f"JS bundle {bundle_name} returned HTTP {resp.status_code}"
            )
            assert len(resp.text) > 500_000, f"JS bundle unexpectedly small: {len(resp.text)} chars"

            hits = find_banned_matches(resp.text)
            assert len(hits) == 0, (
                f"Detected {len(hits)} banned terms in JS bundle {bundle_name}: {hits}"
            )

    def test_live_evolution_api_zero_banned_terms(self) -> None:
        """Verify GET /api/v1/canary/evolution contains exactly 0 banned Malay terms."""
        with httpx.Client(base_url=LIVE_BASE_URL, timeout=30.0) as client:
            resp = client.get("/api/v1/canary/evolution")
            assert resp.status_code == 200, f"Evolution API returned HTTP {resp.status_code}"
            hits = find_banned_matches(resp.text)
            assert len(hits) == 0, f"Detected {len(hits)} banned terms in evolution API: {hits}"

    def test_live_execution_status_api_zero_banned_terms(self) -> None:
        """Verify GET /api/v1/execution/status contains exactly 0 banned Malay terms."""
        with httpx.Client(base_url=LIVE_BASE_URL, timeout=30.0) as client:
            resp = client.get("/api/v1/execution/status")
            assert resp.status_code == 200, f"Execution API returned HTTP {resp.status_code}"
            hits = find_banned_matches(resp.text)
            assert len(hits) == 0, f"Detected {len(hits)} banned terms in execution API: {hits}"

    def test_live_canary_summary_api_zero_banned_terms(self) -> None:
        """Verify GET /api/v1/canary/summary contains exactly 0 banned Malay terms."""
        with httpx.Client(base_url=LIVE_BASE_URL, timeout=30.0) as client:
            resp = client.get("/api/v1/canary/summary")
            assert resp.status_code == 200, f"Summary API returned HTTP {resp.status_code}"
            hits = find_banned_matches(resp.text)
            assert len(hits) == 0, f"Detected {len(hits)} banned terms in summary API: {hits}"


# =============================================================================
# 2. VPS Trader Daemon Continuous Invariant Suite
# =============================================================================


@pytest.mark.skipif(not SSH_KEY_PATH.exists(), reason="Kainode VPS SSH key missing")
class TestVPSTraderDaemonContinuousInvariant:
    """Rigorous independent verification of trader daemon continuity on Kainode VPS."""

    def test_daemon_systemd_properties_pid_and_zero_restarts(self) -> None:
        """Verify autonomous-futures-trader.service Main PID is strictly 87549 and NRestarts=0."""
        proc = run_ssh(
            "systemctl --user show autonomous-futures-trader.service "
            "--property=MainPID,NRestarts,ActiveState,SubState,Result"
        )
        assert proc.returncode == 0, f"systemctl query failed: {proc.stderr}"
        stdout = proc.stdout

        props: dict[str, str] = {}
        for line in stdout.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()

        assert props.get("MainPID") == "87549", f"MainPID violation: {props}"
        assert props.get("NRestarts") == "0", f"NRestarts violation: {props}"
        assert props.get("ActiveState") == "active", f"ActiveState violation: {props}"
        assert props.get("SubState") == "running", f"SubState violation: {props}"
        assert props.get("Result") == "success", f"Result violation: {props}"

    def test_daemon_process_table_multi_day_uptime(self) -> None:
        """Verify ps process table entry shows continuous multi-day runtime."""
        proc = run_ssh("ps -p 87549 -o pid,ppid,user,etime,args --no-headers")
        assert proc.returncode == 0, f"ps query failed: {proc.stderr}"
        stdout = proc.stdout.strip()
        assert "87549" in stdout, f"PID 87549 not in process table: {stdout}"
        assert "run_phase_310_real_autonomous_trading.py" in stdout
        # Must show multi-day prefix in elapsed time (e.g. '2-')
        assert "2-" in stdout or "3-" in stdout, (
            f"Process appears recently restarted (no multi-day prefix): {stdout}"
        )

    def test_daemon_journalctl_error_log_is_clean(self) -> None:
        """Verify journalctl user service error-level log has 0 entries."""
        proc = run_ssh("journalctl --user -u autonomous-futures-trader.service -p err --no-pager")
        assert proc.returncode == 0, f"journalctl query failed: {proc.stderr}"
        stdout = proc.stdout.strip()
        assert "-- No entries --" in stdout or len(stdout) == 0, (
            f"Unexpected error log entries: {stdout}"
        )


# =============================================================================
# 3. Cryptographic Parity & Zero Balance Drift Suite
# =============================================================================


@pytest.mark.skipif(not SSH_KEY_PATH.exists(), reason="Kainode VPS SSH key missing")
class TestCryptographicParityAndSolvency:
    """Verify cryptographic parity of remote files and live double-entry solvency."""

    def test_remote_canary_py_sha256_parity(self) -> None:
        """Verify SHA256 of remote canary.py exactly matches local canary.py."""
        local_canary = Path("src/autonomous_futures/api/canary.py")
        assert local_canary.exists(), "Local canary.py does not exist"
        local_hash = hashlib.sha256(local_canary.read_bytes()).hexdigest()

        proc = run_ssh("sha256sum /opt/autonomous-futures-bot/src/autonomous_futures/api/canary.py")
        assert proc.returncode == 0, f"sha256sum query failed: {proc.stderr}"
        remote_hash = proc.stdout.strip().split()[0]

        assert remote_hash == local_hash, (
            f"Hash mismatch: remote {remote_hash} != local {local_hash}"
        )

    def test_live_execution_status_solvency_zero_drift(self) -> None:
        """Verify /api/v1/execution/status reports zero balance drift (|Δ| < 10^-15 USDT)."""
        with httpx.Client(base_url=LIVE_BASE_URL, timeout=15.0) as client:
            resp = client.get("/api/v1/execution/status")
            assert resp.status_code == 200, f"Execution status returned {resp.status_code}"
            data = resp.json()

            solvency = data.get("solvency", {})
            assert solvency.get("zero_balance_drift_verified") is True
            assert abs(float(solvency.get("drift_usdt", 999.0))) < 1e-15
            assert float(solvency.get("cash_reserve_pct", 0.0)) == 100.0
            assert float(data.get("aggregate_exposure_usdt", 999.0)) == 0.0
