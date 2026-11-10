"use client";

import { useCallback } from "react";
import { api } from "@/lib/api";
import { useAction, useResource } from "@/hooks/use-api";
import type { AIArtifact, ExplainKind } from "@/lib/types";

/** Cached AI artifacts for an audit, plus helpers to look up / add results. */
export function useExplanations(auditId: string) {
  const r = useResource(`explanations:${auditId}`, () => api.listExplanations(auditId));
  const { data, setData } = r;
  const find = useCallback(
    (kind: ExplainKind, target?: string | null): AIArtifact | null => {
      const matches = (data ?? []).filter((a) => a.kind === kind && (a.target ?? null) === (target ?? null));
      // newest wins
      return matches.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
    },
    [data],
  );
  const upsert = useCallback(
    (art: AIArtifact) => setData([...(data ?? []).filter((a) => a.id !== art.id && !(a.kind === art.kind && (a.target ?? null) === (art.target ?? null))), art]),
    [data, setData],
  );
  return { ...r, find, upsert };
}

/** Generate (or refresh) an AI explanation. */
export function useExplain(auditId: string, onResult: (a: AIArtifact) => void) {
  return useAction(async (kind: ExplainKind, target?: string, refresh?: boolean) => {
    const a = await api.explain(auditId, { kind, target, refresh });
    onResult(a);
    return a;
  });
}
