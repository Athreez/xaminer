import { useEffect, useState } from "react";

import type { ApiError } from "@/api/client";
import type { components } from "@/api/schema";

// Plain helpers for the admin pages (kept apart from components for fast refresh and tests).

export type AdminUser = components["schemas"]["AdminUserView"];
export type Role = AdminUser["role"];
export type UserStatus = AdminUser["status"];

/**
 * The data of an openapi-fetch result, or throws its API error (for TanStack Query).
 * 204 responses have no data, so success is judged by the HTTP status.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.response.ok) return result.data as T;
  throw (result.error as ApiError | undefined) ?? new Error(`HTTP ${result.response.status}`);
}

/** A sentence to show for an API error. Our server messages are written for people already. */
export function errorText(error: unknown): string {
  const body = (error as ApiError | undefined)?.error;
  if (!body) return "Can't reach the server. Check your connection and try again.";
  if (body.code === "VALIDATION_FAILED" && body.details?.length) {
    const first = body.details[0] as { field?: string; message?: string };
    const field = first.field?.split(".").pop();
    return field && field !== "body" && first.message
      ? `${field.replaceAll("_", " ")}: ${first.message}`
      : body.message;
  }
  if (body.code === "INTERNAL_ERROR" || !body.message) {
    return "Something went wrong. Try again in a moment.";
  }
  return body.message;
}

export function isNotFound(error: unknown): boolean {
  return (error as ApiError | undefined)?.error?.code === "NOT_FOUND";
}

/** `value`, but only after it has stopped changing for `ms` (for search boxes). */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

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

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

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
