#!/bin/bash
# Re-run the detection benchmark. See DETECTION_BENCHMARK.md at the project root.
set -e
B="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$B/real"
[ -d "$B/real/itsdangerous" ] || git clone --depth 1 https://github.com/pallets/itsdangerous "$B/real/itsdangerous"
[ -d "$B/real/full-stack-fastapi-template" ] || git clone --depth 1 https://github.com/fastapi/full-stack-fastapi-template "$B/real/full-stack-fastapi-template"
cd "$B" && python3 gen_secrets_repo.py && python3 gen_arch_repo.py && python3 build_ground_truth.py
cd "$B/../backend"
uv run python "$B/run_bench.py" vuln_py vuln_js secrets_repo arch_repo clean_repo probe_alias_root probe_sqli_concat real/itsdangerous real/full-stack-fastapi-template
cd "$B" && python3 evaluate.py && python3 sample_real.py >/dev/null && python3 verify_unresolved.py && python3 make_report.py
