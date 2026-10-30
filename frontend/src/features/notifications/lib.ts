import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { unwrap } from "@/lib/api";

export const NOTIFICATIONS_KEY = ["notifications"];

/** The latest notifications and the unread count, checked every minute (and on focus). */
export function useNotifications() {
  return useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: async () => unwrap(await api.GET("/api/v1/notifications")),
    refetchInterval: 60_000,
  });
}

/** `/student/notifications` from `/student/...`: each role's shell has its own page. */
export function notificationsPath(pathname: string): string {
  return `/${pathname.split("/")[1] ?? ""}/notifications`;
}
