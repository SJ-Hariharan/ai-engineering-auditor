"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { EmptyState, NativeSelect, Panel } from "@/components/app/common";
import { Pill, SeverityBadge } from "@/components/app/badges";
import { CATEGORY_LABEL, SEVERITY_LABEL, SEVERITY_RANK } from "@/lib/format";
import { CATEGORIES, SEVERITIES, type Category, type Finding } from "@/lib/types";
import { useReport } from "./report-context";

export type FindingSort = "priority" | "severity" | "file";

export interface FindingFilters {
  /** Category value, or "all". */
  cat: string;
  /** Severity value, or "all". */
  sev: string;
  /** Kind value ("objective" | "subjective"), or "all". */
  kind: string;
  /** Free-text search over title, file, rule id and tool (case-insensitive). */
  q: string;
}

/** Keep the findings that match every active filter. Order is preserved. */
export function filterFindings(findings: Finding[], { cat, sev, kind, q }: FindingFilters): Finding[] {
  const needle = q.trim().toLowerCase();
  return findings.filter(
    (f) =>
      (cat === "all" || f.category === cat) &&
      (sev === "all" || f.severity === sev) &&
      (kind === "all" || f.kind === kind) &&
      (!needle ||
        f.title.toLowerCase().includes(needle) ||
        (f.file ?? "").toLowerCase().includes(needle) ||
        f.rule_id.toLowerCase().includes(needle) ||
        f.tool.toLowerCase().includes(needle)),
  );
}

/**
 * `findings` arrives in API priority order, so "priority" returns it unchanged.
 * The other sorts return a new array and leave the input alone.
 */
export function sortFindings(findings: Finding[], sort: FindingSort): Finding[] {
  if (sort === "severity") return [...findings].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]);
  if (sort === "file")
    return [...findings].sort((a, b) => (a.file ?? "").localeCompare(b.file ?? "") || (a.line ?? 0) - (b.line ?? 0));
  return findings;
}

export function FindingsTable({
  findings,
  categories = CATEGORIES,
  emptyText = "No findings match these filters.",
}: {
  findings: Finding[];
  categories?: Category[];
  emptyText?: string;
}) {
  const { openFinding } = useReport();
  const [cat, setCat] = useState("all");
  const [sev, setSev] = useState("all");
  const [kind, setKind] = useState("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<FindingSort>("priority");

  const rows = useMemo(
    () => sortFindings(filterFindings(findings, { cat, sev, kind, q }), sort),
    [findings, cat, sev, kind, q, sort],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1 basis-56">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input aria-label="Search findings" placeholder="Search title, file, rule…" className="pl-8" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {categories.length > 1 && (
          <NativeSelect
            label="Category"
            value={cat}
            onChange={setCat}
            options={[{ value: "all", label: "All categories" }, ...categories.map((c) => ({ value: c, label: CATEGORY_LABEL[c] }))]}
          />
        )}
        <NativeSelect
          label="Severity"
          value={sev}
          onChange={setSev}
          options={[{ value: "all", label: "All severities" }, ...SEVERITIES.map((s) => ({ value: s, label: SEVERITY_LABEL[s] }))]}
        />
        <NativeSelect
          label="Kind"
          value={kind}
          onChange={setKind}
          options={[
            { value: "all", label: "Objective + subjective" },
            { value: "objective", label: "Objective" },
            { value: "subjective", label: "Subjective" },
          ]}
        />
        <NativeSelect
          label="Sort"
          value={sort}
          onChange={(v) => setSort(v as typeof sort)}
          options={[
            { value: "priority", label: "Sort: priority" },
            { value: "severity", label: "Sort: severity" },
            { value: "file", label: "Sort: file" },
          ]}
        />
      </div>
      <div className="text-xs text-muted-foreground" aria-live="polite">
        {rows.length} of {findings.length} findings
      </div>
      {rows.length === 0 ? (
        <EmptyState title="Nothing to show">{emptyText}</EmptyState>
      ) : (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium">Severity</th>
                <th className="px-3 py-2 font-medium">Finding</th>
                <th className="px-3 py-2 font-medium">Category</th>
                <th className="px-3 py-2 font-medium">Location</th>
                <th className="px-3 py-2 font-medium">Kind</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr
                  key={f.id}
                  className="cursor-pointer border-b last:border-0 hover:bg-muted/40 focus-within:bg-muted/40"
                  onClick={() => openFinding(f)}
                >
                  <td className="px-3 py-2 align-top"><SeverityBadge severity={f.severity} /></td>
                  <td className="max-w-md px-3 py-2 align-top">
                    <button
                      type="button"
                      className="text-left font-medium hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        openFinding(f);
                      }}
                    >
                      {f.title}
                    </button>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {f.tool} · {f.rule_id}
                    </div>
                  </td>
                  <td className="px-3 py-2 align-top text-xs whitespace-nowrap">{CATEGORY_LABEL[f.category]}</td>
                  <td className="px-3 py-2 align-top font-mono text-xs break-all">
                    {f.file ?? "-"}
                    {f.line ? `:${f.line}` : ""}
                  </td>
                  <td className="px-3 py-2 align-top"><Pill>{f.kind}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}
