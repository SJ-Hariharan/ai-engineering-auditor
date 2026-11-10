"use client";

import Link from "next/link";
import { useState } from "react";
import { BookOpen, GraduationCap, Sparkles } from "lucide-react";
import { useReport } from "./report-context";
import { useExplain, useExplanations } from "./ai-hooks";
import { ArtifactView } from "./ai-render";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorNote, Panel, Spinner, WithReason } from "@/components/app/common";
import { useApp } from "@/components/app/app-context";
import type { AIArtifact, ExplainKind } from "@/lib/types";

export function LearnTab() {
  const { audit, project, aiDisabledReason } = useReport();
  const { ai } = useApp();
  const expl = useExplanations(audit.id);
  const [fresh, setFresh] = useState<Partial<Record<ExplainKind, AIArtifact>>>({});
  const [active, setActive] = useState<ExplainKind | null>(null);
  const explain = useExplain(audit.id, (a) => {
    setFresh((f) => ({ ...f, [a.kind]: a }));
    expl.upsert(a);
  });

  const consentOff = project != null && !project.llm_consent;
  const notConfigured = !consentOff && ai != null && !ai.configured;
  const get = (k: ExplainKind) => fresh[k] ?? expl.find(k, null);
  const overview = get("overview");
  const questions = get("questions");

  const gen = (kind: ExplainKind) => {
    setActive(kind);
    void explain.run(kind, undefined, !!get(kind));
  };

  return (
    <div className="space-y-6">
      {aiDisabledReason && (
        <EmptyState icon={Sparkles} title={consentOff ? "AI features are off for this project" : notConfigured ? "No AI provider configured" : "AI unavailable"}>
          {consentOff ? (
            <>
              Codebase explanations and learning questions are written by an AI model, so they need your consent first. When enabled, redacted code
              excerpts are sent to the configured provider. Nothing is sent while this is off.
            </>
          ) : notConfigured ? (
            <>The server has no AI provider API key configured, so explanations cannot be generated. Ask whoever runs this deployment to set one up.</>
          ) : (
            aiDisabledReason
          )}
          {consentOff && project && (
            <div className="mt-3">
              <Link href={`/projects/${project.id}`} className="text-brand hover:underline">
                Open project settings to enable AI
              </Link>
            </div>
          )}
        </EmptyState>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          icon={BookOpen}
          title="Codebase explanation"
          description="An AI-written walkthrough of what this project does, how it is organised, key modules, design decisions and risks."
          buttonLabel={overview ? "Regenerate explanation" : "Generate codebase explanation"}
          disabledReason={aiDisabledReason}
          pending={explain.pending && active === "overview"}
          onClick={() => gen("overview")}
        />
        <Card
          icon={GraduationCap}
          title="Learning questions"
          description="Questions that test whether you understand this codebase, with answers hidden until you reveal them."
          buttonLabel={questions ? "Regenerate questions" : "Generate learning questions"}
          disabledReason={aiDisabledReason}
          pending={explain.pending && active === "questions"}
          onClick={() => gen("questions")}
        />
      </div>

      {expl.loading && <Spinner label="Loading saved results…" />}
      <ErrorNote error={explain.error} />

      {overview && (
        <Panel className="p-4">
          <h2 className="mb-3 text-sm font-semibold">Codebase explanation</h2>
          <ArtifactView artifact={overview} />
        </Panel>
      )}
      {questions && (
        <Panel className="p-4">
          <h2 className="mb-3 text-sm font-semibold">Learning questions</h2>
          <ArtifactView artifact={questions} />
        </Panel>
      )}
      {!overview && !questions && !expl.loading && !aiDisabledReason && (
        <p className="text-sm text-muted-foreground">Nothing generated yet. Results are saved with the audit so you only generate them once.</p>
      )}
    </div>
  );
}

function Card({
  icon: Icon,
  title,
  description,
  buttonLabel,
  disabledReason,
  pending,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  buttonLabel: string;
  disabledReason: string | null;
  pending: boolean;
  onClick: () => void;
}) {
  return (
    <Panel className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-2">
        <Icon className="size-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <p className="text-sm text-muted-foreground">{description}</p>
      <div className="mt-auto">
        <WithReason reason={disabledReason}>
          <Button variant="outline" disabled={!!disabledReason || pending} onClick={onClick}>
            <Sparkles /> {pending ? "Generating…" : buttonLabel}
          </Button>
        </WithReason>
      </div>
    </Panel>
  );
}
