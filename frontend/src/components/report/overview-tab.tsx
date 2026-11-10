"use client";

import Link from "next/link";
import { AlertTriangle, ArrowDown, ArrowUp, Info } from "lucide-react";
import { useReport } from "./report-context";
import { EmptyState, FileLink, InlineCode, Panel, Section } from "@/components/app/common";
import { Pill, ScannerStatusBadge, SeverityBadge, SeverityCounts } from "@/components/app/badges";
import { GradeBadge, ScoreBar, scoreTone } from "@/components/app/score";
import { CATEGORY_LABEL, fmtNum, fmtScore, tabHref } from "@/lib/format";
import { CATEGORIES } from "@/lib/types";
import { cn } from "@/lib/utils";

export function OverviewTab() {
  const { audit, summary, findings, findingsLoading, openFinding, goTab } = useReport();
  const s = summary;
  const overall = s.scores.overall;
  const tone = overall != null ? scoreTone(overall) : { text: "text-muted-foreground" };
  const caps = s.scores.caps ?? [];
  const bad = s.scanners.filter((x) => x.status !== "ok");
  const top = findings.slice(0, 8);
  const cmp = s.comparison;
  const sup = s.suppressions;

  return (
    <div className="space-y-8">
      {bad.length > 0 && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <div>
            <strong className="font-medium">{bad.length} scanner{bad.length > 1 ? "s" : ""} did not run successfully</strong>
            : {bad.map((b) => `${b.name} (${b.status})`).join(", ")}. Skipped or failed scanners contribute no findings, so the score below
            may be higher than reality. See the scanner table at the bottom of this page.
          </div>
        </div>
      )}

      {sup && sup.total > 0 && (
        <div role="note" className="flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div>
            <strong className="font-medium">Scanner suppressions were found and ignored.</strong> The repository contains
            {sup.files.length > 0 && <> {sup.files.map((f) => f.file).join(", ")}</>}
            {sup.files.length > 0 && Object.keys(sup.inline).length > 0 && " and"}
            {Object.keys(sup.inline).length > 0 && (
              <> {Object.entries(sup.inline).map(([m, n]) => `${n} inline ${m} comment${n > 1 ? "s" : ""}`).join(", ")}</>
            )}
            . Findings are reported regardless, so a repository cannot hide its own issues. Review each suppression
            and fix the underlying issue or accept the finding.
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <Panel className="p-4">
          <div className="text-xs text-muted-foreground">Overall score</div>
          <div className="mt-1 flex items-center gap-3">
            <span className={cn("text-4xl font-semibold tabular-nums", tone.text)}>{fmtScore(overall)}</span>
            <GradeBadge grade={s.scores.grade} score={overall ?? undefined} className="size-9 text-lg" />
          </div>
          {overall != null ? (
            <ScoreBar score={overall} className="mt-3" />
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">Nothing in this repository could be analysed, so there is no score.</p>
          )}
          {caps.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs" aria-label="Score caps">
              {caps.map((c) => (
                <li key={c.reason} className="flex items-start gap-1.5">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
                  <span>
                    Capped at {fmtScore(c.max)}
                    {s.scores.uncapped_overall != null && <> (was {fmtScore(s.scores.uncapped_overall)})</>}: {c.note}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>
              A prioritisation aid, not a security certification.{" "}
              <button type="button" onClick={() => goTab("methodology")} className="text-brand hover:underline">
                Methodology
              </button>
            </span>
          </p>
          <div className="mt-3 border-t pt-3">
            <div className="mb-1.5 text-xs text-muted-foreground">{s.counts.total} findings</div>
            <SeverityCounts counts={s.counts.by_severity} />
          </div>
        </Panel>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {CATEGORIES.map((c) => {
            const cs = s.scores.categories[c];
            if (!cs) return null;
            const na = cs.score == null;
            const weight = cs.effective_weight ?? cs.weight;
            return (
              <Panel key={c} className="p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{cs.label ?? CATEGORY_LABEL[c]}</span>
                  <GradeBadge grade={cs.grade} score={cs.score ?? undefined} className="size-6 text-xs" />
                </div>
                {na ? (
                  <div className="mt-1 text-sm text-muted-foreground">Not analysed</div>
                ) : (
                  <>
                    <div className={cn("mt-1 text-xl font-semibold tabular-nums", scoreTone(cs.score as number).text)}>
                      {fmtScore(cs.score)}
                      {cs.status === "incomplete" && <Pill className="ml-2 align-middle">incomplete</Pill>}
                    </div>
                    <ScoreBar score={cs.score as number} className="mt-1.5" />
                  </>
                )}
                {cs.note && <p className="mt-1.5 text-xs text-muted-foreground">{cs.note}</p>}
                <div className="mt-2">
                  <SeverityCounts counts={cs.counts} />
                </div>
                <div className="mt-1.5 text-xs text-muted-foreground">
                  {na ? "Excluded from the overall score" : `Weight ${Math.round(weight * 100)}%`}
                  {!!cs.merged_duplicates && ` · ${cs.merged_duplicates} same-line duplicate${cs.merged_duplicates > 1 ? "s" : ""} scored once`}
                </div>
              </Panel>
            );
          })}
        </div>
      </div>

      <Section
        title="Fix first"
        description="Top findings by priority."
        actions={<button type="button" onClick={() => goTab("findings")} className="text-xs text-brand hover:underline">All {s.counts.total} findings</button>}
      >
        {findingsLoading ? (
          <p className="text-sm text-muted-foreground">Loading findings…</p>
        ) : top.length === 0 ? (
          <EmptyState title="No findings">Nothing was detected by the enabled scanners and analyzers.</EmptyState>
        ) : (
          <Panel className="divide-y">
            {top.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => openFinding(f)}
                className="flex w-full flex-wrap items-start gap-x-3 gap-y-1 px-3 py-2.5 text-left hover:bg-muted/40"
              >
                <SeverityBadge severity={f.severity} />
                <span className="min-w-0 flex-1 basis-60 text-sm">{f.title}</span>
                <span className="font-mono text-xs break-all text-muted-foreground">
                  {f.file ?? "(no file)"}
                  {f.line ? `:${f.line}` : ""}
                </span>
              </button>
            ))}
          </Panel>
        )}
      </Section>

      <div className="grid gap-8 lg:grid-cols-2">
        <Section title="What this codebase is">
          <Panel className="space-y-2 p-4 text-sm">
            {s.overview.paragraphs.map((p, i) => (
              <p key={i}><InlineCode text={p} /></p>
            ))}
            <p className="pt-1 text-xs text-muted-foreground">Generated deterministically from static analysis (no AI).</p>
          </Panel>
        </Section>

        <Section title="Stack">
          <Panel className="space-y-3 p-4 text-sm">
            <div>
              <div className="mb-1 text-xs text-muted-foreground">Languages</div>
              <ul className="space-y-1">
                {s.stack.languages.map((l) => (
                  <li key={l.name} className="flex justify-between gap-2">
                    <span>{l.name}</span>
                    <span className="text-muted-foreground tabular-nums">
                      {l.files} file{l.files !== 1 ? "s" : ""}
                      {l.lines != null && ` · ${fmtNum(l.lines)} lines`}
                    </span>
                  </li>
                ))}
                {s.stack.languages.length === 0 && <li className="text-muted-foreground">None detected</li>}
              </ul>
            </div>
            <TagRow label="Frameworks" items={s.stack.frameworks} />
            <TagRow label="Databases" items={s.stack.databases} />
            <TagRow label="Test frameworks" items={s.stack.test_frameworks} empty="None detected" />
            <TagRow label="Package managers" items={s.stack.package_managers} />
            <TagRow label="Manifests" items={s.stack.manifests} mono />
            <div className="text-xs text-muted-foreground">
              {s.stack.containerized ? "Containerized (Dockerfile found)." : "No container configuration found."} {fmtNum(s.inventory.source_files)} source
              files of {fmtNum(s.inventory.total_files)}, {fmtNum(s.inventory.total_lines)} lines
              {s.inventory.skipped_large_files > 0 && `; ${s.inventory.skipped_large_files} large files skipped`}.
            </div>
          </Panel>
        </Section>
      </div>

      <Section title="Entry points">
        {s.entry_points.length === 0 ? (
          <EmptyState title="No entry points detected" />
        ) : (
          <Panel className="divide-y">
            {s.entry_points.map((e, i) => (
              <div key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                {e.file ? <FileLink auditId={audit.id} file={e.file} /> : <span className="text-muted-foreground">(none)</span>}
                <Pill>{e.kind}</Pill>
                <span className="text-xs text-muted-foreground">{e.reason}</span>
              </div>
            ))}
          </Panel>
        )}
      </Section>

      {cmp && (
        <Section title="Compared with previous audit">
          <Panel className="space-y-3 p-4">
            <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">Score</div>
                {cmp.previous_score != null && overall != null ? (
                  <ScoreDelta now={overall} before={cmp.previous_score} />
                ) : (
                  <span>-</span>
                )}
              </div>
              <Mini label="Resolved" value={cmp.resolved} cls="text-ok" />
              <Mini label="New" value={cmp.new} cls="text-sev-critical" />
              <Mini label="Persisting" value={cmp.persisting} />
              <Link href={tabHref(cmp.previous_audit_id, "overview")} className="self-end text-xs text-brand hover:underline">
                View previous report
              </Link>
            </div>
            {cmp.resolved_findings.length > 0 && (
              <div>
                <div className="mb-1 text-xs text-muted-foreground">Resolved findings</div>
                <ul className="divide-y rounded-md border">
                  {cmp.resolved_findings.map((r, i) => (
                    <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 text-sm">
                      <SeverityBadge severity={r.severity} />
                      <span className="min-w-0 flex-1 basis-56">{r.title}</span>
                      {r.file && <span className="font-mono text-xs text-muted-foreground">{r.file}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>
        </Section>
      )}

      <Section title="Scanners" description="Scanners that were skipped or failed contribute no findings and can inflate the score.">
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium">Scanner</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Version</th>
                <th className="px-3 py-2 text-right font-medium">Duration</th>
                <th className="px-3 py-2 text-right font-medium">Findings</th>
                <th className="px-3 py-2 font-medium">Message</th>
              </tr>
            </thead>
            <tbody>
              {s.scanners.map((sc) => (
                <tr
                  key={sc.name}
                  className={cn(
                    "border-b last:border-0",
                    sc.status === "skipped" && "bg-warn/10",
                    sc.status === "failed" && "bg-sev-critical/10",
                  )}
                >
                  <td className="px-3 py-2 font-medium">{sc.name}</td>
                  <td className="px-3 py-2"><ScannerStatusBadge status={sc.status} /></td>
                  <td className="px-3 py-2 font-mono text-xs">{sc.version ?? "-"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{sc.duration_s.toFixed(1)}s</td>
                  <td className="px-3 py-2 text-right tabular-nums">{sc.findings}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{sc.message || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </Section>
    </div>
  );
}

function TagRow({ label, items, empty = "None", mono }: { label: string; items: string[]; empty?: string; mono?: boolean }) {
  return (
    <div>
      <div className="mb-1 text-xs text-muted-foreground">{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.length ? items.map((i) => <Pill key={i} className={cn(mono && "font-mono")}>{i}</Pill>) : <span className="text-xs text-muted-foreground">{empty}</span>}
      </div>
    </div>
  );
}

function Mini({ label, value, cls }: { label: string; value: number; cls?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("text-lg font-semibold tabular-nums", value > 0 && cls)}>{value}</div>
    </div>
  );
}

function ScoreDelta({ now, before }: { now: number; before: number }) {
  const d = now - before;
  return (
    <span className="inline-flex items-center gap-1.5 text-lg font-semibold tabular-nums">
      {before.toFixed(1)} → {now.toFixed(1)}
      <span className={cn("inline-flex items-center text-sm", d > 0 ? "text-ok" : d < 0 ? "text-sev-critical" : "text-muted-foreground")}>
        {d > 0 ? <ArrowUp className="size-3.5" aria-hidden /> : d < 0 ? <ArrowDown className="size-3.5" aria-hidden /> : null}
        {d > 0 ? "+" : ""}
        {d.toFixed(1)}
      </span>
    </span>
  );
}
