import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { unwrap } from "@/lib/api";
import type { AnswerValue } from "@/features/questions/lib";

import {
  connection,
  restore,
  type AttemptView,
  type Connection,
  type Heartbeat,
  type Receipt,
} from "./lib";
import type { ServerClock } from "./sync/clock";
import { Outbox } from "./sync/outbox";
import { TIMEOUT_MS, apiTransport } from "./sync/transport";
import { Uploader, type Status } from "./sync/uploader";

/** Architecture § 9.6: a heartbeat every 15 s. */
const HEARTBEAT_MS = 15_000;
/** Typing is written to the device after this pause (each choice click is written at once). */
const TEXT_DEBOUNCE_MS = 300;
/** Code is written to the device after this pause in typing. */
const CODE_DEBOUNCE_MS = 800;
/** At time up, submitting is retried this often until it gets through. */
const SUBMIT_RETRY_MS = 5_000;
/** At time up, submitting waits until this long past the deadline by the server's clock. */
const SUBMIT_AFTER_DEADLINE_MS = 2_000;

/** Why answers can't be changed any more. */
export type Ended = "TIME_UP" | "SUBMITTED" | "AUTO_SUBMITTED" | "VOIDED";

export interface BrowserEvent {
  kind:
    | "FULLSCREEN_EXIT"
    | "TAB_SWITCH"
    | "PASTE_BLOCKED"
    | "MULTIPLE_SCREENS"
    | "FACE_ABSENT"
    | "MULTIPLE_FACES"
    | "GAZE_AWAY"
    | "VOICE_DETECTED"
    | "SCREEN_SHARE_STOPPED"
    | "LIVENESS_FAILED";
  /** When it started (ms since epoch); now by default. */
  at?: number;
  /** Given beforehand when pictures name the event; a new one otherwise. */
  clientId?: string;
  durationMs?: number;
  details?: Record<string, string | number | boolean>;
}

/** Joins the camera proctoring (when the exam has it) to the session: its frame count for the
 *  heartbeat, and events still open, recorded before submitting. */
/** Something proctoring sees right now, for the teacher's live monitor. */
export type Happening = { kind: string; seconds: number };

type ProctorSource = {
  frames: () => number;
  happening: () => Happening[];
  flush: () => Promise<void>;
};

export class ProctorLink {
  private source: ProctorSource | null = null;
  /** For picture uploads: the latest attempt token, and whether the student's work is all sent
   *  (pictures wait behind it). Set by the session. */
  private token: string | null = null;
  private isIdle: () => boolean = () => false;

  setToken(token: string): void {
    this.token = token;
  }

  setIdle(isIdle: () => boolean): void {
    this.isIdle = isIdle;
  }

  attemptToken(): string | null {
    return this.token;
  }

  idle(): boolean {
    return this.isIdle();
  }

  attach(source: ProctorSource | null): void {
    this.source = source;
  }

  frames(): number | undefined {
    return this.source?.frames();
  }

  happening(): Happening[] {
    return this.source?.happening() ?? [];
  }

  async flush(): Promise<void> {
    await this.source?.flush();
  }
}

export interface ExamSession {
  ready: boolean;
  /** Set if this browser can't keep answers on the device (the exam can't run safely). */
  storageError: unknown;
  answers: Record<string, AnswerValue>;
  flags: Record<string, boolean>;
  save: Status;
  connection: Connection;
  secondsLeft: number;
  ended: Ended | null;
  /** Minutes a teacher just added, for the banner (null when nothing to say). */
  extendedBy: number | null;
  dismissExtension: () => void;
  setAnswer: (examQuestionId: string, value: AnswerValue, typing?: boolean) => void;
  setFlag: (examQuestionId: string, marked: boolean) => void;
  /** A proctoring event for the teacher: queued like answers, sent last. */
  recordEvent: (event: BrowserEvent) => Promise<void>;
  /** Coding questions: saved code per language, and the language last used. */
  drafts: Record<string, Record<string, string>>;
  lastLanguage: Record<string, string>;
  /** Keep code for one language (written to the device after a short pause, then uploaded). */
  setDraft: (examQuestionId: string, languageKey: string, source: string) => void;
  /** Write what's typed and try to send everything now; resolves with what's still unsent. */
  sendAll: () => Promise<Status>;
  /** Submit the exam. Throws if the server can't be reached (nothing is lost: try again). */
  submit: () => Promise<void>;
  /** Set once the exam is submitted (by the student, at time up, or by the teacher). */
  receipt: Receipt | null;
  /** Changes that never reached the server before it ended (told honestly on the receipt). */
  lost: number;
}

