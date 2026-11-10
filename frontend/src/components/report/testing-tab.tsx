"use client";

import { useEffect, useState } from "react";
import { Play, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAction } from "@/hooks/use-api";
import { useReport } from "./report-context";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorNote, FileLink, Panel, Section, Spinner, Stat } from "@/components/app/common";
import { Pill } from "@/components/app/badges";
import { ScoreBar } from "@/components/app/score";
import { CodeBlock } from "@/components/app/code-view";
import { formatDate, fmtNum } from "@/lib/format";
import type { TestRun } from "@/lib/types";
import { cn } from "@/lib/utils";

const RUN_STYLE: Record<TestRun["status"], string> = {
  running: "text-brand border-brand/40 bg-brand/10",
  passed: "text-ok border-ok/40 bg-ok/10",
  failed: "text-sev-critical border-sev-critical/40 bg-sev-critical/10",
  timeout: "text-sev-high border-sev-high/40 bg-sev-high/10",
  skipped: "text-warn border-warn/50 bg-warn/15",
};

function friendly(e: ApiError): string {
  if (e.status === 410) return "The source files for this audit have expired and been deleted, so tests can no longer be run. Re-run the audit to fetch the code again.";
  if (e.status === 503) return `The test sandbox is unavailable (${e.message}). Docker must be running on the server for tests to run.`;
  if (e.status === 409) return `A test run is already in progress. ${e.message}`;
  return e.message;
}

export function TestingTab() {
  const { audit, summary, reloadAudit, setPollingTests } = useReport();
  const t = summary.testing;
  const run = t.run ?? null;
  const [requestedAt, setRequestedAt] = useState<number | null>(null);

  const start = useAction(async () => {
    await api.runTests(audit.id);
    setRequestedAt(Date.now());
    setPollingTests(true);
    reloadAudit();
  });

  // Stop polling once the run we asked for has finished (or after a safety timeout).
  useEffect(() => {
    if (requestedAt == null) return;
    const finished = run && run.status !== "running" && new Date(run.started_at).getTime() >= requestedAt - 60_000;
    if (finished) {
      setPollingTests(false);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset local request marker when the run completes
      setRequestedAt(null);
      return;
    }
    const timer = setTimeout(() => {
      setPollingTests(false);
      setRequestedAt(null);
    }, 15 * 60_000);
    return () => clearTimeout(timer);
  }, [run, requestedAt, setPollingTests]);

  useEffect(() => () => setPollingTests(false), [setPollingTests]);

  const running = run?.status === "running" || requestedAt != null;
  const cov = t.static_coverage_pct;
  const expired = !audit.workspace_available;

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Test files" value={t.test_files} hint={`${fmtNum(t.test_lines)} lines`} />
        <Stat label="Source files" value={t.source_files} hint={`${fmtNum(t.source_lines)} lines`} />
        <Stat label="Modules referenced by tests" value={t.referenced_modules} />
        <div className="rounded-lg border bg-card px-3 py-2.5">
          <div className="text-xs text-muted-foreground">Static coverage</div>
          <div className="mt-0.5 text-lg font-semibold tabular-nums">{cov != null ? `${cov.toFixed(0)}%` : "n/a"}</div>
          {cov != null && <ScoreBar score={cov} className="mt-1.5" />}
        </div>
      </div>
      <p className="-mt-4 text-xs text-muted-foreground">
        Static coverage is an estimate (method: {t.method}). It does not execute any tests and is not line coverage.
      </p>

      <div className="grid gap-8 lg:grid-cols-2">
        <Section title="Test frameworks">
          {t.frameworks.length ? (
            <div className="flex flex-wrap gap-1.5">{t.frameworks.map((f) => <Pill key={f}>{f}</Pill>)}</div>
          ) : (
            <EmptyState title="No test framework detected" />
          )}
        </Section>
        <Section title={`Untested modules (${t.untested_modules.length})`} description="Source files with no test importing or matching them.">
          {t.untested_modules.length === 0 ? (
            <EmptyState title="Every module is referenced by a test" />
          ) : (
            <Panel className="max-h-72 overflow-auto divide-y">
              {t.untested_modules.map((m) => (
                <div key={m.file} className="flex items-center justify-between gap-3 px-3 py-1.5">
                  <FileLink auditId={audit.id} file={m.file} />
                  <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">{m.lines} lines</span>
                </div>
              ))}
            </Panel>
          )}
        </Section>
      </div>

      <Section title="Run tests in sandbox">
        <Panel className="space-y-4 p-4">
          <div className="flex items-start gap-2 text-sm text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
            <p>
              This is the only step that executes repository code. Tests run in a throwaway Docker container with no network access,
              CPU/memory/process limits, a read-only root filesystem, a non-root user, dropped capabilities and a time limit. If Docker is not
              available the run is reported as skipped rather than executed on the host.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void start.run()} disabled={start.pending || running || expired}>
              <Play /> {running ? "Running…" : "Run tests in sandbox"}
            </Button>
            {running && <Spinner label="Running tests, checking every 2 seconds…" />}
            {expired && <span className="text-xs text-muted-foreground">Source expired. Re-run the audit to run tests.</span>}
          </div>
          {start.error && <ErrorNote error={friendly(start.error)} />}

          {run && run.status !== "running" && <RunResult run={run} />}
          {!run && !running && <p className="text-xs text-muted-foreground">No test run has been recorded for this audit.</p>}
        </Panel>
      </Section>
    </div>
  );
}

function RunResult({ run }: { run: TestRun }) {
  const counts = Object.entries(run.counts ?? {});
  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("inline-flex h-5 items-center rounded-md border px-1.5 text-xs font-medium capitalize", RUN_STYLE[run.status])}>{run.status}</span>
        {run.test && <span className="text-xs text-muted-foreground tabular-nums">{run.test.duration_s.toFixed(1)}s · exit code {run.test.exit_code}{run.test.timed_out && " · timed out"}</span>}
        {run.finished_at && <span className="text-xs text-muted-foreground">{formatDate(run.finished_at)}</span>}
      </div>
      {run.reason && <p className="text-sm">{run.reason}</p>}
      {counts.length > 0 && (
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          {counts.map(([k, v]) => (
            <div key={k}>
              <span className="text-lg font-semibold tabular-nums">{v}</span> <span className="text-xs text-muted-foreground">{k}</span>
            </div>
          ))}
        </div>
      )}
      {run.coverage && (
        <div className="max-w-sm">
          <div className="text-xs text-muted-foreground">
            Measured coverage: {run.coverage.percent.toFixed(1)}% ({run.coverage.covered_lines}/{run.coverage.statements} statements)
          </div>
          <ScoreBar score={run.coverage.percent} className="mt-1" />
        </div>
      )}
      <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
        {run.runtime && (
          <>
            <dt className="text-muted-foreground">Runtime</dt>
            <dd className="font-mono">{run.runtime}</dd>
          </>
        )}
        {run.isolation && (
          <>
            <dt className="text-muted-foreground">Isolation</dt>
            <dd className="font-mono break-words">{run.isolation}</dd>
          </>
        )}
      </dl>
      {run.test?.output && (
        <details>
          <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">Test output</summary>
          <CodeBlock className="mt-2" maxHeight="24rem">{run.test.output}</CodeBlock>
        </details>
      )}
    </div>
  );
}
