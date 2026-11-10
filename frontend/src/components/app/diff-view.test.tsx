import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { DiffView, parseDiff } from "./diff-view";

const DIFF = [
  "--- a/app/db.py",
  "+++ b/app/db.py",
  "@@ -3,4 +3,4 @@",
  " import sqlite3",
  "-def load(name):",
  "+def load(name: str):",
  "     return conn.execute(q)",
  "",
].join("\n");

describe("parseDiff", () => {
  it("classifies header, hunk, context, added and removed lines", () => {
    const rows = parseDiff(DIFF);
    expect(rows.map((r) => r.t)).toEqual(["meta", "meta", "hunk", "ctx", "del", "add", "ctx"]);
  });

  it("numbers removed lines against the old file and added lines against the new file", () => {
    const rows = parseDiff(DIFF);
    const del = rows.find((r) => r.t === "del");
    const add = rows.find((r) => r.t === "add");
    expect(del).toMatchObject({ text: "def load(name):", oldNo: 4, newNo: null });
    expect(add).toMatchObject({ text: "def load(name: str):", oldNo: null, newNo: 4 });
  });

  it("drops the trailing empty context row produced by the final newline", () => {
    const rows = parseDiff(DIFF);
    expect(rows[rows.length - 1].text).toBe("    return conn.execute(q)");
  });

  it("accepts CRLF line endings", () => {
    const rows = parseDiff(DIFF.replace(/\n/g, "\r\n"));
    expect(rows.find((r) => r.t === "add")?.text).toBe("def load(name: str):");
  });
});

describe("DiffView", () => {
  it("shows added and removed lines with a sign and an accessible label, and counts them", () => {
    render(<DiffView diff={DIFF} />);

    const added = screen.getByLabelText("added");
    const removed = screen.getByLabelText("removed");
    expect(added).toHaveTextContent("+");
    expect(removed).toHaveTextContent("-");
    expect(added.parentElement).toHaveTextContent("def load(name: str):");
    expect(removed.parentElement).toHaveTextContent("def load(name):");
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("-1")).toBeInTheDocument();
  });

  it("gives unchanged lines a different label from added and removed lines", () => {
    render(<DiffView diff={DIFF} />);
    expect(screen.getAllByLabelText("unchanged")).toHaveLength(2);
  });

  it("switches to a before/after layout and keeps both sides of a change", () => {
    render(<DiffView diff={DIFF} />);
    expect(screen.queryByText("Before")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Before / after" }));

    expect(screen.getByText("Before")).toBeInTheDocument();
    expect(screen.getByText("After")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Before / after" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("def load(name):")).toBeInTheDocument();
    expect(screen.getByText("def load(name: str):")).toBeInTheDocument();
  });

  it("returns to the unified layout from before/after", () => {
    render(<DiffView diff={DIFF} />);
    const group = screen.getByRole("group", { name: "Diff layout" });
    fireEvent.click(within(group).getByRole("button", { name: "Before / after" }));
    fireEvent.click(within(group).getByRole("button", { name: "Unified" }));
    expect(screen.getByLabelText("added")).toBeInTheDocument();
    expect(screen.queryByText("Before")).not.toBeInTheDocument();
  });
});
