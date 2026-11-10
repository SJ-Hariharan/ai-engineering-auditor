"""Deterministic stratified sample of 10 findings per real repo (round-robin over rules, seed 7)."""
import json, random, collections, sys
rnd = random.Random(7)
out = {}
for n in ["itsdangerous", "full-stack-fastapi-template"]:
    d = json.load(open(f"results/{n}.json"))
    by = collections.defaultdict(list)
    for f in d["findings"]: by[(f["tool"], f["rule_id"])].append(f)
    keys = sorted(by); pick = []
    for k in keys: rnd.shuffle(by[k])
    i = 0
    while len(pick) < 10 and any(by.values()):
        for k in keys:
            if by[k] and len(pick) < 10: pick.append(by[k].pop())
    out[n] = [{k: f[k] for k in ("tool", "rule_id", "severity", "confidence", "file", "line", "title", "evidence")} for f in pick]
json.dump(out, open("results/real_sample.json", "w"), indent=1)
for n, l in out.items():
    print("=====", n)
    for j, f in enumerate(l):
        print(j, f["tool"], f["rule_id"], f["severity"], f["file"], f["line"], "|", f["title"][:90]); print("   EV:", f["evidence"][:400].replace("\n", "\n      "))
