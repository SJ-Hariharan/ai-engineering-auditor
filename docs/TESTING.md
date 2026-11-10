# Testing

## Philosophy

- **Deterministic analysis is unit-tested.** Parsers, the import graph, quality
  metrics, scoring, and fixers return the same output for the same input, so tests
  assert exact results.
- **Security boundaries have dedicated tests.** Each trust boundary (archive
  extraction, file access, authentication, ownership, AI data handling, GitHub
  writes, and test execution) has tests that try to cross it and expect a refusal.
- **Tests need no network and no secrets.** The suite runs with SQLite in a temp
  directory, inline jobs, `AUDITOR_OFFLINE=true` (no OSV or Trivy database
  lookups), and the LLM provider set to `none`. The only external pieces are
  optional: Semgrep and Gitleaks (tests that need them are skipped when missing)
  and Docker (the sandbox test is skipped when no daemon is running).

## Quick reference

Run from `backend/`.

| Goal | Command |
|---|---|
| Install dependencies | `uv sync` |
| Run everything the environment supports | `uv run pytest` |
| Fast run, no Docker | `uv run pytest -m "not docker"` |
| Only the Docker sandbox test | `uv run pytest -m docker` |
| Skip Semgrep and Gitleaks tests | `SKIP_SCANNERS=1 uv run pytest` |
| One file | `uv run pytest tests/test_zip_extract.py` |
| One test | `uv run pytest tests/test_api.py::test_cross_user_isolation` |
| Lint | `uv run ruff check app tests` |

Pytest is configured in `backend/pyproject.toml`: `testpaths = ["tests"]`, quiet
output (`-q`), and a `docker` marker.

Install Semgrep and Gitleaks on your `PATH` to run the scanner-dependent tests
(`test_full_audit_flow`). Both are available from Homebrew and other package
managers. OSV-Scanner and Trivy are not required by any test, because the tests only
check that the scanner names appear in the summary.

### Frontend

```bash
cd frontend
npm install             # first time only
npm test                # Vitest unit and component tests (jsdom), about 5 seconds
npx tsc --noEmit        # type check (strict mode)
npm run lint            # ESLint
npm run build           # production build, catches many runtime import errors
```

Vitest is configured in `frontend/vitest.config.ts`. Tests live next to the code as
`src/**/*.test.ts(x)`. The shared setup file `src/test/setup.ts` loads the jest-dom
matchers and unmounts rendered trees after each test. `src/test/fixtures.ts` has a
`makeFinding()` helper that builds a valid `Finding`. The tests need no backend and no
network. `src/lib/api.test.ts` runs in the Node environment (`// @vitest-environment node`)
and stubs `fetch` and `window`.

| Test file | What it covers |
|---|---|
| `src/lib/api.test.ts` (17) | Mutating requests send `X-Auditor-Client: 1` and `credentials: "include"`. GET requests do not send the header. FastAPI `{detail}` strings and validation arrays become readable `ApiError` messages. Non-JSON errors fall back to a status message. Network failure is `ApiError(0, ...)`. A 401 redirects to `/login` from protected pages only. Query params are encoded and empty ones dropped. Path segments are encoded. 204 returns `undefined`. |
| `src/lib/format.test.ts` (23) | Grade boundaries, score and number formatting, repo name parsing, `worstSeverity`, code and tab link builders, and `timeAgo` buckets (fake timers). |
| `src/lib/file-tree.test.ts` (6) | Code-tab tree building: leaf-only file nodes, shared folders, folders sorted before files. |
| `src/components/app/diff-view.test.tsx` (8) | `parseDiff` line kinds, old and new line numbers, CRLF input. The component marks added and removed lines with a sign and an accessible label. The unified and before/after layouts both work. |
| `src/components/app/code-view.test.tsx` (7) | Line numbers, CRLF input, gutter markers for finding lines (clickable, with a label), multi-line shading, the focused line, and no marker for findings without a line. |
| `src/components/app/badges.test.tsx` (8) | Each severity renders its text label. Severity counts list only non-zero levels, most severe first. |
| `src/components/app/score.test.tsx` (9) | Score colour thresholds, the progressbar ARIA values, clamping, and the grade badge label. |
| `src/components/report/findings-table.test.tsx` (14) | `filterFindings` (category, severity, kind, search across title, file, rule and tool), `sortFindings`, and the rendered table with its filter controls, counts, empty state and row click. |
| `src/components/report/overview-tab.test.tsx` (4) | Score cards for SC-01/SC-02: a not-analysed category shows *Not analysed*, grade N/A, its reason and "Excluded from the overall score"; same-line duplicates are reported; a capped overall explains the cap and the uncapped value; an incomplete category is marked; no score when nothing was analysed; audits scored before the fix still render. |
| `src/components/report/untrusted-text.test.tsx` (1) | A finding title, rule id, file, and evidence that contain `<img src=x onerror=alert(1)>` render as literal text, with no `img` or `onerror` attribute created. |

