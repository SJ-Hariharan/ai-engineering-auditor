# Contributing

This guide covers local setup, the rules every change must follow, and the
checklist for a pull request. For the system design, read
[ARCHITECTURE.md](ARCHITECTURE.md). For the HTTP API, read [docs/API.md](docs/API.md).
For tests, read [docs/TESTING.md](docs/TESTING.md).

## Project layout

| Path | Contents |
|---|---|
| `backend/app/` | FastAPI API, RQ worker, deterministic analysis, sandbox, AI layer, remediation |
| `backend/tests/` | pytest suite and the intentionally vulnerable fixture app |
| `backend/scripts/smoke.py` | End-to-end check against a running API and worker |
| `frontend/src/` | Next.js (App Router) UI |
| `docs/` | API reference and testing guide |

The backend module map is in [ARCHITECTURE.md](ARCHITECTURE.md#directory-layout).

## Dev setup

### Backend

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
```

Settings are read from environment variables with the `AUDITOR_` prefix (or from
`backend/.env`). The source of truth is `app/core/config.py`.

Choose one of two modes:

**A. SQLite, no services (fastest for development).** Jobs run in-process.

```bash
mkdir -p var
export AUDITOR_DATABASE_URL=sqlite:///./var/dev.db
export AUDITOR_INLINE_JOBS=true
export AUDITOR_LLM_PROVIDER=none
uv run uvicorn app.main:app --reload --port 8000
```

**B. PostgreSQL and Redis (closer to production).** The defaults are
`AUDITOR_DATABASE_URL=postgresql+psycopg://localhost/auditor` and
`AUDITOR_REDIS_URL=redis://localhost:6379/0`. Start the API as above without
`AUDITOR_INLINE_JOBS`, then start a worker in a second terminal:

```bash
uv run python -m app.worker            # processes the "audits" queue
uv run python -m app.worker cleanup    # one-off: delete expired workspaces
```

Without a worker, audits stay `queued` in mode B.

On macOS, RQ forks a process per job, which the Objective-C runtime aborts unless you
export `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` before starting the worker. Linux and
the Docker image do not need this.

### Database migrations

The schema is managed with [Alembic](https://alembic.sqlalchemy.org/) (`backend/migrations/`).
The API and worker run `alembic upgrade head` automatically at startup (serialised by a
PostgreSQL advisory lock), so you normally never apply migrations by hand. Databases created
before Alembic was added are stamped at `0001_initial` on first start.

After changing `app/models.py`:

```bash
cd backend
uv run alembic revision --autogenerate -m "add widget table"   # against a DB at head
# Review migrations/versions/<id>_add_widget_table.py: autogenerate misses renames,
# server defaults and data migrations. Edit by hand where needed.
uv run alembic upgrade head                                     # apply (optional locally)
```

`tests/test_migrations.py` fails if the migrations and the models drift apart, so commit the
migration together with the model change. Autogenerate needs a database at the current head;
point `AUDITOR_DATABASE_URL` at a scratch SQLite or PostgreSQL database.

### Frontend

```bash
cd frontend
cp .env.example .env.local    # optional; defaults to http://localhost:8000
npm install
npm run dev                   # http://localhost:3000
```

The browser only calls same-origin `/api/*`. `next.config.ts` forwards those
requests to `AUDITOR_API_URL`.

Before writing Next.js code, read the guides in `frontend/node_modules/next/dist/docs/`.
`frontend/AGENTS.md` says this Next.js version has breaking changes from what you
may remember.

## Coding standards

### Backend (Python)

- Python 3.12. Type hints on all new functions and public attributes.
- Lint with `uv run ruff check app tests` (line length 100). The fixture app in
  `tests/fixtures/` is excluded on purpose and must not be "fixed".
- Keep deterministic analysis separate from AI. Analyzers and scanners create
  findings. The LLM layer only explains existing findings or proposes patches, and
  its output is labelled as AI output.
- Every finding must carry `evidence`, `impact`, `remediation`, `confidence`, and
  `kind` (`objective` or `subjective`). `test_full_audit_flow` checks these fields
  on the fixture's findings, so a new rule that leaves them empty will be caught
  there only if the fixture triggers it. Fill them in regardless.
- Use Pydantic models in `app/schemas.py` for every request and response body.
- Keep [docs/API.md](docs/API.md) in sync with any endpoint change.

### Frontend (TypeScript)

- TypeScript `strict` is on. Do not use `any`. Prefer narrow types and `unknown`
  with a check.
- API types in `src/lib/types.ts` mirror `docs/API.md`. Change both together.
- Call the API only through `src/lib/api.ts`. It sends credentials and the CSRF
  header.
- No placeholder UI. Do not ship stub buttons, "coming soon" text, or fake data.
  If a feature is not finished, leave it out of the build.
- Run `npx tsc --noEmit`, `npm run lint`, and `npm run build` before submitting.

## Security rules

These rules protect users' source code and credentials. Reviewers reject changes
that break them.

| Rule | How it is enforced |
|---|---|
| Never execute repository code outside the Docker sandbox. | Only `app/sandbox/docker_tests.py` runs project tests. Scanners and parsers only read files. Do not call `subprocess` on repository content from anywhere else. |
| All resource access goes through owner-scoped loaders. | `get_project`, `get_audit`, `get_finding`, `get_fix` in `app/api/deps.py` join to `Project.owner_id`. Do not query `Project`, `Audit`, `Finding`, or `FixProposal` directly in a route. A resource owned by someone else returns `404`, never `403`. |
| Never log or return secrets. | Redact before any LLM call (`app/llm/redact.py`). Do not put secret values in `evidence`, logs, API responses, or the Markdown report. |
| State-changing requests need the CSRF header. | The middleware in `app/main.py` rejects any non-GET `/api/*` request without `X-Auditor-Client: 1`. New endpoints get this automatically. Do not add a route that bypasses the middleware. |
| Validate all input. | Pydantic models for bodies. Path and file names are checked with `safe_join` (`app/ingestion/workspace.py`). Do not build file paths from request data without it. |
| AI is opt-in per project. | Routes that call the LLM must check `llm_consent` and return `403` without it. Repository content in prompts must sit inside the `<repository_data>` wrapper. |
| Never store the GitHub token. | The token is used for one PR request and then discarded. Do not persist it, log it, or include it in an error message. |
| Fixes never touch the original copy. | Fixes are proposals stored as diffs. They reach GitHub only through a new branch and a pull request the user confirms. |

## Adding an analyzer or scanner

### Deterministic analyzer (Python code in the worker)

1. Add `app/analysis/<name>.py`. Expose a function that takes the parsed files
   and returns `(summary: dict, findings: list[RawFinding])`, like
   `analyze_quality` in `app/analysis/quality.py`.
2. Return findings as `RawFinding` objects from `app/analysis/common.py`:

   | Field | Allowed values |
   |---|---|
   | `tool` | Name of the analyzer, for example `"quality"` |
   | `rule_id` | Stable kebab-case ID. It feeds the fingerprint, so do not rename it casually. |
   | `category` | `security`, `architecture`, `code_quality`, `reliability`, `maintainability` |
   | `severity` | `critical`, `high`, `medium`, `low`, `info` |
   | `confidence` | `high`, `medium`, `low` |
   | `kind` | `objective` (measurable, e.g. a cycle or a duplicate block) or `subjective` (judgement) |
   | `title`, `explanation`, `impact`, `remediation`, `evidence` | Required text fields |
   | `file`, `line`, `end_line` | Location, when there is one |
   | `principle`, `references` | Optional, for example `"DRY"` or a CWE link |

   `fingerprint()` ignores line numbers, so small edits do not change finding
   identity.
3. Register it in `run_analysis` in `app/analysis/pipeline.py`. Call your function,
   add its findings to `findings`, and add its summary to the `summary` dict.
4. If the summary shape changes, update `src/lib/types.ts` and the matching report
   tab in `src/components/report/`.
5. Add tests as described in [docs/TESTING.md](docs/TESTING.md#how-to-add-a-new-analyzer).

### External scanner (subprocess)

1. Add `app/analysis/scanners/<name>.py`. Use `timed(name, binary, version_args, fn)`
   from `scanners/base.py`. It handles a missing binary (status `skipped`) and
   exceptions (status `failed`), so one broken scanner cannot abort the audit.
2. Run the tool through `run_tool` in `app/sandbox/process.py`. It applies an empty
   environment, a timeout, and a private working copy.
3. Register it in `run_analysis` in `app/analysis/pipeline.py`: add a
   `pool.submit(...)` entry, read its result, and append its findings.
4. Add the scanner name to the expected set in `test_full_audit_flow`
   (`tests/test_api.py`).

## Pull request checklist

- [ ] `uv run ruff check app tests` passes.
- [ ] `uv run pytest -m "not docker"` passes. Run `uv run pytest -m docker` too if you touched the sandbox.
- [ ] `npx tsc --noEmit`, `npm run lint`, and `npm run build` pass if you touched `frontend/`.
- [ ] New or changed behaviour has a test. Security-relevant changes have a test that would fail without the fix.
- [ ] New findings include every required field and the correct `kind`.
- [ ] No secrets, tokens, or real credentials in code, tests, fixtures, logs, or screenshots.
- [ ] `docs/API.md` and `src/lib/types.ts` match any API change.
- [ ] `ARCHITECTURE.md` is updated if a design decision changed.
- [ ] You checked the affected screens in the UI (see the manual checklist in [docs/TESTING.md](docs/TESTING.md#manual-ui-verification-checklist)).
- [ ] The PR description says what changed, why, and how you tested it.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short imperative summary>

<optional body explaining why>
```

- Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.
- Scopes: `backend`, `frontend`, `analysis`, `sandbox`, `remediation`, `api`, `docs`, or a module name.
- Keep the summary under 72 characters and lowercase after the colon.
- Do not commit `.env` files, local databases, `var/` workspaces, or cache directories.

Example:

```
fix(sandbox): fail closed when docker info times out
```
