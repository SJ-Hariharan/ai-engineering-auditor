# Engineering progress log

Working log for the path from the v0.1.0 public beta (`f9a9210`) to a deployable release candidate.
Each milestone lists what changed, what was run and the actual result. Nothing is marked done until it
works end to end. Older history: [TEST_RESULTS.md](../TEST_RESULTS.md),
[PRIORITIZED_FIXES.md](../PRIORITIZED_FIXES.md).

## Release-candidate acceptance criteria

| # | Criterion | Status |
|---|---|---|
| AC1 | Every service restarts on failure and reports health; the stack recovers from a killed container | **met** (M1) |
| AC2 | A documented production deployment serves HTTPS, exposes no plain-HTTP app port, and passes the live checks | **met** (M2, verified in CI) |
| AC3 | Login lockout is not possible from another client, including for a brand-new browser (SEC-02 residual) | **met** with the production ingress (M2, verified in CI) |
| AC4 | Re-run comparison counts new copies of identical defects and does not churn on moved secrets (E-01, E-05) | **met** (M3) |
| AC5 | CI runs backend lint and tests and frontend lint, type-check, tests and build on every push | **met** (M4) |
| AC6 | All suites green; live Compose checks green; docs match the code | open |

## Milestones

_(newest last)_

### M1 — Restart policies and health checks (AC1) — done, 2026-11-12

- **Problem:** in `docker-compose.yml` only `cleanup` had a restart policy and only `db` a health check.
  A crashed API, worker or web process, or a host reboot, left the app down with nothing reporting it.
  `web` started as soon as `api` started, not when it was ready.
- **Change:** `restart: unless-stopped` on every service. Health checks:
  - Redis: `redis-cli ping`.
  - API: `GET /api/health`.
  - Worker: this container's RQ worker is registered in Redis.
  - Web: `GET /login` answers below 500.
  - `api` and `worker` wait for healthy `db` and `redis`; `web` waits for a healthy `api`.
- **Changed files:** `docker-compose.yml`, `backend/tests/test_deployment_config.py` (new).
- **Tests:**
  - `pytest tests/test_deployment_config.py`: 3 passed.
  - `docker compose config -q`: valid.
  - Live: `docker compose -p auditor-rc up --build -d --wait` brought all six services up, and every
    service with a health check reported healthy (2 min 25 s, including the image build).
  - Recovery: SIGTERM sent to PID 1 of `api`, `worker` and `web` (a hard `SIGKILL` to PID 1 is ignored
    inside a container, and the images have no `kill` binary). All three restarted (`RestartCount` 0 → 1)
    and were healthy again after about 7 s.
- **Known issues:** Redis runs without persistence, so jobs queued at the moment Redis restarts are
  lost. Their audits are marked failed by the stale-audit sweep at the next worker start or rerun
  attempt (REL-02), and the user re-runs them.

### M2 — Production HTTPS ingress and trusted client IP (AC2, AC3) — done; verified live in CI

- **Problem:**
  - The only documented production advice was "put it behind an HTTPS reverse proxy". None shipped.
  - The web UI was published as plain HTTP.
  - SEC-02 residual: the API cannot trust any client IP (the Next.js proxy forwards a client-supplied
    `X-Forwarded-For`). So browsers without a device cookie share one failure budget per email, and an
    attacker can delay a user's first sign-in on a new browser.
- **Change:**
  - `docker-compose.prod.yml` overlay:
    - adds Caddy (`deploy/Caddyfile`, built into the image by `deploy/Dockerfile.caddy`), with
      automatic TLS, HSTS, a 52 MiB body limit, health check, restart policy and only
      `NET_BIND_SERVICE`;
    - removes the web port (`!reset`);
    - sets `AUDITOR_TRUST_CLIENT_IP_HEADER=true` and an HTTPS CORS origin.
  - Caddy overwrites `X-Auditor-Client-IP` with the peer address.
  - `api/auth.py`: when that setting is on and the header holds a valid IP, a browser without a device
    cookie gets its own budget per IP + email (10). Limits: 100 per email across IPs (distributed
    guessing), 50 per IP across emails (spraying). Off by default: behaviour is unchanged without the
    ingress.
  - `.env.production.example` gains `AUDITOR_DOMAIN`.
