"""Validation logic and models for Kainode staging Google AI Studio preflight."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .domain.contracts import DomainModel
from .research.google_ai_studio_provider import (
    GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    _sanitize_error_text,
)

DEFAULT_ENCRYPTED_SOURCE_PATH = Path("/etc/autonomous-futures/credentials/google_ai_studio_api_key")
RUNTIME_CREDENTIAL_NAME = "google_ai_studio_api_key"
ALLOWED_GEMMA_MODELS: tuple[str, ...] = ("gemma-4-26b-a4b-it", "gemma-4-31b-it")


class EncryptedSourceStoreReport(DomainModel):
    path: str
    exists: bool
    is_regular_file: bool
    mode_octal: str | None = None
    mode_valid: bool
    owner_uid: int | None = None
    owner_name: str | None = None
    owner_valid: bool
    size_bytes: int | None = None
    validation_error: str | None = None


class RuntimeCredentialReport(DomainModel):
    directory: str | None = None
    credential_name: str = RUNTIME_CREDENTIAL_NAME
    exists: bool
    is_regular_file: bool
    non_empty: bool
    in_memory_only: Literal[True] = True
    validation_error: str | None = None


class OfflineSafetyInvariants(DomainModel):
    exchange_access: Literal[False] = False
    execution_authority: Literal[False] = False
    orders: Literal[0] = 0
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    binance_keys_forbidden: Literal[True] = True
    binance_keys_detected: tuple[str, ...] = ()
    validation_error: str | None = None


class SingleProbeConstraints(DomainModel):
    provider: Literal["google_ai_studio"] = "google_ai_studio"
    base_url: str
    model_id: str
    max_retries: int = 0
    fallback_provider: bool = False
    validation_error: str | None = None


class StagingPreflightReport(DomainModel):
    ready: bool
    status: Literal["ready_for_staging_probe", "blocked"]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_store: EncryptedSourceStoreReport
    runtime_credential: RuntimeCredentialReport
    offline_safety: OfflineSafetyInvariants
    probe_constraints: SingleProbeConstraints
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_consistency(self) -> StagingPreflightReport:
        if self.ready and self.status != "ready_for_staging_probe":
            raise ValueError("ready report must have status 'ready_for_staging_probe'")
        if self.ready and self.errors:
            raise ValueError("ready report cannot have errors")
        if not self.ready and self.status != "blocked":
            raise ValueError("unready report must have status 'blocked'")
        return self


def is_file_tracked_by_git(path: Path) -> bool:
    """Return True if path is actively tracked in a git repository."""
    try:
        res = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0
    except FileNotFoundError, OSError:
        return False


def validate_encrypted_source_store(
    path: Path,
    *,
    stat_fn: Callable[[Path], os.stat_result] | None = None,
    platform: str = sys.platform,
    allowed_uids: set[int] | None = None,
) -> EncryptedSourceStoreReport:
    """Validate encrypted credential store existence, permissions (0o600/0o400), and ownership."""
    path_str = str(path)
    if not path.exists():
        return EncryptedSourceStoreReport(
            path=path_str,
            exists=False,
            is_regular_file=False,
            mode_valid=False,
            owner_valid=False,
            validation_error=f"credential_store_missing: source credential not found at {path_str}",
        )

    if not path.is_file() or path.is_symlink():
        return EncryptedSourceStoreReport(
            path=path_str,
            exists=True,
            is_regular_file=False,
            mode_valid=False,
            owner_valid=False,
            validation_error=(
                "credential_store_not_a_regular_file: "
                f"source credential is not a regular file at {path_str}"
            ),
        )

    if is_file_tracked_by_git(path):
        return EncryptedSourceStoreReport(
            path=path_str,
            exists=True,
            is_regular_file=True,
            mode_valid=False,
            owner_valid=False,
            validation_error=(
                "credential_store_tracked_by_git: source credential must not be tracked in git"
            ),
        )

    st = stat_fn(path) if stat_fn is not None else path.stat()
    size_bytes = st.st_size
    if size_bytes == 0:
        return EncryptedSourceStoreReport(
            path=path_str,
            exists=True,
            is_regular_file=True,
            size_bytes=0,
            mode_valid=False,
            owner_valid=False,
            validation_error="credential_store_empty: source credential file is 0 bytes",
        )

    mode_int = stat.S_IMODE(st.st_mode)
    mode_octal = oct(mode_int)

    # Windows cross-platform handling
    if platform == "win32" and stat_fn is None:
        return EncryptedSourceStoreReport(
            path=path_str,
            exists=True,
            is_regular_file=True,
            mode_octal=mode_octal,
            mode_valid=True,
            owner_uid=st.st_uid,
            owner_name="windows_user",
            owner_valid=True,
            size_bytes=size_bytes,
        )

    # POSIX validation: strictly mode 0o600 or 0o400 (no group, no others)
    mode_valid = mode_int in (0o600, 0o400)
    owner_uid = st.st_uid
    uids: set[int] = {0, 1000} if allowed_uids is None else set(allowed_uids)
    owner_name = "root" if owner_uid == 0 else ("afbot" if owner_uid == 1000 else None)

    try:
        import importlib

        pwd_mod: Any = importlib.import_module("pwd")

        try:
            afbot_entry = pwd_mod.getpwnam("afbot")
            uids.add(afbot_entry.pw_uid)
            if owner_uid == afbot_entry.pw_uid:
                owner_name = "afbot"
        except KeyError, AttributeError:
            pass
        if owner_name is None:
            try:
                owner_name = pwd_mod.getpwuid(owner_uid).pw_name
            except KeyError, AttributeError, ImportError:
                owner_name = f"uid_{owner_uid}"
    except ImportError, KeyError:
        pass

    owner_valid = owner_uid in uids
    err = None
    if not mode_valid:
        err = (
            "credential_store_insecure_permissions: "
            f"insecure_mode_{mode_octal}_expected_0o600_or_0o400"
        )
    elif not owner_valid:
        err = (
            "credential_store_invalid_owner: "
            f"owner {owner_name or owner_uid} is invalid, expected root or afbot"
        )

    return EncryptedSourceStoreReport(
        path=path_str,
        exists=True,
        is_regular_file=True,
        mode_octal=mode_octal,
        mode_valid=mode_valid,
        owner_uid=owner_uid,
        owner_name=owner_name,
        owner_valid=owner_valid,
        size_bytes=size_bytes,
        validation_error=err,
    )


def validate_runtime_credential_delivery(
    credential_dir: Path | None,
    credential_name: str = RUNTIME_CREDENTIAL_NAME,
) -> tuple[RuntimeCredentialReport, str | None]:
    """Validate runtime credential in $CREDENTIALS_DIRECTORY in process memory only."""
    if credential_dir is None:
        return (
            RuntimeCredentialReport(
                directory=None,
                credential_name=credential_name,
                exists=False,
                is_regular_file=False,
                non_empty=False,
                validation_error=(
                    "credentials_directory_missing: credentials directory not specified"
                ),
            ),
            None,
        )

    dir_str = str(credential_dir)
    if not credential_dir.exists() or not credential_dir.is_dir():
        return (
            RuntimeCredentialReport(
                directory=dir_str,
                credential_name=credential_name,
                exists=False,
                is_regular_file=False,
                non_empty=False,
                validation_error=(
                    "credentials_directory_missing: "
                    f"credentials directory does not exist: {dir_str}"
                ),
            ),
            None,
        )

    cred_file = credential_dir / credential_name
    if not cred_file.exists():
        return (
            RuntimeCredentialReport(
                directory=dir_str,
                credential_name=credential_name,
                exists=False,
                is_regular_file=False,
                non_empty=False,
                validation_error=(
                    "runtime_credential_missing: "
                    f"runtime credential file missing: {credential_name}"
                ),
            ),
            None,
        )

    if not cred_file.is_file() or cred_file.is_symlink():
        return (
            RuntimeCredentialReport(
                directory=dir_str,
                credential_name=credential_name,
                exists=True,
                is_regular_file=False,
                non_empty=False,
                validation_error=(
                    "runtime_credential_not_a_regular_file: "
                    f"runtime credential {credential_name} is not a regular file"
                ),
            ),
            None,
        )

    try:
        raw_key = cred_file.read_text(encoding="utf-8").strip()
    except Exception as exc:
        sanitized = _sanitize_error_text(str(exc))
        del exc
        return (
            RuntimeCredentialReport(
                directory=dir_str,
                credential_name=credential_name,
                exists=True,
                is_regular_file=True,
                non_empty=False,
                validation_error=f"runtime_credential_read_failure: {sanitized}",
            ),
            None,
        )

    if not raw_key:
        return (
            RuntimeCredentialReport(
                directory=dir_str,
                credential_name=credential_name,
                exists=True,
                is_regular_file=True,
                non_empty=False,
                validation_error="runtime_credential_empty: runtime credential file is empty",
            ),
            None,
        )

    # Format verification (length check; never record or log key value)
    if len(raw_key) < 20 or any(c.isspace() for c in raw_key):
        del raw_key
        return (
            RuntimeCredentialReport(
                directory=dir_str,
                credential_name=credential_name,
                exists=True,
                is_regular_file=True,
                non_empty=False,
                validation_error=(
                    "runtime_credential_invalid_format: runtime credential must be "
                    "non-empty string of at least 20 chars without whitespace"
                ),
            ),
            None,
        )

    # Key is valid and kept in memory only
    report = RuntimeCredentialReport(
        directory=dir_str,
        credential_name=credential_name,
        exists=True,
        is_regular_file=True,
        non_empty=True,
        in_memory_only=True,
    )
    return report, raw_key


def validate_offline_safety(
    *,
    env: Mapping[str, str] | None = None,
    credential_dir: Path | None = None,
) -> OfflineSafetyInvariants:
    """Assert zero exchange access and ensure absence of any BINANCE_* secrets."""
    environ = env if env is not None else os.environ
    detected: list[str] = []

    # 1. Environment variable inspection
    for key in environ:
        if "BINANCE" in key.upper():
            detected.append(f"env:{key}")

    # 2. Credential directory inspection
    if credential_dir is not None and credential_dir.is_dir():
        try:
            for item in credential_dir.iterdir():
                if "binance" in item.name.lower():
                    detected.append(f"file:{item.name}")
        except OSError:
            pass

    detected_tuple = tuple(sorted(detected))
    err = (
        "exchange_credential_contamination: binance credential detected: "
        f"{', '.join(detected_tuple)}"
        if detected_tuple
        else None
    )

    return OfflineSafetyInvariants(
        exchange_access=False,
        execution_authority=False,
        orders=0,
        promotion_state="unpromoted",
        paper_activation=False,
        binance_keys_forbidden=True,
        binance_keys_detected=detected_tuple,
        validation_error=err,
    )


def validate_single_probe_constraints(
    *,
    base_url: str,
    model_id: str,
    max_retries: int,
    fallback_provider: bool,
) -> SingleProbeConstraints:
    """Enforce single diagnostic probe invariants."""
    errs: list[str] = []

    # 1. Base URL verification
    normalized_url = base_url.rstrip("/")
    parsed = urlsplit(normalized_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "generativelanguage.googleapis.com"
        or parsed.path != "/v1beta/openai"
        or parsed.query
        or parsed.fragment
    ):
        errs.append(
            "invalid_base_url: base_url must be official Google AI Studio endpoint "
            "(https://generativelanguage.googleapis.com/v1beta/openai)"
        )

    # 2. Pinned model verification
    if model_id not in ALLOWED_GEMMA_MODELS:
        errs.append(f"invalid_model_id: unsupported_model_id_{model_id}_must_be_pinned_gemma")

    # 3. Retries verification
    if max_retries != 0:
        errs.append(
            "single_probe_retry_violation: "
            "max_retries must be zero for single-probe staging diagnostic"
        )

    # 4. Fallback provider verification
    if fallback_provider:
        errs.append(
            "single_probe_fallback_violation: "
            "fallback_provider is forbidden for single-probe staging diagnostic"
        )

    err = "; ".join(errs) if errs else None

    return SingleProbeConstraints(
        provider="google_ai_studio",
        base_url=normalized_url,
        model_id=model_id,
        max_retries=max_retries,
        fallback_provider=fallback_provider,
        validation_error=err,
    )


def validate_staging_environment(
    *,
    source_credential_path: Path | None = None,
    credential_dir: Path | None = None,
    base_url: str = GOOGLE_AI_STUDIO_OPENAI_BASE_URL,
    model_id: str = "gemma-4-31b-it",
    max_retries: int = 0,
    fallback_provider: bool = False,
    skip_source_check: bool = False,
    stat_fn: Callable[[Path], os.stat_result] | None = None,
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    allowed_uids: set[int] | None = None,
) -> StagingPreflightReport:
    """Complete preflight evaluation returning safe StagingPreflightReport."""
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Encrypted source store validation
    source_path = source_credential_path or DEFAULT_ENCRYPTED_SOURCE_PATH
    if skip_source_check:
        source_report = EncryptedSourceStoreReport(
            path=str(source_path),
            exists=True,
            is_regular_file=True,
            mode_valid=True,
            owner_valid=True,
            validation_error=None,
        )
        warnings.append("source_store_check_skipped")
    else:
        source_report = validate_encrypted_source_store(
            source_path, stat_fn=stat_fn, platform=platform, allowed_uids=allowed_uids
        )
        if source_report.validation_error:
            errors.append(source_report.validation_error)

    # 2. Runtime credential delivery validation
    runtime_report, raw_key = validate_runtime_credential_delivery(credential_dir)
    if raw_key is not None:
        del raw_key  # in-memory scrubbing
    if runtime_report.validation_error:
        errors.append(runtime_report.validation_error)

    # 3. Offline safety invariants validation
    safety_report = validate_offline_safety(env=env, credential_dir=credential_dir)
    if safety_report.validation_error:
        errors.append(safety_report.validation_error)

    # 4. Single-probe constraint validation
    probe_report = validate_single_probe_constraints(
        base_url=base_url,
        model_id=model_id,
        max_retries=max_retries,
        fallback_provider=fallback_provider,
    )
    if probe_report.validation_error:
        for pe in probe_report.validation_error.split("; "):
            errors.append(pe)

    is_ready = len(errors) == 0
    status: Literal["ready_for_staging_probe", "blocked"] = (
        "ready_for_staging_probe" if is_ready else "blocked"
    )

    metadata: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform,
        "python_version": sys.version.split()[0],
    }

    return StagingPreflightReport(
        ready=is_ready,
        status=status,
        errors=tuple(errors),
        warnings=tuple(warnings),
        source_store=source_report,
        runtime_credential=runtime_report,
        offline_safety=safety_report,
        probe_constraints=probe_report,
        metadata=metadata,
    )


__all__ = [
    "ALLOWED_GEMMA_MODELS",
    "DEFAULT_ENCRYPTED_SOURCE_PATH",
    "EncryptedSourceStoreReport",
    "OfflineSafetyInvariants",
    "RUNTIME_CREDENTIAL_NAME",
    "RuntimeCredentialReport",
    "SingleProbeConstraints",
    "StagingPreflightReport",
    "is_file_tracked_by_git",
    "validate_encrypted_source_store",
    "validate_offline_safety",
    "validate_runtime_credential_delivery",
    "validate_single_probe_constraints",
    "validate_staging_environment",
]
