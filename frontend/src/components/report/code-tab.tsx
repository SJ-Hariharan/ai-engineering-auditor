"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronDown, ChevronRight, FileCode2, FlaskConical, Search, Sparkles } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useResource } from "@/hooks/use-api";
import { useReport } from "./report-context";
import { useExplain, useExplanations } from "./ai-hooks";
import { ArtifactView } from "./ai-render";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorNote, Panel, Spinner, WithReason } from "@/components/app/common";
import { CodeView } from "@/components/app/code-view";
import { Pill, severityColorClass } from "@/components/app/badges";
import { SEVERITY_LABEL, worstSeverity } from "@/lib/format";
import { buildTree, sortedChildren, type TreeNode } from "@/lib/file-tree";
import type { AIArtifact, CodeSymbol, Finding } from "@/lib/types";
import { cn } from "@/lib/utils";

function TreeRow({
  node,
  depth,
  selected,
  open,
  toggle,
  select,
  counts,
}: {
  node: TreeNode;
  depth: number;
  selected: string | null;
  open: Set<string>;
  toggle: (p: string) => void;
  select: (p: string) => void;
  counts: Map<string, Finding[]>;
}) {
  const pad = { paddingLeft: 8 + depth * 14 };
  if (node.file) {
    const fs = counts.get(node.path) ?? [];
    return (
      <button
        type="button"
        onClick={() => select(node.path)}
        aria-current={selected === node.path ? "true" : undefined}
        style={pad}
        className={cn(
          "flex w-full items-center gap-1.5 rounded py-1 pr-2 text-left text-xs hover:bg-muted",
          selected === node.path && "bg-muted font-medium",
        )}
        title={node.path}
      >
        {node.file.is_test ? <FlaskConical className="size-3.5 shrink-0 text-ok" aria-label="test file" /> : <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />}
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
        {fs.length > 0 && (
          <span
            className="inline-flex shrink-0 items-center gap-1 rounded border px-1 text-[10px] tabular-nums"
            title={`${fs.length} finding(s), worst: ${SEVERITY_LABEL[worstSeverity(fs)]}`}
          >
            <span className={cn("size-1.5 rounded-full", severityColorClass(worstSeverity(fs)))} aria-hidden />
            {fs.length}
          </span>
        )}
      </button>
    );
  }
  const isOpen = open.has(node.path);
  return (
    <div>
      <button
        type="button"
        onClick={() => toggle(node.path)}
        aria-expanded={isOpen}
        style={pad}
        className="flex w-full items-center gap-1 rounded py-1 pr-2 text-left text-xs font-medium hover:bg-muted"
      >
        {isOpen ? <ChevronDown className="size-3.5 shrink-0" aria-hidden /> : <ChevronRight className="size-3.5 shrink-0" aria-hidden />}
        <span className="truncate">{node.name}</span>
      </button>
      {isOpen &&
        sortedChildren(node).map((c) => (
          <TreeRow key={c.path} node={c} depth={depth + 1} selected={selected} open={open} toggle={toggle} select={select} counts={counts} />
        ))}
    </div>
  );
}

