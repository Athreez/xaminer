import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * Typed API client. Paths, request bodies and responses come from the backend's OpenAPI spec
 * (`make api-client`), so a backend change that breaks the frontend fails `npm run typecheck`.
 *
 * Same origin as the app (nginx in Docker, the Vite proxy in `npm run dev`), so no CORS.
 */
export const api = createClient<paths>({ baseUrl: "" });

/** Every API error has this shape (TECHNICAL_ARCHITECTURE.md § 8). Switch on `code`. */
export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: { field: string; message: string; type: string }[];
    request_id?: string;
  };
}
