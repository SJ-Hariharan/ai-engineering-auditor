"use client";

import { useEffect, useMemo, useRef } from "react";
import { cn } from "@/lib/utils";
import { SEVERITY_LABEL, SEVERITY_RANK } from "@/lib/format";
import type { Finding, Severity } from "@/lib/types";
import { severityColorClass } from "./badges";

export interface CodeViewProps {
  content: string;
  findings?: Finding[];
  /** 1-based line to highlight and scroll to. */
  focusLine?: number | null;
  onFindingClick?: (f: Finding) => void;
  /** Bump to re-trigger scrolling to focusLine (e.g. when clicking the same symbol twice). */
  scrollKey?: number;
  maxHeight?: string;
  className?: string;
}

export function CodeView({ content, findings = [], focusLine, onFindingClick, scrollKey, maxHeight = "70vh", className }: CodeViewProps) {
  const lines = useMemo(() => content.replace(/\r\n/g, "\n").split("\n"), [content]);
  const containerRef = useRef<HTMLDivElement>(null);

  // findings by line (every line in [line, end_line] gets marked; first line carries the clickable marker)
  const byLine = useMemo(() => {
    const m = new Map<number, Finding[]>();
    for (const f of findings) {
      if (!f.line) continue;
      const end = Math.max(f.line, f.end_line ?? f.line);
      for (let l = f.line; l <= Math.min(end, f.line + 50); l++) {
        const arr = m.get(l) ?? [];
        arr.push(f);
        m.set(l, arr);
      }
    }
    return m;
  }, [findings]);

  useEffect(() => {
    if (!focusLine) return;
    const box = containerRef.current;
    const el = box?.querySelector<HTMLElement>(`[data-line="${focusLine}"]`);
    // scroll only the code box (not the whole page)
    if (box && el) box.scrollTop = Math.max(0, el.offsetTop - box.clientHeight / 2 + el.clientHeight / 2);
  }, [focusLine, scrollKey, content]);

  return (
    <div
      ref={containerRef}
      className={cn("relative overflow-auto rounded-md border bg-card font-mono text-xs leading-5", className)}
      style={{ maxHeight }}
      tabIndex={0}
      aria-label="Source code"
    >
      <div className="min-w-max">
        {lines.map((text, i) => {
          const n = i + 1;
          const fs = byLine.get(n);
          const worst: Severity | null = fs
            ? fs.reduce<Severity>((a, f) => (SEVERITY_RANK[f.severity] < SEVERITY_RANK[a] ? f.severity : a), "info")
            : null;
          const starting = fs?.filter((f) => f.line === n) ?? [];
          return (
            <div
              key={n}
              data-line={n}
              className={cn(
                "flex",
                worst && "bg-muted/60",
                focusLine === n && "bg-brand/15 outline outline-1 -outline-offset-1 outline-brand/50",
              )}
            >
              <span className="flex w-6 shrink-0 items-center justify-center">
                {starting.length > 0 && worst && (
                  <button
                    type="button"
                    onClick={() => onFindingClick?.(starting[0])}
                    title={`${starting.length} finding(s): ${starting.map((f) => `${SEVERITY_LABEL[f.severity]} - ${f.title}`).join("; ")}`}
                    aria-label={`Open finding: ${starting[0].title} (${SEVERITY_LABEL[worst]})`}
                    className={cn("size-3 rounded-full ring-2 ring-background hover:scale-125", severityColorClass(worst))}
                  />
                )}
              </span>
              <span className="w-10 shrink-0 pr-3 text-right text-muted-foreground select-none">{n}</span>
              <span
                className={cn(
                  "pr-4 whitespace-pre",
                  worst && "border-l-2 pl-2 -ml-px",
                )}
                style={worst ? { borderLeftColor: `var(--sev-${worst})` } : undefined}
              >
                {text === "" ? " " : text}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Plain monospace block for evidence / output. */
export function CodeBlock({ children, className, maxHeight }: { children: string; className?: string; maxHeight?: string }) {
  return (
    <pre
      className={cn("overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-5 whitespace-pre", className)}
      style={maxHeight ? { maxHeight } : undefined}
    >
      {children}
    </pre>
  );
}
