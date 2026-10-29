import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { Field, FormMessage } from "@/components/form";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { errorText, formatDateTime, unwrap, useDebounced } from "@/lib/api";

import { ExamStatusBadge } from "./ExamLayout";
import { proctoringLabel, statusLabel, windowLabel, windowState, type ExamStatus } from "./lib";

const ALL = "all";

/** The teacher's exams (FRONTEND_SPEC § 5.4). */
export function ExamListPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<ExamStatus | undefined>();
  const [creating, setCreating] = useState(false);
  const q = useDebounced(search.trim(), 300);

  const exams = useInfiniteQuery({
    queryKey: ["exams", { q, status }],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/exams", {
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
        description="Build an exam, assign students, then publish it."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> New exam
          </Button>
        }
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
          onValueChange={(v) => setStatus(v === ALL ? undefined : (v as ExamStatus))}
        >
          <SelectTrigger className="w-44" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            {(Object.keys(statusLabel) as ExamStatus[]).map((s) => (
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
          <EmptyState title="No exams yet">
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus /> Create your first exam
            </Button>
          </EmptyState>
        )
      ) : (
        <>
          <TableCard>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Exam</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Window</TableHead>
                  <TableHead className="text-right">Questions</TableHead>
                  <TableHead className="text-right">Students</TableHead>
                  <TableHead>Proctoring</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((exam) => {
                  const state = windowState(exam);
                  return (
                    <TableRow key={exam.id}>
                      <TableCell>
                        <Link to={exam.id} className="font-medium hover:underline">
                          {exam.title}
                        </Link>
                        {exam.has_coding && (
                          <Badge variant="outline" className="ml-2">
                            Coding
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <ExamStatusBadge status={exam.status} />
                      </TableCell>
                      <TableCell>
                        <span className="block">{windowLabel[state]}</span>
                        {exam.open_at && (
                          <span className="text-muted-foreground text-xs">
                            {formatDateTime(exam.open_at)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {exam.question_count}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {exam.assigned_count}
                      </TableCell>
                      <TableCell>{proctoringLabel[exam.proctoring_mode]}</TableCell>
                    </TableRow>
                  );
                })}
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
      <NewExamDialog open={creating} onOpenChange={setCreating} />
    </section>
  );
}

function NewExamDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exams", {
          // Only the title is required; the server fills every other setting with its default.
          // The generated type lists defaulted fields as required, hence the cast.
          body: { title } as components["schemas"]["ExamCreate"],
        }),
      ),
    onSuccess: (exam) => {
      void queryClient.invalidateQueries({ queryKey: ["exams"] });
      navigate(`${exam.id}/settings`);
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) {
          setTitle("");
          create.reset();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New exam</DialogTitle>
          <DialogDescription>
            Start with a title. Settings, questions and students come next.
          </DialogDescription>
        </DialogHeader>
        <form id="new-exam" onSubmit={onSubmit} className="space-y-4" noValidate>
          {create.isError && <FormMessage tone="error">{errorText(create.error)}</FormMessage>}
          <Field label="Title">
            {(props) => (
              <Input
                {...props}
                autoFocus
                maxLength={200}
                placeholder="Data Structures — Mid-term"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            )}
          </Field>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form="new-exam" disabled={!title.trim() || create.isPending}>
            <Busy busy={create.isPending}>Create exam</Busy>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