/**
 * Runs one attempt on the exam screen (FRONTEND_SPEC § 6, rules § 6.8): every change goes to the
 * device first and is uploaded in the background, so the network never blocks the student. The
 * timer follows the server's clock; heartbeats bring teacher actions (extra time, force-submit).
 */
export function useExamSession(
  view: AttemptView,
  clock: ServerClock,
  proctor?: ProctorLink,
): ExamSession {
  const attemptId = view.id;
  const [ready, setReady] = useState(false);
  const [storageError, setStorageError] = useState<unknown>(null);
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({});
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [save, setSave] = useState<Status>({ state: "saved", unsent: 0, refused: 0 });
  const [online, setOnline] = useState(() => navigator.onLine);
  const [failingSince, setFailingSince] = useState<number | null>(null);
  const [deadline, setDeadline] = useState(view.deadline_at);
  const [closed, setEnded] = useState<Ended | null>(null); // said by the server
  const [extendedBy, setExtendedBy] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [lost, setLost] = useState(0);

  const tools = useRef<{ outbox: Outbox; uploader: Uploader } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [lastLanguage, setLastLanguage] = useState<Record<string, string>>({});
  // Typing not yet written to the device: answers and code, each written after a short pause.
  const typing = useRef(new Map<string, { timer: number; write: () => Promise<void> }>());
  const unsent = useRef(0);
  const locked = useRef(false);
  const finished = useRef(false); // submitted: stop heartbeats and uploads

  const reached = useCallback(() => setFailingSince(null), []);
  const failed = useCallback(() => setFailingSince((since) => since ?? Date.now()), []);

  const flush = useCallback(
    async (force = false): Promise<Status | null> => {
      const uploader = tools.current?.uploader;
      if (!uploader) return null;
      const status = await uploader.flush(force);
      setSave(status);
      if (status.state === "offline" || status.state === "failing") failed();
      else if (status.state === "saved") reached();
      return status;
    },
    [failed, reached],
  );

  const write = useCallback(
    async (examQuestionId: string, value: AnswerValue) => {
      const outbox = tools.current?.outbox;
      if (!outbox) return;
      await outbox.put(attemptId, "answer", examQuestionId, {
        exam_question_id: examQuestionId,
        ...value,
      });
      setSave((s) => (s.state === "saved" ? { ...s, state: "saving", unsent: s.unsent + 1 } : s));
      void flush();
    },
    [attemptId, flush],
  );

  const writeDraft = useCallback(
    async (examQuestionId: string, languageKey: string, source: string) => {
      const outbox = tools.current?.outbox;
      if (!outbox) return;
      await outbox.put(attemptId, "draft", `${examQuestionId}:${languageKey}`, {
        exam_question_id: examQuestionId,
        language_key: languageKey,
        source,
      });
      setSave((s) => (s.state === "saved" ? { ...s, state: "saving", unsent: s.unsent + 1 } : s));
      void flush();
    },
    [attemptId, flush],
  );

  /** Write `run` after a pause in typing (a newer change to the same `key` replaces it). */
  const later = useCallback((key: string, run: () => Promise<void>, delayMs: number) => {
    const waiting = typing.current.get(key);
    if (waiting) window.clearTimeout(waiting.timer);
    const timer = window.setTimeout(() => {
      typing.current.delete(key);
      void run();
    }, delayMs);
    typing.current.set(key, { timer, write: run });
  }, []);

  // Typing not yet written goes to the device now (leaving the page, submitting, time up).
  const writePending = useCallback(async () => {
    const waiting = [...typing.current.values()];
    typing.current.clear();
    await Promise.all(
      waiting.map(({ timer, write: run }) => {
        window.clearTimeout(timer);
        return run();
      }),
    );
  }, []);

  // Declared before the outbox effect so that, on leaving the page, typing is written before
  // the outbox closes (React cleans up effects in order).
  useEffect(() => {
    const leave = () => void writePending();
    window.addEventListener("pagehide", leave);
    return () => {
      window.removeEventListener("pagehide", leave);
      leave();
    };
  }, [writePending]);

  // Open the outbox, lay unsent changes over the server's copy, start uploading.
  useEffect(() => {
    let cancelled = false;
    let outbox: Outbox | null = null;
    (async () => {
      try {
        outbox = await Outbox.open();
        const pending = await outbox.pending(attemptId);
        const restored = restore(view.questions, pending);
        await outbox.ensureRevisionAbove(attemptId, restored.revision);
        if (cancelled) return;
        tools.current = {
          outbox,
          uploader: new Uploader(outbox, apiTransport, attemptId, {
            onServerTime: (sent, received, time) => clock.observe(sent, received, time),
          }),
        };
        proctor?.setIdle(() => tools.current?.uploader.idle() ?? false);
        setAnswers(restored.answers);
        setFlags(restored.flags);
        setDrafts(restored.drafts);
        setLastLanguage(restored.lastLanguage);
        // Changes left from last time are unsent until the uploader says otherwise.
        if (pending.length) setSave({ state: "saving", unsent: pending.length, refused: 0 });
        setReady(true);
        void flush();
      } catch (error) {
        if (!cancelled) setStorageError(error);
      }
    })();
    return () => {
      cancelled = true;
      tools.current = null;
      outbox?.close();
    };
  }, [attemptId, view.questions, clock, flush, proctor]);

  // Every second: the timer moves and whatever is queued gets another chance to go.
  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(Date.now());
      void flush();
    }, 1000);
    return () => window.clearInterval(id);
  }, [flush]);

  // Heartbeats: server time, deadline changes and the attempt's status.
  useEffect(() => {
    let previousDeadline = Date.parse(view.deadline_at);
    async function beat() {
      if (finished.current) return;
      const sentAt = Date.now();
      try {
        const { data, response } = await api.POST("/api/v1/attempts/{attempt_id}/heartbeat", {
          params: { path: { attempt_id: attemptId } },
          body: {
            unsynced: Math.min(unsent.current, 10_000),
            proctoring_frames: proctor?.frames(),
            proctoring_now: (proctor?.happening() ?? []) as never,
          },
          signal: AbortSignal.timeout(TIMEOUT_MS),
        });
        if (response.status === 404) return setEnded("VOIDED");
        if (!data) return failed();
        reached();
        apply(data, sentAt);
      } catch {
        failed();
      }
    }
    function apply(data: Heartbeat, sentAt: number) {
      clock.observe(sentAt, Date.now(), data.server_time);
      const next = Date.parse(data.deadline_at);
      const added = Math.round((next - previousDeadline) / 60_000);
      if (added > 0) setExtendedBy(added);
      previousDeadline = next;
      setDeadline(data.deadline_at);
      if (data.attempt_token) proctor?.setToken(data.attempt_token);
      if (data.status !== "IN_PROGRESS") setEnded(data.status);
    }
    void beat();
    const id = window.setInterval(beat, HEARTBEAT_MS);
    return () => window.clearInterval(id);
  }, [attemptId, view.deadline_at, clock, failed, reached, proctor]);

  useEffect(() => {
    const up = () => {
      setOnline(true);
      // Send at once instead of waiting out the backoff (up to 30 s).
      tools.current?.uploader.retryNow();
      void flush();
    };
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, [flush]);

  // While anything is unsent, closing the tab asks first (§ 6.3).
  useEffect(() => {
    if (save.unsent === 0) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [save.unsent]);

  const sendAll = useCallback(async (): Promise<Status> => {
    await writePending();
    return (await flush(true)) ?? { state: "saved", unsent: 0, refused: 0 };
  }, [writePending, flush]);

  // The exam is over on the server: keep the receipt, count what never got there, and forget
  // this attempt's outbox (the server refuses anything still in it).
  const finish = useCallback(
    async (done: Receipt) => {
      finished.current = true;
      const uploader = tools.current?.uploader;
      const left = uploader ? await uploader.flush(true) : null;
      setLost(left ? left.unsent + left.refused : 0);
      setReceipt(done);
      await tools.current?.outbox.clear(attemptId);
    },
    [attemptId],
  );

  const submit = useCallback(async () => {
    await proctor?.flush();
    await sendAll();
    const done = unwrap(
      await api.POST("/api/v1/attempts/{attempt_id}/submit", {
        params: { path: { attempt_id: attemptId } },
        signal: AbortSignal.timeout(TIMEOUT_MS),
      }),
    );
    await finish(done);
  }, [sendAll, attemptId, finish, proctor]);

  // Submitted elsewhere (the teacher, or the server after the grace): fetch the receipt.
  useEffect(() => {
    if (closed !== "SUBMITTED" && closed !== "AUTO_SUBMITTED") return;
    if (finished.current) return;
    void (async () => {
      const { data } = await api.GET("/api/v1/attempts/{attempt_id}/receipt", {
        params: { path: { attempt_id: attemptId } },
      });
      if (data) await finish(data);
    })();
  }, [closed, attemptId, finish]);

  const secondsLeft = clock.secondsLeft(deadline);
  void now; // re-rendered every second so the line above moves
  const ended: Ended | null =
    closed ?? (receipt ? receipt.status : ready && secondsLeft <= 0 ? "TIME_UP" : null);
  useEffect(() => {
    unsent.current = save.unsent;
    locked.current = ended !== null;
  }, [save.unsent, ended]);

  // Time up: send everything (the server takes saves for 60 s more), then submit, retrying until
  // it gets through. Past the grace the server ends the attempt itself and returns its receipt.
  // The timer shows 0 up to a second early and the clock estimate is approximate, so the submit
  // waits until the deadline has surely passed on the server: it then counts as automatic.
  useEffect(() => {
    if (ended !== "TIME_UP" || finished.current) return;
    void writePending().then(() => flush(true));
    let busy = false;
    let nextTry = Date.parse(deadline) + SUBMIT_AFTER_DEADLINE_MS;
    const id = window.setInterval(async () => {
      if (busy || finished.current || clock.serverNow() < nextTry) return;
      busy = true;
      try {
        await submit();
      } catch {
        nextTry = clock.serverNow() + SUBMIT_RETRY_MS;
      } finally {
        busy = false;
      }
    }, 500);
    return () => window.clearInterval(id);
  }, [ended, submit, deadline, clock, writePending, flush]);

  const setAnswer = useCallback(
    (examQuestionId: string, value: AnswerValue, isTyping = false) => {
      if (locked.current) return;
      setAnswers((all) => ({ ...all, [examQuestionId]: value }));
      const key = `answer:${examQuestionId}`;
      if (!isTyping) {
        const waiting = typing.current.get(key);
        if (waiting) window.clearTimeout(waiting.timer);
        typing.current.delete(key);
        void write(examQuestionId, value);
        return;
      }
      later(key, () => write(examQuestionId, value), TEXT_DEBOUNCE_MS);
    },
    [write, later],
  );

  const setDraft = useCallback(
    (examQuestionId: string, languageKey: string, source: string) => {
      if (locked.current) return;
      setDrafts((all) => ({
        ...all,
        [examQuestionId]: { ...all[examQuestionId], [languageKey]: source },
      }));
      setLastLanguage((all) => ({ ...all, [examQuestionId]: languageKey }));
      later(
        `draft:${examQuestionId}:${languageKey}`,
        () => writeDraft(examQuestionId, languageKey, source),
        CODE_DEBOUNCE_MS,
      );
    },
    [writeDraft, later],
  );

  const setFlag = useCallback(
    (examQuestionId: string, marked: boolean) => {
      if (locked.current) return;
      setFlags((all) => ({ ...all, [examQuestionId]: marked }));
      void (async () => {
        await tools.current?.outbox.put(attemptId, "flag", examQuestionId, { marked });
        void flush();
      })();
    },
    [attemptId, flush],
  );

  const recordEvent = useCallback(
    async (event: BrowserEvent) => {
      if (finished.current) return;
      const clientId = event.clientId ?? crypto.randomUUID();
      await tools.current?.outbox.put(attemptId, "event", clientId, {
        client_id: clientId,
        kind: event.kind,
        occurred_at: new Date(event.at ?? Date.now()).toISOString(),
        duration_ms: event.durationMs ?? null,
        details: event.details ?? {},
      });
      void flush();
    },
    [attemptId, flush],
  );

  return {
    ready,
    storageError,
    answers,
    flags,
    save,
    connection: connection(online, failingSince, now),
    secondsLeft,
    ended,
    extendedBy,
    dismissExtension: () => setExtendedBy(null),
    setAnswer,
    setFlag,
    recordEvent,
    drafts,
    lastLanguage,
    setDraft,
    sendAll,
    submit,
    receipt,
    lost,
  };
}
