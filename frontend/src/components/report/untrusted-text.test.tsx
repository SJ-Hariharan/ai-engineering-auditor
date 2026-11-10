import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReportContext, type ReportCtx } from "./report-context";
import { FindingsTable } from "./findings-table";
import { CodeBlock, CodeView } from "@/components/app/code-view";
import { makeFinding } from "@/test/fixtures";

// Finding titles, evidence and source files come from the scanned repository, so they are
// untrusted. React must render them as text: no element may be created from them.
const PAYLOAD = "<img src=x onerror=alert(1)>";

describe("repository-derived text", () => {
  it("renders finding titles, rule ids and evidence as literal text, not markup", () => {
    const finding = makeFinding({
      title: PAYLOAD,
      evidence: PAYLOAD,
      rule_id: PAYLOAD,
      file: "app/<img src=x onerror=alert(2)>.py",
      line: 1,
      end_line: 1,
    });
    const ctx = { openFinding: vi.fn() } as unknown as ReportCtx;

    const { container } = render(
      <ReportContext.Provider value={ctx}>
        <FindingsTable findings={[finding]} />
        <CodeBlock>{finding.evidence}</CodeBlock>
        <CodeView content={PAYLOAD} findings={[finding]} />
      </ReportContext.Provider>,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
    expect(screen.getAllByText(PAYLOAD).length).toBeGreaterThan(0);
    expect(screen.getByText(/app\/<img src=x onerror=alert\(2\)>\.py/)).toBeInTheDocument();
  });
});
