"use client";

import Link from "next/link";
import { FolderGit2, Lock, Sparkles, Terminal } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/hooks/use-api";
import type { Project } from "@/lib/types";
import { NewAuditPanel } from "@/components/app/new-audit-panel";
import { ErrorNote, PageLoading, Panel } from "@/components/app/common";
import { Pill, SeverityCounts, StatusBadge } from "@/components/app/badges";
import { GradeBadge, ScoreBar, scoreTone } from "@/components/app/score";
import { fmtScore, gradeOf, repoName, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

function WhatHappens() {
  const items = [
    { icon: FolderGit2, title: "Static analysis only", text: "Your code is parsed and scanned (Semgrep, Gitleaks, OSV-Scanner, Trivy). It is never executed during an audit." },
    { icon: Terminal, title: "Tests run only if you opt in", text: "Running a project's tests is a separate, explicit action. It happens in an isolated Docker sandbox with no network." },
    { icon: Sparkles, title: "AI is off by default", text: "AI explanations and fixes need per-project consent. Only redacted excerpts are sent, and you can switch it off at any time." },
    { icon: Lock, title: "Source is temporary", text: "Uploaded or cloned source is kept for a limited time so you can browse and fix it. Findings and metrics remain afterwards." },
  ];
  return (
    <Panel className="p-4">
      <h2 className="text-sm font-semibold">Audit AI-generated code before you ship it</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Point the auditor at a repository to get a scored report on security, architecture, code quality and testing, plus
        guided help understanding and fixing what you find.
      </p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {items.map((i) => (
          <li key={i.title} className="flex gap-3">
            <i.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            <div>
              <div className="text-sm font-medium">{i.title}</div>
              <div className="text-xs text-muted-foreground">{i.text}</div>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function ProjectRow({ p }: { p: Project }) {
  const a = p.latest_audit;
  const tone = a?.overall_score != null ? scoreTone(a.overall_score) : null;
  return (
    <tr className="border-b last:border-0 hover:bg-muted/40">
      <td className="px-3 py-2.5">
        <Link href={`/projects/${p.id}`} className="font-medium hover:underline">
          {p.name}
        </Link>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <Pill>{p.source_type === "github" ? "GitHub" : "ZIP"}</Pill>
          {p.source_url && <span className="break-all">{repoName(p.source_url)}</span>}
        </div>
      </td>
      <td className="px-3 py-2.5">{a ? <StatusBadge status={a.status} /> : <span className="text-xs text-muted-foreground">No audits</span>}</td>
      <td className="px-3 py-2.5">
        {a?.overall_score != null ? (
          <div className="flex w-28 items-center gap-2">
            <GradeBadge grade={gradeOf(a.overall_score)} score={a.overall_score} className="size-6 text-xs" />
            <div className="min-w-0 flex-1">
              <div className={cn("text-sm font-medium tabular-nums", tone?.text)}>{fmtScore(a.overall_score)}</div>
              <ScoreBar score={a.overall_score} />
            </div>
          </div>
        ) : (
          <span className="text-muted-foreground">-</span>
        )}
      </td>
      <td className="px-3 py-2.5">{a?.status === "completed" ? <SeverityCounts counts={a.finding_counts} /> : <span className="text-muted-foreground">-</span>}</td>
      <td className="px-3 py-2.5 text-xs whitespace-nowrap text-muted-foreground">{timeAgo(a?.finished_at ?? a?.created_at ?? p.created_at)}</td>
      <td className="px-3 py-2.5 text-right">
        {a && (
          <Link href={`/audits/${a.id}`} className="text-xs text-brand hover:underline">
            Open report
          </Link>
        )}
      </td>
    </tr>
  );
}

export default function ProjectsPage() {
  const projects = useResource("projects", () => api.listProjects(), (list) =>
    list && list.some((p) => p.latest_audit && (p.latest_audit.status === "queued" || p.latest_audit.status === "running")) ? 3000 : null,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Projects</h1>
        <p className="text-sm text-muted-foreground">Understand what you built. Know what to fix. Ship with confidence.</p>
      </div>

      {projects.loading ? (
        <PageLoading />
      ) : projects.error ? (
        <ErrorNote error={projects.error} />
      ) : projects.data && projects.data.length === 0 ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <WhatHappens />
          <NewAuditPanel />
        </div>
      ) : (
        <>
          <NewAuditPanel />
          <Panel className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Project</th>
                  <th className="px-3 py-2 font-medium">Latest audit</th>
                  <th className="px-3 py-2 font-medium">Score</th>
                  <th className="px-3 py-2 font-medium">Findings</th>
                  <th className="px-3 py-2 font-medium">Updated</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>{projects.data?.map((p) => <ProjectRow key={p.id} p={p} />)}</tbody>
            </table>
          </Panel>
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">What happens to my code?</summary>
            <div className="mt-3">
              <WhatHappens />
            </div>
          </details>
        </>
      )}
    </div>
  );
}
