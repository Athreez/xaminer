import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { errorText, unwrap } from "@/lib/api";

/**
 * Re-run every submission to one coding question (PRD EXE-09), e.g. after fixing a test case.
 * It uses the question's current, validated test cases; changed released scores keep a revision.
 * Shown only when the exam has coding questions.
 */
export function ReEvaluate({ examId }: { examId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [questionId, setQuestionId] = useState("");
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);

  const questions = useQuery({
    queryKey: ["exams", examId, "questions"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/questions", {
          params: { path: { exam_id: examId } },
        }),
      ),
  });
  const coding = (questions.data?.questions ?? []).filter((q) => q.type === "CODING");

  const run = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exams/{exam_id}/re-evaluate", {
          params: { path: { exam_id: examId } },
          body: { exam_question_id: questionId, reason: reason.trim() },
        }),
      ),
    onSuccess: (result) => {
      setOpen(false);
      setReason("");
      setDone(
        result.queued === 0
          ? "No submissions to re-run for that question."
          : `${result.queued} ${result.queued === 1 ? "submission is" : "submissions are"} running again with version ${result.version_no}. Scores update as results arrive.`,
      );
      void queryClient.invalidateQueries({ queryKey: ["exams", examId, "results"] });
    },
  });

  if (coding.length === 0) return null;

  return (
    <>
      <Button
        variant="outline"
        onClick={() => {
          setQuestionId(coding[0]!.exam_question_id);
          setDone(null);
          run.reset();
          setOpen(true);
        }}
      >
        <RotateCcw /> Re-evaluate code
      </Button>
      {done && <FormMessage tone="success">{done}</FormMessage>}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Re-evaluate a coding question</DialogTitle>
            <DialogDescription>
              Every submission to the question runs again with its current test cases (fix them in
              the question bank and validate first). If a released score changes, the student sees
              the old and new score and your reason.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="re-question">Question</Label>
              <Select value={questionId} onValueChange={setQuestionId}>
                <SelectTrigger id="re-question" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {coding.map((q) => (
                    <SelectItem key={q.exam_question_id} value={q.exam_question_id}>
                      Question {q.position}: {q.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="re-reason">Reason</Label>
              <Input
                id="re-reason"
                value={reason}
                placeholder="e.g. Test 7 expected the wrong output"
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
          </div>
          {run.isError && <FormMessage tone="error">{errorText(run.error)}</FormMessage>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={reason.trim().length < 3 || run.isPending}
              onClick={() => run.mutate()}
            >
              <Busy busy={run.isPending}>Re-evaluate</Busy>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
