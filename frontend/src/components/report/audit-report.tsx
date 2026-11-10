"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { ArrowLeft, Download } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/hooks/use-api";
import type { AuditSummary, Finding } from "@/lib/types";
import { useApp } from "@/components/app/app-context";
import { ErrorNote, PageLoading } from "@/components/app/common";
import { StatusBadge, Pill } from "@/components/app/badges";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatDate, repoName } from "@/lib/format";
import { ReportContext } from "./report-context";
import { ProgressView } from "./progress-view";
import { OverviewTab } from "./overview-tab";
import { FindingsTab } from "./findings-tab";
import { FindingSheet } from "./finding-sheet";
import { ArchitectureTab } from "./architecture-tab";
import { QualityTab } from "./quality-tab";
import { TestingTab } from "./testing-tab";
import { CodeTab } from "./code-tab";
import { LearnTab } from "./learn-tab";
import { RemediationTab } from "./remediation-tab";
import { MethodologyTab } from "./methodology-tab";

const TABS = [
  ["overview", "Overview"],
  ["findings", "Findings"],
  ["architecture", "Architecture"],
  ["quality", "Code quality"],
  ["testing", "Testing"],
  ["code", "Code"],
  ["learn", "Learn"],
  ["remediation", "Remediation"],
  ["methodology", "Methodology"],
] as const;

export function AuditReport() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const { ai } = useApp();
  const [pollingTests, setPollingTests] = useState(false);
  const [openFindingState, setOpenFinding] = useState<Finding | null>(null);

  const audit = useResource(id, () => api.getAudit(id), (a) =>
    !a || a.status === "queued" || a.status === "running" || a.summary?.testing?.run?.status === "running" || pollingTests
      ? 2000
      : null,
  );
  const completed = audit.data?.status === "completed";
  const projectId = audit.data?.project_id ?? null;
  const project = useResource(projectId ? `project:${projectId}` : null, () => api.getProject(projectId as string));
  const findings = useResource(completed ? `findings:${id}` : null, () => api.getFindings(id));

  const tabParam = sp.get("tab") ?? "overview";
  const tab = TABS.some(([k]) => k === tabParam) ? tabParam : "overview";

  const goTab = useCallback(
    (t: string, extra: Record<string, string | undefined> = {}) => {
      const q = new URLSearchParams();
      q.set("tab", t);
      for (const [k, v] of Object.entries(extra)) if (v) q.set(k, v);
      router.replace(`${pathname}?${q.toString()}`, { scroll: false });
    },
    [router, pathname],
  );

  const aiDisabledReason = useMemo(() => {
    if (project.data && !project.data.llm_consent)
      return "AI features are off for this project. Turn them on in project settings.";
    if (ai && !ai.configured) return "No AI provider is configured on the server (set an API key to enable AI).";
    return null;
  }, [project.data, ai]);

  if (audit.loading && !audit.data) return <PageLoading label="Loading audit…" />;
  if (!audit.data) {
    return (
      <div className="space-y-3">
        <ErrorNote error={audit.error ?? "Audit not found"} />
        <Link href="/" className="text-sm text-brand hover:underline">Back to projects</Link>
      </div>
    );
  }
  const a = audit.data;
  const header = (
    <div className="mb-5">
      <Link href={`/projects/${a.project_id}`} className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3" /> {project.data?.name ?? "Project"}
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight break-words">{project.data?.name ?? "Audit report"}</h1>
            <StatusBadge status={a.status} />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {project.data?.source_url && <span>{repoName(project.data.source_url)}</span>}
            {a.commit_sha && <Pill className="font-mono">{a.commit_sha.slice(0, 8)}</Pill>}
            <span>{formatDate(a.finished_at ?? a.created_at)}</span>
            {!a.workspace_available && completed && <Pill>Source expired</Pill>}
          </div>
        </div>
        {completed && (
          <a
            href={api.reportUrl(a.id)}
            download
            className={cn(buttonVariants({ variant: "outline", size: "default" }))}
          >
            <Download /> Download report (.md)
          </a>
        )}
      </div>
    </div>
  );

  if (!completed) {
    return (
      <>
        {header}
        <ProgressView audit={a} />
      </>
    );
  }

  const summary = a.summary as AuditSummary;
  return (
    <ReportContext.Provider
      value={{
        audit: a,
        summary,
        project: project.data,
        findings: findings.data ?? [],
        findingsLoading: findings.loading,
        findingsError: findings.error,
        openFinding: setOpenFinding,
        closeFinding: () => setOpenFinding(null),
        aiDisabledReason,
        reloadAudit: audit.reload,
        setPollingTests,
        goTab,
      }}
    >
      {header}
      <Tabs value={tab} onValueChange={(v) => goTab(String(v))}>
        <div className="-mx-4 overflow-x-auto px-4">
          <TabsList variant="line" className="min-w-max border-b">
            {TABS.map(([k, label]) => (
              <TabsTrigger key={k} value={k} className="px-3">
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value="overview" className="pt-5"><OverviewTab /></TabsContent>
        <TabsContent value="findings" className="pt-5"><FindingsTab /></TabsContent>
        <TabsContent value="architecture" className="pt-5"><ArchitectureTab /></TabsContent>
        <TabsContent value="quality" className="pt-5"><QualityTab /></TabsContent>
        <TabsContent value="testing" className="pt-5"><TestingTab /></TabsContent>
        <TabsContent value="code" className="pt-5"><CodeTab /></TabsContent>
        <TabsContent value="learn" className="pt-5"><LearnTab /></TabsContent>
        <TabsContent value="remediation" className="pt-5"><RemediationTab /></TabsContent>
        <TabsContent value="methodology" className="pt-5"><MethodologyTab /></TabsContent>
      </Tabs>
      <FindingSheet finding={openFindingState} onClose={() => setOpenFinding(null)} />
    </ReportContext.Provider>
  );
}
