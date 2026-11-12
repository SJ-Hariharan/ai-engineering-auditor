# Release readiness assessment

**Verdict: not ready for a public release.** After the two P0 fixes in this pass, it is suitable for a
**private beta with trusted users** on a single instance, provided the P1 items in [PRIORITIZED_FIXES.md](PRIORITIZED_FIXES.md) are
tracked and users are told the score is not comparable across repositories.

**Current status (2026-11-12): v0.2.0 release candidate — deployable for a self-hosted, single-instance
deployment using the production overlay.** This supersedes both earlier verdicts. The record of each milestone,
with commands and results, is in [docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md).

- **New since v0.1.0:**
  - Restart policies and health checks for every service.
  - HTTPS production overlay (Caddy).
  - SEC-02 closed when that overlay is used: a trusted client IP, verified live with a second IP.
  - E-01, E-05, DET-11, the SEC-03 residual, and part of E-03.
  - CI that runs every suite and deploys the overlay and runs the live checks on every push (AC1–AC6 in
    the engineering log).
- **Still open:**
  - SEC-02 without the overlay, SEC-09/10;
  - Trivy inline ignores;
  - pnpm/yarn/poetry lockfile reachability;
  - E-03 (one full summary per view), E-04;
  - SC-04 to SC-07.
- **Not done:** no external penetration test and no load test. This is not a security certification.

**Previous status (2026-11-10): public v0.1.0 beta.**

- **Fixed since that assessment:** SEC-01, SEC-03, SEC-04, SEC-05, SEC-06, SEC-07, SEC-08, DET-01, DET-10,
  DET-16, SC-01, SC-02 and SC-03.
- **Mitigated:** SEC-02. A browser the user has already signed in with cannot be locked out; a brand-new
  browser can still be delayed during an active attack.
- **Re-tested on the rebuilt Compose stack:** 31/31 end-to-end flows and 7/7 abuse checks through the web
  proxy; 126 backend tests (including the real Docker sandbox); 97 frontend tests.
- **Still open, documented, not blocking a self-hosted beta:**
  - SEC-02 residual, SEC-09/10;
  - DET-11 and Trivy inline ignores;
  - E-01/03/04;
  - SC-04 to SC-07.
- **Not done:** no external penetration test and no load test. Both are still recommended before a hosted,
  multi-tenant service. This is not a security certification.

Companion documents:
- [TEST_RESULTS.md](TEST_RESULTS.md): what was run and the outcomes.
- [SECURITY_REVIEW.md](SECURITY_REVIEW.md): threats, PoCs, and the controls that hold.
- [DETECTION_BENCHMARK.md](DETECTION_BENCHMARK.md): accuracy measured against ground truth.
- [PRIORITIZED_FIXES.md](PRIORITIZED_FIXES.md): every issue with evidence and remediation.

Raw evidence (scripts and outputs) is in `docs/audit-evidence/` and `benchmarks/`.

**Independence caveat.** This audit was performed with AI assistance by the same team that built the application.
Three review subagents worked independently of the build context:
- **Quality and scoring:** completed. Its scripts were later lost when a scratch folder was cleared, so its key claims were re-verified and the re-run scripts are saved.
- **Detection benchmark:** completed, and preserved in `benchmarks/`.
- **Security review:** stopped by a usage limit, so the security checks were redone directly with saved PoCs.

An external penetration test is still recommended before any public launch. **Nothing here is a security certification.**

## 1. What works (verified)

- All suites pass: 62 backend tests (including a real Docker sandbox run), 93 frontend tests, lint, type-check, and the production build.
- The full Docker Compose stack builds and starts. Migrations run once under the advisory lock, and a real GitHub repository is audited end to end through the web proxy with all four scanners.
- The core security boundaries hold under test:
  - cross-user isolation on every resource;
  - path traversal blocked;
  - ZIP archive attacks rejected;
  - CSRF enforced through the proxy;
  - Gitleaks secrets masked;
  - AI consent gating;
  - the PR drift check;
  - sandbox network, environment and filesystem isolation.
- Detection matches its rules well: 89% recall and 85–90% precision on planted security issues, zero findings on the clean repository, and no false positives on 26 safe look-alikes.

## 2. What blocked release (found and fixed in this pass)

- **REL-01 (critical).** In the Compose/PostgreSQL deployment, every audit after the first per worker process failed, because forked RQ jobs reused the parent's database connection. It reproduced live with 3 audits and was invisible to the test suite, which uses SQLite and in-process jobs.
- **REL-02 (high).** A failed job could not record its failure, so audits stayed `running` forever and the project rejected reruns.

