import { ArrowLeft, Send } from "lucide-react";
import { useState } from "react";

import { Busy } from "@/components/page";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { typeLabel } from "@/features/questions/lib";
import { errorText } from "@/lib/api";
import { cn } from "@/lib/utils";

import { navStateText, plainText, type AttemptItem, type NavState } from "./lib";
import type { ExamSession } from "./useExamSession";

export interface ReviewRow {
  item: AttemptItem;
  state: NavState;
  open: boolean;
  submitted?: boolean;
}

/**
 * Review and submit (FRONTEND_SPEC § 6.6): every question with its state, clickable counts of what
 * still needs attention, then a confirmation that repeats the counts. If anything hasn't reached
 * the server, the student is told how much and asked again.
 */
export function ReviewPage({
  rows,
  session,
  onOpen,
  onBack,
}: {
  rows: ReviewRow[];
  session: ExamSession;
  onOpen: (index: number) => void;
  onBack: () => void;
}) {
  const [step, setStep] = useState<"closed" | "confirm" | "unsent">("closed");
  const [unsent, setUnsent] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const locked = session.ended !== null;

  const unanswered = rows.filter((r) => r.state === "not-answered" || r.state === "not-visited");
  const marked = rows.filter((r) => r.state === "marked" || r.state === "answered-marked");
  const coding = rows.filter((r) => r.item.question.type === "CODING" && !r.submitted);
  const answered = rows.filter(
    (r) => r.state === "answered" || r.state === "answered-marked",
  ).length;

  async function confirm(anyway: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (!anyway) {
        const status = await session.sendAll();
        if (status.unsent > 0) {
          setUnsent(status.unsent);
          setStep("unsent");
          return;
        }
      }
      await session.submit();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const counts = [
    { label: "unanswered", rows: unanswered },
    { label: "marked for review", rows: marked },
    ...(coding.length ? [{ label: "coding without a submission", rows: coding }] : []),
  ];
  // The first of these the student may still open (-1: none).
  const first = (list: ReviewRow[]) => rows.findIndex((r) => r.open && list.includes(r));

  return (
    <main className="mx-auto w-full max-w-4xl space-y-5 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={onBack}>
          <ArrowLeft className="size-4" /> Back to questions
        </Button>
        <h2 className="mr-auto text-lg font-semibold">Review and submit</h2>
        <Button disabled={locked} onClick={() => setStep("confirm")}>
          <Send className="size-4" /> Submit exam
        </Button>
      </div>

      <ul className="flex flex-wrap gap-2" aria-label="Needs attention">
        {counts.map(({ label, rows: list }) => {
          const target = first(list);
          return (
            <li key={label}>
              <Button
                variant="outline"
                size="sm"
                disabled={target < 0}
                onClick={() => onOpen(target)}
                className={cn(list.length > 0 && "border-warning")}
              >
                <span className="font-semibold tabular-nums">{list.length}</span> {label}
              </Button>
            </li>
          );
        })}
      </ul>

      <div className="bg-card shadow-card overflow-hidden rounded-2xl border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-muted-foreground text-left">
            <tr>
              <th className="w-px px-4 py-2.5 font-medium">#</th>
              <th className="px-4 py-2.5 font-medium">Question</th>
              <th className="w-px px-4 py-2.5 font-medium">Type</th>
              <th className="w-px px-4 py-2.5 font-medium">State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row.item.exam_question_id} className="border-t">
                <td className="px-4 py-2.5 tabular-nums">
                  {row.open ? (
                    <button
                      type="button"
                      className="text-selection font-medium underline-offset-2 hover:underline"
                      aria-label={`Open question ${i + 1}`}
                      onClick={() => onOpen(i)}
                    >
                      {i + 1}
                    </button>
                  ) : (
                    i + 1
                  )}
                </td>
                <td className="max-w-0 truncate px-4 py-2.5">
                  {plainText(row.item.question.body)}
                </td>
                <td className="text-muted-foreground px-4 py-2.5 whitespace-nowrap">
                  {typeLabel[row.item.question.type]}
                </td>
                <td
                  className={cn(
                    "px-4 py-2.5 whitespace-nowrap first-letter:uppercase",
                    (row.state === "not-answered" || row.state === "not-visited") &&
                      "text-warning font-medium",
                  )}
                >
                  {navStateText[row.state]}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={step !== "closed"} onOpenChange={(open) => !open && !busy && setStep("closed")}>
        <DialogContent showCloseButton={false}>
          {step === "unsent" ? (
            <DialogHeader>
              <DialogTitle>
                {unsent} {unsent === 1 ? "answer hasn't" : "answers haven't"} reached the server
              </DialogTitle>
              <DialogDescription>
                There's no connection right now. They're safe on this device and will be sent when
                the connection is back. If you submit now, they won't count.
              </DialogDescription>
            </DialogHeader>
          ) : (
            <DialogHeader>
              <DialogTitle>Submit your exam?</DialogTitle>
              <DialogDescription>
                You answered {answered} of {rows.length} questions
                {unanswered.length > 0 && `; ${unanswered.length} unanswered`}
                {marked.length > 0 && `; ${marked.length} marked for review`}. You can't change
                answers after submitting.
              </DialogDescription>
            </DialogHeader>
          )}
          {error !== null && (
            <p className="text-destructive text-sm" role="alert">
              {errorText(error)} Your answers are safe on this device.
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setStep("closed")}>
              {step === "unsent" ? "Wait for the connection" : "Keep working"}
            </Button>
            <Button disabled={busy} onClick={() => void confirm(step === "unsent")}>
              <Busy busy={busy}>{step === "unsent" ? "Submit anyway" : "Submit"}</Busy>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
