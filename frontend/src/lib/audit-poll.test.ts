import { describe, expect, it, vi } from "vitest";
import { refreshAudit } from "./audit-poll";
import type { Audit, AuditStatusInfo } from "./types";

const full = (over: Partial<Audit> = {}): Audit =>
  ({
    id: "a1", project_id: "p1", previous_audit_id: null, status: "running", stage: "parsing", error: null,
    commit_sha: null, created_at: "", started_at: null, finished_at: null, workspace_available: true,
    summary: {}, ...over,
  }) as Audit;

const status = (over: Partial<AuditStatusInfo> = {}): AuditStatusInfo => ({
  id: "a1", status: "running", stage: "quality", error: null, finished_at: null, test_run: null, ...over,
});

function client(s: AuditStatusInfo, a: Audit) {
  return { getAuditStatus: vi.fn().mockResolvedValue(s), getAudit: vi.fn().mockResolvedValue(a) };
}

describe("refreshAudit (E-03)", () => {
  it("fetches the full audit on the first load", async () => {
    const c = client(status(), full());
    await refreshAudit("a1", null, c);
    expect(c.getAudit).toHaveBeenCalledOnce();
    expect(c.getAuditStatus).not.toHaveBeenCalled();
  });

  it("only polls the small status while nothing but the stage changes", async () => {
    const c = client(status({ stage: "security" }), full());
    const next = await refreshAudit("a1", full(), c);
    expect(c.getAudit).not.toHaveBeenCalled();
    expect(next.stage).toBe("security");
  });

  it("fetches the full audit when the status changes", async () => {
    const done = full({ status: "completed", summary: { counts: { total: 3 } } as Audit["summary"] });
    const c = client(status({ status: "completed", stage: null }), done);
    expect(await refreshAudit("a1", full(), c)).toBe(done);
  });

  it("fetches the full audit when the test run changes", async () => {
    const prev = full({ status: "completed" });
    const c = client(status({ status: "completed", test_run: { status: "passed" } as AuditStatusInfo["test_run"] }), prev);
    await refreshAudit("a1", prev, c);
    expect(c.getAudit).toHaveBeenCalledOnce();
  });

  it("fetches the full audit when forced or when the audit id changed", async () => {
    const c = client(status(), full());
    await refreshAudit("a1", full(), c, true);
    await refreshAudit("a1", full({ id: "other" }), c);
    expect(c.getAudit).toHaveBeenCalledTimes(2);
  });
});
