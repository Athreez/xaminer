import { useEffect, useState } from "react";

import type { ApiError } from "@/api/client";

// Helpers for pages that call the API: results, error messages, search boxes, dates.

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

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
