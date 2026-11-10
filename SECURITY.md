# Security

Every imported repository is treated as **untrusted input**. This document describes the
threat model, the controls in place, and their limits. Security is part of the
architecture: most controls live in a single place and have dedicated tests
(see [docs/TESTING.md](docs/TESTING.md)).

## Threat model

| Threat | Example | Primary controls |
|---|---|---|
| Malicious archive | `../../etc/cron.d/x`, symlinks, zip bombs | `ingestion/zip_extract.py` |
| Malicious repository content | Code that runs on install/test; git hooks; LFS smudge filters | No execution outside the Docker sandbox; hardened `git clone` |
| Path traversal via the API | `/files/../../etc/passwd` | `safe_join` resolves and checks every path |
| Cross-user data access | Guessing another user's audit ID | Owner-scoped loaders, 404 for foreign resources |
| Secret disclosure | Repo contains AWS keys; server holds LLM/DB keys | Gitleaks `--redact`, masking, scrubbed subprocess env |
| Prompt injection | A README telling the AI to "ignore previous instructions" | Delimited untrusted data, structured output, AI never creates findings |
| Unwanted code changes | Auto-pushing fixes | Approval per fix, explicit confirmation, new branch only, drift check |
| Data leaving the server | Source sent to an LLM without consent | Per-project opt-in consent, redaction |
| CSRF / session theft | Cross-site form posts | HTTP-only SameSite cookie + mandatory custom header |

## Controls

### Ingestion
- **Request size**: an ASGI middleware rejects any request body over the upload cap + 1 MB
  before it is parsed or written to disk, from `Content-Length` or while streaming (SEC-04).
- **ZIP uploads**: magic-byte check, 50 MB upload cap (streamed), limits on entry count,
  total expanded size (enforced while streaming, since headers can lie) and per-entry
  compression ratio. Absolute paths, `..`, drive letters, symlinks and special files are
  rejected. Files are written `0600`.
- **GitHub import**: only `https://github.com/<owner>/<repo>` (validated by regex).
  `git clone --depth 1 --single-branch --no-tags` with `protocol.allow=never` except
  HTTPS, hooks disabled, symlinks disabled, submodules and LFS filters off, no global or
  system git config, no terminal prompts, a timeout, and `.git` deleted afterwards.
  The clone is watched while it runs and killed as soon as it passes `AUDITOR_MAX_EXTRACTED_BYTES`
  (SEC-05); file-count limits are enforced after cloning and symlinks are removed.
- **Per-user limits** (SEC-06): at most `AUDITOR_MAX_ACTIVE_AUDITS_PER_USER` (default 2) audits
  queued or running at once, and `AUDITOR_MAX_AUDITS_PER_USER_PER_DAY` (default 50); otherwise 429.

### Analysis without execution
- Tree-sitter, Semgrep, Gitleaks, OSV-Scanner and Trivy **read** files only.
- They run through `sandbox/process.py`: argv lists (no shell), a minimal allow-listed
  environment (no API keys, database URLs or other secrets), a new process group killed
  on timeout, CPU-time/file-size/core rlimits.
- OSV-Scanner and Trivy query vulnerability databases with package names and versions.
  **No source code is sent.** Set `AUDITOR_OFFLINE=true` to disable these lookups.

### Running tests (the only code execution)
Opt-in per audit, Docker only (`sandbox/docker_tests.py`):
- throwaway copy of the source; nothing is executed on the host;
- install phase: network allowed, but **install scripts disabled**
  (`pip --only-binary=:all:`, `npm --ignore-scripts`);
- test phase: `--network none`, dependency directory mounted read-only;
- both phases: non-root (`65534`), read-only root filesystem, `--cap-drop ALL`,
  `no-new-privileges`, CPU / memory / PID limits, wall-clock timeout, no host env vars;
- optional hardened runtime: `AUDITOR_SANDBOX_RUNTIME=runsc` (gVisor).
- If Docker is unavailable the step is reported as **skipped**, never run on the host.

**Residual risk:** containers share the host kernel; a kernel exploit could escape.
In production run sandboxes on a dedicated host or VM with gVisor/Kata, and do not
mount the Docker socket into the worker on a shared machine (the Compose file leaves the
sandbox disabled for this reason).

### Authentication and authorization
- Argon2id password hashing; minimum length 10; timing-equalised login for unknown users.
- Opaque 256-bit session tokens; only SHA-256 hashes are stored; HTTP-only,
  `SameSite=Lax`, `Secure` when `AUDITOR_COOKIE_SECURE=true`.
