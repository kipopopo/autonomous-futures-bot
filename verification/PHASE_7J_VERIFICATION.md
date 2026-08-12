# Phase 7J Verification — non-mutating absent paper-observation inspection

## Decision

Phase 7J fixes a concrete read-only violation in the observation inspector. A valid request against a nonexistent SQLite journal previously returned `status="unavailable"` but created an empty database as a side effect because the typed store initializer called `sqlite3.connect`.

## Delivered

The inspector now validates its candidate binding, then checks the caller-supplied journal path before constructing `SqlitePaperObservations`:

```text
missing journal path → status="unavailable", exit 0, no file created
existing empty journal → status="unavailable", exit 0
existing bound rows   → latest snapshot, status="available"
```

No SQLite schema/table/store behavior changed. The guard is limited to the read-only CLI boundary; capture remains the intentional creator/writer.

## TDD evidence

```text
RED: valid absent journal returned unavailable but created absent.sqlite3
GREEN: tests/unit/test_paper_observation_inspect_cli.py — 3 passed
related paper tests: 38 passed
```

The new regression invokes the real CLI with a valid candidate/hash and a nonexistent temporary journal path, asserts the normal unavailable JSON, and verifies the path still does not exist.

## Verification

```text
full locked suite: 526 passed
Ruff:              passed
Ruff format:       passed
Mypy:              130 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No new SQLite writer, schema migration, capture change, scheduler, runtime loop, market/exchange/network client, credential, activation, testnet, or live path was introduced. Paper authority remains structurally false.
