import type { components } from "@/api/schema";

export type Exam = components["schemas"]["ExamView"];
export type ExamSummary = components["schemas"]["ExamSummary"];
export type ExamStatus = Exam["status"];
export type Issue = components["schemas"]["Issue"];

export const statusLabel: Record<ExamStatus, string> = {
  DRAFT: "Draft",
  PUBLISHED: "Published",
  ARCHIVED: "Archived",
};

export const proctoringLabel: Record<Exam["proctoring_mode"], string> = {
  OFF: "Off",
  VIDEO: "Video",
  VIDEO_AUDIO: "Video + audio",
};

export type WindowState = "NOT_SCHEDULED" | "UPCOMING" | "OPEN" | "CLOSED";

/** Where the exam window stands right now. */
export function windowState(
  exam: { open_at: string | null; close_at: string | null },
  now = new Date(),
): WindowState {
  if (!exam.open_at || !exam.close_at) return "NOT_SCHEDULED";
  if (now < new Date(exam.open_at)) return "UPCOMING";
  if (now < new Date(exam.close_at)) return "OPEN";
  return "CLOSED";
}

export const windowLabel: Record<WindowState, string> = {
  NOT_SCHEDULED: "Not scheduled",
  UPCOMING: "Upcoming",
  OPEN: "Open now",
  CLOSED: "Closed",
};

/** `<input type="datetime-local">` value (local time, minutes) for an ISO instant, or "". */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** The ISO instant (with time zone) for a datetime-local value, or null when empty. */
export function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

/** The exam page that fixes a publish-check issue, e.g. a missing duration → settings. */
export function fixLink(examPath: string, issue: Issue): string {
  if (issue.question_id || issue.field === "questions") return `${examPath}/questions`;
  if (issue.field === "assignments") return `${examPath}/students`;
  if (issue.field === "status") return examPath;
  return `${examPath}/settings${issue.field ? `#${issue.field}` : ""}`;
}
