"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Sparkles, Wrench } from "lucide-react";
import { api } from "@/lib/api";
import { useAction } from "@/hooks/use-api";
import type { AIArtifact, Finding, Fix } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ErrorNote, FileLink, WithReason } from "@/components/app/common";
import { Pill, SeverityBadge } from "@/components/app/badges";
import { CodeBlock } from "@/components/app/code-view";
import { DiffView } from "@/components/app/diff-view";
import { CATEGORY_LABEL } from "@/lib/format";
import { useReport } from "./report-context";
import { ArtifactView } from "./ai-render";

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      <div className="text-sm">{children}</div>
    </section>
  );
}

/** Safe external links only (http/https); repo-derived strings are never rendered as raw hrefs otherwise. */
function isHttp(u: string) {
  return /^https?:\/\//i.test(u);
}

export function FindingSheet({ finding, onClose }: { finding: Finding | null; onClose: () => void }) {
  return (
    <Sheet open={!!finding} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl data-[side=right]:sm:max-w-xl">
        {finding && <FindingBody key={finding.id} f={finding} />}
      </SheetContent>
    </Sheet>
  );
}

function FindingBody({ f }: { f: Finding }) {
  const { audit, aiDisabledReason, goTab, closeFinding } = useReport();
  const [fix, setFix] = useState<Fix | null>(null);
  const [artifact, setArtifact] = useState<AIArtifact | null>(null);

  // `has_fix` means a fix was already generated for this finding: show it instead of making a new one.
  useEffect(() => {
    if (!f.has_fix) return;
    let cancelled = false;
    api
      .listFixes(audit.id)
      .then((list) => {
        const existing = list.filter((x) => x.finding_id === f.id).pop();
        if (!cancelled && existing) setFix(existing);
      })
      .catch(() => {
        /* the Remediation tab surfaces fix loading errors */
      });
    return () => {
      cancelled = true;
    };
  }, [f.has_fix, f.id, audit.id]);

  const suggest = useAction(async () => setFix(await api.createFix(f.id)));
  const explain = useAction(async () => setArtifact(await api.explain(audit.id, { kind: "finding", target: f.id })));

  return (
    <div className="flex flex-col gap-5 p-4">
      <SheetHeader className="p-0 pr-8">
        <div className="flex flex-wrap items-center gap-1.5">
          <SeverityBadge severity={f.severity} />
          <Pill>{CATEGORY_LABEL[f.category]}</Pill>
          <Pill>confidence: {f.confidence}</Pill>
        </div>
        <SheetTitle className="mt-2 text-base leading-snug break-words">{f.title}</SheetTitle>
        <SheetDescription className="font-mono text-xs">
          {f.tool} · {f.rule_id}
        </SheetDescription>
      </SheetHeader>

      <div className="rounded-md border bg-muted/30 p-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Pill className={f.kind === "objective" ? "border-ok/40 text-ok" : "border-warn/50 text-warn"}>
            {f.kind === "objective" ? "Objective" : "Subjective"}
          </Pill>
          {f.principle && <span className="text-muted-foreground">Principle: {f.principle}</span>}
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">
          {f.kind === "objective"
            ? "Objective findings are verifiable facts about the code (e.g. a known vulnerability pattern)."
            : "Subjective findings are judgement calls based on engineering conventions and may not apply to your context."}
        </p>
      </div>

      {f.file && (
        <Field title="Location">
          <FileLink auditId={audit.id} file={f.file} line={f.line} />
          {f.end_line && f.line && f.end_line !== f.line && <span className="text-xs text-muted-foreground"> (to line {f.end_line})</span>}
        </Field>
      )}
      <Field title="Evidence">
        <CodeBlock maxHeight="14rem">{f.evidence || "(none)"}</CodeBlock>
      </Field>
      <Field title="Explanation"><p className="whitespace-pre-wrap">{f.explanation}</p></Field>
      <Field title="Impact"><p className="whitespace-pre-wrap">{f.impact}</p></Field>
      <Field title="Recommended fix"><p className="whitespace-pre-wrap">{f.remediation}</p></Field>
      {f.references.length > 0 && (
        <Field title="References">
          <ul className="space-y-1">
            {f.references.map((r) => (
              <li key={r} className="break-all">
                {isHttp(r) ? (
                  <a href={r} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline">
                    {r} <ExternalLink className="size-3 shrink-0" aria-hidden />
                  </a>
                ) : (
                  <span>{r}</span>
                )}
              </li>
            ))}
          </ul>
        </Field>
      )}

      <div className="space-y-3 border-t pt-4">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void suggest.run()} disabled={suggest.pending}>
            <Wrench /> {suggest.pending ? "Generating…" : f.fixable ? "Suggest fix" : "Suggest fix with AI"}
          </Button>
          <WithReason reason={aiDisabledReason}>
            <Button variant="outline" onClick={() => void explain.run()} disabled={!!aiDisabledReason || explain.pending}>
              <Sparkles /> {explain.pending ? "Asking AI…" : "Explain with AI"}
            </Button>
          </WithReason>
        </div>
        {aiDisabledReason && <p className="text-xs text-muted-foreground">AI explanation unavailable: {aiDisabledReason}</p>}
        <ErrorNote error={suggest.error} />
        <ErrorNote error={explain.error} />
        {fix && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <strong>Proposed fix</strong>
              <Pill>{fix.source === "ai" ? `AI · ${fix.generator}` : `Deterministic · ${fix.generator}`}</Pill>
              <button
                type="button"
                onClick={() => {
                  closeFinding();
                  goTab("remediation");
                }}
                className="text-xs text-brand hover:underline"
              >
                Review in Remediation
              </button>
            </div>
            <p className="text-sm text-muted-foreground">{fix.rationale}</p>
            <DiffView diff={fix.diff} />
            {fix.caveats.length > 0 && (
              <ul className="list-disc pl-5 text-xs text-muted-foreground">
                {fix.caveats.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {artifact && <ArtifactView artifact={artifact} />}
      </div>
    </div>
  );
}