export function CodeTab() {
  const { audit, summary, findings, goTab, openFinding, aiDisabledReason } = useReport();
  const sp = useSearchParams();
  const selected = sp.get("file");
  const lineParam = parseInt(sp.get("line") ?? "", 10);
  const line = Number.isFinite(lineParam) && lineParam > 0 ? lineParam : null;
  const [filter, setFilter] = useState("");
  const [scrollKey, setScrollKey] = useState(0);

  const tree = useMemo(() => buildTree(summary.files), [summary.files]);
  const counts = useMemo(() => {
    const m = new Map<string, Finding[]>();
    for (const f of findings) if (f.file) m.set(f.file, [...(m.get(f.file) ?? []), f]);
    return m;
  }, [findings]);

  // Open dirs: all top-level + the directories on the path to the selected file.
  const [userOpen, setUserOpen] = useState<Record<string, boolean>>({});
  const open = useMemo(() => {
    const o = new Set<string>();
    const walk = (n: TreeNode, depth: number) => {
      for (const c of n.children.values()) {
        if (c.file) continue;
        if (depth === 0 || summary.files.length <= 30) o.add(c.path);
        walk(c, depth + 1);
      }
    };
    walk(tree, 0);
    if (selected) {
      const parts = selected.split("/");
      for (let i = 1; i < parts.length; i++) o.add(parts.slice(0, i).join("/"));
    }
    for (const [k, v] of Object.entries(userOpen)) {
      if (v) o.add(k);
      else o.delete(k);
    }
    return o;
  }, [tree, summary.files.length, selected, userOpen]);

  const toggle = (p: string) => setUserOpen((u) => ({ ...u, [p]: !open.has(p) }));
  const select = (p: string) => goTab("code", { file: p });

  const matches = filter.trim() ? summary.files.filter((f) => f.path.toLowerCase().includes(filter.trim().toLowerCase())) : null;

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <Panel className="flex max-h-72 flex-col lg:max-h-[78vh]">
        <div className="relative border-b p-2">
          <Search className="pointer-events-none absolute top-1/2 left-4 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input aria-label="Filter files" placeholder="Filter files…" className="h-7 pl-7 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <div className="flex-1 overflow-auto p-1">
          {summary.files.length === 0 ? (
            <p className="p-3 text-xs text-muted-foreground">No source files were analysed.</p>
          ) : matches ? (
            matches.length === 0 ? (
              <p className="p-3 text-xs text-muted-foreground">No files match.</p>
            ) : (
              matches.map((f) => (
                <TreeRow key={f.path} node={{ name: f.path, path: f.path, children: new Map(), file: f }} depth={0} selected={selected} open={open} toggle={toggle} select={select} counts={counts} />
              ))
            )
          ) : (
            sortedChildren(tree).map((c) => (
              <TreeRow key={c.path} node={c} depth={0} selected={selected} open={open} toggle={toggle} select={select} counts={counts} />
            ))
          )}
        </div>
        <div className="border-t px-3 py-1.5 text-[11px] text-muted-foreground">
          <FlaskConical className="mr-1 inline size-3 text-ok" aria-hidden /> test file · badge = findings
        </div>
      </Panel>

      <div className="min-w-0">
        {selected ? (
          <FileViewer
            key={selected}
            path={selected}
            line={line}
            scrollKey={scrollKey}
            onSymbol={(l) => {
              setScrollKey((k) => k + 1);
              goTab("code", { file: selected, line: String(l) });
            }}
            onFinding={openFinding}
            auditId={audit.id}
            aiDisabledReason={aiDisabledReason}
          />
        ) : (
          <EmptyState icon={FileCode2} title="Select a file">
            Pick a file from the tree to read it with findings marked on their lines. Findings in the other tabs link here.
          </EmptyState>
        )}
      </div>
    </div>
  );
}

