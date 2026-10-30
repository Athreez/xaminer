import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { ErrorState, LoadingRows, NotFoundBlock } from "@/components/page";
import { formatDateTime, isNotFound, unwrap } from "@/lib/api";

import { passLabel, score } from "./lib";
import { ResultQuestions } from "./ResultQuestions";

/**
 * A released result (PRD GRD-07): total, each question's score and feedback, coding verdicts with
 * passed counts and the integrity outcome. Never the correct answers, hidden tests or events.
 */
export function StudentResultPage() {
  const { attemptId = "" } = useParams();
  const result = useQuery({
    queryKey: ["student", "results", attemptId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/student/results/{attempt_id}", {
          params: { path: { attempt_id: attemptId } },
        }),
      ),
  });

  if (result.isPending) return <LoadingRows />;
  if (result.isError) {
    if (isNotFound(result.error)) return <NotFoundBlock what="result" back="/student/results" />;
    return <ErrorState error={result.error} onRetry={() => void result.refetch()} />;
  }
  const r = result.data;

  return (
    <section className="mx-auto max-w-4xl space-y-4">
      <Link
        to="/student/results"
        className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft className="size-4" /> All results
      </Link>
      <div className="bg-card flex flex-wrap items-start justify-between gap-4 rounded-xl border p-5">
        <div>
          <h1 className="text-2xl font-semibold">{r.exam_title}</h1>
          <p className="text-muted-foreground text-sm">
            Submitted {formatDateTime(r.submitted_at)} · released {formatDateTime(r.released_at)}
          </p>
          {r.integrity_outcome && (
            <p className="mt-1 text-sm">Integrity review: {r.integrity_outcome}</p>
          )}
        </div>
        <div className="text-right">
          <p className="text-3xl font-semibold tabular-nums">
            {score(r.total_score)} / {score(r.max_score)}
          </p>
          <p className="text-muted-foreground">
            {score(r.percentage)}%{r.passed != null && ` · ${passLabel(r.passed)}`}
          </p>
        </div>
      </div>
      {r.revisions.length > 0 && (
        <div className="bg-card rounded-xl border p-4 text-sm">
          <h2 className="mb-1 font-semibold">Your score was changed</h2>
          <ul className="space-y-1">
            {r.revisions.map((v) => (
              <li key={v.created_at}>
                {score(v.old_score)} → {score(v.new_score)}: {v.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      <ResultQuestions questions={r.questions} />
    </section>
  );
}
