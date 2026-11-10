import type {
  AIArtifact,
  AIStatus,
  Audit,
  ExplainKind,
  FileContent,
  Finding,
  Fix,
  FixStatus,
  ProjectDetail,
  Project,
  PullRequest,
  User,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const BASE = "/api";
const AUTH_PAGES = ["/login", "/register"];

/** Turn a FastAPI `{detail}` payload (string or validation list) into a message. */
function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (d && typeof d === "object" && "msg" in d) {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc)
            ? ((d as { loc: unknown[] }).loc.filter((x) => x !== "body").join("."))
            : "";
          return `${loc ? loc + ": " : ""}${String((d as { msg: unknown }).msg)}`;
        }
        return null;
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

async function request<T>(
  method: string,
  path: string,
  opts: { json?: unknown; form?: FormData; query?: Record<string, string | undefined> } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-Auditor-Client"] = "1";
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  let url = BASE + path;
  if (opts.query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(opts.query)) if (v) qs.set(k, v);
    const s = qs.toString();
    if (s) url += `?${s}`;
  }

  let res: Response;
  try {
    res = await fetch(url, { method, headers, body, credentials: "include" });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is the backend running?");
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      message = detailToMessage(data?.detail, message);
    } catch {
      /* non-JSON error body */
    }
    if (
      res.status === 401 &&
      typeof window !== "undefined" &&
      !AUTH_PAGES.includes(window.location.pathname)
    ) {
      window.location.replace("/login");
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const enc = encodeURIComponent;
/** Encode a repo-relative path segment-wise (keeps slashes). */
const encPath = (p: string) => p.split("/").map(enc).join("/");

export const api = {
  // auth
  register: (email: string, password: string) =>
    request<User>("POST", "/auth/register", { json: { email, password } }),
  login: (email: string, password: string) =>
    request<User>("POST", "/auth/login", { json: { email, password } }),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<User>("GET", "/auth/me"),

  // projects
  listProjects: () => request<Project[]>("GET", "/projects"),
  getProject: (id: string) => request<ProjectDetail>("GET", `/projects/${enc(id)}`),
  createGithubProject: (url: string, branch?: string) =>
    request<ProjectDetail>("POST", "/projects/github", {
      json: { url, ...(branch ? { branch } : {}) },
    }),
  uploadProject: (file: File, name?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    return request<ProjectDetail>("POST", "/projects/upload", { form });
  },
  updateProject: (id: string, patch: { name?: string; llm_consent?: boolean }) =>
    request<ProjectDetail>("PATCH", `/projects/${enc(id)}`, { json: patch }),
  deleteProject: (id: string) => request<void>("DELETE", `/projects/${enc(id)}`),
  rerunAudit: (projectId: string, file?: File) => {
    if (file) {
      const form = new FormData();
      form.append("file", file);
      return request<AuditBriefLike>("POST", `/projects/${enc(projectId)}/audits`, { form });
    }
    return request<AuditBriefLike>("POST", `/projects/${enc(projectId)}/audits`);
  },

  // audits
  getAudit: (id: string) => request<Audit>("GET", `/audits/${enc(id)}`),
  getFindings: (
    id: string,
    q: { category?: string; severity?: string; kind?: string; file?: string; sort?: string } = {},
  ) => request<Finding[]>("GET", `/audits/${enc(id)}/findings`, { query: q }),
  getFile: (id: string, path: string) =>
    request<FileContent>("GET", `/audits/${enc(id)}/files/${encPath(path)}`),
  runTests: (id: string) =>
    request<{ status: string }>("POST", `/audits/${enc(id)}/tests/run`),
  reportUrl: (id: string) => `${BASE}/audits/${enc(id)}/report.md`,

  // remediation
  createFix: (findingId: string, useAi = false) =>
    request<Fix>("POST", `/findings/${enc(findingId)}/fix`, {
      query: { use_ai: useAi ? "true" : undefined },
    }),
  listFixes: (auditId: string) => request<Fix[]>("GET", `/audits/${enc(auditId)}/fixes`),
  setFixStatus: (fixId: string, status: FixStatus) =>
    request<Fix>("PATCH", `/fixes/${enc(fixId)}`, { json: { status } }),
  createPullRequest: (
    auditId: string,
    body: { github_token: string; title?: string; confirm: true },
  ) => request<PullRequest>("POST", `/audits/${enc(auditId)}/pull-request`, { json: body }),
  listPullRequests: (auditId: string) =>
    request<PullRequest[]>("GET", `/audits/${enc(auditId)}/pull-requests`),

  // AI
  aiStatus: () => request<AIStatus>("GET", "/ai/status"),
  explain: (
    auditId: string,
    body: { kind: ExplainKind; target?: string; refresh?: boolean },
  ) => request<AIArtifact>("POST", `/audits/${enc(auditId)}/explain`, { json: body }),
  listExplanations: (auditId: string) =>
    request<AIArtifact[]>("GET", `/audits/${enc(auditId)}/explanations`),
};

// POST /projects/{id}/audits returns an Audit (API.md); only a few fields are needed by callers.
type AuditBriefLike = Audit;
