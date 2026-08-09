# Phase 3BB Verification — Verified Persisted Evaluation-Observation Review Loader

**Runtime:** `gpt-5.6-luna` / `openai-codex` / Medium
**Status:** VERIFIED — read-only exact-binding loader

Phase 3BB composes the Phase 3BA hash-verified reader with exact Phase 3AY
caller binding:

```text
persisted Phase 3AZ review
→ hash-verified Phase 3BA read
→ Phase 3AY input hash revalidation
→ exact research-run binding
→ exact observation-input hash binding
→ exact upstream evaluation/observation hash binding
```

Focused tests:

```text
3 passed in 0.72s
```

Full suites:

```text
pre-commit:  374 passed in 8.10s
post-commit: 374 passed in 6.89s
```

Static gates passed: Ruff, format, mypy (85 source files), lock check,
compileall, and diff check. No quality, qualification, promotion, paper,
provider, exchange, order, or execution authority was added.
