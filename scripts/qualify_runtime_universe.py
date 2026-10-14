"""Run frozen per-pair qualification with bounded local subprocess concurrency."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "SUIUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "LINKUSDT",
    "APTUSDT",
    "ADAUSDT",
)


def run(
    symbol: str,
    family: str,
    commissions: Path | None,
    output: Path,
    worker_count: int,
    entry_mode: str = "limit_touch",
    starting_equity: Decimal | None = None,
    equity_evidence_path: Path | None = None,
) -> dict[str, str | int]:
    if family not in {"ict", "scalper"}:
        raise ValueError("Unsupported qualification family")
    if commissions is None:
        raise ValueError("Qualification requires commission data")
    if family == "ict" and entry_mode not in {"limit_touch", "reclaim_retest"}:
        raise ValueError("Unsupported ICT entry mode")
    if family == "scalper" and entry_mode != "limit_touch":
        raise ValueError("Entry mode applies only to ICT qualification")
    if starting_equity is not None and equity_evidence_path is not None:
        raise ValueError("Choose either a starting-equity value or an equity-evidence snapshot")
    if starting_equity is not None and (not starting_equity.is_finite() or starting_equity <= 0):
        raise ValueError("Starting equity must be a positive finite Decimal")
    output.mkdir(parents=True, exist_ok=True)
    cache = REPO / "research/immutable-data/runtime-official-20261013"
    script = "qualify_runtime_ict.py" if family == "ict" else "qualify_runtime_scalper.py"
    command = [
        sys.executable,
        "-X",
        "utf8",
        str(REPO / "scripts" / script),
        "--symbol",
        symbol,
        "--cache",
        str(cache),
        "--output",
        str(output),
    ]
    command.extend(["--commissions", str(commissions)])
    if family == "ict":
        command.extend(["--entry-mode", entry_mode])
    else:
        command.extend(["--funding", str(cache / "funding" / f"{symbol}-funding.csv")])
    if starting_equity is not None:
        command.extend(["--starting-equity", str(starting_equity)])
    if equity_evidence_path is not None:
        command.extend(["--equity-evidence", str(equity_evidence_path)])
    log = output / f"{symbol}-process.jsonl"
    with log.open("x", encoding="utf-8") as destination:
        process = subprocess.run(
            command, cwd=REPO, stdout=destination, stderr=subprocess.STDOUT, check=False
        )
    result: dict[str, str | int] = {
        "family": family,
        "symbol": symbol,
        "worker_count": worker_count,
        "exit_code": process.returncode,
        "log": str(log),
    }
    if family == "ict":
        result["entry_mode"] = entry_mode
    if starting_equity is not None:
        result["starting_equity"] = str(starting_equity)
    if equity_evidence_path is not None:
        result["equity_evidence"] = str(equity_evidence_path)
    print(json.dumps(result), flush=True)
    return result


def select_symbols(family: str, include: list[str] | None, exclude: list[str]) -> list[str]:
    """Resolve an explicit, validated symbol partition from the canonical universe."""
    if family not in {"ict", "scalper"}:
        raise ValueError("Unsupported qualification family")
    eligible = tuple(symbol for symbol in SYMBOLS if family == "ict" or symbol != "BTCUSDT")
    if len(set(include or ())) != len(include or ()):
        raise ValueError("--include contains duplicate symbols")
    if len(set(exclude)) != len(exclude):
        raise ValueError("--exclude contains duplicate symbols")
    unknown = (set(include or ()) | set(exclude)) - set(SYMBOLS)
    if unknown:
        raise ValueError(f"Unknown universe symbols: {', '.join(sorted(unknown))}")
    if include is not None and not set(include) <= set(eligible):
        raise ValueError(f"--include contains symbols unavailable to {family}")
    overlap = set(include or ()) & set(exclude)
    if overlap:
        joined = ", ".join(sorted(overlap))
        raise ValueError(f"Symbols cannot be both included and excluded: {joined}")
    selected = [
        symbol
        for symbol in eligible
        if (include is None or symbol in include) and symbol not in exclude
    ]
    if not selected:
        raise ValueError("The selected qualification partition is empty")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=["ict", "scalper"], required=True)
    parser.add_argument(
        "--commissions",
        type=Path,
        required=True,
        help="Authenticated Testnet commission snapshot bound into every pair report.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--entry-mode",
        choices=["limit_touch", "reclaim_retest"],
        default="limit_touch",
        help="Freeze the ICT entry model; only applies when --family=ict.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        help="Run only these symbols; repeat for each symbol in an explicit batch.",
    )
    parser.add_argument("--exclude", action="append", default=[])
    capital = parser.add_mutually_exclusive_group()
    capital.add_argument("--starting-equity", type=Decimal)
    capital.add_argument("--equity-evidence", type=Path)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        raise SystemExit("--workers must be between 1 and 4 on this bounded runner")
    if args.family == "scalper" and args.entry_mode != "limit_touch":
        parser.error("--entry-mode applies only when --family=ict")
    try:
        symbols = select_symbols(args.family, args.include, args.exclude)
    except ValueError as exc:
        parser.error(str(exc))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(
                run,
                symbol,
                args.family,
                args.commissions,
                args.output,
                args.workers,
                args.entry_mode,
                args.starting_equity,
                args.equity_evidence,
            )
            for symbol in symbols
        ]
        results = [future.result() for future in futures]
    args.output.joinpath("process-results.json").write_bytes(
        (json.dumps(results, indent=2) + "\n").encode()
    )
    if any(result["exit_code"] != 0 for result in results):
        raise SystemExit("Some qualification processes failed; inspect their preserved logs")


if __name__ == "__main__":
    main()
