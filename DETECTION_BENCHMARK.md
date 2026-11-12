# Detection benchmark

Full generated report with every table: [benchmarks/BENCHMARK_REPORT.md](benchmarks/BENCHMARK_REPORT.md).
Re-run: `bash benchmarks/run_all.sh` (needs semgrep, gitleaks, osv-scanner, trivy and network access; under the
Claude sandbox it must run unsandboxed). Ground truth: `benchmarks/ground_truth/*.json`. Hand labels: `benchmarks/labels.json`.

> **Updated after the DET-10 fix.** Tables reflect the latest run. The pre-fix report is kept as
> `benchmarks/BENCHMARK_REPORT.before-det10.md`. Changes: the FastAPI template went from 295 to 87 findings (208 false
> import errors removed), the broken-alias case (DET-03) is now detected, and an OSV-Scanner `.gitignore` gap found
> while re-measuring (DET-16) is fixed.

## Method

- **Synthetic repos with planted ground truth.** Each planted issue carries an inline marker `GT:<id>|<category>`. Safe look-alikes are marked `SAFE:<id>`.
  - `vuln_py`: 34 planted issues and 13 safe look-alikes.
  - `vuln_js`: 23 planted issues (3 are known out-of-scope gaps) and 7 safe look-alikes.
  - `secrets_repo`: 10 planted secrets and 6 safe look-alikes.
  - `arch_repo`: 19 planted structural issues.
  - `clean_repo`: no planted issues, a Python package and a TS module with tests.
- **Matching.** A finding counts when it is in the same file, within ±3 lines (±1 for imports), and its rule belongs to the issue's category. Every finding that doesn't match was hand-labelled as true-but-unplanted, debatable or false positive.
- **Reality check.** Two real public repos (`pallets/itsdangerous`, `fastapi/full-stack-fastapi-template`) were analysed without ground truth. Ten findings from each were hand-labelled, and all 208 unresolved-import findings in the template were checked against the files on disk.
- **Run conditions.** All four scanners reported status `ok` in every reported run. Benchmark code was never executed.

**Limitations.** The repos are small, written by one author, with one variant per issue type. Recall measures these
variants only. The labels are the auditors' judgement, and the real-repo samples are indicative.

## Results

| Repo | Recall | Findings | Planted TP | True, unplanted | Debatable | FP | Score |
|---|---|---|---|---|---|---|---|
| vuln_py | 34/34 (100%) | 50 | 34 | 10 | 5 | 1 | 65.3 D |
| vuln_js | 17/20 (85%) | 23 | 17 | 1 | 5 | 0 | 69.4 D |
| secrets_repo | 9/10 (90%) | 12 | 9 | 3 | 0 | 0 | 68.4 D |
| arch_repo | 18/19 (95%) | 19 | 18 | 0 | 1 | 0 | 79.2 C |
| clean_repo | n/a | **0** | 0 | 0 | 0 | 0 | 100 A |
| **All synthetic** | **78/83 (94%)** | 104 | 78 | 14 | 11 | 1 | |

- **Security (vulnerabilities + secrets):** recall 60/64 (94%); precision 86% strict, 90% adjusted (90–99% depending on debatable). Was 57/64 before the DET-01 fix; no new false positives.
- **Architecture/quality/reliability:** recall 18/19 (95%); adjusted precision 100%.
- **Safe look-alikes:** 26 were planted (parameterised SQL, list-arg subprocess, `safe_load`, `literal_eval`, `verify=True`, `secure_filename`, `Depends(current_user)`, DOMPurify, `textContent`, `execFile`, `jwt.verify`, `crypto.randomBytes`, env-sourced keys, placeholders, hash/UUID constants).
  - No security rule fired on any of them.
  - One verb-based design finding landed on a safe POST route.
- **Known out-of-scope gaps:** prototype pollution (2 variants) and NoSQL injection were missed (0/3). There are no rules for them, and they are excluded from recall.

### Real repositories

| Repo | Findings | Sample of 10 (TP / debatable / FP) | Score | Notes |
|---|---|---|---|---|
| pallets/itsdangerous | 32 (was 25: identical occurrences are now all kept, E-01) | 1 / 7 / 2 (earlier sample) | 87.2 B (was 81.4 B) | 11 dependency advisories, all for dev tooling in `uv.lock`; since DET-11 they are labelled dev tooling and lowered one level, so none is critical |
| fastapi/full-stack-fastapi-template | 89 (was 295; 87 before E-01 kept identical occurrences) | 3 / 4 / 3 (pre-fix sample) | 68.6 D (was 58.4) | Before DET-10: 208 of 295 findings (70.5%) were verified-false `unresolved-import`. Now: **0** `unresolved-import` findings; reliability 86.8 (was 37.9) |

## False negatives (planted, expected, missed)

