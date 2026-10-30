import { MarkdownView } from "@/components/MarkdownView";
import { Badge } from "@/components/ui/badge";

import { verdictText } from "../attempt/coding/lib";
import { score, typeLabel, type QuestionResult, type TeacherQuestionResult } from "./lib";

/**
 * The questions of a result, each with the student's answer and score. Teachers also get the key,
 * the rubric and how the score was made; students never do (SECURITY_AND_ACCESS § 4.3).
 */
export function ResultQuestions({
  questions,
}: {
  questions: (QuestionResult | TeacherQuestionResult)[];
}) {
  return (
    <ol className="space-y-3">
      {questions.map((q) => {
        const teacher = "correct_labels" in q ? q : null;
        return (
          <li key={q.exam_question_id} className="bg-card rounded-xl border p-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-semibold">
                Question {q.position}{" "}
                <span className="text-muted-foreground text-sm font-normal">
                  · {typeLabel[q.type]}
                </span>
              </h3>
              <Badge variant="outline" className="tabular-nums">
                {score(q.score)} / {score(q.points)}
              </Badge>
            </div>
            <MarkdownView text={q.body} className="text-sm" />
            <div className="mt-3 space-y-1 text-sm">
              {q.type === "CODING" ? (
                q.coding ? (
                  <p>
                    {verdictText[q.coding.verdict ?? ""] ?? "Not evaluated"}
                    {q.coding.total_weight != null &&
                      ` · ${q.coding.passed_weight} of ${q.coding.total_weight} test weight passed`}
                    <span className="text-muted-foreground"> · {q.coding.language_key}</span>
                  </p>
                ) : (
                  <p className="text-muted-foreground">No code was submitted.</p>
                )
              ) : q.type === "DESCRIPTIVE" ? (
                <p className="bg-muted/40 rounded-md border p-2 whitespace-pre-wrap">
                  {q.text_answer?.trim() || (
                    <span className="text-muted-foreground">Not answered</span>
                  )}
                </p>
              ) : (
                <p>
                  <span className="text-muted-foreground">Answer: </span>
                  {q.selected_labels?.length ? q.selected_labels.join(", ") : "Not answered"}
                </p>
              )}
              {teacher && teacher.correct_labels && teacher.correct_labels.length > 0 && (
                <p>
                  <span className="text-muted-foreground">Correct: </span>
                  {teacher.correct_labels.join(", ")}
                </p>
              )}
              {teacher?.manual_score != null && teacher.auto_score != null && (
                <p className="text-muted-foreground">
                  Automatic {score(teacher.auto_score)}, marked {score(teacher.manual_score)}
                </p>
              )}
              {q.feedback && (
                <p>
                  <span className="text-muted-foreground">Feedback: </span>
                  {q.feedback}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
