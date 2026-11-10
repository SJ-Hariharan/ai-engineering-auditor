import { cn } from "@/lib/utils";

export function scoreTone(score: number): { bar: string; text: string } {
  if (score >= 80) return { bar: "bg-ok", text: "text-ok" };
  if (score >= 55) return { bar: "bg-warn", text: "text-warn" };
  return { bar: "bg-sev-critical", text: "text-sev-critical" };
}

export function ScoreBar({ score, className }: { score: number; className?: string }) {
  const tone = scoreTone(score);
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
      role="progressbar"
      aria-valuenow={Math.round(score)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={cn("h-full rounded-full", tone.bar)} style={{ width: `${Math.max(1, Math.min(100, score))}%` }} />
    </div>
  );
}

export function GradeBadge({ grade, score, className }: { grade: string; score?: number; className?: string }) {
  const tone = score != null ? scoreTone(score) : { text: "text-foreground" };
  return (
    <span
      className={cn(
        "inline-flex size-7 items-center justify-center rounded-md border bg-muted/40 text-sm font-semibold",
        tone.text,
        className,
      )}
      aria-label={`Grade ${grade}`}
    >
      {grade}
    </span>
  );
}
