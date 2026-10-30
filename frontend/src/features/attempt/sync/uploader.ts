import { backoffMs } from "./backoff";
import type { Entry, Outbox } from "./outbox";

/**
 * Sends the outbox to the server (architecture § 9.6). One uploader per attempt:
 *
 * - Answers go in one batch request; flags and code drafts one by one. Highest priority first.
 * - The server keeps only newer revisions; what it already had ("stale") is safe to drop.
 * - A failed request is retried after a jittered backoff (1 s → 30 s). Nothing ever blocks the
 *   student: they keep working and changes keep queueing.
 * - "Time up" or "already submitted" is final: those changes are kept aside and reported honestly.
 */

export type Failure = "network" | "closed" | "invalid";

/** Thrown by a transport. `closed`: the attempt no longer takes saves; `invalid`: this change is
 * refused (e.g. not a valid answer) and retrying won't help; `network`: try again later. */
export class SendError extends Error {
  readonly failure: Failure;

  constructor(failure: Failure, message: string = failure) {
    super(message);
    this.failure = failure;
  }
}

export interface AnswerOut {
  exam_question_id: string;
  selected_option_ids?: string[] | null;
  text_answer?: string | null;
  client_revision: number;
}

export interface Transport {
  saveAnswers(
    attemptId: string,
    answers: AnswerOut[],
  ): Promise<{ saved: string[]; stale: string[]; server_time: string }>;
  setFlag(attemptId: string, examQuestionId: string, marked: boolean): Promise<void>;
  saveDraft(
    attemptId: string,
    examQuestionId: string,
    draft: { language_key: string; source: string; client_revision: number },
  ): Promise<{ saved: boolean; server_time: string }>;
  sendEvents(attemptId: string, events: EventOut[]): Promise<void>;
}

/** A browser-check event as the API takes it. */
export interface EventOut {
  client_id: string;
  kind: string;
  occurred_at: string;
  duration_ms?: number | null;
  details?: Record<string, string | number | boolean>;
}

export type SaveState = "saved" | "saving" | "offline" | "failing";

export interface Status {
  state: SaveState;
  /** Changes not on the server yet (they are safe on this device). */
  unsent: number;
  /** Changes the server refused for good (e.g. made after time was up). */
  refused: number;
}

/** After this long without a successful upload, the status turns to "N answers not saved". */
export const FAILING_AFTER_MS = 60_000;
const MAX_BATCH = 200;

export interface UploaderOptions {
  now?: () => number;
  random?: () => number;
  /** Called with each response's send/receive times and server time, for the clock. */
  onServerTime?: (sentAt: number, receivedAt: number, serverTime: string) => void;
}

export class Uploader {
  private failures = 0;
  private firstFailureAt: number | null = null;
  private nextTryAt = 0;
  private inflight: Promise<void> | null = null;
  private unsent = 0;
  private refused = 0;
  private readonly now: () => number;
  private readonly random: () => number;

  private readonly outbox: Outbox;
  private readonly transport: Transport;
  private readonly attemptId: string;
  private readonly options: UploaderOptions;

  constructor(
    outbox: Outbox,
    transport: Transport,
    attemptId: string,
    options: UploaderOptions = {},
  ) {
    this.outbox = outbox;
    this.transport = transport;
    this.attemptId = attemptId;
    this.options = options;
    this.now = options.now ?? Date.now;
    this.random = options.random ?? Math.random;
  }

  status(): Status {
    let state: SaveState = "saved";
    if (this.unsent > 0) {
      if (this.firstFailureAt === null) state = "saving";
      else state = this.now() - this.firstFailureAt >= FAILING_AFTER_MS ? "failing" : "offline";
    }
    return { state, unsent: this.unsent, refused: this.refused };
  }

  /** True when there is nothing waiting (lower-priority uploads may go now). */
  idle(): boolean {
    return this.unsent === 0;
  }

  /** The connection is back (the browser said so): skip the rest of the backoff. */
  retryNow(): void {
    this.nextTryAt = 0;
  }

  /** When the next attempt is due after a failure (0 when it may go now). */
  retryAt(): number {
    return this.nextTryAt;
  }

