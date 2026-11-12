# Security review

Scope: backend (`backend/app`), frontend (`frontend/src`), Docker/Compose, migrations, as of 2026-11-08.
Method: code reading plus reproduction. The PoCs live in `docs/audit-evidence/` and were run against an isolated
SQLite instance and against the running Docker Compose stack.

**This is not a security certification.** It is a time-boxed review by the same tool-assisted team that built
the application. Treat it as an internal pre-release review, not an independent penetration test. An
independent review subagent was started but stopped by a usage limit before producing results, so every result below
comes from the checks recorded here.

Status legend: **VERIFIED** = reproduced. **SUSPECTED** = from code reading only, not reproduced.

## Summary

| ID | Severity | Title | Status |
|---|---|---|---|
| SEC-01 | High | A scanned repository can suppress its own findings (`.semgrepignore`, `# nosemgrep`, `.gitleaks.toml`) | VERIFIED → **FIXED** (residual: Trivy inline comments) |
| SEC-02 | Medium | Anyone can lock any user out of login (rate-limit key is shared behind the proxy) | VERIFIED → **FIXED with the production overlay** (trusted client IP via Caddy; verified live in CI); MITIGATED without it (known browsers protected) |
| SEC-03 | Medium | Secret values stored and exported verbatim when found by a non-Gitleaks rule | VERIFIED → **FIXED** (evidence redacted before storage and in the export; residual: file viewer, pre-fix audits, pattern coverage) |
| SEC-04 | Medium | Upload size limit is checked only after the whole body has been received and spooled | SUSPECTED → **FIXED** (ASGI body limit before parsing) |
| SEC-05 | Medium | No size cap while cloning; limits are enforced only after the clone finishes | SUSPECTED → **FIXED** (clone killed when it passes the size limit) |
| SEC-06 | Medium | No per-user quota or concurrency limit on audits; registration open by default | SUSPECTED → **FIXED** (per-user concurrent and daily limits; production template closes registration) |
| SEC-07 | Medium | Unsafe production defaults with no startup validation | VERIFIED → **FIXED** (validator incl. secret key; production template; sandbox off by default) |
| SEC-08 | Medium | Retention claim not enforced: source copies outlive the 24 h TTL on idle instances | VERIFIED (code) → **FIXED** (hourly Compose cleanup service; orphan sweep; Compose not re-run live) |
| SEC-09 | Low | Sandbox install phase has outbound network access | SUSPECTED |
| SEC-10 | Low | Account enumeration through registration (409) | VERIFIED (existing test) |
| SEC-11 | Low | Dev-only advisories in frontend lockfile (deepmerge, minimatch via shadcn CLI) | VERIFIED |
| SEC-12 | Info | AI-proposed patches are checked for syntax only; human approval is the real control | VERIFIED (code) |

The release-blocking reliability defects (REL-01, REL-02) are in [PRIORITIZED_FIXES.md](PRIORITIZED_FIXES.md). They
are not security bugs, but REL-02 has an availability impact.

---

### SEC-01 — Repository-controlled suppression of findings (High, VERIFIED)

- **Evidence:**
  - `backend/app/analysis/scanners/semgrep.py:24` runs `semgrep scan … .` with the repository as the working directory and no `--disable-nosem`, so Semgrep honours a `.semgrepignore` in the repo and inline `nosemgrep` comments.
  - `backend/app/analysis/scanners/gitleaks.py:19` runs `gitleaks dir .` with no `--config`, so Gitleaks loads a `.gitleaks.toml` (and `.gitleaksignore`, plus `gitleaks:allow` comments) from the scanned repository.
- **Reproduction:** `cd backend && .venv/bin/python ../docs/audit-evidence/security_pocs.py` (checks P6a–c). Output is in `docs/audit-evidence/security_pocs_output.txt`.
- **Observed:**
  - Adding `.semgrepignore` containing `server/` and `web/` dropped Semgrep findings from 16 to 0 and raised the overall score from 60.4 to 82.7.
  - A `.gitleaks.toml` allowlist dropped Gitleaks findings from 2 to 0.
  - Appending `# nosemgrep` to the SQL-injection line removed that finding.
  - The report shows no sign that anything was suppressed.
