"""Match findings (results/<repo>.json) against ground_truth/<repo>.json; write results/eval.json.
Matching: same file, |line diff| <= 3, and rule in RULES[category] (line ignored for graph/duplicate/no-tests categories)."""
import json, pathlib, collections
HERE = pathlib.Path(__file__).parent
REPOS = ["vuln_py", "vuln_js", "secrets_repo", "arch_repo", "clean_repo"]
GIT = {"gitleaks"}
RULES = {
 "sql-injection": {"py-sql-injection-string-build", "js-sql-injection-string-build"},
 "command-injection": {"py-command-injection-shell", "js-command-injection"},
 "code-injection": {"py-eval-exec", "js-eval"},
 "insecure-deserialization": {"py-unsafe-deserialization"},
 "path-traversal": {"py-path-traversal-request-data", "js-path-traversal"},
 "ssrf": {"py-ssrf-request-data", "js-ssrf"},
 "xss": {"py-template-injection", "py-markup-unescaped", "js-xss-inner-html", "js-react-dangerously-set-inner-html", "js-reflected-xss-express"},
 "tls-verification": {"py-tls-verification-disabled", "js-tls-verification-disabled"},
 "debug-enabled": {"py-flask-debug-enabled"},
 "jwt-verification": {"py-jwt-signature-not-verified", "js-jwt-decode-without-verify"},
 "weak-hash": {"py-weak-hash"},
 "hardcoded-secret": {"py-hardcoded-secret-key", "GITLEAKS"},
 "cors-misconfig": {"py-cors-wildcard-with-credentials", "js-cors-wildcard-with-credentials"},
 "missing-auth": {"api-unauthenticated-mutation"},
 "n-plus-one": {"db-query-in-loop"},
 "open-redirect": {"js-open-redirect"},
 "weak-random": {"js-weak-random-token"},
 "secret-exposed-to-browser": {"js-secret-exposed-to-browser", "GITLEAKS"},
 "insecure-cookie": {"js-insecure-cookie"},
 "prototype-pollution": set(), "nosql-injection": set(),
 "circular-dependency": {"circular-dependency"}, "unresolved-import": {"unresolved-import"}, "coupling-hub": {"coupling-hub", "high-fan-out"},
 "large-class": {"large-class"}, "high-complexity": {"high-complexity"}, "deep-nesting": {"deep-nesting"}, "long-function": {"long-function"},
 "duplicate-code": {"duplicate-code"}, "bare-except": {"bare-except"}, "swallowed-exception": {"swallowed-exception"},
 "empty-catch": {"empty-catch"}, "many-parameters": {"many-parameters"}, "no-tests": {"no-tests"},
}
def rule_ok(cat, f):
    rs = RULES.get(cat, set())
    return f["rule_id"] in rs or ("GITLEAKS" in rs and f["tool"] == "gitleaks")
def match(g, f):
    if not rule_ok(g["category"], f): return False
    files = g.get("alt_files") or [g["file"]]
    if g["file"] is None: return True
    if f["file"] not in files: return False
    if g.get("line_agnostic"): return True
    tol = 1 if g["category"] == "unresolved-import" else 3
    return f["line"] is not None and abs(f["line"] - g["line"]) <= tol
labels = json.load(open(HERE / "labels.json")) if (HERE / "labels.json").exists() else {}
out = {}
for repo in REPOS:
    res = json.load(open(HERE / "results" / f"{repo}.json"))
    gt = json.load(open(HERE / "ground_truth" / f"{repo}.json"))
    fs = res["findings"]; used = set(); rows = []
    for g in gt["planted"]:
        cands = [(abs((f["line"] or 0) - (g["line"] or 0)), i) for i, f in enumerate(fs) if i not in used and match(g, f)]
        hit = None
        if cands:
            _, i = min(cands); used.add(i); hit = fs[i]
        rows.append({"gt": g, "detected": hit is not None, "finding": None if not hit else {k: hit[k] for k in ("tool", "rule_id", "file", "line", "severity", "confidence")}})
    unmatched = []
    for i, f in enumerate(fs):
        if i in used: continue
        key = f'{repo}|{f["file"]}|{f["line"]}|{f["rule_id"]}'
        wkey = f'{repo}|{f["file"]}|*|{f["rule_id"]}'
        safe_hit = [s["id"] for s in gt["safe_lookalikes"] if s["file"] == f["file"] and f["line"] and 0 <= f["line"] - s["line"] <= 1]
        lab = labels.get(key) or labels.get(wkey)
        if safe_hit and not lab: lab = {"label": "FP", "reason": f"fires on SAFE look-alike {safe_hit[0]}"}
        unmatched.append({"key": key, "finding": {k: f[k] for k in ("tool", "rule_id", "category", "severity", "confidence", "file", "line", "title")}, "label": (lab or {}).get("label", "UNLABELED"), "reason": (lab or {}).get("reason", ""), "safe_hit": safe_hit})
    out[repo] = {"rows": rows, "unmatched": unmatched, "scores": res["scores"], "n_findings": len(fs), "counts": res["counts"], "seconds": res["seconds"]}
json.dump(out, open(HERE / "results" / "eval.json", "w"), indent=1)
for repo, o in out.items():
    exp = [r for r in o["rows"] if r["gt"]["expected_detect"]]
    print(f"{repo}: planted(expected)={len(exp)} detected={sum(r['detected'] for r in exp)} | unmatched={len(o['unmatched'])} unlabeled={sum(u['label']=='UNLABELED' for u in o['unmatched'])}")
    for r in o["rows"]:
        if not r["detected"]: print("   MISS", r["gt"]["id"], r["gt"]["file"], r["gt"]["line"], "(expected)" if r["gt"]["expected_detect"] else "(known gap)")
