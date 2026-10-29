import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, Rocket, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
import { Busy, ErrorState, LoadingRows } from "@/components/page";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { errorText, formatDateTime, unwrap } from "@/lib/api";

import { useExam } from "./context";
import { fixLink, proctoringLabel, type Issue } from "./lib";

function IssueList({ issues, tone }: { issues: Issue[]; tone: "block" | "warning" }) {
  const { base } = useExam();
  const Icon = tone === "block" ? XCircle : AlertTriangle;
  return (
    <ul className="space-y-2">
      {issues.map((issue) => (
        <li
          key={`${issue.code}-${issue.question_id ?? issue.field}`}
          className="bg-card flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3"
        >
          <Icon
            className={tone === "block" ? "text-destructive size-5" : "text-warning size-5"}
            aria-hidden
          />
          <span className="flex-1 text-sm">{issue.message}</span>
          <Button variant="outline" size="sm" asChild>
            <Link to={fixLink(base, issue)}>
              Fix <ArrowRight />
            </Link>
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** Run the check, fix what blocks, then publish with a summary (FRONTEND_SPEC § 5.4). */
export function ExamPublishPage() {
  const { exam, draft, refresh } = useExam();
  const [confirming, setConfirming] = useState(false);
  const check = useQuery({
    enabled: draft,
    queryKey: ["exams", exam.id, "publish-check"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/publish-check", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
  });
  const publish = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exams/{exam_id}/publish", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
    onSuccess: () => {
      setConfirming(false);
      refresh();
    },
    onError: () => {
      setConfirming(false);
      void check.refetch();
    },
  });

  if (!draft) {
    return exam.status === "PUBLISHED" ? (
      <FormMessage tone="success">
        Published as version {exam.published_version_no}. Its questions and settings are frozen;
        students see it when the window opens.
      </FormMessage>
    ) : (
      <FormMessage tone="info">This exam is archived.</FormMessage>
    );
  }
  if (check.isPending) return <LoadingRows rows={4} />;
  if (check.isError) return <ErrorState error={check.error} onRetry={() => void check.refetch()} />;
  const { blocks, warnings, can_publish } = check.data;

  return (
    <div className="space-y-6">
      {publish.isError && <FormMessage tone="error">{errorText(publish.error)}</FormMessage>}
      {blocks.length > 0 ? (
        <section className="space-y-3">
          <h2 className="flex items-center gap-2 font-semibold">
            <XCircle className="text-destructive size-5" /> Fix before publishing ({blocks.length})
          </h2>
          <IssueList issues={blocks} tone="block" />
        </section>
      ) : (
        <p className="text-success flex items-center gap-2 font-medium">
          <CheckCircle2 className="size-5" /> Nothing blocks publishing.
        </p>
      )}
      {warnings.length > 0 && (
        <section className="space-y-3">
          <h2 className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="text-warning size-5" /> Worth a look ({warnings.length})
          </h2>
          <IssueList issues={warnings} tone="warning" />
        </section>
      )}
      <div className="flex gap-2">
        <Button disabled={!can_publish} onClick={() => setConfirming(true)}>
          <Rocket /> Publish
        </Button>
        <Button variant="outline" onClick={() => void check.refetch()} disabled={check.isFetching}>
          <Busy busy={check.isFetching}>Check again</Busy>
        </Button>
      </div>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Publish "{exam.title}"?</DialogTitle>
            <DialogDescription>
              After publishing, questions and settings are frozen. You can still extend the window's
              end and assign more students.
            </DialogDescription>
          </DialogHeader>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Questions</dt>
            <dd>
              {exam.question_count} ({Number(exam.total_points)} marks)
            </dd>
            <dt className="text-muted-foreground">Students</dt>
            <dd>{exam.assigned_count}</dd>
            <dt className="text-muted-foreground">Window</dt>
            <dd>
              {formatDateTime(exam.open_at)} to {formatDateTime(exam.close_at)}
            </dd>
            <dt className="text-muted-foreground">Duration</dt>
            <dd>{exam.duration_min} min</dd>
            <dt className="text-muted-foreground">Proctoring</dt>
            <dd>{proctoringLabel[exam.proctoring_mode]}</dd>
            {warnings.length > 0 && (
              <>
                <dt className="text-muted-foreground">Warnings</dt>
                <dd>{warnings.length} (see the list)</dd>
              </>
            )}
          </dl>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button disabled={publish.isPending} onClick={() => publish.mutate()}>
              <Busy busy={publish.isPending}>Publish now</Busy>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
