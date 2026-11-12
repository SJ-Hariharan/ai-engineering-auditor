import type { Audit, AuditStatusInfo } from "./types";

export interface AuditPollApi {
  getAudit: (id: string) => Promise<Audit>;
  getAuditStatus: (id: string) => Promise<AuditStatusInfo>;
}

/**
 * Next value of a polled audit (E-03). The full audit carries the whole summary, which can be
 * megabytes, so while polling only the small status payload is fetched. The full audit is fetched
 * on the first load, when `force` is set, or when the status or the test run changed.
 */
export async function refreshAudit(
  id: string,
  prev: Audit | null,
  client: AuditPollApi,
  force = false,
): Promise<Audit> {
  if (!force && prev && prev.id === id) {
    const s = await client.getAuditStatus(id);
    const prevRun = prev.summary?.testing?.run ?? null;
    if (s.status === prev.status && JSON.stringify(s.test_run ?? null) === JSON.stringify(prevRun)) {
      return { ...prev, stage: s.stage, error: s.error, finished_at: s.finished_at };
    }
  }
  return client.getAudit(id);
}
