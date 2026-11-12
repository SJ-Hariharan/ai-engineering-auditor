# Test results

Every result below was produced by running the command shown, on 2026-11-08 (macOS arm64, Docker Desktop 29.7.2).
Nothing here is inferred. Where a step was not run, it says so.

## 1. Automated suites

| Suite | Command | Result |
|---|---|---|
| Backend unit/integration (pytest) | `cd backend && .venv/bin/pytest -v -p no:warnings -rs` | **62 passed**, 0 failed, 0 skipped (59 s), including the real Docker sandbox test |
| Backend lint | `.venv/bin/ruff check app tests migrations` | All checks passed |
| Frontend unit/component (Vitest) | `cd frontend && npm test` | **93 passed** (9 files) |
| Frontend types | `npx tsc --noEmit` | exit 0 |
| Frontend lint | `npm run lint` | exit 0 |
| Frontend production build | `npm run build` | exit 0, compiled successfully |
| Frontend production dependencies | `npm audit --omit=dev` | 0 vulnerabilities |
| Backend dependencies | `osv-scanner scan source backend/uv.lock` | 0 advisories |

Notes and anomalies:

- **First run: 2 failed.** `test_full_audit_flow` and `test_ai_overview_is_redacted_cached_and_injection_wrapped` failed because the fixture's `.env` file (fake keys) was missing. The project-move step drops `.env` files. After restoring the fixture, all tests passed. This is a test-design fragility: the suite depends on a dotfile that git hygiene and copy tools commonly strip (see TEST-01 in PRIORITIZED_FIXES).
- The pytest process reported 59 s of test time, but the wrapping `time` showed 1 h 31 m wall-clock before the process exited. The machine may have slept. A hang after the session ends (lingering thread or subprocess) was **not** investigated or ruled out.
- Scanner-dependent tests need `semgrep`/`gitleaks` on the host. Under the Claude command sandbox Semgrep crashes, so the suite was run outside it. The independent reviewer observed `test_full_audit_flow` failing when Semgrep was unusable. The tests are not hermetic.
- Coverage, measured by the quality reviewer with pytest-cov: 82% lines overall. `worker.py` 0%, `ingestion/github.py` 26%, `sandbox/docker_tests.py` 22%, `scanners/semgrep.py` 52%. The raw report was lost with the reviewer's scratch folder, so these numbers are reported, not re-measured.

## 2. Builds and full-stack startup

| Step | Command | Result |
|---|---|---|
| Docker Compose build + start | `docker compose -p auditor up --build -d` | **Succeeded** in 3 m 38 s. db (healthy), redis, api, worker, web running |
| Migrations at startup | API and worker logs | `Running upgrade -> 0001_initial` ran once (worker), API waited on the advisory lock, both started |
| End-to-end audit through the web proxy | `.venv/bin/python scripts/smoke.py --api http://localhost:3000 --github https://github.com/pallets/itsdangerous` | **Completed**: commit `672971d`, score 81.4 (B), all 4 scanners `ok`, 25 findings |
| Second audit (ZIP upload of the fixture) | `docs/audit-evidence/live_flows.py` against Compose | **FAILED — stuck `running` at stage `quality` indefinitely** |
| Third audit (GitHub `pallets/markupsafe`) | `scripts/smoke.py … --timeout 90` | **FAILED — stuck `running` at stage `quality`** |

**Root cause of the stuck audits (REL-01, verified):** the RQ worker forks one process per job, and each child
inherits the parent's open PostgreSQL connection. The second and later jobs fail with
`psycopg.errors.DuplicatePreparedStatement: prepared statement "_pg3_0" already exists`.
The failure handler then tries to mark the audit failed on the same broken connection, so the audit stays
`running` forever (REL-02). The worker log showed this 6 times. Only the first audit after each worker start succeeds.
The local test suite never caught it because it uses SQLite and runs jobs in-process.
After the fix, see §5 for re-test results.

## 3. Live flows against the Compose stack

Script: `docs/audit-evidence/live_flows.py`. Before the fix it stopped at the stuck ZIP audit, so the steps after that
were first exercised through the in-process test client:

