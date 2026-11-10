import { AlertOctagon, AlertTriangle, ArrowUp, Info, Minus, CircleCheck, CircleX, Loader2, Clock, MinusCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { SEVERITY_LABEL } from "@/lib/format";
import type { AuditStatus, Severity, FindingCounts } from "@/lib/types";

const SEV_STYLE: Record<Severity, string> = {
  critical: "border-sev-critical/40 bg-sev-critical/10 text-sev-critical",
  high: "border-sev-high/40 bg-sev-high/10 text-sev-high",
  medium: "border-sev-medium/40 bg-sev-medium/10 text-sev-medium",
  low: "border-sev-low/40 bg-sev-low/10 text-sev-low",
  info: "border-sev-info/30 bg-sev-info/10 text-sev-info",
};
const SEV_ICON: Record<Severity, typeof Info> = {
  critical: AlertOctagon,
  high: AlertTriangle,
  medium: ArrowUp,
  low: Minus,
  info: Info,
};

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const Icon = SEV_ICON[severity];
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-md border px-1.5 text-xs font-medium whitespace-nowrap",
        SEV_STYLE[severity],
        className,
      )}
    >
      <Icon className="size-3" aria-hidden />
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

export function severityColorClass(s: Severity) {
  return {
    critical: "bg-sev-critical",
    high: "bg-sev-high",
    medium: "bg-sev-medium",
    low: "bg-sev-low",
    info: "bg-sev-info",
  }[s];
}

/** Compact severity counts: "4 C · 15 H ..." as small labelled chips. */
export function SeverityCounts({ counts, className }: { counts: FindingCounts; className?: string }) {
  const order: Severity[] = ["critical", "high", "medium", "low", "info"];
  const items = order.filter((s) => (counts[s] ?? 0) > 0);
  if (!items.length) return <span className="text-xs text-muted-foreground">No findings</span>;
  return (
    <span className={cn("inline-flex flex-wrap gap-1", className)}>
      {items.map((s) => (
        <span
          key={s}
          title={`${counts[s]} ${SEVERITY_LABEL[s]}`}
          className={cn(
            "inline-flex h-5 items-center gap-1 rounded-md border px-1.5 text-xs font-medium tabular-nums",
            SEV_STYLE[s],
          )}
        >
          <span className={cn("size-1.5 rounded-full", severityColorClass(s))} aria-hidden />
          {counts[s]} {SEVERITY_LABEL[s]}
        </span>
      ))}
    </span>
  );
}

const STATUS_STYLE: Record<AuditStatus, { cls: string; icon: typeof Info; label: string }> = {
  queued: { cls: "text-muted-foreground border-border bg-muted", icon: Clock, label: "Queued" },
  running: { cls: "text-brand border-brand/40 bg-brand/10", icon: Loader2, label: "Running" },
  completed: { cls: "text-ok border-ok/40 bg-ok/10", icon: CircleCheck, label: "Completed" },
  failed: { cls: "text-sev-critical border-sev-critical/40 bg-sev-critical/10", icon: CircleX, label: "Failed" },
};

export function StatusBadge({ status }: { status: AuditStatus }) {
  const s = STATUS_STYLE[status];
  const Icon = s.icon;
  return (
    <span className={cn("inline-flex h-5 items-center gap-1 rounded-md border px-1.5 text-xs font-medium", s.cls)}>
      <Icon className={cn("size-3", status === "running" && "animate-spin")} aria-hidden />
      {s.label}
    </span>
  );
}

export function ScannerStatusBadge({ status }: { status: "ok" | "skipped" | "failed" }) {
  const map = {
    ok: { cls: "text-ok border-ok/40 bg-ok/10", icon: CircleCheck, label: "OK" },
    skipped: { cls: "text-warn border-warn/50 bg-warn/15", icon: MinusCircle, label: "Skipped" },
    failed: { cls: "text-sev-critical border-sev-critical/40 bg-sev-critical/10", icon: CircleX, label: "Failed" },
  }[status];
  const Icon = map.icon;
  return (
    <span className={cn("inline-flex h-5 items-center gap-1 rounded-md border px-1.5 text-xs font-medium", map.cls)}>
      <Icon className="size-3" aria-hidden />
      {map.label}
    </span>
  );
}

export function Pill({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-5 items-center rounded-md border bg-muted/50 px-1.5 text-xs text-muted-foreground whitespace-nowrap", className)}>
      {children}
    </span>
  );
}
