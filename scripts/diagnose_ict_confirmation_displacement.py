"""Screen filled ICT trades by the signal-candle displacement, using verified dev data only.

This diagnostic never qualifies a candidate. It filters only trades already present in
rejected reports, so every result requires a complete chronological replay before use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.research.official_market_data import archive_minutes  # noqa: E402
from autonomous_futures.research.runtime_qualification import content_hash  # noqa: E402

D = Decimal


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_file(path_text: str) -> Path:
    path = (REPO / path_text).resolve()
    if not path.is_relative_to(REPO):
        raise ValueError("Attested path leaves the repository")
    return path


def load_rejected_report(path: Path, implementation_hashes: dict[str, str]) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    identity = report.get("report_hash")
    payload = dict(report)
    payload.pop("report_hash", None)
    if not identity or content_hash(payload) != identity:
        raise ValueError(f"Report hash mismatch: {path}")
    if report.get("family") != "ICT_TWINS" or report.get("decision") != "REJECTED":
        raise ValueError(f"Only rejected ICT development reports are admissible: {path}")
    if report.get("execution_authority") is not False:
        raise ValueError(f"Rejected report unexpectedly grants execution authority: {path}")
    for relative, expected in report.get("implementation", {}).items():
        source = repo_file(relative)
        observed = implementation_hashes.setdefault(relative, sha256(source))
        if observed != expected:
            raise ValueError(f"Report implementation differs from current source: {relative}")

    matches = []
    for candidate in (REPO / "artifacts/qualification").rglob(
        f"{report['symbol']}-source-attestation-*.json"
    ):
        candidate_data = json.loads(candidate.read_text(encoding="utf-8"))
        if candidate_data.get("original_report_hash") == identity:
            matches.append((candidate, candidate_data))
    if not matches:
        raise ValueError(f"No report-bound source attestation for {report['symbol']}")
    if len({sha256(candidate) for candidate, _ in matches}) != 1:
        raise ValueError(f"Conflicting report-bound source attestations for {report['symbol']}")
    attestation_path, attestation = matches[0]
    report_relative = path.resolve().relative_to(REPO).as_posix()
    if (
        attestation.get("schema") != "runtime-report-source-attestation-v1"
        or attestation.get("original_decision") != "REJECTED"
        or attestation.get("execution_authority") is not False
        or attestation.get("original_report_hash") != identity
        or attestation.get("report_path") != report_relative
        or attestation.get("report_sha256") != sha256(path)
    ):
        raise ValueError(f"Source attestation does not bind this rejected report: {path}")
    source_hashes: dict[str, str] = {}
    for record in attestation.get("source_files", []):
        source = repo_file(record["path"])
        observed = source_hashes.setdefault(record["path"], sha256(source))
        if observed != record["sha256"]:
            raise ValueError(f"Attested source bytes changed: {record['path']}")
    if len(source_hashes) != len(attestation.get("source_files", [])):
        raise ValueError(f"Source attestation contains duplicate paths: {path}")
    return {
        "report": report,
        "report_sha256": sha256(path),
        "attestation_path": attestation_path,
        "attestation_sha256": sha256(attestation_path),
        "source_count": len(source_hashes),
    }


def verified_archive_bars(
    minute_root: Path, symbol: str, month: str, archive_hashes: dict[str, str]
) -> list[Any]:
    minute_root = minute_root.expanduser().resolve()
    archive_name = f"{symbol}-1m-{month}"
    manifest_path = minute_root / symbol / f"{archive_name}.zip.manifest.json"
    archive_path = minute_root / symbol / f"{archive_name}.zip"
    checksum_path = minute_root / symbol / f"{archive_name}.zip.CHECKSUM"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checksum = checksum_path.read_text(encoding="utf-8").split()
    if (
        manifest.get("symbol") != symbol
        or manifest.get("timeframe") != "1m"
        or manifest.get("month") != month
        or len(checksum) != 2
        or checksum[0] != manifest.get("sha256")
        or checksum[1].lstrip("*") != archive_path.name
    ):
        raise ValueError(f"Official archive manifest/checksum mismatch: {archive_path}")
    observed = sha256(archive_path)
    if observed != manifest["sha256"]:
        raise ValueError(f"Official archive bytes changed: {archive_path}")
    archive_hashes[archive_path.relative_to(REPO).as_posix()] = observed
    archive_hashes[manifest_path.relative_to(REPO).as_posix()] = sha256(manifest_path)
    archive_hashes[checksum_path.relative_to(REPO).as_posix()] = sha256(checksum_path)
    return list(archive_minutes(archive_path, manifest["sha256"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=REPO / "artifacts/qualification/runtime-ict-directional-fix-20261013",
    )
    parser.add_argument("--minute-root", type=Path, default=REPO / "research/official-archives/1m")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO
        / "artifacts/qualification/diagnostics/ict-confirmation-displacement-20261013.json",
    )
    parser.add_argument(
        "--thresholds",
        default="-1,0,0.05,0.10,0.20,0.30,0.50,0.75,1.00,1.50",
        help="Comma-separated favorable signal-candle displacement thresholds in 1m ATR units.",
    )
    parser.add_argument(
        "--reserved-start",
        default="2026-08-01T00:00:00+00:00",
        help="UTC lower boundary of reserved holdout data; no decision at/after this time is read.",
    )
    args = parser.parse_args()
    thresholds = tuple(D(item.strip()) for item in args.thresholds.split(","))
    if not thresholds or not all(item.is_finite() for item in thresholds):
        raise ValueError("Displacement thresholds must be finite Decimals")
    frozen_policy_path = args.report_dir / "frozen-policy.json"
    frozen_policy = json.loads(frozen_policy_path.read_text(encoding="utf-8"))
    trade_risk_pct = D(str(frozen_policy.get("trade_risk_pct", "")))
    if not trade_risk_pct.is_finite() or trade_risk_pct <= 0:
        raise ValueError("Frozen report policy must declare a positive trade_risk_pct")
    reserved_start_ms = int(
        datetime.fromisoformat(args.reserved_start.replace("Z", "+00:00")).timestamp() * 1000
    )
    implementation_hashes: dict[str, str] = {}
    verified_reports = []
    for path in sorted(args.report_dir.glob("*USDT-*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("family") == "ICT_TWINS" and report.get("symbol"):
            verified_reports.append(load_rejected_report(path, implementation_hashes))
    if not verified_reports:
        raise ValueError("No rejected ICT reports found")

    trades: list[dict[str, Any]] = []
    for item in verified_reports:
        report = item["report"]
        for window_index, window in enumerate(report["windows"]):
            for trade in window["trades"]:
                plan = trade["plan"]
                target_ms = int(plan["decision_ms"]) - 60_000
                if target_ms + 60_000 >= reserved_start_ms:
                    raise ValueError("A trade enters the reserved holdout interval")
                dt = datetime.fromtimestamp(target_ms / 1000, UTC)
                trades.append(
                    {
                        "symbol": plan["symbol"],
                        "window": window_index,
                        "month": f"{dt:%Y-%m}",
                        "target_ms": target_ms,
                        "side": plan["side"],
                        "entry": D(plan["entry"]),
                        "quantity": D(plan["quantity"]),
                        "net": D(trade["net_pnl"]),
                        "stress": D(trade["stress_net_pnl"]),
                        "reasons": [exit_item["reason"] for exit_item in trade["exits"]],
                    }
                )

    by_archive: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        by_archive[(trade["symbol"], trade["month"])].append(trade)
    archive_hashes: dict[str, str] = {}
    for (symbol, month), month_trades in by_archive.items():
        bars = verified_archive_bars(args.minute_root, symbol, month, archive_hashes)
        start_ms = bars[0].timestamp_ms
        for trade in month_trades:
            index = (trade["target_ms"] - start_ms) // 60_000
            if index < 14 or index >= len(bars) or bars[index].timestamp_ms != trade["target_ms"]:
                raise ValueError(f"Exact signal candle unavailable: {symbol} {trade['target_ms']}")
            bar = bars[index]
            sign = D(1) if trade["side"] == "BUY" else D(-1)
            favorable = sign * (bar.close - trade["entry"])
            ranges = []
            for position in range(index - 13, index + 1):
                prior_close = bars[position - 1].close
                ranges.append(
                    max(
                        bars[position].high - bars[position].low,
                        abs(bars[position].high - prior_close),
                        abs(bars[position].low - prior_close),
                    )
                )
            atr = sum(ranges, D(0)) / D(len(ranges))
            if atr <= 0:
                raise ValueError(f"Invalid signal-candle ATR: {symbol} {trade['target_ms']}")
            trade["impulse_atr"] = favorable / atr
            trade["body_aligned"] = sign * (bar.close - bar.open) > 0

    def summarize(selected: list[dict[str, Any]]) -> dict[str, Any]:
        early = [trade for trade in selected if trade["window"] <= 2]
        late = [trade for trade in selected if trade["window"] >= 3]
        return {
            "trades": len(selected),
            "net_pnl_usdt": str(sum((trade["net"] for trade in selected), D(0))),
            "stress_net_pnl_usdt": str(sum((trade["stress"] for trade in selected), D(0))),
            "early_windows_0_2": {
                "trades": len(early),
                "net_pnl_usdt": str(sum((trade["net"] for trade in early), D(0))),
            },
            "later_windows_3_4": {
                "trades": len(late),
                "net_pnl_usdt": str(sum((trade["net"] for trade in late), D(0))),
            },
            "trades_with_cisd_invalidation": sum(
                "CISD_INVALIDATION" in trade["reasons"] for trade in selected
            ),
        }

    threshold_results = []
    for threshold in thresholds:
        selected = [trade for trade in trades if trade["impulse_atr"] >= threshold]
        threshold_results.append(
            {"minimum_displacement_atr": str(threshold), **summarize(selected)}
        )
    symbol_results = []
    for symbol in sorted({trade["symbol"] for trade in trades}):
        selected = [trade for trade in trades if trade["symbol"] == symbol]
        filtered = [trade for trade in selected if trade["impulse_atr"] >= D("0.5")]
        symbol_results.append(
            {
                "symbol": symbol,
                "unfiltered": summarize(selected),
                "minimum_displacement_atr_0.5": summarize(filtered),
            }
        )

    result = {
        "schema": "ict-confirmation-displacement-screen-v1",
        "status": "DIAGNOSTIC_ONLY",
        "qualification": False,
        "execution_authority": False,
        "measurement": (
            "Favorable close-to-entry displacement on the exact 1m signal candle, "
            "divided by trailing 14-bar true-range mean."
        ),
        "limitations": [
            (
                "The screen filters only trades that filled in rejected reports. It does not "
                "rerun the candidate path or account state."
            ),
            (
                "Per-symbol reports use isolated research wallets and do not establish a "
                "shared-wallet portfolio domain."
            ),
            "A filtered result cannot qualify a strategy or authorize a change to live exits.",
            (
                f"Trades retain the frozen report batch's {trade_risk_pct} percent research "
                "risk policy; this diagnostic does not independently qualify risk sizing."
            ),
        ],
        "reserved_holdout_start_utc": args.reserved_start,
        "research_trade_risk_pct": str(trade_risk_pct),
        "frozen_policy_source": {
            "path": frozen_policy_path.resolve().relative_to(REPO).as_posix(),
            "sha256": sha256(frozen_policy_path),
        },
        "trade_count": len(trades),
        "symbols": sorted({trade["symbol"] for trade in trades}),
        "source_reports": [
            {
                "symbol": item["report"]["symbol"],
                "report_hash": item["report"]["report_hash"],
                "report_sha256": item["report_sha256"],
                "attestation_sha256": item["attestation_sha256"],
                "attested_source_file_count": item["source_count"],
            }
            for item in verified_reports
        ],
        "implementation_sha256": implementation_hashes,
        "official_minute_source_sha256": archive_hashes,
        "threshold_results": threshold_results,
        "symbol_results": symbol_results,
    }
    result["diagnostic_hash"] = content_hash(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "diagnostic_hash": result["diagnostic_hash"],
                "trade_count": result["trade_count"],
                "threshold_results": result["threshold_results"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
