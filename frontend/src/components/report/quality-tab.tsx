"use client";

import { useMemo, useState } from "react";
import { useReport } from "./report-context";
import { EmptyState, ErrorNote, FileLink, Panel, Section, SortHeader, Stat } from "@/components/app/common";
import { FindingsTable } from "./findings-table";
import { cn } from "@/lib/utils";

type HKey = "file" | "name" | "complexity" | "lines";

const THRESHOLD_LABEL: Record<string, string> = {
  function_lines_low: "Function length: low severity above (lines)",
  function_lines_medium: "Function length: medium severity above (lines)",
  complexity_medium: "Cyclomatic complexity: medium above",
  complexity_high: "Cyclomatic complexity: high above",
  nesting: "Nesting depth above",
  params: "Parameters above",
  file_lines_low: "File length: low above (lines)",
  file_lines_medium: "File length: medium above (lines)",
  class_methods: "Class methods above",
  class_lines: "Class length above (lines)",
  duplicate_window: "Duplicate-code window (lines)",
};

export function QualityTab() {
  const { audit, summary: s, findings, findingsLoading, findingsError } = useReport();
  const q = s.quality;
  const [sort, setSort] = useState<{ key: HKey; dir: 1 | -1 }>({ key: "complexity", dir: -1 });
  const medium = q.thresholds.complexity_medium ?? Infinity;
  const high = q.thresholds.complexity_high ?? Infinity;

  const hotspots = useMemo(() => {
    const r = [...q.hotspots];
    r.sort((a, b) => {
      const x = a[sort.key];
      const y = b[sort.key];
      return (typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number)) * sort.dir;
    });
    return r;
  }, [q.hotspots, sort]);
  const onSort = (k: HKey) => setSort((p) => (p.key === k ? { key: k, dir: (p.dir * -1) as 1 | -1 } : { key: k, dir: k === "file" || k === "name" ? 1 : -1 }));

  const related = findings.filter((f) => f.category === "code_quality" || f.category === "maintainability");

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Functions" value={q.functions} />
        <Stat label="Classes" value={q.classes} />
        <Stat label="Avg complexity" value={q.avg_complexity.toFixed(1)} />
        <Stat label="Complex functions" value={q.complex_functions} hint={`complexity > ${q.thresholds.complexity_medium ?? "?"}`} />
        <Stat label="Long functions" value={q.long_functions} hint={`> ${q.thresholds.function_lines_low ?? "?"} lines`} />
      </div>

      <Section title="Complexity hotspots" description="The most complex functions. Cyclomatic complexity counts independent paths through a function.">
        {hotspots.length === 0 ? (
          <EmptyState title="No functions analysed" />
        ) : (
          <Panel className="max-h-[30rem] overflow-auto">
            <table className="w-full min-w-[30rem] text-sm">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <SortHeader label="Function" k="name" sort={sort} onSort={onSort} />
                  <SortHeader label="File" k="file" sort={sort} onSort={onSort} />
                  <SortHeader label="Complexity" k="complexity" sort={sort} onSort={onSort} align="right" />
                  <SortHeader label="Lines" k="lines" sort={sort} onSort={onSort} align="right" />
                </tr>
              </thead>
              <tbody>
                {hotspots.map((h, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-1.5 font-mono text-xs break-all">{h.name}</td>
                    <td className="px-3 py-1.5"><FileLink auditId={audit.id} file={h.file} line={h.line} /></td>
                    <td
                      className={cn(
                        "px-3 py-1.5 text-right font-medium tabular-nums",
                        h.complexity > high ? "text-sev-high" : h.complexity > medium ? "text-sev-medium" : "",
                      )}
                    >
                      {h.complexity}
                      {h.complexity > medium && <span className="ml-1 text-xs font-normal">({h.complexity > high ? "very high" : "high"})</span>}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{h.lines}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
      </Section>

      <Section title="Code quality & maintainability findings" description="Many of these are subjective: they reflect conventions, not defects.">
        {findingsLoading ? (
          <p className="text-sm text-muted-foreground">Loading findings…</p>
        ) : findingsError ? (
          <ErrorNote error={findingsError} />
        ) : (
          <FindingsTable findings={related} categories={["code_quality", "maintainability"]} emptyText="No code quality or maintainability findings." />
        )}
      </Section>

      <Section title="Thresholds" description="Findings are raised when these limits are exceeded.">
        <Panel className="divide-y">
          {Object.entries(q.thresholds).map(([k, v]) => (
            <div key={k} className="flex items-center justify-between gap-3 px-3 py-1.5 text-sm">
              <span>{THRESHOLD_LABEL[k] ?? k}</span>
              <span className="font-mono text-xs tabular-nums">{v}</span>
            </div>
          ))}
        </Panel>
      </Section>
    </div>
  );
}
