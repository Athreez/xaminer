import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
import { Busy, EmptyState, ErrorState, LoadingRows, TableCard } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorText, formatDateTime, unwrap } from "@/lib/api";

import { useExam } from "../exams/context";
import { gradingLabel, integrityLabel, passLabel, score } from "./lib";
import { ReEvaluate } from "./ReEvaluate";

/**
 * Every attempt's result (FRONTEND_SPEC § 5.4, PRD GRD-05, GRD-06). Release stays disabled, with
 * the reason beside it, until every attempt has ended and is fully graded.
 */
export function ExamResultsPage() {
  const { exam, base } = useExam();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [count, setCount] = useState(0); // as it was when the dialog opened
  const key = ["exams", exam.id, "results"];

  const results = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/results", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
  });
  const release = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exams/{exam_id}/results/release", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data);
      setConfirming(false);
    },
  });

  if (results.isPending) return <LoadingRows />;
  if (results.isError)
    return <ErrorState error={results.error} onRetry={() => void results.refetch()} />;
  const data = results.data;

  return (
    <div className="space-y-4">
      {release.isSuccess && <FormMessage tone="success">Results released to students.</FormMessage>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">
            {data.rows.length} {data.rows.length === 1 ? "attempt" : "attempts"}
          </h2>
          <p className="text-muted-foreground text-sm">
            {data.release_policy === "ON_SUBMIT"
              ? "Results are released as soon as each attempt is graded."
              : "Students see results only after you release them."}
            {data.pass_percent != null && ` Pass mark: ${score(data.pass_percent)}%.`}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex flex-wrap justify-end gap-2">
            <ReEvaluate examId={exam.id} />
            <Button
              disabled={!data.can_release}
              onClick={() => {
                setCount(data.unreleased);
                setConfirming(true);
              }}
            >
              Release results{data.unreleased > 0 && ` (${data.unreleased})`}
            </Button>
          </div>
          {data.blocked_reason && (
            <p id="release-reason" className="text-muted-foreground text-xs">
              {data.blocked_reason}
            </p>
          )}
        </div>
      </div>

      {data.rows.length === 0 ? (
        <EmptyState title="No attempts yet">Results appear here once students submit.</EmptyState>
      ) : (
        <TableCard>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Student</TableHead>
                <TableHead className="text-right">Score</TableHead>
                <TableHead className="text-right">%</TableHead>
                <TableHead>Pass / fail</TableHead>
                <TableHead>Grading</TableHead>
                <TableHead>Integrity</TableHead>
                <TableHead>Released</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((r) => (
                <TableRow key={r.attempt_id}>
                  <TableCell>
                    <Link
                      to={`${base}/results/${r.attempt_id}`}
                      className="font-medium hover:underline"
                    >
                      {r.student_name}
                    </Link>
                    <div className="text-muted-foreground text-xs">{r.student_email}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.total_score == null
                      ? "—"
                      : `${score(r.total_score)} / ${score(r.max_score)}`}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{score(r.percentage)}</TableCell>
                  <TableCell>{passLabel(r.passed)}</TableCell>
                  <TableCell>
                    {r.status === "IN_PROGRESS" ? (
                      <Badge variant="outline">In progress</Badge>
                    ) : (
                      <Badge variant="outline">{gradingLabel[r.grading_status]}</Badge>
                    )}
                  </TableCell>
                  <TableCell>{integrityLabel[r.integrity_outcome ?? ""] ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {r.released_at ? formatDateTime(r.released_at) : "Not yet"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableCard>
      )}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Release results?</DialogTitle>
            <DialogDescription>
              {count} {count === 1 ? "student" : "students"} will see their score, feedback and
              coding results. Changing a score afterwards needs a reason, and the student sees the
              change.
            </DialogDescription>
          </DialogHeader>
          {release.isError && <FormMessage tone="error">{errorText(release.error)}</FormMessage>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button onClick={() => release.mutate()} disabled={release.isPending}>
              <Busy busy={release.isPending}>Release</Busy>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
