/** Folder/file tree for the code tab, built from the audit's flat file list. */

export interface TreeNode {
  name: string;
  path: string;
  children: Map<string, TreeNode>;
  file?: { path: string; is_test: boolean };
}

export function buildTree(files: { path: string; is_test: boolean }[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map() };
  for (const f of files) {
    const parts = f.path.split("/");
    let cur = root;
    parts.forEach((p, i) => {
      const path = parts.slice(0, i + 1).join("/");
      let next = cur.children.get(p);
      if (!next) {
        next = { name: p, path, children: new Map() };
        cur.children.set(p, next);
      }
      if (i === parts.length - 1) next.file = f;
      cur = next;
    });
  }
  return root;
}

/** Folders first, then files; each group sorted by name. */
export function sortedChildren(n: TreeNode): TreeNode[] {
  return [...n.children.values()].sort((a, b) => Number(!!a.file) - Number(!!b.file) || a.name.localeCompare(b.name));
}
