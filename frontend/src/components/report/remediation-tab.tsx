"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Check, ExternalLink, GitPullRequest, RotateCcw, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAction, useResource } from "@/hooks/use-api";
import { useReport } from "./report-context";
import type { Fix, FixStatus, PullRequest } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CopyButton, EmptyState, ErrorNote, FileLink, PageLoading, Panel, Section } from "@/components/app/common";
import { Pill, SeverityBadge } from "@/components/app/badges";
import { DiffView } from "@/components/app/diff-view";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const STATUS_CLS: Record<FixStatus, string> = {
  pending: "text-muted-foreground border-border bg-muted",
  approved: "text-ok border-ok/40 bg-ok/10",
  rejected: "text-sev-critical border-sev-critical/40 bg-sev-critical/10",
};

export function RemediationTab() {
  const { audit, project, findings } = useReport();
  const fixes = useResource(`fixes:${audit.id}`, () => api.listFixes(audit.id));
  const prs = useResource(project?.source_type === "github" ? `prs:${audit.id}` : null, () => api.listPullRequests(audit.id));
  const [prOpen, setPrOpen] = useState(false);

  const byFinding = useMemo(() => new Map(findings.map((f) => [f.id, f])), [findings]);
  const isGithub = project?.source_type === "github";
  const approved = (fixes.data ?? []).filter((f) => f.status === "approved");

  const setStatus = useAction(async (fix: Fix, status: FixStatus) => {
    const updated = await api.setFixStatus(fix.id, status);
    fixes.setData((fixes.data ?? []).map((f) => (f.id === updated.id ? updated : f)));
  });

  if (fixes.loading) return <PageLoading label="Loading fixes…" />;
  if (fixes.error) return <ErrorNote error={fixes.error} />;
  const list = fixes.data ?? [];

  return (
    <div className="space-y-8">
      <Section
        title="Proposed fixes"
        description="Nothing is changed in your code until you approve fixes and open a pull request. Review every diff."
        actions={
          <div className="flex flex-wrap gap-2">
            {!isGithub && approved.length > 0 && <CopyButton text={approved.map((f) => f.diff).join("\n")} label={`Copy ${approved.length} approved diff${approved.length > 1 ? "s" : ""}`} />}
            {isGithub && (
              <Button disabled={approved.length === 0} onClick={() => setPrOpen(true)}>
                <GitPullRequest /> Create pull request ({approved.length})
              </Button>
            )}
          </div>
        }
      >
        {project && !isGithub && (
          <p className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            Pull requests are only available for GitHub projects. This project was uploaded as a ZIP, so approve the fixes you want and use
            &quot;Copy diff&quot; to apply them yourself (for example with <code className="font-mono">git apply</code>).
          </p>
        )}
        <ErrorNote error={setStatus.error} />
        {list.length === 0 ? (
          <EmptyState icon={GitPullRequest} title="No fixes yet">
            Open a finding in the{" "}
            <Link href={`/audits/${audit.id}?tab=findings`} className="text-brand hover:underline">Findings</Link>{" "}
            tab and choose &quot;Suggest fix&quot;. Deterministic fixes are available for some rules; AI fixes need project consent.
          </EmptyState>
        ) : (
          <div className="space-y-4">
            {list.map((fx) => {
              const f = byFinding.get(fx.finding_id);
              return (
                <Panel key={fx.id} className="space-y-3 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        {f && <SeverityBadge severity={f.severity} />}
                        <span className="text-sm font-medium">{f?.title ?? "Fix"}</span>
                      </div>
                      <FileLink auditId={audit.id} file={fx.file} line={f?.line} />
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Pill className={fx.source === "ai" ? "border-brand/40 text-brand" : ""}>
                        {fx.source === "ai" ? "AI" : "Deterministic"} · {fx.generator}
                      </Pill>
                      <span className={cn("inline-flex h-5 items-center rounded-md border px-1.5 text-xs font-medium capitalize", STATUS_CLS[fx.status])}>{fx.status}</span>
                    </div>
                  </div>
                  <p className="text-sm">{fx.rationale}</p>
                  {fx.source === "ai" && <p className="text-xs text-muted-foreground">AI-generated change. It may be wrong; read the diff carefully.</p>}
                  <DiffView diff={fx.diff} />
                  {fx.caveats.length > 0 && (
                    <div>
                      <div className="text-xs font-medium">Caveats</div>
                      <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                        {fx.caveats.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" variant={fx.status === "approved" ? "default" : "outline"} disabled={setStatus.pending || fx.status === "approved"} onClick={() => void setStatus.run(fx, "approved")}>
                      <Check /> Approve
                    </Button>
                    <Button size="sm" variant="outline" disabled={setStatus.pending || fx.status === "rejected"} onClick={() => void setStatus.run(fx, "rejected")}>
                      <X /> Reject
                    </Button>
                    <Button size="sm" variant="ghost" disabled={setStatus.pending || fx.status === "pending"} onClick={() => void setStatus.run(fx, "pending")}>
                      <RotateCcw /> Reset
                    </Button>
                    {!isGithub && <CopyButton text={fx.diff} label="Copy diff" />}
                  </div>
                </Panel>
              );
            })}
          </div>
        )}
      </Section>

      {isGithub && (
        <Section title="Pull requests">
          {prs.loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : prs.error ? (
            <ErrorNote error={prs.error} />
          ) : (prs.data ?? []).length === 0 ? (
            <EmptyState title="No pull requests created from this audit" />
          ) : (
            <Panel className="divide-y">
              {(prs.data ?? []).map((pr) => (
                <PrRow key={pr.id} pr={pr} />
              ))}
            </Panel>
          )}
          {(prs.data ?? []).length > 0 && project && (
            <p className="text-sm">
              Merged your changes?{" "}
              <Link href={`/projects/${project.id}`} className="text-brand hover:underline">
                Re-run the audit to verify
              </Link>{" "}
              the findings are resolved.
            </p>
          )}
        </Section>
      )}

      {isGithub && project && (
        <PrDialog
          open={prOpen}
          onOpenChange={setPrOpen}
          auditId={audit.id}
          projectId={project.id}
          approvedCount={approved.length}
          onCreated={() => prs.reload()}
        />
      )}
    </div>
  );
}

function PrRow({ pr }: { pr: PullRequest }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-sm">
      <a href={safeHttp(pr.url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline">
        {pr.url} <ExternalLink className="size-3" aria-hidden />
      </a>
      <span className="font-mono text-xs text-muted-foreground">{pr.branch}</span>
      <span className="text-xs text-muted-foreground">{pr.fix_ids.length} fix{pr.fix_ids.length !== 1 ? "es" : ""}</span>
      <span className="text-xs text-muted-foreground">{formatDate(pr.created_at)}</span>
    </div>
  );
}

function safeHttp(u: string): string {
  return /^https?:\/\//i.test(u) ? u : "#";
}

function PrDialog({
  open,
  onOpenChange,
  auditId,
  projectId,
  approvedCount,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  auditId: string;
  projectId: string;
  approvedCount: number;
  onCreated: () => void;
}) {
  const [token, setToken] = useState("");
  const [title, setTitle] = useState("Fix issues found by AI Engineering Auditor");
  const [reviewed, setReviewed] = useState(false);
  const [created, setCreated] = useState<PullRequest | null>(null);
  const create = useAction(async () => {
    const pr = await api.createPullRequest(auditId, { github_token: token, title: title.trim() || undefined, confirm: true });
    setToken(""); // never keep the token around
    setCreated(pr);
    onCreated();
  });

  const close = (o: boolean) => {
    if (!o) {
      setToken("");
      setReviewed(false);
      setCreated(null);
    }
    onOpenChange(o);
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>Pull request created</DialogTitle>
              <DialogDescription>Review it on GitHub and merge when you are happy.</DialogDescription>
            </DialogHeader>
            <a href={safeHttp(created.url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm break-all text-brand hover:underline">
              {created.url} <ExternalLink className="size-3 shrink-0" aria-hidden />
            </a>
            <p className="text-sm text-muted-foreground">
              After merging, <Link href={`/projects/${projectId}`} className="text-brand hover:underline">re-run the audit to verify</Link> the fixes worked.
            </p>
            <DialogFooter>
              <Button variant="outline" onClick={() => close(false)}>Close</Button>
            </DialogFooter>
          </>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void create.run();
            }}
          >
            <DialogHeader>
              <DialogTitle>Create pull request</DialogTitle>
              <DialogDescription>
                {approvedCount} approved fix{approvedCount !== 1 ? "es" : ""} will be committed to a new branch and opened as a pull request. Your default branch is never pushed to.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-1.5">
              <Label htmlFor="gh-token">GitHub token</Label>
              <Input id="gh-token" type="password" autoComplete="off" spellCheck={false} required value={token} onChange={(e) => setToken(e.target.value)} placeholder="github_pat_…" />
              <p className="text-xs text-muted-foreground">
                Used once for this request and never stored. Fine-grained token with repository permissions <strong>Contents: write</strong> and{" "}
                <strong>Pull requests: write</strong>.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pr-title">Pull request title</Label>
              <Input id="pr-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
            </div>
            <label className="flex items-start gap-2 text-sm">
              <Checkbox checked={reviewed} onCheckedChange={(v) => setReviewed(v === true)} className="mt-0.5" />
              <span>I reviewed these changes.</span>
            </label>
            <ErrorNote error={create.error} />
            <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="outline" onClick={() => close(false)}>Cancel</Button>
              <Button type="submit" disabled={!reviewed || !token || create.pending}>
                {create.pending ? "Creating…" : "Create pull request"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
