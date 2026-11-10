"""Run a repository's test suite inside a locked-down Docker container.

This is the ONLY place repository code is executed. Two phases:

1. install  — dependencies are installed with network access, but without
              running package install scripts (`pip --only-binary=:all:`,
              `npm ci --ignore-scripts`).
2. test     — `--network none`; the tests run with no network at all.

Both phases: throwaway copy of the source, non-root user, read-only root FS,
all capabilities dropped, no-new-privileges, CPU/memory/PID limits, wall-clock
timeout, no host environment variables. Docker unavailable → step is skipped.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.ingestion.workspace import source_dir
from app.sandbox.process import run_tool

OUTPUT_LIMIT = 20_000


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return run_tool(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15).returncode == 0


def _docker_run(image: str, work: Path, out: Path, deps: Path, command: str, *, network: bool,
                timeout: int) -> dict:
    s = get_settings()
    name = f"auditor-sbx-{uuid.uuid4().hex[:12]}"
    argv = [
        "docker", "run", "--rm", "--name", name,
        "--network", "bridge" if network else "none",
        "--cpus", str(s.sandbox_cpus), "--memory", s.sandbox_memory, "--memory-swap", s.sandbox_memory,
        "--pids-limit", str(s.sandbox_pids),
        "--read-only", "--tmpfs", "/tmp:rw,size=256m",  # noqa: S108 - container-private tmpfs
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
        "-e", "HOME=/tmp", "-e", "CI=true", "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1", "-e", "npm_config_cache=/tmp/.npm",
        "-v", f"{work}:/work:rw", "-v", f"{out}:/out:rw",
        # Dependencies are writable only during the install phase.
        "-v", f"{deps}:/deps:{'rw' if network else 'ro'}", "-w", "/work",
        image, "sh", "-c", command,
    ]
    if s.sandbox_runtime:
        argv[3:3] = ["--runtime", s.sandbox_runtime]
    start = time.monotonic()
    res = run_tool(argv, timeout=timeout)
    if res.timed_out:
        run_tool(["docker", "kill", name], timeout=20)
    return {"exit_code": res.returncode, "timed_out": res.timed_out,
            "duration_s": round(time.monotonic() - start, 1),
            "output": (res.stdout + "\n" + res.stderr)[-OUTPUT_LIMIT:]}


def _plan(src: Path, stack: dict) -> dict | None:
    if (src / "package.json").is_file():
        pkg = json.loads((src / "package.json").read_text("utf-8", "replace") or "{}")
        if "test" in (pkg.get("scripts") or {}):
            install = "npm ci --ignore-scripts --no-audit --no-fund" if (src / "package-lock.json").is_file() \
                else "npm install --ignore-scripts --no-audit --no-fund"
            return {"runtime": "node", "image": get_settings().sandbox_node_image,
                    "install": install, "test": "npm test --silent 2>&1"}
    py_markers = ("pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg", "tox.ini", "requirements.txt")
    if any((src / m).is_file() for m in py_markers) or "pytest" in stack.get("test_frameworks", []):
        reqs = " ".join(f"-r {p.relative_to(src)}" for p in sorted(src.glob("requirements*.txt"))[:3])
        install = ("python -m pip install --target /deps --only-binary=:all: -q "
                   f"pytest pytest-cov {reqs}")
        if (src / "pyproject.toml").is_file():
            install += " && (python -m pip install --target /deps --only-binary=:all: -q . || true)"
        test = ("PYTHONPATH=/deps:/work python -m pytest -q -p no:cacheprovider "
                "--cov=/work --cov-report=json:/out/coverage.json 2>&1")
        return {"runtime": "python", "image": get_settings().sandbox_python_image,
                "install": install, "test": test}
    return None


def _summarise(runtime: str, output: str) -> dict:
    counts: dict[str, int] = {}
    if runtime == "python":
        for n, label in re.findall(r"(\d+) (passed|failed|errors?|skipped)", output):
            counts[label.rstrip("s") if label.startswith("error") else label] = int(n)
    else:
        m = re.search(r"Tests?:\s+(.*)", output)  # jest / vitest style summary
        if m:
            for n, label in re.findall(r"(\d+) (passed|failed|skipped|todo)", m.group(1)):
                counts[label] = int(n)
    return counts


def run_test_suite(workspace: Path, stack: dict) -> dict:
    s = get_settings()
    now = datetime.now(UTC).isoformat()
    base = {"started_at": now, "finished_at": now}  # overwritten when tests actually run
    if not s.sandbox_enabled:
        return base | {"status": "skipped", "reason": "Sandboxed execution is disabled on this server."}
    if not docker_available():
        return base | {"status": "skipped",
                       "reason": "Docker is not available, so tests were not run. Repository code is "
                                 "never executed outside a sandbox."}
    src = source_dir(workspace)
    plan = _plan(src, stack)
    if plan is None:
        return base | {"status": "skipped", "reason": "No supported test setup found (npm `test` script or pytest)."}
    run_dir = workspace / "sandbox_run"
    shutil.rmtree(run_dir, ignore_errors=True)
    work, out, deps = run_dir / "work", run_dir / "out", run_dir / "deps"
    shutil.copytree(src, work, symlinks=False)
    out.mkdir(parents=True)
    deps.mkdir()
    for d in (run_dir, work, out, deps):
        d.chmod(0o777)  # container runs as nobody
    for p in work.rglob("*"):
        p.chmod(0o777 if p.is_dir() else 0o666)
    try:
        install = _docker_run(plan["image"], work, out, deps, plan["install"], network=True,
                              timeout=s.sandbox_timeout_seconds)
        test = _docker_run(plan["image"], work, out, deps, plan["test"], network=False,
                           timeout=s.sandbox_timeout_seconds)
        coverage = None
        cov_file = out / "coverage.json"
        if cov_file.is_file():
            try:
                totals = json.loads(cov_file.read_text())["totals"]
                coverage = {"percent": round(totals["percent_covered"], 1),
                            "covered_lines": totals["covered_lines"], "statements": totals["num_statements"]}
            except (ValueError, KeyError):
                coverage = None
        status = "timeout" if test["timed_out"] else ("passed" if test["exit_code"] == 0 else "failed")
        return base | {
            "status": status, "runtime": plan["runtime"], "image": plan["image"],
            "install": {k: install[k] for k in ("exit_code", "timed_out", "duration_s")} | {
                "output": install["output"][-4000:]},
            "test": test, "counts": _summarise(plan["runtime"], test["output"]), "coverage": coverage,
            "finished_at": datetime.now(UTC).isoformat(),
            "isolation": "docker: network=none during tests, non-root, read-only rootfs, caps dropped, "
                         f"{s.sandbox_cpus} CPU / {s.sandbox_memory} RAM / {s.sandbox_pids} PIDs, "
                         f"{s.sandbox_timeout_seconds}s timeout",
        }
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
