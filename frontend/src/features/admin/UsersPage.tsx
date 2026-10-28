import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

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

import {
  errorText,
  roleLabel,
  statusLabel,
  unwrap,
  useDebounced,
  type Role,
  type UserStatus,
} from "./lib";
import {
  Busy,
  EmptyState,
  ErrorState,
  LoadingRows,
  PageHeader,
  StatusBadge,
  TableCard,
} from "./shared";

const ALL = "all";

/** Users (FRONTEND_SPEC § 5.1). Filters live in the address bar so Back and reload keep them. */
export function UsersPage() {
  const [params, setParams] = useSearchParams();
  const role = (params.get("role") as Role | null) ?? undefined;
  const status = (params.get("status") as UserStatus | null) ?? undefined;
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search.trim(), 300);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (q) next.set("q", q);
        else next.delete("q");
        return next;
      },
      { replace: true },
    );
  }, [q, setParams]);

  function setFilter(name: "role" | "status", value: string) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value === ALL) next.delete(name);
      else next.set(name, value);
      return next;
    });
  }

  const filtered = Boolean(role || status || q);
  const users = useInfiniteQuery({
    queryKey: ["users", { role, status, q }],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/users", {
          params: { query: { role, status, q: q || undefined, cursor: pageParam, limit: 50 } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = users.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <section>
      <PageHeader
        title="Users"
        description="Everyone in your institution. New users get an email to set their password."
        actions={
          <Button onClick={() => setAdding(true)}>
            <Plus /> Add user
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <div className="relative min-w-64 flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            aria-label="Search by name, email or roll number"
            placeholder="Search name, email or roll no."
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select value={role ?? ALL} onValueChange={(v) => setFilter("role", v)}>
          <SelectTrigger className="w-40" aria-label="Role">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All roles</SelectItem>
            {Object.entries(roleLabel).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={status ?? ALL} onValueChange={(v) => setFilter("status", v)}>
          <SelectTrigger className="w-40" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            {Object.entries(statusLabel).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {users.isPending ? (
        <LoadingRows />
      ) : users.isError ? (
        <ErrorState error={users.error} onRetry={() => void users.refetch()} />
      ) : rows.length === 0 ? (
        filtered ? (
          <EmptyState title="No users match these filters">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSearch("");
                setParams({});
              }}
            >
              Clear filters
            </Button>
          </EmptyState>
        ) : (
          <EmptyState title="No users yet">
            Add your teachers and students to get started.
          </EmptyState>
        )
      ) : (
        <>
          <TableCard>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Roll no.</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">
                      <Link to={user.id} className="hover:underline">
                        {user.full_name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{user.email}</TableCell>
                    <TableCell>{roleLabel[user.role]}</TableCell>
                    <TableCell>{user.roll_no ?? "—"}</TableCell>
                    <TableCell>
                      <StatusBadge status={user.status} locked={user.locked} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableCard>
          {users.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={users.isFetchingNextPage}
                onClick={() => void users.fetchNextPage()}
              >
                <Busy busy={users.isFetchingNextPage}>Load more</Busy>
              </Button>
            </div>
          )}
        </>
      )}

      <AddUserDialog open={adding} onOpenChange={setAdding} />
    </section>
  );
}

function AddUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    email: "",
    full_name: "",
    role: "STUDENT" as Role,
    roll_no: "",
  });

  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/users", {
          body: { ...form, roll_no: form.roll_no.trim() || null },
        }),
      ),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      onOpenChange(false);
      setForm({ email: "", full_name: "", role: form.role, roll_no: "" });
      create.reset();
      navigate(user.id, { state: { notice: `Invitation sent to ${user.email}.` } });
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
        if (!next) create.reset();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add user</DialogTitle>
          <DialogDescription>
            They get an email with a link to set their password. The link works for 7 days.
          </DialogDescription>
        </DialogHeader>
        <form id="add-user" onSubmit={onSubmit} className="space-y-4" noValidate>
          {create.isError && <FormMessage tone="error">{errorText(create.error)}</FormMessage>}
          <UserFields value={form} onChange={setForm} />
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="add-user"
            disabled={create.isPending || !form.email.trim() || !form.full_name.trim()}
          >
            <Busy busy={create.isPending}>Send invitation</Busy>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export interface UserFieldValues {
  email: string;
  full_name: string;
  role: Role;
  roll_no: string;
}

/** Name, email, role and roll number: shared by "Add user" and the user page. */
export function UserFields({
  value,
  onChange,
  roleLocked,
}: {
  value: UserFieldValues;
  onChange: (value: UserFieldValues) => void;
  /** Shown read-only (an admin can't change their own role). */
  roleLocked?: string;
}) {
  const set = <K extends keyof UserFieldValues>(key: K, v: UserFieldValues[K]) =>
    onChange({ ...value, [key]: v });
  return (
    <>
      <Field label="Full name">
        {(props) => (
          <Input
            {...props}
            autoFocus
            value={value.full_name}
            onChange={(e) => set("full_name", e.target.value)}
          />
        )}
      </Field>
      <Field label="Email">
        {(props) => (
          <Input
            {...props}
            type="email"
            value={value.email}
            onChange={(e) => set("email", e.target.value)}
          />
        )}
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Role">
          {(props) => (
            <Select
              value={value.role}
              onValueChange={(v) => set("role", v as Role)}
              disabled={Boolean(roleLocked)}
            >
              <SelectTrigger {...props} className="w-full" title={roleLocked}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(roleLabel).map(([v, label]) => (
                  <SelectItem key={v} value={v}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>
        <Field label="Roll no. (optional)">
          {(props) => (
            <Input
              {...props}
              value={value.roll_no}
              onChange={(e) => set("roll_no", e.target.value)}
            />
          )}
        </Field>
      </div>
      {roleLocked && <p className="text-muted-foreground text-xs">{roleLocked}</p>}
    </>
  );
}
