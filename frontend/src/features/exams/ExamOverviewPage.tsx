import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, Archive, CheckCircle2, Eye, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
import { ConfirmDialog } from "@/components/page";
import { Button } from "@/components/ui/button";
import { errorText, unwrap } from "@/lib/api";

import { useExam } from "./context";
import { fixLink, proctoringLabel } from "./lib";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-card shadow-card rounded-xl border p-4">
      <dt className="text-muted-foreground text-sm">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/** Status, counts and the next thing to do (FRONTEND_SPEC § 5.4). Attempt counts arrive in E06. */
export function ExamOverviewPage() {
  const { exam, base, draft, refresh } = useExam();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState<"archive" | "delete" | null>(null);

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

  const act = useMutation({
    mutationFn: async (action: "archive" | "delete") => {
      const path = { params: { path: { exam_id: exam.id } } };
      if (action === "archive")
        return unwrap(await api.POST("/api/v1/exams/{exam_id}/archive", path));
      return unwrap(await api.DELETE("/api/v1/exams/{exam_id}", path));
    },
    onSuccess: (_, action) => {
      setConfirm(null);
      refresh();
      if (action === "delete") navigate("/teacher/exams", { replace: true });
    },
    onError: () => setConfirm(null),
  });

  // A preview attempt of your own: the real exam screen, never counted (replaces the last one).
  const preview = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exams/{exam_id}/preview-attempt", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
    onSuccess: (attempt) => navigate(`/attempt/${attempt.id}`),
  });

  const next = check.data?.blocks[0];

  return (
    <div className="space-y-6">
      {act.isError && <FormMessage tone="error">{errorText(act.error)}</FormMessage>}
      {preview.isError && <FormMessage tone="error">{errorText(preview.error)}</FormMessage>}

      <dl className="grid gap-3 sm:grid-cols-4">
        <Stat label="Questions" value={exam.question_count} />
        <Stat label="Total marks" value={Number(exam.total_points)} />
        <Stat label="Students assigned" value={exam.assigned_count} />
        <Stat label="Proctoring" value={proctoringLabel[exam.proctoring_mode]} />
      </dl>

      {draft && (
        <div className="bg-card shadow-card rounded-xl border p-5">
          <h2 className="font-semibold">Next step</h2>
          {check.isPending ? (
            <p className="text-muted-foreground mt-1 text-sm">Checking…</p>
          ) : next ? (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm">{next.message}</p>
              <Button variant="outline" size="sm" asChild>
                <Link to={fixLink(base, next)}>
                  Fix it <ArrowRight />
                </Link>
              </Button>
            </div>
          ) : (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <p className="text-success flex items-center gap-2 text-sm">
                <CheckCircle2 className="size-4" /> Everything is in place. Ready to publish.
              </p>
              <Button size="sm" asChild>
                <Link to={`${base}/publish`}>
                  Review and publish <ArrowRight />
                </Link>
              </Button>
            </div>
          )}
        </div>
      )}
      {exam.status === "PUBLISHED" && (
        <FormMessage tone="info">
          Published as version {exam.published_version_no}. Students see it when the window opens.
          You can still extend the window's end and assign more students.
        </FormMessage>
      )}

      {exam.status !== "ARCHIVED" && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={preview.isPending || exam.question_count === 0}
            onClick={() => preview.mutate()}
          >
            <Eye /> {preview.isPending ? "Opening…" : "Try it as a student"}
          </Button>
          <Button variant="outline" onClick={() => setConfirm("archive")}>
            <Archive /> Archive
          </Button>
          {draft && (
            <Button variant="outline" onClick={() => setConfirm("delete")}>
              <Trash2 /> Delete draft
            </Button>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirm === "archive"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Archive "${exam.title}"?`}
        description="It leaves your active list and can't be changed afterwards. Results and records are kept."
        confirmLabel="Archive"
        busy={act.isPending}
        onConfirm={() => act.mutate("archive")}
      />
      <ConfirmDialog
        open={confirm === "delete"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Delete "${exam.title}"?`}
        description="The draft and its question list and assignments are removed. The questions themselves stay in your bank."
        confirmLabel="Delete"
        busy={act.isPending}
        onConfirm={() => act.mutate("delete")}
      />
    </div>
  );
}
