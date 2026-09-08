"""Offline audit of the adjacent frozen paper snapshot; no runtime writes."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path


def audit():
    source = Path(__file__).with_name("exit-cost-snapshot.json").read_bytes()
    data = json.loads(source)
    opens = {}
    closes = {}
    sequences = set()
    for event in data["events"]:
        assert event["sequence"] > data["after_sequence"]
        assert event["sequence"] not in sequences
        sequences.add(event["sequence"])
        assert event["event"] in ("open", "close")
        target = opens if event["event"] == "open" else closes
        assert event["trade_id"] not in target
        target[event["trade_id"]] = event
    marks = {m["trade_id"]: json.loads(m["payload"]) for m in data["marks"]}
    groups = {}
    for tid, close in closes.items():
        entry = opens[tid]
        for key in ("candidate_id", "candidate_artifact_hash", "symbol", "side", "quantity"):
            assert entry[key] == close[key], (tid, key)
        assert entry["sequence"] < close["sequence"]
        mark = marks.get(tid, {})
        reason = "unavailable"
        if mark.get("lifecycle_status") == "closed" and mark.get("reason_codes"):
            reason = mark["reason_codes"][-1]
        gross, net, entry_fee, exit_fee = (
            Decimal(close[k]) for k in ("gross_pnl", "net_pnl", "entry_fee", "exit_fee")
        )
        assert all(x.is_finite() for x in (gross, net, entry_fee, exit_fee))
        assert entry_fee == Decimal(entry["entry_fee"])
        assert entry_fee >= 0 and exit_fee >= 0
        assert net == gross - entry_fee - exit_fee, tid
        key = (close["candidate_id"], close["candidate_artifact_hash"], close["symbol"], reason)
        group = groups.setdefault(
            key, {"count": 0, "wins": 0, "gross": Decimal(0), "fees": Decimal(0), "net": Decimal(0)}
        )
        group["count"] += 1
        group["wins"] += net > 0
        group["gross"] += gross
        group["fees"] += entry_fee + exit_fee
        group["net"] += net
    rows = [
        dict(
            zip(("candidate_id", "artifact_hash", "symbol", "exit_reason"), key, strict=True),
            **value,
        )
        for key, value in sorted(groups.items())
    ]
    return {
        "snapshot_sha256": hashlib.sha256(source).hexdigest(),
        "observed_at": data["observed_at"],
        "closed_count": len(closes),
        "excluded_open_count": len(set(opens) - set(closes)),
        "gross": sum((r["gross"] for r in rows), Decimal(0)),
        "fees": sum((r["fees"] for r in rows), Decimal(0)),
        "net": sum((r["net"] for r in rows), Decimal(0)),
        "groups": rows,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), default=str, indent=2, sort_keys=True))
