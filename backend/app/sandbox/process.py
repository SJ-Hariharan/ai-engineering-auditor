"""Hardened subprocess runner for *static* tools (scanners, git).

These tools read repository files but never execute repository code. They are
still treated carefully:
  * the environment is replaced with a minimal allow-list, so API keys,
    database URLs and other secrets in the server environment are never visible;
  * a wall-clock timeout kills the whole process group;
  * CPU-time and file-size rlimits are applied on POSIX;
  * the command is passed as an argv list (never through a shell).
"""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")


@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    aborted: bool = False  # stopped because `abort_if` returned True


def minimal_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin")
    env.setdefault("LANG", "C.UTF-8")
    if extra:
        env.update(extra)
    return env


def _limits(cpu_seconds: int) -> None:  # pragma: no cover - runs in child
    os.setsid()
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
    two_gb = 2 * 1024**3
    resource.setrlimit(resource.RLIMIT_FSIZE, (two_gb, two_gb))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_tool(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 300,
    env_extra: dict[str, str] | None = None,
    max_output_bytes: int = 64 * 1024 * 1024,
    abort_if: Callable[[], bool] | None = None,
) -> ProcessResult:
    """Run argv. ``abort_if`` is polled about once a second; returning True kills the process
    (e.g. a clone that grows past the size limit, SEC-05)."""
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        env=minimal_env(env_extra),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=lambda: _limits(timeout * 2),  # noqa: PLW1509
    )
    def kill() -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()

    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            kill()
            return ProcessResult(-9, "", "timed out", timed_out=True)
        try:
            out, err = proc.communicate(timeout=min(remaining, 1.0) if abort_if else remaining)
            break
        except subprocess.TimeoutExpired:
            if abort_if and abort_if():
                kill()
                return ProcessResult(-9, "", "aborted", aborted=True)
    return ProcessResult(
        proc.returncode,
        out[:max_output_bytes].decode("utf-8", "replace"),
        err[-20000:].decode("utf-8", "replace"),
    )