- **Changed files:**
  - `backend/app/api/auth.py`
  - `backend/app/core/config.py`
  - `docker-compose.prod.yml` (new), `deploy/Caddyfile` (new), `deploy/Dockerfile.caddy` (new)
  - `.env.production.example`, `README.md`, `SECURITY.md`
  - `backend/tests/test_abuse_limits.py` (+5 tests), `backend/tests/test_deployment_config.py` (+2 tests)
- **Tests:**
  - `pytest -m "not docker"`: **135 passed**, 1 deselected (log `docs/audit-evidence/logs/pytest-m2.txt`).
  - The new tests cover:
    - a brand-new browser on another IP signs in during an attack;
    - the header is ignored unless trusted;
    - an invalid header falls back to the shared budget;
    - the per-email distributed cap and the per-IP spraying cap;
    - the overlay publishes only Caddy;
    - IP trust appears only together with the overwriting Caddyfile.
  - `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`: valid. Only Caddy publishes
    ports (80, 443, 443/udp); the API trusts the header and has the HTTPS CORS origin.
- **Not verified (blocks AC2):** the overlay has not served traffic yet.
  - The first attempt bind-mounted the Caddyfile from `~/Desktop`. Docker Desktop then stopped
    starting containers: a `caddy validate` container and then the API, worker, web and Caddy containers
    stayed in `Created` for hours. db and Redis did start.
  - The likely cause is a pending macOS permission for Docker to access the Desktop folder. That is why
    the Caddyfile is now built into an image rather than mounted.
  - The Docker engine needs to be restarted (or the prompt answered) by the owner before the live check
    can run. The real Docker sandbox test is excluded from this run for the same reason.
- **Security concerns:**
  - `AUDITOR_TRUST_CLIENT_IP_HEADER=true` without the overwriting ingress would let clients pick their
    own IP and bypass per-IP limits. The per-email cap of 100 still bounds guessing.
  - If another load balancer sits in front of Caddy, `{remote_host}` is that balancer. The Caddyfile
    comment says how to switch to `{client_ip}` with `trusted_proxies`.

### M3 — Re-run comparison integrity (AC4) — done, 2026-11-12

- **Problem:**
  - E-01: the fingerprint ignores line numbers, so identical defects in one file got the same
    fingerprint, and `_dedupe` kept only the first. Copies were missing from the report, and a newly
    added copy showed "0 new".
  - E-05: the Gitleaks fingerprint included the line number, so a secret that moved showed as
    "resolved" plus "new".
- **Change:**
  - `_dedupe` collapses only true repeats (same rule at the same location, most severe kept), as before.
  - Remaining findings that share a fingerprint are distinct occurrences. In line order, the first
    keeps the base fingerprint (compatible with existing audits); later ones get `sha256(base#i)`.
  - The Gitleaks key is now `path|rule`.
  - No schema change: fingerprints were never unique per audit.
- **Changed files:**
  - `backend/app/analysis/pipeline.py`, `backend/app/analysis/scanners/gitleaks.py`
  - `backend/tests/test_fingerprints.py` (new, 7 tests)
  - `PRIORITIZED_FIXES.md`, `README.md`
- **Tests:**
  - `pytest tests/test_fingerprints.py`: 7 passed.
  - Mutation check: with the occurrence suffix removed, 4 of the 7 fail. File restored and verified
    identical.
  - `pytest -m "not docker"`: **142 passed**, 1 deselected (log `logs/pytest-m3.txt`).
  - Evidence `scoring_fingerprint_output_after_e01_e05.txt`:
    - F1: two identical bare-excepts are 2 findings (was 1).
    - F2: adding a third gives 2 new fingerprints, one each for `bare-except` and
      `swallowed-exception`, which both fire on the new block (was 0).
- **Known issues:**
  - Occurrence numbers follow line order. Inserting a new copy *above* existing ones re-labels the
    identities: the count of new findings is still right (1), but the "new" one may be reported at the
    location of an older copy.
  - Gitleaks findings change fingerprint once on the first re-run after this upgrade, showing as
    resolved + new for that one comparison.

### M4 — Continuous integration (AC5) — done, 2026-11-12

