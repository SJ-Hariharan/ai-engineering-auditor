import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ReportContext, type ReportCtx } from "./report-context";
import { FindingsTable, filterFindings, sortFindings } from "./findings-table";
import { makeFinding } from "@/test/fixtures";
import type { Finding } from "@/lib/types";

const FINDINGS: Finding[] = [
  makeFinding({
    id: "a",
    title: "SQL injection in login query",
    category: "security",
    severity: "critical",
    kind: "objective",
    file: "server/auth.py",
    line: 12,
    rule_id: "python.sql-injection",
    tool: "semgrep",
  }),
  makeFinding({
    id: "b",
    title: "Function too complex",
    category: "code_quality",
    severity: "medium",
    kind: "subjective",
    file: "server/reports.py",
    line: 80,
    rule_id: "high-complexity",
    tool: "analyzer",
  }),
  makeFinding({
    id: "c",
    title: "Circular import between api and db",
    category: "architecture",
    severity: "low",
    kind: "objective",
    file: "server/api.py",
    line: 3,
    rule_id: "import-cycle",
    tool: "analyzer",
  }),
];

function renderTable(findings = FINDINGS) {
  const openFinding = vi.fn();
  const ctx = { openFinding } as unknown as ReportCtx;
  render(
    <ReportContext.Provider value={ctx}>
      <FindingsTable findings={findings} />
    </ReportContext.Provider>,
  );
  return { openFinding };
}

function titles() {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("button")[0].textContent);
}

describe("filterFindings", () => {
  it("returns everything when all filters are neutral", () => {
    expect(filterFindings(FINDINGS, { cat: "all", sev: "all", kind: "all", q: "" })).toHaveLength(3);
  });

  it("filters by category, severity and kind together", () => {
    const r = filterFindings(FINDINGS, { cat: "security", sev: "critical", kind: "objective", q: "" });
    expect(r.map((f) => f.id)).toEqual(["a"]);
    expect(filterFindings(FINDINGS, { cat: "all", sev: "all", kind: "subjective", q: "" }).map((f) => f.id)).toEqual(["b"]);
  });

  it("matches the search text against title, file, rule id and tool, case-insensitively", () => {
    const search = (q: string) => filterFindings(FINDINGS, { cat: "all", sev: "all", kind: "all", q }).map((f) => f.id);
    expect(search("  SQL INJECTION ")).toEqual(["a"]);
    expect(search("reports.py")).toEqual(["b"]);
    expect(search("import-cycle")).toEqual(["c"]);
    expect(search("analyzer")).toEqual(["b", "c"]);
  });

  it("does not match a finding without a file against a file search", () => {
    const noFile = makeFinding({ id: "n", file: null, title: "Missing tests" });
    expect(filterFindings([noFile], { cat: "all", sev: "all", kind: "all", q: "server" })).toEqual([]);
  });

  it("keeps the input order and does not mutate it", () => {
    const input = [...FINDINGS];
    const r = filterFindings(input, { cat: "all", sev: "all", kind: "all", q: "" });
    expect(r.map((f) => f.id)).toEqual(["a", "b", "c"]);
    expect(input).toEqual(FINDINGS);
  });
});

describe("sortFindings", () => {
  it("keeps the API priority order for the priority sort", () => {
    const shuffled = [FINDINGS[2], FINDINGS[0], FINDINGS[1]];
    expect(sortFindings(shuffled, "priority").map((f) => f.id)).toEqual(["c", "a", "b"]);
  });

  it("sorts by severity, most severe first", () => {
    const shuffled = [FINDINGS[2], FINDINGS[1], FINDINGS[0]];
    expect(sortFindings(shuffled, "severity").map((f) => f.id)).toEqual(["a", "b", "c"]);
  });

  it("sorts by file, then by line", () => {
    const sameFile = [
      makeFinding({ id: "x", file: "a.py", line: 9 }),
      makeFinding({ id: "y", file: "a.py", line: 2 }),
      makeFinding({ id: "z", file: "b.py", line: 1 }),
    ];
    expect(sortFindings(sameFile, "file").map((f) => f.id)).toEqual(["y", "x", "z"]);
  });

  it("does not mutate its input", () => {
    const input = [FINDINGS[2], FINDINGS[0]];
    sortFindings(input, "severity");
    expect(input.map((f) => f.id)).toEqual(["c", "a"]);
  });
});

describe("FindingsTable", () => {
  it("lists all findings and the count", () => {
    renderTable();
    expect(screen.getByText("3 of 3 findings")).toBeInTheDocument();
    expect(titles()).toEqual([
      "SQL injection in login query",
      "Function too complex",
      "Circular import between api and db",
    ]);
  });

  it("narrows the rows as the search text changes", () => {
    renderTable();
    fireEvent.change(screen.getByLabelText("Search findings"), { target: { value: "circular" } });
    expect(screen.getByText("1 of 3 findings")).toBeInTheDocument();
    expect(titles()).toEqual(["Circular import between api and db"]);
  });

  it("applies the severity and kind selects", () => {
    renderTable();
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "objective" } });
    expect(titles()).toEqual(["SQL injection in login query", "Circular import between api and db"]);

    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "low" } });
    expect(titles()).toEqual(["Circular import between api and db"]);
  });

  it("applies the category select and shows the empty state when nothing matches", () => {
    renderTable();
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "security" } });
    expect(titles()).toEqual(["SQL injection in login query"]);

    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "info" } });
    expect(screen.getByText("Nothing to show")).toBeInTheDocument();
    expect(screen.getByText("0 of 3 findings")).toBeInTheDocument();
  });

  it("opens the finding when its title is clicked", () => {
    const { openFinding } = renderTable();
    fireEvent.click(screen.getByRole("button", { name: "Function too complex" }));
    expect(openFinding).toHaveBeenCalledWith(FINDINGS[1]);
  });
});
