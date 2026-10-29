import { useId } from "react";

import { MarkdownView } from "@/components/MarkdownView";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { msqRule, type AnswerValue, type StudentQuestion } from "./lib";

/**
 * The answer part of a question as a student sees it (FRONTEND_SPEC § 6.5): radio buttons for
 * single choice and true/false, checkboxes for multiple choice, a text area with a live count for
 * descriptive answers. Controlled: the caller keeps the answer (the exam screen saves every change).
 */
export function AnswerControls({
  question,
  value,
  onChange,
  disabled = false,
}: {
  question: StudentQuestion;
  value: AnswerValue;
  onChange: (value: AnswerValue) => void;
  disabled?: boolean;
}) {
  const name = useId();
  const picked = value.selected_option_ids ?? [];
  const text = value.text_answer ?? "";

  function choose(id: string, on: boolean) {
    const next = !question.multiple_answers
      ? [id]
      : on
        ? [...picked, id]
        : picked.filter((p) => p !== id);
    onChange({ selected_option_ids: next.length ? next : null, text_answer: null });
  }

  if (question.type === "DESCRIPTIVE") {
    const limit = question.max_answer_length;
    return (
      <div className="space-y-1.5">
        <Textarea
          aria-label="Your answer"
          rows={8}
          maxLength={limit ?? undefined}
          placeholder="Type your answer"
          value={text}
          disabled={disabled}
          onChange={(e) =>
            onChange({ selected_option_ids: null, text_answer: e.target.value || null })
          }
        />
        <p className="text-muted-foreground text-right text-xs tabular-nums" aria-live="off">
          {limit ? `${text.length} / ${limit} characters` : `${text.length} characters`}
        </p>
      </div>
    );
  }

  if (question.type === "CODING") {
    return (
      <p className="text-muted-foreground rounded-xl border border-dashed p-4 text-sm">
        Coding questions open in the code editor, which arrives in a later step.
      </p>
    );
  }

  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-muted-foreground mb-3 text-sm">
        {question.multiple_answers ? msqRule(question.msq_scoring) : "Choose one answer."}
      </legend>
      {question.options.map((option, i) => {
        const checked = picked.includes(option.id);
        return (
          <label
            key={option.id}
            className={cn(
              "flex items-start gap-3 rounded-xl border px-4 py-3 transition-colors",
              disabled ? "opacity-70" : "cursor-pointer",
              checked ? "border-selection bg-selection-soft" : !disabled && "hover:bg-accent/50",
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
  );
}
