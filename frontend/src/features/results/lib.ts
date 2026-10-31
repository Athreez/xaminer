import type { components } from "@/api/schema";

export type ExamResults = components["schemas"]["ExamResults"];
export type ResultRow = components["schemas"]["ResultRow"];
export type GradingQueue = components["schemas"]["GradingQueue"];
export type QuestionResult = components["schemas"]["QuestionResult"];
export type TeacherQuestionResult = components["schemas"]["TeacherQuestionResult"];

/** Grading status in words (FRONTEND_SPEC § 3). */
export const gradingLabel: Record<string, string> = {
  PENDING: "Pending",
  AWAITING_CODING: "Awaiting code evaluation",
  AWAITING_MANUAL: "Awaiting marking",
  COMPLETE: "Complete",
};

export const typeLabel: Record<string, string> = {
  MCQ: "Single choice",
  MSQ: "Multiple choice",
  TRUE_FALSE: "True / False",
  DESCRIPTIVE: "Written answer",
  CODING: "Coding",
};

/** "7.5" for "7.50", "10" for "10.00": scores read better without trailing zeros. */
export function score(value: string | null | undefined): string {
  if (value == null) return "—";
  return String(Number(value));
}

export function passLabel(passed: boolean | null | undefined): string {
  return passed == null ? "—" : passed ? "Pass" : "Fail";
}

/** A mark the teacher typed: a number from 0 to points with at most 2 decimals, or why not. */
export function markProblem(text: string, points: string): string | null {
  const trimmed = text.trim();
  if (!trimmed) return "Enter a mark.";
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return "Use a number like 4 or 4.5 (2 decimals at most).";
  if (Number(trimmed) > Number(points)) return `The most this question gives is ${score(points)}.`;
  return null;
}

/** Integrity outcome in words (PRD PRC-11); never changes the score. */
export const integrityLabel: Record<string, string> = {
  NO_CONCERNS: "No concerns",
  PENDING_REVIEW: "Pending review",
  CONCERNS_CONFIRMED: "Concerns confirmed",
};

export const eventLabel: Record<string, string> = {
  TAB_SWITCH: "Left the exam page",
  FULLSCREEN_EXIT: "Left fullscreen",
  PASTE_BLOCKED: "Paste from outside blocked",
  MULTIPLE_SCREENS: "More than one screen",
  FACE_ABSENT: "No face on camera",
  MULTIPLE_FACES: "Another person on camera",
  GAZE_AWAY: "Head turned away",
  VOICE_DETECTED: "Talking",
  SCREEN_SHARE_STOPPED: "Stopped sharing the screen",
  SIGNAL_LOST: "Proctoring stopped",
  PHONE_DETECTED: "Phone on camera",
  BOOK_DETECTED: "Book on camera",
};
