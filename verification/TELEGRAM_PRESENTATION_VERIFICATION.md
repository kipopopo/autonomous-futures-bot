# Telegram presentation polish

Status: LOCALLY VERIFIED — pending commit/push at report authoring time; not deployed or sent to Telegram.
Base commit: ab8b8df (Phase 263).

## Changes

- Escape literal MarkdownV2 parentheses in portfolio digest, position lines, risk warnings and command help. The old plain-text fallback retained markup, consistent with the screenshot's visible stars.
- Explicit PAPER headers for paper trade alerts and digest.
- Display-only Decimal rounding: balances to two decimal places, PnL/fees to four, quantities trimmed; underlying accounting remains untouched.
- Display event timestamps in MYT (UTC+8). Daily-report scheduler and aggregation windows are unchanged.
- Put close-trade PnL before entry/exit details and portfolio balances before daemon diagnostics.
- Closed-trade indicator reflects positive, negative, zero or unavailable PnL.
- Unknown or non-finite monetary values render as Unavailable, without a currency prefix. Preserve explicit zero.
- Do not invent a strategy exit reason when absent.
- Sum entry and exit fees only when both are available, unless an explicit total is supplied.
- Recover entry fill from exactly one prior open event with matching trade ID; lookup is read-only and works across a notifier checkpoint. Ambiguous/missing entry remains unavailable.
- Preserve missing ledger PnL and fee fields instead of converting NULL to zero. Event-time cash/equity remain unavailable when not supplied; current balances are not substituted.

## Verification

- Final full snapshot: `uv run --locked pytest -q` — **1,930 passed in 391.25 seconds** on the final working tree.
- Targeted Telegram suite: **52 passed**.
- Ruff check: PASS (`src tests scripts`).
- Ruff format check: PASS (450 files).
- Mypy: PASS (230 source files, `src scripts`).
- `uv lock --check`: PASS.
- `git diff --check`: PASS.
- An auxiliary `compileall` probe hit pre-existing Windows path-length/cache filename errors in deep research modules; this is not part of the repository's six canonical gates and did not affect pytest, Ruff, mypy, lock, or diff verification.

## Boundary

No exchange calls, trade-engine edits, credential access, Telegram sends or VPS restarts were performed. Mock transport tests verify payload behavior, not real Telegram server rendering. Deployment and a real rendering check remain a separately authorized step.