Both are fixed with small, separately tested changes. Re-test results are in TEST_RESULTS.md.

## 3. What still needs work before a public release

1. ~~**Result integrity (SEC-01).**~~ **Fixed in a follow-up pass.** Repository suppression files and comments are now ignored and listed in the report. The only residual is Trivy inline `trivy:ignore` comments.
2. **Real-world accuracy (DET-11, DET-01).**
   - ~~Monorepo false import errors (DET-10)~~ fixed: 208 → 0 on the FastAPI template. A related OSV `.gitignore` gap that hid vulnerable dependencies (DET-16) was found and fixed.
   - Dev tooling in lockfiles is rated critical.
   - Common SQL concatenation forms are missed.
3. **Scoring (SC-03..07).** ~~SC-01, SC-02~~ fixed in a follow-up pass. Details in §5.
4. **Operations:**
   - ~~retention is not enforced on idle instances (SEC-08)~~ fixed: hourly cleanup service and orphan sweep (not yet run live in Compose);
   - anyone can lock a user out (SEC-02);
   - uploads, clones and audit counts are not bounded (SEC-04/05/06);
   - ~~production defaults are unsafe (SEC-07)~~ partly fixed: production now refuses insecure cookies and inline jobs; registration is still open by default;
   - ~~secrets verbatim in non-Gitleaks evidence (SEC-03)~~ fixed (redacted before storage and export);
   - the polling payload grows to megabytes (E-03).

## 4. Engineering quality

Objective defects are separated from subjective recommendations. Evidence and line numbers for each item are in PRIORITIZED_FIXES.md.

**Objective defects (verified):**
- REL-01/02 (fixed).
- Failed audits keep partial findings and their workspace (E-02).
- Fingerprint collisions (E-01).
- Gitleaks fingerprint includes the line number (E-05).
- N+1 queries and unbounded lists (E-04).
- An oversized summary blob sent on every poll (E-03).
- ~~Retention depends on job traffic (SEC-08).~~ Fixed (hourly cleanup).
- Each file is parsed with tree-sitter three times per audit (`pipeline.py` + `design.py`). The analyzer takes about 50 s on 360k lines.
- `run_tool` buffers the full scanner output before truncating it (`sandbox/process.py`).
- Dead `backend/src/auditor_backend` stub; no CI.

**Subjective recommendations:**
- `jobs.py` mixes queueing, orchestration, persistence, comparison and retention. Split them.
- `api/audits.py` imports serializers from `api/projects.py`. Move them to a shared module.
- The analyzer core is the least maintainable part, judged by the tool's own rules: six functions with cyclomatic complexity 33–40 in `design.py`, `inventory.py` and `parsing.py`, and `design.py` is 807 lines.
- Logging is unstructured, with no audit id.
- The frontend polls every 2 s with no backoff or upper bound.
- Frontend score colours use different thresholds from the backend grades.

**Strengths:**
- The AI layer is cleanly separated (analysis never imports `app.llm`).
- Owner-scoped loaders are centralised in `api/deps.py`.
- Typed API contract; Pydantic validation on every input.
- Migrations with a concurrency-safe startup.
- The frontend has strict TypeScript and no unsafe HTML rendering of repository content (the only `dangerouslySetInnerHTML` is a constant theme script).

## 5. Scoring methodology

**Checked and consistent:**
- The weights sum to 1.0.
- The overall score is the weighted mean of the category scores.
- The formula matches the documentation.
- Runs are reproducible for a fixed input and scanner state (two offline and two online runs gave identical scores).

**Problems (all verified with `docs/audit-evidence/scoring_fingerprint_checks.py` unless noted):**

