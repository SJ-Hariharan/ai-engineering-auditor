# Prioritized fixes

Ordered by what blocks release first. Severity reflects actual impact. Status is **VERIFIED** (reproduced) or
**SUSPECTED** (code reading). Security items are detailed in [SECURITY_REVIEW.md](SECURITY_REVIEW.md) and detection
items in [DETECTION_BENCHMARK.md](DETECTION_BENCHMARK.md). Items marked ✅ were fixed in this pass and re-tested (see
TEST_RESULTS.md).

## P0 — release blockers

### REL-01 — Every audit after the first per worker process fails in the production deployment (Critical, VERIFIED) ✅
- **Evidence:**
  - `backend/app/worker.py:16-21`: `init_db()` opens a pooled PostgreSQL connection in the parent process, then `Worker.work()` forks a child per job.
  - `backend/app/core/database.py:20-26`: the engine is cached with `lru_cache`, so children reuse the inherited pool and socket.
- **Reproduction:** `docker compose up --build`, then run two audits (for example `scripts/smoke.py` twice with different repos).
  - The second audit stays `running`.
  - The worker log shows `psycopg.errors.DuplicatePreparedStatement: prepared statement "_pg3_0" already exists` at `jobs.py:73` (`on_stage` commit).
- **Impact:** In Docker Compose, the documented deployment, the product works for exactly one audit per worker start.
- **Fix:**
  - Dispose the inherited engine pool in the worker parent before forking (`worker.py`).
  - At the start of every job, call `engine.dispose(close=False)` so a forked child never uses the parent's sockets (`jobs.py`).
- **Test:** `tests/test_jobs.py::test_job_does_not_reuse_parent_connection`; re-run of the Compose flow with several sequential audits.

### REL-02 — A failed or killed job leaves the audit "running" forever and locks the project (High, VERIFIED) ✅
- **Evidence:**
  - `backend/app/jobs.py:101-105`: the `except Exception` path sets `failed` and commits on the same, possibly broken, session. When that commit raises, as in REL-01, the audit is never updated.
  - Nothing detects a worker that died (OOM, restart, RQ timeout).
  - `api/projects.py:160-161` then refuses every rerun with 409 "An audit is already in progress".
  - The UI polls forever.
- **Reproduction:** live in Compose (REL-01). The quality reviewer also simulated a dead worker in-process.
- **Fix:**
  - Roll back the session, and record the failure in a fresh session.
  - Mark audits stuck in `queued`/`running` longer than the job timeout as `failed` ("worker lost"), at worker start and before a rerun is refused.
- **Test:** `tests/test_jobs.py` (`test_failure_is_recorded_even_if_session_is_broken`, `test_stale_running_audit_does_not_block_rerun`).

## P1 — fix before inviting users