| Flow | Result | Where |
|---|---|---|
| Register, login, wrong password 401, logout then 401 | pass | Compose (smoke) + `tests/test_api.py` |
| Cookie HttpOnly + SameSite=Lax | pass | `test_auth_lifecycle` |
| CSRF header enforced through the proxy | pass | live (403) |
| GitHub ingestion + analysis + findings | pass (first job only before fix) | Compose |
| ZIP ingestion + analysis | pass in-process; **fails in Compose before fix** | REL-01 |
| File viewer, secret masking, traversal blocked | pass | `security_pocs.py` P3c/P5 |
| Deterministic fix → diff → approve | pass | `test_deterministic_fix_approval_and_pr_rules`, `security_pocs.py` |
| PR workflow | **not run against GitHub** (would need a real token and repository). Request validation, refusal for ZIP projects, and drift abort tested with a mocked GitHub API | `tests/test_remediation_llm.py` |
| AI explanations / AI fixes | consent gating verified; generation tested with a **fake provider only** (no API key configured) | tests |
| Sandboxed test run | real Docker run passes (`test_sandbox.py`); disabled in Compose by default (API returns 503) | |
| Rerun + comparison | identical rerun passes; **changed-repo comparison is wrong**: a newly added duplicate defect shows as 0 new (E-01) | `scoring_fingerprint_checks.py` F2 |
| Cross-user isolation | pass on all 11 operations | `security_pocs.py` P4 |
| Delete project removes workspace | pass | `test_delete_project_removes_workspace` |

## 4. Security and accuracy checks

- `docs/audit-evidence/security_pocs.py` → `security_pocs_output.txt`: 4 VULNERABLE (P1, P3a, P3b, P6a–c) and 5 HOLDS.
- `docs/audit-evidence/scoring_fingerprint_checks.py` → `scoring_fingerprint_output.txt`.
- Detection benchmark: `benchmarks/run_all.sh` (see DETECTION_BENCHMARK.md).

## 5. After the critical fixes

See the "Re-test after fixes" section appended below.

## Re-test after fixes (REL-01, REL-02)

| Check | Command | Result |
|---|---|---|
| Backend suite | `cd backend && .venv/bin/pytest -p no:warnings -rs` | **67 passed, 1 skipped** (Docker was down at that moment); the skipped `test_sandbox.py` was then run with Docker up: **passed**. Total 68/68 |
| New regression tests | `tests/test_jobs.py` (6 tests) | pass. **Mutation check:** with the fork hook and stale-audit sweep removed, `test_forked_child_does_not_reuse_parent_connections` and `test_stale_running_audit_does_not_block_rerun` **fail**, so the tests detect the bugs |
| Lint | `.venv/bin/ruff check app tests migrations` | All checks passed |
| Compose rebuild | `docker compose -p auditor up --build -d` | all 5 services running |
| Stale-audit recovery | worker startup log | `marked 2 stale audit(s) as failed`. The two audits stuck since the previous run now read "The analysis worker stopped before this audit finished. Please re-run it." |
| Live flows (4 audits back to back in one worker) | `.venv/bin/python -u ../docs/audit-evidence/live_flows.py http://localhost:3000` | **30/31 passed** (`docs/audit-evidence/logs/live-flows-after-fixes.txt`). Sequential GitHub audits #1 and #2 completed (18 s, 19 s), the ZIP audit as the 3rd job (13 s, all 4 scanners ok, 36 findings), and the rerun as the 4th job with comparison (0 new / 0 resolved / 36 persisting) |
| The 1 failing live check | expected 503 for a sandbox test run in Compose | Got 202: CFG-01, a config mismatch. The worker skipped the run because it has no Docker access, so no code executed. `.env.example` now defaults to `false` |

Frontend code was not changed by the fixes. The frontend results in §1 still apply.

## Re-test after SEC-01 fix (scanner suppression)

