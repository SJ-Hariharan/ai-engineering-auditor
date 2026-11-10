"""Open a pull request with approved fixes on a NEW branch.

Never pushes to an existing branch. Before writing, every target file on the
base branch is compared with the audited copy; if anything changed, nothing is
written and the user is asked to re-run the audit.
"""

from __future__ import annotations

import base64
import time
from urllib.parse import quote

import httpx

API = "https://api.github.com"


class PRError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _client(token: str) -> httpx.Client:
    return httpx.Client(base_url=API, timeout=30, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ai-engineering-auditor"})


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code in (401, 403):
        raise PRError(403, f"GitHub denied {what}. The token needs Contents and Pull requests "
                           "write access to this repository.")
    if r.status_code == 404:
        raise PRError(404, f"GitHub could not find {what} (or the token cannot see it).")
    if r.status_code >= 400:
        raise PRError(502, f"GitHub error while {what}: {r.status_code}")
    return r.json() if r.content else {}


def create_pull_request(*, token: str, repo_url: str, base_branch: str | None, files: dict[str, tuple[str, str]],
                        title: str, body: str, branch_hint: str) -> tuple[str, str]:
    """files: path -> (audited_content, new_content). Returns (pr_url, branch)."""
    owner, repo = repo_url.rstrip("/").split("/")[-2:]
    slug = f"/repos/{quote(owner)}/{quote(repo)}"
    with _client(token) as gh:
        meta = _check(gh.get(slug), "the repository")
        base = base_branch or meta["default_branch"]
        ref = _check(gh.get(f"{slug}/git/ref/heads/{quote(base, safe='')}"), f"branch {base}")
        base_sha = ref["object"]["sha"]

        blob_shas: dict[str, str] = {}
        for path, (audited, _) in files.items():
            cur = _check(gh.get(f"{slug}/contents/{quote(path)}", params={"ref": base_sha}), path)
            remote = base64.b64decode(cur.get("content", "")).decode("utf-8", "replace")
            if remote != audited:
                raise PRError(409, f"{path} changed on {base} since this audit. Re-run the audit "
                                   "and regenerate the fixes.")
            blob_shas[path] = cur["sha"]

        branch = f"auditor/{branch_hint}-{int(time.time())}"
        _check(gh.post(f"{slug}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha}),
               "creating the branch")
        for path, (_, new) in files.items():
            _check(gh.put(f"{slug}/contents/{quote(path)}", json={
                "message": f"fix: apply audited remediation to {path}",
                "content": base64.b64encode(new.encode()).decode(),
                "sha": blob_shas[path], "branch": branch}), f"updating {path}")
        pr = _check(gh.post(f"{slug}/pulls", json={"title": title, "head": branch, "base": base,
                                                    "body": body}), "opening the pull request")
        return pr["html_url"], branch
