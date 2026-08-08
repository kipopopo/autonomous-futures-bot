# Phase 2u Verification — Real Persisted-Artifact CLI Dogfood

**Status:** GREEN after corrected Windows source-root invocation.
**Scope:** Real temporary persisted candidate, registry, OOS aggregation, policy,
and qualification artifact passed through the production CLI subprocess.
**Safety boundary:** local cached evidence only; no exchange/network calls, no
candidate mutation, no promotion, no paper activation, and no order routing.

## Dogfood method

A temporary verifier used the production artifact builders and writers to create
one real persisted fixture:

```text
candidate artifact
candidate registry
persisted OOS aggregation envelope
qualification policy JSON
```

The verifier then launched the actual module subprocess rather than calling
`main(...)` directly:

```text
PYTHONPATH=src uv run --locked python -m autonomous_futures.research.qualification_cli
```

It parsed the CLI JSON output and read the resulting qualification artifact
through the production reader. The temporary verifier and its temporary fixture
were removed after execution.

## Actual dogfood result

```json
{
  "candidate_unchanged": true,
  "cli_exit_code": 0,
  "execution_authority": false,
  "fixture_cleanup": true,
  "phase2u_dogfood": "GREEN",
  "promotion_state": "unpromoted",
  "qualification_readback": true,
  "qualified_candidate_ids": ["cand-phase2u-dogfood"],
  "registry_unchanged": true
}
```

The candidate-specific result was:

```text
selected_count=1
evaluated_count=1
qualified_count=1
blocked_count=0
```

The qualification artifact readback confirmed:

```text
decision="qualified"
source="walk_forward_oos"
promotion_state="unpromoted"
execution_authority=false
```

The CLI output did not contain `promoted_ids`.

## Preservation checks

Before CLI execution, the verifier recorded candidate and registry bytes. After
execution it confirmed:

```text
candidate artifact bytes unchanged: true
registry bytes unchanged: true
registry hash/readback unchanged: true
qualification artifact readback: true
```

Only the qualification artifact appeared under the temporary qualification root.
No candidate lifecycle or registry mutation occurred.

## Import-boundary note

The first temporary verifier attempt failed before fixture creation because the
source root was not supplied to the verifier process:

```text
ModuleNotFoundError: No module named 'autonomous_futures'
```

The temporary file was deleted, then the verifier was recreated and rerun with
the documented Windows-safe source-root boundary:

```text
PYTHONPATH=src uv run --locked python <temporary-verifier>.py
```

The corrected subprocess dogfood passed. This was an invocation setup issue,
not a production CLI or persistence failure.

## Safety conclusions

This dogfood proves the persisted CLI path can produce strict qualification
evidence from real persisted artifacts while preserving the safety boundary. It
does **not** prove profitability, paper readiness, promotion eligibility, live
execution readiness, or exchange connectivity.

No authenticated exchange client, order endpoint, promotion path, paper
activation, or execution authority was invoked.
