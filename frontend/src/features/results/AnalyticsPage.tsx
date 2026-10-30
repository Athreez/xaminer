import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { EmptyState, ErrorState, LoadingRows, TableCard } from "@/components/page";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { unwrap } from "@/lib/api";

import { verdictText } from "../attempt/coding/lib";
import { useExam } from "../exams/context";
import { score, typeLabel } from "./lib";

type Analytics = components["schemas"]["ExamAnalytics"];
type Question = Analytics["questions"][number];

/**
 * Exam analytics (FRONTEND_SPEC § 5.4, PRD MON-03..05): summary numbers and a score histogram;
 * per question average, full marks and option picks; for coding, verdicts and the pass rate of
 * each test case, with low ones flagged as possibly broken. Over fully graded attempts.
 */
export function AnalyticsPage() {
  const { exam } = useExam();
  const data = useQuery({
    queryKey: ["exams", exam.id, "analytics"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/analytics", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
  });

  if (data.isPending) return <LoadingRows />;
  if (data.isError) return <ErrorState error={data.error} onRetry={() => void data.refetch()} />;
  const a = data.data;
  if (a.graded === 0)
    return (
      <EmptyState title="Nothing to show yet">
        Analytics appear once attempts are fully graded.
      </EmptyState>
    );

  return (
    <div className="space-y-6">
      <p className="text-muted-foreground text-sm">
        Over {a.graded} fully graded {a.graded === 1 ? "attempt" : "attempts"}.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label="Average" value={`${score(a.average)} / ${score(a.max_score)}`} />
        <Stat label="Median" value={score(a.median)} />
        <Stat label="Highest" value={score(a.highest)} />
        <Stat label="Lowest" value={score(a.lowest)} />
        <Stat
          label="Pass rate"
          value={a.pass_rate == null ? "No pass mark" : `${Math.round(a.pass_rate * 100)}%`}
        />
      </div>
      <Histogram counts={a.histogram} />
      <QuestionTable questions={a.questions} />
      {a.questions
        .filter((q) => q.type === "CODING")
        .map((q) => (
          <CodingStats key={q.exam_question_id} question={q} />
        ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="bg-card shadow-card rounded-xl border p-4">
      <p className="text-xl font-semibold tabular-nums">{value}</p>
      <p className="text-muted-foreground text-sm">{label}</p>
    </div>
  );
}

/** Attempts per 10 % band: one series, so one colour and no legend; the title names it. */
function Histogram({ counts }: { counts: number[] }) {
  const most = Math.max(1, ...counts);
  return (
    <section className="bg-card shadow-card rounded-xl border p-4">
      <h2 className="mb-4 font-semibold">Scores (% of the maximum)</h2>
      <div className="flex h-40 items-end gap-[2px] border-b" role="list">
        {counts.map((n, i) => {
          const band = i === 9 ? "90–100%" : `${i * 10}–${i * 10 + 9}%`;
          const text = `${band}: ${n} ${n === 1 ? "attempt" : "attempts"}`;
          return (
            <div
              key={band}
              role="listitem"
              aria-label={text}
              title={text}
              className="group relative flex h-full flex-1 items-end"
            >
              <div
                className="bg-primary group-hover:bg-primary/80 w-full rounded-t-[4px]"
                style={{ height: `${(n / most) * 100}%`, minHeight: n ? 2 : 0 }}
              />
              {n > 0 && (
                <span className="text-muted-foreground absolute -top-5 w-full text-center text-xs tabular-nums">
                  {n}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <div className="text-muted-foreground mt-1 flex gap-[2px] text-xs">
        {counts.map((_, i) => (
          <span key={i} className="flex-1 text-center tabular-nums">
            {i * 10}
          </span>
        ))}
      </div>
    </section>
  );
}

function QuestionTable({ questions }: { questions: Question[] }) {
  return (
    <section className="space-y-2">
      <h2 className="font-semibold">Questions</h2>
      <TableCard>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Question</TableHead>
              <TableHead className="text-right">Average</TableHead>
              <TableHead className="text-right">Full marks</TableHead>
              <TableHead>Options picked</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {questions.map((q) => (
              <TableRow key={q.exam_question_id}>
                <TableCell className="max-w-xs">
                  <div className="truncate font-medium">
                    {q.position}. {q.title}
                  </div>
                  <div className="text-muted-foreground text-xs">{typeLabel[q.type]}</div>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {score(q.average)} / {score(q.points)}
                </TableCell>
                <TableCell className="text-right tabular-nums">{q.full_marks}</TableCell>
                <TableCell className="text-sm">
                  {q.options && q.options.length > 0
                    ? q.options.map((o, i) => (
                        <span key={i} className="mr-3 whitespace-nowrap">
                          {o.label}
                          {o.is_correct && <span className="text-success"> ✓</span>}:{" "}
                          <span className="tabular-nums">{o.picked}</span>
                        </span>
                      ))
                    : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableCard>
    </section>
  );
}

function CodingStats({ question }: { question: Question }) {
  const verdicts = Object.entries(question.verdicts ?? {});
  const cases = question.test_cases ?? [];
  return (
    <section className="bg-card shadow-card space-y-3 rounded-xl border p-4">
      <h2 className="font-semibold">
        Question {question.position}: {question.title}
      </h2>
      <p className="text-sm">
        {verdicts.length === 0
          ? "No submissions."
          : verdicts.map(([v, n]) => (
              <span key={v} className="mr-4 whitespace-nowrap">
                {v === "NO_SUBMISSION" ? "No submission" : (verdictText[v] ?? v)}:{" "}
                <span className="font-semibold tabular-nums">{n}</span>
              </span>
            ))}
      </p>
      {cases.length > 0 && (
        <ul className="space-y-1.5">
          {cases.map((c) => (
            <li
              key={c.number}
              className="grid grid-cols-[9rem_1fr_7rem] items-center gap-3 text-sm"
            >
              <span>
                {c.hidden ? "Hidden" : "Public"} test {c.number}
                {c.weight > 1 && <span className="text-muted-foreground"> ×{c.weight}</span>}
              </span>
              <div className="bg-muted h-2 overflow-hidden rounded-full" aria-hidden>
                <div
                  className="bg-primary h-full rounded-full"
                  style={{ width: `${c.pass_rate * 100}%` }}
                />
              </div>
              <span className="tabular-nums">
                {c.passed}/{c.total} passed
                {c.possibly_broken && (
                  <span className="text-warning ml-1 inline-flex items-center gap-1 align-middle">
                    <TriangleAlert className="size-3.5" aria-hidden />
                    <span className="sr-only">possibly broken</span>
                  </span>
                )}
              </span>
              {c.possibly_broken && (
                <p className="text-warning col-span-3 -mt-1 text-xs">
                  Possibly broken test case: most students fail it. Check its expected output, fix
                  it in the question bank, then use Re-evaluate code on the Results tab.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