function FileViewer({
  path,
  line,
  scrollKey,
  onSymbol,
  onFinding,
  auditId,
  aiDisabledReason,
}: {
  path: string;
  line: number | null;
  scrollKey: number;
  onSymbol: (l: number) => void;
  onFinding: (f: Finding) => void;
  auditId: string;
  aiDisabledReason: string | null;
}) {
  const file = useResource(`file:${auditId}:${path}`, () => api.getFile(auditId, path));
  const expl = useExplanations(auditId);
  const [shown, setShown] = useState<{ kind: "file" | "symbol"; target: string } | null>(null);
  const [fresh, setFresh] = useState<AIArtifact | null>(null);
  const explain = useExplain(auditId, (a) => {
    setFresh(a);
    expl.upsert(a);
  });

  if (file.loading) return <Spinner label="Loading file…" className="p-6" />;
  if (file.error) {
    const e = file.error;
    return e instanceof ApiError && e.status === 410 ? (
      <EmptyState title="Source files have expired">
        Repository contents are kept for a limited time. Findings and metrics remain available, but the code can no longer be displayed. Re-run the audit to fetch it again.
      </EmptyState>
    ) : (
      <ErrorNote error={e} />
    );
  }
  const f = file.data;
  if (!f) return null;

  const art = shown ? (fresh && fresh.kind === shown.kind && (fresh.target ?? "") === shown.target ? fresh : expl.find(shown.kind, shown.target)) : null;
  const run = (kind: "file" | "symbol", target: string, refresh = false) => {
    setShown({ kind, target });
    setFresh(null);
    void explain.run(kind, target, refresh);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-sm font-medium break-all">{f.path}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            {f.language && <Pill>{f.language}</Pill>}
            <span>{f.content.split("\n").length} lines</span>
            <span>{f.findings.length} finding{f.findings.length !== 1 ? "s" : ""}</span>
          </div>
        </div>
        <WithReason reason={aiDisabledReason}>
          <Button variant="outline" size="sm" disabled={!!aiDisabledReason || explain.pending} onClick={() => run("file", f.path, !!expl.find("file", f.path))}>
            <Sparkles /> {expl.find("file", f.path) ? "Re-explain file" : "Explain file"}
          </Button>
        </WithReason>
      </div>
      {f.truncated && <p className="rounded-md border border-warn/50 bg-warn/10 px-3 py-1.5 text-xs">This file is large and was truncated. Secrets in the source are masked.</p>}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_14rem]">
        <CodeView content={f.content} findings={f.findings} focusLine={line} scrollKey={scrollKey} onFindingClick={onFinding} />
        <SymbolOutline
          symbols={f.symbols}
          onSymbol={onSymbol}
          onExplain={(s) => run("symbol", `${f.path}#${s.name}`)}
          aiDisabledReason={aiDisabledReason}
          busy={explain.pending}
        />
      </div>

      {f.findings.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-semibold text-muted-foreground">Findings in this file</h3>
          <Panel className="divide-y">
            {[...f.findings].sort((a, b) => (a.line ?? 0) - (b.line ?? 0)).map((x) => (
              <button key={x.id} type="button" onClick={() => onFinding(x)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 text-left text-sm hover:bg-muted/40">
                <span className="w-14 font-mono text-xs text-muted-foreground">{x.line ? `L${x.line}` : "-"}</span>
                <span className="inline-flex items-center gap-1 text-xs">
                  <span className={cn("size-2 rounded-full", severityColorClass(x.severity))} aria-hidden />
                  {SEVERITY_LABEL[x.severity]}
                </span>
                <span className="min-w-0 flex-1 basis-56">{x.title}</span>
              </button>
            ))}
          </Panel>
        </div>
      )}

      {(explain.pending || explain.error || art || aiDisabledReason) && (
        <Panel className="space-y-3 p-4">
          <h3 className="text-sm font-semibold">{shown?.kind === "symbol" ? `Symbol: ${shown.target.split("#")[1]}` : "AI explanation"}</h3>
          {explain.pending && <Spinner label="Asking the AI provider…" />}
          <ErrorNote error={explain.error} />
          {art && <ArtifactView artifact={art} />}
          {!art && !explain.pending && !explain.error && aiDisabledReason && <p className="text-sm text-muted-foreground">AI explanations are unavailable: {aiDisabledReason}</p>}
        </Panel>
      )}
    </div>
  );
}

function SymbolOutline({
  symbols,
  onSymbol,
  onExplain,
  aiDisabledReason,
  busy,
}: {
  symbols: CodeSymbol[];
  onSymbol: (line: number) => void;
  onExplain: (s: CodeSymbol) => void;
  aiDisabledReason: string | null;
  busy: boolean;
}) {
  return (
    <Panel className="max-h-[70vh] self-start overflow-auto">
      <h3 className="border-b px-3 py-2 text-xs font-semibold text-muted-foreground">Outline</h3>
      {symbols.length === 0 ? (
        <p className="p-3 text-xs text-muted-foreground">No symbols parsed for this file.</p>
      ) : (
        <ul className="p-1">
          {symbols.map((s, i) => (
            <li key={`${s.name}:${s.line}:${i}`} className="group flex items-center gap-1 rounded hover:bg-muted">
              <button type="button" onClick={() => onSymbol(s.line)} className="flex min-w-0 flex-1 items-center gap-1.5 px-2 py-1 text-left text-xs">
                <span className="w-9 shrink-0 text-[10px] text-muted-foreground uppercase">{s.kind === "function" ? "fn" : s.kind === "method" ? "meth" : s.kind === "arrow" ? "arrow" : "class"}</span>
                <span className="min-w-0 flex-1 truncate font-mono" title={s.parent ? `${s.parent}.${s.name}` : s.name}>
                  {s.parent ? `${s.parent}.` : ""}
                  {s.name}
                </span>
                <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">{s.line}</span>
              </button>
              <WithReason reason={aiDisabledReason}>
                <Button variant="ghost" size="icon-xs" disabled={!!aiDisabledReason || busy} onClick={() => onExplain(s)} aria-label={`Explain ${s.name} with AI`} title="Explain with AI">
                  <Sparkles />
                </Button>
              </WithReason>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
