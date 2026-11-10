"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";

export type Row =
  | { t: "meta"; text: string }
  | { t: "hunk"; text: string }
  | { t: "ctx" | "add" | "del"; text: string; oldNo: number | null; newNo: number | null };

export function parseDiff(diff: string): Row[] {
  const rows: Row[] = [];
  let o = 0;
  let n = 0;
  for (const raw of diff.replace(/\r\n/g, "\n").split("\n")) {
    if (raw.startsWith("@@")) {
      const m = /@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(raw);
      o = m ? parseInt(m[1], 10) : 0;
      n = m ? parseInt(m[2], 10) : 0;
      rows.push({ t: "hunk", text: raw });
    } else if (raw.startsWith("---") || raw.startsWith("+++") || raw.startsWith("diff ") || raw.startsWith("index ")) {
      rows.push({ t: "meta", text: raw });
    } else if (raw.startsWith("+")) {
      rows.push({ t: "add", text: raw.slice(1), oldNo: null, newNo: n++ });
    } else if (raw.startsWith("-")) {
      rows.push({ t: "del", text: raw.slice(1), oldNo: o++, newNo: null });
    } else if (raw.startsWith("\\")) {
      rows.push({ t: "meta", text: raw });
    } else if (raw !== "" || rows.length) {
      rows.push({ t: "ctx", text: raw.startsWith(" ") ? raw.slice(1) : raw, oldNo: o++, newNo: n++ });
    }
  }
  // drop trailing empty ctx row produced by final newline
  while (rows.length && rows[rows.length - 1].t === "ctx" && (rows[rows.length - 1] as { text: string }).text === "") rows.pop();
  return rows;
}

const ROW_CLS = {
  add: "bg-ok/10",
  del: "bg-sev-critical/10",
  ctx: "",
} as const;

function UnifiedView({ rows }: { rows: Row[] }) {
  return (
    <table className="w-full border-collapse font-mono text-xs leading-5">
      <tbody>
        {rows.map((r, i) =>
          r.t === "meta" || r.t === "hunk" ? (
            <tr key={i} className={r.t === "hunk" ? "bg-brand/10 text-brand" : "text-muted-foreground"}>
              <td colSpan={4} className="px-2 whitespace-pre">{r.text}</td>
            </tr>
          ) : (
            <tr key={i} className={ROW_CLS[r.t]}>
              <td className="w-10 px-2 text-right text-muted-foreground select-none">{r.oldNo ?? ""}</td>
              <td className="w-10 px-2 text-right text-muted-foreground select-none">{r.newNo ?? ""}</td>
              <td className={cn("w-4 text-center select-none", r.t === "add" && "text-ok", r.t === "del" && "text-sev-critical")} aria-label={r.t === "add" ? "added" : r.t === "del" ? "removed" : "unchanged"}>
                {r.t === "add" ? "+" : r.t === "del" ? "-" : ""}
              </td>
              <td className="pr-3 whitespace-pre">{r.text}</td>
            </tr>
          ),
        )}
      </tbody>
    </table>
  );
}

/** Pair removed/added blocks side by side within each hunk. */
function SplitView({ rows }: { rows: Row[] }) {
  type Pair = { l: Row | null; r: Row | null } | { hunk: string };
  const pairs: Pair[] = [];
  let dels: Row[] = [];
  let adds: Row[] = [];
  const flush = () => {
    const len = Math.max(dels.length, adds.length);
    for (let i = 0; i < len; i++) pairs.push({ l: dels[i] ?? null, r: adds[i] ?? null });
    dels = [];
    adds = [];
  };
  for (const r of rows) {
    if (r.t === "del") dels.push(r);
    else if (r.t === "add") adds.push(r);
    else {
      flush();
      if (r.t === "hunk") pairs.push({ hunk: r.text });
      else if (r.t === "ctx") pairs.push({ l: r, r });
    }
  }
  flush();
  return (
    <div className="grid min-w-[40rem] grid-cols-2 font-mono text-xs leading-5">
      <div className="border-b px-2 py-1 font-sans text-xs font-medium text-muted-foreground">Before</div>
      <div className="border-b border-l px-2 py-1 font-sans text-xs font-medium text-muted-foreground">After</div>
      {pairs.map((p, i) =>
        "hunk" in p ? (
          <div key={i} className="col-span-2 bg-brand/10 px-2 whitespace-pre text-brand">{p.hunk}</div>
        ) : (
          <SplitRow key={i} l={p.l} r={p.r} />
        ),
      )}
    </div>
  );
}

function SplitRow({ l, r }: { l: Row | null; r: Row | null }) {
  const cell = (row: Row | null, side: "l" | "r") => {
    const kind = row && (row.t === "add" || row.t === "del" || row.t === "ctx") ? row.t : null;
    const no = row && kind ? (side === "l" ? (row as { oldNo: number | null }).oldNo : (row as { newNo: number | null }).newNo) : null;
    return (
      <div className={cn("flex min-w-0", side === "r" && "border-l", kind && ROW_CLS[kind], !row && "bg-muted/30")}>
        <span className="w-9 shrink-0 px-1 text-right text-muted-foreground select-none">{no ?? ""}</span>
        <span className={cn("w-4 shrink-0 text-center select-none", kind === "add" && "text-ok", kind === "del" && "text-sev-critical")}>
          {kind === "add" ? "+" : kind === "del" ? "-" : ""}
        </span>
        <span className="min-w-0 pr-2 break-all whitespace-pre-wrap">{row && "text" in row ? row.text : ""}</span>
      </div>
    );
  };
  return (
    <>
      {cell(l, "l")}
      {cell(r, "r")}
    </>
  );
}

export function DiffView({ diff, className }: { diff: string; className?: string }) {
  const [mode, setMode] = useState<"unified" | "split">("unified");
  const rows = useMemo(() => parseDiff(diff), [diff]);
  const stats = useMemo(
    () => ({ add: rows.filter((r) => r.t === "add").length, del: rows.filter((r) => r.t === "del").length }),
    [rows],
  );
  return (
    <div className={cn("overflow-hidden rounded-md border bg-card", className)}>
      <div className="flex items-center justify-between border-b bg-muted/40 px-2 py-1 text-xs">
        <span className="text-muted-foreground">
          <span className="text-ok">+{stats.add}</span> <span className="text-sev-critical">-{stats.del}</span>
        </span>
        <div className="inline-flex rounded-md border bg-background p-0.5" role="group" aria-label="Diff layout">
          {(["unified", "split"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              aria-pressed={mode === m}
              className={cn("rounded px-2 py-0.5", mode === m ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground")}
            >
              {m === "unified" ? "Unified" : "Before / after"}
            </button>
          ))}
        </div>
      </div>
      <div className="max-h-[28rem] overflow-auto">{mode === "unified" ? <UnifiedView rows={rows} /> : <SplitView rows={rows} />}</div>
    </div>
  );
}
