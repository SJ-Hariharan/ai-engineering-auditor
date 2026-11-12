// Mirrors docs/API.md exactly. Keep in sync with the backend contract.

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Category =
  | "security"
  | "architecture"
  | "code_quality"
  | "reliability"
  | "maintainability";
export type Confidence = "high" | "medium" | "low";
export type FindingKind = "objective" | "subjective";
export type AuditStatus = "queued" | "running" | "completed" | "failed";

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export type FindingCounts = Partial<Record<Severity, number>>;

export interface AuditBrief {
  id: string;
  status: AuditStatus;
  stage: string | null;
  error: string | null;
  commit_sha: string | null;
  created_at: string;
  finished_at: string | null;
  overall_score: number | null;
  finding_counts: FindingCounts;
}

export interface Project {
  id: string;
  name: string;
  source_type: "github" | "zip";
  source_url: string | null;
  default_branch: string | null;
  llm_consent: boolean;
  llm_consent_at: string | null;
  created_at: string;
  latest_audit: AuditBrief | null;
}

export interface ProjectDetail extends Project {
  audits: AuditBrief[];
}

export interface Finding {
  id: string;
  fingerprint: string;
  tool: string;
  rule_id: string;
  category: Category;
  severity: Severity;
  confidence: Confidence;
  kind: FindingKind;
  principle: string | null;
  title: string;
  file: string | null;
  line: number | null;
  end_line: number | null;
  evidence: string;
  explanation: string;
  impact: string;
  remediation: string;
  references: string[];
  /** A fix proposal was already generated for this finding. */
  has_fix: boolean;
  /** A deterministic (non-AI) fixer exists; otherwise suggesting a fix needs AI consent. */
  fixable: boolean;
}

export interface CodeSymbol {
  name: string;
  kind: "class" | "function" | "method" | "arrow";
  line: number;
  end_line: number;
  params?: number;
  complexity?: number;
  methods?: number;
  parent?: string | null;
}

export interface FileContent {
  path: string;
  language: string | null;
  content: string;
  truncated: boolean;
  symbols: CodeSymbol[];
  findings: Finding[];
}

export interface StackSummary {
  languages: { name: string; files: number; lines: number | null }[];
  frameworks: string[];
  test_frameworks: string[];
  databases: string[];
  package_managers: string[];
  manifests: string[];
  containerized: boolean;
}

export interface FileInfo {
  path: string;
  language: string | null;
  lines: number;
  is_test: boolean;
  functions: number;
  classes: number;
  fan_in?: number;
  fan_out?: number;
  instability?: number;
}

export interface GraphDirNode {
  id: string;
  files: number;
}
export interface GraphDirEdge {
  source: string;
  target: string;
  weight: number;
}
export interface GraphFileNode {
  id: string;
  group: string;
  test: boolean;
}

export interface ArchitectureSummary {
  edges: number;
  cycles: string[][];
  external_dependencies: { name: string; imports: number }[];
  graph: {
    directories: { nodes: GraphDirNode[]; edges: GraphDirEdge[] };
    files: {
      truncated: boolean;
      nodes: GraphFileNode[];
      edges: { source: string; target: string }[];
    };
  };
}

export interface QualitySummary {
  functions: number;
  classes: number;
  avg_complexity: number;
  complex_functions: number;
  long_functions: number;
  hotspots: {
    file: string;
    name: string;
    line: number;
    complexity: number;
    lines: number;
  }[];
  thresholds: Record<string, number>;
}

export type TestRunStatus =
  | "running"
  | "passed"
  | "failed"
  | "timeout"
  | "skipped";

export interface TestRun {
  status: TestRunStatus;
  reason?: string;
  runtime?: string;
  counts?: Record<string, number>;
  coverage?: {
    percent: number;
    covered_lines: number;
    statements: number;
  } | null;
  test?: {
    exit_code: number;
    timed_out: boolean;
    duration_s: number;
    output: string;
  };
  isolation?: string;
  started_at: string;
  finished_at: string;
}

export interface TestingSummary {
  test_files: number;
  source_files: number;
  test_lines: number;
  source_lines: number;
  frameworks: string[];
  referenced_modules: number;
  untested_modules: { file: string; lines: number }[];
  static_coverage_pct: number | null;
  method: string;
  run?: TestRun | null;
}

export interface Route {
  method: string;
  path: string;
  file: string;
  line: number;
  handler: string | null;
}

export interface DataFlowSummary {
  routes: Route[];
  data_access: string[];
  external_calls: string[];
  flows: { from: string; to: string; path: string[]; kind: string }[];
  method: string;
}

export interface ScannerStatus {
  name: string;
  status: "ok" | "skipped" | "failed";
  version: string | null;
  duration_s: number;
  message: string;
  findings: number;
}

export interface CategoryScore {
  label: string;
  /** null when nothing in this category could be analysed (SC-01). */
  score: number | null;
  /** "N/A" when score is null. */
  grade: string;
  /** Absent on audits scored before SC-01. */
  status?: "scored" | "incomplete" | "not_analysed";
  note?: string;
  weight: number;
  /** Share of the overall score after not-analysed categories are excluded. */
  effective_weight?: number;
  deduction: number;
  counts: FindingCounts;
  /** Findings at the same file and line as a more severe one, scored once (SC-02). */
  merged_duplicates?: number;
}

export interface ScoreCap {
  reason: "critical" | "incomplete";
  max: number;
  note: string;
}

