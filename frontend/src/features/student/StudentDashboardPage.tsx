import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, Clock, FileText, Play, User } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime, unwrap } from "@/lib/api";

import { completedText, durationText, type StudentExam } from "./lib";

/**
 * `/student`: Available now (start or resume), Upcoming (when it opens), Completed (submitted or
 * missed) — FRONTEND_SPEC § 5.6. Refreshed every minute so exams move between sections by themselves.
 */
export function StudentDashboardPage() {
  const exams = useQuery({
    queryKey: ["student", "exams"],
    queryFn: async () => unwrap(await api.GET("/api/v1/student/exams")),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-8">
      <PageHeader title="Your exams" />
      {exams.isPending ? (
        <LoadingRows rows={3} />
      ) : exams.isError ? (
        <ErrorState error={exams.error} onRetry={() => exams.refetch()} />
      ) : (
        <>
          <Section title="Available now" empty="No exam is open right now.">
            {exams.data.available.map((exam) => (
              <ExamCard key={exam.id} exam={exam} when={`Closes ${formatDateTime(exam.close_at)}`}>
                <AvailableAction exam={exam} />
              </ExamCard>
            ))}
          </Section>
          <Section title="Upcoming" empty="Nothing scheduled yet.">
            {exams.data.upcoming.map((exam) => (
              <ExamCard key={exam.id} exam={exam} when={`Opens ${formatDateTime(exam.open_at)}`}>
                <Button variant="outline" asChild>
                  <Link to={`/student/exams/${exam.id}`}>
                    <FileText /> Details
                  </Link>
                </Button>
              </ExamCard>
            ))}
          </Section>
          <Section title="Completed" empty="Exams you've taken appear here.">
            {exams.data.completed.map((exam) => (
              <ExamCard
                key={exam.id}
                exam={exam}
                when={
                  exam.attempt?.submitted_at
                    ? `Submitted ${formatDateTime(exam.attempt.submitted_at)}`
                    : `Closed ${formatDateTime(exam.close_at)}`
                }
                note={completedText(exam)}
              >
                {exam.attempt && (
                  <Button variant="outline" asChild>
                    <Link to={`/attempt/${exam.attempt.id}`}>Receipt</Link>
                  </Button>
                )}
              </ExamCard>
            ))}
          </Section>
        </>
      )}
    </div>
  );
}

function Section({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children: ReactNode[];
}) {
  return (
    <section className="space-y-3" aria-label={title}>
      <h2 className="text-lg font-semibold">
        {title} <span className="text-muted-foreground font-normal">({children.length})</span>
      </h2>
      {children.length ? <ul className="space-y-3">{children}</ul> : <EmptyState title={empty} />}
    </section>
  );
}

function ExamCard({
  exam,
  when,
  note,
  children,
}: {
  exam: StudentExam;
  when: string;
  note?: string;
  children?: ReactNode;
}) {
  return (
    <li className="bg-card shadow-card flex flex-col gap-3 rounded-xl border p-4 sm:flex-row sm:items-center sm:gap-4">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold">{exam.title}</h3>
          {exam.state === "IN_PROGRESS" && <Badge variant="secondary">In progress</Badge>}
          {exam.proctoring_mode !== "OFF" && <Badge variant="outline">Proctored</Badge>}
        </div>
        <p className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <span className="flex items-center gap-1">
            <User className="size-3.5" aria-hidden /> {exam.teacher_name}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="size-3.5" aria-hidden /> {durationText(exam.duration_min)} ·{" "}
            {exam.question_count} {exam.question_count === 1 ? "question" : "questions"}
          </span>
          <span className="flex items-center gap-1">
            <CalendarClock className="size-3.5" aria-hidden /> {when}
          </span>
        </p>
        {note && <p className="text-sm">{note}</p>}
      </div>
      {children && <div className="sm:shrink-0">{children}</div>}
    </li>
  );
}

function AvailableAction({ exam }: { exam: StudentExam }) {
  if (exam.state === "IN_PROGRESS" && exam.attempt) {
    return (
      <Button asChild>
        <Link to={`/attempt/${exam.attempt.id}`}>
          <Play /> Resume
        </Link>
      </Button>
    );
  }
  if (exam.state === "TOO_LATE") {
    return (
      <p className="text-muted-foreground text-sm sm:max-w-56">
        Less than 5 minutes left in the window: too late to start.
      </p>
    );
  }
  return (
    <Button asChild>
      <Link to={`/student/exams/${exam.id}`}>
        Start <ArrowRight />
      </Link>
    </Button>
  );
}
