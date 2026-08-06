# Pre-Development Readiness Audit

**Project:** Autonomous Futures Bot  
**Audit timestamp:** 2026-08-06 09:16 UTC  
**Scope:** proposal consistency, research safety, toolchain freshness, local readiness, Kainode readiness, and LLM credential boundary.  
**Mode:** read-only inspection plus documentation-only proposal updates. No package installation, VPS configuration, exchange authentication, or provider API call was performed.

## Executive verdict

| Area | Verdict |
|---|---|
| Architecture and proposal direction | **PASS after audit updates** |
| Existing public-data research slice | **PASS** |
| Existing tests | **PASS — 8 passed** |
| Proposal citation verification | **PASS — strict/evidence verification passed** |
| Version targets | **UPDATED and pinned as candidate lockfile inputs** |
| Local development environment | **NOT READY** — current interpreter is Hermes' shared environment, not a project environment |
| Kainode deployment environment | **BLOCKED** — security hardening and runtime bootstrap are still pending |
| OpenCode/DeepSeek runtime | **BLOCKED intentionally** — no credential was installed and no provider call was made |
| Overall “all prerequisites okay” | **NO-GO for starting implementation/deployment today** |

The proposal is structurally ready for approval, but the full prerequisite set is not ready. The safe next gate is environment/security preparation, followed by a narrowly scoped Phase 0 implementation after explicit proposal acceptance.

## What passed

### 1. Proposal safety and architecture

The proposal remains aligned with the core constraints:

- `5m` is the primary signal interval and `15m` is the closed-bar regime context.
- The collector is public-only and has no authentication or order path.
- The strategy screener is offline and causal; it does not make network calls.
- The LLM is restricted to typed proposals/reviews and has no authority over size, leverage, risk guards, credentials, orders, reconciliation, or promotion.
- Research parallelism is bounded; account truth, risk authority, promotion, and order authority remain serial.
- Kainode is the target only after hardening and benchmark verification.
- Paper safety, immutable evidence, deterministic gates, reconciliation, and live-authorization separation remain explicit.
- The OpenCode contract remains exact: `deepseek-v4-flash-free`, no silent fallback, and fail-closed behavior on unavailability.

The proposal was also corrected so the deployment model now says PostgreSQL 18 is a directly managed Kainode service; Docker Compose is only an optional local-development convenience.

### 2. Existing research evidence

The current research test suite ran successfully:

```text
python -m pytest -q   # from research/
8 passed in 2.27s
```

The proposal citation ledger passed the strict evidence verification:

```text
487 prose sentence(s), 7 with declared provenance
9 distinct source(s) cited, 9 in ledger
9 sources with evidence quotes
citations OK
```

### 3. Version review

The following candidate pins were rechecked against official release pages/registries during this audit:

| Component | Candidate pin | Decision |
|---|---:|---|
| Python | 3.14.7 | Use latest stable feature line through uv; do not replace Ubuntu's system Python |
| uv | 0.12.2 | Pin for environment and lockfile management |
| FastAPI | 0.141.1 | Pin |
| Pydantic | 2.13.4 | Pin |
| Uvicorn | 0.52.1 | Pin |
| SQLAlchemy | 2.0.51 | Pin |
| Alembic | 1.19.0 | Pin |
| PostgreSQL | 18.4 | Pin supported major/patch line |
| Polars | 1.43.2 | Pin |
| PyArrow | 25.0.0 | Pin |
| HTTPX | 0.28.1 | Pin |
| Binance USDⓈ-M Futures SDK | 16.0.0 | Use the exact official package name in the proposal; keep behind our adapter |
| structlog | 26.1.0 | Pin |
| pandas | 3.0.5 | Pin for the existing screener slice |
| NumPy | 2.4.6 | Pin for the existing screener slice |
| psycopg | 3.3.4 | Pin with explicit binary/pool extras after lock resolution |
| pytest | 9.1.1 | Pin |
| Hypothesis | 6.165.2 | Pin |
| Ruff | 0.16.1 | Pin |
| mypy | 2.3.0 | Pin |
| cryptography | 50.0.0 | Pin |
| Node.js | 24.19.0 LTS | Use LTS for production/build reproducibility, not Node 26 current |
| npm | 12.0.2 | Pin/package-manager baseline |
| React | 19.2.8 | Pin |
| TypeScript | 7.0.2 | Pin |
| Vite | 8.2.0 | Pin |
| Tailwind CSS | 4.3.3 | Pin |
| shadcn/ui CLI | 4.16.1 | Pin |

