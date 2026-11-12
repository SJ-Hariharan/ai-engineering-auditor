# Engineering progress log

Working log for the path from the v0.1.0 public beta (`f9a9210`) to a deployable release candidate.
Each milestone lists what changed, what was run and the actual result. Nothing is marked done until it
works end to end. Older history: [TEST_RESULTS.md](../TEST_RESULTS.md),
[PRIORITIZED_FIXES.md](../PRIORITIZED_FIXES.md).

## Release-candidate acceptance criteria

| # | Criterion | Status |
|---|---|---|
| AC1 | Every service restarts on failure and reports health; the stack recovers from a killed container | **met** (M1) |
| AC2 | A documented production deployment serves HTTPS, exposes no plain-HTTP app port, and passes the live checks | open |
| AC3 | Login lockout is not possible from another client, including for a brand-new browser (SEC-02 residual) | open |
| AC4 | Re-run comparison counts new copies of identical defects and does not churn on moved secrets (E-01, E-05) | open |
| AC5 | CI runs backend lint and tests and frontend lint, type-check, tests and build on every push | open |
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
