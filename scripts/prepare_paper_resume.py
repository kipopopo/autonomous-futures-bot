"""Prepare a paper-resume request without applying it to the runtime."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.domain.risk import ResumeEvidence
from autonomous_futures.paper.resume_control import (
    PaperRecoveryPreflight,
    build_paper_resume_request,
    capture_paper_recovery_preflight,
    write_paper_resume_request,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate explicit paper recovery evidence and persist a non-authoritative "
            "resume request. This command never applies, restarts, or places orders."
        )
    )
    parser.add_argument("--evidence-file", type=Path, required=True)
    preflight_group = parser.add_mutually_exclusive_group(required=True)
    preflight_group.add_argument("--storage-dir", type=Path)
    preflight_group.add_argument("--preflight-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--created-at", required=True, help="UTC ISO-8601 timestamp")
    parser.add_argument("--expires-at", required=True, help="UTC ISO-8601 timestamp")
    return parser


def _read_evidence(path: Path) -> ResumeEvidence:
    return ResumeEvidence.model_validate_json(path.read_text(encoding="utf-8"))


def _read_preflight(path: Path) -> PaperRecoveryPreflight:
    return PaperRecoveryPreflight.model_validate_json(path.read_text(encoding="utf-8"))


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _blocked() -> int:
    print(json.dumps({"reason": "invalid_input", "status": "blocked"}, sort_keys=True))
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        evidence = _read_evidence(args.evidence_file)
        created_at = _parse_utc(args.created_at)
        if args.storage_dir is not None:
            preflight = capture_paper_recovery_preflight(
                args.storage_dir,
                observed_at=created_at,
            )
        else:
            preflight = _read_preflight(args.preflight_file)
        request = build_paper_resume_request(
            request_id=args.request_id,
            evidence=evidence,
            preflight=preflight,
            created_at=created_at,
            expires_at=_parse_utc(args.expires_at),
        )
        persisted = write_paper_resume_request(args.output, request)
    except OSError:
        return _blocked()
    except ValueError:
        return _blocked()
    except ValidationError:
        return _blocked()
    except DomainViolation:
        return _blocked()

    print(
        json.dumps(
            {
                "status": persisted.status,
                "request_id": persisted.request_id,
                "request_hash": persisted.request_hash,
                "control_scope": persisted.control_scope,
                "paper_activation": persisted.paper_activation,
                "execution_authority": persisted.execution_authority,
                "testnet_activation": persisted.testnet_activation,
                "live_activation": persisted.live_activation,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
