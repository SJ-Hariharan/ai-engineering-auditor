# API reference

Base path: `/api`. JSON everywhere except uploads (multipart) and `report.md` (text).
Interactive OpenAPI docs: `http://localhost:8000/api/docs` (disabled when `AUDITOR_ENV=production`).

## Conventions

- **Auth**: HTTP-only cookie `auditor_session` set by `/auth/register` and `/auth/login`.
  Send requests with `credentials: "include"`.
- **CSRF**: every non-GET request must include header `X-Auditor-Client: 1`, otherwise `403`.
- **Errors**: `{"detail": "message"}` (or FastAPI validation errors `{"detail": [ ... ]}` with 422).
- **Ownership**: resources owned by another user return `404`.
- Status codes used: `401` not logged in · `404` not found · `409` conflict/in progress ·
  `410` source files expired (retention) · `413` upload too large · `422` validation ·
  `429` rate limited · `502/503` AI provider or GitHub unavailable.

## Auth

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/register` | `{email, password(min 10)}` | `201 User` + cookie |
| POST | `/auth/login` | `{email, password}` | `User` + cookie |
| POST | `/auth/logout` | – | `204` |
| GET | `/auth/me` | – | `User` |

`User = {id, email, created_at}`

## Projects

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/projects` | – | `Project[]` |
| POST | `/projects/github` | `{url: "https://github.com/o/r", branch?: string}` | `201 ProjectDetail` (first audit queued) |
| POST | `/projects/upload` | multipart `file` (.zip ≤ 50 MB), optional `name` | `201 ProjectDetail` |
| GET | `/projects/{id}` | – | `ProjectDetail` |
| PATCH | `/projects/{id}` | `{name?, llm_consent?: boolean}` | `ProjectDetail` |
| DELETE | `/projects/{id}` | – | `204` (deletes audits and stored source) |
| POST | `/projects/{id}/audits` | GitHub: empty body. ZIP: multipart `file` required | `201 Audit` (re-run; compared with previous) |

```ts
Project = { id, name, source_type: "github"|"zip", source_url: string|null, default_branch: string|null,
            llm_consent: boolean, llm_consent_at: string|null, created_at, latest_audit: AuditBrief|null }
ProjectDetail = Project & { audits: AuditBrief[] }          // newest first
AuditBrief = { id, status: "queued"|"running"|"completed"|"failed", stage: string|null, error: string|null,
               commit_sha: string|null, created_at, finished_at: string|null,
               overall_score: number|null, finding_counts: {critical?: n, high?: n, ...} }
```

`stage` while running: `ingestion → inventory → parsing → architecture → design → quality → testing → security → scoring`.
Poll `GET /audits/{id}` every ~2 s until status is `completed` or `failed`.

## Audits

| Method | Path | Notes |
|---|---|---|
| GET | `/audits/{id}` | `Audit` (full summary) |
| GET | `/audits/{id}/findings?category=&severity=&kind=&file=&sort=priority\|severity\|file` | `Finding[]` |
| GET | `/audits/{id}/files/{path}` | `FileContent` (410 when source expired; secrets masked) |
| POST | `/audits/{id}/tests/run` | `202 {status:"queued"}` — runs tests in Docker sandbox; result appears in `summary.testing.run` |
| GET | `/audits/{id}/report.md` | Markdown export |

```ts
Audit = { id, project_id, previous_audit_id: string|null, status, stage, error, commit_sha,
          created_at, started_at, finished_at, workspace_available: boolean, summary: AuditSummary }

Finding = { id, fingerprint, tool, rule_id,
            category: "security"|"architecture"|"code_quality"|"reliability"|"maintainability",
            severity: "critical"|"high"|"medium"|"low"|"info", confidence: "high"|"medium"|"low",
            kind: "objective"|"subjective", principle: string|null, title,
            file: string|null, line: number|null, end_line: number|null,
            evidence, explanation, impact, remediation, references: string[],
            has_fix: boolean,   // a fix proposal was already generated (GET /audits/{id}/fixes)
            fixable: boolean }  // a deterministic fixer exists; otherwise "Suggest fix" needs AI consent

FileContent = { path, language: string|null, content, truncated: boolean,
                symbols: Symbol[], findings: Finding[] }
Symbol = { name, kind: "class"|"function"|"method"|"arrow", line, end_line,
           params?, complexity?, methods?, parent? }
```

### `AuditSummary` (see `docs/sample-audit-summary.json` for a real example)

