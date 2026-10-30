import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { api } from "@/api/client";
import { Busy, EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/page";
import { Button } from "@/components/ui/button";
import { formatDateTime, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import { NOTIFICATIONS_KEY, useNotifications } from "./lib";

/** Your notifications, newest first (PRD NOT-02). Opening one marks it read. */
export function NotificationsPage() {
  const list = useNotifications();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });

  const readAll = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/notifications/read-all")),
    onSuccess: refresh,
  });
  const open = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/notifications/{notification_id}/read", {
          params: { path: { notification_id: id } },
        }),
      ),
    onSettled: refresh,
  });

  return (
    <section className="mx-auto max-w-3xl">
      <PageHeader
        title="Notifications"
        actions={
          (list.data?.unread ?? 0) > 0 && (
            <Button variant="outline" onClick={() => readAll.mutate()} disabled={readAll.isPending}>
              <Busy busy={readAll.isPending}>Mark all as read</Busy>
            </Button>
          )
        }
      />
      {list.isPending ? (
        <LoadingRows rows={4} />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.data.items.length === 0 ? (
        <EmptyState title="Nothing yet">New exams and released results show up here.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {list.data.items.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => {
                  if (!n.read) open.mutate(n.id);
                  if (n.link) void navigate(n.link);
                }}
                className={cn(
                  "bg-card hover:border-primary/40 w-full rounded-xl border p-4 text-left transition-colors",
                  !n.read && "border-primary/30",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <p className={cn("font-medium", !n.read && "font-semibold")}>
                    {!n.read && (
                      <span className="bg-primary mr-2 inline-block size-2 rounded-full align-middle">
                        <span className="sr-only">Unread: </span>
                      </span>
                    )}
                    {n.title}
                  </p>
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {formatDateTime(n.created_at)}
                  </span>
                </div>
                {n.body && <p className="text-muted-foreground mt-1 text-sm">{n.body}</p>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