- **Login throttling without lockout** (SEC-02): only failed logins are counted (10 per 5
  minutes). A browser that has signed in to an account holds a signed device cookie
  (HMAC with `AUDITOR_SECRET_KEY`) and gets its own budget, so failures from anyone else cannot
  lock it out. Clients without a valid device cookie share one budget per email, so a user signing
  in from a new browser can still be delayed by an ongoing attack on their address. Client IPs
  are not used: behind the bundled Next.js proxy they are not trustworthy (a client-supplied
  `X-Forwarded-For` is passed through). Counters are in memory per API process.
- Registration attempts are limited per email address.
- **CSRF**: every non-GET `/api` request must carry `X-Auditor-Client: 1`. Browsers cannot
  send custom headers cross-origin without a CORS preflight, and CORS only allows the
  configured origins.
- **Authorization**: every project/audit/finding/fix lookup goes through
  `api/deps.py`, which joins to `Project.owner_id`. Another user's resource returns 404.

### Scanner integrity
- A scanned repository cannot suppress its own findings: repo `.semgrepignore`, `nosemgrep`
  comments, `.gitleaks.toml`, `.gitleaksignore`, `gitleaks:allow`, `.trivyignore`, `trivy.yaml`
  and `osv-scanner.toml` are ignored; the app supplies its own scanner configuration
  (`app/analysis/scanner_config/`). Suppressions that were present are listed in the report.
  Known gap: Trivy inline `trivy:ignore` comments cannot be disabled.

### Secrets
- Gitleaks runs with `--redact`; evidence shows the line with the secret masked.
- The file viewer replaces lines with Gitleaks-detected secrets; the Markdown export uses the
  same masked evidence for Gitleaks findings.
- Evidence from every other rule (Semgrep, Trivy, built-in analyzers) passes through
  `llm/redact.py` before it is stored, and the Markdown export redacts it again (SEC-03).
  Remaining gaps: redaction is pattern-based (common key formats, quoted secret assignments,
  connection strings, private keys), so unusual formats can still appear; audits stored before
  this change keep their original evidence in the API until re-run; and the file viewer shows
  raw source except for Gitleaks-detected lines.
- Text sent to an LLM passes through `llm/redact.py` (common key formats, credential
  assignments, connection strings, private keys) and Gitleaks-flagged lines are blanked.
- Server secrets come from environment variables only; `.env` is git-ignored.
- The GitHub token for PR creation is used for a single request and never stored or logged.

### AI
- Off by default. A project owner must explicitly enable it; the UI names the provider
  and model. Consent can be withdrawn at any time.
- Repository content is wrapped in `<repository_data>` tags and the system prompt tells
  the model to treat it as data. Responses must validate against a Pydantic schema and
  are rendered as text (never HTML).
- The AI does not create findings. AI fix proposals are restricted to a line range around
  the finding, must parse, and are labelled with provider and model.

### Remediation
- Fixes are proposals stored separately; the audited copy is never modified.
- A pull request requires: a GitHub project, at least one approved fix, `confirm: true`
  and a token. Changes go to a **new** branch `auditor/fixes-…`.
- Before writing anything, each target file on the base branch is compared with the
  audited copy; if it changed, nothing is written.

### Production configuration
- With `AUDITOR_ENV=production` the API, worker and cleanup job refuse to start unless
  `AUDITOR_COOKIE_SECURE=true`, `AUDITOR_INLINE_JOBS=false` and `AUDITOR_SECRET_KEY` is a
  random value of 32+ characters (SEC-07). `.env.production.example` is a starting point; it is
  rejected until its placeholder secret is replaced, and it ships with registration closed.
- Sandboxed test execution is off by default in code and in Compose.

### Data retention
- Source copies expire after `AUDITOR_WORKSPACE_TTL_HOURS` (default 24). Expired copies are
  deleted when the next audit job starts and by the hourly `cleanup` service in Docker Compose
  (`python -m app.worker cleanup`). The purge also removes orphaned workspace and upload folders
  older than the TTL that no audit references, such as ones left by a crashed job (SEC-08).
  Outside Compose, schedule that command yourself (e.g. hourly cron). A copy can therefore live
  up to about one hour past the TTL. Findings and metrics remain. Deleting a project deletes its
  source immediately.
- Uploaded ZIPs are deleted right after extraction.

### HTTP hardening
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
`Cache-Control: no-store` on API responses; OpenAPI docs disabled in production.

## Known limitations

- The score is a prioritisation aid, **not a security certification**. Static analysis
  misses business-logic and most authorization flaws.
- Login throttling is in memory per process; run one API process (as Compose does) or move the
  counters to Redis before scaling out.
- Registration reveals whether an email already has an account (409).
- Trivy honours inline `trivy:ignore` comments in the repository; they are listed in the report.
- No multi-factor authentication or account recovery yet.
- Docker-based isolation shares the host kernel (see above).

## Reporting a vulnerability

Please report security issues privately to the maintainers rather than opening a
public issue. Include steps to reproduce and the affected version.
