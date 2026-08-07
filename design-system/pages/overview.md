# Overview Page Overrides

## Page role

The Overview is an evidence reader for the persisted dataset foundation. It is not a trading terminal and must not imply account, position, P&L, signal, or execution state.

## Above-the-fold order

```text
1. page title + MYT/GMT+8 context
2. PAPER-SAFE / READ-ONLY / EXECUTION AUTHORITY OFF rail
3. API/catalog verification state
4. bundle identity summary
5. component inventory
```

## Allowed live fields

From `/health`:

```text
service
paper_safe
execution_authority
```

From `/api/v1/dataset/bundle`:

```text
bundle_hash
registry_hash
component_count
symbols
primary_interval
context_interval
context_feature_policy
primary time range
```

From `/api/v1/dataset/components`:

```text
kind
symbols
interval
artifact_ref
manifest_hash
artifact_sha256 when available
rows when available
schema_version
```

## Refresh behavior

- fetch all three GET routes on initial mount;
- use one explicit `Refresh verified data` button with a visible 44px target;
- show request state per page, not fake zero values;
- show the verification time in `MYT (GMT+8)` and retain UTC in an accessible detail label;
- do not poll or animate in this phase.

## Mobile override

- safety rail wraps to two rows;
- bundle hash is displayed in a scrollable or copyable code treatment;
- component table becomes stacked cards;
- verification state remains visible before artifact details.