- **Impact:** The threat model treats repositories as untrusted. The tool's main promise is "is my application secure?", and an AI coding agent, or anyone with write access, can make a repository look clean. The score is inflated with no indication.
- **Remediation:**
  - Run Semgrep with `--disable-nosem` and ignore repo `.semgrepignore`, for example by scanning with an explicit, app-controlled ignore file.
  - Pass an explicit Gitleaks config (the default rules) so a repo `.gitleaks.toml` is not used, and pass `--ignore-gitleaks-allow` where supported.
  - If honouring developer suppressions is wanted, report them as a separate, visible "suppressed" list rather than dropping them.
- **Fixed (follow-up pass).** Repository suppressions are never honoured; the app controls every scanner's ignore rules and reports what it ignored:
  - **Semgrep:** `--disable-nosem`, `--x-ignore-semgrepignore-files`, `--no-git-ignore`, and the app's own excludes (dependency, build and test folders, the same as Semgrep's defaults) (`scanners/semgrep.py`).
  - **Gitleaks:**
    - `--config scanner_config/gitleaks.toml` extends the built-in rules, so a repo `.gitleaks.toml` is not used.
    - `--ignore-gitleaks-allow` disables inline allow comments.
    - `--gitleaks-ignore-path` points to an empty app folder. Gitleaks *also* always reads `<source>/.gitleaksignore`, a gap found by the new test, so that file is moved aside for the scan and restored afterwards (`scanners/gitleaks.py`).
  - **Trivy:** `--ignorefile ""` and `--config ""` stop it reading the repo's `.trivyignore` and `trivy.yaml`.
  - **OSV-Scanner:** `--config scanner_config/osv-scanner.toml` overrides repo `osv-scanner.toml` ignore lists. `--no-ignore` was added later (DET-16), because OSV also honours `.gitignore`. A repo `.gitignore` listing `uv.lock` dropped OSV findings from 11 to 0; with the flag they are 11 again.
  - **Visibility:** suppression files and inline markers are listed in `summary.suppressions`, shown as a note on the Overview tab and in the Markdown export (`scanners/suppressions.py`).
  - **Verification:**
    - `security_pocs.py` P6a–c now HOLD: Semgrep 16→16, score 60.4→60.4, Gitleaks 2→2, SQLi still reported (`docs/audit-evidence/security_pocs_output_after_sec01.txt`).
    - `tests/test_scanner_suppression.py` (6 tests) covers every mechanism, including `.gitleaksignore` and `gitleaks:allow`.
  - **Residual risk:**
    - Trivy's inline `trivy:ignore` comments in IaC files cannot be disabled by flag. They are counted in the suppression note, but they still hide that misconfiguration finding (SUSPECTED, not reproduced).
    - Semgrep still skips `test/` and `tests/` folders, as it does by default; the tree-sitter analyzers still cover them.
    - Verified with the host scanner versions, which are the same versions pinned in the Docker image; the container itself was not rebuilt for this change.

### SEC-02 — Login lockout of arbitrary users (Medium, VERIFIED)

- **Evidence:** `backend/app/api/auth.py:30-38`. The limiter key is `client IP | email`. Behind the Next.js proxy (`frontend/next.config.ts` rewrites), every request reaches the API from the web container's IP; the API access log shows `172.18.0.6` for all users. The limiter is also per process and in memory.
- **Reproduction:** `security_pocs.py`, check P1. It makes 10 failed logins for `victim@example.com` from another client.
- **Observed:** the victim's next login, with the correct password, returned **429**.
- **Impact:** Anyone who knows a user's email can keep that user locked out indefinitely (10 requests per 5 minutes). Per-IP protection against password spraying across many emails is also absent.
- **Remediation:**
  - Key failed-login counters on the email, but only count failures, and lock with exponential back-off instead of a hard block.
  - Add a separate per-real-client-IP limit using a trusted proxy header (configure Next/uvicorn `--forwarded-allow-ips`).
  - Store counters in Redis so they work across instances.

### SEC-03 — Secrets kept verbatim outside the Gitleaks path (Medium, VERIFIED)

