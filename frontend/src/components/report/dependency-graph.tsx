"use client";

import { useMemo, useState } from "react";

export interface GNode {
  id: string;
  label: string;
  sub?: string;
  test?: boolean;
}
export interface GEdge {
  source: string;
  target: string;
  weight?: number;
}

const NODE_H = 34;
const ROW_GAP = 14;
const COL_GAP = 90;
const PAD = 16;

interface Placed extends GNode {
  x: number;
  y: number;
  layer: number;
}

function layout(nodes: GNode[], edges: GEdge[], nodeW: number) {
  const ids = new Set(nodes.map((n) => n.id));
  const es = edges.filter((e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target);
  const out = new Map<string, string[]>();
  for (const n of nodes) out.set(n.id, []);
  for (const e of es) out.get(e.source)!.push(e.target);

  // 1. find back edges with iterative DFS so cycles don't break layering
  const state = new Map<string, 0 | 1 | 2>();
  const back = new Set<string>();
  for (const n of nodes) {
    if (state.get(n.id)) continue;
    const stack: { id: string; i: number }[] = [{ id: n.id, i: 0 }];
    state.set(n.id, 1);
    while (stack.length) {
      const top = stack[stack.length - 1];
      const nexts = out.get(top.id)!;
      if (top.i < nexts.length) {
        const t = nexts[top.i++];
        const st = state.get(t);
        if (st === 1) back.add(`${top.id}\u0000${t}`);
        else if (!st) {
          state.set(t, 1);
          stack.push({ id: t, i: 0 });
        }
      } else {
        state.set(top.id, 2);
        stack.pop();
      }
    }
  }
  const dag = es.filter((e) => !back.has(`${e.source}\u0000${e.target}`));

  // 2. longest-path layering
  const indeg = new Map<string, number>();
  const dagOut = new Map<string, string[]>();
  const dagIn = new Map<string, string[]>();
  for (const n of nodes) {
    indeg.set(n.id, 0);
    dagOut.set(n.id, []);
    dagIn.set(n.id, []);
  }
  for (const e of dag) {
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
    dagOut.get(e.source)!.push(e.target);
    dagIn.get(e.target)!.push(e.source);
  }
  const layerOf = new Map<string, number>();
  const queue = nodes.filter((n) => indeg.get(n.id) === 0).map((n) => n.id);
  for (const q of queue) layerOf.set(q, 0);
  while (queue.length) {
    const id = queue.shift()!;
    for (const t of dagOut.get(id)!) {
      layerOf.set(t, Math.max(layerOf.get(t) ?? 0, (layerOf.get(id) ?? 0) + 1));
      indeg.set(t, indeg.get(t)! - 1);
      if (indeg.get(t) === 0) queue.push(t);
    }
  }
  const maxLayer = Math.max(0, ...Array.from(layerOf.values()));
  const layers: string[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const n of [...nodes].sort((a, b) => a.id.localeCompare(b.id))) layers[layerOf.get(n.id) ?? 0].push(n.id);

  // 3. barycentre ordering (down then up)
  const pos = new Map<string, number>();
  const reindex = () => layers.forEach((l) => l.forEach((id, i) => pos.set(id, i)));
  reindex();
  const bary = (id: string, nb: string[]) => (nb.length ? nb.reduce((s, x) => s + (pos.get(x) ?? 0), 0) / nb.length : pos.get(id)!);
  for (let pass = 0; pass < 2; pass++) {
    for (let l = 1; l < layers.length; l++) {
      layers[l].sort((a, b) => bary(a, dagIn.get(a)!) - bary(b, dagIn.get(b)!));
      reindex();
    }
    for (let l = layers.length - 2; l >= 0; l--) {
      layers[l].sort((a, b) => bary(a, dagOut.get(a)!) - bary(b, dagOut.get(b)!));
      reindex();
    }
  }

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const placed = new Map<string, Placed>();
  let height = 0;
  layers.forEach((l, li) =>
    l.forEach((id, i) => {
      const y = PAD + i * (NODE_H + ROW_GAP);
      placed.set(id, { ...byId.get(id)!, x: PAD + li * (nodeW + COL_GAP), y, layer: li });
      height = Math.max(height, y + NODE_H + PAD);
    }),
  );
  const width = PAD * 2 + layers.length * nodeW + Math.max(0, layers.length - 1) * COL_GAP;
  return { placed, edges: es.map((e) => ({ ...e, back: back.has(`${e.source}\u0000${e.target}`) })), width, height };
}

function trimLeft(s: string, n: number) {
  return s.length > n ? "…" + s.slice(s.length - n + 1) : s;
}

export function DependencyGraph({
  nodes,
  edges,
  nodeW = 190,
  showWeights = true,
  ariaLabel,
}: {
  nodes: GNode[];
  edges: GEdge[];
  nodeW?: number;
  showWeights?: boolean;
  ariaLabel: string;
}) {
  const g = useMemo(() => layout(nodes, edges, nodeW), [nodes, edges, nodeW]);
  const [hover, setHover] = useState<string | null>(null);
  const maxChars = Math.floor((nodeW - 16) / 6.6);
  const maxW = Math.max(1, ...edges.map((e) => e.weight ?? 1));

  return (
    <div className="overflow-auto rounded-md border bg-card" style={{ maxHeight: "34rem" }}>
      <svg width={g.width} height={g.height} role="img" aria-label={ariaLabel} className="block text-foreground">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="currentColor" className="text-muted-foreground" />
          </marker>
          <marker id="arrow-cycle" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--warn)" />
          </marker>
          <marker id="arrow-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--brand)" />
          </marker>
        </defs>
        {g.edges.map((e, i) => {
          const a = g.placed.get(e.source)!;
          const b = g.placed.get(e.target)!;
          const hi = hover != null && (e.source === hover || e.target === hover);
          const dim = hover != null && !hi;
          // back edges (cycles) connect right-to-left; forward edges left-to-right
          const fwd = a.x < b.x;
          const x1 = fwd ? a.x + nodeW : a.x;
          const x2 = fwd ? b.x : b.x + nodeW;
          // offset back edges so a↔b pairs do not overlap
          const off = e.back ? 9 : 0;
          const y1 = a.y + NODE_H / 2 + off;
          const y2 = b.y + NODE_H / 2 + off;
          const same = a.x === b.x;
          let d: string;
          let mx: number;
          let my: number;
          if (same) {
            const bulge = 40;
            d = `M${a.x + nodeW},${y1} C${a.x + nodeW + bulge},${y1} ${b.x + nodeW + bulge},${y2} ${b.x + nodeW},${y2}`;
            mx = a.x + nodeW + bulge * 0.75;
            my = (y1 + y2) / 2;
          } else {
            const dx = Math.max(30, Math.abs(x2 - x1) / 2);
            const dir = fwd ? 1 : -1;
            d = `M${x1},${y1} C${x1 + dx * dir},${y1} ${x2 - dx * dir},${y2} ${x2},${y2}`;
            mx = (x1 + x2) / 2;
            my = (y1 + y2) / 2;
          }
          const w = e.weight ?? 1;
          return (
            <g key={i} opacity={dim ? 0.12 : 1}>
              <path
                d={d}
                fill="none"
                stroke={hi ? "var(--brand)" : e.back ? "var(--warn)" : "currentColor"}
                strokeOpacity={hi || e.back ? 1 : 0.35}
                strokeWidth={1 + (w / maxW) * 3}
                strokeDasharray={e.back ? "5 3" : undefined}
                markerEnd={`url(#${hi ? "arrow-hi" : e.back ? "arrow-cycle" : "arrow"})`}
              />
              {showWeights && e.weight != null && (
                <g>
                  <rect x={mx - 9} y={my - 8} width={18} height={16} rx={4} fill="var(--card)" stroke="var(--border)" />
                  <text x={mx} y={my + 4} textAnchor="middle" fontSize="10" fill="currentColor" className="tabular-nums">
                    {e.weight}
                  </text>
                </g>
              )}
              <title>{`${e.source} → ${e.target}${e.weight != null ? ` (${e.weight} imports)` : ""}${e.back ? " (part of a cycle)" : ""}`}</title>
            </g>
          );
        })}
        {Array.from(g.placed.values()).map((n) => {
          const connected =
            hover == null ||
            n.id === hover ||
            g.edges.some((e) => (e.source === hover && e.target === n.id) || (e.target === hover && e.source === n.id));
          return (
            <g
              key={n.id}
              transform={`translate(${n.x},${n.y})`}
              opacity={connected ? 1 : 0.3}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(n.id)}
              onBlur={() => setHover(null)}
              tabIndex={0}
              aria-label={`${n.id}${n.sub ? `, ${n.sub}` : ""}`}
            >
              <rect
                width={nodeW}
                height={NODE_H}
                rx={6}
                fill="var(--card)"
                stroke={hover === n.id ? "var(--brand)" : "var(--border)"}
                strokeWidth={hover === n.id ? 1.5 : 1}
                strokeDasharray={n.test ? "3 2" : undefined}
              />
              <text x={8} y={n.sub ? 14 : 21} fontSize="11" fill="currentColor" fontFamily="var(--font-geist-mono), monospace">
                {trimLeft(n.label, maxChars)}
              </text>
              {n.sub && (
                <text x={8} y={27} fontSize="9.5" fill="var(--muted-foreground)">
                  {n.sub}
                </text>
              )}
              <title>{n.id}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
