"""Freeze a symmetric Macro Scalper development grid from verified project inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.research.runtime_qualification import content_hash  # noqa: E402

SOURCE_PATHS = (
    "src/autonomous_futures/strategy/macro_liquidity_scalper.py",
    "src/autonomous_futures/execution/trade_plan.py",
    "src/autonomous_futures/execution/daily_risk.py",
    "src/autonomous_futures/research/runtime_qualification.py",
    "scripts/qualify_runtime_scalper_variant.py",
    "scripts/run_scalper_development_grid.py",
    "scripts/select_scalper_development_candidates.py",
    "scripts/freeze_scalper_development_grid.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_path(value: str, repo: Path) -> Path:
    path = Path(value.replace("\\", "/"))
    return (path if path.is_absolute() else repo / path).resolve()


def relative_path(path: Path, repo: Path) -> str:
    resolved = path.resolve()
    root = repo.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Frozen inputs must be inside the repository")
    return resolved.relative_to(root).as_posix()


def report_for_symbol(directory: Path, symbol: str) -> tuple[Path, dict[str, Any]]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in directory.glob("*.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        if (
            isinstance(report, dict)
            and report.get("family") == "MACRO_SCALPER"
            and report.get("symbol") == symbol
        ):
            matches.append((path.resolve(), report))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one Macro report for {symbol}, found {len(matches)}")
    path, report = matches[0]
    body = dict(report)
    claimed_hash = body.pop("report_hash", None)
    if (
        report.get("decision") != "REJECTED"
        or report.get("execution_authority") is not False
        or claimed_hash != content_hash(body)
        or report.get("policy", {}).get("trade_risk_pct") != "0.5"
        or report.get("policy", {}).get("daily_loss_pct") != "5"
    ):
        raise ValueError(f"Reference report is not a hash-valid rejected 0.5%/5% report: {symbol}")
    return path, report


def freeze(
    *,
    base_protocol_path: Path,
    reference_reports_dir: Path,
    commissions_path: Path,
    equity_evidence_path: Path,
    output_path: Path,
    output_directory: str,
    repo: Path = REPO,
    max_workers: int = 3,
) -> dict[str, Any]:
    root = repo.resolve()
    base_path = project_path(str(base_protocol_path), root)
    reports_dir = project_path(str(reference_reports_dir), root)
    commissions = project_path(str(commissions_path), root)
    equity_evidence = project_path(str(equity_evidence_path), root)
    target = project_path(str(output_path), root)
    if target.exists():
        raise ValueError("Frozen protocol already exists and is immutable")
    if not 1 <= max_workers <= 3:
        raise ValueError("max_workers must be between one and three")

    base = json.loads(base_path.read_text(encoding="utf-8"))
    if base.get("status") != "FROZEN_BEFORE_EVALUATION":
        raise ValueError("Base protocol must already be frozen")
    symbols = base.get("symbols")
    if not isinstance(symbols, list) or not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("Base protocol must contain unique Macro symbols")
    holdout_path = root / "research/qualification-holdout-2026-08-2026-09/holdout-index.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    if holdout.get("status") != "partially_consumed":
        raise ValueError("Validation partitions must come from the current holdout usage index")

    protocol = deepcopy(base)
    protocol["research_variant"] = "macro_scalper_symmetric_short_v1"
    protocol["started_at_utc"] = datetime.now(UTC).isoformat()
    protocol["max_workers"] = max_workers
    protocol["output_directory"] = output_directory
    protocol["excluded_combinations"] = []
    protocol["selection_policy"] = (
        "Evaluate the frozen parameter axes against development data only using the current "
        "symmetric long/short Macro implementation. Every report remains DEVELOPMENT_ONLY; "
        "the development interval cannot grant qualification or execution authority."
    )
    protocol["reference_report_policy"] = {
        "role": "rejected historical baseline only",
        "implementation_current": False,
        "execution_authority": False,
    }
    protocol["validation_partition_index"] = {
        "path": relative_path(holdout_path, root),
        "sha256": digest(holdout_path),
        "status": holdout["status"],
        "uninspected_target_symbols": holdout["consumption"]["uninspected_target_symbols"],
        "shared_context_consumed": [{"symbol": "BTCUSDT", "timeframe": "1h"}],
    }
    protocol["inputs"] = {
        **protocol["inputs"],
        "commissions": relative_path(commissions, root),
        "equity_evidence": relative_path(equity_evidence, root),
    }

    references: dict[str, dict[str, str]] = {}
    fingerprints: dict[str, str] = {}

    def bind(path: Path) -> str:
        portable = relative_path(path, root)
        value = digest(path)
        existing = fingerprints.get(portable)
        if existing is not None and existing != value:
            raise ValueError(f"Conflicting frozen hashes for {portable}")
        fingerprints[portable] = value
        return portable

    for item in base["input_fingerprints"]:
        source = project_path(str(item["path"]), root)
        if digest(source) != item["sha256"]:
            raise ValueError(f"Base input hash mismatch: {item['path']}")
        bind(source)
    for path in (base_path, commissions, equity_evidence, holdout_path):
        bind(path)
    for relative in SOURCE_PATHS:
        bind(root / relative)
    for symbol in symbols:
        report_path, _report = report_for_symbol(reports_dir, symbol)
        portable = bind(report_path)
        references[symbol] = {
            "path": portable,
            "sha256": fingerprints[portable],
        }
    protocol["reference_reports"] = references
    protocol["input_fingerprints"] = [
        {"path": path, "sha256": value} for path, value in sorted(fingerprints.items())
    ]

    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(protocol, indent=2, sort_keys=True) + "\n"
    with target.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(encoded)
    return cast(dict[str, Any], protocol)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-protocol", type=Path, required=True)
    parser.add_argument("--reference-reports", type=Path, required=True)
    parser.add_argument("--commissions", type=Path, required=True)
    parser.add_argument("--equity-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--max-workers", type=int, default=3)
    args = parser.parse_args()
    protocol = freeze(
        base_protocol_path=args.base_protocol,
        reference_reports_dir=args.reference_reports,
        commissions_path=args.commissions,
        equity_evidence_path=args.equity_evidence,
        output_path=args.output,
        output_directory=args.output_directory,
        max_workers=args.max_workers,
    )
    print(
        json.dumps(
            {
                "event": "SCALPER_DEVELOPMENT_PROTOCOL_FROZEN",
                "path": str(args.output),
                "symbol_count": len(protocol["symbols"]),
                "job_count": len(protocol["symbols"])
                * len(protocol["distance_thresholds"])
                * len(protocol["target_atr_multipliers"]),
                "input_count": len(protocol["input_fingerprints"]),
                "execution_authority": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
