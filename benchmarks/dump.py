import json,sys
for n in sys.argv[1:]:
    d=json.load(open(f"results/{n}.json")); print("==",n,d["scores"])
    for f in sorted(d["findings"],key=lambda f:(f["file"] or "",f["line"] or 0)):
        print(f'{f["file"]}:{f["line"]} {f["tool"]}/{f["rule_id"]} {f["category"]} {f["severity"]}/{f["confidence"]} | {f["title"][:70]}')
