import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, FilePen, FileText, Plus, Send } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/hooks";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime, unwrap } from "@/lib/api";

import { windowLabel, windowState } from "./lib";

type DashboardExam = components["schemas"]["DashboardExam"];

/**
 * `/teacher`: what needs doing across the teacher's exams (answers to mark, results to release),
 * exams open now and coming up, and shortcuts. Refreshed every minute.
 */
export function TeacherDashboardPage() {
  const session = useSession();
  const name = session.status === "authenticated" ? session.user.full_name.split(" ")[0] : "";
  const data = useQuery({
    queryKey: ["teacher", "dashboard"],
    queryFn: async () => unwrap(await api.GET("/api/v1/teacher/dashboard")),
    refetchInterval: 60_000,
  });

  return (
    <section className="max-w-5xl space-y-8">
      <PageHeader
        title={name ? `Hello, ${name}` : "Dashboard"}
        description="What needs your attention across your exams."
        actions={
          <>
            <Button variant="outline" asChild>
              <Link to="/teacher/questions/new">
                <Plus /> New question
              </Link>
            </Button>
            <Button asChild>
              <Link to="/teacher/exams">
                <Plus /> New exam
              </Link>
            </Button>
          </>
        }
      />
      {data.isPending ? (
        <LoadingRows rows={4} />
      ) : data.isError ? (
        <ErrorState error={data.error} onRetry={() => void data.refetch()} />
      ) : (
        <Body {...data.data} />
      )}
    </section>
  );
}

function Body({ exams, drafts, questions }: components["schemas"]["TeacherDashboard"]) {
  const toMark = exams.reduce((n, e) => n + e.to_mark, 0);
  const toRelease = exams.reduce((n, e) => n + e.to_release, 0);
  const attention = exams.filter((e) => e.to_mark > 0 || e.to_release > 0);
  const open = exams.filter((e) => windowState(e) === "OPEN");
  const upcoming = exams
    .filter((e) => windowState(e) === "UPCOMING")
    .sort((a, b) => (a.open_at ?? "").localeCompare(b.open_at ?? ""));

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile icon={<ClipboardCheck />} label="Answers to mark" value={toMark} />
        <Tile icon={<Send />} label="Results to release" value={toRelease} />
        <Tile icon={<FilePen />} label="Draft exams" value={drafts} to="/teacher/exams" />
        <Tile icon={<FileText />} label="Questions" value={questions} to="/teacher/questions" />
      </div>

      <Section title="Needs your attention">
        {attention.length === 0 ? (
          <EmptyState title="All caught up">
            Answers to mark and results to release show up here.
          </EmptyState>
        ) : (
          attention.map((e) => (
            <Row key={e.id} exam={e}>
              {e.to_mark > 0 && (
                <Button size="sm" asChild>
                  <Link to={`/teacher/exams/${e.id}/grading`}>Mark {e.to_mark}</Link>
                </Button>
              )}
              {e.to_release > 0 && (
                <Button size="sm" variant="outline" asChild>
                  <Link to={`/teacher/exams/${e.id}/results`}>Release {e.to_release}</Link>
                </Button>
              )}
            </Row>
          ))
        )}
      </Section>

      <Section title="Open now">
        {open.length === 0 ? (
          <p className="text-muted-foreground text-sm">No exam is open right now.</p>
        ) : (
          open.map((e) => (
            <Row key={e.id} exam={e}>
              <span className="text-muted-foreground text-sm">
                {e.started} of {e.assigned} started · {e.submitted} submitted
              </span>
            </Row>
          ))
        )}
      </Section>

      <Section title="Upcoming">
        {upcoming.length === 0 ? (
          <p className="text-muted-foreground text-sm">Nothing scheduled.</p>
        ) : (
          upcoming.map((e) => (
            <Row key={e.id} exam={e}>
              <span className="text-muted-foreground text-sm">
                Opens {formatDateTime(e.open_at)} · {e.assigned} assigned
              </span>
            </Row>
          ))
        )}
      </Section>
    </>
  );
}

function Tile({
  icon,
  label,
  value,
  to,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  to?: string;
}) {
  const body = (
    <div className="bg-card shadow-card flex items-center gap-3 rounded-xl border p-4">
      <span className="bg-primary/10 text-primary rounded-lg p-2 [&_svg]:size-5">{icon}</span>
      <div>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
        <p className="text-muted-foreground text-sm">{label}</p>
      </div>
    </div>
  );
  return to ? (
    <Link to={to} className="hover:[&>div]:border-primary/40 block">
      {body}
    </Link>
  ) : (
    body
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h2 className="font-semibold">{title}</h2>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function Row({ exam, children }: { exam: DashboardExam; children: ReactNode }) {
  const state = windowState(exam);
  return (
    <div className="bg-card flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3">
      <div className="flex items-center gap-2">
        <Link to={`/teacher/exams/${exam.id}`} className="font-medium hover:underline">
          {exam.title}
        </Link>
        <Badge variant="outline">{windowLabel[state]}</Badge>
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}
