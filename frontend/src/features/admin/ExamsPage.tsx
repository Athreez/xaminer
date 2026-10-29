import { useInfiniteQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import {
  Busy,
  EmptyState,
  ErrorState,
  LoadingRows,
  PageHeader,
  TableCard,
} from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, unwrap, useDebounced } from "@/lib/api";

type Status = components["schemas"]["AdminExamSummary"]["status"];

const ALL = "all";
const statusLabel: Record<Status, string> = {
  DRAFT: "Draft",
  PUBLISHED: "Published",
  ARCHIVED: "Archived",
};
const statusTone: Record<Status, string> = {
  DRAFT: "bg-muted text-muted-foreground border-border",
  PUBLISHED: "bg-success-soft text-success border-success/30",
  ARCHIVED: "bg-muted text-muted-foreground border-border",
};

/** Exams of the institution, read-only: title, owner, window, status (FRONTEND_SPEC § 5.1). */
export function ExamsPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<Status | undefined>();
  const q = useDebounced(search.trim(), 300);

  const exams = useInfiniteQuery({
    queryKey: ["admin-exams", { q, status }],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/admin/exams", {
          params: { query: { q: q || undefined, status, cursor: pageParam, limit: 50 } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = exams.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <section>
      <PageHeader
        title="Exams"
        description="Every exam in your institution. Teachers create and run them; questions and answers stay with them."
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="relative min-w-64 flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            aria-label="Search exam titles"
            placeholder="Search titles"
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select
          value={status ?? ALL}
          onValueChange={(v) => setStatus(v === ALL ? undefined : (v as Status))}
        >
          <SelectTrigger className="w-44" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            {(Object.keys(statusLabel) as Status[]).map((s) => (
              <SelectItem key={s} value={s}>
                {statusLabel[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {exams.isPending ? (
        <LoadingRows />
      ) : exams.isError ? (
        <ErrorState error={exams.error} onRetry={() => void exams.refetch()} />
      ) : rows.length === 0 ? (
        q || status ? (
          <EmptyState title="No exams match these filters">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSearch("");
                setStatus(undefined);
              }}
            >
              Clear filters
            </Button>
          </EmptyState>
        ) : (
          <EmptyState title="No exams yet">Teachers' exams will appear here.</EmptyState>
        )
      ) : (
        <>
          <TableCard>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Owner</TableHead>
                  <TableHead>Opens</TableHead>
                  <TableHead>Closes</TableHead>
                  <TableHead className="text-right">Minutes</TableHead>
                  <TableHead className="text-right">Students</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((exam) => (
                  <TableRow key={exam.id}>
                    <TableCell className="font-medium">{exam.title}</TableCell>
                    <TableCell>{exam.owner_name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(exam.open_at)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(exam.close_at)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {exam.duration_min ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{exam.assigned_count}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={statusTone[exam.status]}>
                        {statusLabel[exam.status]}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableCard>
          {exams.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={exams.isFetchingNextPage}
                onClick={() => void exams.fetchNextPage()}
              >
                <Busy busy={exams.isFetchingNextPage}>Load more</Busy>
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
