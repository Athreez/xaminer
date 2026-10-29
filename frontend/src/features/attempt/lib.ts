import type { components } from "@/api/schema";
import type { AnswerValue } from "@/features/questions/lib";

import type { Entry } from "./sync/outbox";

export type AttemptView = components["schemas"]["AttemptView"];
export type AttemptItem = components["schemas"]["AttemptItem"];
export type Heartbeat = components["schemas"]["HeartbeatOut"];

// ----------------------------------------------------------------------------- answers

export function isAnswered(answer: AnswerValue | null | undefined): boolean {
  return Boolean(answer?.selected_option_ids?.length || answer?.text_answer?.trim());
}

export interface Restored {
  answers: Record<string, AnswerValue>;
  flags: Record<string, boolean>;
  /** The highest revision the server already has; new changes must go above it. */
  revision: number;
}

/**
 * What the student sees on (re)opening the exam: the server's answers and flags, with anything
 * still waiting on this device laid on top (it is newer: the server never saw it).
 */
export function restore(items: AttemptItem[], pending: Entry[]): Restored {
  const answers: Record<string, AnswerValue> = {};
  const flags: Record<string, boolean> = {};
  let revision = 0;
  for (const item of items) {
    flags[item.exam_question_id] = item.marked_for_review;
    if (item.answer) {
      answers[item.exam_question_id] = {
        selected_option_ids: item.answer.selected_option_ids,
        text_answer: item.answer.text_answer,
      };
      revision = Math.max(revision, item.answer.client_revision);
    }
  }
  for (const entry of pending) {
    if (entry.kind === "answer") {
      answers[entry.target] = {
        selected_option_ids: (entry.payload.selected_option_ids as string[] | null) ?? null,
        text_answer: (entry.payload.text_answer as string | null) ?? null,
      };
    } else if (entry.kind === "flag") {
      flags[entry.target] = Boolean(entry.payload.marked);
    }
  }
  return { answers, flags, revision };
}

// ----------------------------------------------------------------------------- navigator

/** Navigator states (FRONTEND_SPEC § 6.4), each with its own shape, never colour alone. */
export type NavState = "not-visited" | "not-answered" | "answered" | "marked" | "answered-marked";

export function navState(answered: boolean, marked: boolean, visited: boolean): NavState {
  if (marked) return answered ? "answered-marked" : "marked";
  if (answered) return "answered";
  return visited ? "not-answered" : "not-visited";
}

export const navStateText: Record<NavState, string> = {
  "not-visited": "not visited",
  "not-answered": "not answered",
  answered: "answered",
  marked: "marked for review",
  "answered-marked": "answered, marked for review",
};

/** Screen reader name, e.g. "Question 7, answered, marked for review". */
export function navLabel(number: number, state: NavState, locked = false): string {
  return `Question ${number}, ${navStateText[state]}${locked ? ", can't go back" : ""}`;
}

/** Sequential exams go forward only: questions before the furthest one reached are closed. */
export function canOpen(sequential: boolean, index: number, furthest: number): boolean {
  return !sequential || index >= furthest;
}

// ----------------------------------------------------------------------------- timer

/** "1:24:37", or "09:05" under an hour. */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

export type TimerLevel = "normal" | "warning" | "danger";

/** Warning style from 10 minutes left, danger from 2 (FRONTEND_SPEC § 6.3). */
export function timerLevel(seconds: number): TimerLevel {
  if (seconds <= 120) return "danger";
  if (seconds <= 600) return "warning";
  return "normal";
}

/** Minutes left at which screen readers hear the time; never every second. */
const ANNOUNCE_AT = [30, 15, 10, 5, 2, 1];

/** What to announce when the timer moves from `before` to `now` seconds left, if anything. */
export function timeAnnouncement(before: number, now: number): string | null {
  const crossed = ANNOUNCE_AT.filter((m) => before > m * 60 && now <= m * 60);
  if (crossed.length === 0) return null;
  const minutes = Math.min(...crossed);
  return `${minutes} ${minutes === 1 ? "minute" : "minutes"} left`;
}

// ----------------------------------------------------------------------------- connection

export type Connection = "online" | "reconnecting" | "offline";

/** After this long without reaching the server, "Reconnecting…" becomes "Offline". */
export const OFFLINE_AFTER_MS = 30_000;

/** `failingSince`: when requests started failing (null while they succeed). */
export function connection(
  browserOnline: boolean,
  failingSince: number | null,
  now: number,
): Connection {
  if (!browserOnline) return "offline";
  if (failingSince === null) return "online";
  return now - failingSince >= OFFLINE_AFTER_MS ? "offline" : "reconnecting";
}
