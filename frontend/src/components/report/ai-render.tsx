"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Pill } from "@/components/app/badges";
import { useReport } from "./report-context";
import { FileLink } from "@/components/app/common";
import type {
  AIArtifact,
  FileContentAI,
  FindingContentAI,
  OverviewContent,
  QuestionsContent,
  SymbolContentAI,
} from "@/lib/types";
import { formatDate } from "@/lib/format";

/** AI output is loosely validated server-side; be defensive about shapes. */
function list(x: unknown): string[] {
  if (x == null || x === "") return [];
  if (Array.isArray(x)) return x.map((v) => (typeof v === "string" ? v : JSON.stringify(v)));
  return [typeof x === "string" ? x : JSON.stringify(x)];
}
function str(x: unknown): string {
  return x == null ? "" : typeof x === "string" ? x : JSON.stringify(x);
}

export function AIBadge({ artifact }: { artifact: AIArtifact }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1 rounded-md border border-brand/40 bg-brand/10 px-1.5 py-0.5 font-medium text-brand">
        <Sparkles className="size-3" aria-hidden /> AI-generated
      </span>
      <span>
        {artifact.provider} / {artifact.model} · {formatDate(artifact.created_at)}
      </span>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h4>
      <div className="text-sm">{children}</div>
    </div>
  );
}
function Bullets({ items }: { items: string[] }) {
  if (!items.length) return <span className="text-muted-foreground">None.</span>;
  return (
    <ul className="list-disc space-y-1 pl-5">
      {items.map((i, k) => (
        <li key={k}>{i}</li>
      ))}
    </ul>
  );
}

export function OverviewAI({ c }: { c: OverviewContent }) {
  const { audit } = useReport();
  return (
    <div className="space-y-5">
      <Block title="Summary"><p>{str(c.summary)}</p></Block>
      <Block title="Architecture"><p>{str(c.architecture)}</p></Block>
      <Block title="Data flow"><Bullets items={list(c.data_flow)} /></Block>
      <Block title="Key modules">
        <ul className="divide-y rounded-md border">
          {(c.key_modules ?? []).map((m, i) => (
            <li key={i} className="flex flex-wrap gap-x-3 gap-y-1 px-3 py-1.5">
              <FileLink auditId={audit.id} file={str(m.path)} />
              <span className="min-w-0 flex-1 basis-56 text-muted-foreground">{str(m.role)}</span>
            </li>
          ))}
        </ul>
      </Block>
      <Block title="Design decisions">
        <ul className="space-y-2">
          {(c.design_decisions ?? []).map((d, i) => (
            <li key={i} className="rounded-md border p-2.5">
              <div className="font-medium">{str(d.decision)}</div>
              <div className="mt-0.5 text-muted-foreground">{str(d.evidence)}</div>
              <Pill className="mt-1.5">confidence: {str(d.confidence)}</Pill>
            </li>
          ))}
        </ul>
      </Block>
      <Block title="Risks"><Bullets items={list(c.risks)} /></Block>
    </div>
  );
}

export function FileAI({ c }: { c: FileContentAI }) {
  return (
    <div className="space-y-4">
      <Block title="Purpose"><p>{str(c.purpose)}</p></Block>
      <Block title="How it works"><Bullets items={list(c.how_it_works)} /></Block>
      <Block title="Key symbols">
        <ul className="space-y-1.5">
          {(c.key_symbols ?? []).map((s, i) => (
            <li key={i}>
              <code className="rounded bg-muted px-1 font-mono text-xs">{str(s.name)}</code> <span className="text-muted-foreground">{str(s.explanation)}</span>
            </li>
          ))}
        </ul>
      </Block>
      <Block title="Dependencies"><Bullets items={list(c.dependencies)} /></Block>
      <Block title="Gotchas"><Bullets items={list(c.gotchas)} /></Block>
    </div>
  );
}

export function SymbolAI({ c }: { c: SymbolContentAI }) {
  return (
    <div className="space-y-4">
      <Block title="Purpose"><p>{str(c.purpose)}</p></Block>
      <Block title="Inputs"><Bullets items={list(c.inputs)} /></Block>
      <Block title="Outputs"><Bullets items={list(c.outputs)} /></Block>
      <Block title="Steps">
        <ol className="list-decimal space-y-1 pl-5">
          {list(c.steps).map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </Block>
      <Block title="Side effects"><Bullets items={list(c.side_effects)} /></Block>
      <Block title="Edge cases"><Bullets items={list(c.edge_cases)} /></Block>
    </div>
  );
}

export function FindingAI({ c }: { c: FindingContentAI }) {
  const fp = c.likely_false_positive;
  const fpText = typeof fp === "boolean" ? (fp ? "Likely a false positive" : "Likely a real issue") : str(fp);
  return (
    <div className="space-y-4">
      <Block title="Plain explanation"><p>{str(c.plain_explanation)}</p></Block>
      <Block title="Failure / attack scenario"><p>{str(c.failure_or_attack_scenario)}</p></Block>
      <Block title="False positive?">
        <p><strong>{fpText}.</strong> {str(c.false_positive_reasoning)}</p>
      </Block>
      <Block title="Fix steps">
        <ol className="list-decimal space-y-1 pl-5">
          {list(c.fix_steps).map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </Block>
    </div>
  );
}

export function QuestionsAI({ c }: { c: QuestionsContent }) {
  const { audit } = useReport();
  const [shown, setShown] = useState<Record<number, boolean>>({});
  return (
    <ol className="space-y-3">
      {(c.questions ?? []).map((q, i) => (
        <li key={i} className="rounded-lg border bg-card p-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1 basis-64 text-sm font-medium">
              {i + 1}. {str(q.question)}
            </div>
            <Pill>{str(q.difficulty)}</Pill>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">Why it matters: {str(q.why_it_matters)}</p>
          {(q.related_files ?? []).length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
              {q.related_files.map((f) => (
                <FileLink key={f} auditId={audit.id} file={f} />
              ))}
            </div>
          )}
          <div className="mt-2">
            <Button variant="outline" size="sm" aria-expanded={!!shown[i]} onClick={() => setShown((s) => ({ ...s, [i]: !s[i] }))}>
              {shown[i] ? "Hide answer" : "Reveal answer"}
            </Button>
            {shown[i] && <p className="mt-2 rounded-md bg-muted/50 p-2.5 text-sm">{str(q.answer)}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Dispatch on artifact.kind. */
export function ArtifactView({ artifact }: { artifact: AIArtifact }) {
  const c = artifact.content;
  return (
    <div className="space-y-3">
      <AIBadge artifact={artifact} />
      {artifact.kind === "overview" && <OverviewAI c={c as OverviewContent} />}
      {artifact.kind === "file" && <FileAI c={c as FileContentAI} />}
      {artifact.kind === "symbol" && <SymbolAI c={c as SymbolContentAI} />}
      {artifact.kind === "questions" && <QuestionsAI c={c as QuestionsContent} />}
      {artifact.kind === "finding" && <FindingAI c={c as FindingContentAI} />}
    </div>
  );
}
