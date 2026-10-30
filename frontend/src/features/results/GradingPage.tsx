import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
import { MarkdownView } from "@/components/MarkdownView";
import { Busy, EmptyState, ErrorState, LoadingRows } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorCode, errorText, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import { useExam } from "../exams/context";
import { markProblem, score, type GradingQueue } from "./lib";

type Question = GradingQueue["questions"][number];

/**
 * Marking written answers (FRONTEND_SPEC § 5.4, PRD GRD-03): pick a question, then one answer at
 * a time with the rubric beside it. Students are "Student 14" unless names are shown. Keyboard
 * only: the mark box has focus, Enter (or Ctrl+Enter in feedback) saves and moves to the next.
 */
export function GradingPage() {
  const { exam } = useExam();
  const [showNames, setShowNames] = useState(false);
  const [questionId, setQuestionId] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const key = ["exams", exam.id, "grading", showNames];

  const queue = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/grading", {
          params: { path: { exam_id: exam.id }, query: { show_names: showNames } },
        }),
      ),
  });

  if (queue.isPending) return <LoadingRows />;
  if (queue.isError) return <ErrorState error={queue.error} onRetry={() => void queue.refetch()} />;
  const questions = queue.data.questions;
  if (questions.every((q) => q.answers.length === 0)) {
    return (
      <EmptyState title="Nothing to mark">
        Written answers appear here once students submit. Other questions are graded automatically.
      </EmptyState>
    );
  }
  const question = questions.find((q) => q.exam_question_id === questionId) ?? questions[0]!;
  const at = Math.min(index, Math.max(0, question.answers.length - 1));
  const current = question.answers[at];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-semibold">
          {queue.data.marked} / {queue.data.total} marked
        </p>
        <div className="flex items-center gap-2">
          <Checkbox
            id="show-names"
            checked={showNames}
            onCheckedChange={(v) => setShowNames(v === true)}
          />
          <Label htmlFor="show-names">Show names</Label>
        </div>
      </div>
      <div role="tablist" aria-label="Questions to mark" className="flex flex-wrap gap-2">
        {questions.map((q) => (
          <Button
            key={q.exam_question_id}
            role="tab"
            aria-selected={q === question}
            variant={q === question ? "default" : "outline"}
            size="sm"
            onClick={() => {
              setQuestionId(q.exam_question_id);
              setIndex(firstUnmarked(q));
            }}
          >
            Question {q.position} · {q.marked}/{q.answers.length}
          </Button>
        ))}
      </div>
      <Marker
        key={`${question.exam_question_id}:${current?.attempt_id}:${current?.score}`}
        question={question}
        index={at}
        onIndex={setIndex}
      />
    </div>
  );
}

function firstUnmarked(q: Question): number {
  const i = q.answers.findIndex((a) => a.score == null);
  return i === -1 ? 0 : i;
}

function Marker({
  question,
  index,
  onIndex,
}: {
  question: Question;
  index: number;
  onIndex: (i: number) => void;
}) {
  const queryClient = useQueryClient();
  const answer = question.answers[index];
  // Keyed by the answer and its saved mark (see GradingPage): each starts from what was saved.
  const [mark, setMark] = useState(answer?.score != null ? score(answer.score) : "");
  const [feedback, setFeedback] = useState(answer?.feedback ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null); // asked for once results are out
  const markBox = useRef<HTMLInputElement>(null);

  useEffect(() => markBox.current?.focus(), []);

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/attempts/{attempt_id}/answers/{exam_question_id}/mark", {
          params: {
            path: { attempt_id: answer!.attempt_id, exam_question_id: question.exam_question_id },
          },
          body: {
            score: mark.trim(),
            feedback: feedback.trim() || null,
            reason: reason?.trim() || null,
          },
        }),
      ),
    onError: (error) => {
      if (errorCode(error) === "REASON_REQUIRED" && reason == null) setReason("");
    },
    onSuccess: async () => {
      setReason(null);
      await queryClient.invalidateQueries({ queryKey: ["exams"] });
      if (index < question.answers.length - 1) onIndex(index + 1);
    },
  });

  if (!answer) {
    return <EmptyState title="No written answers to this question" />;
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const wrong = markProblem(mark, question.points);
    setProblem(wrong);
    if (!wrong) save.mutate();
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
      <form onSubmit={submit} className="bg-card space-y-4 rounded-xl border p-5">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold">
            {answer.student_name ?? answer.student_label}
            {answer.score != null && (
              <span className="text-success ml-2 text-sm font-normal">
                marked {score(answer.score)}
              </span>
            )}
          </h2>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Previous answer"
              disabled={index === 0}
              onClick={() => onIndex(index - 1)}
            >
              <ChevronLeft />
            </Button>
            <span className="text-muted-foreground text-sm">
              {index + 1} of {question.answers.length}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Next answer"
              disabled={index >= question.answers.length - 1}
              onClick={() => onIndex(index + 1)}
            >
              <ChevronRight />
            </Button>
          </div>
        </div>
        <div className="bg-muted/40 rounded-md border p-3 whitespace-pre-wrap">
          {answer.text_answer}
        </div>
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <div className="space-y-1">
            <Label htmlFor="mark">Mark (out of {score(question.points)})</Label>
            <Input
              id="mark"
              ref={markBox}
              inputMode="decimal"
              value={mark}
              onChange={(e) => setMark(e.target.value)}
              aria-invalid={problem != null}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="feedback">Feedback (optional)</Label>
            <Textarea
              id="feedback"
              rows={2}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit();
              }}
            />
          </div>
        </div>
        {reason != null && (
          <div className="space-y-1">
            <Label htmlFor="reason">Reason for the change</Label>
            <Input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            <p className="text-muted-foreground text-xs">
              This result is already released: the student sees the old and new score and this
              reason.
            </p>
          </div>
        )}
        {problem && <FormMessage tone="error">{problem}</FormMessage>}
        {save.isError && reason == null && (
          <FormMessage tone="error">{errorText(save.error)}</FormMessage>
        )}
        <div className="flex items-center justify-between gap-2">
          <p className="text-muted-foreground text-xs">
            Enter saves and opens the next answer (Ctrl+Enter from feedback).
          </p>
          <Button type="submit" disabled={save.isPending}>
            <Busy busy={save.isPending}>Save mark</Busy>
          </Button>
        </div>
      </form>
      <aside className="space-y-3">
        <div className="bg-card rounded-xl border p-4">
          <h3 className="mb-2 text-sm font-semibold">Question {question.position}</h3>
          <MarkdownView text={question.body} className="text-sm" />
        </div>
        <div className={cn("bg-card rounded-xl border p-4", !question.rubric && "hidden")}>
          <h3 className="mb-2 text-sm font-semibold">Rubric</h3>
          <MarkdownView text={question.rubric ?? ""} className="text-sm" />
        </div>
      </aside>
    </div>
  );
}
