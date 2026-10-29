import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pencil, Search, Trash2, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { FormMessage } from "@/components/form";
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

import { NameDialog } from "./GroupsPage";
import { errorText, isNotFound, unwrap, useDebounced } from "@/lib/api";
import {
  Busy,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingRows,
  NotFoundBlock,
  PageHeader,
  TableCard,
} from "@/components/page";
import { StatusBadge } from "./shared";

type Group = components["schemas"]["GroupDetail"];

/** One group: its students, add/remove, rename, delete (FRONTEND_SPEC § 5.1). */
export function GroupDetailPage() {
  const { groupId = "" } = useParams();
  const group = useQuery({
    queryKey: ["groups", groupId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/groups/{group_id}", { params: { path: { group_id: groupId } } }),
      ),
  });

  if (group.isPending) return <LoadingRows rows={6} />;
  if (group.isError) {
    if (isNotFound(group.error)) return <NotFoundBlock what="group" back="/admin/groups" />;
    return <ErrorState error={group.error} onRetry={() => void group.refetch()} />;
  }
  return <GroupDetail group={group.data} />;
}

function GroupDetail({ group }: { group: Group }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [dialog, setDialog] = useState<"rename" | "delete" | "add" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const remove = useMutation({
    mutationFn: async (userId: string) =>
      unwrap(
        await api.DELETE("/api/v1/groups/{group_id}/members/{user_id}", {
          params: { path: { group_id: group.id, user_id: userId } },
        }),
      ),
    onSuccess: () => {
      setNotice(null);
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
    },
  });

  const destroy = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/api/v1/groups/{group_id}", {
          params: { path: { group_id: group.id } },
        }),
      ),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["groups", group.id] });
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
      navigate("/admin/groups", { replace: true });
    },
  });

  const error = remove.error ?? destroy.error;

  return (
    <section className="max-w-4xl">
      <Link
        to="/admin/groups"
        className="text-muted-foreground mb-4 inline-flex items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft className="size-4" /> All groups
      </Link>
      <PageHeader
        title={group.name}
        description={`${group.member_count} ${group.member_count === 1 ? "student" : "students"}`}
        actions={
          <>
            <Button variant="outline" onClick={() => setDialog("rename")}>
              <Pencil /> Rename
            </Button>
            <Button variant="outline" onClick={() => setDialog("delete")}>
              <Trash2 /> Delete
            </Button>
            <Button onClick={() => setDialog("add")}>
              <UserPlus /> Add students
            </Button>
          </>
        }
      />
      <div className="mb-4 space-y-4">
        {notice && <FormMessage tone="success">{notice}</FormMessage>}
        {error && <FormMessage tone="error">{errorText(error)}</FormMessage>}
      </div>

      {group.members.length === 0 ? (
        <EmptyState title="No students in this group yet">
          <Button size="sm" onClick={() => setDialog("add")}>
            <UserPlus /> Add students
          </Button>
        </EmptyState>
      ) : (
        <TableCard>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Roll no.</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-12">
                  <span className="sr-only">Remove</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {group.members.map((member) => (
                <TableRow key={member.id}>
                  <TableCell>{member.roll_no ?? "—"}</TableCell>
                  <TableCell className="font-medium">
                    <Link to={`/admin/users/${member.id}`} className="hover:underline">
                      {member.full_name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{member.email}</TableCell>
                  <TableCell>
                    <StatusBadge status={member.status} />
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove ${member.full_name} from the group`}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(member.id)}
                    >
                      <X />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableCard>
      )}

      <NameDialog
        open={dialog === "rename"}
        onOpenChange={(open) => setDialog(open ? "rename" : null)}
        title="Rename group"
        submitLabel="Save"
        groupId={group.id}
        current={group.name}
      />
      <ConfirmDialog
        open={dialog === "delete"}
        onOpenChange={(open) => setDialog(open ? "delete" : null)}
        title={`Delete "${group.name}"?`}
        description="Only the group is deleted. The students in it keep their accounts."
        confirmLabel="Delete group"
        busy={destroy.isPending}
        onConfirm={() => destroy.mutate()}
      />
      <AddStudentsDialog
        open={dialog === "add"}
        onOpenChange={(open) => setDialog(open ? "add" : null)}
        group={group}
        onAdded={(count) => setNotice(`${count} ${count === 1 ? "student" : "students"} added.`)}
      />
    </section>
  );
}

/** Search students and tick several to add at once. */
function AddStudentsDialog({
  open,
  onOpenChange,
  group,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  group: Group;
  onAdded: (count: number) => void;
}) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const inGroup = new Set(group.members.map((m) => m.id));

  const students = useQuery({
    enabled: open,
    queryKey: ["users", { role: "STUDENT", q, picker: true }],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/users", {
          params: { query: { role: "STUDENT", q: q || undefined, limit: 100 } },
        }),
      ),
  });
  // Deactivated students can't be added (the server refuses them too).
  const choices = (students.data?.data ?? []).filter((s) => s.status !== "DEACTIVATED");

  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/groups/{group_id}/members", {
          params: { path: { group_id: group.id } },
          body: { user_ids: [...picked] },
        }),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(["groups", group.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
      onAdded(picked.size);
      onOpenChange(false);
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

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) {
          setPicked(new Set());
          setSearch("");
          add.reset();
        }
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add students to {group.name}</DialogTitle>
          <DialogDescription>
            Search by name, email or roll number, then tick students.
          </DialogDescription>
        </DialogHeader>
        {add.isError && <FormMessage tone="error">{errorText(add.error)}</FormMessage>}
        <div className="relative">
          <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            aria-label="Search students"
            placeholder="Search students"
            className="pl-9"
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="max-h-80 overflow-y-auto rounded-lg border">
          {students.isPending ? (
            <div className="p-3">
              <LoadingRows rows={4} />
            </div>
          ) : students.isError ? (
            <div className="p-3">
              <ErrorState error={students.error} onRetry={() => void students.refetch()} />
            </div>
          ) : choices.length === 0 ? (
            <p className="text-muted-foreground p-6 text-center text-sm">
              {q
                ? "No students match this search."
                : "No students yet. Add them on the Users page."}
            </p>
          ) : (
            <ul className="divide-y">
              {choices.map((student) => {
                const already = inGroup.has(student.id);
                const id = `pick-${student.id}`;
                return (
                  <li key={student.id}>
                    <label
                      htmlFor={id}
                      className="hover:bg-accent/50 flex cursor-pointer items-center gap-3 px-3 py-2 has-[:disabled]:cursor-default has-[:disabled]:opacity-60"
                    >
                      <Checkbox
                        id={id}
                        checked={already || picked.has(student.id)}
                        disabled={already}
                        onCheckedChange={(on) => toggle(student.id, on === true)}
                      />
                      <span className="flex-1">
                        <span className="block text-sm font-medium">{student.full_name}</span>
                        <span className="text-muted-foreground block text-xs">
                          {[student.roll_no, student.email].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      {already && <span className="text-muted-foreground text-xs">In group</span>}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        {students.data?.next_cursor && (
          <p className="text-muted-foreground text-xs">
            Showing the first 100 students. Search to find others.
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={picked.size === 0 || add.isPending} onClick={() => add.mutate()}>
            <Busy busy={add.isPending}>
              Add {picked.size || ""} {picked.size === 1 ? "student" : "students"}
            </Busy>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
