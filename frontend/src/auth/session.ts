/**
 * The login session (FRONTEND_SPEC.md § 2.3, SECURITY_AND_ACCESS.md § 2.2).
 *
 * - The access token lives in memory only (never localStorage), so injected scripts can't read it
 *   from storage. After a reload it is fetched again with the HttpOnly refresh cookie.
 * - Only one tab refreshes at a time (Web Locks API). The refresh cookie rotates on every use; two
 *   tabs racing would look like a stolen token. A tab that loses the race gets
 *   TOKEN_ALREADY_ROTATED, and by then holds the new cookie, so it retries once.
 */

import type { components } from "@/api/schema";

export type User = components["schemas"]["UserView"];
type LoginResponse = components["schemas"]["LoginResponse"];

export type SessionState =
  { status: "loading" } | { status: "anonymous" } | { status: "authenticated"; user: User };

let accessToken: string | null = null;
let state: SessionState = { status: "loading" };
const listeners = new Set<() => void>();

export function getSession(): SessionState {
  return state;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function set(next: SessionState, token: string | null): void {
  accessToken = token;
  state = next;
  listeners.forEach((notify) => notify());
}

export function signedIn(response: LoginResponse): void {
  set({ status: "authenticated", user: response.user }, response.access_token);
}

export function signedOut(): void {
  set({ status: "anonymous" }, null);
}

async function postRefresh(): Promise<
  { ok: true; body: LoginResponse } | { ok: false; code: string }
> {
  // Plain fetch, not the API client: the client itself calls refresh on 401.
  const response = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    credentials: "same-origin",
  });
  if (response.ok) return { ok: true, body: (await response.json()) as LoginResponse };
  const error = (await response.json().catch(() => null)) as { error?: { code?: string } } | null;
  return { ok: false, code: error?.error?.code ?? "UNKNOWN" };
}

async function refreshOnce(): Promise<boolean> {
  for (let attempt = 0; attempt < 2; attempt++) {
    let result;
    try {
      result = await postRefresh();
    } catch {
      return false; // network error: keep the current state; the caller decides what to show
    }
    if (result.ok) {
      signedIn(result.body);
      return true;
    }
    if (result.code !== "TOKEN_ALREADY_ROTATED") break; // only that answer is worth a retry
  }
  signedOut();
  return false;
}

let inFlight: Promise<boolean> | null = null;

/** Get a fresh access token from the refresh cookie. Concurrent callers share one attempt. */
export function refreshSession(): Promise<boolean> {
  if (inFlight) return inFlight;
  const run = async (): Promise<boolean> =>
    navigator.locks
      ? await navigator.locks.request("xaminer-refresh", () => refreshOnce())
      : await refreshOnce();
  inFlight = run().finally(() => {
    inFlight = null;
  });
  return inFlight;
}
