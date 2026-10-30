import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { unwrap } from "@/lib/api";

export type RunView = components["schemas"]["RunView"];
export type SubmissionView = components["schemas"]["SubmissionView"];
export type SubmissionHistory = components["schemas"]["SubmissionHistory"];

/** What a verdict means, in words (FRONTEND_SPEC § 7.4). */
export const verdictText: Record<string, string> = {
  ACCEPTED: "Accepted",
  PARTIAL: "Partly correct",
  WRONG_ANSWER: "Wrong answer",
  COMPILE_ERROR: "Doesn't compile",
  RUNTIME_ERROR: "Crashed",
  TIME_LIMIT_EXCEEDED: "Too slow",
  MEMORY_LIMIT_EXCEEDED: "Too much memory",
  OUTPUT_LIMIT_EXCEEDED: "Too much output",
  INTERNAL_ERROR: "Couldn't be run (our problem)",
};

export const PLATFORM_FAILURE =
  "We couldn't run this. It's our problem, not yours. Your code is saved and will be re-run. It won't be scored zero.";

/**
 * Spaces, tabs and line endings made visible, so "3" and "3 " can be told apart: · for a space,
 * → for a tab, ↵ at the end of each line, ␍ for a Windows line ending.
 */
export function visible(text: string): string {
  return text.replace(/ /g, "·").replace(/\t/g, "→").replace(/\r/g, "␍").replace(/\n/g, "↵\n");
}

export interface DiffLine {
  expected: string | null;
  actual: string | null;
  same: boolean;
}

/** Expected and actual output side by side, line by line, marking the lines that differ. */
export function diffLines(expected: string, actual: string): DiffLine[] {
  const want = expected.split("\n");
  const got = actual.split("\n");
  const rows: DiffLine[] = [];
  for (let i = 0; i < Math.max(want.length, got.length); i++) {
    const e = i < want.length ? (want[i] ?? "") : null;
    const a = i < got.length ? (got[i] ?? "") : null;
    rows.push({ expected: e, actual: a, same: e === a });
  }
  // A final newline adds an empty last line: not worth showing as a difference.
  while (rows.length > 1) {
    const last = rows[rows.length - 1]!;
    if ((last.expected ?? "") === "" && (last.actual ?? "") === "") rows.pop();
    else break;
  }
  return rows;
}

/** "3 s", "1 min 5 s" since a moment, for "Running — 4 s". */
export function elapsed(fromMs: number, nowMs: number): string {
  const s = Math.max(0, Math.floor((nowMs - fromMs) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

/** The submissions of one coding question (also read by the navigator for its "submitted" tick). */
export function historyKey(attemptId: string, examQuestionId: string) {
  return ["submissions", attemptId, examQuestionId];
}

export async function fetchHistory(attemptId: string, examQuestionId: string) {
  return unwrap(
    await api.GET("/api/v1/attempts/{attempt_id}/questions/{exam_question_id}/submissions", {
      params: { path: { attempt_id: attemptId, exam_question_id: examQuestionId } },
    }),
  );
}
