import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Eye } from "lucide-react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { ErrorState, LoadingRows, NotFoundBlock } from "@/components/page";
import { isNotFound, unwrap } from "@/lib/api";

import { StudentQuestionCard } from "./StudentQuestionCard";

/** Exactly what a student sees (PRD QB-08). Answers can be tried out; nothing is saved. */
export function QuestionPreviewPage() {
  const { questionId = "" } = useParams();
  const preview = useQuery({
    queryKey: ["questions", questionId, "preview"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/questions/{question_id}/preview", {
          params: { path: { question_id: questionId } },
        }),
      ),
  });

  return (
    <section className="max-w-3xl">
      <Link
        to={`/teacher/questions/${questionId}`}
        className="text-muted-foreground mb-4 inline-flex items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft className="size-4" /> Back to the question
      </Link>
      <div className="bg-selection-soft text-selection mb-4 flex items-center gap-2 rounded-xl border px-4 py-2 text-sm font-medium">
        <Eye className="size-4" /> Preview: this is what a student sees. Answers here aren't saved.
      </div>
      {preview.isPending ? (
        <LoadingRows rows={4} />
      ) : preview.isError ? (
        isNotFound(preview.error) ? (
          <NotFoundBlock what="question" back="/teacher/questions" />
        ) : (
          <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
        )
      ) : (
        <StudentQuestionCard question={preview.data} number={1} />
      )}
    </section>
  );
}
