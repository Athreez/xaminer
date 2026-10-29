import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, UserPlus, Users, X } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { FormMessage } from "@/components/form";
import { Busy, EmptyState, ErrorState, LoadingRows, TableCard } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorText, unwrap, useDebounced } from "@/lib/api";

import { useExam } from "./context";

/** Who may take the exam (FRONTEND_SPEC § 5.4, PRD EX-04). Changes allowed until archived. */
export function ExamStudentsPage() {
  const { exam, refresh } = useExam();
  const queryClient = useQueryClient();
  const [picking, setPicking] = useState<"groups" | "students" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const open = exam.status !== "ARCHIVED";
  const key = ["exams", exam.id, "assignments"];

  const assigned = useQuery({
    queryKey: key,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/assignments", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
  });

  const remove = useMutation({
    mutationFn: async (studentId: string) =>
      unwrap(
        await api.DELETE("/api/v1/exams/{exam_id}/assignments/{student_id}", {
          params: { path: { exam_id: exam.id, student_id: studentId } },
        }),
      ),
    onSuccess: () => {
      setNotice(null);
      void queryClient.invalidateQueries({ queryKey: key });
      refresh();
    },
  });

  function done(text: string) {
    setNotice(text);
    setPicking(null);
    void queryClient.invalidateQueries({ queryKey: ["exams", exam.id] });
    refresh();
  }

  const students = assigned.data?.students ?? [];

  return (
    <div className="space-y-4">
      {!open && <FormMessage tone="info">This exam is archived and can't be changed.</FormMessage>}
      {notice && <FormMessage tone="success">{notice}</FormMessage>}
      {remove.isError && <FormMessage tone="error">{errorText(remove.error)}</FormMessage>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">
          {students.length} {students.length === 1 ? "student" : "students"} assigned
        </h2>
        {open && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setPicking("groups")}>
              <Users /> Assign groups
            </Button>
            <Button onClick={() => setPicking("students")}>
              <UserPlus /> Assign students
            </Button>
          </div>
        )}
      </div>

      {assigned.isPending ? (
        <LoadingRows />
      ) : assigned.isError ? (
        <ErrorState error={assigned.error} onRetry={() => void assigned.refetch()} />
      ) : students.length === 0 ? (
        <EmptyState title="Nobody is assigned yet">
          Only assigned students can see and take the exam.
        </EmptyState>
      ) : (
        <TableCard>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Roll no.</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>From group</TableHead>
                {open && (
                  <TableHead className="w-12">
                    <span className="sr-only">Remove</span>
                  </TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {students.map((s) => (
                <TableRow key={s.student_id}>
                  <TableCell>{s.roll_no ?? "—"}</TableCell>
                  <TableCell className="font-medium">
                    {s.full_name}
                    {s.status === "DEACTIVATED" && (
                      <span className="text-muted-foreground ml-2 text-xs">(deactivated)</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{s.email}</TableCell>
                  <TableCell>{s.via_group ?? "—"}</TableCell>
                  {open && (
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Remove ${s.full_name}`}
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(s.student_id)}
                      >
                        <X />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableCard>
      )}

      <AssignDialog mode={picking} onClose={() => setPicking(null)} onDone={done} />
    </div>
  );
}

function AssignDialog({
  mode,
  onClose,
  onDone,
}: {
  mode: "groups" | "students" | null;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const { exam } = useExam();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);

  const groups = useQuery({
    enabled: mode === "groups",
    queryKey: ["groups", { q }],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/groups", { params: { query: { q: q || undefined } } })),
  });
  const choices = useQuery({
    enabled: mode === "students",
    queryKey: ["exams", exam.id, "student-choices", q],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/student-choices", {
          params: { path: { exam_id: exam.id }, query: { q: q || undefined, limit: 100 } },
        }),
      ),
  });

  const assign = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/exams/{exam_id}/assignments", {
          params: { path: { exam_id: exam.id } },
          body:
            mode === "groups"
              ? { group_ids: [...picked], student_ids: [] }
              : { group_ids: [], student_ids: [...picked] },
        }),
      ),
    onSuccess: (result) => {
      const parts = [`${result.added} ${result.added === 1 ? "student" : "students"} assigned.`];
      if (result.already_assigned) parts.push(`${result.already_assigned} were already assigned.`);
      if (result.skipped_inactive)
        parts.push(`${result.skipped_inactive} deactivated students were skipped.`);
      onDone(parts.join(" "));
    },
  });

  function toggle(id: string, on: boolean) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  const rows =
    mode === "groups"
      ? (groups.data ?? []).map((g) => ({
          id: g.id,
          title: g.name,
          detail: `${g.member_count} ${g.member_count === 1 ? "student" : "students"}`,
          done: false,
        }))
      : (choices.data ?? []).map((s) => ({
          id: s.id,
          title: s.full_name,
          detail: [s.roll_no, s.email].filter(Boolean).join(" · "),
          done: s.assigned,
        }));
  const loading = mode === "groups" ? groups.isPending : choices.isPending;

  return (
    <Dialog
      open={mode !== null}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
          setPicked(new Set());
          setSearch("");
          assign.reset();
        }
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{mode === "groups" ? "Assign groups" : "Assign students"}</DialogTitle>
          <DialogDescription>
            {mode === "groups"
              ? "Everyone in the group now is assigned. Students who join it later are not."
              : "Search by name, email or roll number, then tick students."}
          </DialogDescription>
        </DialogHeader>
        {assign.isError && <FormMessage tone="error">{errorText(assign.error)}</FormMessage>}
        <div className="relative">
          <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            aria-label={mode === "groups" ? "Search groups" : "Search students"}
            placeholder="Search"
            className="pl-9"
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="max-h-80 overflow-y-auto rounded-lg border">
          {loading ? (
            <div className="p-3">
              <LoadingRows rows={4} />
            </div>
          ) : rows.length === 0 ? (
            <p className="text-muted-foreground p-6 text-center text-sm">
              {mode === "groups"
                ? "No groups. Your admin creates them."
                : "No students match this search."}
            </p>
          ) : (
            <ul className="divide-y">
              {rows.map((row) => {
                const id = `pick-${row.id}`;
                return (
                  <li key={row.id}>
                    <label
                      htmlFor={id}
                      className="hover:bg-accent/50 flex cursor-pointer items-center gap-3 px-3 py-2 has-[:disabled]:cursor-default has-[:disabled]:opacity-60"
                    >
                      <Checkbox
                        id={id}
                        checked={row.done || picked.has(row.id)}
                        disabled={row.done}
                        onCheckedChange={(on) => toggle(row.id, on === true)}
                      />
                      <span className="flex-1">
                        <span className="block text-sm font-medium">{row.title}</span>
                        <span className="text-muted-foreground block text-xs">{row.detail}</span>
                      </span>
                      {row.done && <span className="text-muted-foreground text-xs">Assigned</span>}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={picked.size === 0 || assign.isPending} onClick={() => assign.mutate()}>
            <Busy busy={assign.isPending}>Assign {picked.size || ""}</Busy>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
