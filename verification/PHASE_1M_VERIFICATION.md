# Phase 1m Verification — Persisted Funding and Mark-Price Artifacts

**Status:** Persisted derivatives-artifact slice GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Public-data artifact persistence only. No credentials, signed requests, account endpoints, leverage, sizing, or order routing were added.

## Scope delivered

Added `src/autonomous_futures/data/derivatives_artifacts.py` with:

- `DerivativesArtifactManifest` for `funding_rate` and `mark_price`;
- canonical Parquet writer/reader for funding events;
- canonical Parquet writer/reader for closed mark-price bars;
- Decimal-preserving roundtrip validation;
- strict UTC half-open ranges;
- event-based funding semantics with no fabricated interval;
- mark-price interval validation for `5m`/`15m`;
- mark-price closed-bar boundary validation;
- rejection of rows outside the requested range;
- artifact SHA-256 binding;
- deterministic manifest hash excluding audit-only `created_at`;
- atomic artifact writes through temporary file plus replace;
- write-once artifact and manifest behavior;
- tamper detection through manifest-to-artifact SHA-256 verification.

The public APIs are exported through `src/autonomous_futures/data/__init__.py`.

## RED → GREEN evidence

Initial focused run before implementation:

```text
pytest tests/unit/test_derivatives_artifacts.py -q
ModuleNotFoundError: No module named 'autonomous_futures.data.derivatives_artifacts'
exit code: 2
```

A later regression test proved the initial implementation could reach a cadence error after an out-of-range mark bar was silently filtered. The implementation was corrected to reject the range before cadence validation.

Focused GREEN result:

```text
pytest tests/unit/test_derivatives_artifacts.py -q
5 passed in 0.75s
```

## Dogfood evidence

Canonical funding and mark-price frames were generated through the existing Phase 1j canonicalizers, persisted to temporary Parquet artifacts, read back, verified against their manifests, and registered by real manifest hash.

```text
funding_rows: 2
mark_rows: 3

funding_manifest_hash:
681cec954fc2aea77bdc4e42207f0778c0eee9e98c2235499da0bb1f180302ea

mark_manifest_hash:
6aa73768e8db0c63c5b2de97c6ef4741ccf22c3f9b764fd21aff729bbfb14b01

registry_entries: 2
registry_hash:
4c128306f57b5d4184d6492629bd7314c7e3a54244cad9658618a78ca2e5448c

persisted: true
```

The temporary output directory was removed after the dogfood probe. Funding and mark-price exact registry lookup succeeded.

## Integrity boundaries

- Funding event at `time_end` is rejected because ranges are `[time_start, time_end)`.
- Duplicate funding event times remain rejected.
- Mark bars with invalid `close_time` remain rejected.
- Mark bars before `time_start` or at/after `time_end` are rejected rather than filtered.
- Existing artifact content cannot be overwritten by a conflicting frame.
- Existing manifest content cannot be overwritten by conflicting metadata.
- Manifest readback verifies both manifest hash and, when supplied, artifact SHA-256.
- Artifact persistence is not an exchange-ingestion claim; the dogfood source was canonical in-memory data.

## Verification

```text
pytest -q
70 passed in 2.74s

ruff check
All checks passed!

ruff format --check
42 files already formatted

mypy src
Success: no issues found in 22 source files

uv lock --check
pass

compileall
pass

git diff --check
pass

secret scan
No findings
```
