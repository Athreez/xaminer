import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, History } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useParams } from "react-router";

import { api } from "@/api/client";
import { useSession } from "@/auth/hooks";
import { FormMessage } from "@/components/form";
import { Button } from "@/components/ui/button";

import { UserFields, type UserFieldValues } from "./UsersPage";
import { errorText, formatDateTime, isNotFound, roleLabel, unwrap, type AdminUser } from "./lib";
import {
  Busy,
  ConfirmDialog,
  ErrorState,
  LoadingRows,
  NotFoundBlock,
  PageHeader,
  StatusBadge,
} from "./shared";

type Action = "deactivate" | "reactivate" | "resend-invite" | "password-reset" | "unlock";

const done: Record<Action, (user: AdminUser) => string> = {
  deactivate: (u) => `${u.full_name} is deactivated and logged out everywhere.`,
  reactivate: (u) => `${u.full_name} can use their account again.`,
  "resend-invite": (u) => `A new invitation was sent to ${u.email}. The old link no longer works.`,
  "password-reset": (u) => `A password reset link was sent to ${u.email}.`,
  unlock: (u) => `${u.full_name}'s account is unlocked.`,
};

/** One user: edit details and account actions (FRONTEND_SPEC § 5.1, PRD USR-01, USR-04). */
export function UserDetailPage() {
  const { userId = "" } = useParams();
  const user = useQuery({
    queryKey: ["users", userId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/users/{user_id}", { params: { path: { user_id: userId } } })),
  });

  if (user.isPending) return <LoadingRows rows={6} />;
  if (user.isError) {
    if (isNotFound(user.error)) return <NotFoundBlock what="user" back="/admin/users" />;
    return <ErrorState error={user.error} onRetry={() => void user.refetch()} />;
  }
  // Keyed by id so the form resets when moving between users.
  return <UserDetail key={user.data.id} user={user.data} />;
}

function UserDetail({ user }: { user: AdminUser }) {
  const session = useSession();
  const location = useLocation();
  const queryClient = useQueryClient();
  const isMe = session.status === "authenticated" && session.user.id === user.id;

  const initial: UserFieldValues = {
    email: user.email,
    full_name: user.full_name,
    role: user.role,
    roll_no: user.roll_no ?? "",
  };
  const [form, setForm] = useState(initial);
  const [notice, setNotice] = useState<string | null>(
    (location.state as { notice?: string } | null)?.notice ?? null,
  );
  const [confirming, setConfirming] = useState<"deactivate" | null>(null);
  const changed = JSON.stringify(form) !== JSON.stringify(initial);
  const identityChanged = form.email.trim() !== user.email || form.role !== user.role;

  function refresh(updated: AdminUser) {
    queryClient.setQueryData(["users", user.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["users"], exact: false });
  }

  const save = useMutation({
    mutationFn: async () => {
      // Send only what changed, so a no-op never touches sessions.
      const body: Record<string, string | null> = {};
      if (form.full_name !== initial.full_name) body.full_name = form.full_name;
      if (form.email !== initial.email) body.email = form.email;
      if (form.role !== initial.role) body.role = form.role;
      if (form.roll_no !== initial.roll_no) body.roll_no = form.roll_no.trim() || null;
      return unwrap(
        await api.PATCH("/api/v1/users/{user_id}", {
          params: { path: { user_id: user.id } },
          body,
        }),
      );
    },
    onSuccess: (updated) => {
      setNotice(
        identityChanged
          ? "Saved. Because the email or role changed, they were logged out everywhere."
          : "Saved.",
      );
      refresh(updated);
    },
  });

  const act = useMutation({
    mutationFn: async (action: Action) => {
      const path = { params: { path: { user_id: user.id } } };
      const call = {
        deactivate: () => api.POST("/api/v1/users/{user_id}/deactivate", path),
        reactivate: () => api.POST("/api/v1/users/{user_id}/reactivate", path),
        "resend-invite": () => api.POST("/api/v1/users/{user_id}/resend-invite", path),
        "password-reset": () => api.POST("/api/v1/users/{user_id}/password-reset", path),
        unlock: () => api.POST("/api/v1/users/{user_id}/unlock", path),
      }[action];
      return { action, user: unwrap(await call()) };
    },
    onSuccess: ({ action, user: updated }) => {
      setConfirming(null);
      setNotice(done[action](updated));
      refresh(updated);
    },
    onError: () => setConfirming(null),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setNotice(null);
    act.reset();
    save.mutate();
  }

  const error = save.error ?? act.error;
  const pending = (action: Action) => act.isPending && act.variables === action;

  return (
    <section className="max-w-3xl">
      <Link
        to=".."
        relative="path"
        className="text-muted-foreground mb-4 inline-flex items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft className="size-4" /> All users
      </Link>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            {user.full_name}
            <StatusBadge status={user.status} locked={user.locked} />
          </span>
        }
        description={`${roleLabel[user.role]} · Added ${formatDateTime(user.created_at)} · Last login ${formatDateTime(user.last_login_at)}`}
        actions={
          <Button variant="outline" asChild>
            <Link to={`/admin/audit?target_type=user&target_id=${user.id}`}>
              <History /> History
            </Link>
          </Button>
        }
      />

      <div className="space-y-4">
        {notice && <FormMessage tone="success">{notice}</FormMessage>}
        {error && <FormMessage tone="error">{errorText(error)}</FormMessage>}
      </div>

      <div className="mt-4 grid gap-6 lg:grid-cols-[1fr_16rem]">
        <form onSubmit={onSubmit} className="bg-card shadow-card space-y-4 rounded-xl border p-6">
          <h2 className="font-semibold">Details</h2>
          <UserFields
            value={form}
            onChange={setForm}
            roleLocked={isMe ? "You can't change your own role." : undefined}
          />
          {identityChanged && (
            <FormMessage tone="info">
              Changing the email or role logs this user out on all their devices.
            </FormMessage>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={!changed || save.isPending}>
              <Busy busy={save.isPending}>Save changes</Busy>
            </Button>
            {changed && (
              <Button type="button" variant="ghost" onClick={() => setForm(initial)}>
                Undo
              </Button>
            )}
          </div>
        </form>

        <div className="bg-card shadow-card flex flex-col gap-2 self-start rounded-xl border p-6">
          <h2 className="mb-1 font-semibold">Account</h2>
          {user.status === "INVITED" && (
            <Button
              variant="outline"
              disabled={act.isPending}
              onClick={() => act.mutate("resend-invite")}
            >
              <Busy busy={pending("resend-invite")}>Resend invitation</Busy>
            </Button>
          )}
          {user.status === "ACTIVE" && (
            <Button
              variant="outline"
              disabled={act.isPending}
              onClick={() => act.mutate("password-reset")}
            >
              <Busy busy={pending("password-reset")}>Send password reset</Busy>
            </Button>
          )}
          {user.locked && (
            <Button variant="outline" disabled={act.isPending} onClick={() => act.mutate("unlock")}>
              <Busy busy={pending("unlock")}>Unlock account</Busy>
            </Button>
          )}
          {user.status === "DEACTIVATED" ? (
            <Button
              variant="outline"
              disabled={act.isPending}
              onClick={() => act.mutate("reactivate")}
            >
              <Busy busy={pending("reactivate")}>Reactivate</Busy>
            </Button>
          ) : (
            !isMe && (
              <Button
                variant="destructive"
                disabled={act.isPending}
                onClick={() => setConfirming("deactivate")}
              >
                Deactivate
              </Button>
            )
          )}
          <p className="text-muted-foreground mt-2 text-xs">
            Admins never see or set passwords. A reset sends the user a link instead.
          </p>
        </div>
      </div>

      <ConfirmDialog
        open={confirming === "deactivate"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={`Deactivate ${user.full_name}?`}
        description="They are logged out everywhere and can't log in until reactivated. Their past work is kept."
        confirmLabel="Deactivate"
        busy={pending("deactivate")}
        onConfirm={() => act.mutate("deactivate")}
      />
    </section>
  );
}
