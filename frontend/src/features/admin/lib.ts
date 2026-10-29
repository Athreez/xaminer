import type { components } from "@/api/schema";

// Admin-only helpers. Shared API helpers live in @/lib/api.

export type AdminUser = components["schemas"]["AdminUserView"];

export type Role = AdminUser["role"];

export type UserStatus = AdminUser["status"];

export const roleLabel: Record<Role, string> = {
  ADMIN: "Admin",
  TEACHER: "Teacher",
  STUDENT: "Student",
};

export const statusLabel: Record<UserStatus, string> = {
  ACTIVE: "Active",
  INVITED: "Invited",
  DEACTIVATED: "Deactivated",
};

/** Local midnight of a "2026-03-10" date-input value as an ISO instant, plus `plusDays`. */
export function dayStart(day: string, plusDays = 0): string {
  const [y = 1970, m = 1, d = 1] = day.split("-").map(Number);
  return new Date(y, m - 1, d + plusDays).toISOString();
}

/** "user.password_reset_sent" → "User · password reset sent" */
export function actionText(action: string): string {
  const [area = "", ...rest] = action.split(".");
  const what = rest.join(".").replaceAll("_", " ");
  const label = area.charAt(0).toUpperCase() + area.slice(1);
  return what ? `${label} · ${what}` : label;
}
