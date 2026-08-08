# Phase 2t Verification — Qualification Batch CLI/JSON Entrypoint

**Status:** GREEN.
**Scope:** Safe module CLI for deterministic persisted candidate batch qualification.
**Safety boundary:** cached-only evidence orchestration; qualification artifacts
only; no candidate mutation, promotion, paper activation, exchange access, or
order routing.

## Entrypoint

```text
PYTHONPATH=src uv run --locked python -m autonomous_futures.research.qualification_cli
```

The project intentionally remains non-packaged (`tool.uv.package = false`), so
the explicit `PYTHONPATH=src` invocation keeps the source boundary visible and
reproducible.

## Required inputs

```text
--registry-path
--candidate-artifact-root
--aggregation-root
--qualification-root
--policy-path
--aggregation-ref candidate_id=relative/aggregation.json
--evaluator-run-id
--evaluator-version
--evaluated-at <UTC ISO-8601 timestamp>
```

Optional:

```text
--limit <positive candidate count>
```

The policy is loaded as strict `WalkForwardQualificationPolicy` JSON. Aggregation
references may be repeated for candidate-specific persisted evidence.

## JSON output

Normal completion emits one stable compact JSON object with sorted keys,
partition counts, IDs, blocker records, and fixed safety fields:

```text
status="completed"
selected_count
unselected_count
evaluated_count
qualified_count
rejected_count
blocked_count
selected_candidate_ids
unselected_candidate_ids
evaluated_candidate_ids
qualified_candidate_ids
rejected_candidate_ids
blocked_candidate_ids
failures
promotion_state="unpromoted"
execution_authority=false
```

`qualified_candidate_ids` are qualification-evidence outcomes only. The CLI does
not emit a promoted-ID list and does not contain a promotion code path.

Controlled CLI errors emit stable JSON without filesystem paths or raw exception
text:

```text
{"error_code":"invalid_policy_config","status":"error"}
{"error_code":"missing_input","status":"error"}
{"error_code":"invalid_input","status":"error"}
```

## Safety behavior

The CLI delegates all candidate processing to
`run_persisted_qualification_batch(...)`; it does not duplicate gate logic.

- Candidate selection remains `testing`-only and registry-ordered.
- Candidate limit is separate from candle/OOS data limits.
- Candidate-specific aggregation references are preserved.
- Candidate/registry/aggregation hashes remain independently verified.
- Path traversal is reported as a blocked candidate, not converted into a pass.
- Missing or tampered evidence produces no qualification artifact.
- Existing qualification files remain write-once and are not overwritten.
- `qualified` never changes candidate state or grants execution authority.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.qualification_cli'
```

Focused GREEN:

```text
CLI tests: 3 passed
```

Tests cover:

- real CLI `main(...)` JSON completion and persisted qualification output;
- stable invalid-policy JSON and exit code 2;
- path traversal remaining blocked evidence with no output artifact;
- fixed unpromoted/execution-disabled safety fields.

Module help smoke test passed:

```text
PYTHONPATH=src uv run --locked python -m autonomous_futures.research.qualification_cli --help
```

## Quality gates

```text
Backend pytest: 169 passed
Focused CLI tests: 3 passed
Frontend Vitest: 9 passed
Frontend lint: 0 warnings, 0 errors
Vite production build: passed
Ruff check: passed
Ruff format: passed (71 files formatted)
Mypy: Success: no issues found in 40 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 119 files, 0 findings
```

## Scope boundary

This phase does **not** implement or claim:

- candidate promotion or lifecycle transition;
- paper/live activation;
- execution or exchange connectivity;
- profitability beyond supplied strict OOS evidence;
- dashboard/API mutation authority;
- automatic policy discovery or wall-clock evaluation timestamps.