- **Evidence:** `backend/app/analysis/scanners/semgrep.py:60` sets `evidence=read_lines(...)` with the raw source lines. Only Gitleaks findings are masked (`gitleaks.py`, `api/audits.py _mask_secrets`). `SECURITY.md` claims "the Markdown export uses the same masked evidence".
- **Reproduction:** `security_pocs.py`, checks P3a and P3b.
- **Observed:**
  - The `semgrep/py-hardcoded-secret-key` finding stores `app.secret_key = "super-secret-dev-key-123"` in the database, and the exported `report.md` contains the value.
  - Gitleaks-detected keys are masked correctly (P3c).
- **Impact:** Secrets that Gitleaks doesn't detect but Semgrep does end up in the database and in reports that are meant to be shared. The exposure is limited to the repository owner's own report, but it contradicts the documented control.
- **Remediation:** Run `llm/redact.py`'s redaction over every finding's evidence before storing it, and over the file viewer and Markdown export. Correct SECURITY.md until this is done.

### SEC-04 — Upload limit enforced after full receipt (Medium, SUSPECTED)

- **Evidence:** `backend/app/api/projects.py` `_save_upload` counts bytes while copying from `UploadFile`. FastAPI/Starlette have already parsed the multipart body and spooled the whole file to a temp file before the handler runs, and no request-size limit exists in uvicorn, the Next.js proxy or Compose.
- **Impact:** Any registered user can make the server receive and store arbitrarily large uploads before getting a 413. This is a disk and bandwidth DoS.
- **Remediation:** Enforce `Content-Length` and a streaming body limit in middleware or the reverse proxy (for example nginx `client_max_body_size`), and reject before parsing.

### SEC-05 — Clone is unbounded until it finishes (Medium, SUSPECTED)

- **Evidence:** `backend/app/ingestion/github.py:25-47`. `git clone --depth 1` has a 120 s timeout, but the size and file-count limits (`_enforce_limits`) run only after the clone completes.
- **Impact:** A large public repository can fill the worker's disk within the timeout.
- **Remediation:** Check repository size through the GitHub API before cloning, clone into a size-limited volume or tmpfs, or use `--filter=blob:limit=…`.

### SEC-06 — No quotas (Medium, SUSPECTED)

- **Evidence:** No per-user limit on projects, audits or concurrent jobs (`api/projects.py`). Registration is open by default (`core/config.py:53`). A single RQ worker processes jobs serially.
- **Impact:** One account can queue unlimited audits and starve everyone else.
- **Remediation:** Add per-user concurrency (1–2) and daily limits, and an admin switch for closed registration in production.

### SEC-07 — Unsafe production defaults (Medium, VERIFIED by reading config)

- **Evidence:** `backend/app/core/config.py`:
  - `env="development"` (line 13), so `/api/docs` is exposed unless `AUDITOR_ENV=production`;
  - `cookie_secure=False` (line 51);
  - `allow_registration=True` (line 53);
  - no validator rejects `inline_jobs=True` or insecure cookies when `env=production`.
- `.env.example` ships `AUDITOR_ENV=development`.
- **Remediation:** Add a settings validator that refuses to start in production with insecure values, and ship a production `.env` template.

### SEC-08 — Retention claim not enforced (Medium, VERIFIED by code)

- **Evidence:**
  - `backend/app/jobs.py:69`: `purge_expired_workspaces()` runs only at the start of the next audit job, or through the manual `python -m app.worker cleanup`.
  - No scheduler exists: `worker.py:21` uses `with_scheduler=False`, and there is no cron service in Compose.
  - Orphaned `<id>.upload` directories are never swept.
  - ARCHITECTURE.md says "a cleanup job deletes them".
- **Impact:** On a quiet instance, copies of private source code stay on disk indefinitely, past the advertised 24 h.
- **Remediation:** Run the purge periodically (a worker loop or a scheduled job), sweep the workspace root by mtime regardless of database state, and add a test.

### SEC-09 — Sandbox install phase has network (Low, SUSPECTED)