| Check | Command | Result |
|---|---|---|
| Backend suite | `cd backend && .venv/bin/pytest -p no:warnings -rs` | **74 passed** (68 + 6 new in `tests/test_scanner_suppression.py`), log `docs/audit-evidence/logs/pytest-sec01.txt` |
| New tests caught a real gap | first run of `test_gitleaks_ignores_repo_config_ignorefile_and_allow_comments` | **failed**: Gitleaks still honoured `<source>/.gitleaksignore` despite `--gitleaks-ignore-path`. Fixed by moving the file aside during the scan; the test now passes and checks the file is restored |
| Lint | `.venv/bin/ruff check app tests migrations` | All checks passed |
| Security PoCs | `.venv/bin/python ../docs/audit-evidence/security_pocs.py` | P6a/P6b/P6c now **HOLD** (Semgrep 16→16, score 60.4→60.4, Gitleaks 2→2, SQLi still reported). Unrelated open items P1, P3a, P3b still reproduce as expected (`security_pocs_output_after_sec01.txt`) |
| Frontend | `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build` | exit 0 / exit 0 / 93 passed / compiled |
| Docker image | not rebuilt for this change | The image pins the same scanner versions used here (Semgrep 1.182.0, Gitleaks 8.30.1, OSV-Scanner 2.7.0, Trivy 0.76.1) |

## Re-test after DET-10 fix (import resolution) and DET-16 (OSV `.gitignore`)

| Check | Command | Result |
|---|---|---|
| Backend suite | `cd backend && .venv/bin/pytest -p no:warnings -rs` | **79 passed, 1 skipped** (Docker sandbox test; Docker was not running), log `docs/audit-evidence/logs/pytest-det10.txt`. Includes 6 new tests in `tests/test_import_resolution.py` and the `--no-ignore` assertion |
| Lint | `.venv/bin/ruff check app tests migrations` | All checks passed |
| Detection benchmark | `bash benchmarks/run_all.sh` (log `docs/audit-evidence/logs/benchmark-det10.txt`) | All 4 scanners `ok` on every repo. FastAPI template **295 → 87 findings, 0 unresolved-import** (was 208 FPs), score 58.4 → 68.2. Synthetic recall **74/83 → 75/83** (broken TS alias now detected). clean_repo still 0 findings. itsdangerous unchanged (25, 81.4) |
| Regression caught during measurement | first re-run | itsdangerous dropped to 0 OSV findings. Traced to OSV honouring `.gitignore` (the audit had git-ignored `benchmarks/real/`). Same effect for a repo `.gitignore` listing `uv.lock` (11 → 0) and for local dev workspaces under the git-ignored `backend/var/`. Fixed with `--no-ignore`; verified 0 → 11 |

## Re-test after SC-01 and SC-02 fixes (scoring)

Run on 2026-11-10 (macOS arm64). Docker was not running, so the sandbox test was skipped.

| Check | Command | Result |
|---|---|---|
| Backend suite | `cd backend && .venv/bin/pytest -p no:warnings -rs` (outside the Claude command sandbox, where Semgrep crashes) | **102 passed, 1 skipped** (Docker sandbox test), log `docs/audit-evidence/logs/pytest-sc01-sc02.txt`. Includes 23 new tests in `tests/test_scoring.py`. Inside the command sandbox, 2 Semgrep-dependent tests fail with a Semgrep crash, as noted in §1 |
| Mutation check | Each fix disabled in turn in `scoring.py`, then `pytest tests/test_scoring.py` | No same-location grouping → 3 tests fail; no N/A → 5 fail; no caps → 7 fail. File restored and verified byte-identical |
| Backend lint | `.venv/bin/ruff check app tests migrations` | All checks passed |
| Backend types | `.venv/bin/mypy app/analysis/scoring.py app/analysis/pipeline.py app/api/audits.py --ignore-missing-imports` | No errors in the new scoring code. Older errors remain in `pipeline.py` `_data_flow`, `audits.py:80` and other modules. mypy is not part of the documented checks |
| Frontend types / lint / tests | `npx tsc --noEmit`, `npm run lint`, `npm test` | exit 0 / exit 0 / **97 passed** (10 files; 4 new in `overview-tab.test.tsx`) |
| Frontend build | `npm run build` | **Not completed here:** Turbopack failed with `binding to a port: Operation not permitted` in this environment (also outside the command sandbox). `npx next build --webpack` **compiled successfully** with all 6 routes. The browser UI was not checked by hand; rendering is covered by the component tests |
| SC-01/SC-02 evidence | `.venv/bin/python ../docs/audit-evidence/scoring_sc01_sc02_checks.py` | `docs/audit-evidence/scoring_sc01_sc02_output.txt`. The "before" values reproduce the documented numbers exactly (44.9, 89.8, 60.4, 74.8) |
| Earlier scoring checks | `scoring_fingerprint_checks.py` | `scoring_fingerprint_output_after_sc01_sc02.txt`: S3 now 79.9 C. F1/F2 (E-01) and S2 (SC-03) are unchanged, as expected: those issues are not part of this fix |
| Detection + scoring benchmark | `bash benchmarks/run_all.sh` (log `docs/audit-evidence/logs/benchmark-sc01-sc02.txt`) | All 4 scanners `ok` on every repo; finding counts and recall unchanged (75/83). Scores unchanged except vuln_js 69.7 D → 70.2 C (eval + XSS on one line now scored once), full-stack-fastapi-template 68.2 → 68.3, probe_sqli_concat 82.1 B → 79.9 C (critical cap). Pre-fix report kept as `benchmarks/BENCHMARK_REPORT.before-sc01-sc02.md` |

