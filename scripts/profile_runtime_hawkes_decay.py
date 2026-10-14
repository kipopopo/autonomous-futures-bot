"""Profile Hawkes decay on recorded Testnet traces; outputs diagnostic-only evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS  # noqa: E402
from autonomous_futures.feed.measured_hawkes import Arrival, fit_arrivals  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_current_generation(path: Path) -> tuple[list[Arrival], int, int]:
    rows: list[tuple[int | None, dict[str, Any]]] = []
    max_generation = 0
    explicit_generation = True
    for line in path.open(encoding="utf-8"):
        record = json.loads(line)
        if "generation_before_ingest" not in record:
            explicit_generation = False
            generation = None
        else:
            generation = int(record["generation_before_ingest"])
            max_generation = max(max_generation, generation)
        payload = record.get("payload", {})
        data = payload.get("data", payload)
        rows.append((generation, data))
    if explicit_generation:
        arrivals = [
            Arrival(str(data["s"]), int(data["T"]), int(data["a"]))
            for generation, data in rows
            if generation == max_generation and data.get("e") == "aggTrade"
        ]
        return arrivals, max_generation, sum(data.get("e") == "aggTrade" for _, data in rows)

    # Older diagnostic traces omit the monitor generation. Reconstruct the same
    # fail-closed resets from genuine aggregate-trade and depth sequence breaks.
    generation = 0
    trade_ids: dict[str, int] = {}
    depth_ids: dict[str, int] = {}
    tagged: list[tuple[int, Arrival]] = []
    all_arrivals = 0
    for _, data in rows:
        event = data.get("e")
        symbol = str(data.get("s", ""))
        gap = (
            event == "aggTrade"
            and symbol in trade_ids
            and int(data["a"]) != trade_ids[symbol] + 1
        ) or (
            event == "depthUpdate"
            and symbol in depth_ids
            and data.get("pu") is not None
            and int(data["pu"]) != depth_ids[symbol]
        )
        if gap:
            generation += 1
            trade_ids.clear()
            depth_ids.clear()
        if event == "aggTrade":
            identity = int(data["a"])
            trade_ids[symbol] = identity
            all_arrivals += 1
            tagged.append((generation, Arrival(symbol, int(data["T"]), identity)))
        elif event == "depthUpdate":
            depth_ids[symbol] = int(data["u"])
    selected = [arrival for tag, arrival in tagged if tag == generation]
    return selected, generation, all_arrivals


def profile(trace: Path, betas: list[float]) -> dict[str, Any]:
    arrivals, generation, all_generation_arrivals = read_current_generation(trace)
    counts = Counter(arrival.symbol for arrival in arrivals)
    fits = []
    for beta in betas:
        try:
            result = fit_arrivals(arrivals, tuple(ACTIVE_PAIRS), beta=beta)
        except (ValueError, ArithmeticError) as exc:
            fits.append({"beta": beta, "accepted_for_diagnostic": False, "error": str(exc)})
            continue
        fits.append(
            {
                "beta": beta,
                "accepted_for_diagnostic": not result.baseline_boundary_symbols,
                "spectral_radius": result.spectral_radius,
                "baseline_boundary_symbols": result.baseline_boundary_symbols,
                "baseline": result.baseline,
                "counts_after_burn_in": result.counts,
                "log_likelihood": result.log_likelihood,
                "arrivals_sha256": result.arrivals_sha256,
            }
        )
    return {
        "trace_path": str(trace.resolve().relative_to(REPO)),
        "trace_sha256": digest(trace),
        "generation": generation,
        "trade_arrivals_in_current_generation": len(arrivals),
        "trade_arrivals_all_generations": all_generation_arrivals,
        "counts_current_generation": dict(sorted(counts.items())),
        "fits": fits,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", action="append", type=Path, required=True)
    parser.add_argument("--beta", action="append", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(not path.is_file() for path in args.trace):
        raise SystemExit("Every trace must be an existing recorded file")
    invalid_beta = any(not math.isfinite(beta) or beta <= 0 for beta in args.beta)
    if invalid_beta or len(set(args.beta)) != len(args.beta):
        raise SystemExit("Beta values must be positive, finite, and unique")
    traces = [profile(path, args.beta) for path in args.trace]
    valid_beta_sets = [
        {
            float(fit["beta"])
            for fit in trace["fits"]
            if fit["accepted_for_diagnostic"] is True
        }
        for trace in traces
    ]
    common_valid = set.intersection(*valid_beta_sets) if valid_beta_sets else set()
    output = {
        "schema": "hawkes-decay-profile-diagnostic-v1",
        "source": "recorded_testnet_market_streams",
        "execution_authority": False,
        "qualification": False,
        "symbols": list(ACTIVE_PAIRS),
        "beta_candidates_per_second": args.beta,
        "selection_rule": (
            "smallest candidate beta with no baseline-boundary symbols "
            "in every supplied trace"
        ),
        "selected_beta_per_second": min(common_valid) if common_valid else None,
        "implementation_sha256": {
            str(path.relative_to(REPO)): digest(path)
            for path in (Path(__file__), REPO / "src/autonomous_futures/feed/measured_hawkes.py")
        },
        "traces": traces,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as destination:
        destination.write(json.dumps(output, indent=2, default=str) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
