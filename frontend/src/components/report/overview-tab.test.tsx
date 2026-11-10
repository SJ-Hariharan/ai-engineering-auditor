import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReportContext, type ReportCtx } from "./report-context";
import { OverviewTab } from "./overview-tab";
import type { AuditSummary, Category, CategoryScore } from "@/lib/types";

function cat(label: string, extra: Partial<CategoryScore> = {}): CategoryScore {
  return { label, score: 100, grade: "A", weight: 0.2, deduction: 0, counts: {}, ...extra };
}

function summary(scores: Partial<AuditSummary["scores"]>, categories: Partial<Record<Category, CategoryScore>> = {}) {
  return {
    scanners: [],
    stack: { languages: [], frameworks: [], databases: [], manifests: [], package_managers: [], test_frameworks: [], containerized: false },
    inventory: { total_files: 0, source_files: 0, total_lines: 0, skipped_large_files: 0, tree: [] },
    entry_points: [],
    overview: { paragraphs: [], largest_areas: [], generated_by: "deterministic" },
    counts: { total: 0, by_severity: {}, by_category: {} },
    comparison: null,
    scores: {
      overall: 100,
      grade: "A",
      methodology: {} as AuditSummary["scores"]["methodology"],
      ...scores,
      categories: {
        security: cat("Security"),
        reliability: cat("Testing & Reliability"),
        architecture: cat("Architecture"),
        code_quality: cat("Code Quality"),
        maintainability: cat("Maintainability"),
        ...categories,
      },
    },
  } as unknown as AuditSummary;
}

function renderWith(s: AuditSummary) {
  const ctx = { summary: s, findings: [], findingsLoading: false, goTab: () => {}, openFinding: () => {} } as unknown as ReportCtx;
  return render(
    <ReportContext.Provider value={ctx}>
      <OverviewTab />
    </ReportContext.Provider>,
  );
}

describe("OverviewTab scores (SC-01/SC-02)", () => {
  it("shows not-analysed categories as N/A, excluded from the overall, with the reason", () => {
    renderWith(
      summary(
        { overall: 81.9, grade: "B", not_analysed: ["architecture"] },
        {
          architecture: cat("Architecture", { score: null, grade: "N/A", status: "not_analysed", note: "No supported source files were parsed." }),
          security: cat("Security", { score: 81.9, grade: "B", effective_weight: 0.375, merged_duplicates: 3 }),
        },
      ),
    );
    expect(screen.getByText("Not analysed")).toBeInTheDocument();
    expect(screen.getByLabelText("Grade N/A")).toBeInTheDocument();
    expect(screen.getByText("No supported source files were parsed.")).toBeInTheDocument();
    expect(screen.getByText("Excluded from the overall score")).toBeInTheDocument();
    expect(screen.getByText(/Weight 38% · 3 same-line duplicates scored once/)).toBeInTheDocument();
  });

  it("explains a capped overall score and marks an incomplete category", () => {
    renderWith(
      summary(
        {
          overall: 79.9,
          grade: "C",
          uncapped_overall: 89.8,
          caps: [{ reason: "critical", max: 79.9, note: "1 high-confidence critical finding(s): the grade cannot be above C." }],
        },
        { security: cat("Security", { score: 65.9, grade: "D", status: "incomplete", note: "Did not run successfully: semgrep (failed)." }) },
      ),
    );
    const caps = screen.getByRole("list", { name: "Score caps" });
    expect(caps).toHaveTextContent("Capped at 79.9 (was 89.8): 1 high-confidence critical finding(s)");
    expect(screen.getByText("incomplete")).toBeInTheDocument();
    expect(screen.getByText("Did not run successfully: semgrep (failed).")).toBeInTheDocument();
  });

  it("renders without a score when nothing could be analysed", () => {
    renderWith(summary({ overall: null, grade: "N/A" }));
    expect(screen.getByText(/Nothing in this repository could be analysed/)).toBeInTheDocument();
  });

  it("still renders audits scored before SC-01 (no status, caps or effective weights)", () => {
    renderWith(summary({ overall: 89.8, grade: "B" }));
    expect(screen.queryByRole("list", { name: "Score caps" })).toBeNull();
    expect(screen.queryByText("Not analysed")).toBeNull();
    expect(screen.getAllByText("Weight 20%")).toHaveLength(5);
  });
});
