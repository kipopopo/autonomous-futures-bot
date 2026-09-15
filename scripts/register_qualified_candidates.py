"""Deterministic registration of qualified multi-timeframe strategies into paper candidate registry.

Evaluates candidate strategies across canonical Parquet data windows, verifies
walk-forward qualification gates (profit factor >= 1.05, worst max drawdown <= 15%),
persists immutable candidate and qualification artifacts, and atomically updates
the paper candidate registry manifest (artifacts/paper_live/candidate_registry.json).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure repo root and src/ are on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    CandidateManifestEntry,
    CandidateRegistryManifest,
    build_candidate_registry_manifest,
    read_candidate_registry,
    validate_manifest_candidate_artifacts,
    write_candidate_registry,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
    write_creator_candidate_artifact,
)
from autonomous_futures.research.qualification_artifacts import (  # noqa: E402
    WalkForwardQualificationPolicy,
    read_creator_candidate_qualification_artifact,
    write_creator_candidate_qualification_artifact,
)
from scripts.explore_offline_strategies import (  # noqa: E402
    evaluate_candidate_offline,
    generate_candidate_catalog,
    load_and_slice_windows,
)

logger = logging.getLogger(__name__)

# Canonical qualified candidates across 15m and 1h exploration
DEFAULT_QUALIFIED_TARGETS: tuple[dict[str, Any], ...] = (
    {
        "symbol": "ETHUSDT",
        "candidate_id": "cand-ethusdt-dcb-003",
        "timeframe": "15m",
        "parquet_path": Path("research/immutable-data/15m/canonical/ETHUSDT-15m.parquet"),
        "bars_per_window": 288,
        "windows_count": 4,
    },
    {
        "symbol": "BTCUSDT",
        "candidate_id": "cand-btcusdt-dcb-002",
        "timeframe": "15m",
        "parquet_path": Path("research/immutable-data/15m/canonical/BTCUSDT-15m.parquet"),
        "bars_per_window": 192,
        "windows_count": 3,
    },
    {
        "symbol": "SOLUSDT",
        "candidate_id": "cand-solusdt-rgb-001",
        "timeframe": "1h",
        "parquet_path": Path("research/immutable-data/1h/canonical/SOLUSDT-1h.parquet"),
        "bars_per_window": 168,
        "windows_count": 3,
    },
)


def register_qualified_candidates(
    targets: Sequence[dict[str, Any]] = DEFAULT_QUALIFIED_TARGETS,
    *,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    candidates_dir: Path | str = Path("artifacts/paper_live/candidates"),
    qualifications_dir: Path | str = Path("artifacts/paper_live/qualifications"),
    policy: WalkForwardQualificationPolicy | None = None,
    admitted_at: datetime | None = None,
    registry_version: int = 2,
) -> tuple[CandidateRegistryManifest, list[dict[str, Any]]]:
    """Evaluate and register qualified strategies into the candidate registry manifest.

    Raises DomainViolation if any target candidate fails qualification.
    """
    reg_path = Path(registry_path)
    cand_dir = Path(candidates_dir)
    qual_dir = Path(qualifications_dir)
    cand_dir.mkdir(parents=True, exist_ok=True)
    qual_dir.mkdir(parents=True, exist_ok=True)

    admission_time = admitted_at or datetime.now(UTC)
    admission_time_iso = admission_time.isoformat()

    qual_policy = policy or WalkForwardQualificationPolicy(
        policy_id="policy-offline-screen-001",
        minimum_windows=1,
        minimum_trades=5,
        minimum_profit_factor=Decimal("1.05"),
        maximum_drawdown_pct=Decimal("15.0"),
        minimum_average_return_pct=Decimal("0.0"),
    )

    manifest_entries: dict[str, CandidateManifestEntry] = {}
    audit_records: list[dict[str, Any]] = []

    # Preserve any existing entries for symbols not in targets if manifest exists
    if reg_path.is_file():
        try:
            prior = read_candidate_registry(reg_path, verify_hash=True)
            for sym, prior_entry in prior.symbols.items():
                manifest_entries[sym] = prior_entry
        except Exception as exc:
            logger.warning("Could not load prior manifest at %s: %s", reg_path, exc)

    for target in targets:
        symbol = str(target["symbol"]).upper()
        candidate_id = str(target["candidate_id"])
        timeframe = str(target["timeframe"])
        parquet_file = Path(target["parquet_path"])
        bars_per_window = int(target.get("bars_per_window", 192))
        windows_count = int(target.get("windows_count", 3))

        if not parquet_file.is_file():
            raise FileNotFoundError(f"Canonical parquet file missing for {symbol}: {parquet_file}")

        cand_artifact_path = cand_dir / f"{candidate_id}.json"
        qual_artifact_path = qual_dir / f"qual-{candidate_id}.json"

        # 1. Generate or read existing candidate artifact
        cand: CreatorCandidateArtifact
        if cand_artifact_path.is_file():
            cand = read_creator_candidate_artifact(cand_artifact_path)
        else:
            catalog = generate_candidate_catalog(
                symbol, timeframe=timeframe, created_at=admission_time
            )
            found = next((c for c in catalog if c.candidate_id == candidate_id), None)
            if found is None:
                raise DomainViolation(
                    f"Candidate {candidate_id} not found in catalog for {symbol} ({timeframe})"
                )
            cand = found

        # 2. Slice walk-forward windows and evaluate offline (or read existing qualification)
        if qual_artifact_path.is_file():
            qual_artifact = read_creator_candidate_qualification_artifact(qual_artifact_path)
            pf_val = next(
                (str(m.value) for m in qual_artifact.metrics if "profit_factor" in m.metric_id),
                "None",
            )
            dd_val = next(
                (str(m.value) for m in qual_artifact.metrics if "drawdown" in m.metric_id),
                "0.0",
            )
            pnl_val = next(
                (str(m.value) for m in qual_artifact.metrics if "net_pnl" in m.metric_id),
                "0.0",
            )
            summary = {
                "profit_factor": pf_val,
                "worst_drawdown_pct": dd_val,
                "pooled_net_pnl": pnl_val,
                "failed_gate_ids": [g.gate_id for g in qual_artifact.gates if not g.passed],
            }
        else:
            windows = load_and_slice_windows(
                parquet_file,
                symbol=symbol,
                timeframe=timeframe,
                windows_count=windows_count,
                bars_per_window=bars_per_window,
            )
            qual_artifact, summary = evaluate_candidate_offline(cand, windows, qual_policy)

        if qual_artifact.decision != "qualified":
            raise DomainViolation(
                f"Candidate {candidate_id} failed qualification: "
                f"decision={qual_artifact.decision}, "
                f"failed_gates={summary['failed_gate_ids']}"
            )

        # 3. Write immutable candidate artifact
        write_creator_candidate_artifact(cand_artifact_path, cand)

        # 4. Write immutable qualification artifact
        write_creator_candidate_qualification_artifact(qual_artifact_path, qual_artifact)

        # 5. Build relative manifest entry path
        # Normalize relative to project root / current working directory
        try:
            rel_art_path = cand_artifact_path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            rel_art_path = cand_artifact_path.as_posix()

        entry = CandidateManifestEntry(
            candidate_id=candidate_id,
            candidate_artifact_hash=cand.artifact_hash,
            artifact_path=rel_art_path,
            qualification_hash=qual_artifact.qualification_hash,
            admitted_at=admission_time_iso,
        )
        manifest_entries[symbol] = entry

        audit_records.append(
            {
                "symbol": symbol,
                "candidate_id": candidate_id,
                "timeframe": timeframe,
                "family": cand.strategy.family,
                "profit_factor": summary["profit_factor"],
                "worst_drawdown_pct": summary["worst_drawdown_pct"],
                "pooled_net_pnl": summary["pooled_net_pnl"],
                "candidate_artifact_hash": cand.artifact_hash,
                "qualification_hash": qual_artifact.qualification_hash,
                "artifact_path": rel_art_path,
                "status": "admitted",
            }
        )

    # 6. Build and atomically persist CandidateRegistryManifest
    manifest = build_candidate_registry_manifest(
        symbols=manifest_entries,
        updated_at=admission_time_iso,
        registry_version=registry_version,
    )
    written_manifest = write_candidate_registry(reg_path, manifest)

    # 7. Validate full integrity
    validate_manifest_candidate_artifacts(written_manifest)

    return written_manifest, audit_records


def verify_existing_registry(
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    base_dir: Path | None = None,
) -> tuple[CandidateRegistryManifest, dict[str, CreatorCandidateArtifact]]:
    """Validate that existing candidate registry manifest and artifacts pass integrity checks."""
    manifest = read_candidate_registry(registry_path, verify_hash=True)
    artifacts = validate_manifest_candidate_artifacts(manifest, base_dir=base_dir)
    return manifest, artifacts


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for candidate registration."""
    parser = argparse.ArgumentParser(
        description="Register qualified multi-timeframe strategies into paper candidate registry."
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_CANDIDATE_REGISTRY_PATH,
        help=f"Path to candidate registry manifest (default: {DEFAULT_CANDIDATE_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--candidates-dir",
        type=Path,
        default=Path("artifacts/paper_live/candidates"),
        help="Directory to store candidate JSON artifacts",
    )
    parser.add_argument(
        "--qualifications-dir",
        type=Path,
        default=Path("artifacts/paper_live/qualifications"),
        help="Directory to store qualification JSON artifacts",
    )
    parser.add_argument(
        "--registry-version",
        type=int,
        default=2,
        help="Candidate registry version (default: 2)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify existing registry manifest and candidate artifacts without modifying",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON summary",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.check_only:
        try:
            manifest, artifacts = verify_existing_registry(args.registry_path)
            if args.json:
                sys.stdout.write(
                    json.dumps(
                        {
                            "status": "verified",
                            "registry_hash": manifest.registry_hash,
                            "registry_version": manifest.registry_version,
                            "updated_at": manifest.updated_at,
                            "symbols": list(manifest.symbols.keys()),
                        },
                        indent=2,
                    )
                    + "\n"
                )
            else:
                sys.stdout.write(
                    f"Candidate registry at {args.registry_path} is VALID.\n"
                    f"Registry Hash: {manifest.registry_hash}\n"
                    f"Registry Version: {manifest.registry_version}\n"
                    f"Symbols: {', '.join(manifest.symbols.keys())}\n"
                )
            return 0
        except Exception as exc:
            sys.stderr.write(f"Candidate registry verification failed: {exc}\n")
            return 1

    try:
        manifest, records = register_qualified_candidates(
            registry_path=args.registry_path,
            candidates_dir=args.candidates_dir,
            qualifications_dir=args.qualifications_dir,
            registry_version=args.registry_version,
        )
    except Exception as exc:
        sys.stderr.write(f"Failed to register qualified candidates: {exc}\n")
        return 1

    if args.json:
        out = {
            "status": "registered",
            "registry_hash": manifest.registry_hash,
            "registry_version": manifest.registry_version,
            "updated_at": manifest.updated_at,
            "admitted_candidates": records,
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0

    sys.stdout.write("\n=== CANDIDATE STRATEGY ADMISSION REGISTRY ===\n")
    sys.stdout.write(f"Registry Path: {args.registry_path}\n")
    sys.stdout.write(f"Registry Hash: {manifest.registry_hash}\n")
    sys.stdout.write(f"Updated At:    {manifest.updated_at}\n")
    sys.stdout.write("-" * 115 + "\n")
    header = (
        f"{'Symbol':<10} {'Candidate ID':<24} {'TF':<6} {'Family':<26} "
        f"{'PF':<8} {'MaxDD %':<9} {'Net PnL':<10} {'Status':<10}"
    )
    sys.stdout.write(header + "\n")
    sys.stdout.write("-" * 115 + "\n")
    for rec in records:
        pf = rec["profit_factor"][:6]
        dd = rec["worst_drawdown_pct"][:6]
        pnl = rec["pooled_net_pnl"][:8]
        sys.stdout.write(
            f"{rec['symbol']:<10} {rec['candidate_id']:<24} {rec['timeframe']:<6} "
            f"{rec['family']:<26} {pf:<8} {dd:<9} {pnl:<10} {rec['status']:<10}\n"
        )
    sys.stdout.write("-" * 115 + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
