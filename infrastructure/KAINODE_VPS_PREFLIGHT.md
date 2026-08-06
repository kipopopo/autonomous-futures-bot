# Kainode VPS — Read-Only Preflight

**Target:** `147.79.18.15`  
**Role:** Proposed dedicated VPS for Autonomous Futures Bot research, paper runtime, and later isolated demo work  
**Method:** Read-only SSH inspection only. No packages, firewall rules, users, SSH settings, services, project files, or credentials were changed.

## Verified capacity

| Resource | Observed value |
|---|---:|
| Hostname | `kipopopo` |
| OS | Ubuntu 24.04.4 LTS |
| Kernel | `6.8.0-124-generic` |
| CPU | 6 × QEMU virtual CPU cores |
| RAM | 15 GiB total; about 15 GiB available at check time |
| Swap | Not configured |
| Root disk | 116 GiB total; 113 GiB free (2% used) |
| Load average | 0.15 / 0.29 / 0.18 |
| Python | 3.12.3 |
| Git | 2.43.0 |

The host is materially more suitable for parallel cached research than the existing one-vCPU Hostinger VPS. It is also clean: no application listener was found beyond SSH and local resolver services, no failed systemd units were reported, and `/root` contains no project deployment directory.

## Current network and security posture

### Good baseline

- SSH connectivity works.
- NTP is synchronized and enabled.
- `unattended-upgrades` is active and enabled.
- Only SSH is publicly listening in the observed TCP list.
- No failed systemd units were reported.

### Must remediate before any project deployment

| Finding | Observed state | Required remediation |
|---|---|---|
| Firewall | UFW inactive | Define deny-by-default rules; allow SSH from an approved source and later only required HTTPS/dashboard ports. |
| Root login | `PermitRootLogin yes` | Create a dedicated non-root deploy/operator user; disable direct root login after key access is proven. |
| Password SSH | `PasswordAuthentication yes` | Install and verify SSH keys, then disable password authentication. |
| Root authorized key | Absent | Add a restricted operator/deploy public key before removing password access. |
| Swap | None | Decide after workload benchmarking whether a small bounded swap file is desirable; do not add it blindly. |

> The supplied root password was used only for this interactive inspection. It is not recorded in this report. Because it was pasted into chat, rotate it before production hardening and replace password SSH with key-based access.

## Parallel research capacity proposal

This is a **6-core / 16 GB** host. The initial research layout should use four CPU-heavy workers and reserve capacity for the operating system, PostgreSQL, dashboard, data collection, aggregation, and burst handling:

```text
4 × CPU-bound causal evaluation workers
3 × bounded public-data I/O fetch slots
4 × bounded network LLM slots shared by generator + critic roles
1 × single authoritative artifact / trial / qualification writer
1 × serial paper-risk / broker / reconciliation authority
```

The worker count is a starting policy, not an assumption of linear speedup. Before recurring research is enabled, run a cached-only benchmark at 1, 2, 4, and 5 CPU workers against the same fixed DatasetManifest and compare:

- wall-clock duration;
- CPU utilization and load average;
- peak RSS / swap use;
- disk I/O wait;
- deterministic equality of trial outputs.

Promote the worker cap from four to five only when the four-worker run demonstrates enough CPU/RAM/disk headroom and does not delay data, dashboard, or paper-risk work.

## Deployment decision

| Item | Status |
|---|---|
| Read-only host connectivity | **Pass** |
| Hardware claim: 6 CPU / 16 GB | **Confirmed** |
| Dedicated-host suitability for parallel research | **Pass, subject to benchmark** |
| Security hardening | **Not started; required before deployment** |
| Autonomous Futures Bot code deployment | **Not started** |
| Exchange credentials/order connectivity | **Not started** |

## Next controlled milestone

After explicit authorization to change the server, perform the security baseline first: rotate root password, install operator SSH key, create a dedicated deploy user, disable root/password SSH, configure UFW, and verify recovery access **before** transferring this project or creating any service.