  /**
   * Send what's queued, once. Respects the backoff unless `force` (submit, time up): then it also
   * waits for a send already under way and sends whatever is still queued after it, so the
   * answer typed a moment ago is never reported as unsent while it's on its way.
   */
  async flush(force = false): Promise<Status> {
    if (this.inflight && !force) return this.status(); // "saving" while it's under way
    while (this.inflight) await this.inflight;
    if (!force && this.now() < this.nextTryAt) {
      await this.count();
      return this.status();
    }
    this.inflight = this.send();
    try {
      await this.inflight;
    } finally {
      this.inflight = null;
    }
    return this.status();
  }

  private async send(): Promise<void> {
    try {
      const pending = await this.outbox.pending(this.attemptId);
      this.unsent = pending.length; // a status asked for meanwhile says "saving", not "saved"
      const answers = pending.filter((e) => e.kind === "answer").slice(0, MAX_BATCH);
      if (answers.length) await this.sendAnswers(answers);
      for (const entry of pending.filter((e) => e.kind === "flag" || e.kind === "draft")) {
        await this.sendOne(entry);
      }
      // Proctoring last, behind everything a student wrote (architecture § 9.6).
      const events = pending.filter((e) => e.kind === "event").slice(0, MAX_BATCH);
      if (events.length) await this.sendEvents(events);
      this.succeeded();
    } catch (error) {
      if (!(error instanceof SendError) || error.failure === "network") this.failed();
    } finally {
      await this.count();
    }
  }

  private async sendAnswers(batch: Entry[]): Promise<void> {
    const sentAt = this.now();
    try {
      const result = await this.transport.saveAnswers(
        this.attemptId,
        batch.map((e) => ({ ...e.payload, client_revision: e.revision }) as AnswerOut),
      );
      this.options.onServerTime?.(sentAt, this.now(), result.server_time);
      // Saved, or the server already had something at least as new: either way, done here.
      await this.outbox.confirm(batch);
    } catch (error) {
      // One bad answer refuses the whole batch: send them one by one so only that one is set aside.
      if (error instanceof SendError && error.failure === "invalid" && batch.length > 1) {
        for (const entry of batch) await this.sendAnswers([entry]);
        return;
      }
      await this.handle(error, batch);
    }
  }

  private async sendEvents(batch: Entry[]): Promise<void> {
    try {
      await this.transport.sendEvents(
        this.attemptId,
        batch.map((e) => e.payload as unknown as EventOut),
      );
      await this.outbox.confirm(batch);
    } catch (error) {
      await this.handle(error, batch);
    }
  }

  private async sendOne(entry: Entry): Promise<void> {
    try {
      if (entry.kind === "flag") {
        await this.transport.setFlag(this.attemptId, entry.target, Boolean(entry.payload.marked));
      } else {
        const sentAt = this.now();
        const result = await this.transport.saveDraft(
          this.attemptId,
          String(entry.payload.exam_question_id),
          {
            language_key: String(entry.payload.language_key),
            source: String(entry.payload.source),
            client_revision: entry.revision,
          },
        );
        this.options.onServerTime?.(sentAt, this.now(), result.server_time);
      }
      await this.outbox.confirm([entry]);
    } catch (error) {
      await this.handle(error, [entry]);
    }
  }

  /** Final refusals are recorded and the rest carries on; network trouble stops this pass. */
  private async handle(error: unknown, entries: Entry[]): Promise<void> {
    if (error instanceof SendError && error.failure === "closed") {
      // The attempt is over: nothing still queued can be saved. Keep it aside, say so honestly.
      await this.outbox.reject(await this.outbox.pending(this.attemptId), "closed");
      throw error;
    }
    if (error instanceof SendError && error.failure === "invalid") {
      await this.outbox.reject(entries, "invalid");
      return;
    }
    throw error instanceof SendError ? error : new SendError("network", String(error));
  }

  private succeeded(): void {
    this.failures = 0;
    this.firstFailureAt = null;
    this.nextTryAt = 0;
  }

  private failed(): void {
    this.failures += 1;
    this.firstFailureAt ??= this.now();
    this.nextTryAt = this.now() + backoffMs(this.failures, this.random);
  }

  private async count(): Promise<void> {
    // Events aren't the student's work: they never make the screen say "not saved".
    this.unsent = (await this.outbox.pending(this.attemptId)).filter(
      (e) => e.kind !== "event",
    ).length;
    this.refused = (await this.outbox.rejected(this.attemptId)).length;
  }
}