| ID | Severity | Item | Status | Evidence | Remediation |
|---|---|---|---|---|---|
| SEC-01 ✅ | High | Scanned repo can suppress its own findings (`.semgrepignore`, `nosemgrep`, `.gitleaks.toml`): Semgrep 16→0, score 60.4→82.7. **Fixed:** app-controlled scanner config, suppressions reported; residual: Trivy inline ignores | VERIFIED | `scanners/semgrep.py:24`, `scanners/gitleaks.py:19` | `--disable-nosem`, app-controlled ignore and Gitleaks config; show suppressions explicitly |
| DET-10 ✅ | High | Monorepo tsconfig handling: 208 unresolved-import FPs (70% of findings) on a popular template. **Fixed:** 0 FPs, recall unchanged or better | VERIFIED |
| DET-16 ✅ | High | OSV-Scanner honoured `.gitignore` files (the repo's own and any above the workspace): vulnerable dependencies silently not reported, and in local dev never reported. **Fixed:** `--no-ignore` | VERIFIED | `analysis/graph.py:85-95` | Find the nearest tsconfig per file; strip block comments; understand Vite `/` imports |
| E-01 ✅ | High | Fingerprint collisions: identical defects merge into one; a newly added copy shows "0 new" on rerun. **Fixed:** every occurrence is kept; the 2nd, 3rd … in line order get an indexed fingerprint and the first keeps the old one (`scoring_fingerprint_output_after_e01_e05.txt`: 2 findings instead of 1; an added copy is new) | VERIFIED | `pipeline.py` `_dedupe` | Add the occurrence index to the fingerprint |
| SC-01 ✅ | High | Missing or failed scanners and empty categories score 100; a lone critical secret still grades B (89.8). **Fixed:** categories with no coverage are N/A and weights renormalise; high-confidence critical caps overall at 79.9 (lone secret → C); skipped/failed/not-run security scanner caps at 89.9 and marks the result incomplete. Residual: a failed scanner's missing findings cannot be recovered (Semgrep-failing fixture 75.8 vs 61.4, now flagged incomplete) | VERIFIED | `analysis/scoring.py` (`build_coverage`, `compute_scores`), `pipeline.py` | Mark categories N/A, renormalise weights, cap the grade when a critical exists or a scanner failed |
| SC-02 ✅ | High | One root cause reported by several rules is counted several times (81.9 → 44.9); `_dedupe` docstring is wrong. **Fixed:** same category + file + line scored once (most severe, order-independent): 4 rules → 81.9. Every finding is still listed; `_dedupe` docstring corrected. Residual: two different issues on one line in one category are scored as one | VERIFIED | `scoring.py` (`scored_findings`), `pipeline.py` `_dedupe` | Deduplicate by location across rules; keep the most severe finding |
| SEC-08 ✅ | Medium | Source copies outlive the advertised 24 h retention on idle instances. **Fixed:** hourly `cleanup` service in Compose; purge also sweeps unreferenced folders older than the TTL (`tests/test_jobs.py`). Not yet run live in Compose | VERIFIED | `jobs.py:69`, `worker.py:21` | Periodic purge, sweep by mtime, test |
| SEC-02 ✅ (with the production overlay) | Medium | Anyone can lock a user out (shared IP behind the proxy). **Fixed:** failure-only counting; device cookies protect known browsers; with `docker-compose.prod.yml`, Caddy supplies a trusted client IP, so each IP has its own budget per email (caps: 100 per email across IPs, 50 per IP). Verified live in CI: a new browser on another IP signs in during an attack. Without the overlay a new browser can still be delayed | VERIFIED | `api/auth.py`, `deploy/Caddyfile` | Failure-only, per-email back-off; device cookies; trusted client IP |
| SEC-03 ✅ | Medium | Secrets verbatim in Semgrep evidence and the Markdown export. **Fixed:** all evidence redacted before storage (`jobs.py`), again on read in the findings API (covers audits stored earlier) and in the export; the file viewer redacts line by line, keeping line numbers. Residual: redaction is pattern-based | VERIFIED | `scanners/semgrep.py:69` | Redact all evidence before storing |
| SEC-07 ✅ | Medium | Unsafe production defaults, no validation. **Fixed:** production refuses to start without secure cookies, worker jobs and a 32+ character secret; `.env.production.example` (registration closed, rejected until filled in); sandbox off by default in code | VERIFIED | `core/config.py` | Production settings validator |
| DET-01 ✅ | Medium | 3-operand SQL concatenation missed (3 of 9 SQLi cases). **Fixed:** `"..." + x + "..."` patterns for direct and intermediate-variable queries (Python, JS/TS) | VERIFIED | `rules/python.yml`, `rules/javascript.yml` | Add nested-concatenation patterns |
| DET-11 ✅ | Medium | Dev-tooling advisories rated critical/high. **Fixed:** lockfile reachability (`uv.lock`, `package-lock.json`, `bun.lock`); advisories for packages reachable only through dev/test dependencies are lowered one level with medium confidence and labelled "dev tooling, transitive". itsdangerous 3 criticals → 0 | VERIFIED | `inventory.py`, `scanners/deps.py` | Parse lockfile dependency groups |
| E-03 (partly ✅) | Medium | `Audit.summary` reaches ~2.6 MB on a 529-file repo and was returned on every poll. **Fixed:** the report polls `GET /api/audits/{id}/status` (a few hundred bytes) and fetches the full audit only when the status or test run changes. Open: the full summary is still sent once per report view and stored in one JSON column | VERIFIED by reviewer | `pipeline.py` summary, `projects.py audit_out` | Store symbols/graph separately; slim polling endpoint |
| SEC-04/05/06 ✅ | Medium | Upload body unbounded before the check; clone unbounded until it finishes; no per-user quotas. **Fixed:** body-size middleware before parsing; clone watchdog kills git past the size limit; 2 concurrent / 50 daily audits per user (configurable) | VERIFIED (tests) | `core/body_limit.py`, `ingestion/github.py`, `api/projects.py` | Proxy body limit; pre-clone size check; per-user concurrency |

## P2 — quality and accuracy

| ID | Severity | Item | Status |
|---|---|---|---|
| SC-03 ✅ | Medium | Score depends on input order (20 distinct scores for the same 6 findings) — `scoring.py:56` sorts by severity only. **Fixed:** sorted by deduction with a deterministic tie-break; 1 score in 200 orders | VERIFIED |
| SC-04 | Medium | No size normalisation; subjective findings weigh the same as objective ones | VERIFIED |
| E-02 | Medium | A failed audit keeps partial findings and its workspace (`jobs.py:90-105`) | VERIFIED by reviewer |
| E-04 | Medium | N+1 queries on `GET /api/projects` and no pagination on list endpoints | VERIFIED by reviewer |
| E-05 ✅ | Medium | Gitleaks fingerprint includes the line number, so a moved secret shows as "resolved + new" (`gitleaks.py:67`). **Fixed:** line removed from the key; identical secrets in one file are told apart by occurrence order. One-time effect: Gitleaks findings get new fingerprints on the first re-run after upgrading | VERIFIED |
| DET-02..07 | Medium/Low | JS auth heuristic, alias→npm, fs path traversal, session cookie, DB URL secret, fan-in hub | VERIFIED |
| DET-12/13/14 | Low | Severity inconsistency (.env vs source), verb-based auth rule, quality noise on real code | VERIFIED |
| TEST-01 | Medium | Tests depend on host scanners and a dotfile fixture; no tests for worker, purge, run_tests, or rerun on a changed repo; `worker.py` 0% coverage | VERIFIED |
| ENG-LOG | Low | Unstructured logs, no audit/request id, stage timings not recorded | VERIFIED (code) |
| SEC-09/10/11 | Low | Install-phase network, enumeration, dev-dependency advisories | see SECURITY_REVIEW |
| CFG-01 | Low | Compose meant to default the sandbox to off, but `.env.example` set `AUDITOR_SANDBOX_ENABLED=true`, which Compose interpolates, so the API accepted test runs (202) and the worker skipped them for lack of Docker. No code ran. | VERIFIED ✅ `.env.example` now `false` |
| HYG-01 | Low | Dead `backend/src/auditor_backend` stub; no CI configuration | VERIFIED |
| DOC-01 | Low | SECURITY.md/ARCHITECTURE.md claim a cleanup job and masked Markdown evidence, and neither exists | VERIFIED ✅ corrected in docs |
