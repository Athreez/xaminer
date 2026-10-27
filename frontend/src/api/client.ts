import createClient from "openapi-fetch";

import { getAccessToken, refreshSession } from "@/auth/session";

import type { paths } from "./schema";

/**
 * Sends the access token, and on a 401 refreshes the session once and retries the request.
 * Auth endpoints are left alone (login, refresh, logout must never trigger a refresh loop).
 */
async function authedFetch(request: Request): Promise<Response> {
  const isAuthCall = new URL(request.url).pathname.startsWith("/api/v1/auth/");
  const withToken = (req: Request): Request => {
    const token = getAccessToken();
    if (!token) return req;
    const headers = new Headers(req.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return new Request(req, { headers });
  };

  const retryCopy = request.clone(); // the body can only be read once
  const response = await fetch(withToken(request));
  const needsRefresh =
    response.status === 401 &&
    (!isAuthCall || new URL(request.url).pathname.match(/\/auth\/(me|logout-all)$/));
  if (!needsRefresh) return response;
  return (await refreshSession()) ? fetch(withToken(retryCopy)) : response;
}

/**
 * Typed API client. Paths, request bodies and responses come from the backend's OpenAPI spec
 * (`make api-client`), so a backend change that breaks the frontend fails `npm run typecheck`.
 *
 * Same origin as the app (nginx in Docker, the Vite proxy in `npm run dev`), so no CORS.
 */
export const api = createClient<paths>({ baseUrl: "", fetch: authedFetch });

/** Every API error has this shape (TECHNICAL_ARCHITECTURE.md § 8). Switch on `code`. */
export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>[];
    request_id?: string;
  };
}

export function errorCode(error: unknown): string | undefined {
  return (error as ApiError | undefined)?.error?.code;
}
