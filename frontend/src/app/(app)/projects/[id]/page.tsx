"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, ExternalLink, RotateCw } from "lucide-react";
import { api } from "@/lib/api";
import { useAction, useResource } from "@/hooks/use-api";
import type { AuditBrief, ProjectDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorNote, PageLoading, Panel, Section } from "@/components/app/common";
import { Pill, SeverityCounts, StatusBadge } from "@/components/app/badges";
import { GradeBadge } from "@/components/app/score";
import { ProjectSettings } from "@/components/app/project-settings";
import { ZipDropzone } from "@/components/app/zip-dropzone";
import { fmtScore, formatDate, gradeOf, repoName } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Score delta against the next-older completed audit (list is newest first). */
function deltaFor(audits: AuditBrief[], i: number): number | null {
  const cur = audits[i];
  if (cur.overall_score == null) return null;
  for (let j = i + 1; j < audits.length; j++) {
    if (audits[j].overall_score != null) return cur.overall_score - (audits[j].overall_score as number);
  }
  return null;
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const project = useResource(id, () => api.getProject(id), (p) =>
    p && p.audits.some((a) => a.status === "queued" || a.status === "running") ? 2000 : null,
  );
  const [zipOpen, setZipOpen] = useState(false);
  const [zipFile, setZipFile] = useState<File | null>(null);

  const rerun = useAction(async (file?: File) => {
    const a = await api.rerunAudit(id, file);
    setZipOpen(false);
    setZipFile(null);
    router.push(`/audits/${a.id}`);
  });

  if (project.loading) return <PageLoading />;
  if (project.error || !project.data) {
    return (
      <div className="space-y-3">
        <ErrorNote error={project.error ?? "Project not found"} />
        <Link href="/" className="text-sm text-brand hover:underline">Back to projects</Link>
      </div>
    );
  }
  const p: ProjectDetail = project.data;
  const isGithub = p.source_type === "github";
  const busy = p.audits.some((a) => a.status === "queued" || a.status === "running");

  return (
    <div className="space-y-8">
      <div>
        <Link href="/" className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3" /> Projects
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight break-words">{p.name}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <Pill>{isGithub ? "GitHub" : "ZIP upload"}</Pill>
              {p.source_url && (
                <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline">
                  {repoName(p.source_url)} <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
              {p.default_branch && <span className="font-mono text-xs">{p.default_branch}</span>}
              <Pill>{p.llm_consent ? "AI enabled" : "AI off"}</Pill>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <Button
              disabled={busy || rerun.pending}
              onClick={() => (isGithub ? void rerun.run() : setZipOpen(true))}
            >
              <RotateCw className={cn(rerun.pending && "animate-spin")} />
              {isGithub ? "Re-run audit" : "Re-run with new ZIP"}
            </Button>
            {busy && <span className="text-xs text-muted-foreground">An audit is in progress.</span>}
          </div>
        </div>
        {isGithub && <ErrorNote error={rerun.error} className="mt-3" />}
      </div>

      <Section title="Audit history" description="Newest first. Deltas compare to the previous completed audit.">
        {p.audits.length === 0 ? (
          <EmptyState title="No audits yet">Re-run to create the first audit.</EmptyState>
        ) : (
          <Panel className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Score</th>
                  <th className="px-3 py-2 font-medium">Delta</th>
                  <th className="px-3 py-2 font-medium">Findings</th>
                  <th className="px-3 py-2 font-medium">Commit</th>
                  <th className="px-3 py-2 font-medium">Started</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {p.audits.map((a, i) => {
                  const d = deltaFor(p.audits, i);
                  return (
                    <tr key={a.id} className="border-b last:border-0 hover:bg-muted/40">
                      <td className="px-3 py-2">
                        <StatusBadge status={a.status} />
                        {a.status === "running" && a.stage && <span className="ml-2 text-xs text-muted-foreground">{a.stage}</span>}
                        {a.status === "failed" && a.error && <div className="mt-1 max-w-xs truncate text-xs text-sev-critical" title={a.error}>{a.error}</div>}
                      </td>
                      <td className="px-3 py-2">
                        {a.overall_score != null ? (
                          <span className="inline-flex items-center gap-2">
                            <GradeBadge grade={gradeOf(a.overall_score)} score={a.overall_score} className="size-6 text-xs" />
                            <span className="tabular-nums">{fmtScore(a.overall_score)}</span>
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-3 py-2 tabular-nums">
                        {d == null ? (
                          <span className="text-muted-foreground">-</span>
                        ) : (
                          <span className={cn(d > 0 ? "text-ok" : d < 0 ? "text-sev-critical" : "text-muted-foreground")}>
                            {d > 0 ? "▲ +" : d < 0 ? "▼ " : "± "}
                            {d.toFixed(1)}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">{a.status === "completed" ? <SeverityCounts counts={a.finding_counts} /> : "-"}</td>
                      <td className="px-3 py-2 font-mono text-xs">{a.commit_sha ? a.commit_sha.slice(0, 8) : "-"}</td>
                      <td className="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground">{formatDate(a.created_at)}</td>
                      <td className="px-3 py-2 text-right">
                        <Link href={`/audits/${a.id}`} className="text-xs text-brand hover:underline">Open</Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        )}
      </Section>

      <Section title="Settings">
        <ProjectSettings project={p} onChange={(np) => project.setData(np)} />
      </Section>

      <Dialog open={zipOpen} onOpenChange={setZipOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Re-run with a new ZIP</DialogTitle>
            <DialogDescription>Upload the updated source. The new audit is compared with the previous one.</DialogDescription>
          </DialogHeader>
          <ZipDropzone file={zipFile} onFile={setZipFile} disabled={rerun.pending} />
          <ErrorNote error={rerun.error} />
          <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={() => setZipOpen(false)}>Cancel</Button>
            <Button disabled={!zipFile || rerun.pending} onClick={() => zipFile && void rerun.run(zipFile)}>
              {rerun.pending ? "Uploading…" : "Upload and audit"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
