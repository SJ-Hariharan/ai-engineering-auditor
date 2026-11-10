"use client";

import Link from "next/link";
import { CircleCheck, CircleDashed, CircleX, Loader2 } from "lucide-react";
import type { Audit } from "@/lib/types";
import { STAGES } from "@/lib/format";
import { ErrorNote, Panel } from "@/components/app/common";
import { cn } from "@/lib/utils";

export function ProgressView({ audit }: { audit: Audit }) {
  const idx = audit.stage ? (STAGES as readonly string[]).indexOf(audit.stage) : -1;
  const failed = audit.status === "failed";
  return (
    <div className="mx-auto max-w-xl space-y-4">
      <Panel className="p-5">
        <h2 className="text-base font-semibold">
          {failed ? "Audit failed" : audit.status === "queued" ? "Audit queued" : "Audit in progress"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {failed
            ? "The analysis could not be completed."
            : "Analysing the repository. This page updates automatically every 2 seconds."}
        </p>
        <ol className="mt-4 space-y-2" aria-label="Audit stages">
          {STAGES.map((s, i) => {
            const done = audit.status === "running" ? i < idx : false;
            const current = audit.status === "running" ? i === idx : failed && i === idx;
            const Icon = failed && current ? CircleX : done ? CircleCheck : current ? Loader2 : CircleDashed;
            return (
              <li
                key={s}
                aria-current={current ? "step" : undefined}
                className={cn(
                  "flex items-center gap-2 text-sm capitalize",
                  done && "text-foreground",
                  current && !failed && "font-medium text-brand",
                  failed && current && "font-medium text-sev-critical",
                  !done && !current && "text-muted-foreground",
                )}
              >
                <Icon className={cn("size-4", current && !failed && "animate-spin", done && "text-ok")} aria-hidden />
                {s}
                {done && <span className="sr-only"> (done)</span>}
              </li>
            );
          })}
        </ol>
        {audit.status === "queued" && <p className="mt-4 text-xs text-muted-foreground">Waiting for a worker to pick this up…</p>}
        {failed && audit.error && <ErrorNote error={audit.error} className="mt-4" />}
        {failed && !audit.error && <ErrorNote error="No error message was recorded." className="mt-4" />}
      </Panel>
      <Link href={`/projects/${audit.project_id}`} className="text-sm text-brand hover:underline">
        Go to project
      </Link>
    </div>
  );
}