- **Problem:** there was no CI (HYG-01), so every result in this repository came from one developer machine.
- **Change:** `.github/workflows/ci.yml`, running on every push and pull request:
  - **backend:** `uv sync --frozen`, Semgrep 1.182.0, and Gitleaks v8.30.1 copied out of the same image the
    Dockerfile uses; then `ruff` and the full pytest suite, including the real Docker sandbox test.
  - **frontend:** `npm ci`, lint, `tsc`, Vitest, production build.
  - **deployment-config:** `docker compose config` for both the default and production files, and
    `caddy validate` on the built Caddy image.
- **Changed files:** `.github/workflows/ci.yml` (new).
- **Tests:** branch `rc/0.2.0`, commit `64e5f50`, run 43185639407, **all three jobs succeeded**:
  - backend: lint clean, **143 passed, 0 skipped** (the Docker sandbox test ran on the runner);
  - frontend: lint clean, `tsc` clean, 97 passed, production build compiled;
  - deployment-config: both Compose files and the Caddyfile valid.
- **Known issues:** actions are pinned to major versions (`@v4`, `@v5`), not commit SHAs.

### M5 — Small polling payload (E-03) — done in tests; live UI check pending

- **Problem:** the report page re-fetched `GET /api/audits/{id}`, including the whole summary (~2.6 MB
  measured on a 529-file repo), every 2 s for as long as a sandboxed test run was in progress. While an
  audit is still running the summary is empty, so that phase was already small.
- **Change:**
  - New `GET /api/audits/{id}/status` returns `{id, status, stage, error, finished_at, test_run}`.
  - The report page (`refreshAudit` in `frontend/src/lib/audit-poll.ts`) polls it and fetches the full
    audit only on the first load, when the status or test run changes, or when an action explicitly
    reloads.
- **Changed files:**
  - backend: `app/api/audits.py`, `app/schemas.py`, `tests/test_api.py` (+1 test)
  - frontend: `src/lib/audit-poll.ts` (new), `src/lib/audit-poll.test.ts` (new, 5 tests),
    `src/lib/api.ts`, `src/lib/types.ts`, `src/components/report/audit-report.tsx`
  - docs: `docs/API.md`, `PRIORITIZED_FIXES.md`
- **Tests:**
  - backend `test_status_endpoint_is_small_and_owner_scoped`: passed. The status response is under
    1,000 bytes while the full audit is larger, and another user gets 404.
  - frontend: `tsc` exit 0, lint exit 0, **102 passed** (11 files).
- **Not verified:** the polling behaviour in a running browser against the stack (Docker engine
  blocked, see M2).
- **Known issue:** the full summary is still sent once per report view and stored as one JSON column;
  splitting symbols and the graph out of it is a larger change, not done.

### M7 — Secrets in the file viewer and in older audits (SEC-03 residual) — done, 2026-11-12

- **Problem:**
  - The file viewer showed raw source except for lines Gitleaks flagged, so, for example, a hard-coded
    Flask `secret_key` was visible there although its finding evidence was redacted.
  - Audits stored before storage-time redaction still returned raw evidence.
- **Change:**
  - `finding_out` redacts evidence on read. This is idempotent on already-redacted text.
  - The file viewer applies `redact()` line by line after Gitleaks masking, so the line count and the
    finding markers stay aligned.
- **Changed files:** `backend/app/api/audits.py`, `backend/tests/test_release_hardening.py` (+2 tests),
  `SECURITY.md`, `README.md`, `PRIORITIZED_FIXES.md`.
- **Tests:**
  - viewer test: the secret is absent, `app.secret_key = "[REDACTED]"` is shown, and the line count
    equals the original's;
  - old-row test: the storage redaction is disabled to simulate an earlier row, and the findings API
    still returns no secret;
  - `pytest -m "not docker"`: **151 passed** (log `logs/pytest-m6-m7.txt`, which also covers M6).
- **Security concern:** redaction is pattern-based; formats it does not know are still shown.

### M2 (continued) — Live verification of the production overlay in CI — done, 2026-11-12

- **Why CI:** the local Docker engine is still wedged (see M2 above). GitHub's runners have Docker, so
  CI job `e2e-production` deploys the overlay there exactly as the README describes:
  - it uses `.env.production.example` with `AUDITOR_DOMAIN=localhost` and secrets generated per run;
  - it runs `up --build --wait`, then the checks below, then tears the stack down.
