"""Verify actual strategy reports without trusting a registry label or declared decision."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from autonomous_futures.execution.account_evidence import finite_decimal
from autonomous_futures.execution.trade_plan import DEFAULT_CAPITAL_POLICY
from autonomous_futures.research.runtime_qualification import content_hash


@dataclass(frozen=True)
class HistoricalQualification:
    family: str
    symbol: str
    report_hash: str
    configuration: dict[str, Any]
    policy: dict[str, Any]
    execution_domain: dict[str, Any] | None = None


@dataclass(frozen=True)
class PortfolioHistoricalQualification:
    portfolio_id: str
    family: str
    symbols: tuple[str, ...]
    report_hash: str
    members: tuple[dict[str, Any], ...]
    metrics: dict[str, Any]
    policy: dict[str, Any]
    selection_hash: str | None = None
    development_report_hash: str | None = None
    development_metrics: dict[str, Any] | None = None
    execution_domain: dict[str, Any] | None = None
    execution_authority: bool = False


def verify_source_index(sources: dict[str, Any], files: list[dict[str, str]], repo: Path) -> None:
    """Every claimed source digest must resolve to verified bytes, including manifests."""
    required: set[str] = set()

    def collect(item: Any) -> None:
        if isinstance(item, str) and len(item) == 64 and all(c in "0123456789abcdef" for c in item):
            required.add(item)
        elif isinstance(item, dict):
            for value in item.values():
                collect(value)
        elif isinstance(item, list):
            for value in item:
                collect(value)

    collect(sources)
    if not required or not files:
        raise ValueError("Qualification has no complete source-file index")
    verified = set()
    seen = set()
    for record in files:
        path = (repo / record["path"]).resolve()
        if not path.is_relative_to(repo.resolve()) or path in seen:
            raise ValueError("Qualification source index has duplicate or outside-repository paths")
        seen.add(path)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != record["sha256"]:
            raise ValueError("Qualification indexed source bytes changed")
        if path.name.endswith(".zip.manifest.json"):
            manifest = json.loads(path.read_bytes())
            archive = path.with_name(path.name.removesuffix(".manifest.json"))
            checksum = archive.with_name(archive.name + ".CHECKSUM")
            expected = manifest["sha256"]
            if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
                raise ValueError("Qualification archive bytes changed behind the manifest")
            words = checksum.read_text(encoding="utf-8").split()
            if len(words) != 2 or words[0] != expected or words[1].lstrip("*") != archive.name:
                raise ValueError("Qualification archive published checksum disagrees with manifest")
        verified.add(sha)
    if not required.issubset(verified):
        raise ValueError("Qualification source-file index omits claimed source hashes")


def verify_historical_report(
    path: Path, *, repo: Path, family: str, symbol: str, approved_sha256: str | None = None
) -> HistoricalQualification:
    raw = path.read_bytes()
    if approved_sha256 is not None and hashlib.sha256(raw).hexdigest() != approved_sha256:
        raise ValueError("Report bytes differ from the reviewed deployment admission")
    report = json.loads(raw)
    identity = report.pop("report_hash", None)
    if identity is None or content_hash(report) != identity:
        raise ValueError("Qualification report hash mismatch")
    if report.get("family") != family or report.get("symbol") != symbol:
        raise ValueError("Qualification does not bind this strategy and symbol")
    if family not in {"MACRO_SCALPER", "ICT_TWINS"} or not report.get("implementation"):
        raise ValueError("Generic or placeholder candidate evidence cannot qualify runtime code")
    if (
        report.get("decision") != "QUALIFIED"
        or not report.get("gates")
        or not all(value is True for value in report["gates"].values())
    ):
        raise ValueError("Genuine runtime qualification gates are not satisfied")
    expected = {
        "src/autonomous_futures/execution/trade_plan.py",
        "src/autonomous_futures/execution/daily_risk.py",
    }
    if family == "ICT_TWINS":
        expected.update(
            {
                "src/autonomous_futures/strategy/ict_mmxm.py",
                "src/autonomous_futures/strategy/pd_array_touch_index.py",
            }
        )
    else:
        expected.add("src/autonomous_futures/strategy/macro_liquidity_scalper.py")
    if not expected.issubset(report["implementation"]):
        raise ValueError("Runtime implementation binding is incomplete")
    for relative, sha in report["implementation"].items():
        source = (repo / relative).resolve()
        if (
            not source.is_relative_to(repo.resolve())
            or hashlib.sha256(source.read_bytes()).hexdigest() != sha
        ):
            raise ValueError("Qualification belongs to another implementation revision")
    sources = report.get("sources", {})
    if not sources:
        raise ValueError("Qualification dataset provenance is missing")
    verify_source_index(sources, report.get("source_files", []), repo)

    def verify_source(item: Any) -> None:
        if isinstance(item, dict):
            if "path" in item and "sha256" in item:
                candidate = Path(item["path"])
                candidate = (
                    candidate.resolve() if candidate.is_absolute() else (repo / candidate).resolve()
                )
                if (
                    not candidate.is_relative_to(repo.resolve())
                    or hashlib.sha256(candidate.read_bytes()).hexdigest() != item["sha256"]
                ):
                    raise ValueError("Qualification source integrity mismatch")
            for value in item.values():
                verify_source(value)
        elif isinstance(item, list):
            for value in item:
                verify_source(value)

    verify_source(sources)
    policy = report["policy"]
    windows = report["windows"]
    if len(windows) != int(policy["windows"]):
        raise ValueError("Qualification windows are incomplete")
    for previous, current in zip(windows, windows[1:], strict=False):
        if int(previous["end_ms"]) != int(current["start_ms"]):
            raise ValueError("Qualification windows overlap or have gaps")
    trades = [trade for window in windows for trade in window["trades"]]
    zero = Decimal("0")
    wins = sum((max(finite_decimal(trade["net_pnl"]), zero) for trade in trades), zero)
    losses = sum((max(-finite_decimal(trade["net_pnl"]), zero) for trade in trades), zero)
    stress = sum((finite_decimal(trade["stress_net_pnl"]) for trade in trades), zero)
    positive_windows = sum(
        sum((finite_decimal(trade["net_pnl"]) for trade in window["trades"]), zero) > 0
        for window in windows
    )
    drawdown = finite_decimal(report["metrics"]["drawdown_usdt"])
    passing = (
        len(trades) >= int(policy["minimum_trades"])
        and wins > losses
        and stress > 0
        and (losses == 0 or wins / losses >= finite_decimal(policy["minimum_profit_factor"]))
        and drawdown / finite_decimal(policy["starting_equity"]) * 100
        <= finite_decimal(policy["maximum_drawdown_pct"])
        and positive_windows >= int(policy["minimum_profitable_windows"])
    )
    if (
        not passing
        or report.get("decision") != "QUALIFIED"
        or not report.get("gates")
        or not all(value is True for value in report["gates"].values())
    ):
        raise ValueError("Genuine runtime qualification gates are not satisfied")
    if (
        "trade_risk_pct" not in policy
        or "daily_loss_pct" not in policy
        or finite_decimal(policy["trade_risk_pct"]) != DEFAULT_CAPITAL_POLICY.trade_risk_pct
        or finite_decimal(policy["daily_loss_pct"]) != DEFAULT_CAPITAL_POLICY.daily_loss_pct
    ):
        raise ValueError(
            "Qualification report risk policy differs from the approved runtime policy"
        )
    # Historical evidence remains only one admission prerequisite. Live microstructure,
    # ownership, capital reference, and confirmed protection are checked independently.
    return HistoricalQualification(
        family,
        symbol,
        str(identity),
        report["configuration"],
        policy,
        report.get("execution_domain"),
    )


def verify_runtime_report(
    path: Path,
    *,
    repo: Path,
    family: str,
    symbol: str,
    admission_manifest_path: Path | None = None,
) -> HistoricalQualification:
    """Require an independently reviewed deployment pin in addition to research gates.

    A report's self-declared hash is integrity metadata, not an execution credential.
    This manifest is deployment configuration and must never be populated from
    uploaded reports or candidate-registry labels by the running trading process.
    """
    manifest_path = admission_manifest_path or (repo / "deploy" / "qualification-admission.json")
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to(repo.resolve()):
        raise ValueError("Qualification admission manifest must be inside the repository")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Qualification admission manifest must be a JSON object")
    if manifest.get("schema") != "runtime-qualification-admission-v1":
        raise ValueError("Unsupported reviewed qualification admission manifest")
    entries = manifest.get("approved_reports", [])
    if not isinstance(entries, list):
        raise ValueError("approved_reports must be a list")
    if any(not isinstance(item, dict) for item in entries):
        raise ValueError("approved_reports entries must be JSON objects")
    identities = [(item["family"], item["symbol"]) for item in entries]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate reviewed qualification identity")
    approved = next(
        (item for item in entries if item["family"] == family and item["symbol"] == symbol), None
    )
    if approved is None:
        raise ValueError("No reviewed deployment admission for this strategy and symbol")
    sha = str(approved["sha256"])
    if len(sha) != 64 or any(character not in "0123456789abcdef" for character in sha):
        raise ValueError("Invalid reviewed qualification digest")
    return verify_historical_report(
        path, repo=repo, family=family, symbol=symbol, approved_sha256=sha
    )


def verify_portfolio_report(
    path: Path,
    *,
    repo: Path,
    family: str,
    symbols: tuple[str, ...],
    portfolio_id: str = "SHARED_WALLET_PORTFOLIO",
    approved_sha256: str | None = None,
    selection_hash: str | None = None,
    development_report_hash: str | None = None,
    development_metrics: dict[str, Any] | None = None,
) -> PortfolioHistoricalQualification:
    """Verify a multi-symbol shared-wallet portfolio qualification receipt."""
    raw = path.read_bytes()
    if approved_sha256 is not None and hashlib.sha256(raw).hexdigest() != approved_sha256:
        raise ValueError("Portfolio report bytes differ from the reviewed deployment admission")
    report = json.loads(raw)
    identity = report.pop("report_hash", None)
    if identity is None or content_hash(report) != identity:
        raise ValueError("Portfolio qualification report hash mismatch")
    if report.get("scope") != "SHARED_WALLET_PORTFOLIO" or report.get("family") != family:
        raise ValueError("Portfolio qualification does not bind this strategy family and scope")
    if family != "MACRO_SCALPER" or not report.get("implementation"):
        raise ValueError("Portfolio qualification requires pinned MACRO_SCALPER implementation")
    expected_symbols = tuple(sorted(symbols))
    by_sym = tuple(sorted(report.get("by_symbol", {}).keys()))
    members = report.get("members", [])
    member_symbols = tuple(sorted({str(m["symbol"]) for m in members}))
    if not expected_symbols or by_sym != expected_symbols or member_symbols != expected_symbols:
        raise ValueError("Portfolio qualification symbols do not match expected universe")
    if (
        report.get("decision") != "QUALIFIED"
        or report.get("execution_authority") is not False
        or not report.get("gates")
        or not all(value is True for value in report["gates"].values())
    ):
        raise ValueError("Portfolio qualification gates or safety flags are not satisfied")
    expected_impl = {
        "src/autonomous_futures/execution/trade_plan.py",
        "src/autonomous_futures/execution/daily_risk.py",
        "src/autonomous_futures/strategy/macro_liquidity_scalper.py",
        "src/autonomous_futures/research/runtime_qualification.py",
        "src/autonomous_futures/research/portfolio_qualification.py",
    }
    if not expected_impl.issubset(report["implementation"]):
        raise ValueError("Portfolio implementation binding is incomplete")
    for relative, sha in report["implementation"].items():
        source = (repo / relative).resolve()
        if (
            not source.is_relative_to(repo.resolve())
            or hashlib.sha256(source.read_bytes()).hexdigest() != sha
        ):
            raise ValueError("Portfolio qualification belongs to another implementation revision")

    sources = report.get("sources", {})
    source_files = report.get("source_files", [])
    if not sources or not source_files:
        raise ValueError("Portfolio qualification dataset provenance is missing")
    claimed_digests: set[str] = set()

    def collect_digests(item: Any) -> None:
        if isinstance(item, str) and len(item) == 64 and all(c in "0123456789abcdef" for c in item):
            claimed_digests.add(item)
        elif isinstance(item, dict):
            for value in item.values():
                collect_digests(value)
        elif isinstance(item, list):
            for value in item:
                collect_digests(value)

    collect_digests(sources)
    indexed_digests: set[str] = set()
    seen_paths: set[Path] = set()
    for record in source_files:
        rel = str(record["path"])
        rec_path = (repo / rel).resolve()
        if not rec_path.is_relative_to(repo.resolve()) or rec_path in seen_paths:
            raise ValueError("Portfolio source index has duplicate or outside-repository paths")
        seen_paths.add(rec_path)
        rec_sha = str(record["sha256"])
        if rel.startswith("artifacts/qualification/") or rec_path.is_file():
            if not rec_path.is_file():
                raise ValueError(f"Required portfolio runtime input file missing: {rel}")
            if hashlib.sha256(rec_path.read_bytes()).hexdigest() != rec_sha:
                raise ValueError("Portfolio indexed source bytes changed")
        indexed_digests.add(rec_sha)
    if not claimed_digests.issubset(indexed_digests):
        raise ValueError("Portfolio source-file index omits claimed source hashes")

    policy = report["policy"]
    windows = report["windows"]
    metrics = report["metrics"]
    if len(windows) != int(policy["windows"]):
        raise ValueError("Portfolio qualification windows are incomplete")
    for previous, current in zip(windows, windows[1:], strict=False):
        if int(previous["end_ms"]) != int(current["start_ms"]):
            raise ValueError("Portfolio qualification windows overlap or have gaps")
    trades = [trade for window in windows for trade in window["trades"]]
    zero = Decimal("0")
    wins = sum((max(finite_decimal(trade["net_pnl"]), zero) for trade in trades), zero)
    losses = sum((max(-finite_decimal(trade["net_pnl"]), zero) for trade in trades), zero)
    stress = sum((finite_decimal(trade["stress_net_pnl"]) for trade in trades), zero)
    positive_windows = sum(
        sum((finite_decimal(trade["net_pnl"]) for trade in window["trades"]), zero) > 0
        for window in windows
    )
    drawdown = finite_decimal(metrics["drawdown_usdt"])
    wallet_drift = abs(finite_decimal(metrics["max_wallet_drift"]))
    equity_drift = abs(finite_decimal(metrics["max_equity_drift"]))
    passing = (
        len(trades) >= int(policy["minimum_trades"])
        and wins > losses
        and stress > 0
        and (losses == 0 or wins / losses >= finite_decimal(policy["minimum_profit_factor"]))
        and drawdown / finite_decimal(policy["starting_equity"]) * 100
        <= finite_decimal(policy["maximum_drawdown_pct"])
        and positive_windows >= int(policy["minimum_profitable_windows"])
        and wallet_drift == zero
        and equity_drift == zero
    )
    if not passing:
        raise ValueError("Genuine portfolio qualification gates are not satisfied")
    if (
        "trade_risk_pct" not in policy
        or "daily_loss_pct" not in policy
        or finite_decimal(policy["trade_risk_pct"]) != DEFAULT_CAPITAL_POLICY.trade_risk_pct
        or finite_decimal(policy["daily_loss_pct"]) != DEFAULT_CAPITAL_POLICY.daily_loss_pct
    ):
        raise ValueError(
            "Portfolio qualification report risk policy differs from the approved runtime policy"
        )
    execution_domain: dict[str, Any] | None = report.get("execution_domain")
    cap_scenario = report.get("capital_scenario")
    if (
        execution_domain is None
        and isinstance(cap_scenario, dict)
        and cap_scenario.get("schema") == "authenticated-testnet-equity-scenario-v1"
        and cap_scenario.get("wallet_and_equity_reconciled") is True
    ):
        starting_eq = finite_decimal(policy["starting_equity"])
        max_dd_pct = finite_decimal(policy["maximum_drawdown_pct"])
        ending_eq = finite_decimal(metrics["ending_equity"])
        dev_ending_eq = (
            finite_decimal(development_metrics["ending_equity"])
            if development_metrics and "ending_equity" in development_metrics
            else ending_eq
        )
        min_eq = (starting_eq * (Decimal("100") - max_dd_pct) / Decimal("100")).quantize(
            Decimal("0.00000001")
        )
        max_eq = (max(starting_eq, ending_eq, dev_ending_eq) * Decimal("1.10")).quantize(
            Decimal("0.00000001")
        )
        execution_domain = {
            "schema": "researched-execution-domain-v1",
            "testnet": bool(cap_scenario.get("testnet", True)),
            "equity_basis": "ACCOUNT",
            "minimum_equity": str(min_eq),
            "maximum_equity": str(max_eq),
            "daily_loss_pct": str(policy["daily_loss_pct"]),
            "trade_risk_pct": str(policy["trade_risk_pct"]),
            "leverages": [1],
            "maximum_concurrent_symbols": len(expected_symbols),
            "symbols": list(expected_symbols),
        }
    enriched_metrics = dict(metrics)
    if "profit_factor" not in enriched_metrics:
        enriched_metrics["profit_factor"] = (
            str((wins / losses).quantize(Decimal("0.01"))) if losses > 0 else "INF"
        )
    return PortfolioHistoricalQualification(
        portfolio_id=portfolio_id,
        family=family,
        symbols=expected_symbols,
        report_hash=str(identity),
        members=tuple(members),
        metrics=enriched_metrics,
        policy=dict(policy),
        selection_hash=selection_hash,
        development_report_hash=development_report_hash,
        development_metrics=development_metrics,
        execution_domain=execution_domain,
        execution_authority=False,
    )


def verify_runtime_portfolio_report(
    path: Path,
    *,
    repo: Path,
    portfolio_id: str,
    admission_manifest_path: Path | None = None,
) -> PortfolioHistoricalQualification:
    """Verify a portfolio receipt against its environment-specific admission manifest."""
    manifest_path = admission_manifest_path or (repo / "deploy" / "qualification-admission.json")
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to(repo.resolve()):
        raise ValueError("Qualification admission manifest must be inside the repository")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Qualification admission manifest must be a JSON object")
    if manifest.get("schema") != "runtime-qualification-admission-v1":
        raise ValueError("Unsupported reviewed qualification admission manifest")
    entries = manifest.get("approved_portfolio_reports", [])
    if not isinstance(entries, list):
        raise ValueError("approved_portfolio_reports must be a list")
    if any(not isinstance(item, dict) for item in entries):
        raise ValueError("approved_portfolio_reports entries must be JSON objects")
    ids = [str(item["portfolio_id"]) for item in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate reviewed portfolio qualification identity")
    approved = next((item for item in entries if item.get("portfolio_id") == portfolio_id), None)
    if approved is None:
        raise ValueError("No reviewed deployment admission for this portfolio")
    if approved.get("execution_authority") is not False:
        raise ValueError("Portfolio admission manifest cannot grant direct execution authority")

    sel_path = (repo / str(approved["selection_manifest_path"])).resolve()
    if not sel_path.is_relative_to(repo.resolve()) or not sel_path.is_file():
        raise ValueError("Portfolio selection manifest missing or outside repository")
    sel_bytes = sel_path.read_bytes()
    if hashlib.sha256(sel_bytes).hexdigest() != str(approved["selection_manifest_sha256"]):
        raise ValueError("Portfolio selection manifest SHA-256 mismatch")
    sel_data = json.loads(sel_bytes)
    sel_body = dict(sel_data)
    sel_hash = sel_body.pop("selection_hash", None)
    if (
        sel_hash is None
        or content_hash(sel_body) != sel_hash
        or sel_hash != str(approved["selection_hash"])
    ):
        raise ValueError("Portfolio selection manifest content hash mismatch")

    dev_path = (repo / str(approved["development_report_path"])).resolve()
    if not dev_path.is_relative_to(repo.resolve()) or not dev_path.is_file():
        raise ValueError("Portfolio development report missing or outside repository")
    dev_bytes = dev_path.read_bytes()
    if hashlib.sha256(dev_bytes).hexdigest() != str(approved["development_report_sha256"]):
        raise ValueError("Portfolio development report SHA-256 mismatch")
    dev_data = json.loads(dev_bytes)
    dev_body = dict(dev_data)
    dev_hash = dev_body.pop("report_hash", None)
    if (
        dev_hash is None
        or content_hash(dev_body) != dev_hash
        or dev_hash != str(approved["development_report_hash"])
        or dev_data.get("portfolio_decision_on_development_sample") != "QUALIFIED"
        or not all(value is True for value in dev_data.get("gates", {}).values())
    ):
        raise ValueError("Portfolio development qualification receipt is invalid")

    holdout_sha = str(approved["holdout_report_sha256"])
    if len(holdout_sha) != 64 or any(c not in "0123456789abcdef" for c in holdout_sha):
        raise ValueError("Invalid reviewed portfolio holdout digest")
    receipt = verify_portfolio_report(
        path,
        repo=repo,
        family=str(approved["family"]),
        symbols=tuple(str(s) for s in approved["symbols"]),
        portfolio_id=portfolio_id,
        approved_sha256=holdout_sha,
        selection_hash=str(sel_hash),
        development_report_hash=str(dev_hash),
        development_metrics=dict(dev_data.get("metrics", {})),
    )
    if receipt.report_hash != str(approved["holdout_report_hash"]):
        raise ValueError("Portfolio holdout report hash disagrees with admission manifest")
    return receipt
