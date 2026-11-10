"use client";

import { EmptyState, FileLink, Panel, Section } from "@/components/app/common";
import { Pill } from "@/components/app/badges";
import type { DesignSummary } from "@/lib/types";

/** Data model and API surface extracted by the deterministic design analyzer. */
export function DesignSection({ design, auditId }: { design: DesignSummary | undefined; auditId: string }) {
  if (!design) {
    return (
      <Section title="Data model & API" description="Database schema and HTTP API surface.">
        <EmptyState title="Not available for this audit">Re-run the audit to include database and API design analysis.</EmptyState>
      </Section>
    );
  }
  const { api } = design;
  const methods = Object.entries(api.by_method).sort((a, b) => b[1] - a[1]);

  return (
    <Section title="Data model & API" description={design.method}>
      <div className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="Models" value={design.models_total} hint={design.orms.join(", ") || "no ORM detected"} />
          <Stat label="Endpoints" value={api.count} hint={`${api.mutating_endpoints} state-changing`} />
          <Stat
            label="Migrations"
            value={design.migrations.length}
            hint={design.migrations.length ? design.migrations.slice(0, 2).join(", ") : "none found"}
          />
        </div>

        {methods.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            By method:
            {methods.map(([m, n]) => (
              <Pill key={m} className="font-mono">
                {m} {n}
              </Pill>
            ))}
            {api.global_auth_middleware_detected && <span>· global auth middleware detected</span>}
          </div>
        )}

        <div>
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground">Models ({design.models_total})</h3>
          {design.models.length === 0 ? (
            <EmptyState title="No database models detected">
              Looked for SQLAlchemy, SQLModel, Django and Prisma models and CREATE TABLE statements.
            </EmptyState>
          ) : (
            <Panel className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Model</th>
                    <th className="px-3 py-2 font-medium">Fields</th>
                    <th className="px-3 py-2 font-medium">Relations</th>
                    <th className="px-3 py-2 font-medium">Location</th>
                  </tr>
                </thead>
                <tbody>
                  {design.models.map((m) => (
                    <tr key={`${m.file}:${m.line}`} className="border-b align-top last:border-0">
                      <td className="px-3 py-1.5">
                        <span className="font-mono text-xs font-medium">{m.name}</span>
                        <div className="text-xs text-muted-foreground">{m.orm}</div>
                      </td>
                      <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground break-words">
                        {m.fields.join(", ") || "—"}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-xs break-words">
                        {m.relations.length
                          ? m.relations.map((r) => `${r.field} → ${r.target}`).join(", ")
                          : <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-3 py-1.5">
                        <FileLink auditId={auditId} file={m.file} line={m.line} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </div>
      </div>
    </Section>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <Panel className="px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      <div className="truncate text-xs text-muted-foreground" title={hint}>
        {hint}
      </div>
    </Panel>
  );
}
