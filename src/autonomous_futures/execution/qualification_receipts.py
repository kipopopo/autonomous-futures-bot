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
    path: Path, *, repo: Path, family: str, symbol: str
) -> HistoricalQualification:
    """Require an independently reviewed deployment pin in addition to research gates.

    A report's self-declared hash is integrity metadata, not an execution credential.
    This manifest is deployment configuration and must never be populated from
    uploaded reports or candidate-registry labels by the running trading process.
    """
    manifest_path = repo / "deploy" / "qualification-admission.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "runtime-qualification-admission-v1":
        raise ValueError("Unsupported reviewed qualification admission manifest")
    entries = manifest["approved_reports"]
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
