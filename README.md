# AI Engineering Auditor

**Understand what you built. Know what to fix. Ship with confidence.**

AI Engineering Auditor reviews a Python, JavaScript or TypeScript codebase and explains what it
contains, what is wrong with it, and what to fix first, with evidence for every finding.

> **Status: v0.1.0 public beta.** A self-hosted tool for one instance. The release-blocking
> security issues found in review are fixed or mitigated and were re-tested on the Docker
> Compose stack. Known limitations are listed below. The score is a prioritisation aid, not a
> security certification. See [Release status](#release-status) and
> [RELEASE_READINESS.md](RELEASE_READINESS.md).

## The problem

Code written quickly, often with AI coding assistants, can work while nobody on the team can say
how it fits together: which routes exist, where data is read and written, which modules depend on
which, whether a secret was committed, or which dependency has a known vulnerability. Answering
that by hand takes a careful read of the whole repository. This tool does the mechanical part of
that review and shows its working, so a person can decide what matters.

## What it does

Point it at a public GitHub repository or upload a ZIP. It produces a report with:

- **Structure:** stack, entry points, HTTP routes, symbols, import graph with cycles and coupling
  metrics, and data-flow paths from routes to data access.
- **Security findings** from Semgrep (30 bundled rules for Python and JS/TS), Gitleaks (committed
  secrets), OSV-Scanner (vulnerable dependencies) and Trivy (configuration, e.g. Dockerfiles).
- **Design and quality findings:** complexity, size, nesting, duplication, error handling, naming,
  N+1 queries, `SELECT *`, missing foreign-key indexes, endpoints without visible auth. Each is
  labelled *objective* (a measurable fact) or *subjective* (a judgement against a threshold).
- **Testing:** test inventory, modules no test references, and an opt-in sandboxed test run
  (Docker, no network) with Python coverage.
- **Priorities:** findings ranked by severity, confidence and category, plus a category score with
  a documented formula (see [The score](#the-score)).
- **Re-run comparison:** new, resolved and persisting findings against the previous audit.
- **Fixes:** deterministic fixers for 8 rules and optional AI-proposed patches. Each is shown as a
  diff, approved one by one, and can be opened as a pull request on a new branch. The original
  repository is never changed automatically.
- **Optional AI explanations** (Claude or OpenAI) of files, functions and the architecture, and
  questions to check your understanding. Off by default; enabled per project, with secrets
  redacted from what is sent.

## How it works

```
GitHub URL / ZIP ─► safe ingestion ─► deterministic analysis ───────────► report + score
                                       tree-sitter · import graph            │
                                       Semgrep · Gitleaks · OSV · Trivy      ├─► fix proposals ─► approved PR
                                       (reads files, never runs them)        └─► AI explanations (opt-in)
                       opt-in: run tests in a network-less Docker sandbox
```

- **Ingestion** clones with hardened git options or extracts the ZIP with checks for traversal,
  symlinks, zip bombs, total size and file count.
- **Analysis** parses files with tree-sitter and runs the four scanners with app-controlled
  configuration, so a repository cannot suppress its own findings with `.semgrepignore`,
  `nosemgrep` or a Gitleaks allowlist. Suppressions found in the repository are listed in the report.
- **Every finding comes from a scanner or a measured metric.** The AI layer only explains and
  proposes patches; it never creates findings or changes scores.
- **Stack:** FastAPI, SQLAlchemy and Alembic, PostgreSQL, Redis + RQ worker (backend); Next.js and
  TypeScript (frontend); Docker Compose for deployment.

More detail: [ARCHITECTURE.md](ARCHITECTURE.md) and [SECURITY.md](SECURITY.md).

## Evidence

Measured results, with the commands and raw output in the linked documents:

- **Detection benchmark** ([DETECTION_BENCHMARK.md](DETECTION_BENCHMARK.md)), on 5 synthetic repositories
  with planted issues:
  - 78 of 83 planted issues found (94%).
  - Security items: 94% recall, 86% strict precision.
  - Zero findings on the clean repository.
  - No security rule fired on 26 safe look-alikes, such as parameterised SQL and `safe_load`.
- **Real repositories:**
  - `pallets/itsdangerous`: 32 findings. All dependency advisories are correctly identified as
    development tooling.
  - `fastapi/full-stack-fastapi-template`: 89 findings, down from 295 after a monorepo
    import-resolution fix.
- **Tests** ([TEST_RESULTS.md](TEST_RESULTS.md)):
  - Backend: 126 tests pass, including a real Docker sandbox run.
  - Frontend: 97 tests pass.
  - Live checks against the Docker Compose stack, through the web proxy: 31/31 end-to-end flows
    and 7/7 abuse-protection checks pass.
  - Security proof-of-concept scripts are saved in `docs/audit-evidence/`.

## Quick start (Docker Compose)

```bash
cp .env.example .env        # set POSTGRES_PASSWORD; optionally an AI API key
docker compose up --build
```

Open http://localhost:3000, create an account, and import a repository. The stack runs the
API, a worker, an hourly cleanup job, PostgreSQL, Redis and the web UI; the web UI is bound to
`127.0.0.1`. ### Production deployment

```bash
cp .env.production.example .env   # fill in every CHANGE-ME, including AUDITOR_DOMAIN
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
```

- The overlay adds Caddy (`deploy/Caddyfile`), which obtains and renews a TLS certificate for
  `AUDITOR_DOMAIN`. Point the domain's DNS at the host and open ports 80 and 443.
- The web UI is no longer published on port 3000, so HTTPS through Caddy is the only way in.
- In production mode the services refuse to start with insecure settings.

Running repository tests in the sandbox is **disabled** in Compose by default, because it needs
Docker access from the worker. See *Running tests* in [SECURITY.md](SECURITY.md) before enabling it.

## Local development

Requirements: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 22, and the scanners on
your `PATH` (`brew install semgrep gitleaks osv-scanner trivy`). Docker is only needed for
sandboxed test runs.

```bash
# Backend (SQLite, audits run in-process — no Postgres/Redis needed)
cd backend
uv sync
AUDITOR_DATABASE_URL=sqlite:///./auditor.db AUDITOR_INLINE_JOBS=true \
  uv run uvicorn app.main:app --reload --port 8000
```

```bash
# Frontend (proxies /api to http://localhost:8000)
cd frontend
npm install
npm run dev
```

For PostgreSQL + Redis + a separate worker, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Configuration

All settings are environment variables with the `AUDITOR_` prefix; see
[.env.example](.env.example). The most important ones:

| Variable | Default | Purpose |
|---|---|---|
| `AUDITOR_ENV` | `development` | `production` hides `/api/docs` and refuses to start with insecure cookies or in-process jobs |
| `AUDITOR_COOKIE_SECURE` | `false` | Must be `true` in production (HTTPS) |
| `AUDITOR_SECRET_KEY` | – | Signs login device cookies; required in production (32+ random characters) |
| `AUDITOR_MAX_ACTIVE_AUDITS_PER_USER` | `2` | Audits a user can have queued or running at once |
| `AUDITOR_MAX_AUDITS_PER_USER_PER_DAY` | `50` | Audits a user can start per 24 hours |
| `AUDITOR_ALLOW_REGISTRATION` | `true` | Set `false` once your accounts exist |
| `AUDITOR_WORKSPACE_TTL_HOURS` | `24` | How long source copies are kept; Compose purges expired copies hourly |
| `AUDITOR_OFFLINE` | `false` | Disable vulnerability-database lookups (results are then marked incomplete) |
| `AUDITOR_SANDBOX_ENABLED` | `false` | Allow opt-in Docker test runs (needs Docker access; read SECURITY.md first) |
| `AUDITOR_LLM_PROVIDER` | `anthropic` | `anthropic`, `openai` or `none` |
| `AUDITOR_ANTHROPIC_API_KEY` | – | Enables Claude (`claude-opus-5-5` by default) |
| `AUDITOR_OPENAI_API_KEY` | – | Enables OpenAI |

## The score

Each category (Security 30%, Testing & Reliability 20%, Architecture 20%, Code Quality 15%,
Maintainability 15%) starts at 100 and loses points per finding by severity × confidence, with
diminishing returns for repeated findings of one rule.

- Findings in the same category on the same file and line (one issue flagged by several rules or
  tools) are scored once, using the most severe. All of them are still listed.
- A category with nothing to analyse (no supported source files, or no security scanner that ran) is
  shown as *Not analysed*. It gets no score, and its weight is shared among the other categories.
- The overall score is capped at 79.9 (C at best) when there is a high-confidence critical finding,
  and at 89.9 (no A) when a security scanner was skipped or failed. A capped result says why.

The formula, weights, caps and limitations are shown in the app's *Methodology* tab and in
`backend/app/analysis/scoring.py`.

**The score is a prioritisation aid, not a security certification.** Static analysis cannot
prove the absence of vulnerabilities, and skipped scanners contribute no findings.

## Release status

**v0.1.0 public beta.** The full assessment is in [RELEASE_READINESS.md](RELEASE_READINESS.md),
and every issue with its evidence is in [PRIORITIZED_FIXES.md](PRIORITIZED_FIXES.md).

Fixed and re-tested (unit tests, saved proof-of-concept scripts, and live on Docker Compose):

- **Reliability:**
  - Worker database connections are fork-safe. Previously, every audit after the first failed
    in Compose.
  - Failed or killed jobs no longer leave a project locked.
- **Result integrity:**
  - Repository-controlled scanner suppression is ignored.
  - Monorepo import false positives are fixed (208 to 0 on the FastAPI template).
  - OSV-Scanner no longer honours `.gitignore`.
  - Three-operand SQL string concatenation is now detected (recall 90% to 94%).
- **Privacy:**
  - Secrets are redacted in all stored finding evidence and in the Markdown export.
  - Source copies are purged hourly, including orphans left by crashed jobs.
- **Abuse resistance:**
  - Request bodies over the upload limit are refused before they are parsed.
  - A clone is stopped as soon as it passes the size limit.
  - Each user is limited to 2 concurrent and 50 daily audits.
  - Login throttling counts only failures and protects browsers the user has already signed in
    with.
- **Deployment:** production mode refuses insecure cookies, in-process jobs or a missing secret.
  A production `.env` template ships with registration closed, and the sandbox is off by default.
- **Scoring:**
  - categories that were not analysed are N/A;
  - critical findings and incomplete results are capped;
  - one issue is counted once;
  - the result no longer depends on input order.

Known issues (none of these is a blocker for a self-hosted beta; all are documented):

- **Login from a new browser** can be delayed while someone is actively guessing that account's
  password. Browsers the user has already signed in with are not affected (SEC-02, mitigated).
  Registration also reveals whether an email is taken (SEC-10).
- **Trivy suppressions:** Trivy honours inline `trivy:ignore` comments; they are listed in the report.
- **Scoring:** not normalised for repository size, and the constants are not calibrated (SC-04 to
  SC-07). Use the score to track one repository over time, not to compare repositories.
- **Not reviewed:**
  - Not load-tested.
  - No external penetration test.
  - PR creation and AI output were tested with mocks, not live services.

## Limitations

- Static analysis cannot prove the absence of vulnerabilities. Business-logic and authorisation
  flaws are often invisible to pattern matching.
- Only Python, JavaScript and TypeScript are analysed; other files are counted but not analysed.
- Design checks are static heuristics. Auth or pagination enforced elsewhere (middleware,
  gateways) may not be visible, so those findings are marked subjective with low confidence.
- Secret redaction in evidence and the file viewer is pattern-based; unusual formats can still appear.
- PR creation and AI output are tested with mocks and fakes, not live services.
- Sandbox coverage numbers are Python-only.
- No MFA or password reset. Login throttling is in memory per API process (Compose runs one).

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, data model, key decisions |
| [SECURITY.md](SECURITY.md) | Threat model, controls, limitations |
| [docs/API.md](docs/API.md) | REST API reference (OpenAPI at `/api/docs` in development) |
| [docs/TESTING.md](docs/TESTING.md) | Test suite, how to run it, known gaps |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, standards, adding analyzers |
| [RELEASE_READINESS.md](RELEASE_READINESS.md) | Release assessment and open blockers |
| [DETECTION_BENCHMARK.md](DETECTION_BENCHMARK.md) | Detection accuracy against ground truth |
| [TEST_RESULTS.md](TEST_RESULTS.md) | What was run and the results |
