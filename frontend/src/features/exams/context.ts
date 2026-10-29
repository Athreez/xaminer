import { useOutletContext } from "react-router";

import type { Exam } from "./lib";

export interface ExamContext {
  exam: Exam;
  /** Path of this exam's pages, e.g. /teacher/exams/123. */
  base: string;
  /** Reload the exam after a change elsewhere (questions, students, publish). */
  refresh: () => void;
  /** Settings can only change in a draft; after publishing, just the window's end. */
  draft: boolean;
}

export function useExam(): ExamContext {
  return useOutletContext<ExamContext>();
}
