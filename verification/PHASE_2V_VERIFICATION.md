# Phase 2v Verification — Read-Only Qualification Evidence API

**Status:** GREEN.
**Scope:** Verified read-only API exposure for persisted creator qualification
evidence.
**Safety boundary:** no mutation, promotion, paper activation, exchange access,
order routing, or execution authority.

## API contract

Added two GET-only routes:

```text
GET /api/v1/creator/qualifications
GET /api/v1/creator/qualifications/{candidate_id}
```

The list route returns verified summaries and explicit missing evidence IDs. The
detail route returns the full typed persisted qualification artifact. Both routes
first verify the creator registry and every referenced candidate artifact, then
verify qualification artifact hashes and exact candidate/bundle/dataset binding.

Configuration is explicit through the `create_app(...)` argument or:

```text
AFBOT_QUALIFICATION_ARTIFACT_ROOT
```

Qualification paths are derived deterministically as:

```text
<qualification_root>/<candidate_id>.json
```

The API does not accept arbitrary artifact paths from request parameters.

## Fail-closed behavior

```text
missing creator registry       -> 404 creator candidate registry unavailable
missing qualification detail   -> 404 creator qualification artifact unavailable
tampered qualification         -> 503 qualification integrity failure
binding mismatch               -> 503 qualification integrity failure
POST to qualification route   -> 405
unknown candidate              -> 404
```

The list route reports candidates without persisted evidence in
`missing_candidate_ids`; it never fabricates a qualification result.

Fixed safety fields remain visible in the response:

```text
promotion_state="unpromoted"
execution_authority=false
```

No `promoted_ids`, order fields, mutation route, or execution authority was
introduced.

## TDD evidence

Focused RED run before implementation:

```text
3 failed — missing create_app qualification_artifact_root contract
```

Focused GREEN run after implementation:

```text
3 passed
```

The test fixture uses production candidate, registry, aggregation, policy, and
qualification artifact writers. It verifies:

- verified list and detail responses;
- candidate count, qualification count, and missing IDs;
- full OOS qualification readback;
- candidate and registry byte preservation;
- missing evidence and unknown candidate handling;
- GET-only behavior;
- tampered qualification rejection for both list and detail routes.

## API dogfood

A temporary verifier reused the persisted production fixture, called the ASGI
application with HTTPX, mutated the persisted qualification payload, and checked
that the API rejected the tampered artifact.

Actual result:

```json
{
  "candidates_unchanged": true,
  "detail_status": 200,
  "fixture_cleanup": true,
  "list_status": 200,
  "phase2v_api_dogfood": "GREEN",
  "post_status": 405,
  "registry_unchanged": true,
  "tampered_status": 503
}
```

Temporary fixture and verifier were removed after execution.

## Quality gates

```text
Backend pytest: 172 passed
Ruff: passed
Ruff format: 73 files formatted
Mypy: no issues in 41 source files
uv lock --check: passed
Compileall: passed
git diff --check: passed
Frontend Vitest: 9 passed
Frontend lint: 0 warnings, 0 errors
Frontend production build: passed
Targeted changed-file credential-format scan: 0 findings
```

The broad repository keyword scan surfaced three pre-existing documentation
matches containing generic `api_key` wording; no credential-format match was
found in any Phase 2v changed file.

## Safety conclusion

Phase 2v exposes only already-persisted, hash-verified qualification evidence.
A `qualified` response remains evidence-only and does not imply profitability,
paper-live status, promotion, or executability.