Two small refactors made the logic testable without changing behaviour:
`filterFindings` and `sortFindings` are now exported from `findings-table.tsx`,
`parseDiff` is exported from `diff-view.tsx`, and `buildTree`/`sortedChildren` moved
from `code-tab.tsx` to `src/lib/file-tree.ts` (with `worstSeverity` moved to
`src/lib/format.ts`).

The page-level components (report tabs, auth forms, the dropzone, the dependency
graph) are not covered by automated tests. See [Known gaps](#known-gaps).

### End-to-end smoke test

Run this against a live API and worker (see the dev setup in
[CONTRIBUTING.md](../CONTRIBUTING.md#dev-setup)):

```bash
cd backend
uv run python scripts/smoke.py --api http://localhost:8000 --github https://github.com/pallets/itsdangerous
```

The script registers a throwaway user, creates a GitHub project, and polls the audit
until it completes or fails (default timeout 600 seconds). It prints:

- the project name and audit ID, then each stage change
- the commit SHA, overall score and grade
- each category score with its finding counts
- each scanner's status, finding count, and message
- the overview paragraphs
- the total number of findings and the first 12 returned by the findings endpoint

It exits with `1` if the audit fails. It needs a running worker, and it needs
network access to GitHub and to any enabled scanner databases.

## Test suite map

All files are in `backend/tests/`. `conftest.py` provides the autouse settings
fixture, a `client` fixture (FastAPI `TestClient` with the CSRF header set), the
`register` helper, `zip_dir` for building archives from the fixture app, and the
`requires_scanners` marker.

### `test_zip_extract.py`: archive ingestion and path safety

| Test | What it covers |
|---|---|
| `test_extracts_and_unwraps_single_root` | A single top-level folder (as GitHub archives produce) is unwrapped. |
| `test_rejects_path_traversal` (4 cases) | Entries named `../evil.py`, `/etc/passwd`, `a/../../evil.py`, and `C:/win.ini` are rejected and nothing is written outside the destination. |
| `test_rejects_symlinks` | Symlink entries are refused. |
| `test_rejects_zip_bomb_ratio` | A highly compressible entry is refused by the ratio or size limit. |
| `test_rejects_too_many_files` | Archives over `AUDITOR_MAX_FILES` entries are refused. |
| `test_rejects_non_zip` | Non-archive bytes raise `IngestionError`. |
| `test_safe_join` | Path joining rejects `..`, NUL bytes, and a symlink that points outside the workspace. |
| `test_zip_bytes_helper_roundtrip` | Sanity check of the in-memory ZIP helper used by other tests. |

### `test_analyzers.py`: deterministic analysis

| Test | What it covers |
|---|---|
| `test_python_parsing_extracts_structure` | Imports, function parameters, cyclomatic complexity, class parent, decorator-style HTTP routes (`@app.post`), and detection of bare `except` and swallowed exceptions. |
| `test_typescript_parsing_and_syntax_errors` | TS/TSX imports, empty `catch` detection, and syntax error reporting. |
| `test_cycle_detection_and_unresolved_imports` | Import-graph cycles (TS and Python), the `@/` alias to `src/`, and unresolved relative imports. |
| `test_tarjan_large_chain_no_recursion_error` | Strongly connected components on a 5,000-node cycle without hitting Python's recursion limit. |
| `test_duplication_and_complexity` | `duplicate-code` (objective, DRY principle) and `high-complexity` findings. |
| `test_scores_have_diminishing_returns_and_bounds` | Scores stay between 0 and 100, repeated identical findings have diminishing effect, one noisy rule cannot zero a category, and the methodology states "not a security certification". |
| `test_redaction` | Anthropic-style keys, AWS access keys, `password =` values, and database URL credentials are removed from text before any AI prompt. The redacted line is marked. |

### `test_scoring.py`: scoring regressions (SC-01, SC-02)

Pure functions plus two small pipeline runs with `run_scanners=False`; no scanners needed.

| Test group | What it covers |
|---|---|
| Same-location grouping (SC-02) | One issue flagged by 4 rules on the same line scores the same as 1 rule (81.9, was 44.9). Gitleaks critical + Semgrep high on one line counts as the critical. The kept finding is chosen the same way in every input order. Distinct occurrences (other lines, other files, other categories, file-level findings with no line) are still each penalised. `counts` keep every reported finding and `merged_duplicates` reports the merge. `_dedupe` keeps every rule at a location in the report. |
| Coverage and caps (SC-01) | A lone high-confidence critical secret is capped at 79.9 / C (was 89.8 / B); medium-confidence criticals do not trigger the cap; the cap never raises a score. Categories with no parsed files are N/A, effective weights renormalise and sum to 1. Nothing analysable gives `overall: null`, grade `N/A`. A failed, skipped or missing security scanner marks security incomplete and caps at 89.9. Findings prove a category was analysed. Both caps together use the lower. Over 300 random inputs the grade always matches the score. Without coverage the old fully-analysed behaviour holds. The pipeline marks unparsed categories N/A and runs without scanners as incomplete. |

### `test_api.py`: HTTP behaviour, authorization, and the audit flow

| Test | What it covers |
|---|---|
| `test_auth_lifecycle` | Register, `/auth/me`, logout invalidates the session, wrong password is `401`, email is case-insensitive, and the cookie is `HttpOnly` with `SameSite=Lax`. |
| `test_duplicate_registration_and_weak_password` | Duplicate email is `409`. Passwords under the minimum length are `422`. |
| `test_csrf_header_required` | A POST without `X-Auditor-Client: 1` is refused with `403`. |
| `test_login_rate_limit` | Repeated failed logins eventually return `429`. |
| `test_requires_auth` | Protected routes return `401` without a session. |
| `test_github_url_validation` | Non-HTTPS URLs, other hosts, `..` segments, `file://` URLs, and repo-less URLs are rejected with `422`. |
| `test_upload_rejects_non_zip` | A `.zip` upload that is not a zip is rejected and no project is created. |
| `test_upload_size_limit` | Uploads over `AUDITOR_MAX_UPLOAD_BYTES` return `413`. |
| `test_full_audit_flow` (needs Semgrep and Gitleaks) | Upload of the fixture app completes. Score is under 90. All four scanner names appear in the summary. Expected rules are found: SQL injection, reflected XSS, circular dependency, unresolved import, bare except, no tests, and AWS access token. Every finding has severity, category, confidence, kind, explanation, impact, and remediation. Gitleaks evidence does not contain the planted AWS key. The file viewer for `.env` does not show the key or the GitHub token. The Markdown report contains the certification disclaimer and not the key. |
| `test_file_viewer_path_traversal` | `../` sequences, URL-encoded `../`, and `server/../../x` are refused with `400` or `404`. A normal file path works. |
| `test_cross_user_isolation` | Another user gets `404` for another user's project, audit, findings, file, fixes, and report. They also cannot PATCH, DELETE, fix, or explain. |
| `test_deterministic_fix_approval_and_pr_rules` | A `bare-except` fix is generated deterministically with a correct diff. Approving it changes its status. A PR request is refused with `422` for an upload project, both with and without `confirm`. The original file is unchanged. |
| `test_ai_requires_consent_and_provider` | AI explain returns `403` without project consent, `503` with consent but no provider. `/api/ai/status` reports `none`. |
| `test_rerun_zip_requires_new_upload_and_compares` | Re-running an upload project without a new file returns `422`. A new upload creates an audit that compares against the previous one. |
| `test_delete_project_removes_workspace` | Deleting a project removes its workspace directory and returns `404` for the audit afterwards. |

### `test_remediation_llm.py`: patching, GitHub PR safety, and the AI layer

| Test | What it covers |
|---|---|
| `test_apply_edits_multiple_and_insert` | Several line edits, including an insertion at the top of a file, apply in the right order. |
| `test_apply_edits_rejects_overlap_and_drift` | Overlapping edits are refused. An edit whose original text no longer matches the file is refused. |
| `test_check_syntax_rejects_broken_change` | A patch that makes Python code unparseable is rejected before it is proposed. |
| `test_pr_happy_path_uses_new_branch` | The PR flow (GitHub API mocked) creates a new `auditor/...` branch, writes the file with the expected blob SHA, and opens a pull request. |
| `test_pr_aborts_if_remote_changed` | If the remote file differs from the proposal's base, the PR is refused with `409` and no write or branch creation happens. |
| `test_ai_overview_is_redacted_cached_and_injection_wrapped` | With a fake provider: the prompt sits inside `<repository_data>`, the system prompt tells the model to ignore instructions in the data, planted secrets are absent from the prompt, a repeat request is served from cache, and a traversal target is refused. |
| `test_ai_fix_is_validated` | An AI fix needs consent (`403` without). With consent, the fake provider's suggestion is validated and stored with `source: "ai"` and its generator name. |

### `test_sandbox.py`: Docker test runner (`docker` marker)

| Test | What it covers |
|---|---|
| `test_sandbox_blocks_network_and_hides_host_env` | Inside the container: outbound connections fail (`--network none`), a host environment variable is not visible, and writes to the root filesystem fail. The run must report 4 passing tests and 100% coverage. |

This test is skipped when Docker is unavailable. It is the only test that runs
repository-style code, so run it after any change under `app/sandbox/`.

## Running by category

| Category | Files | Needs |
|---|---|---|
| Pure logic | `test_zip_extract.py`, `test_analyzers.py`, most of `test_remediation_llm.py` | Nothing |
| HTTP and authorization | `test_api.py` (except `test_full_audit_flow`) | Nothing |
| Scanner-dependent | `test_api.py::test_full_audit_flow` | Semgrep and Gitleaks on `PATH` |
| Docker sandbox | `test_sandbox.py` | Running Docker daemon |

## How to add a new Semgrep rule

Rules live in `backend/app/analysis/rules/python.yml` and `javascript.yml`. Each
rule needs `id`, `languages`, `severity`, `message`, and `metadata` with `category`,
`cwe`, `confidence`, `impact`, and `fix`. The scanner maps `ERROR` to `high`,
`WARNING` to `medium`, and `INFO` to `low`. Rules in the `sql-injection`,
`command-injection`, and `code-injection` categories become `critical` when
confidence is `HIGH`.

1. Add the rule to the appropriate file in `app/analysis/rules/`.
2. Add a matching vulnerable line to the fixture app in
   `tests/fixtures/vulnerable_app/`. The fixture is intentionally insecure and is
   excluded from ruff. Do not add real secrets. Use obviously fake values.
3. Test the rule against the fixture. Semgrep skips `tests/` directories by default,
   so copy the fixture to a directory outside `tests/` and scan that copy:

   ```bash
   cd backend
   SCAN_DIR="$(mktemp -d)"
   cp -R tests/fixtures/vulnerable_app/. "$SCAN_DIR"/
   semgrep scan --config app/analysis/rules --json --metrics=off "$SCAN_DIR" \
     | python3 -c "import json,sys; [print(r['check_id'], r['path'], r['start']['line']) for r in json.load(sys.stdin)['results']]"
   ```

   Your rule ID should appear in the output. Use the `check_id` suffix (the part after the last `.`) as the `rule_id` in the app.
4. Add the rule ID to the expected set in `test_full_audit_flow` so the test fails
   if the rule stops firing.
5. Run `uv run pytest tests/test_api.py::test_full_audit_flow`. It needs Semgrep on `PATH`.

## How to add a deterministic fixer

Fixers live in `backend/app/remediation/fixers.py`. A fixer is a function that takes
the file's lines and the finding, and returns `(edits, rationale, caveats)` or `None`
when it cannot make a safe change. Register it with `@fixer("<rule-id>")`. Use
`make_edit` and `apply_edits` from `app/remediation/patching.py`. The patch pipeline
checks syntax and rejects overlapping or stale edits, so a fixer only has to produce
the edit.

1. Write the fixer. Return `None` when the change is not mechanical (for example,
   `py-unsafe-deserialization` only fixes `yaml.load`, not `pickle`).
2. Add a test. Today `test_deterministic_fix_approval_and_pr_rules` covers only
   `bare-except`, through the API. For a new fixer, add a focused test in
   `tests/test_remediation_llm.py` that calls `deterministic_fix(lines, finding)`
   with a `Finding` (or the same shape) and asserts the new text and the caveats.
   Also assert that the result passes `check_syntax` for Python.
3. Run the API flow test if the fixer is reachable from the fixture. For fixers
   whose rule comes from Semgrep, the test needs Semgrep on `PATH`.

## How to add a new analyzer

1. Add a unit test in `tests/test_analyzers.py` that parses a small inline project
   (use `_write` to create files in `tmp_path`) and asserts the exact `rule_id`s
   and `kind` values. Follow `test_duplication_and_complexity` for a pattern.
2. If the analyzer adds an API-visible field, extend `test_full_audit_flow` to check
   it on the fixture.
3. Keep the test deterministic. Do not use wall-clock time, random values, or the
   network.

## Manual UI verification checklist

Frontend unit and component tests (`npm test`) cover the API client, helpers and core
components, but not full pages or real browser behaviour. For any frontend change, or any
backend change that affects what the UI shows, run the app (`npm run dev` with the API running)
and check:

- [ ] Register, log out, and log in again. Logging out and then loading a page
      sends you to `/login`.
- [ ] Create a project from a GitHub URL. The audit page shows stage changes while
      it runs, then the report.
- [ ] Upload the fixture app as a `.zip`. The report appears, and the score is
      below 90.
- [ ] Every report tab opens without errors: overview, findings, architecture,
      quality, testing, code, learn, remediation, methodology.
- [ ] Deep link `/audits/{id}?tab=code&file=server/app.py&line=21` opens the code tab at that file.
- [ ] Open a finding. It shows severity, confidence, `kind` (objective or subjective),
      evidence, impact, and remediation.
- [ ] `.env` in the code tab does not show the planted AWS key or the GitHub token.
- [ ] Remediation: a deterministic fix shows a diff. Approving it changes its
      status. Creating a PR asks for explicit confirmation first.
- [ ] AI: with consent off, the AI actions show that consent is needed. With no
      provider configured, they show an error and do not invent output.
- [ ] Log in as a second user and try to open the first user's audit URL. The page
      shows "not found", not the report.
- [ ] Theme toggle switches between light and dark, and text stays readable in both.
- [ ] At phone width (about 375 px) the report and the new-audit panel are usable
      and do not scroll sideways.
- [ ] The browser console shows no errors during these steps.

## Known gaps

| Gap | Detail |
|---|---|
| Frontend tests cover helpers and selected components only | Vitest covers the API client, pure helpers, the diff, code, badge and score components, and the findings table filters. Report tabs, auth forms, the upload dropzone, the dependency graph, and the AI panels have no automated tests, so they still rely on the manual checklist above. |
| No frontend end-to-end or browser tests | Nothing drives a real browser against a running backend. Visual layout, dark mode, and the phone-width checks remain manual. |
| No frontend coverage threshold | `npm test` does not collect coverage and no target is enforced. |
| No load or performance tests | Nothing measures throughput, large repository handling, or worker concurrency. |
| PR flow tested with a mocked GitHub only | `test_remediation_llm.py` replaces the GitHub client with `httpx.MockTransport`. Real branch, commit, and PR behaviour against github.com is not tested automatically. |
| LLM output tested only with a fake provider | `FakeProvider` checks prompts, redaction, caching, and validation. Real Anthropic and OpenAI responses, rate limits, and malformed model output are not tested automatically. |
| OSV-Scanner and Trivy not asserted | `test_full_audit_flow` checks that their names appear in the summary, not that they ran. |
| Per-rule Semgrep tests are indirect | Rules are checked by the fixture-based audit test, not by one test per rule. |
| Fixer coverage is thin | Only `bare-except` is exercised through the API. The other fixers in `fixers.py` have no dedicated tests. |
| Docker sandbox needs a local daemon | `test_sandbox.py` is skipped on machines without Docker, so it does not run in a plain `uv run pytest`. |
| No CI configuration in the repository | Tests and lint are run by hand. |
| No coverage threshold | `pytest-cov` is a dev dependency, but no coverage target is enforced. |
