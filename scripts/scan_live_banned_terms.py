# ruff: noqa: E501
"""Scan live production endpoints for banned Malay terms."""

import re
import sys

import httpx

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


def main() -> int:
    print(f"Total banned terms in dictionary: {len(BANNED_MALAY_TERMS)}")
    base_url = "https://futures.semua.dev"
    client = httpx.Client(base_url=base_url, timeout=30.0)

    # 1. Root HTML
    r_root = client.get("/")
    assert r_root.status_code == 200, f"Root failed: {r_root.status_code}"
    html_text = r_root.text

    # Extract JS bundle filename from root HTML
    m = re.search(r'src=["\']/assets/(index-[^"\']+\.js)["\']', html_text)
    js_filename = m.group(1) if m else "index-DOERVwn7.js"
    print(f"Detected JS bundle: {js_filename}")

    # 2. JS bundle
    r_js = client.get(f"/assets/{js_filename}")
    assert r_js.status_code == 200, f"JS bundle failed: {r_js.status_code}"
    js_text = r_js.text

    # 3. Evolution endpoint
    r_evo = client.get("/api/v1/canary/evolution")
    assert r_evo.status_code == 200, f"Evolution failed: {r_evo.status_code}"
    evo_text = r_evo.text

    # 4. Execution status endpoint
    r_exec = client.get("/api/v1/execution/status")
    assert r_exec.status_code == 200, f"Execution failed: {r_exec.status_code}"
    exec_text = r_exec.text

    # 5. Summary endpoint
    r_sum = client.get("/api/v1/canary/summary")
    assert r_sum.status_code == 200, f"Summary failed: {r_sum.status_code}"
    sum_text = r_sum.text

    targets = {
        "root_html (/)": html_text,
        f"js_bundle (/assets/{js_filename})": js_text,
        "api_canary_evolution (/api/v1/canary/evolution)": evo_text,
        "api_execution_status (/api/v1/execution/status)": exec_text,
        "api_canary_summary (/api/v1/canary/summary)": sum_text,
    }

    all_passed = True
    for target_name, content in targets.items():
        print(f"\n--- Scanning {target_name} ({len(content):,} chars) ---")
        hits: list[tuple[str, int, str]] = []
        for term in BANNED_MALAY_TERMS:
            # Look for exact word boundary match
            pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            matches = list(pattern.finditer(content))
            if matches:
                first_m = matches[0]
                snippet = content[
                    max(0, first_m.start() - 25) : min(len(content), first_m.end() + 25)
                ]
                hits.append((term, len(matches), snippet.strip()))

        if hits:
            all_passed = False
            print(f"FAILED: Found {len(hits)} matching banned terms:")
            for term, count, snippet in hits:
                print(f"  - '{term}' ({count}x): snippet -> {snippet!r}")
        else:
            print(
                f"PASSED: Exactly 0 banned Malay terms matched across all {len(BANNED_MALAY_TERMS)} terms."
            )

    if all_passed:
        print("\n" + "=" * 80)
        print("EMPIRICAL VERIFICATION COMPLETE: ALL 5 LIVE TARGETS 100% CLEAN OF MALAY TERMS!")
        print("=" * 80)
        return 0
    else:
        print("\n" + "=" * 80)
        print("EMPIRICAL VERIFICATION FAILED: RESIDUAL MALAY TERMS DETECTED!")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