- **Evidence:** `backend/app/sandbox/docker_tests.py` runs the install phase with `--network bridge`. Install scripts are disabled (`pip --only-binary=:all:`, `npm --ignore-scripts`), which blocks the common code-execution paths. The test phase has no network, verified by `tests/test_sandbox.py` passing.
- **Residual risk:** If any build path runs repository code during install, it has outbound network but no secrets. In Compose the worker has no Docker access, so runs are skipped. Before this pass, `.env.example` enabled the sandbox flag (CFG-01, now `false`).
- **Remediation:** Install through an egress proxy restricted to package registries, or pre-resolve dependencies on a separate trusted builder.

### SEC-10 — Account enumeration (Low, VERIFIED)

- **Evidence:** `backend/app/api/auth.py:58` returns 409 "An account with this email already exists", asserted by `tests/test_api.py::test_duplicate_registration_and_weak_password`. Login itself is timing-equalised.
- **Remediation:** Return a generic response and send a verification email.

### SEC-11 — Frontend dev-dependency advisories (Low, VERIFIED)

- `osv-scanner` on `frontend/package-lock.json` reports `deepmerge 4.3.1` (CVSS 5.3) and `minimatch 10.2.6` (6.9). Both come through the shadcn CLI, a build-time dependency.
- `npm audit --omit=dev` reports **0 vulnerabilities**, and the backend `uv.lock` has no known advisories (`docs/audit-evidence/osv-self.json`).

### SEC-12 — AI patch validation is syntactic (Info)

- **Evidence:** `backend/app/api/remediation.py` and `remediation/patching.py`. AI edits are limited to a line window, must apply cleanly and must not introduce parse errors.
- Nothing checks semantics. A prompt-injected repository could steer a plausible but harmful patch.
- **Mitigations that hold:** per-fix human approval; PRs go only to a new branch of the audited repository; a drift check aborts if the remote changed.
- Keep the UI warning that AI patches must be reviewed.

---

## Controls verified as working

| Control | How verified |
|---|---|
| Cross-user isolation (IDOR) on all 11 resource operations returns 404 | `security_pocs.py` P4; `tests/test_api.py::test_cross_user_isolation`; live against Compose |
| File-viewer path traversal blocked (`../`, absolute, encoded) | P5; `test_file_viewer_path_traversal` |
| ZIP attacks: traversal, absolute paths, drive letters, symlinks, special files, zip-bomb ratio, total size, entry count | `tests/test_zip_extract.py` (all pass) |
| CSRF: non-GET without `X-Auditor-Client: 1` → 403, including through the Next.js proxy | `test_csrf_header_required`; live check against Compose returned 403 |
| Session cookie HttpOnly and SameSite=Lax; logout revokes; opaque tokens stored hashed | `test_auth_lifecycle`; code `core/security.py` |
| Gitleaks secrets masked in evidence, file viewer and Markdown export | P3c; `test_full_audit_flow` |
| LLM consent gating (403 without consent) and prompt redaction / `<repository_data>` wrapping | `test_ai_requires_consent_and_provider`, `test_ai_overview_is_redacted_cached_and_injection_wrapped` |
| PR creation: GitHub-only, needs `confirm: true` and approved fixes, aborts without writing if the remote file changed | `test_deterministic_fix_approval_and_pr_rules`, `test_pr_aborts_if_remote_changed` (GitHub mocked) |
| Docker sandbox: no network, no host env vars, read-only rootfs, non-root | `tests/test_sandbox.py` (real Docker run, passed) |
| Scanner subprocesses get a scrubbed environment (no API keys or DB URLs) | code `sandbox/process.py`; covered indirectly by the sandbox env test |
| GitHub URL allow-list (https://github.com/owner/repo only) | `test_github_url_validation` |
| Own dependencies: backend `uv.lock` 0 advisories; frontend production deps 0 | `docs/audit-evidence/osv-self.json`, `npm-audit-prod.txt` |

## Not reviewed or not reproducible in this pass

- Real GitHub PR creation (needs a real token; mocked only).
- Real LLM behaviour under prompt injection (fake provider only).
- Git clone edge cases against a hostile remote (submodules, LFS and symlink handling verified by reading the arguments, not by a PoC).
- Load or DoS testing.
