"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRight } from "lucide-react";
import { useReport } from "./report-context";
import { EmptyState, FileLink, Panel, Section, SortHeader } from "@/components/app/common";
import { Pill } from "@/components/app/badges";
import { DependencyGraph } from "./dependency-graph";
import { DesignSection } from "./design-section";
import { cn } from "@/lib/utils";
import { fmtNum } from "@/lib/format";
import type { FileInfo } from "@/lib/types";

type CouplingKey = "path" | "lines" | "fan_in" | "fan_out" | "instability";

export function ArchitectureTab() {
  const { audit, summary: s } = useReport();
  const arch = s.architecture;
  const [level, setLevel] = useState<"directories" | "files">("directories");
  const [sort, setSort] = useState<{ key: CouplingKey; dir: 1 | -1 }>({ key: "fan_in", dir: -1 });

  const dirGraph = arch.graph.directories;
  const fileGraph = arch.graph.files;

  const dirNodes = useMemo(() => dirGraph.nodes.map((n) => ({ id: n.id, label: n.id, sub: `${n.files} file${n.files !== 1 ? "s" : ""}` })), [dirGraph]);
  const fileNodes = useMemo(
    () => fileGraph.nodes.map((n) => ({ id: n.id, label: n.id, sub: n.test ? "test" : n.group, test: n.test })),
    [fileGraph],
  );

  const rows = useMemo(() => {
    const r = [...s.files];
    const val = (f: FileInfo): number | string => (sort.key === "path" ? f.path : (f[sort.key] ?? -1));
    r.sort((a, b) => {
      const x = val(a);
      const y = val(b);
      return (typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number)) * sort.dir;
    });
    return r;
  }, [s.files, sort]);
  const onSort = (k: CouplingKey) => setSort((p) => (p.key === k ? { key: k, dir: (p.dir * -1) as 1 | -1 } : { key: k, dir: k === "path" ? 1 : -1 }));

  const df = s.data_flow;
  const nothingGraphed = dirGraph.nodes.length === 0 && fileGraph.nodes.length === 0;

  return (
    <div className="space-y-8">
      <Section
        title="Dependency graph"
        description={`${arch.edges} import edge${arch.edges !== 1 ? "s" : ""}. An arrow means "imports". Dashed amber edges are part of a cycle. Numbers are import counts.`}
        actions={
          <div className="inline-flex rounded-md border p-0.5 text-xs" role="group" aria-label="Graph level">
            {(["directories", "files"] as const).map((l) => (
              <button
                key={l}
                type="button"
                aria-pressed={level === l}
                onClick={() => setLevel(l)}
                className={cn("rounded px-2.5 py-1", level === l ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground")}
              >
                {l === "directories" ? "Directories" : "Files"}
              </button>
            ))}
          </div>
        }
      >
        {nothingGraphed ? (
          <EmptyState title="No dependency graph">No resolvable imports between project files were found.</EmptyState>
        ) : level === "directories" ? (
          dirNodes.length ? (
            <DependencyGraph nodes={dirNodes} edges={dirGraph.edges} ariaLabel="Directory-level dependency graph" />
          ) : (
            <EmptyState title="No directories to graph" />
          )
        ) : (
          <>
            {fileGraph.truncated && (
              <div className="mb-2 flex items-center gap-2 rounded-md border border-warn/50 bg-warn/10 px-3 py-1.5 text-xs">
                <AlertTriangle className="size-3.5 shrink-0 text-warn" aria-hidden />
                The file-level graph was truncated for size: only part of the project is shown. Use the directory view or the coupling table for the full picture.
              </div>
            )}
            {fileNodes.length ? (
              <DependencyGraph nodes={fileNodes} edges={fileGraph.edges} nodeW={230} showWeights={false} ariaLabel="File-level dependency graph" />
            ) : (
              <EmptyState title="No files to graph" />
            )}
          </>
        )}
      </Section>

      <Section title="Circular dependencies" description="Import cycles make code harder to change and test in isolation.">
        {arch.cycles.length === 0 ? (
          <EmptyState title="No circular dependencies detected" />
        ) : (
          <Panel className="divide-y">
            {arch.cycles.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-x-1.5 gap-y-1 px-3 py-2 text-xs">
                {c.map((f, k) => (
                  <span key={k} className="inline-flex items-center gap-1.5">
                    <FileLink auditId={audit.id} file={f} />
                    {k < c.length - 1 && <ArrowRight className="size-3 text-warn" aria-label="imports" />}
                  </span>
                ))}
              </div>
            ))}
          </Panel>
        )}
      </Section>

      <Section title="Coupling" description="Fan-in: files that import this one. Fan-out: files this one imports. Instability = fan-out / (fan-in + fan-out); high values change easily.">
        <Panel className="max-h-[32rem] overflow-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="border-b text-left text-xs text-muted-foreground">
                <SortHeader label="File" k="path" sort={sort} onSort={onSort} />
                <SortHeader label="Lines" k="lines" sort={sort} onSort={onSort} align="right" />
                <SortHeader label="Fan-in" k="fan_in" sort={sort} onSort={onSort} align="right" />
                <SortHeader label="Fan-out" k="fan_out" sort={sort} onSort={onSort} align="right" />
                <SortHeader label="Instability" k="instability" sort={sort} onSort={onSort} align="right" />
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.path} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-3 py-1.5">
                    <FileLink auditId={audit.id} file={f.path} />
                    {f.is_test && <Pill className="ml-2">test</Pill>}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtNum(f.lines)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{f.fan_in ?? "-"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{f.fan_out ?? "-"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{f.instability != null ? f.instability.toFixed(2) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </Section>

      <Section title="External dependencies" description="Packages and standard-library modules imported by the code.">
        {arch.external_dependencies.length === 0 ? (
          <EmptyState title="No external imports found" />
        ) : (
          <Panel className="max-h-80 overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Module</th>
                  <th className="px-3 py-2 text-right font-medium">Imports</th>
                </tr>
              </thead>
              <tbody>
                {[...arch.external_dependencies].sort((a, b) => b.imports - a.imports || a.name.localeCompare(b.name)).map((d) => (
                  <tr key={d.name} className="border-b last:border-0">
                    <td className="px-3 py-1.5 font-mono text-xs">{d.name}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{d.imports}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
      </Section>

      <Section title="Data flow" description={df.method}>
        <div className="space-y-5">
          <div>
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground">Routes ({df.routes.length})</h3>
            {df.routes.length === 0 ? (
              <EmptyState title="No HTTP routes detected" />
            ) : (
              <Panel className="overflow-x-auto">
                <table className="w-full min-w-[32rem] text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      <th className="px-3 py-2 font-medium">Method</th>
                      <th className="px-3 py-2 font-medium">Path</th>
                      <th className="px-3 py-2 font-medium">Location</th>
                      <th className="px-3 py-2 font-medium">Handler</th>
                    </tr>
                  </thead>
                  <tbody>
                    {df.routes.map((r, i) => (
                      <tr key={i} className="border-b last:border-0">
                        <td className="px-3 py-1.5"><Pill className="font-mono">{r.method}</Pill></td>
                        <td className="px-3 py-1.5 font-mono text-xs break-all">{r.path}</td>
                        <td className="px-3 py-1.5"><FileLink auditId={audit.id} file={r.file} line={r.line} /></td>
                        <td className="px-3 py-1.5 font-mono text-xs">{r.handler ?? <span className="text-muted-foreground">(anonymous)</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            )}
          </div>
          <div className="grid gap-5 md:grid-cols-2">
            <ModuleList title="Data-access modules" auditId={audit.id} files={df.data_access} empty="None detected" />
            <ModuleList title="External-call modules" auditId={audit.id} files={df.external_calls} empty="None detected" />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground">Flows ({df.flows.length})</h3>
            {df.flows.length === 0 ? (
              <EmptyState title="No flows traced" />
            ) : (
              <Panel className="divide-y">
                {df.flows.map((f, i) => (
                  <div key={i} className="space-y-1 px-3 py-2">
                    <Pill>{f.kind}</Pill>
                    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
                      {f.path.map((p, k) => (
                        <span key={k} className="inline-flex items-center gap-1.5">
                          <FileLink auditId={audit.id} file={p} />
                          {k < f.path.length - 1 && <ArrowRight className="size-3 text-muted-foreground" aria-hidden />}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </Panel>
            )}
          </div>
        </div>
      </Section>

      <DesignSection design={s.design} auditId={audit.id} />
    </div>
  );
}

function ModuleList({ title, files, auditId, empty }: { title: string; files: string[]; auditId: string; empty: string }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{title}</h3>
      {files.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <Panel className="divide-y">
          {files.map((f) => (
            <div key={f} className="px-3 py-1.5">
              <FileLink auditId={auditId} file={f} />
            </div>
          ))}
        </Panel>
      )}
    </div>
  );
}
