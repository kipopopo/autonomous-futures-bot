"""Select frozen Macro Scalper candidates from completed development-only reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.research.runtime_qualification import content_hash  # noqa: E402


def project_path(value: str) -> Path:
    path = Path(value.replace("\\", "/"))
    return path if path.is_absolute() else REPO / path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def window_net_pnl(report: dict[str, Any]) -> list[Decimal]:
    windows = report.get("windows", [])
    if not windows:
        raise ValueError("Development report has no windows")
    return [
        sum((Decimal(trade["net_pnl"]) for trade in window["trades"]), Decimal("0"))
        for window in windows
    ]


def candidate_priority(report: dict[str, Any], required_gates: set[str]) -> tuple[Any, ...] | None:
    gates = report.get("gates", {})
    if set(gates) != required_gates:
        raise ValueError("Qualification gate set changed during development selection")
    if (
        not all(gates.values())
        or report.get("candidate_decision_on_development_sample") != "QUALIFIED"
    ):
        return None
    metrics = report["metrics"]
    params = report["research_variant"]["parameters"]
    nets = window_net_pnl(report)
    return (
        -min(nets),
        -Decimal(metrics["stress_net_pnl"]),
        Decimal(metrics["drawdown_usdt"]),
        -int(metrics["trade_count"]),
        Decimal(params["distance_threshold"]),
        Decimal(params["target_atr_multiplier"]),
    )


def select(protocol_path: Path, summary_path: Path, output_path: Path) -> dict[str, Any]:
    protocol_path = protocol_path if protocol_path.is_absolute() else REPO / protocol_path
    summary_path = summary_path if summary_path.is_absolute() else REPO / summary_path
    output_path = output_path if output_path.is_absolute() else REPO / output_path
    protocol_path, summary_path, output_path = (
        protocol_path.resolve(),
        summary_path.resolve(),
        output_path.resolve(),
    )
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "COMPLETE" or summary.get("execution_authority") is not False:
        raise ValueError("Only a complete non-admissible development grid can be selected")
    if summary.get("protocol_sha256") != digest(protocol_path):
        raise ValueError("Development summary does not match the frozen grid protocol")
    if (
        summary.get("completed_jobs") != summary.get("job_count")
        or len(summary["results"]) != summary["job_count"]
    ):
        raise ValueError("Development summary job counts are inconsistent")
    if protocol.get("status") != "FROZEN_BEFORE_EVALUATION":
        raise ValueError("Selection protocol was not frozen before evaluation")
    if (
        protocol["selection_interval"]["end_exclusive"]
        != protocol["reserved_validation_interval"]["start"]
    ):
        raise ValueError("Development interval must end where the reserved holdout begins")
    required_gates = set(protocol["required_gates"])
    selected: list[dict[str, Any]] = []
    eligible_by_symbol: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = {
        symbol: [] for symbol in protocol["symbols"]
    }
    for item in summary["results"]:
        if item.get("status") != "COMPLETED":
            raise ValueError("Development summary contains an incomplete job")
        report_path = project_path(item["report_path"])
        if digest(report_path) != item["report_sha256"]:
            raise ValueError("Development report hash mismatch")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_body = dict(report)
        report_body.pop("report_hash", None)
        if (
            report.get("decision") != "DEVELOPMENT_ONLY"
            or report.get("execution_authority") is not False
            or report.get("report_hash") != item["report_hash"]
            or content_hash(report_body) != report.get("report_hash")
        ):
            raise ValueError("Grid output is not sealed as development-only evidence")
        symbol = item["symbol"]
        if symbol not in eligible_by_symbol:
            raise ValueError("Development summary contains an unexpected symbol")
        variant = report["research_variant"]
        if (
            report.get("symbol") != symbol
            or variant["parameters"]["distance_threshold"] != item["distance_threshold"]
            or variant["parameters"]["target_atr_multiplier"] != item["target_atr_multiplier"]
        ):
            raise ValueError("Development report differs from its frozen grid job")
        reference = protocol["reference_reports"][symbol]
        if variant["reference_report_sha256"] != reference["sha256"]:
            raise ValueError("Development report uses an unexpected reference report")
        priority = candidate_priority(report, required_gates)
        if priority is None:
            continue
        metrics = report["metrics"]
        gates = report["gates"]
        params = variant["parameters"]
        nets = window_net_pnl(report)
        eligible_by_symbol[symbol].append(
            (
                priority,
                {
                    "candidate_id": (
                        f"macro-scalper-{symbol.lower()}-"
                        f"d{params['distance_threshold']}-t{params['target_atr_multiplier']}"
                    ),
                    "symbol": symbol,
                    "parameters": params,
                    "development_report_path": item["report_path"],
                    "development_report_sha256": item["report_sha256"],
                    "development_report_hash": item["report_hash"],
                    "reference_report": reference,
                    "minimum_window_net_pnl_usdt": str(min(nets)),
                    "metrics": metrics,
                    "gates": gates,
                },
            )
        )
    for symbol in protocol["symbols"]:
        candidates = eligible_by_symbol[symbol]
        if candidates:
            selected.append(min(candidates, key=lambda item: item[0])[1])
    result = {
        "schema_version": 1,
        "status": "FROZEN_FOR_RESERVED_HOLDOUT" if selected else "NO_ELIGIBLE_CANDIDATES",
        "execution_authority": False,
        "grid_protocol_path": protocol_path.relative_to(REPO.resolve()).as_posix(),
        "grid_protocol_sha256": digest(protocol_path),
        "grid_summary_path": summary_path.relative_to(REPO.resolve()).as_posix(),
        "grid_summary_sha256": digest(summary_path),
        "selector_sha256": digest(Path(__file__).resolve()),
        "selection_rule": protocol["candidate_selection_rule"],
        "selection_interval": protocol["selection_interval"],
        "reserved_validation_interval": protocol["reserved_validation_interval"],
        "selected_count": len(selected),
        "selected_candidates": selected,
        "selection_time_utc": datetime.now(UTC).isoformat(),
    }
    result["selection_hash"] = content_hash(result)
    if output_path.exists():
        raise ValueError("Frozen candidate selection artifact already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = select(args.protocol, args.summary, args.output)
    print(
        json.dumps(
            {
                "event": "DEVELOPMENT_CANDIDATES_FROZEN",
                "status": result["status"],
                "selected_count": result["selected_count"],
                "execution_authority": False,
                "path": str(args.output),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
