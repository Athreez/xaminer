import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { ErrorState, LoadingRows, NotFoundBlock } from "@/components/page";
import { formatDateTime, isNotFound, unwrap } from "@/lib/api";

import { useExam } from "../exams/context";
import { gradingLabel, passLabel, score } from "./lib";
import { IntegrityReview } from "./IntegrityReview";
import { ResultQuestions } from "./ResultQuestions";

/** One attempt in full for the teacher: every answer with its score, the key and feedback. */
export function AttemptResultPage() {
  const { exam, base } = useExam();
  const { attemptId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["exams", exam.id, "results", attemptId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/results/{attempt_id}", {
          params: { path: { exam_id: exam.id, attempt_id: attemptId } },
        }),
      ),
  });

  if (detail.isPending) return <LoadingRows />;
  if (detail.isError) {
    if (isNotFound(detail.error)) return <NotFoundBlock what="attempt" back={`${base}/results`} />;
    return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  }
  const d = detail.data;
  const r = d.result;

  return (
    <div className="space-y-4">
      <Link
        to={`${base}/results`}
        className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft className="size-4" /> All results
      </Link>
      <div className="bg-card flex flex-wrap items-start justify-between gap-4 rounded-xl border p-4">
        <div>
          <h2 className="text-lg font-semibold">{d.student_name}</h2>
          <p className="text-muted-foreground text-sm">
            {d.student_email} · submitted {formatDateTime(d.submitted_at)} · grading:{" "}
            {gradingLabel[d.grading_status]}
          </p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-semibold tabular-nums">
            {r.total_score == null ? "—" : `${score(r.total_score)} / ${score(r.max_score)}`}
          </p>
          <p className="text-muted-foreground text-sm">
            {r.percentage != null && `${score(r.percentage)}% · `}
            {passLabel(r.passed)} · {r.released_at ? "released" : "not released"}
          </p>
        </div>
      </div>
      {d.revisions.length > 0 && (
        <div className="bg-card rounded-xl border p-4 text-sm">
          <h3 className="mb-1 font-semibold">Changes after release</h3>
          <ul className="space-y-1">
            {d.revisions.map((v) => (
              <li key={v.created_at}>
                {score(v.old_score)} → {score(v.new_score)}: {v.reason}{" "}
                <span className="text-muted-foreground">({formatDateTime(v.created_at)})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <IntegrityReview
        events={d.events ?? []}
        outcome={d.integrity_outcome}
        startedAt={null}
        queryKey={["exams", exam.id, "results", attemptId]}
      />
      <ResultQuestions questions={d.questions} />
    </div>
  );
}
