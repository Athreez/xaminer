import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "@/api/client";
import { EmptyState, ErrorState, LoadingRows, PageHeader, TableCard } from "@/components/page";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, unwrap } from "@/lib/api";

import { passLabel, score } from "./lib";

/** The student's past exams (PRD GRD-09); a score only once the teacher releases it. */
export function StudentResultsPage() {
  const results = useQuery({
    queryKey: ["student", "results"],
    queryFn: async () => unwrap(await api.GET("/api/v1/student/results")),
  });

  return (
    <section className="mx-auto max-w-4xl">
      <PageHeader title="Results" description="Your submitted exams and released results." />
      {results.isPending ? (
        <LoadingRows />
      ) : results.isError ? (
        <ErrorState error={results.error} onRetry={() => void results.refetch()} />
      ) : results.data.items.length === 0 ? (
        <EmptyState title="No results yet">Exams you submit appear here.</EmptyState>
      ) : (
        <TableCard>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Exam</TableHead>
                <TableHead>Submitted</TableHead>
                <TableHead className="text-right">Score</TableHead>
                <TableHead>Pass / fail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {results.data.items.map((r) => (
                <TableRow key={r.attempt_id}>
                  <TableCell className="font-medium">
                    {r.released ? (
                      <Link to={`/student/results/${r.attempt_id}`} className="hover:underline">
                        {r.exam_title}
                      </Link>
                    ) : (
                      r.exam_title
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {formatDateTime(r.submitted_at)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.released
                      ? `${score(r.total_score)} / ${score(r.max_score)} (${score(r.percentage)}%)`
                      : "Not released yet"}
                  </TableCell>
                  <TableCell>{r.released ? passLabel(r.passed) : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableCard>
      )}
    </section>
  );
}
