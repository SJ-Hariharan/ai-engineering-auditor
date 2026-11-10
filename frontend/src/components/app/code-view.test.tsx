import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CodeView } from "./code-view";
import { makeFinding } from "@/test/fixtures";

const CONTENT = ["import os", "", "def run(cmd):", "    os.system(cmd)", "    return 0", ""].join("\n");

function row(container: HTMLElement, n: number) {
  const el = container.querySelector<HTMLElement>(`[data-line="${n}"]`);
  if (!el) throw new Error(`no row for line ${n}`);
  return el;
}

describe("CodeView", () => {
  it("renders every line with its 1-based line number", () => {
    const { container } = render(<CodeView content={CONTENT} />);
    expect(container.querySelectorAll("[data-line]")).toHaveLength(6);
    expect(row(container, 1)).toHaveTextContent("import os");
    expect(row(container, 3)).toHaveTextContent("def run(cmd):");
    expect(row(container, 4).textContent).toContain("4");
  });

  it("normalises CRLF line endings", () => {
    const { container } = render(<CodeView content={"a\r\nb\r\n"} />);
    expect(container.querySelectorAll("[data-line]")).toHaveLength(3);
    expect(row(container, 2)).toHaveTextContent("b");
  });

  it("marks the lines that have findings with a clickable gutter marker", () => {
    const finding = makeFinding({ title: "Shell command injection", severity: "critical", line: 4, end_line: 4 });
    render(<CodeView content={CONTENT} findings={[finding]} />);

    const marker = screen.getByRole("button", { name: "Open finding: Shell command injection (Critical)" });
    expect(marker.closest("[data-line]")).toHaveAttribute("data-line", "4");
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("calls onFindingClick with the finding when its marker is clicked", () => {
    const onFindingClick = vi.fn();
    const finding = makeFinding({ title: "Shell command injection", line: 4, end_line: 4 });
    render(<CodeView content={CONTENT} findings={[finding]} onFindingClick={onFindingClick} />);

    fireEvent.click(screen.getByRole("button", { name: /Open finding: Shell command injection/ }));
    expect(onFindingClick).toHaveBeenCalledWith(finding);
  });

  it("shades every line in a multi-line finding range and marks only its first line", () => {
    const finding = makeFinding({ title: "Long block", severity: "high", line: 2, end_line: 4 });
    const { container } = render(<CodeView content={CONTENT} findings={[finding]} />);

    for (const n of [2, 3, 4]) expect(row(container, n).className).toMatch(/bg-muted\/60/);
    expect(row(container, 1).className).not.toMatch(/bg-muted\/60/);
    expect(row(container, 5).className).not.toMatch(/bg-muted\/60/);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(row(container, 2).querySelector("button")).not.toBeNull();
    expect(row(container, 3).querySelector("button")).toBeNull();
  });

  it("highlights the focused line", () => {
    const { container } = render(<CodeView content={CONTENT} focusLine={4} />);
    expect(row(container, 4).className).toMatch(/bg-brand\/15/);
    expect(row(container, 3).className).not.toMatch(/bg-brand\/15/);
  });

  it("does not create a marker for findings without a line", () => {
    render(<CodeView content={CONTENT} findings={[makeFinding({ line: null, end_line: null })]} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
