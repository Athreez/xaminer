import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "@/api/client";
import { Field, FormMessage } from "@/components/form";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { errorText, formatDateTime, unwrap, useDebounced } from "./lib";
import { Busy, EmptyState, ErrorState, LoadingRows, PageHeader, TableCard } from "./shared";

/** Groups with member counts (FRONTEND_SPEC § 5.1, PRD USR-02). */
export function GroupsPage() {
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const [creating, setCreating] = useState(false);

  const groups = useQuery({
    queryKey: ["groups", { q }],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/groups", { params: { query: { q: q || undefined } } })),
  });

  return (
    <section>
      <PageHeader
        title="Groups"
        description='Sets of students, like "CSE-A 2026", so teachers can assign an exam to all of them.'
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> New group
          </Button>
        }
      />
      <div className="relative mb-4 max-w-md">
        <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input
          aria-label="Search groups"
          placeholder="Search groups"
          className="pl-9"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {groups.isPending ? (
        <LoadingRows rows={4} />
      ) : groups.isError ? (
        <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
      ) : groups.data.length === 0 ? (
        q ? (
          <EmptyState title="No groups match this search">
            <Button variant="outline" size="sm" onClick={() => setSearch("")}>
              Clear search
            </Button>
          </EmptyState>
        ) : (
          <EmptyState title="No groups yet">Create a group, then add students to it.</EmptyState>
        )
      ) : (
        <TableCard>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="text-right">Students</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.data.map((group) => (
                <TableRow key={group.id}>
                  <TableCell className="font-medium">
                    <Link to={group.id} className="hover:underline">
                      {group.name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{group.member_count}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(group.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableCard>
      )}

      <NameDialog
        open={creating}
        onOpenChange={setCreating}
        title="New group"
        submitLabel="Create group"
      />
    </section>
  );
}

/** Name a new group, or rename one (when `groupId` and `current` are given). */
export function NameDialog({
  open,
  onOpenChange,
  title,
  submitLabel,
  groupId,
  current = "",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  submitLabel: string;
  groupId?: string;
  current?: string;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState(current);

  const save = useMutation({
    mutationFn: async () =>
      groupId
        ? unwrap(
            await api.PATCH("/api/v1/groups/{group_id}", {
              params: { path: { group_id: groupId } },
              body: { name },
            }),
          )
        : unwrap(await api.POST("/api/v1/groups", { body: { name } })),
    onSuccess: (group) => {
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
      onOpenChange(false);
      if (!groupId) navigate(group.id);
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (next) setName(current);
        save.reset();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>Names must be unique in your institution.</DialogDescription>
        </DialogHeader>
        <form id="group-name" onSubmit={onSubmit} className="space-y-4" noValidate>
          {save.isError && <FormMessage tone="error">{errorText(save.error)}</FormMessage>}
          <Field label="Group name">
            {(props) => (
              <Input
                {...props}
                autoFocus
                maxLength={100}
                placeholder="CSE-A 2026"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            )}
          </Field>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="group-name"
            disabled={save.isPending || !name.trim() || name.trim() === current}
          >
            <Busy busy={save.isPending}>{submitLabel}</Busy>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