Python 3.14.7 is the latest stable feature release identified from Python's release page.[1]

FastAPI 0.141.1 is the current release shown by its release notes.[2]

PostgreSQL 18.4 is the current supported PostgreSQL 18 documentation line.[3] PostgreSQL 19 remains a development/beta line rather than the production target.[3]

uv 0.12.2 is the current registry/release target identified for this audit.[4]

Node 24.19.0 is the latest LTS line while Node 26.7.0 is current/non-LTS; the LTS line is the safer production choice.[5]

The React and Vite pins were checked against the npm package registry.[6][7]

The TypeScript, Tailwind CSS, and shadcn/ui pins were checked against the npm package registry.[8][9][10]

The database and web-runtime package pins were checked against their PyPI package pages.[12][17][18]

The remaining web and persistence package pins were checked against their PyPI package pages.[19][20][21]

The transport and logging package pins were checked against their PyPI package pages.[22][23]

The data-processing package pins were checked against their PyPI package pages.[13][14][15]

The Parquet, test, lint, type, and security package pins were checked against their PyPI package pages.[16][24][25]

The remaining quality-tool pins were checked against their PyPI package pages.[26][27][28]

The official Binance USDⓈ-M Futures SDK package identity was checked against PyPI.[11]

## Observed environments

### Local Windows workstation

The current `python` command resolves to Hermes' shared interpreter, not a project-local environment:

```text
Executable: C:\Users\thaqi\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
Python:    3.11.15
uv:       0.12.0
Node:     v22.23.2
npm:      12.0.2
```

Installed packages in that shared environment are not the project lockfile:

```text
pandas=3.0.3             target=3.0.5
numpy=2.4.3              target=2.4.6
fastapi=0.133.1          target=0.141.1
uvicorn=0.41.0           target=0.52.1
alembic=1.18.5           target=1.19.0
cryptography=48.0.1      target=50.0.0

pydantic=2.13.4          matches candidate
sqlalchemy=2.0.51        matches candidate
httpx=0.28.1             matches candidate
pytest=9.1.1             matches candidate
structlog=26.1.0         matches candidate

polars, pyarrow, psycopg, hypothesis, ruff, mypy = not installed in shared environment
```

This is not a failure of the existing research slice; it means the project environment has not been created yet. No `pyproject.toml`, `uv.lock`, frontend `package.json`, or Git repository exists. This is expected before Phase 0, but it is a prerequisite gap for reproducible development.

### Kainode VPS

The prior read-only preflight found Ubuntu 24.04.4, 6 vCPU, approximately 15 GiB usable RAM, approximately 116 GiB root disk, Python 3.12.3, Git 2.43.0, and low load. The latest read-only runtime inventory found:

```text
Python 3.12.3
Git 2.43.0
curl 8.5.0
uv       missing
Node.js  missing
npm      missing
PostgreSQL client/service  missing
Docker   missing
gcc      missing
Python package environment  empty/not provisioned
```

This is a clean host, not a ready application host. The project runtime should use a uv-managed Python 3.14.7 environment; Ubuntu's system Python 3.12.3 should remain untouched for OS tooling.

The prior security preflight also found these blockers:

- UFW inactive;
- root SSH login enabled;
- password SSH login enabled;
- no root authorized key;
- no swap configured;
- no project/service deployed yet.

No Kainode configuration was changed during this audit.

## Blocking prerequisites before development/deployment

### Blocker A — Kainode hardening

Before any project credential or service is copied to Kainode:

1. Rotate the root password.
2. Install and verify an operator SSH key through a second-session recovery test.
3. Create a non-root runtime/deploy user.
4. Enable default-deny UFW with only the explicitly required management/application ports.
5. Disable root/password SSH only after key access is verified.
6. Decide and document the no-swap/memory-pressure policy; benchmark with memory and I/O telemetry.
7. Install/verify security updates and fail2ban according to the approved maintenance plan.

### Blocker B — Reproducible local toolchain

After proposal acceptance, create—not before—:

- `pyproject.toml` with Python 3.14.7 compatibility;
- uv-managed `.venv` and committed `uv.lock`;
- frontend `package.json` and committed npm lockfile;
- `.gitignore` and secret scanning;
- CI checks for tests, type checking, lint/format, lockfile integrity, and secret leakage.

Do not upgrade Hermes' shared environment as a substitute for the project environment. That would create cross-project coupling.

### Blocker C — Database/runtime bootstrap

