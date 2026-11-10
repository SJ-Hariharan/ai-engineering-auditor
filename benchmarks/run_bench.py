"""Run the analyzer on a repo; dump findings+summary to results/<name>.json.
Usage: uv run python run_bench.py <name> [<abs repo path>]"""
import sys, json, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backend"))
from pathlib import Path
from app.analysis.pipeline import run_analysis
from app.core.config import Settings
HERE = Path(__file__).parent
names = sys.argv[1:] or ["vuln_py", "vuln_js", "secrets_repo", "arch_repo", "clean_repo"]
(HERE / "results").mkdir(exist_ok=True)
for name in names:
    repo = HERE / name if "/" in name else HERE / "repos" / name
    name = name.split("/")[-1]
    t = time.time()
    r = run_analysis(repo, Settings(offline=False))
    sc = r.summary["scores"]
    out = {"findings": r.findings, "scores": {k: sc[k] for k in ("overall", "grade")} |
           {"uncapped_overall": sc.get("uncapped_overall"), "caps": [c["reason"] for c in sc.get("caps", [])],
            "not_analysed": sc.get("not_analysed", []),
            "merged_duplicates": sum(c.get("merged_duplicates", 0) for c in sc["categories"].values())} |
           {"categories": {c: v["score"] for c, v in r.summary["scores"]["categories"].items()}},
           "scanners": r.summary["scanners"], "counts": r.summary["counts"], "seconds": round(time.time() - t, 1)}
    (HERE / "results" / f"{name}.json").write_text(json.dumps(out, indent=1, default=str))
    print(name, len(r.findings), "findings", out["scores"]["overall"], [(s.get("name"), s.get("status")) for s in r.summary["scanners"]], out["seconds"], "s")