| ID | Problem | Measurement |
|---|---|---|
| SC-01 ✅ | Categories with nothing analysed, or whose scanner failed, score 100 and pull the overall up | A lone critical secret gives overall 89.8 (**B**). With Semgrep failing, the fixture scored 74.8 instead of 60.4 (quality reviewer). **After the fix** (`scoring_sc01_sc02_output.txt`): lone critical → 79.9 **C**; nothing analysable → N/A instead of 100; Go-only repo with one secret → 81.9 instead of 94.6; Semgrep failing → security marked incomplete, overall capped at 89.9. The fixture still scores 75.8 vs 61.4 with Semgrep failing: missing findings cannot be recovered, only flagged |
| SC-02 ✅ | One root cause reported under several rules is counted several times | Same issue as 1 rule → security 81.9; as 4 rules → 44.9. **After the fix:** 81.9 for both; 4 rules on 4 different lines still 44.9. On the benchmark, vuln_js (eval + XSS on one line) 69.7 D → 70.2 C |
| SC-03 | Order-dependent: the 1/k discount is assigned before sorting by confidence | 6 identical findings in 200 orders → 20 distinct scores (66.0–76.3) |
| SC-04 | No size normalisation, so large repos accumulate deductions; subjective findings weigh as much as objective ones | `compute_scores` takes findings only (code); code-quality and maintainability (30% of weight) are almost entirely subjective threshold rules |
| SC-05 | Diminishing returns per rule make distinct real instances nearly free after about 10 | 10 vs 100 SQL injections across different files: 55.7 vs 35.4 (quality reviewer) |
| SC-06 | Constants are arbitrary and uncalibrated | Severity points (25/12/5/1.5/0.3), confidence factors, weights, the /60 decay and grade bands are not derived from data. The docstring says one critical gives "around 60"; it gives 65.9 |
| SC-07 | Confidence means different things per tool | Gitleaks is "high" outside example paths; dependency advisories are always "high"; quality thresholds are "high" because the measurement is exact, even though the finding is subjective |

**Conclusion.** The score is a reasonable within-repository progress indicator, re-running the same repository with the same
tools. It is **not** valid for comparing repositories. SC-01 and SC-02 are now fixed: unanalysed categories no
longer score 100, failed scanners are flagged and capped, a critical finding limits the grade, and one root cause is
penalised once. SC-03 to SC-07 (order dependence, no size normalisation, arbitrary constants) remain, so the score
should still not be presented as a quality grade. The in-app methodology text already says this is not a
certification, which is correct and should stay.

## 6. Changes made in this pass

| Change | Why | Files |
|---|---|---|
| Fork-safe database connections in the worker | REL-01 | `backend/app/worker.py`, `backend/app/jobs.py` |
| Failure recording in a fresh session; stale-audit recovery | REL-02 | `backend/app/jobs.py`, `backend/app/api/projects.py` |
| Tests for both | regression protection | `backend/tests/test_jobs.py` |
| Restored the test fixture's fake `.env` (dropped by a folder move) | tests depend on it | `backend/tests/fixtures/vulnerable_app/.env` |
| App-controlled scanner configuration; repo suppressions ignored and reported (UI note, Markdown export, `summary.suppressions`) | SEC-01 | `backend/app/analysis/scanners/{semgrep,gitleaks,deps,suppressions}.py`, `backend/app/analysis/scanner_config/`, `backend/app/analysis/pipeline.py`, `backend/app/api/audits.py`, `frontend/src/components/report/overview-tab.tsx`, `frontend/src/lib/types.ts`, `tests/test_scanner_suppression.py` |
| JS/TS import resolution: nearest tsconfig per file, JSONC, `extends`, asset and root-absolute imports; configured aliases internal | DET-10, DET-03 | `backend/app/analysis/graph.py`, `tests/test_import_resolution.py` |
| OSV-Scanner run with `--no-ignore` | DET-16 | `backend/app/analysis/scanners/deps.py`, `tests/test_scanner_suppression.py` |
| Per-category coverage (N/A + renormalised weights), critical and incomplete caps; same-location findings scored once; UI and Markdown show N/A, caps and incompleteness | SC-01, SC-02 | `backend/app/analysis/scoring.py`, `backend/app/analysis/pipeline.py`, `backend/app/api/audits.py`, `frontend/src/lib/types.ts`, `frontend/src/components/report/overview-tab.tsx`, `tests/test_scoring.py`, `overview-tab.test.tsx`, `benchmarks/run_bench.py`, `benchmarks/make_report.py` |
| `.env.example`: `AUDITOR_SANDBOX_ENABLED=false` (was `true`, contradicting the documented Compose default) | CFG-01 | `.env.example` |
| Corrected false claims in SECURITY.md / ARCHITECTURE.md (cleanup job, masked Markdown evidence) | DOC-01 | docs |
| Added the detection benchmark and audit evidence to the repository | reproducibility | `benchmarks/`, `docs/audit-evidence/` |

No security control was disabled. The only configuration change is the safer `.env.example` sandbox default above.
No repository code was executed outside the existing sandbox.

**Re-test:** 68/68 backend tests and 30/31 live checks against the rebuilt Compose stack, including four
sequential audits in one worker; the one failing check is CFG-01, now fixed in the example config. See TEST_RESULTS.md.

**Re-test after SC-01/SC-02:** 102 backend tests pass (1 Docker test skipped), 97 frontend tests, lint and
type-check. The detection benchmark shows unchanged findings and recall. See TEST_RESULTS.md.
