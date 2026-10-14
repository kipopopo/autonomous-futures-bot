"""Evaluate one frozen Macro Scalper candidate on a disjoint historical holdout."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.research import runtime_qualification as qualification  # noqa: E402
from autonomous_futures.strategy.macro_liquidity_scalper import (  # noqa: E402
    MacroLiquidityDipScalper,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_repo_path(value: str | Path, repo: Path) -> Path:
    path = Path(str(value).replace("\\", "/"))
    return (path if path.is_absolute() else repo / path).resolve()


def validate_intervals(selection: dict[str, str], validation: dict[str, str]) -> None:
    selection_start = datetime.fromisoformat(selection["start"])
    selection_end = datetime.fromisoformat(selection["end_exclusive"])
    validation_start = datetime.fromisoformat(validation["start"])
    validation_end = datetime.fromisoformat(validation["end_exclusive"])
    if selection_start >= selection_end or validation_start >= validation_end:
        raise ValueError("Candidate intervals must be non-empty")
    if validation_start < selection_end and selection_start < validation_end:
        raise ValueError("Validation interval overlaps the candidate selection interval")


def load_candidate(path: Path, *, repo: Path | None = None) -> dict[str, Any]:
    root = (repo if repo is not None else REPO).resolve()
    candidate = json.loads(path.read_text(encoding="utf-8"))
    if candidate.get("status") != "FROZEN_BEFORE_VALIDATION":
        raise ValueError("Candidate must be frozen before holdout evaluation")
    if candidate.get("family") != "MACRO_SCALPER":
        raise ValueError("Candidate family must be MACRO_SCALPER")
    if candidate.get("execution_authority") is not False:
        raise ValueError("Candidate manifest cannot grant execution authority")

    if "manifest_hash" in candidate:
        body = dict(candidate)
        claimed_manifest_hash = body.pop("manifest_hash", None)
        if claimed_manifest_hash != qualification.content_hash(body):
            raise ValueError("Frozen candidate manifest hash mismatch")

    validate_intervals(candidate["selection_interval"], candidate["validation_interval"])
    reports: dict[str, dict[str, Any]] = {}
    for source in candidate["selection_reports"]:
        report_path = resolve_repo_path(source["path"], root)
        if digest(report_path) != source["sha256"]:
            raise ValueError("Frozen candidate selection report hash mismatch")
        reports[source["role"]] = json.loads(report_path.read_text(encoding="utf-8"))
    baseline = reports.get("rejected_baseline", {})
    selection = reports.get("parameter_selection_evidence", {})
    if baseline.get("decision") != "REJECTED":
        raise ValueError("Candidate baseline must remain a rejected report")
    if (
        selection.get("decision") != "DEVELOPMENT_ONLY"
        or selection.get("candidate_decision_on_development_sample") != "QUALIFIED"
    ):
        raise ValueError("Candidate selection evidence does not match the frozen protocol")
    selected_parameters = selection.get("research_variant", {}).get("parameters", {})
    if selected_parameters != candidate["parameters"]:
        raise ValueError("Frozen candidate parameters differ from the selection evidence")
    selection_windows = selection.get("windows", [])
    if (
        not selection_windows
        or selection_windows[0]["start_ms"]
        != int(
            datetime.fromisoformat(candidate["selection_interval"]["start"])
            .replace(tzinfo=UTC)
            .timestamp()
            * 1000
        )
        or selection_windows[-1]["end_ms"]
        != int(
            datetime.fromisoformat(candidate["selection_interval"]["end_exclusive"])
            .replace(tzinfo=UTC)
            .timestamp()
            * 1000
        )
    ):
        raise ValueError("Selection report interval differs from the frozen candidate manifest")

    policy_binding = candidate.get("policy_binding")
    if isinstance(policy_binding, dict):
        if (
            policy_binding.get("trade_risk_pct") != "0.5"
            or policy_binding.get("daily_loss_pct") != "5"
        ):
            raise ValueError("Frozen candidate policy must bind 0.5% trade risk and 5% daily loss")
        sel_policy = selection.get("policy", {})
        if (
            sel_policy.get("trade_risk_pct") != "0.5"
            or sel_policy.get("daily_loss_pct") != "5"
            or sel_policy.get("starting_equity") != policy_binding.get("starting_equity")
            or selection.get("policy_hash") != policy_binding.get("policy_hash")
        ):
            raise ValueError("Selection report policy disagrees with frozen candidate policy_binding")

    inputs = candidate.get("inputs")
    if isinstance(inputs, dict):
        for input_role in ("commissions", "filters", "equity_evidence"):
            info = inputs.get(input_role)
            if isinstance(info, dict) and "path" in info and "sha256" in info:
                target_file = resolve_repo_path(info["path"], root)
                if digest(target_file) != info["sha256"]:
                    raise ValueError(f"Frozen candidate {input_role} input hash mismatch")

    impl = candidate.get("implementation")
    if isinstance(impl, dict):
        for rel_path, expected_sha in impl.items():
            if digest(resolve_repo_path(rel_path, root)) != expected_sha:
                raise ValueError(f"Implementation hash changed since candidate freeze: {rel_path}")

    ledger = candidate.get("holdout_partition_ledger")
    if isinstance(ledger, dict):
        index_path = resolve_repo_path(ledger["index_path"], root)
        if digest(index_path) != ledger["pre_evaluation_index_sha256"]:
            raise ValueError("Holdout partition index changed since candidate freeze")
        holdout_index = json.loads(index_path.read_text(encoding="utf-8"))
        consumption = holdout_index.get("consumption", {})
        if (
            holdout_index.get("status") != ledger.get("status")
            or holdout_index.get("candidate_tuning_used") is not False
            or candidate["symbol"] not in consumption.get("uninspected_target_symbols", [])
        ):
            raise ValueError("Target symbol holdout partition is no longer uninspected or valid")

    return cast(dict[str, Any], candidate)


def seal_holdout_report(
    report: dict[str, Any],
    candidate: dict[str, Any],
    candidate_path: Path,
    funding_manifest_path: Path,
    funding_path: Path,
    *,
    repo: Path | None = None,
) -> dict[str, Any]:
    root = (repo if repo is not None else REPO).resolve()
    if report.get("family") != candidate["family"] or report.get("symbol") != candidate["symbol"]:
        raise ValueError("Qualification output does not match the frozen candidate")
    start_ms = int(
        datetime.fromisoformat(candidate["validation_interval"]["start"])
        .replace(tzinfo=UTC)
        .timestamp()
        * 1000
    )
    end_ms = int(
        datetime.fromisoformat(candidate["validation_interval"]["end_exclusive"])
        .replace(tzinfo=UTC)
        .timestamp()
        * 1000
    )
    windows = report.get("windows", [])
    if not windows or windows[0]["start_ms"] != start_ms or windows[-1]["end_ms"] != end_ms:
        raise ValueError("Qualification window does not match the frozen holdout interval")

    funding_manifest = json.loads(funding_manifest_path.read_text(encoding="utf-8"))
    if funding_manifest.get("symbol") != candidate["symbol"] or funding_manifest.get(
        "sha256"
    ) != digest(funding_path):
        raise ValueError("Funding provenance does not match the frozen candidate inputs")
    market_provenance: dict[str, Any] = {}
    for role in ("market", "execution", "macro"):
        source = report["sources"][role]
        if "dataset" in source and "manifest" in source:
            parquet_path = resolve_repo_path(source["dataset"]["path"], root)
            manifest_path = resolve_repo_path(source["manifest"]["path"], root)
            expected_manifest_sha = source["manifest"]["sha256"]
        else:
            parquet_path = Path(source["path"])
            if not parquet_path.is_absolute():
                parquet_path = (root / parquet_path).resolve()
            timeframe = parquet_path.parent.parent.name
            manifest_path = (
                parquet_path.parent.parent
                / "manifests"
                / f"{parquet_path.name.removesuffix(f'-{timeframe}.parquet')}-{timeframe}.manifest.json"
            )
            expected_manifest_sha = source["manifest_sha256"]
        if digest(manifest_path) != expected_manifest_sha:
            raise ValueError(f"Market provenance hash mismatch for {role}")
        market_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("builder_sha256", "market_data_parser_sha256"):
            value = market_manifest.get(key)
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"Market cache manifest is missing {key} for {role}")
        market_provenance[role] = {
            "manifest_sha256": expected_manifest_sha,
            "builder_sha256": market_manifest["builder_sha256"],
            "market_data_parser_sha256": market_manifest["market_data_parser_sha256"],
            "official_archives": market_manifest["official_archives"],
        }

    sealed = dict(report)
    validation_meta: dict[str, Any] = {
        "evidence_class": "INDEPENDENT_HISTORICAL_HOLDOUT",
        "candidate_id": candidate["candidate_id"],
        "candidate_manifest_sha256": digest(candidate_path),
        "selection_reports": candidate["selection_reports"],
        "validation_interval": candidate["validation_interval"],
        "parameters": candidate["parameters"],
        "market_archive_provenance": market_provenance,
        "funding_manifest_sha256": digest(funding_manifest_path),
        "funding_official_archives": funding_manifest["official_archives"],
        "runtime_environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "dependencies": {
                name: importlib.metadata.version(name) for name in ("numpy", "pandas", "pyarrow")
            },
        },
    }
    ledger = candidate.get("holdout_partition_ledger")
    if isinstance(ledger, dict):
        validation_meta["holdout_partition_ledger"] = ledger
        shared_ctx = ledger.get("shared_context_consumed", [])
        validation_meta["holdout_context_status"] = (
            "PARTIALLY_CONSUMED_SHARED_BTC_CONTEXT" if shared_ctx else "UNINSPECTED"
        )
        if shared_ctx:
            assumptions = list(sealed.get("assumptions", []))
            disclosure_note = (
                "shared BTCUSDT 1h regime context in 2026-08..2026-09 was previously consumed "
                "by a rejected LINKUSDT diagnostic; target symbol partition was uninspected before freeze"
            )
            if disclosure_note not in assumptions:
                assumptions.append(disclosure_note)
            sealed["assumptions"] = assumptions
    if "policy_binding" in candidate:
        validation_meta["policy_binding"] = candidate["policy_binding"]
    if "downstream_provenance" in candidate:
        validation_meta["downstream_provenance"] = candidate["downstream_provenance"]

    sealed["candidate_validation"] = validation_meta
    sealed["execution_authority"] = False
    sealed.setdefault("implementation", {})["scripts/qualify_frozen_scalper_candidate.py"] = digest(
        Path(__file__)
    )
    if (
        "source_files" in sealed
        and funding_manifest_path.resolve().is_relative_to(root)
        and isinstance(sealed.get("sources", {}).get("funding"), dict)
    ):
        sources_copy = dict(sealed["sources"])
        funding_src = dict(sources_copy["funding"])
        funding_src["manifest"] = {
            "path": qualification.repo_relative_source_path(funding_manifest_path, root),
            "sha256": digest(funding_manifest_path),
        }
        sources_copy["funding"] = funding_src
        sealed["sources"] = sources_copy
        sealed["source_files"] = qualification.source_file_index(sources_copy, root)

    sealed.pop("report_hash", None)
    sealed["report_hash"] = qualification.content_hash(sealed)
    return sealed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--funding", type=Path, required=True)
    parser.add_argument("--funding-manifest", type=Path, required=True)
    parser.add_argument("--filters", type=Path, required=True)
    parser.add_argument("--commissions", type=Path, required=True)
    parser.add_argument("--equity-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = load_candidate(args.candidate_manifest, repo=REPO)
    parameters = candidate["parameters"]
    distance = Decimal(parameters["distance_threshold"])
    target = Decimal(parameters["target_atr_multiplier"])
    if not distance.is_finite() or distance >= 0 or not target.is_finite() or target <= 0:
        raise ValueError("Frozen candidate parameters are invalid")

    inputs = candidate.get("inputs", {})
    if isinstance(inputs, dict):
        if "filters" in inputs and digest(args.filters) != inputs["filters"]["sha256"]:
            raise ValueError("--filters file does not match frozen candidate filters SHA-256")
        if "commissions" in inputs and digest(args.commissions) != inputs["commissions"]["sha256"]:
            raise ValueError("--commissions file does not match frozen candidate commissions SHA-256")

    equity_evidence_path = args.equity_evidence
    if equity_evidence_path is None and isinstance(inputs, dict) and "equity_evidence" in inputs:
        equity_evidence_path = resolve_repo_path(inputs["equity_evidence"]["path"], REPO)
    if (
        equity_evidence_path is not None
        and isinstance(inputs, dict)
        and "equity_evidence" in inputs
        and digest(equity_evidence_path) != inputs["equity_evidence"]["sha256"]
    ):
        raise ValueError("Equity evidence file does not match frozen candidate equity_evidence SHA-256")

    start = datetime.fromisoformat(candidate["validation_interval"]["start"])
    oos_start_ms = int(start.replace(tzinfo=UTC).timestamp() * 1000)
    engine_factory = partial(
        MacroLiquidityDipScalper,
        dist_atr_threshold=distance,
        tp_atr_mult=target,
    )
    base_policy, capital_scenario = qualification.qualification_capital(
        repo=REPO,
        equity_evidence_path=equity_evidence_path,
    )
    policy, _commission_binding = qualification.bind_commission_policy(
        base_policy, args.commissions, candidate["symbol"], REPO
    )
    policy_binding = candidate.get("policy_binding")
    if isinstance(policy_binding, dict):
        if (
            str(policy.trade_risk_pct) != policy_binding["trade_risk_pct"]
            or str(policy.daily_loss_pct) != policy_binding["daily_loss_pct"]
            or str(policy.starting_equity) != policy_binding["starting_equity"]
        ):
            raise ValueError("Resolved runtime qualification policy disagrees with frozen candidate")

    with patch.object(qualification, "MacroLiquidityDipScalper", engine_factory):
        report = qualification.qualify_scalper(
            cache=args.cache,
            funding_path=args.funding,
            filters_path=args.filters,
            commissions_path=args.commissions,
            symbol=candidate["symbol"],
            oos_start_ms=oos_start_ms,
            repo=REPO,
            policy=policy,
        )
    report = qualification.bind_equity_scenario(report, capital_scenario, REPO)
    sealed = seal_holdout_report(
        report,
        candidate,
        args.candidate_manifest,
        args.funding_manifest,
        args.funding,
        repo=REPO,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    target_path = args.output / f"{candidate['symbol']}-{sealed['report_hash'][:16]}.json"
    encoded = json.dumps(sealed, indent=2, sort_keys=True, default=str) + "\n"
    if target_path.exists() and target_path.read_text(encoding="utf-8") != encoded:
        raise ValueError("Immutable holdout report collision")
    target_path.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "event": "FROZEN_CANDIDATE_HOLDOUT_RECORDED",
                "path": str(target_path),
                "decision": sealed["decision"],
                "execution_authority": sealed["execution_authority"],
                "metrics": sealed["metrics"],
                "gates": sealed["gates"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
