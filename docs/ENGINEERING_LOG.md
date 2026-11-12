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

### M2 — Production HTTPS ingress and trusted client IP (AC2, AC3) — code done; live check blocked

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
