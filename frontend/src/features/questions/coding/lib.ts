import type { components } from "@/api/schema";

export type CodingView = components["schemas"]["CodingView"];
export type CodingIn = components["schemas"]["CodingIn"];
export type TestCase = components["schemas"]["TestCaseView"];
export type Language = components["schemas"]["LanguageView"];
export type ComparisonMode = CodingView["comparison_mode"];

/** One line per comparison mode (FRONTEND_SPEC § 5.3; PRD § 6.2). */
export const comparisonText: Record<ComparisonMode, string> = {
  TRIM: "Ignore line endings, spaces at the end of lines and blank lines at the end (recommended)",
  EXACT: "Character for character",
  TOKEN: "Same words and numbers in the same order, however they're spaced",
  NUMERIC: "Like the previous one, and numbers may differ by up to 0.000001",
};

export const statusText: Record<CodingView["validation_status"], string> = {
  NEEDS_VALIDATION: "Not validated",
  VALIDATING: "Validating…",
  PASSED: "Passed",
  FAILED: "Failed",
};

export const outcomeText: Record<string, string> = {
  PASSED: "Passed",
  WRONG_ANSWER: "Wrong answer",
  RUNTIME_ERROR: "Crashed",
  TIME_LIMIT_EXCEEDED: "Too slow",
  MEMORY_LIMIT_EXCEEDED: "Too much memory",
  OUTPUT_LIMIT_EXCEEDED: "Too much output",
};

/** A language's real time limit (PRD CQ-03). */
export function effectiveMs(limitMs: number, multiplier: number): number {
  return Math.floor(limitMs * multiplier);
}

/** "12 B", "3.4 KB", "1.0 MB" for the size of a test case's text. */
export function sizeText(text: string): string {
  const bytes = new TextEncoder().encode(text).length;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** The PUT body: the saved setup with some fields changed (PUT replaces all of it). */
export function codingBody(saved: CodingView, changes: Partial<CodingIn>): CodingIn {
  return {
    input_format: saved.input_format,
    output_format: saved.output_format,
    constraints: saved.constraints,
    allowed_languages: saved.allowed_languages,
    time_limit_ms: saved.time_limit_ms,
    memory_limit_mb: saved.memory_limit_mb,
    comparison_mode: saved.comparison_mode,
    partial_scoring: saved.partial_scoring,
    run_code_allowed: saved.run_code_allowed,
    max_submissions: saved.max_submissions,
    ...changes,
  };
}

export interface LanguageReport {
  status: "PASSED" | "FAILED" | "ERROR";
  time_limit_ms: number;
  compile_output: string | null;
  error?: string;
  cases: {
    name: string;
    hidden: boolean;
    outcome: string;
    time_ms: number;
    slow: boolean;
    stdout: string | null;
    stderr: string | null;
  }[];
  warnings: string[];
}

export interface ValidationReport {
  run: string;
  pending: string[];
  languages: Record<string, LanguageReport>;
  warnings?: string[];
}
