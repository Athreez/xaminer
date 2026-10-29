import type { ApiError } from "@/api/client";
import type { components } from "@/api/schema";

export type Question = components["schemas"]["QuestionView"];
export type QuestionSummary = components["schemas"]["QuestionSummary"];
export type StudentQuestion = components["schemas"]["StudentQuestion"];
export type QuestionType = Question["type"];
export type Visibility = Question["visibility"];

/** A student's answer to one question, as the attempt API stores it. */
export interface AnswerValue {
  selected_option_ids: string[] | null;
  text_answer: string | null;
}

export const NO_ANSWER: AnswerValue = { selected_option_ids: null, text_answer: null };

/** The multiple-choice marking rule in one sentence (PRD § 6.1). */
export function msqRule(scoring: StudentQuestion["msq_scoring"]): string {
  return scoring === "PARTIAL"
    ? "Tick every correct option: each one you tick earns its share of the marks, but any wrong tick loses them all."
    : "Tick every correct option: marks are given only if you tick exactly the correct ones.";
}

/** Types teachers can create here. Coding questions get their own editor (E07). */
export const EDITABLE_TYPES = ["MCQ", "MSQ", "TRUE_FALSE", "DESCRIPTIVE"] as const;

export const typeLabel: Record<QuestionType, string> = {
  MCQ: "Single choice",
  MSQ: "Multiple choice",
  TRUE_FALSE: "True / False",
  DESCRIPTIVE: "Descriptive",
  CODING: "Coding",
};

export const typeHint: Record<QuestionType, string> = {
  MCQ: "2 to 10 options, exactly one correct.",
  MSQ: "2 to 10 options, one or more correct.",
  TRUE_FALSE: "Mark True or False as the correct answer.",
  DESCRIPTIVE: "A written answer, graded by hand with your rubric.",
  CODING: "Code, run against test cases.",
};

export const visibilityLabel: Record<Visibility, string> = {
  PRIVATE: "Only me",
  INSTITUTION: "Shared with my institution",
};

/**
 * The API's field errors keyed by form field, e.g. `points`, `options`, `options.1.label`.
 * Request-shape errors arrive as `body.points`; question rules as `points`. Both map the same.
 */
export function fieldErrors(error: unknown): Record<string, string> {
  const details = (error as ApiError | undefined)?.error?.details ?? [];
  const out: Record<string, string> = {};
  for (const detail of details as { field?: string; message?: string }[]) {
    if (!detail.field || !detail.message) continue;
    const field = detail.field.replace(/^body\./, "");
    out[field] ??= detail.message;
  }
  return out;
}

/** "arrays, Easy ,arrays" → ["arrays", "easy"] (the server lower-cases too). */
export function parseTags(text: string): string[] {
  return [
    ...new Set(
      text
        .split(",")
        .map((t) => t.trim().toLowerCase())
        .filter(Boolean),
    ),
  ];
}

/** Insert `snippet` at the cursor of a textarea's value, on its own line. */
export function insertAt(value: string, start: number, end: number, snippet: string): string {
  const before = value.slice(0, start);
  const after = value.slice(end);
  const lead = before && !before.endsWith("\n") ? "\n" : "";
  const trail = after && !after.startsWith("\n") ? "\n" : "";
  return `${before}${lead}${snippet}${trail}${after}`;
}