```ts
{
  stack: { languages: {name, files, lines|null}[], frameworks: string[], test_frameworks: string[],
           databases: string[], package_managers: string[], manifests: string[], containerized: boolean },
  inventory: { total_files, source_files, total_lines, skipped_large_files,
               tree: {path, files, lines, tests}[] },
  entry_points: {file: string|null, kind, reason}[],
  files: {path, language, lines, is_test, functions, classes, fan_in?, fan_out?, instability?}[],
  symbols: Record<path, Symbol[]>,
  architecture: { edges: number, cycles: string[][], external_dependencies: {name, imports}[],
                  graph: { directories: {nodes: {id, files}[], edges: {source, target, weight}[]},
                           files: {truncated, nodes: {id, group, test}[], edges: {source, target}[]} } },
  quality: { functions, classes, avg_complexity, complex_functions, long_functions,
             hotspots: {file, name, line, complexity, lines}[], thresholds: Record<string, number> },
  testing: { test_files, source_files, test_lines, source_lines, frameworks: string[],
             referenced_modules, untested_modules: {file, lines}[], static_coverage_pct: number|null,
             method: string,
             run?: null | { status: "running"|"passed"|"failed"|"timeout"|"skipped", reason?, runtime?,
                            counts?: Record<string, number>, coverage?: {percent, covered_lines, statements}|null,
                            test?: {exit_code, timed_out, duration_s, output}, isolation?, started_at, finished_at } },
  data_flow: { routes: {method, path, file, line, handler}[], data_access: string[],
               external_calls: string[], flows: {from, to, path: string[], kind}[], method: string },
  design?: { models: {name, file, line, orm, fields: string[], relations: {field, target, kind}[]}[],
             models_total, orms: string[], migrations: string[],
             api: { endpoints: {method, path, file, line, handler}[], count, by_method: Record<string, n>,
                    mutating_endpoints, unauth_candidates, unauth_findings_shown,
                    global_auth_middleware_detected: boolean },
             method: string },   // absent on audits created before the design analyzer
  scanners: {name, status: "ok"|"skipped"|"failed", version, duration_s, message, findings}[],
  suppressions?: { honoured: false, files: {file, scanner}[], inline: Record<marker, n>,
                   examples: {file, line, marker}[], total, note },  // repo suppression directives (ignored)
  scores: { overall: number|null, grade,            // null / "N/A" when no category could be analysed
            uncapped_overall: number|null, caps: {reason: "critical"|"incomplete", max, note}[],
            complete: boolean, not_analysed: Category[],  // these four are absent on older audits
            categories: Record<Category, {label, score: number|null, grade, weight, deduction,
              status: "scored"|"incomplete"|"not_analysed", note, effective_weight,
              merged_duplicates, counts: Record<Severity, number>}>,
            methodology: {summary, severity_points, confidence_factor, weights, caps, formula,
              limitations: string[]} },
  counts: { total, by_severity: Record<Severity, n>, by_category: Record<Category, n> },
  overview: { paragraphs: string[], largest_areas: {path, files, lines}[], generated_by: "deterministic" },
  comparison: null | { previous_audit_id, previous_score: number|null, resolved, new, persisting,
                       resolved_findings: {title, severity, file, category}[] }
}
```

## Remediation

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/findings/{id}/fix?use_ai=false` | – | `201 Fix`. Deterministic fixer first; if none exists falls back to AI (requires consent, else 403). `use_ai=true` forces AI. |
| GET | `/audits/{id}/fixes` | – | `Fix[]` |
| PATCH | `/fixes/{id}` | `{status: "approved"\|"rejected"\|"pending"}` | `Fix` |
| POST | `/audits/{id}/pull-request` | `{github_token, title?, confirm: true}` | `201 PullRequest` — GitHub projects only; token is never stored |
| GET | `/audits/{id}/pull-requests` | – | `PullRequest[]` |

```ts
Fix = { id, finding_id, file, diff /* unified diff */, rationale, source: "deterministic"|"ai",
        generator, caveats: string[], status: "pending"|"approved"|"rejected", created_at }
PullRequest = { id, url, branch, fix_ids: string[], created_at }
```

## AI (consent-gated)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/ai/status` | – | `{provider: "anthropic"\|"openai"\|"none", configured: boolean, model}` |
| POST | `/audits/{id}/explain` | `{kind, target?, refresh?}` | `AIArtifact` (403 without consent, 503 not configured) |
| GET | `/audits/{id}/explanations` | – | `AIArtifact[]` (cached results) |

`kind` / `target` / `content` shape:

| kind | target | content |
|---|---|---|
| `overview` | – | `{summary, architecture, data_flow: string[], key_modules: {path, role}[], design_decisions: {decision, evidence, confidence}[], risks: string[]}` |
| `file` | `path` | `{purpose, how_it_works: string[], key_symbols: {name, explanation}[], dependencies, gotchas: string[]}` |
| `symbol` | `path#name` | `{purpose, inputs, outputs, steps: string[], side_effects: string[], edge_cases: string[]}` |
| `questions` | – | `{questions: {question, why_it_matters, answer, related_files: string[], difficulty}[]}` |
| `finding` | finding id | `{plain_explanation, failure_or_attack_scenario, likely_false_positive, false_positive_reasoning, fix_steps: string[]}` |

`AIArtifact = {id, kind, target, provider, model, content, created_at}`

## Health

`GET /api/health` → `{status: "ok"}`

### `GET /api/audits/{id}/status`

A small payload for polling while an audit or a sandboxed test run is in progress (the full
`GET /api/audits/{id}` includes the summary, which can be megabytes). Owner-scoped like every
audit route (404 for others).

```
{ id, status, stage, error, finished_at, test_run: TestRun | null }
```
