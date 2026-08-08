from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from ..domain.errors import DomainViolation
from .persisted_qualification import (
    PersistedQualificationBatchResult,
    run_persisted_qualification_batch,
)
from .qualification_artifacts import WalkForwardQualificationPolicy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run cached-only persisted candidate qualification without promotion."
    )
    parser.add_argument("--registry-path", type=Path, required=True)
    parser.add_argument("--candidate-artifact-root", type=Path, required=True)
    parser.add_argument("--aggregation-root", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--policy-path", type=Path, required=True)
    parser.add_argument("--aggregation-ref", action="append", required=True)
    parser.add_argument("--evaluator-run-id", required=True)
    parser.add_argument("--evaluator-version", required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--limit", type=int)
    return parser


def _load_policy(path: Path) -> WalkForwardQualificationPolicy:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return WalkForwardQualificationPolicy.model_validate(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise DomainViolation("invalid qualification policy config") from exc


def _parse_aggregation_refs(values: list[str]) -> dict[str, str]:
    references: dict[str, str] = {}
    for value in values:
        candidate_id, separator, reference = value.partition("=")
        if not separator or not candidate_id or not reference:
            raise DomainViolation("invalid aggregation reference")
        if candidate_id in references:
            raise DomainViolation("duplicate aggregation reference")
        references[candidate_id] = reference
    return references


def _parse_utc_timestamp(value: str) -> datetime:
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DomainViolation("invalid evaluated-at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise DomainViolation("evaluated-at must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _result_payload(result: PersistedQualificationBatchResult) -> dict[str, object]:
    payload = result.model_dump(mode="json")
    payload.update(
        {
            "status": "completed",
            "selected_count": len(result.selected_candidate_ids),
            "unselected_count": len(result.unselected_candidate_ids),
            "evaluated_count": len(result.evaluated_candidate_ids),
            "qualified_count": len(result.qualified_candidate_ids),
            "rejected_count": len(result.rejected_candidate_ids),
            "blocked_count": len(result.blocked_candidate_ids),
        }
    )
    return payload


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = _load_policy(args.policy_path)
    except DomainViolation:
        _print_json({"error_code": "invalid_policy_config", "status": "error"})
        return 2

    try:
        aggregation_refs = _parse_aggregation_refs(args.aggregation_ref)
        evaluated_at = _parse_utc_timestamp(args.evaluated_at)
        result = run_persisted_qualification_batch(
            registry_path=args.registry_path,
            candidate_artifact_root=args.candidate_artifact_root,
            aggregation_root=args.aggregation_root,
            qualification_root=args.qualification_root,
            aggregation_refs=aggregation_refs,
            policy=policy,
            evaluator_run_id=args.evaluator_run_id,
            evaluator_version=args.evaluator_version,
            evaluated_at=evaluated_at,
            limit=args.limit,
        )
    except FileNotFoundError:
        _print_json({"error_code": "missing_input", "status": "error"})
        return 2
    except OSError:
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    except ValidationError:
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2
    except ValueError:
        _print_json({"error_code": "invalid_input", "status": "error"})
        return 2

    _print_json(_result_payload(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
