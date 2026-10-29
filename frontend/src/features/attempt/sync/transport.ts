import { api, errorCode } from "@/api/client";

import { SendError, type AnswerOut, type Transport } from "./uploader";

/** Requests give up after this long and are retried (architecture § 9.6). */
export const TIMEOUT_MS = 10_000;

/** The attempt no longer takes changes: retrying won't help. */
const CLOSED = new Set(["TIME_UP", "ATTEMPT_SUBMITTED"]);

export function failure(response: Response, error: unknown): SendError {
  if (CLOSED.has(errorCode(error) ?? "")) return new SendError("closed", errorCode(error));
  if (response.status === 404) return new SendError("closed", "NOT_FOUND"); // voided
  // The session ran out and couldn't be refreshed: keep the change and retry after logging in.
  if (response.status === 401) return new SendError("network", "SESSION_EXPIRED");
  if (
    response.status >= 400 &&
    response.status < 500 &&
    response.status !== 408 &&
    response.status !== 429
  ) {
    return new SendError("invalid", errorCode(error) ?? String(response.status));
  }
  return new SendError("network", String(response.status));
}

async function call<T>(
  request: (signal: AbortSignal) => Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result;
  try {
    result = await request(AbortSignal.timeout(TIMEOUT_MS));
  } catch (error) {
    throw new SendError("network", String(error)); // offline, timeout, DNS ...
  }
  if (!result.response.ok) throw failure(result.response, result.error);
  return result.data as T;
}

/** The real transport: the typed API client with a timeout on every request. */
export const apiTransport: Transport = {
  saveAnswers: (attemptId, answers: AnswerOut[]) =>
    call((signal) =>
      api.PUT("/api/v1/attempts/{attempt_id}/answers", {
        params: { path: { attempt_id: attemptId } },
        body: { answers },
        signal,
      }),
    ),
  setFlag: async (attemptId, examQuestionId, marked) => {
    await call((signal) =>
      api.PUT("/api/v1/attempts/{attempt_id}/flags/{exam_question_id}", {
        params: { path: { attempt_id: attemptId, exam_question_id: examQuestionId } },
        body: { marked },
        signal,
      }),
    );
  },
  saveDraft: (attemptId, examQuestionId, draft) =>
    call((signal) =>
      api.PUT("/api/v1/attempts/{attempt_id}/drafts/{exam_question_id}", {
        params: { path: { attempt_id: attemptId, exam_question_id: examQuestionId } },
        body: draft,
        signal,
      }),
    ),
};
