"""Durable causal state for ICT close-reclaim maker entries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from autonomous_futures.execution.account_evidence import atomic_json
from autonomous_futures.execution.lifecycle_coordinator import restore_plan
from autonomous_futures.execution.trade_plan import TradePlan
from autonomous_futures.research.ict_runtime_qualification import has_close_reclaim
from autonomous_futures.strategy.ict_mmxm import Candle

ENTRY_TTL_MS = 300_000
MINUTE_MS = 60_000
SCHEMA = "ict-reclaim-entry-state-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass
class ReclaimCandidate:
    plan: TradePlan
    report_path: str
    report_hash: str
    last_processed_candle_ms: int
    expires_ms: int
    stage: Literal["WAIT_RECLAIM", "DISPATCHED"] = "WAIT_RECLAIM"
    readiness_ms: int | None = None


class IctReclaimEntryStore:
    """Persist one evidence-bound reclaim candidate per ICT pair.

    The scanner submits the maker intention only after a completed minute candle
    touches and reclaims the CISD line. A later exchange fill remains authoritative.
    """

    def __init__(self, path: Path, repo: Path) -> None:
        self.path = path
        self.repo = repo.resolve()
        self.candidates: dict[str, ReclaimCandidate] = {}
        if path.exists():
            self._load(json.loads(path.read_text(encoding="utf-8")))

    def _load(self, body: object) -> None:
        if not isinstance(body, dict) or body.get("schema") != SCHEMA:
            raise ValueError("Persisted ICT reclaim state has an unsupported schema")
        raw = body.get("candidates")
        if not isinstance(raw, dict):
            raise ValueError("Persisted ICT reclaim candidates are malformed")
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ValueError("Persisted ICT reclaim candidate is malformed")
            plan = restore_plan(cast(dict[str, Any], value["plan"]))
            raw_report_path = value["report_path"]
            if not isinstance(raw_report_path, str):
                raise ValueError("Persisted ICT report path is malformed")
            report_path = raw_report_path
            resolved_report = (self.repo / report_path).resolve()
            if (
                not resolved_report.is_relative_to(self.repo)
                or resolved_report.relative_to(self.repo).as_posix() != report_path
            ):
                raise ValueError("Persisted ICT report path is outside the repository")
            raw_report_hash = value["report_hash"]
            if not isinstance(raw_report_hash, str):
                raise ValueError("Persisted ICT report digest is malformed")
            report_hash = raw_report_hash
            stage = value["stage"]
            last_ms = value["last_processed_candle_ms"]
            expires_ms = value["expires_ms"]
            readiness_ms = value["readiness_ms"]
            if (
                key != f"ICT_TWINS:{plan.symbol}"
                or plan.family != "ICT_TWINS"
                or plan.decision_ms % MINUTE_MS != 0
                or not _SHA256.fullmatch(report_hash)
                or type(last_ms) is not int
                or last_ms < plan.decision_ms - MINUTE_MS
                or last_ms % MINUTE_MS != 0
                or type(expires_ms) is not int
                or last_ms >= expires_ms - MINUTE_MS
                or expires_ms != plan.decision_ms + ENTRY_TTL_MS
                or stage not in {"WAIT_RECLAIM", "DISPATCHED"}
                or (stage == "WAIT_RECLAIM" and readiness_ms is not None)
                or (
                    stage == "DISPATCHED"
                    and (
                        type(readiness_ms) is not int
                        or readiness_ms != last_ms + MINUTE_MS
                        or readiness_ms <= plan.decision_ms
                        or readiness_ms > expires_ms
                    )
                )
            ):
                raise ValueError("Persisted ICT reclaim candidate violates its invariants")
            self.candidates[key] = ReclaimCandidate(
                plan,
                report_path,
                report_hash,
                last_ms,
                expires_ms,
                cast(Literal["WAIT_RECLAIM", "DISPATCHED"], stage),
                None if readiness_ms is None else cast(int, readiness_ms),
            )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(
            self.path,
            {
                "schema": SCHEMA,
                "candidates": {
                    key: {
                        "plan": candidate.plan.to_dict(),
                        "report_path": candidate.report_path,
                        "report_hash": candidate.report_hash,
                        "last_processed_candle_ms": candidate.last_processed_candle_ms,
                        "expires_ms": candidate.expires_ms,
                        "stage": candidate.stage,
                        "readiness_ms": candidate.readiness_ms,
                    }
                    for key, candidate in self.candidates.items()
                },
            },
            durable=True,
        )

    @staticmethod
    def key(symbol: str) -> str:
        return f"ICT_TWINS:{symbol}"

    def get(self, symbol: str) -> ReclaimCandidate | None:
        return self.candidates.get(self.key(symbol))

    def _report_identity(self, report_path: Path) -> str:
        resolved = report_path.resolve()
        if not resolved.is_relative_to(self.repo):
            raise ValueError("ICT qualification report is outside the repository")
        return resolved.relative_to(self.repo).as_posix()

    def begin(
        self,
        plan: TradePlan,
        report_path: Path,
        report_hash: str,
        *,
        entry_ttl_ms: int,
    ) -> ReclaimCandidate:
        if (
            plan.family != "ICT_TWINS"
            or plan.decision_ms % MINUTE_MS != 0
            or type(entry_ttl_ms) is not int
            or entry_ttl_ms != ENTRY_TTL_MS
            or not _SHA256.fullmatch(report_hash)
        ):
            raise ValueError("ICT reclaim intention does not match the qualified runtime policy")
        key = self.key(plan.symbol)
        report_identity = self._report_identity(report_path)
        existing = self.candidates.get(key)
        if existing is not None:
            if (
                existing.plan.signal_key != plan.signal_key
                or existing.report_hash != report_hash
                or existing.report_path != report_identity
            ):
                raise ValueError("A different ICT signal is already pending for this pair")
            return existing
        candidate = ReclaimCandidate(
            plan=plan,
            report_path=report_identity,
            report_hash=report_hash,
            last_processed_candle_ms=plan.decision_ms - MINUTE_MS,
            expires_ms=plan.decision_ms + entry_ttl_ms,
        )
        self.candidates[key] = candidate
        self._save()
        return candidate

    def assert_binding(
        self, candidate: ReclaimCandidate, report_path: Path, report_hash: str
    ) -> None:
        if (
            candidate.report_path != self._report_identity(report_path)
            or candidate.report_hash != report_hash
        ):
            raise ValueError("Persisted ICT reclaim state belongs to another reviewed report")

    def advance(
        self,
        symbol: str,
        candles: tuple[Candle, ...],
        decision_ms: int,
        *,
        report_path: Path,
        report_hash: str,
        entry_ttl_ms: int,
    ) -> int | None:
        key = self.key(symbol)
        candidate = self.candidates.get(key)
        if candidate is None:
            return None
        self.assert_binding(candidate, report_path, report_hash)
        if (
            type(entry_ttl_ms) is not int
            or entry_ttl_ms != ENTRY_TTL_MS
            or type(decision_ms) is not int
            or decision_ms % MINUTE_MS != 0
            or candidate.expires_ms != candidate.plan.decision_ms + entry_ttl_ms
        ):
            raise ValueError("ICT reclaim expiry differs from its qualified entry policy")
        if decision_ms >= candidate.expires_ms:
            del self.candidates[key]
            self._save()
            return None
        if candidate.stage == "DISPATCHED":
            return None

        observed = tuple(
            candle
            for candle in candles
            if candidate.last_processed_candle_ms < candle.timestamp_ms
            and candle.timestamp_ms + MINUTE_MS <= decision_ms
        )
        changed = False
        expected_ms = candidate.last_processed_candle_ms + MINUTE_MS
        for candle in observed:
            if candle.timestamp_ms != expected_ms:
                del self.candidates[key]
                self._save()
                raise ValueError("ICT reclaim evidence has a missing or reordered minute candle")
            expected_ms += MINUTE_MS
            candidate.last_processed_candle_ms = candle.timestamp_ms
            changed = True
            if has_close_reclaim(candle, candidate.plan):
                candidate.stage = "DISPATCHED"
                candidate.readiness_ms = candle.timestamp_ms + MINUTE_MS
                self._save()
                return candidate.readiness_ms
        if changed:
            self._save()
        return None
