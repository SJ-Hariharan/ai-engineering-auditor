# Architecture

> Understand what you built. Know what to fix. Ship with confidence.

AI Engineering Auditor ingests a repository (GitHub URL or ZIP), runs a
**deterministic analysis pipeline** over it, and presents the results as an
engineering health report. An **optional, consent-gated AI layer** explains
the codebase and proposes fixes. Fixes are only ever applied to a new branch
through a pull request the user explicitly approves.

## High-level components

```
 Browser ── Next.js frontend (TypeScript, Tailwind, shadcn/ui)
              │  REST/JSON, HTTP-only session cookie
              ▼
          FastAPI API (Pydantic)  ──── PostgreSQL (users, projects, audits, findings, fixes)
              │ enqueue job
              ▼
            Redis  ──►  RQ worker(s)
                          │
                          ├─ ingestion   (safe clone / safe unzip → private workspace)
                          ├─ analysis    (deterministic; no repo code executed)
                          │    ├─ inventory      file walk, languages, stack, entry points
                          │    ├─ parsing        tree-sitter (Python, JS, TS/TSX)
                          │    ├─ graph          import graph, cycles (Tarjan), coupling
                          │    ├─ quality        complexity, size, duplication, error handling, naming
                          │    ├─ testing        test inventory, untested modules, broken imports
                          │    └─ scanners       Semgrep · Gitleaks · OSV-Scanner · Trivy
                          ├─ scoring     transparent, documented heuristic
                          └─ sandbox     Docker (network=none) — only for opt-in test runs
          LLM layer (Claude / OpenAI) ── only with per-project consent, redacted input
```

## Directory layout

```
auditor/
  backend/app/
    core/         config, database, security primitives (passwords, sessions)
    api/          FastAPI routers (auth, projects, audits, remediation)
    models.py     SQLAlchemy ORM
    schemas.py    Pydantic request/response models (the API contract)
    ingestion/    safe ZIP extraction, GitHub clone, workspace lifecycle
    sandbox/      locked-down subprocess runner + Docker test runner
    analysis/     deterministic analyzers, scanners/, rules/ (Semgrep rules)
    llm/          provider interface, Anthropic + OpenAI, redaction, prompts
    remediation/  deterministic fixers, diff generation, GitHub PR creation
    worker.py     RQ job entry points
  frontend/       Next.js app
  docs/           API.md, TESTING.md
```

## Key design decisions

| Decision | Rationale |
|---|---|
| Deterministic analysis is separate from AI | Findings are reproducible and auditable. The LLM never creates findings; it only explains existing ones or proposes patches, and both are labelled as AI output. |
| Static scanners run as hardened subprocesses, not in Docker | Semgrep, Gitleaks, OSV-Scanner, Trivy and tree-sitter *read* files; they never execute repository code. They run with an empty environment (no API keys), a timeout, and against a private workspace copy. In the Docker Compose deployment the whole worker is itself containerised. |
| Repository code is executed only in Docker, opt-in | Running tests is the only step that executes untrusted code. It runs in a throwaway container: `--network none`, CPU/memory/PID limits, read-only root filesystem, non-root user, dropped capabilities, wall-clock timeout. If Docker is unavailable the step is reported as skipped rather than run on the host. |
| Scanner network access | OSV-Scanner and Trivy need vulnerability databases. They send package names/versions, never source code. This is documented in SECURITY.md and can be disabled (`AUDITOR_OFFLINE=true`). |
| Trivy runs config scanning by default | OSV-Scanner already covers dependency vulnerabilities. Trivy's vulnerability DB is ~1.6 GB per worker, so `AUDITOR_TRIVY_SCANNERS=vuln,misconfig` makes it opt-in; overlapping results are de-duplicated. |
| Local Semgrep rules by default | Curated rules in `analysis/rules/` give deterministic, offline results. Registry packs can be added with `AUDITOR_SEMGREP_EXTRA_CONFIGS`. |
| RQ for background jobs | Simple, Redis-backed, one process per job (fork), easy to reason about. Tests run the pipeline synchronously. |
| Opaque session tokens in HTTP-only cookies | Revocable server-side; only SHA-256 hashes are stored. No JWT key management needed for an MVP. |
| Workspaces expire | Repository contents are kept only for `AUDITOR_WORKSPACE_TTL_HOURS` (default 24h) so explanations and fixes can reference code. Expired copies are deleted when the next audit starts and by the hourly `cleanup` service in Compose (`python -m app.worker cleanup`), which also sweeps orphaned workspaces older than the TTL. Findings and metrics stay. |
| PR token is never stored | The GitHub token is used for one PR request and then discarded. |

## Data model

- **User** — email, Argon2id password hash.
- **AuthSession** — hashed opaque token, expiry.
- **Project** — owner, name, source (`github` URL or `zip`), `llm_consent` flag.
- **Audit** — project, status (`queued → running → completed | failed`),
  commit SHA, workspace path + expiry, `summary` JSON (stack, inventory,
  graph, metrics, scores, test results), `previous_audit_id` for comparisons.
- **Finding** — audit, stable `fingerprint`, tool, rule, category, severity,
  confidence, `kind` (`objective`/`subjective`), file, line, evidence,
  explanation, impact, remediation.
- **FixProposal** — finding, file, original/proposed content, unified diff,
  rationale, source (`deterministic`/`ai`), status (`pending/approved/rejected`).
- **PullRequestRecord** — audit, URL, branch.
- **AIArtifact** — cached AI output (overview, file explanation, questions).

## Authorization

Every resource query is scoped through `Project.owner_id == current_user.id`.
Lookups of an audit/finding/fix that belong to another user return **404**
(not 403) so existence is not leaked. This is enforced in one place
(`api/deps.py` loaders) and covered by tests.

## Scoring

See `app/analysis/scoring.py` and the in-app *Methodology* page. Each category
starts at 100 and loses points per finding by severity × confidence, with
diminishing returns, so one noisy rule cannot zero a category. Findings in the
same category at the same file and line count once (the most severe). The overall
score is a weighted mean (security 30%, reliability 20%, architecture 20%,
code quality 15%, maintainability 15%) over the categories that were analysed.
A category with no coverage is N/A and its weight is renormalised away. The
pipeline passes that coverage to the scorer: parsed source files for the built-in
categories, and scanner status for security. A high-confidence critical finding
caps the overall at 79.9, and a skipped or failed security scanner caps it at
89.9 and marks the result incomplete. It is a prioritisation aid, **not** a
security certification.

## Phases and status

See README.md → *Project status* for what is implemented and known gaps.
