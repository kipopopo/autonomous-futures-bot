# Autonomous Futures Bot — handoff to Antigravity

## 1. Product mandate — read first

The user's latest clarification is explicit: **autonomous futures trading, learning,
and strategy creation are the core of this project**, not optional future extras.
Paper reliability and analytics are supporting foundations, not the final product.
Do not continue a succession of observation-only milestones while leaving the core
learning/creation/execution feedback loop unintegrated.

The target is a bounded, auditable autonomous cycle:

```text
verified market data + prior research/paper outcomes
→ learn / evaluate evidence
→ create or revise a strategy with new immutable identity
→ deterministic evaluation + OOS/walk-forward + cost/risk gates
→ separate eligibility/admission decision
→ safe paper strategy selection and execution
→ durable results feeding the next learning/creation cycle
```

Automation must perform actual work, not just produce advice, log a hypothetical
training result, or expose disconnected APIs. Autonomous does NOT mean unrestricted
LLM authority over risk, capital, promotion, or real-money orders. Real-money execution
remains a separately approved boundary; this handoff grants no live/testnet activation.

## 2. Workspace and ownership

- Local root: `C:\Users\thaqi\Projects\Autonomous Futures Bot`.
- Repository: https://github.com/kipopopo/autonomous-futures-bot
- Branch: `main`.
- Verified baseline before this handoff document:
  `29f41eb0b98406573353d4bc8e2ea4fe0fca7196`, equal to remote `origin/main`, clean tree.
- This handoff is documentation only, not a new runtime release. Its eventual commit
  is newer than the baseline above; inspect current Git instead of checking out backward.
- This is NOT the separate VibeCrypt or Crypto Trading Bot repository.
- Antigravity is the next writer. Hermes is not implementing a new slice or controlling
  VPS services as part of this handoff. Do not run two coding agents against this tree.
