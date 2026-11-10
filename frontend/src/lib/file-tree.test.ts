import { describe, expect, it } from "vitest";
import { buildTree, sortedChildren } from "./file-tree";

const files = [
  { path: "server/app.py", is_test: false },
  { path: "server/tests/test_app.py", is_test: true },
  { path: "README.md", is_test: false },
  { path: "client/src/index.ts", is_test: false },
];

describe("buildTree", () => {
  it("creates one node per path segment and attaches the file to the leaf only", () => {
    const root = buildTree(files);

    const server = root.children.get("server");
    expect(server).toBeDefined();
    expect(server?.path).toBe("server");
    expect(server?.file).toBeUndefined();

    const app = server?.children.get("app.py");
    expect(app?.path).toBe("server/app.py");
    expect(app?.file).toEqual({ path: "server/app.py", is_test: false });
  });

  it("keeps the is_test flag on test files", () => {
    const root = buildTree(files);
    const testFile = root.children.get("server")?.children.get("tests")?.children.get("test_app.py");
    expect(testFile?.file?.is_test).toBe(true);
  });

  it("shares folders between files in the same directory", () => {
    const root = buildTree(files);
    expect([...(root.children.get("server")?.children.keys() ?? [])].sort()).toEqual(["app.py", "tests"]);
  });

  it("returns an empty root for an empty file list", () => {
    const root = buildTree([]);
    expect(root.children.size).toBe(0);
    expect(root.file).toBeUndefined();
  });
});

describe("sortedChildren", () => {
  it("lists folders before files, each group alphabetically", () => {
    const root = buildTree(files);
    expect(sortedChildren(root).map((n) => n.name)).toEqual(["client", "server", "README.md"]);
  });

  it("sorts names alphabetically within a folder", () => {
    const root = buildTree([
      { path: "b.py", is_test: false },
      { path: "a.py", is_test: false },
      { path: "c/z.py", is_test: false },
      { path: "c/d.py", is_test: false },
    ]);
    expect(sortedChildren(root).map((n) => n.name)).toEqual(["c", "a.py", "b.py"]);
    expect(sortedChildren(root.children.get("c")!).map((n) => n.name)).toEqual(["d.py", "z.py"]);
  });
});
