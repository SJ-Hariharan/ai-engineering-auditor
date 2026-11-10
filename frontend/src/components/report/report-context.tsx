"use client";

import { createContext, useContext } from "react";
import type { Audit, AuditSummary, Finding, ProjectDetail } from "@/lib/types";

export interface ReportCtx {
  audit: Audit;
  summary: AuditSummary;
  project: ProjectDetail | null;
  findings: Finding[];
  findingsLoading: boolean;
  findingsError: Error | null;
  /** Open the finding detail sheet. */
  openFinding: (f: Finding) => void;
  closeFinding: () => void;
  /** Why AI actions are unavailable, or null when they can be used. */
  aiDisabledReason: string | null;
  /** Re-fetch the audit now (e.g. after starting a sandbox test run). */
  reloadAudit: () => void;
  setPollingTests: (v: boolean) => void;
  goTab: (tab: string, extra?: Record<string, string | undefined>) => void;
}

export const ReportContext = createContext<ReportCtx | null>(null);

export function useReport(): ReportCtx {
  const v = useContext(ReportContext);
  if (!v) throw new Error("useReport outside ReportContext");
  return v;
}