export interface Methodology {
  summary: string;
  severity_points: Record<Severity, number>;
  confidence_factor: Record<Confidence, number>;
  weights: Record<Category, number>;
  formula: string;
  limitations: string[];
}

export interface Comparison {
  previous_audit_id: string;
  previous_score: number | null;
  resolved: number;
  new: number;
  persisting: number;
  resolved_findings: {
    title: string;
    severity: Severity;
    file: string | null;
    category: Category;
  }[];
}

export interface AuditSummary {
  stack: StackSummary;
  inventory: {
    total_files: number;
    source_files: number;
    total_lines: number;
    skipped_large_files: number;
    tree: { path: string; files: number; lines: number; tests: number }[];
  };
  entry_points: { file: string | null; kind: string; reason: string }[];
  files: FileInfo[];
  symbols: Record<string, CodeSymbol[]>;
  architecture: ArchitectureSummary;
  quality: QualitySummary;
  testing: TestingSummary;
  data_flow: DataFlowSummary;
  /** Absent on audits created before the design analyzer existed. */
  design?: DesignSummary;
  scanners: ScannerStatus[];
  /** Scanner-suppression directives found in the repo (ignored). Absent on older audits. */
  suppressions?: SuppressionSummary;
  scores: {
    /** null when no category could be analysed. */
    overall: number | null;
    grade: string;
    /** The following fields are absent on audits scored before SC-01. */
    uncapped_overall?: number | null;
    caps?: ScoreCap[];
    complete?: boolean;
    not_analysed?: Category[];
    categories: Record<Category, CategoryScore>;
    methodology: Methodology;
  };
  counts: {
    total: number;
    by_severity: Partial<Record<Severity, number>>;
    by_category: Partial<Record<Category, number>>;
  };
  overview: {
    paragraphs: string[];
    largest_areas: { path: string; files: number; lines: number }[];
    generated_by: "deterministic";
  };
  comparison: Comparison | null;
}

export interface Audit {
  id: string;
  project_id: string;
  previous_audit_id: string | null;
  status: AuditStatus;
  stage: string | null;
  error: string | null;
  commit_sha: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  workspace_available: boolean;
  // Empty object (not a full summary) while queued/running/failed.
  summary: Partial<AuditSummary>;
}

/** Small polling payload from GET /api/audits/{id}/status. */
export interface AuditStatusInfo {
  id: string;
  status: AuditStatus;
  stage: string | null;
  error: string | null;
  finished_at: string | null;
  test_run: TestRun | null;
}

export type FixStatus = "pending" | "approved" | "rejected";

export interface Fix {
  id: string;
  finding_id: string;
  file: string;
  diff: string;
  rationale: string;
  source: "deterministic" | "ai";
  generator: string;
  caveats: string[];
  status: FixStatus;
  created_at: string;
}

export interface PullRequest {
  id: string;
  url: string;
  branch: string;
  fix_ids: string[];
  created_at: string;
}

export interface AIStatus {
  provider: "anthropic" | "openai" | "none";
  configured: boolean;
  model: string;
}

export type ExplainKind = "overview" | "file" | "symbol" | "questions" | "finding";

export interface OverviewContent {
  summary: string;
  architecture: string;
  data_flow: string[];
  key_modules: { path: string; role: string }[];
  design_decisions: { decision: string; evidence: string; confidence: string }[];
  risks: string[];
}
export interface FileContentAI {
  purpose: string;
  how_it_works: string[];
  key_symbols: { name: string; explanation: string }[];
  dependencies: string | string[];
  gotchas: string[];
}
export interface SymbolContentAI {
  purpose: string;
  inputs: string | string[];
  outputs: string | string[];
  steps: string[];
  side_effects: string[];
  edge_cases: string[];
}
export interface QuestionsContent {
  questions: {
    question: string;
    why_it_matters: string;
    answer: string;
    related_files: string[];
    difficulty: string;
  }[];
}
export interface FindingContentAI {
  plain_explanation: string;
  failure_or_attack_scenario: string;
  likely_false_positive: boolean | string;
  false_positive_reasoning: string;
  fix_steps: string[];
}

export interface AIArtifact<C = unknown> {
  id: string;
  kind: ExplainKind;
  target: string | null;
  provider: string;
  model: string;
  content: C;
  created_at: string;
}

export const CATEGORIES: Category[] = [
  "security",
  "reliability",
  "architecture",
  "code_quality",
  "maintainability",
];
export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];

export interface DesignModel {
  name: string;
  file: string;
  line: number;
  orm: string;
  fields: string[];
  relations: { field: string; target: string; kind: string }[];
}

export interface DesignEndpoint {
  method: string;
  path: string;
  file: string;
  line: number;
  handler: string | null;
}

export interface DesignSummary {
  models: DesignModel[];
  models_total: number;
  orms: string[];
  migrations: string[];
  api: {
    endpoints: DesignEndpoint[];
    count: number;
    by_method: Record<string, number>;
    mutating_endpoints: number;
    unauth_candidates: number;
    unauth_findings_shown: number;
    global_auth_middleware_detected: boolean;
  };
  method: string;
}

export interface SuppressionSummary {
  honoured: boolean;
  files: { file: string; scanner: string }[];
  inline: Record<string, number>;
  examples: { file: string; line: number; marker: string }[];
  total: number;
  note: string;
}