- No `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, or earlier handoff file was found during
  this preflight. Recheck in case workspace rules have changed.
- Keep Ponytail full: read and trace first, reuse existing contracts, minimal diffs,
  strict RED → GREEN for behavior changes, no speculative framework or drive-by refactor.
- Group diagnosis → implementation → integration regression → verified delivery into
  one meaningful outcome. Do not ask the user to approve each mechanical micro-step.
- Routine delivery is verify → commit → push → deploy **when release gates pass**.
  A handoff, test pass, or Git push alone never authorizes a service restart.
- No new cron/scheduled development jobs were requested. The user rejected slow cron
  ticks as a substitute for active development; that is NOT a rejection of the product's
  eventual bounded autonomous runtime. Design its cadence/budgets deliberately.

## 3. What is actually implemented versus integrated

### A. Working paper execution foundation

- `scripts/run_phase_259_live_paper_daemon.py:507` defines `run_live_paper_daemon`.
  It builds `LivePaperEngine`, seeds market history, and streams public market data.
- `src/autonomous_futures/paper/live_engine.py:307` loads supplied or default candidates.
- `src/autonomous_futures/paper/live_engine.py:367` defines `_load_default_candidates`:
  the default path reads `PINNED_CANDIDATE_IDS` from
  `artifacts/research/phase252/candidates`.
- Current trading is therefore evidenced as continuous paper execution using pinned
  candidate artifacts, NOT evidence of continuous self-training or strategy replacement.
- The name `qualified_symbols` is assigned from loaded candidate keys. Do not treat
  that name as proof a full qualification envelope was checked at runtime admission;
  trace candidate provenance and the actual qualification/admission path first.

### B. Existing Creator and research pieces — reuse them

- `src/autonomous_futures/research/creator_generator.py:107`: `CreatorGenerator`,
  injected transport, strict proposal parsing, bounded failure metadata, no execution.
- `src/autonomous_futures/research/creator_proposals.py`: proposal and canonical identity.
- `src/autonomous_futures/research/creator_batch.py`: bounded batch orchestration.
- `src/autonomous_futures/research/creator_artifacts.py`: persisted candidate artifacts.
- `src/autonomous_futures/research/creator_cached_evaluation.py` and
  `creator_qualification.py`: existing evaluation / qualification boundaries.
- `src/autonomous_futures/api/creator.py`: Creator API and historical-ID helper.
- `src/autonomous_futures/phase_252_batch.py` and
  `scripts/run_phase_252_batch_campaign.py`: real bounded multi-asset campaign path.
- `scripts/evaluate_phase_253_walk_forward.py`: existing walk-forward runner.

### C. Existing learning and feedback pieces — not a verified autonomous loop

- `src/autonomous_futures/research/learner_training_pipeline.py:45`:
  `execute_learner_training_with_evidence`, requiring an explicit trainer callback,
  bound windows and persisted source/output/model/evidence roots.
- `learner_inputs.py`, `learner_runs.py`, `learner_training.py`, `learner_bootstrap.py`,
  `learner_artifacts.py`, `learner_training_evidence.py`: causal input and real model
  artifact/training evidence foundations under the same research directory.
- `learner_evaluation.py`, `learner_qualification.py`, `learner_quality_review.py`:
  evaluation and quality/qualification components.
- `creator_feedback_training.py` and `learner_critic_training.py` call the shared
  training pipeline. `learner_critic.py` and `learner_critic_provider.py` provide Critic
  contracts/adapters. API surface also exists in `src/autonomous_futures/api/learner.py`.
- Caller tracing in this handoff found the training pipeline used by those feedback
  wrappers, and Creator generation used by staging/batch paths. It did NOT establish
  a production end-to-end scheduled learn → create → qualify → select cycle.
- Presence of files is not proof of deployed model training, learned-model influence
  on trading decisions, or automatic replacement of pinned candidates. Inspect actual
  trainers, entrypoints, persisted artifacts and runtime consumers before making claims.

### D. Reliability and evidence already delivered — do not redo for activity

- Exact Decimal cash restoration; durable protective/position state with strategy and
  ledger binding; fail-closed dirty-intent recovery; natural open-position restart and
  later natural closure were verified in the recovery milestone.
- Preserve the write-ahead intent BEFORE in-memory mutations and failure latch across
  caller exception handling. Do not replace it with best-effort deletion or a memory flag.
- Actual exit reason now persists in append-only lifecycle `closed` marks and is read
  by analytics. Missing historical reasons remain `unavailable`, never `normal_close`.
- Natural runtime close sequences 99, 100, 102 and 105 proved strategy exit, trailing
  stop and stop-loss reasons through lifecycle and analytics; PnL values matched.
- Frozen offline audit is reproducible; no new runtime feature is needed to repeat it.

## 4. Provider and lineage cautions

Do not import provider/model assumptions from another project or an old phase.
Earlier campaigns used paid OpenCode Zen `deepseek-v4-flash` with encrypted credential
staging. The inspected Phase 252 runner instead imports Google AI Studio/Gemma policy
and defaults from `phase_252_batch.py`. **These are different historical paths, not
proof of the currently authorized provider for a new autonomous loop.** Resolve the
active role/model policy and cost budget with the user before paid calls; do not guess
keys, silently switch providers, add fallback, or start an unbounded provider loop.
The existing Phase 252 CLI requires `max_retries=0` and no fallback provider.

Never read/print secret contents, `.env`, private keys, authorization headers, raw
provider prompts/responses or decrypted systemd credentials into chat/logs/Git.
Use the approved encrypted staging workflow; a CLI `--api-key` option is not a reason
to put a secret on the command line. Host-key verification must stay enabled.

Use locally canonical content-derived candidate IDs. Build the complete sorted union
of historical stored IDs AND canonical IDs before revisions; immediate-parent-only
or latest-registry-only snapshots are insufficient. Preserve rejected evidence and
immutable lineage; no gate relaxation or recycling failed evidence as qualified.

## 5. VPS state — historical observations, recheck before operating

- App root: `/opt/autonomous-futures-bot` on Kainode.
- Services: `autonomous-futures-paper-live.service`,
  `autonomous-futures-telegram.service`.
- Last source release deployed: `77b747ba17a1194bc09e77d14cce76580ed560f2`.
- Archive source/test/script manifest:
  `01f91c6808d47944b6ce7c39deea43fd6c924e099d7265cbcb4668d1901ee72e`.
- Remote Git metadata intentionally represents an older checkout; release identity is
  the verified archive/manifest, not remote HEAD. Git archive applied CRLF: exact
  archive/remote byte parity and normalized blob parity were separately verified.
- Latest read-only observation available to this handoff: **2026-09-08 16:26:18 MYT**.
  Paper PID 695336 and Telegram PID 695342 were active/running, restart count 0.
  Ledger 54 opens / 52 closes, last sequence 106, two positions open, dirty intents 0.
  These values are snapshots, not an assertion they remain unchanged on takeover.
- Safety observation: paper=true; live=false; execution_authority=false;
  orders_submitted=0; unpromoted; zero private exchange credentials.
- Persistent artifacts under `artifacts/paper_live/` include `paper-ledger.sqlite3`,
  `paper-lifecycle.sqlite3`, `paper-observations.sqlite3`, `paper-daemon-health.json`,
  `telegram-checkpoint.json` and backups. Preserve them all.
- Recovery tables: `paper_position_state`, `paper_position_update_intent`.
- Read-only audits: explicit SQLite URI `mode=ro`, `PRAGMA query_only=ON`,
  `PRAGMA busy_timeout=1000`, consistent read transactions. Do not instantiate a writer
  engine against production DB just to inspect it; do not copy a live WAL DB directly.
- Deployment backup pair exists with prefix
  `/opt/autonomous-futures-bot/artifacts/paper_live/backups/exit-attribution-20260908T064148Z-`
  followed by `paper-ledger.sqlite3` or `paper-lifecycle.sqlite3`.
- Recheck operator access and exact sudo scope via the approved route. No credentials
  or private-key contents are included here. Do not guess accounts or bypass permissions.
- No restart merely to improve an evidence label. A previous single open-position
  restart approval was consumed. For any future release: verify backups, compatibility,
  state and authorized service controls; a zero-open preflight is not a post-stop gate.
- Do not roll back old code over new open state/schema without compatibility proof.
  Lifecycle readers predating `closed` may reject the current evidence contract.
- A Telegram checkpoint/service proves processing, not independently verified delivery.
  Do not claim the historical unavailable HTTP health endpoint is healthy.

## 6. Evidence and verification

Read in this order:

1. `verification/ENTRY_EXIT_COST_ATTRIBUTION.md` — root fix, final tests and rollout;
   earlier pending statements are chronology, superseded by its final release section.
2. `verification/EXIT_COST_AUDIT.md` plus `verification/exit-cost-snapshot.json` and
   `verification/reproduce_exit_cost_audit.py` — later natural-close evidence.
3. `verification/PHASE_269_VERIFICATION.md` — durable intent/failure-latch boundary.
4. `verification/PHASE_271_DEPLOYMENT_VERIFICATION.md` — safe source cutover.
5. `verification/PHASE_274_REAL_OPEN_POSITION_RESTART.md` and
   `verification/PHASE_275_RECOVERED_POSITION_NATURAL_CLOSURE.md` — real recovery chain.
6. Creator/Learner source and the corresponding reports/tests before planning integration.
   Do not assume old negative Creator campaigns describe newer Phase 252 candidates.

Historical verified release suite: **1948 passed in 409.54s** on final release source.
Staged VPS focused regression: **40 passed in 5.64s**. Latest audit post-commit analytics:
**26 passed in 2.09s**. These are scoped historical results, not tests of future edits.

Frozen post-release cohort: four closes, two unmatched opens excluded. Decimal gross
`-0.2963645597591040`, fees `0.14851486592677885440`, net `-0.44487942568588285440` USDT.
This is neither total lifetime performance nor evidence of an edge. Gross is already
negative; do not describe losses as fees-only. Do not subtract slippage twice or infer
missing funding/entry rationale. This small sample does not justify auto-tuning, but
it does not prevent building the bounded autonomous integration offline.

Project runtime is **Python >=3.14,<3.15**, per `pyproject.toml`; the host's bare Python
may be 3.11. Use the locked uv environment for product code/tests. On Windows, use
native `C:/Users/...` paths for native programs. Do not mix shell syntaxes.

```bash
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
uv run --locked pytest -q tests/unit/test_performance_analytics.py tests/unit/test_phase_267_position_recovery.py tests/unit/test_phase_267_review_blockers.py
uv run --locked pytest -q
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
uv run --locked mypy src scripts
uv lock --check
git diff --check
git show --check --oneline HEAD
python verification/reproduce_exit_cost_audit.py
```

The final command is a stdlib-only audit script. Run changed Creator/Learner tests
as well when those paths change. Freeze code/tests during the full suite (roughly
seven minutes historically); edits afterward require new final verification.

## 7. Next outcome: integrate the core, not another audit-only phase

Begin with read-only repo inspection and a short **exists / connected / runtime-proven /
missing** map. Verify the actual trainer, provider adapters, candidate qualification
policy and paper strategy selection before proposing additions. Do not rewrite the
existing research foundation or call a new wrapper 'autonomy'.

Then implement the smallest end-to-end **bounded learning → strategy creation/revision
→ deterministic evaluation/qualification → explicit paper-selection decision** cycle
that reuses those pieces. Prove its feedback input and consumer, not only serialization.
Keep production paper running untouched while developing against isolated artifacts.

Acceptance criteria for the integrated milestone:

- One auditable cycle consumes verified cached data plus bound prior outcome/feedback
  evidence, invokes actual implemented training/creation paths, and persists real results.
- State explicitly what the learner learns and where its output changes subsequent
  creation or deterministic decisions; an unused model artifact is not learning integration.
- Distinguish training success, candidate validity, qualification and admission. Missing,
  stale, malformed or rejected evidence blocks selection and leaves the active candidate
  unchanged. A negative/no-change cycle is a valid end-to-end result.
- Preserve candidate/model/dataset/run hashes and full lineage; replay and process
  restart do not duplicate paid requests, artifacts, strategy adoption, fees or trades.
- Fixed cycle/candidate/call/time budgets and stop reasons; no silent fallback, same-failure
  retry loop, or unbounded scheduler. External provider runs need verified credentials
  and an approved provider/budget; deterministic offline tests do not prove paid runtime.
- Candidate adoption respects open-position strategy/protective bindings. Never mutate
  the strategy behind an already-open trade or bypass qualification to make adoption occur.
- One real cross-boundary isolated integration check plus failure/restart tests, focused
  regressions and final locked quality gates. No mocked success reported as real learning.
- Verify → commit → push; deploy only after the separate operational gates. Live/testnet,
  new paid recurring execution and major scheduling/admission policy decisions require
  explicit approval, not inference from this handoff.

Return concise BM/Manglish updates: what works, proof, gaps and next meaningful outcome.
The intended endpoint remains an autonomous trading/learning/creation system—not a
paper monitor that waits indefinitely for a larger audit sample.
