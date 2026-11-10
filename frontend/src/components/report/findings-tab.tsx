"use client";

import { useReport } from "./report-context";
import { ErrorNote } from "@/components/app/common";
import { FindingsTable } from "./findings-table";

export function FindingsTab() {
  const { findings, findingsLoading, findingsError } = useReport();
  if (findingsLoading) return <p className="text-sm text-muted-foreground">Loading findings…</p>;
  if (findingsError) return <ErrorNote error={findingsError} />;
  return <FindingsTable findings={findings} emptyText="No findings match these filters." />;
}
