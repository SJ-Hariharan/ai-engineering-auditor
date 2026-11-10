"""For every unresolved-import finding on full-stack-fastapi-template, check on disk (read-only, no code execution)
whether the target exists under frontend/src (the real tsconfig alias @/* -> ./src/*)."""
import json, pathlib, collections
root = pathlib.Path("real/full-stack-fastapi-template")
d = json.load(open("results/full-stack-fastapi-template.json"))
exts = ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx"]
c = collections.Counter(); bad = []
for f in d["findings"]:
    if f["rule_id"] != "unresolved-import": continue
    spec = f["title"].split("'")[1]
    if spec.startswith("@/"):
        ok = any((root / "frontend/src" / (spec[2:] + e)).is_file() for e in exts)
        c["alias @/ target exists (FP)" if ok else "alias @/ target missing (true)"] += 1
        if not ok: bad.append(spec)
    elif spec.startswith("/assets/"):
        ok = (root / "frontend/src" / spec.lstrip("/")).is_file() or (root / "frontend/public" / spec.lstrip("/")).is_file()
        c["/assets exists (FP, vite)" if ok else "/assets missing"] += 1
    else:
        ok = (root / "frontend/src" / spec.lstrip("./")).is_file()
        c["relative exists (FP)" if ok else "relative missing"] += 1
print(dict(c), bad[:5])
