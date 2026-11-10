"""Scan repos/<name> for 'GT:id|category|cwe|detect' and 'SAFE:id|category' markers; write repos/<name>/../ground_truth/<name>.json.
The GT line is the line immediately AFTER the marker line. Manual items live in MANUAL below (files that cannot hold comments)."""
import json, re, pathlib
HERE = pathlib.Path(__file__).parent
REPOS = ["vuln_py", "vuln_js", "secrets_repo", "arch_repo", "clean_repo"]
ALT = {  # arch items: finding may legitimately be reported on any file of the group (line ignored)
    "py_cycle2": ["pypkg/a.py", "pypkg/b.py"], "py_cycle3": ["pypkg/c.py", "pypkg/d.py", "pypkg/e.py"],
    "ts_cycle2": ["tsapp/src/lib/x.ts", "tsapp/src/lib/y.ts"], "ts_cycle3": ["tsapp/src/lib/p.ts", "tsapp/src/lib/q.ts", "tsapp/src/lib/r.ts"],
    "py_duplicate": ["pypkg/dup1.py", "pypkg/dup2.py"],
}
LINE_AGNOSTIC_CATS = {"circular-dependency", "duplicate-code", "coupling-hub"}
MANUAL = {
    "secrets_repo": [{"id": "json_fixture_token", "file": "fixtures/sample_data.json", "line": 2, "category": "hardcoded-secret", "cwe": "CWE-798", "expected_detect": True}],
    "arch_repo": [{"id": "arch_no_tests", "file": None, "line": None, "category": "no-tests", "cwe": "NA", "expected_detect": True}],
}
(HERE / "ground_truth").mkdir(exist_ok=True)
for name in REPOS:
    root = HERE / "repos" / name
    items, safe = [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file(): continue
        rel = str(p.relative_to(root))
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            m = re.search(r"GT:([\w]+)\|([\w-]+)\|([\w-]+)\|([\w-]+)", line)
            if m:
                det = m.group(4).startswith("yes")
                it = {"id": m.group(1), "file": rel, "line": i + 1, "category": m.group(2), "cwe": m.group(3), "expected_detect": det}
                if m.group(1) in ALT: it["alt_files"] = ALT[m.group(1)]
                if m.group(2) in LINE_AGNOSTIC_CATS or m.group(1) in ALT: it["line_agnostic"] = True
                items.append(it); continue
            m = re.search(r"SAFE:([\w]+)\|([\w-]+)", line)
            if m: safe.append({"id": m.group(1), "file": rel, "line": i + 1, "category": m.group(2)})
    items += [dict(x) for x in MANUAL.get(name, [])]
    (HERE / "ground_truth" / f"{name}.json").write_text(json.dumps({"repo": name, "planted": items, "safe_lookalikes": safe}, indent=1))
    print(name, len(items), "planted", len(safe), "safe")
