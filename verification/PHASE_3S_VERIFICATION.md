# Phase 3S Verification — Persisted Cached-only Learner Metric Evidence

**Status:** GREEN

## Scope

Phase 3S persists the typed `LearnerMetricEvaluationRun` produced by the cached-only metric adapter. It adds:

- `read_learner_metric_evaluation_run(...)`;
- `write_learner_metric_evaluation_run(...)`;
- public exports through `research.__init__`.

The persistence boundary validates the typed envelope, recomputes the canonical SHA-256 content hash, maps missing files explicitly, rejects malformed/tampered content, and preserves exact Decimal-safe metric values.

## Persistence contract

- Hash verification happens before filesystem writes.
- New files use a unique sibling temporary file and exclusive `os.link` creation.
- Temporary files are removed in `finally`, including temporary-write failure paths.
- Existing artifacts are read and verified before comparison.
- Identical complete artifacts are idempotent.
- Any conflicting rewrite, including a changed audit timestamp with the same content hash, raises `DomainViolation`.
- The created artifact is read back and verified before the writer returns.

## Safety boundary

Persisted metric evidence remains observational provenance only. It does **not**:

- train or execute a model;
- load model bytes;
- fetch filesystem/network/exchange data beyond the caller-provided path;
- qualify or promote a candidate;
- activate paper/live trading;
- create execution authority or order routing;
- add API/UI or mutation controls.

The persisted safety fields remain:

```text
data_source="cached_only"
exchange_access=false
```

Metric evidence describes what the explicit simulator produced. It does not prove accuracy, profitability, robustness, qualification or promotion readiness.

## TDD evidence

RED was observed before implementation:

```text
ImportError: cannot import name 'read_learner_metric_evaluation_run'
```

The focused Phase 3S suite then passed:

```text
7 passed in 1.28s
```

Coverage includes verified round-trip, identical write, audit-time immutable conflict, tampered hash, malformed JSON, missing path, cached-only safety fields, and pre-write hash mismatch with no destination file created.

## Verification gates

```text
Focused related tests:     56 passed in 1.54s
Full backend pytest:       235 passed in 5.68s
Ruff:                      All checks passed!
Ruff format:               94 files already formatted
Mypy:                      Success: no issues found in 52 source files
uv lock --check:           passed
compileall:                passed
git diff --check:          passed
Safety diff scan:          0 findings
```

No frontend or API files changed, so frontend/browser dogfood is not applicable to this phase.

## Layman explanation

Yang sudah dibuat: hasil metric learner sekarang boleh disimpan sebagai fail evidence yang tidak boleh ditukar secara senyap. Bila dibaca semula, sistem semak bentuk data dan hash; fail rosak, hash salah, JSON rosak atau fail hilang tidak dianggap sebagai keputusan yang sah.

Yang belum dibuat: evidence ini masih belum bermaksud model bagus, profitable, qualified atau promoted. Ia juga belum mengaktifkan paper/live trading dan belum mempunyai order authority.

## Next safe boundary

The next isolated slice may verify persisted metric evidence through a read-only quality-review input boundary. It must continue to reject missing/tampered evidence, keep review caller-supplied, and remain separate from qualification, promotion and execution authority.
