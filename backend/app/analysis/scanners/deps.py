"""Dependency vulnerabilities (OSV-Scanner) and config/dependency scanning (Trivy).

Both tools send package names and versions to vulnerability databases; no source
code leaves the worker. Results are grouped per package@version and de-duplicated
between the two tools.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.analysis.common import RawFinding
from app.analysis.scanners.base import SCANNER_CONFIG_DIR, ScannerResult, cvss_to_severity, timed
from app.core.config import Settings
from app.sandbox.process import run_tool

SEV_ORDER = ["critical", "high", "medium", "low", "info"]
TRIVY_SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low",
             "UNKNOWN": "medium"}


def _version_key(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-+]", v)[:5])


def _dep_finding(tool: str, ecosystem: str, name: str, version: str, manifest: str,
                 vulns: list[tuple[str, str, str]], fixed: list[str]) -> RawFinding:
    severity = min((v[1] for v in vulns), key=SEV_ORDER.index)
    fix_to = max(fixed, key=_version_key) if fixed else None
    listing = "\n".join(f"• {vid} [{sev}] {summary[:110]}" for vid, sev, summary in vulns[:12])
    more = f"\n… and {len(vulns) - 12} more" if len(vulns) > 12 else ""
    return RawFinding(
        tool=tool, rule_id="vulnerable-dependency", category="security", severity=severity,
        confidence="high", kind="objective",
        title=f"{name} {version} has {len(vulns)} known vulnerabilit{'y' if len(vulns) == 1 else 'ies'}",
        file=manifest, evidence=f"{ecosystem} package {name}@{version}\n{listing}{more}",
        explanation="The installed version matches published advisories in the OSV/GitHub/NVD "
                    "databases. Whether each one is exploitable depends on how the package is used.",
        impact="Known, documented vulnerabilities are the easiest for attackers to exploit at scale.",
        remediation=(f"Upgrade {name} to {fix_to} or later" if fix_to else
                     f"No fixed version is published yet for {name}; consider an alternative or "
                     "mitigate the affected functionality") + ", then re-run the audit.",
        references=[f"https://osv.dev/vulnerability/{vulns[0][0]}"],
        fingerprint_key=f"{ecosystem.lower()}|{name.lower().replace('_', '-')}|{_norm_version(version)}")


def _norm_version(v: str) -> str:
    while v.endswith(".0") and v.count(".") > 0:
        v = v[:-2]
    return v


def run_osv(root: Path, settings: Settings) -> ScannerResult:
    def _scan(result: ScannerResult) -> None:
        if settings.offline:
            result.status = "skipped"
            result.message = "Offline mode: vulnerability database lookups disabled"
            return
        argv = ["osv-scanner", "scan", "source", "-r", "--format", "json", "--allow-no-lockfiles",
                # SEC-01: override any osv-scanner.toml in the repo (it can ignore vulnerabilities),
                # and don't honour .gitignore files: OSV reads them even outside a git repository,
                # including the repo's own and any in folders *above* the workspace, which made it
                # silently report nothing (e.g. a lockfile listed in .gitignore).
                "--no-ignore", "--config", str(SCANNER_CONFIG_DIR / "osv-scanner.toml"), "."]
        res = run_tool(argv, cwd=root, timeout=settings.scanner_timeout_seconds)
        if res.timed_out:
            raise TimeoutError("osv-scanner timed out")
        if res.returncode == 128 or not res.stdout.strip():
            result.message = "No supported dependency manifests or lockfiles found"
            return
        if res.returncode not in (0, 1):
            raise RuntimeError(res.stderr.strip()[-300:] or f"exit code {res.returncode}")
        data = json.loads(res.stdout)
        for src in data.get("results", []):
            manifest = str(Path(src["source"]["path"]).resolve().relative_to(root.resolve()))
            for pkg in src.get("packages", []):
                info = pkg["package"]
                group_sev = {}
                for g in pkg.get("groups", []):
                    try:
                        score = float(g.get("max_severity") or "nan")
                        sev = cvss_to_severity(score if score == score else None)
                    except ValueError:
                        sev = "medium"
                    for vid in g.get("ids", []):
                        group_sev[vid] = sev
                vulns, fixed = [], []
                for v in pkg.get("vulnerabilities", []):
                    sev = group_sev.get(v["id"]) or _ghsa_sev(v)
                    vulns.append((v["id"], sev, v.get("summary") or v.get("details", "")[:120]))
                    for aff in v.get("affected", []):
                        for rng in aff.get("ranges", []):
                            fixed += [e["fixed"] for e in rng.get("events", []) if "fixed" in e]
                if vulns:
                    result.findings.append(_dep_finding("osv-scanner", info.get("ecosystem", ""),
                                                        info["name"], info.get("version", "?"),
                                                        manifest, vulns, fixed))

    return timed("osv-scanner", "osv-scanner", ["--version"], _scan)


def _ghsa_sev(v: dict) -> str:
    raw = str((v.get("database_specific") or {}).get("severity", "")).upper()
    return {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "medium", "LOW": "low"}.get(raw, "medium")


def run_trivy(root: Path, settings: Settings) -> ScannerResult:
    def _scan(result: ScannerResult) -> None:
        argv = ["trivy", "fs", "--scanners", settings.trivy_scanners, "--format", "json", "--quiet",
                # SEC-01: ignore the repo's .trivyignore and trivy.yaml (they can hide findings).
                "--ignorefile", "", "--config", "",
                "--skip-version-check", "--timeout", f"{settings.scanner_timeout_seconds}s"]
        if settings.offline:
            argv += ["--skip-db-update", "--skip-check-update", "--offline-scan"]
        argv.append(".")
        res = run_tool(argv, cwd=root, timeout=settings.scanner_timeout_seconds + 30)
        if res.timed_out:
            raise TimeoutError("trivy timed out")
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip()[-300:] or f"exit code {res.returncode}")
        data = json.loads(res.stdout or "{}")
        for r in data.get("Results", []) or []:
            target = r.get("Target", "")
            by_pkg: dict[tuple[str, str], list[dict]] = {}
            for v in r.get("Vulnerabilities") or []:
                by_pkg.setdefault((v["PkgName"], v.get("InstalledVersion", "?")), []).append(v)
            for (name, version), vs in by_pkg.items():
                vulns = [(v["VulnerabilityID"], TRIVY_SEV.get(v.get("Severity", ""), "medium"),
                          v.get("Title") or "") for v in vs]
                fixed = [f.strip() for v in vs for f in (v.get("FixedVersion") or "").split(",") if f.strip()]
                result.findings.append(_dep_finding("trivy", r.get("Type", ""), name, version,
                                                    target, vulns, fixed))
            for m in r.get("Misconfigurations") or []:
                if m.get("Status") != "FAIL":
                    continue
                cause = m.get("CauseMetadata") or {}
                lines = ((cause.get("Code") or {}).get("Lines") or [])
                result.findings.append(RawFinding(
                    tool="trivy", rule_id=m.get("ID", "misconfig"), category="security",
                    severity=TRIVY_SEV.get(m.get("Severity", ""), "medium"), confidence="high",
                    kind="objective", title=m.get("Title", "Misconfiguration"), file=target,
                    line=cause.get("StartLine"), end_line=cause.get("EndLine"),
                    evidence="\n".join(ln.get("Content", "") for ln in lines[:6]) or m.get("Message", ""),
                    explanation=f"{m.get('Description', '')} {m.get('Message', '')}".strip(),
                    impact="Insecure infrastructure configuration widens the attack surface or "
                           "the blast radius of a compromise.",
                    remediation=m.get("Resolution", ""),
                    references=[m["PrimaryURL"]] if m.get("PrimaryURL") else [],
                    fingerprint_key=f"{target}|{m.get('ID')}"))

    return timed("trivy", "trivy", ["--version"], _scan)


def merge_dependency_findings(osv: list[RawFinding], trivy: list[RawFinding]) -> list[RawFinding]:
    """Trivy dependency findings not already reported by OSV-Scanner for the same package@version."""
    seen = {f.fingerprint_key.split("|", 1)[1] for f in osv if f.rule_id == "vulnerable-dependency"}
    return [f for f in trivy if f.rule_id == "vulnerable-dependency"
            and f.fingerprint_key.split("|", 1)[1] not in seen]


def classify_dependency_findings(findings: list[RawFinding], runtime: set[str], dev: set[str]) -> None:
    """Adjust severity/confidence by how the package is used, and say so in the finding.

    * declared only as a dev/test dependency → one severity level lower (not shipped to users)
    * not declared directly (transitive)     → confidence 'medium' (may only be pulled in by tooling)
    """
    from app.analysis.inventory import norm_pkg

    for f in findings:
        if f.rule_id != "vulnerable-dependency":
            continue
        name = norm_pkg(f.fingerprint_key.split("|")[1])
        if name in runtime:
            f.explanation += " This is a direct runtime dependency."
        elif name in dev:
            f.severity = SEV_ORDER[min(SEV_ORDER.index(f.severity) + 1, len(SEV_ORDER) - 1)]
            f.title += " (dev dependency)"
            f.explanation += (" It is declared only as a development/test dependency, so it is usually "
                              "not shipped to users; severity was lowered one level.")
        else:
            f.confidence = "medium"
            f.title += " (transitive)"
            f.explanation += (" It is not declared directly; it is pulled in by another package and "
                              "may only be used by development tooling. Confidence is medium.")
