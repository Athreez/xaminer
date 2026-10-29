import { useId, useState } from "react";

import { MarkdownView } from "@/components/MarkdownView";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import type { StudentQuestion } from "./lib";

/**
 * A question as a student answers it. Built from the student view, which has no answer key, so
 * nothing here can reveal one. The teacher preview uses it now; the exam screen will too.
 */
export function StudentQuestionCard({
  question,
  number,
}: {
  question: StudentQuestion;
  number?: number;
}) {
  const name = useId();
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState("");
  const points = Number(question.points);
  const negative = Number(question.negative_marks);

  function choose(id: string, on: boolean) {
    if (!question.multiple_answers) setPicked([id]);
    else setPicked((prev) => (on ? [...prev, id] : prev.filter((p) => p !== id)));
  }

  return (
    <article className="bg-card shadow-card rounded-2xl border p-6">
      <header className="text-muted-foreground mb-3 flex flex-wrap items-center gap-x-3 text-sm">
        {number !== undefined && <span className="text-foreground font-semibold">Q{number}</span>}
        <span>
          {points} {points === 1 ? "mark" : "marks"}
        </span>
        {negative > 0 && <span>−{negative} for a wrong answer</span>}
        {question.multiple_answers && (
          <span>
            Select all that apply
            {question.msq_scoring === "PARTIAL" ? " (partial marks)" : " (all or nothing)"}
          </span>
        )}
      </header>

      <MarkdownView text={question.body} />

      {question.options.length > 0 && (
        <fieldset className="mt-5 space-y-2">
          <legend className="sr-only">Answer</legend>
          {question.options.map((option, i) => {
            const checked = picked.includes(option.id);
            return (
              <label
                key={option.id}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 transition-colors",
                  checked ? "border-selection bg-selection-soft" : "hover:bg-accent/50",
                )}
              >
                <input
                  type={question.multiple_answers ? "checkbox" : "radio"}
                  name={name}
                  className="accent-selection mt-1 size-4"
                  checked={checked}
                  onChange={(e) => choose(option.id, e.target.checked)}
                />
                <span className="text-muted-foreground w-5 shrink-0 font-medium">
                  {String.fromCharCode(65 + i)}.
                </span>
                <MarkdownView text={option.label} className="flex-1" />
              </label>
            );
          })}
        </fieldset>
      )}

      {question.type === "DESCRIPTIVE" && (
        <div className="mt-5 space-y-1.5">
          <Textarea
            aria-label="Your answer"
            rows={6}
            maxLength={question.max_answer_length ?? undefined}
            placeholder="Type your answer"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {question.max_answer_length && (
            <p className="text-muted-foreground text-right text-xs tabular-nums">
              {text.length} / {question.max_answer_length}
            </p>
          )}
        </div>
      )}
    </article>
  );
}
