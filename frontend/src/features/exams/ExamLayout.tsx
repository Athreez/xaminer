import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, NavLink, Outlet, useParams } from "react-router";

import { api } from "@/api/client";
import { ErrorState, LoadingRows, NotFoundBlock } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { formatDateTime, isNotFound, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import type { ExamContext } from "./context";
import { statusLabel, windowLabel, windowState, type ExamStatus } from "./lib";

/** Tabs inside an exam (FRONTEND_SPEC § 4). Review and Analytics join with their tickets. */
const TABS = [
  { to: "", label: "Overview", end: true },
  { to: "questions", label: "Questions" },
  { to: "settings", label: "Settings" },
  { to: "students", label: "Students" },
  { to: "publish", label: "Publish" },
  { to: "monitor", label: "Monitor" },
  { to: "grading", label: "Grading" },
  { to: "results", label: "Results" },
];

export function ExamStatusBadge({ status }: { status: ExamStatus }) {
  const tone = {
    DRAFT: "bg-muted text-muted-foreground border-border",
    PUBLISHED: "bg-success-soft text-success border-success/30",
    ARCHIVED: "bg-muted text-muted-foreground border-border",
  }[status];
  return (
    <Badge variant="outline" className={tone}>
      {statusLabel[status]}
    </Badge>
  );
}

/** Loads the exam once for all its tabs and shows the header and tab bar. */
export function ExamLayout() {
  const { examId = "" } = useParams();
  const queryClient = useQueryClient();
  const exam = useQuery({
    queryKey: ["exams", examId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/exams/{exam_id}", { params: { path: { exam_id: examId } } })),
  });

  if (exam.isPending) return <LoadingRows rows={8} />;
  if (exam.isError) {
    if (isNotFound(exam.error)) return <NotFoundBlock what="exam" back="/teacher/exams" />;
    return <ErrorState error={exam.error} onRetry={() => void exam.refetch()} />;
  }

  const base = `/teacher/exams/${examId}`;
  const context: ExamContext = {
    exam: exam.data,
    base,
    draft: exam.data.status === "DRAFT",
    refresh: () => void queryClient.invalidateQueries({ queryKey: ["exams"] }),
  };
  const state = windowState(exam.data);

  return (
    <section className="max-w-5xl">
      <Link
        to="/teacher/exams"
        className="text-muted-foreground mb-4 inline-flex items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft className="size-4" /> All exams
      </Link>
      <header className="mb-4">
        <h1 className="flex flex-wrap items-center gap-3 text-2xl font-semibold">
          {exam.data.title}
          <ExamStatusBadge status={exam.data.status} />
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          {windowLabel[state]}
          {exam.data.open_at &&
            ` · ${formatDateTime(exam.data.open_at)} to ${formatDateTime(exam.data.close_at)}`}
          {exam.data.duration_min && ` · ${exam.data.duration_min} min`}
        </p>
      </header>
      <nav aria-label="Exam" className="mb-6 flex gap-1 overflow-x-auto border-b">
        {TABS.map((tab) => (
          <NavLink
            key={tab.label}
            to={tab.to ? `${base}/${tab.to}` : base}
            end={tab.end}
            className={({ isActive }) =>
              cn(
                "-mb-px border-b-2 px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors",
                isActive
                  ? "border-selection text-foreground"
                  : "text-muted-foreground hover:text-foreground border-transparent",
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet context={context} />
    </section>
  );
}
