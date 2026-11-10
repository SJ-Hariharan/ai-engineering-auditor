"use client";

import { useReport } from "./report-context";
import { Panel, Section } from "@/components/app/common";
import { CATEGORY_LABEL, SEVERITY_LABEL } from "@/lib/format";
import { CATEGORIES, SEVERITIES } from "@/lib/types";
import { SeverityBadge } from "@/components/app/badges";

const SCANNERS = [
  { name: "Semgrep", what: "Pattern-based static analysis with curated local rules: injection, unsafe deserialization, command execution, weak crypto, XSS sinks and more. Reads source, never runs it." },
  { name: "Gitleaks", what: "Looks for committed secrets such as API keys, tokens and private keys. Matches are masked in the UI." },
  { name: "OSV-Scanner", what: "Checks dependency manifests and lockfiles against the OSV vulnerability database. Only package names and versions are sent to the database, never your code." },
  { name: "Trivy", what: "Scans dependencies and container/IaC configuration (e.g. Dockerfiles) for known vulnerabilities and misconfigurations." },
  { name: "Built-in analyzers", what: "Tree-sitter based parsing for Python, JavaScript and TypeScript: import graph and cycles, coupling, complexity, function/file size, duplication, error handling, naming and a static view of test coverage." },
];

export function MethodologyTab() {
  const { summary } = useReport();
  const m = summary.scores.methodology;
  return (
    <div className="max-w-4xl space-y-8">
      <div className="rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-sm">
        The score is a prioritisation aid, not a security certification or compliance attestation.
      </div>

      <Section title="How scores work">
        <Panel className="space-y-3 p-4 text-sm">
          <p>{m.summary}</p>
          <div>
            <div className="text-xs text-muted-foreground">Formula</div>
            <code className="mt-1 block rounded-md bg-muted px-3 py-2 font-mono text-xs break-words">{m.formula}</code>
          </div>
        </Panel>
      </Section>

      <div className="grid gap-6 md:grid-cols-3">
        <Section title="Severity points">
          <Panel className="divide-y">
            {SEVERITIES.map((s) => (
              <div key={s} className="flex items-center justify-between px-3 py-1.5">
                <SeverityBadge severity={s} />
                <span className="font-mono text-xs tabular-nums">{m.severity_points[s]}</span>
              </div>
            ))}
          </Panel>
        </Section>
        <Section title="Confidence factor" description="Points are multiplied by this.">
          <Panel className="divide-y">
            {(["high", "medium", "low"] as const).map((c) => (
              <div key={c} className="flex items-center justify-between px-3 py-1.5 text-sm capitalize">
                <span>{c}</span>
                <span className="font-mono text-xs tabular-nums">{m.confidence_factor[c]}</span>
              </div>
            ))}
          </Panel>
        </Section>
        <Section title="Category weights">
          <Panel className="divide-y">
            {CATEGORIES.map((c) => (
              <div key={c} className="flex items-center justify-between px-3 py-1.5 text-sm">
                <span>{CATEGORY_LABEL[c]}</span>
                <span className="font-mono text-xs tabular-nums">{Math.round((m.weights[c] ?? 0) * 100)}%</span>
              </div>
            ))}
          </Panel>
        </Section>
      </div>

      <Section title="Limitations">
        <ul className="list-disc space-y-1.5 pl-5 text-sm">
          {m.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      </Section>

      <Section title="Objective vs subjective findings">
        <Panel className="space-y-2 p-4 text-sm">
          <p>
            <strong>Objective</strong> findings describe something verifiable: a vulnerable dependency version, a committed secret, a query built by
            string concatenation. They can be reproduced and checked.
          </p>
          <p>
            <strong>Subjective</strong> findings are engineering judgement: a long function, high complexity, or a naming convention. They rely on
            thresholds that are conventions, not laws, and may not apply to your context. Each finding is labelled so you can weigh it accordingly.
          </p>
          <p className="text-xs text-muted-foreground">Severity labels: {SEVERITIES.map((s) => SEVERITY_LABEL[s]).join(", ")}. AI never creates findings or changes scores.</p>
        </Panel>
      </Section>

      <Section title="What each scanner does">
        <Panel className="divide-y">
          {SCANNERS.map((s) => (
            <div key={s.name} className="px-3 py-2.5 text-sm">
              <div className="font-medium">{s.name}</div>
              <div className="text-muted-foreground">{s.what}</div>
            </div>
          ))}
        </Panel>
      </Section>
    </div>
  );
}
