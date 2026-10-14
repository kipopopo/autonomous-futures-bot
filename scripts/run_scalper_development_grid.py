"""Run a frozen Macro Scalper parameter grid on development data only."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


def project_path(value: str) -> Path:
    path = Path(value.replace("\\", "/"))
    return path if path.is_absolute() else REPO / path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_inputs(protocol: dict[str, Any]) -> None:
    inputs = protocol.get("inputs")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("commissions"), str):
        raise ValueError("Frozen protocol must select an authenticated commission snapshot")
    commission_path = project_path(inputs["commissions"]).resolve()
    frozen_paths = {
        project_path(str(item["path"])).resolve(): item["sha256"]
        for item in protocol["input_fingerprints"]
    }
    if commission_path not in frozen_paths:
        raise ValueError("Commission snapshot must be fingerprinted in the frozen protocol")
    for item in protocol["input_fingerprints"]:
        path = project_path(item["path"])
        if digest(path) != item["sha256"]:
            raise ValueError(f"Frozen development input hash mismatch: {item['path']}")


def expand_jobs(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    if protocol.get("status") != "FROZEN_BEFORE_EVALUATION":
        raise ValueError("Development grid must be frozen before evaluation")
    interval = protocol["selection_interval"]
    start = datetime.fromisoformat(interval["start"])
    end = datetime.fromisoformat(interval["end_exclusive"])
    if start >= end:
        raise ValueError("Development selection interval must be non-empty")
    symbols = protocol["symbols"]
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("Development grid symbols must be non-empty and unique")
    distances = protocol["distance_thresholds"]
    targets = protocol["target_atr_multipliers"]
    if not distances or not targets:
        raise ValueError("Development grid parameter axes must be non-empty")
    for value in distances:
        decimal = Decimal(value)
        if not decimal.is_finite() or decimal >= 0:
            raise ValueError("Distance thresholds must be finite and negative")
    for value in targets:
        decimal = Decimal(value)
        if not decimal.is_finite() or decimal <= 0:
            raise ValueError("Target ATR multipliers must be finite and positive")
    references = protocol["reference_reports"]
    if set(references) != set(symbols):
        raise ValueError("Every development symbol must have exactly one reference report")
    excluded = {
        (item["symbol"], item["distance_threshold"], item["target_atr_multiplier"])
        for item in protocol.get("excluded_combinations", [])
    }
    jobs = []
    for symbol in symbols:
        reference = references[symbol]
        for distance in distances:
            for target in targets:
                if (symbol, distance, target) in excluded:
                    continue
                jobs.append(
                    {
                        "symbol": symbol,
                        "distance_threshold": distance,
                        "target_atr_multiplier": target,
                        "reference_report": reference["path"],
                        "reference_report_sha256": reference["sha256"],
                    }
                )
    if not jobs:
        raise ValueError("Development grid has no runnable combinations")
    return jobs


def run_job(job: dict[str, Any], protocol: dict[str, Any], output: Path) -> dict[str, Any]:
    reference = project_path(job["reference_report"])
    if digest(reference) != job["reference_report_sha256"]:
        raise ValueError(f"Reference report hash mismatch for {job['symbol']}")
    reference_report = json.loads(reference.read_text(encoding="utf-8"))
    if reference_report.get("decision") != "REJECTED":
        raise ValueError(f"Reference report is not rejected for {job['symbol']}")
    inputs = protocol["inputs"]
    command = [
        sys.executable,
        str(REPO / "scripts/qualify_runtime_scalper_variant.py"),
        "--symbol",
        job["symbol"],
        "--reference-report",
        str(reference),
        "--cache",
        str(REPO / inputs["cache"]),
        "--filters",
        str(REPO / inputs["filters"]),
        "--commissions",
        str(REPO / inputs["commissions"]),
        "--funding",
        str(REPO / inputs["funding_directory"] / f"{job['symbol']}-funding.csv"),
        "--oos-start",
        protocol["selection_interval"]["start"],
        "--distance-threshold",
        job["distance_threshold"],
        "--target-atr-multiplier",
        job["target_atr_multiplier"],
        "--output",
        str(output),
    ]
    if inputs.get("equity_evidence"):
        command.extend(["--equity-evidence", str(REPO / inputs["equity_evidence"])])
    completed = subprocess.run(command, cwd=REPO, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return {
            **job,
            "status": "FAILED",
            "returncode": completed.returncode,
            "stderr": completed.stderr[-4000:],
        }
    try:
        event = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {**job, "status": "FAILED", "reason": f"Invalid runner output: {exc}"}
    if event.get("event") != "DEVELOPMENT_REPLAY_RECORDED":
        return {**job, "status": "FAILED", "reason": "Unexpected development runner event"}
    report_path = REPO / event["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        **job,
        "status": "COMPLETED",
        "report_path": report_path.relative_to(REPO).as_posix(),
        "report_sha256": digest(report_path),
        "report_hash": report["report_hash"],
        "candidate_decision_on_development_sample": event[
            "candidate_decision_on_development_sample"
        ],
        "metrics": event["metrics"],
        "gates": event["gates"],
    }


def run_grid(protocol_path: Path) -> Path:
    protocol_path = protocol_path if protocol_path.is_absolute() else REPO / protocol_path
    protocol_path = protocol_path.resolve()
    frozen_protocol_sha256 = digest(protocol_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    validate_inputs(protocol)
    jobs = expand_jobs(protocol)
    max_workers = protocol.get("max_workers", 1)
    if not isinstance(max_workers, int) or not 1 <= max_workers <= 3:
        raise ValueError("Development grid max_workers must be between 1 and 3")
    output = project_path(str(protocol["output_directory"]))
    summary_path = output / "grid-summary.json"
    if summary_path.exists():
        raise ValueError("Immutable development grid summary already exists")
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any] | None] = [None] * len(jobs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_job, job, protocol, output): index for index, job in enumerate(jobs)
        }
        completed_count = 0
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[futures[future]] = result
            completed_count += 1
            print(
                json.dumps(
                    {
                        "event": "DEVELOPMENT_JOB_COMPLETED",
                        "completed_jobs": completed_count,
                        "job_count": len(jobs),
                        "symbol": result["symbol"],
                        "distance_threshold": result["distance_threshold"],
                        "target_atr_multiplier": result["target_atr_multiplier"],
                        "status": result["status"],
                        "candidate_decision_on_development_sample": result.get(
                            "candidate_decision_on_development_sample"
                        ),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    if digest(protocol_path) != frozen_protocol_sha256:
        raise ValueError("Frozen protocol changed during development evaluation")
    validate_inputs(protocol)
    complete = [result for result in results if result is not None]
    summary = {
        "schema_version": 1,
        "status": "COMPLETE" if all(r["status"] == "COMPLETED" for r in complete) else "INCOMPLETE",
        "protocol_path": protocol_path.relative_to(REPO).as_posix(),
        "protocol_sha256": frozen_protocol_sha256,
        "runner_sha256": digest(Path(__file__)),
        "started_at_utc": protocol["started_at_utc"],
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "selection_interval": protocol["selection_interval"],
        "selection_evidence_only": True,
        "execution_authority": False,
        "job_count": len(jobs),
        "completed_jobs": sum(r["status"] == "COMPLETED" for r in complete),
        "failed_jobs": sum(r["status"] == "FAILED" for r in complete),
        "results": complete,
    }
    encoded = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    temporary = summary_path.with_suffix(".json.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(summary_path)
    print(
        json.dumps(
            {
                "event": "SCALPER_DEVELOPMENT_GRID_RECORDED",
                "status": summary["status"],
                "job_count": summary["job_count"],
                "completed_jobs": summary["completed_jobs"],
                "failed_jobs": summary["failed_jobs"],
                "path": str(summary_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if summary["status"] != "COMPLETE":
        raise SystemExit("Development grid completed with failed jobs")
    return summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    run_grid(args.protocol)


if __name__ == "__main__":
    main()