- **Result:** branch `rc/0.2.0`, commit `3d47287`, run 43186085694 — **all 4 jobs succeeded**.
  - All 7 services healthy (db, redis, api, worker, cleanup, web, caddy).
  - Ingress:
    - `http://localhost/login` answers `308 https://localhost/login`;
    - HSTS `max-age=31536000; includeSubDomains` is set;
    - port 3000 is not reachable;
    - `/login` and `/api/health` answer 200 over HTTPS.
  - `live_flows.py` over HTTPS: **31/31** (4 audits in one worker, all 4 scanners ok, isolation,
    masking, fixes, rerun comparison).
  - `live_abuse_checks.py`: **9/9**:
    - attacker throttled after 10 failures;
    - spoofed `X-Forwarded-For` and spoofed `X-Auditor-Client-IP` are both ineffective, the latter
      overwritten by Caddy;
    - the victim's known browser logs in during the attack;
    - **a victim on a new browser from another IP (a request from inside the Caddy container) logs in
      during the attack: 200**;
    - a 60 MB upload gets 413 and creates nothing.
  - The production guard refuses `AUDITOR_COOKIE_SECURE=false` (`Unsafe production configuration`).
  - Crash recovery: after SIGTERM to the API's PID 1, `RestartCount` is 1 and the API is healthy again.
- **Changed files:** `.github/workflows/ci.yml` (job `e2e-production`); `docs/audit-evidence/live_flows.py`
  and `live_abuse_checks.py` (`LIVE_TLS_VERIFY=0` for Caddy's local CA; ingress checks with `LIVE_COMPOSE`).

### M6 — Dependency severity from lockfiles (DET-11) — done, 2026-11-12

- **Problem:** advisories for development tooling found only in a lockfile were rated at full severity
  (itsdangerous, a zero-dependency library, had 3 criticals for `uv`/`virtualenv`-type tooling). Only
  manifests were read, and every undeclared package was treated as an unknown transitive.
- **Change:**
  - `inventory.py` computes reachability from `uv.lock` (the project's runtime dependencies and extras
    vs dev groups and dev-like extras, followed transitively), `package-lock.json` (npm's `dev: true`)
    and `bun.lock` (workspace dependencies vs `devDependencies`, with nested copies resolved).
  - Packages reachable only through dev roots form `dev_only_transitive`. Runtime reachability is
    over-approximated (all extras count), so a package with any runtime path is never lowered.
  - `classify_dependency_findings` lowers those advisories one level, sets medium confidence, and says why.
- **Changed files:**
  - `backend/app/analysis/inventory.py`, `backend/app/analysis/scanners/deps.py`,
    `backend/app/analysis/pipeline.py`
  - `backend/tests/test_dependency_lockfiles.py` (new, 6 tests)
  - `benchmarks/make_report.py`, `DETECTION_BENCHMARK.md`, `README.md`, `PRIORITIZED_FIXES.md`
- **Tests:**
  - 6 new tests: the uv/npm/bun closures; runtime paths win (e.g. `certifi` via `requests`; `seroval`
    via `react-router`); a malformed lockfile is ignored; the classification text.
  - `pytest -m "not docker"`: 151 passed.
  - Benchmark `run_all.sh` (log `logs/benchmark-det11.txt`; before/after in `logs/det11-before.txt`,
    `logs/det11-after.txt`):
    - Synthetic detection unchanged: 78/83, FP 1, clean repo 0.
    - itsdangerous dependency severities went from {critical 3, high 3, medium 3, low 2} to
      {high 3, medium 3, low 4, info 1}: all 11 are dev tooling, score 81.4 → 87.2.
    - FastAPI template: 4 of 14 advisories became dev tooling. The critical `seroval` stays, because it
      is reached at runtime via `@tanstack/react-router`; `glob`/`minimatch` stay, reached via the
      runtime `react-email` workspace.
- **Known issues:** `pnpm-lock.yaml`, `yarn.lock` and `poetry.lock` are not read yet; their packages
  keep the previous "transitive, medium confidence" treatment.