Before and after, from `scoring_sc01_sc02_output.txt`:

| Case | Before | After |
|---|---|---|
| Same issue, 1 rule vs 4 rules on one line (security) | 81.9 vs 44.9 | 81.9 vs 81.9 |
| 4 rules on 4 different lines (control) | 44.9 | 44.9 |
| Lone high-confidence critical secret (overall) | 89.8 B | 79.9 C (uncapped 89.8) |
| Nothing analysable, no findings | 100.0 A | N/A |
| Go-only repo, one high secret | 94.6 A | 81.9 B (4 categories N/A) |
| No findings, Semgrep failed | 100.0 A | 89.9 B, incomplete |
| Fixture, all scanners (offline) | 60.4 D | 61.4 D (one bare-except + swallowed-exception pair scored once) |
| Fixture, Semgrep failing | 74.8 C | 75.8 C, security marked incomplete |

## Re-test after SEC-03 and SEC-07 fixes (release review)

Run on 2026-11-10 (macOS arm64). Docker was not running.

| Check | Command | Result |
|---|---|---|
| Backend suite | `cd backend && .venv/bin/pytest -p no:warnings -rs` (outside the Claude command sandbox) | **106 passed, 1 skipped** (Docker sandbox test), log `docs/audit-evidence/logs/pytest-release-review.txt`. Includes 4 new tests in `tests/test_release_hardening.py` |
| Mutation check | storage-time redaction removed from `jobs.py`, then `pytest tests/test_release_hardening.py` | the SEC-03 test **fails**; file restored and verified byte-identical |
| Backend lint | `.venv/bin/ruff check app tests migrations` | All checks passed |
| Security PoCs | `AUDITOR_OFFLINE=true .venv/bin/python ../docs/audit-evidence/security_pocs.py` | `security_pocs_output_after_sec03_sec07.txt`: P3a/P3b now **HOLD** (were VULNERABLE). P1 (SEC-02 lockout) still **VULNERABLE**. P2 prints HOLDS only because the limiter tripped by P1 answered 429; registration still returns 409 for a taken email (SEC-10 open) |
| SEC-08 (same day) | `pytest tests/test_jobs.py`; `docker compose config --services` | Orphan sweep test passes and **fails** with the deletion removed (file restored). Compose config is valid and lists the new `cleanup` service. The service was **not run live** (Docker daemon down) Full backend suite afterwards: **108 passed, 1 skipped**; ruff clean; frontend `tsc` / lint / **97 tests** pass after the tagline change (production build not re-run) |
| Not run | Compose rebuild and live flows, the `cleanup` service live, frontend production build, benchmark | Docker not running; the only frontend change is the tagline text (type-check, lint and tests pass); detection is unaffected (redaction happens after analysis and fingerprinting) |

## Re-test for the v0.1.0 public beta (SEC-02/04/05/06/07, DET-01, SC-03)

Run on 2026-11-10 (macOS arm64, Docker Desktop 29.7.2). The Compose stack was rebuilt from this tree
(`docker compose -p auditor-rc up --build -d`, project name chosen to avoid an older stack), using a
throwaway development `.env`.

