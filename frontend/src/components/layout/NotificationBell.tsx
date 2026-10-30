import { Bell } from "lucide-react";
import { NavLink, useLocation } from "react-router";

import { notificationsPath, useNotifications } from "@/features/notifications/lib";
import { cn } from "@/lib/utils";

/** The bell with the unread count (PRD NOT-02); opens the notifications page. */
export function NotificationBell({ withLabel = false }: { withLabel?: boolean }) {
  const { pathname } = useLocation();
  const unread = useNotifications().data?.unread ?? 0;
  const label = unread ? `Notifications, ${unread} unread` : "Notifications";
  return (
    <NavLink
      to={notificationsPath(pathname)}
      aria-label={label}
      title={label}
      className={({ isActive }) =>
        cn(
          "hover:bg-accent relative inline-flex items-center gap-2 rounded-md px-2 py-2 text-sm font-medium",
          isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground",
        )
      }
    >
      <Bell className="size-4" aria-hidden />
      {withLabel && <span>Notifications</span>}
      {unread > 0 && (
        <span
          aria-hidden
          className="bg-primary text-primary-foreground min-w-5 rounded-full px-1.5 text-center text-xs leading-5 font-semibold tabular-nums"
        >
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </NavLink>
  );
}
