"""Bridge aggregate development candidate selection into a per-candidate holdout manifest.

Enforces the partial-consumption holdout ledger, binds the 0.5% trade-risk / 5% daily-loss
policy, the authenticated Testnet account-equity sizing basis, actual commissions/filters,
and current implementation digests without altering frozen grid source bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.research import runtime_qualification as qualification  # noqa: E402

REQUIRED_IMPLEMENTATION_PATHS = (
    "src/autonomous_futures/strategy/macro_liquidity_scalper.py",
    "src/autonomous_futures/execution/trade_plan.py",
    "src/autonomous_futures/execution/daily_risk.py",
    "src/autonomous_futures/research/runtime_qualification.py",
    "scripts/qualify_runtime_scalper_variant.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_repo_path(value: str | Path, repo: Path) -> Path:
    raw = str(value).replace("\\", "/")
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else repo / candidate).resolve()
    if not resolved.is_relative_to(repo.resolve()):
        raise ValueError(f"Path must remain inside repository: {value}")
    return resolved


def rel_posix(path: Path, repo: Path) -> str:
    return path.resolve().relative_to(repo.resolve()).as_posix()


def verify_report_integrity(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    body = dict(report)
    claimed = body.pop("report_hash", None)
    if not isinstance(claimed, str) or claimed != qualification.content_hash(body):
        raise ValueError(f"Report content hash mismatch: {path}")
    if report.get("execution_authority") is not False:
        raise ValueError(f"Report cannot claim execution authority: {path}")
    return cast(dict[str, Any], report)


def bridge_candidate(
    *,
    selection_path: Path,
    protocol_path: Path,
    holdout_index_path: Path,
    symbol: str,
    output_path: Path,
    repo: Path = REPO,
) -> dict[str, Any]:
    root = repo.resolve()
    sel_file = resolve_repo_path(selection_path, root)
    proto_file = resolve_repo_path(protocol_path, root)
    holdout_file = resolve_repo_path(holdout_index_path, root)
    out_file = resolve_repo_path(output_path, root)

    if out_file.exists():
        raise ValueError(f"Frozen candidate validation manifest already exists: {out_file}")

    selection = json.loads(sel_file.read_text(encoding="utf-8"))
    selection_body = dict(selection)
    claimed_selection_hash = selection_body.pop("selection_hash", None)
    if (
        selection.get("status") != "FROZEN_FOR_RESERVED_HOLDOUT"
        or selection.get("execution_authority") is not False
        or claimed_selection_hash != qualification.content_hash(selection_body)
    ):
        raise ValueError("Aggregate candidate selection artifact is invalid or unverified")

    protocol_sha = digest(proto_file)
    if selection.get("grid_protocol_sha256") != protocol_sha:
        raise ValueError("Aggregate selection does not match the frozen grid protocol SHA-256")

    protocol = json.loads(proto_file.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_EVALUATION":
        raise ValueError("Grid protocol is not FROZEN_BEFORE_EVALUATION")

    summary_file = resolve_repo_path(selection["grid_summary_path"], root)
    if digest(summary_file) != selection.get("grid_summary_sha256"):
        raise ValueError("Grid summary SHA-256 mismatch")

    # Verify all fingerprinted inputs from the grid protocol remain intact.
    for item in protocol.get("input_fingerprints", []):
        fp_path = resolve_repo_path(item["path"], root)
        if digest(fp_path) != item["sha256"]:
            raise ValueError(f"Frozen grid input fingerprint mismatch: {item['path']}")

    # Verify holdout partition ledger and shared-context consumption.
    holdout_sha = digest(holdout_file)
    partition_index_meta = protocol.get("validation_partition_index", {})
    if partition_index_meta.get("sha256") and partition_index_meta["sha256"] != holdout_sha:
        raise ValueError("Holdout partition index changed since grid protocol freeze")

    holdout = json.loads(holdout_file.read_text(encoding="utf-8"))
    consumption = holdout.get("consumption", {})
    if (
        holdout.get("status") not in {"uninspected", "partially_consumed"}
        or consumption.get("status") != holdout.get("status")
        or holdout.get("candidate_tuning_used") is not False
        or holdout.get("qualification_decision_authority") is not False
    ):
        raise ValueError("Holdout index status or governance flags are invalid")

    uninspected = consumption.get("uninspected_target_symbols", [])
    if symbol not in uninspected:
        raise ValueError(f"Target symbol {symbol} is not listed as uninspected in holdout ledger")

    consumed_entries = consumption.get("consumed_validation", [])
    for entry in consumed_entries:
        if entry.get("symbol") == symbol:
            raise ValueError(f"Target symbol {symbol} already has a consumed holdout validation")

    shared_context_records: list[dict[str, Any]] = []
    for entry in consumed_entries:
        for ctx in entry.get("shared_context_consumed", []):
            shared_context_records.append(
                {
                    "symbol": ctx["symbol"],
                    "timeframe": ctx["timeframe"],
                    "prior_family": entry["family"],
                    "prior_symbol": entry["symbol"],
                    "prior_candidate_id": entry["candidate_id"],
                    "prior_report_path": entry["report_path"],
                    "prior_report_sha256": entry["report_sha256"],
                }
            )

    matches = [c for c in selection.get("selected_candidates", []) if c.get("symbol") == symbol]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly 1 selected candidate for {symbol}, found {len(matches)}"
        )
    selected = matches[0]

    dev_report_file = resolve_repo_path(selected["development_report_path"], root)
    if digest(dev_report_file) != selected["development_report_sha256"]:
        raise ValueError("Selected development report file SHA-256 mismatch")
    dev_report = verify_report_integrity(dev_report_file)
    if (
        dev_report.get("decision") != "DEVELOPMENT_ONLY"
        or dev_report.get("candidate_decision_on_development_sample") != "QUALIFIED"
        or dev_report.get("report_hash") != selected["development_report_hash"]
    ):
        raise ValueError(
            "Selected development report is not a verified gate-passing development run"
        )

    ref_info = selected["reference_report"]
    ref_report_file = resolve_repo_path(ref_info["path"], root)
    if digest(ref_report_file) != ref_info["sha256"]:
        raise ValueError("Reference baseline report SHA-256 mismatch")
    ref_report = verify_report_integrity(ref_report_file)
    if ref_report.get("decision") != "REJECTED":
        raise ValueError("Reference baseline report must have decision=REJECTED")

    # Enforce 0.5% trade risk / 5% daily loss and same authenticated account-equity basis.
    policy_data = dev_report.get("policy", {})
    if policy_data.get("trade_risk_pct") != "0.5" or policy_data.get("daily_loss_pct") != "5":
        raise ValueError(
            "Development report policy does not bind 0.5% trade risk and 5% daily loss"
        )

    inputs_cfg = protocol.get("inputs", {})
    commissions_file = resolve_repo_path(inputs_cfg["commissions"], root)
    filters_file = resolve_repo_path(inputs_cfg["filters"], root)
    equity_file = resolve_repo_path(inputs_cfg["equity_evidence"], root)

    verified_scenario = qualification.authenticated_equity_scenario(equity_file, root)
    if dev_report.get("capital_scenario") != verified_scenario:
        raise ValueError(
            "Development report capital_scenario disagrees with authenticated equity probe"
        )
    if policy_data.get("starting_equity") != verified_scenario["starting_equity"]:
        raise ValueError(
            "Development report starting_equity disagrees with authenticated equity probe"
        )

    resolved_policy, commission_binding = qualification.bind_commission_policy(
        qualification.RuntimeQualificationPolicy(
            starting_equity=qualification.D(verified_scenario["starting_equity"])
        ),
        commissions_file,
        symbol,
        root,
    )
    if (
        policy_data.get("maker_fee") != str(resolved_policy.maker_fee)
        or policy_data.get("taker_fee") != str(resolved_policy.taker_fee)
    ):
        raise ValueError(
            "Development report fee rates disagree with authenticated commission snapshot"
        )

    # Verify implementation hashes match current repository files and the development report.
    implementation: dict[str, str] = {}
    dev_impl = dev_report.get("implementation", {})
    for rel_path in REQUIRED_IMPLEMENTATION_PATHS:
        current_sha = digest(root / rel_path)
        if dev_impl.get(rel_path) != current_sha:
            raise ValueError(f"Implementation hash drift detected for {rel_path}")
        implementation[rel_path] = current_sha

    manifest: dict[str, Any] = {
        "schema_version": 2,
        "status": "FROZEN_BEFORE_VALIDATION",
        "execution_authority": False,
        "candidate_id": selected["candidate_id"],
        "family": "MACRO_SCALPER",
        "research_variant": protocol.get("research_variant", "macro_scalper_symmetric_short_v1"),
        "symbol": symbol,
        "parameters": dict(selected["parameters"]),
        "selection_interval": dict(selection["selection_interval"]),
        "validation_interval": dict(selection["reserved_validation_interval"]),
        "selection_reports": [
            {
                "path": rel_posix(ref_report_file, root),
                "sha256": digest(ref_report_file),
                "report_hash": ref_report["report_hash"],
                "role": "rejected_baseline",
            },
            {
                "path": rel_posix(dev_report_file, root),
                "sha256": digest(dev_report_file),
                "report_hash": dev_report["report_hash"],
                "role": "parameter_selection_evidence",
            },
        ],
        "downstream_provenance": {
            "grid_protocol": {
                "path": rel_posix(proto_file, root),
                "sha256": protocol_sha,
            },
            "grid_summary": {
                "path": rel_posix(summary_file, root),
                "sha256": digest(summary_file),
            },
            "aggregate_selection": {
                "path": rel_posix(sel_file, root),
                "sha256": digest(sel_file),
                "selection_hash": claimed_selection_hash,
                "selector_sha256": selection["selector_sha256"],
            },
            "bridge_script": {
                "path": rel_posix(Path(__file__), root),
                "sha256": digest(Path(__file__)),
            },
        },
        "policy_binding": {
            "trade_risk_pct": "0.5",
            "daily_loss_pct": "5",
            "starting_equity": verified_scenario["starting_equity"],
            "maker_fee": str(resolved_policy.maker_fee),
            "taker_fee": str(resolved_policy.taker_fee),
            "policy_hash": dev_report["policy_hash"],
        },
        "capital_scenario": verified_scenario,
        "inputs": {
            "commissions": commission_binding,
            "filters": {
                "path": rel_posix(filters_file, root),
                "sha256": digest(filters_file),
            },
            "equity_evidence": {
                "path": rel_posix(equity_file, root),
                "sha256": digest(equity_file),
            },
        },
        "implementation": implementation,
        "holdout_partition_ledger": {
            "index_path": rel_posix(holdout_file, root),
            "pre_evaluation_index_sha256": holdout_sha,
            "status": holdout["status"],
            "target_symbol_uninspected_before_freeze": True,
            "candidate_tuning_used": False,
            "shared_context_consumed": shared_context_records,
            "disclosure": (
                f"Target {symbol} market and funding partitions for "
                f"{selection['reserved_validation_interval']['start']}.."
                f"{selection['reserved_validation_interval']['end_exclusive']} were uninspected "
                "prior to candidate freeze, but BTCUSDT 1h shared regime context from this "
                "interval was previously consumed in a rejected LINKUSDT diagnostic. "
                "This validation is a partially-consumed common-context holdout, not a "
                "wholly pristine common-context holdout."
            ),
        },
        "frozen_at_utc": datetime.now(UTC).isoformat(),
    }
    manifest["manifest_hash"] = qualification.content_hash(manifest)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument(
        "--holdout-index",
        type=Path,
        default=REPO / "research/qualification-holdout-2026-08-2026-09/holdout-index.json",
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = bridge_candidate(
        selection_path=args.selection,
        protocol_path=args.protocol,
        holdout_index_path=args.holdout_index,
        symbol=args.symbol,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "event": "VALIDATION_CANDIDATE_BRIDGED_AND_FROZEN",
                "candidate_id": manifest["candidate_id"],
                "symbol": manifest["symbol"],
                "status": manifest["status"],
                "execution_authority": manifest["execution_authority"],
                "manifest_hash": manifest["manifest_hash"],
                "path": str(args.output),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
