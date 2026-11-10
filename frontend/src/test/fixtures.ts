import type { Finding } from "@/lib/types";

/** A valid Finding (matches src/lib/types.ts) with overrides for the fields a test cares about. */
export function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: "f-1",
    fingerprint: "fp-1",
    tool: "semgrep",
    rule_id: "python.sql-injection",
    category: "security",
    severity: "high",
    confidence: "high",
    kind: "objective",
    principle: null,
    title: "SQL injection in login query",
    file: "server/auth.py",
    line: 10,
    end_line: 10,
    evidence: "cursor.execute(f\"SELECT * FROM users WHERE id={uid}\")",
    explanation: "User input is concatenated into SQL.",
    impact: "Data disclosure.",
    remediation: "Use parameterised queries.",
    references: [],
    has_fix: false,
    fixable: true,
    ...overrides,
  };
}