| ID | Gap | Cause | Evidence |
|---|---|---|---|
| DET-01 ✅ | SQL built with 3-operand concatenation, `"…" + x + "'"` (Python direct, Python via variable, JS) — 3 of 9 SQLi items | Rule patterns only match the 2-operand `"…" + $X` | `backend/app/analysis/rules/python.yml:16,28`; `javascript.yml` js-sql rule; probe repo `benchmarks/repos/probe_sqli_concat` | **Fixed:** 3-operand patterns added for direct and intermediate-variable queries (Python, JS/TS); all 3 items now detected.
| DET-02 | JS route without auth not reported | `GLOBAL_AUTH_RE` treats any `.use(…session…)` in the file as global auth | `backend/app/analysis/design.py:467,643` |
| DET-03 ✅ | TS alias import whose target is missing | Was treated as an npm package. **Fixed:** a prefix declared in the project's own tsconfig `paths` is internal, so a missing target is reported | `backend/app/analysis/graph.py` `JsResolver.resolve` |
| DET-04 | `fs.readFileSync("/data/" + req.query.f)` path traversal | Rule covers `sendFile`/`path.join` sinks only | `javascript.yml` js-path-traversal |
| DET-05 | express-session cookie without `secure`/`httpOnly` | Rule only matches `res.cookie(...)` | `javascript.yml` js-insecure-cookie |
| DET-06 | Database URL with an embedded password | No Semgrep rule; Gitleaks default rules don't match | — |
| DET-07 | Pure fan-in hub module | `coupling-hub` needs fan-in ≥ 8 **and** fan-out ≥ 6 (arguably by design) | `graph.py analyze_graph` |

## False positives and accuracy problems

| ID | Problem | Measured | Cause |
|---|---|---|---|
| DET-10 ✅ | **Mass unresolved-import FPs in monorepos** | Was 208/208 FPs on the FastAPI template (reliability 37.9). **Fixed; now 0** (reliability 86.8) | **Cause:** `tsconfig.json` was read only at the repo root, `/* */` comments were not stripped, and Vite `/assets/...` and CSS imports were not understood. **Fix (`graph.py` `JsResolver`):** the nearest `tsconfig*.json`/`jsconfig*.json` per file, JSONC parsing, relative `extends`, `paths` relative to `baseUrl` or the config folder, on-disk checks for non-code imports, root-absolute imports via the package's `public/`, and Vite `?raw` suffixes. 6 tests in `tests/test_import_resolution.py` |
| DET-16 ✅ | OSV-Scanner silently skipped lockfiles covered by any `.gitignore` | Found while re-measuring: `itsdangerous` showed 0 dependency findings instead of 11. A repo `.gitignore` listing `uv.lock` also hid them | OSV reads `.gitignore` files even outside a git repository, including folders *above* the workspace. In local development the workspace (`backend/var/`) is git-ignored by the project, so OSV reported nothing for every audit. **Fixed:** `--no-ignore` (`scanners/deps.py`) and a test |
| DET-11 ✅ | Dev-tooling advisories rated critical/high | itsdangerous: `uv`, `virtualenv`, `certifi`, `anyio` from `uv.lock` rated critical/high; security score 51.8 for a zero-dependency library | Dependency classification reads only `package.json`, `requirements.txt` and `pyproject.toml` (`inventory.py`); everything else is "transitive" with severity unchanged | **Fixed:** reachability from `uv.lock`, `package-lock.json` and `bun.lock`; packages reachable only through dev/test dependencies are lowered one level with medium confidence. itsdangerous: 3 criticals → 0; FastAPI template: 4 of 14 advisories reclassified, the runtime critical stays.
| DET-12 | Same secret class rated differently by file type | AWS key in `.env` is **high**; the same class in `.py`/`.yaml`/`.js` is **critical** | `gitleaks.py:49-52` lowers `.env` severity |
| DET-13 | Verb-based "unauthenticated mutation" | Flags parse-only POST routes (1 FP, 3 debatable) | `design.py` api-unauthenticated-mutation |
| DET-14 | Low-value quality noise on real code | `duplicate-code` on `@overload` stubs and import blocks; `untested-modules` on `docs/conf.py`; `naming-convention` on `_private` helpers | quality/testing heuristics |
| DET-15 | Overall score compresses severe security problems | A repo with 7 critical secrets scores 68.4 (D), the same band as one with only structural smells | Weighted mean of 5 categories; see SCORE items in RELEASE_READINESS.md. Still open: the SC-01 critical cap (79.9) only lowers scores above it, and these repos are already below it |

## Conclusion

After the DET-10 fix, the monorepo false-positive flood is gone. On code that matches its rules, detection is good: about 89% recall and 85–90% precision on security items, with no
false positives on the safe look-alikes or the clean repository.

The real-repository runs show the remaining weak points:
- dev-tooling advisories carry inflated severity;
- ~~common SQL concatenation forms are missed~~ fixed (DET-01): recall 75/83 → 78/83.

Taken together, the overall score is **not reliable enough to compare repositories**.
