import { useState } from "react";

import { MarkdownView } from "@/components/MarkdownView";

import { AnswerControls } from "./AnswerControls";
import { NO_ANSWER, type AnswerValue, type StudentQuestion } from "./lib";

/**
 * A question as a student answers it. Built from the student view, which has no answer key, so
 * nothing here can reveal one. Used by the teacher preview; the answer stays on this page.
 */
export function StudentQuestionCard({
  question,
  number,
}: {
  question: StudentQuestion;
  number?: number;
}) {
  const [answer, setAnswer] = useState<AnswerValue>(NO_ANSWER);

  return (
    <article className="bg-card shadow-card rounded-2xl border p-6">
      <header className="text-muted-foreground mb-3 flex flex-wrap items-center gap-x-3 text-sm">
        {number !== undefined && <span className="text-foreground font-semibold">Q{number}</span>}
        <MarksNote question={question} />
      </header>
      <MarkdownView text={question.body} />
      <div className="mt-5">
        <AnswerControls question={question} value={answer} onChange={setAnswer} />
      </div>
    </article>
  );
}

/** "4 marks · −1 for a wrong answer" */
export function MarksNote({ question }: { question: StudentQuestion }) {
  const points = Number(question.points);
  const negative = Number(question.negative_marks);
  return (
    <>
      <span>
        {points} {points === 1 ? "mark" : "marks"}
      </span>
      {negative > 0 && <span>−{negative} for a wrong answer</span>}
    </>
  );
}
