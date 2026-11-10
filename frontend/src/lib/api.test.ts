// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

// Node environment: no DOM. `window` is stubbed per test so the 401 redirect can be observed.

type Call = { url: string; init: RequestInit };

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(response: Response | (() => Promise<Response>)) {
  const calls: Call[] = [];
  const fn = vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return typeof response === "function" ? response() : response.clone();
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

function stubWindow(pathname: string) {
  const replace = vi.fn();
  vi.stubGlobal("window", { location: { pathname, replace } });
  return replace;
}

function headersOf(init: RequestInit): Record<string, string> {
  return (init.headers ?? {}) as Record<string, string>;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request headers and credentials", () => {
  it("sends X-Auditor-Client and includes credentials on mutating requests", async () => {
    const calls = mockFetch(jsonResponse(200, { id: "u1", email: "a@b.co", created_at: "2026-01-01" }));
    await api.login("a@b.co", "pw-123456");

    expect(calls).toHaveLength(1);
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0].init)["X-Auditor-Client"]).toBe("1");
    expect(calls[0].init.credentials).toBe("include");
    expect(calls[0].url).toBe("/api/auth/login");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ email: "a@b.co", password: "pw-123456" });
  });

  it("sends the CSRF header on DELETE and PATCH as well", async () => {
    const calls = mockFetch(new Response(null, { status: 204 }));
    await api.deleteProject("p1");
    await api.setFixStatus("f1", "approved");

    expect(calls.map((c) => c.init.method)).toEqual(["DELETE", "PATCH"]);
    for (const c of calls) expect(headersOf(c.init)["X-Auditor-Client"]).toBe("1");
  });

  it("does not send the CSRF header on GET requests but still includes credentials", async () => {
    const calls = mockFetch(jsonResponse(200, []));
    await api.listProjects();

    expect(calls[0].init.method).toBe("GET");
    expect(headersOf(calls[0].init)).not.toHaveProperty("X-Auditor-Client");
    expect(calls[0].init.credentials).toBe("include");
  });
});

describe("error handling", () => {
  it("turns a {detail: string} body into ApiError(status, message)", async () => {
    mockFetch(jsonResponse(409, { detail: "Email already registered" }));
    const err = await api.register("a@b.co", "pw-123456").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, message: "Email already registered", name: "ApiError" });
  });

  it("turns a FastAPI validation array into a readable message, dropping the 'body' location", async () => {
    mockFetch(
      jsonResponse(422, {
        detail: [
          { loc: ["body", "password"], msg: "String should have at least 10 characters", type: "string_too_short" },
          { loc: ["body", "email", "domain"], msg: "value is not a valid email" },
        ],
      }),
    );
    const err = (await api.register("x", "short").catch((e: unknown) => e)) as ApiError;

    expect(err.status).toBe(422);
    expect(err.message).toBe(
      "password: String should have at least 10 characters; email.domain: value is not a valid email",
    );
  });

  it("falls back to a generic message when the error body is not JSON", async () => {
    mockFetch(new Response("<html>Bad gateway</html>", { status: 502 }));
    const err = (await api.me().catch((e: unknown) => e)) as ApiError;

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
    expect(err.message).toBe("Request failed (502)");
  });

  it("turns a network failure into ApiError(0, ...)", async () => {
    mockFetch(async () => {
      throw new TypeError("fetch failed");
    });
    const err = (await api.listProjects().catch((e: unknown) => e)) as ApiError;

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.message).toBe("Cannot reach the API. Is the backend running?");
  });

  it("redirects to /login on 401 when the user is on a protected page", async () => {
    const replace = stubWindow("/audits/abc");
    mockFetch(jsonResponse(401, { detail: "Not authenticated" }));

    await expect(api.me()).rejects.toMatchObject({ status: 401, message: "Not authenticated" });
    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("does not redirect on 401 while already on an auth page", async () => {
    const replace = stubWindow("/login");
    mockFetch(jsonResponse(401, { detail: "Invalid email or password" }));

    await expect(api.login("a@b.co", "wrong")).rejects.toMatchObject({ status: 401 });
    expect(replace).not.toHaveBeenCalled();
  });

  it("does not redirect on other error statuses", async () => {
    const replace = stubWindow("/audits/abc");
    mockFetch(jsonResponse(403, { detail: "LLM consent required" }));

    await expect(api.explain("a1", { kind: "overview" })).rejects.toMatchObject({ status: 403 });
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("responses", () => {
  it("returns undefined for 204 No Content", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(api.logout()).resolves.toBeUndefined();
  });

  it("parses JSON bodies on success", async () => {
    mockFetch(jsonResponse(200, [{ id: "p1", name: "demo" }]));
    await expect(api.listProjects()).resolves.toEqual([{ id: "p1", name: "demo" }]);
  });
});

describe("URL building", () => {
  it("encodes path ids and encodes each file path segment while keeping slashes", async () => {
    const calls = mockFetch(jsonResponse(200, { path: "x", content: "", language: null, truncated: false, symbols: [], findings: [] }));
    await api.getFile("aud 1", "server/app dir/a#b.py");

    expect(calls[0].url).toBe("/api/audits/aud%201/files/server/app%20dir/a%23b.py");
  });

  it("drops empty and undefined query params, and omits '?' when none remain", async () => {
    const calls = mockFetch(jsonResponse(200, []));
    await api.getFindings("a1", { category: "security", severity: "", kind: undefined });
    await api.getFindings("a1", { severity: "" });

    expect(calls[0].url).toBe("/api/audits/a1/findings?category=security");
    expect(calls[1].url).toBe("/api/audits/a1/findings");
  });

  it("encodes query values", async () => {
    const calls = mockFetch(jsonResponse(200, []));
    await api.getFindings("a1", { file: "src/a&b=c.ts" });

    const params = new URL(calls[0].url, "http://localhost").searchParams;
    expect(params.get("file")).toBe("src/a&b=c.ts");
    expect(calls[0].url).not.toContain("a&b=c.ts");
  });

  it("sends use_ai only when requested", async () => {
    const calls = mockFetch(jsonResponse(200, {}));
    await api.createFix("f1");
    await api.createFix("f1", true);

    expect(calls[0].url).toBe("/api/findings/f1/fix");
    expect(calls[1].url).toBe("/api/findings/f1/fix?use_ai=true");
  });

  it("builds the report download URL without a request", () => {
    expect(api.reportUrl("a 1")).toBe("/api/audits/a%201/report.md");
  });
});