The proposal requires PostgreSQL 18 for later event, candidate, audit, and paper-state storage. It is not installed on Kainode. Install it only after hardening and only with:

- localhost/private-bind policy;
- separate non-superuser application role;
- migrations through Alembic;
- backup/restore drill;
- audit/event retention policy;
- no public database port.

### Blocker D — OpenCode credential and model preflight

The supplied API key is not stored in the repository, proposal, memory, or Kainode. No provider call was made. Because it was transmitted in chat, it must be rotated before provisioning. The replacement key should be installed only after hardening using the documented encrypted systemd credential path.

The first provider preflight must verify only:

- base URL connectivity;
- exact model ID availability;
- timeout/retry/rate-limit behavior;
- schema-constrained response parsing;
- cost/token telemetry;
- fail-closed behavior.

It must not submit exchange credentials, orders, or strategy-promotion decisions.

## Non-blocking items

These do not block Phase 0 after the gates above are accepted:

- the permanent public brand name;
- dashboard implementation, because the dashboard is explicitly after the domain/API vertical slice;
- Kafka, Redis/Celery, Kubernetes, vector database, and feature-store products; the proposal correctly excludes them for Version 1;
- live/demo account setup, which remains a later governance and venue/compliance decision;
- any profitability claim; current screen results remain rejection evidence, not a reason to force a candidate.

## Decision

**Proposal:** ready for user acceptance after the version and deployment-model corrections in this audit.  
**Development:** not yet cleared as a fully reproducible setup.  
**Deployment:** blocked until Kainode hardening and runtime bootstrap pass.  
**Trading:** remains paper-safe; no exchange credential or order path is approved.

The correct next action is not to install everything blindly. It is to approve the proposal, harden Kainode, create the isolated local lockfile environment, and then execute only Phase 0 with failing tests first.

## Post-approval execution addendum — 2026-08-06 10:39 UTC

The user approved the proposal. The following safe steps were executed without exchange credentials, OpenCode credentials, order endpoints, live services, or trading activity:

- Kainode non-root administrative user `afbot` was created and verified through a fresh ED25519 key-based SSH session.
- UFW was enabled with default deny incoming, default allow outgoing, and SSH port 22 as the only explicit inbound rule.
- Fail2ban was installed, enabled, and verified active.
- Effective SSH policy was verified as `PermitRootLogin=no`, `PasswordAuthentication=no`, `KbdInteractiveAuthentication=no`, and `PubkeyAuthentication=yes`.
- No failed systemd units or public application listeners were observed after hardening.
- A newer kernel was available after package installation; reboot remains deferred until an explicit maintenance window and post-reboot access verification.
- The local project now has `pyproject.toml`, `.python-version`, `.gitignore`, `.venv`, and `uv.lock`.
- `uv 0.12.2` resolved 67 packages and installed 66 locked packages into the project-local environment using CPython 3.14.7.
- The project-local test suite passed with `8 passed in 6.28s`.
- Ruff check and format verification passed for the five research Python files.

Remaining gates are PostgreSQL private deployment, application/API implementation, deterministic scheduler and risk components, provider/model preflight after credential rotation, and later paper-runtime verification. No production or trading path has been activated.

## Sources

[1] https://www.python.org/downloads/release/python-3147
[2] https://fastapi.tiangolo.com/release-notes
[3] https://www.postgresql.org/docs/current/release-18-4.html
[4] https://pypi.org/project/uv
[5] https://nodejs.org/en/about/previous-releases
[6] https://www.npmjs.com/package/react
[7] https://www.npmjs.com/package/vite
[8] https://www.npmjs.com/package/typescript
[9] https://www.npmjs.com/package/tailwindcss
[10] https://www.npmjs.com/package/shadcn
[11] https://pypi.org/project/binance-sdk-derivatives-trading-usds-futures
[12] https://pypi.org/project/psycopg
[13] https://pypi.org/project/pandas
[14] https://pypi.org/project/numpy
[15] https://pypi.org/project/polars
[16] https://pypi.org/project/pyarrow
[17] https://pypi.org/project/fastapi
[18] https://pypi.org/project/pydantic
[19] https://pypi.org/project/uvicorn
[20] https://pypi.org/project/sqlalchemy
[21] https://pypi.org/project/alembic
[22] https://pypi.org/project/httpx
[23] https://pypi.org/project/structlog
[24] https://pypi.org/project/pytest
[25] https://pypi.org/project/hypothesis
[26] https://pypi.org/project/ruff
[27] https://pypi.org/project/mypy
[28] https://pypi.org/project/cryptography
