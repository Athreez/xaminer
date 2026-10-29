import type { components } from "@/api/schema";

export type StudentExam = components["schemas"]["StudentExam"];
export type StudentExamDetail = components["schemas"]["StudentExamDetail"];
export type ExamState = StudentExam["state"];

/** "in 2 days", "in 1 h 5 min", "in 4 min 10 s" for a countdown to an opening time. */
export function countdown(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  const days = Math.floor(s / 86_400);
  const hours = Math.floor((s % 86_400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (days >= 2) return `in ${days} days`;
  if (days === 1) return hours ? `in 1 day ${hours} h` : "in 1 day";
  if (hours > 0) return minutes ? `in ${hours} h ${minutes} min` : `in ${hours} h`;
  if (minutes > 0) return `in ${minutes} min ${s % 60} s`;
  return `in ${s} s`;
}

/** "90 minutes", "1 hour", "2 hours 30 minutes". */
export function durationText(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const hours = h ? `${h} ${h === 1 ? "hour" : "hours"}` : "";
  const mins = m ? `${m} ${m === 1 ? "minute" : "minutes"}` : "";
  return [hours, mins].filter(Boolean).join(" ") || "0 minutes";
}

/** The proctoring mode in plain words (FRONTEND_SPEC § 5.6). */
export const proctoringText: Record<StudentExam["proctoring_mode"], string> = {
  OFF: "Not proctored.",
  VIDEO:
    "Proctored with your camera. The browser watches for possible problems and a teacher reviews anything it flags, with up to 3 still pictures. Nothing is recorded.",
  VIDEO_AUDIO:
    "Proctored with your camera and microphone. The browser watches and listens for possible problems and a teacher reviews anything it flags, with up to 3 still pictures. Nothing is recorded.",
};

export const navigationText: Record<StudentExamDetail["navigation_mode"], string> = {
  FREE: "Answer the questions in any order and go back to change answers until you submit.",
  SEQUENTIAL: "Forward only: once you move to the next question, you can't go back.",
};

/** Device needs for the exam (FRONTEND_SPEC § 10). */
export function deviceNeeds(exam: Pick<StudentExamDetail, "proctoring_mode" | "has_coding">) {
  const needs = [
    exam.has_coding
      ? "A screen of at least 1280 × 720 (there is a code editor)."
      : "A screen of at least 1024 × 768.",
    "A steady internet connection. If it drops, keep working: answers are kept on this device and sent when it's back.",
  ];
  if (exam.proctoring_mode !== "OFF") {
    needs.unshift(
      `A laptop or desktop with a working camera${exam.proctoring_mode === "VIDEO_AUDIO" ? " and microphone" : ""}. Phones and tablets can't be used.`,
    );
  }
  return needs;
}

/** What a finished exam card says. */
export function completedText(exam: StudentExam): string {
  if (exam.state === "MISSED") return "Missed: the exam closed before you started it.";
  return "Submitted. Results appear when your teacher releases them.";
}
