import type { Category, Finding, Severity } from "./types";

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

export const SEVERITY_RANK: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

/** Most severe level among the findings ("info" when the list is empty). */
export function worstSeverity(fs: Pick<Finding, "severity">[]): Severity {
  return fs.reduce<Severity>((a, f) => (SEVERITY_RANK[f.severity] < SEVERITY_RANK[a] ? f.severity : a), "info");
}

export const CATEGORY_LABEL: Record<Category, string> = {
  security: "Security",
  reliability: "Testing & Reliability",
  architecture: "Architecture",
  code_quality: "Code Quality",
  maintainability: "Maintainability",
};

export const STAGES = [
  "ingestion",
  "inventory",
  "parsing",
  "architecture",
  "design",
  "quality",
  "testing",
  "security",
  "scoring",
] as const;

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  return formatDate(iso);
}

export function fmtScore(n: number | null | undefined): string {
  return n == null ? "-" : n.toFixed(1);
}

export function fmtNum(n: number | null | undefined): string {
  return n == null ? "-" : n.toLocaleString();
}

export function gradeOf(score: number): string {
  if (score >= 90) return "A";
  if (score >= 80) return "B";
  if (score >= 70) return "C";
  if (score >= 55) return "D";
  return "F";
}

export function repoName(url: string | null): string {
  if (!url) return "";
  return url.replace(/^https?:\/\/(www\.)?github\.com\//, "").replace(/\.git$/, "");
}

/** Link to the code viewer of an audit at a given file/line. */
export function codeHref(auditId: string, file: string, line?: number | null): string {
  const q = new URLSearchParams({ tab: "code", file });
  if (line) q.set("line", String(line));
  return `/audits/${encodeURIComponent(auditId)}?${q.toString()}`;
}

export function tabHref(auditId: string, tab: string): string {
  return `/audits/${encodeURIComponent(auditId)}?tab=${tab}`;
}