| Check | Command | Result |
|---|---|---|
| Backend suite | `cd backend && .venv/bin/pytest -p no:warnings -rs` (outside the Claude command sandbox) | **126 passed, 0 skipped**, including the real Docker sandbox test. Log `docs/audit-evidence/logs/pytest-public-release.txt`. New: `tests/test_abuse_limits.py` (14), more in `test_release_hardening.py`, `test_scoring.py`, `test_jobs.py` |
| Backend lint | `.venv/bin/ruff check app tests migrations` | All checks passed |
| Frontend | `npx tsc --noEmit`, `npm run lint`, `npm test` | exit 0 / exit 0 / **97 passed** |
| Frontend production build | built inside the `web` image by Compose | succeeded |
| Compose services | `docker compose -p auditor-rc ps` | db (healthy), redis, api, worker, **cleanup**, web running; cleanup log shows the migration under the lock and `purged 0 workspace(s)` |
| Live end-to-end flows | `.venv/bin/python -u ../docs/audit-evidence/live_flows.py http://localhost:3000` | **31/31 passed** (`logs/live-flows-public-release.txt`): 4 sequential audits in one worker, all 4 scanners ok, 36 findings, secret masking, traversal blocked, fix approval, rerun comparison, isolation, delete |
| Live abuse checks | `.venv/bin/python ../docs/audit-evidence/live_abuse_checks.py http://localhost:3000` | **7/7 passed** (`logs/live-abuse-checks.txt`): device cookie set through the proxy; attacker throttled after 10 failures; spoofed `X-Forwarded-For` does not help; the victim's known browser still logs in during the attack; a 60 MB upload is refused with 413 immediately and creates nothing |
| Production guard in a container | `docker compose -p auditor-rc run --rm --no-deps -e AUDITOR_ENV=production api python -c "from app.main import app"` | refuses to start: `Unsafe production configuration: AUDITOR_COOKIE_SECURE must be true …; AUDITOR_SECRET_KEY must be set …` |
| Security PoCs | `AUDITOR_OFFLINE=true .venv/bin/python ../docs/audit-evidence/security_pocs.py` | `security_pocs_output_public_release.txt`. **P1 still reproduces** (victim on a *new* browser gets 429 during an attack, the documented SEC-02 residual); **P1b holds** (victim's known browser: 200); **P2 reproduces** (registration 409, SEC-10, low); P3a–P6c hold |
| Detection benchmark | `bash benchmarks/run_all.sh` (log `logs/benchmark-public-release.txt`) | recall **75/83 → 78/83 (94%)**; the 3 new findings are the planted 3-operand SQLi items; FP unchanged (1); clean repo 0 findings; security recall 60/64, strict precision 86% |
| Not run | live clone of a repo over 300 MB; live quota exhaustion; load test; real GitHub PR; real LLM | covered by unit tests only (clone watchdog with a real growing process, quotas), or out of scope |

## v0.2.0 release candidate (2026-11-12)

The full record, milestone by milestone, is in [docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md). Summary:

| Check | Where | Result |
|---|---|---|
| Backend suite | CI `backend` job, run 43186974018 on `e290f82` (Ubuntu, Semgrep 1.182.0, Gitleaks v8.30.1) | **152 passed, 0 skipped**, including the real Docker sandbox test |
| Backend suite | local, `pytest -m "not docker"` | 151 passed, 1 deselected (local Docker engine wedged, see below) |
| Frontend | CI `frontend` job and locally | lint, `tsc`, **102 passed**, production build |
| Deployment config | CI `deployment-config` | both Compose files and the Caddyfile valid |
| Production overlay, live | CI `e2e-production` (runs 43186085694 and 43186974018) | 7 services healthy; HTTP→HTTPS 308; HSTS; port 3000 closed; **31/31** live flows and **9/9** abuse checks over HTTPS (incl. a new browser on a second IP signing in during an attack); production guard refuses insecure cookies; API restarts and is healthy after SIGTERM |
| Restart and health (default Compose) | local Docker, M1 | all services healthy; api, worker and web each restarted (RestartCount 0 → 1) and healthy again ~7 s after their main process exited |
| Detection benchmark | local `run_all.sh` | synthetic recall 78/83 unchanged; itsdangerous dependency criticals 3 → 0 (all dev tooling); FastAPI template 4 of 14 advisories reclassified |

**Local Docker blocker (not a product defect).** On this machine a `caddy validate` container that
bind-mounted a file from `~/Desktop` left Docker Desktop unable to start containers. The likely cause
is a pending macOS permission. Stuck containers are still in `Created`, including `beautiful_boyd`
and two `auditor-sbx-*`. The overlay now builds the Caddyfile into an image instead of mounting it,
and the live verification ran in CI instead. Restarting Docker Desktop and removing those containers
is left to the machine owner.
