import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { AnswerValue } from "@/features/questions/lib";

import { connection, restore, type AttemptView, type Connection, type Heartbeat } from "./lib";
import type { ServerClock } from "./sync/clock";
import { Outbox } from "./sync/outbox";
import { TIMEOUT_MS, apiTransport } from "./sync/transport";
import { Uploader, type Status } from "./sync/uploader";

/** Architecture § 9.6: a heartbeat every 15 s. */
const HEARTBEAT_MS = 15_000;
/** Typing is written to the device after this pause (each choice click is written at once). */
const TEXT_DEBOUNCE_MS = 300;

/** Why answers can't be changed any more. */
export type Ended = "TIME_UP" | "SUBMITTED" | "AUTO_SUBMITTED" | "VOIDED";

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
}

/**
 * Runs one attempt on the exam screen (FRONTEND_SPEC § 6, rules § 6.8): every change goes to the
 * device first and is uploaded in the background, so the network never blocks the student. The
 * timer follows the server's clock; heartbeats bring teacher actions (extra time, force-submit).
 */
export function useExamSession(view: AttemptView, clock: ServerClock): ExamSession {
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

  const tools = useRef<{ outbox: Outbox; uploader: Uploader } | null>(null);
  const typing = useRef(new Map<string, { timer: number; value: AnswerValue }>());
  const unsent = useRef(0);
  const locked = useRef(false);

  const reached = useCallback(() => setFailingSince(null), []);
  const failed = useCallback(() => setFailingSince((since) => since ?? Date.now()), []);

  const flush = useCallback(
    async (force = false) => {
      const uploader = tools.current?.uploader;
      if (!uploader) return;
      const status = await uploader.flush(force);
      setSave(status);
      if (status.state === "offline" || status.state === "failing") failed();
      else if (status.state === "saved") reached();
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

  // Typing not yet written goes to the device now (leaving the page, time up).
  const writePending = useCallback(() => {
    for (const [id, { timer, value }] of typing.current) {
      window.clearTimeout(timer);
      void write(id, value);
    }
    typing.current.clear();
  }, [write]);

  // Declared before the outbox effect so that, on leaving the page, typing is written before
  // the outbox closes (React cleans up effects in order).
  useEffect(() => {
    window.addEventListener("pagehide", writePending);
    return () => {
      window.removeEventListener("pagehide", writePending);
      writePending();
    };
  }, [writePending]);

  // Open the outbox, lay unsent changes over the server's copy, start uploading.
  useEffect(() => {
    let cancelled = false;
    let outbox: Outbox | null = null;
    (async () => {
      try {
        outbox = await Outbox.open();
        const restored = restore(view.questions, await outbox.pending(attemptId));
        await outbox.ensureRevisionAbove(attemptId, restored.revision);
        if (cancelled) return;
        tools.current = {
          outbox,
          uploader: new Uploader(outbox, apiTransport, attemptId, {
            onServerTime: (sent, received, time) => clock.observe(sent, received, time),
          }),
        };
        setAnswers(restored.answers);
        setFlags(restored.flags);
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
  }, [attemptId, view.questions, clock, flush]);

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
      const sentAt = Date.now();
      try {
        const { data, response } = await api.POST("/api/v1/attempts/{attempt_id}/heartbeat", {
          params: { path: { attempt_id: attemptId } },
          body: { unsynced: Math.min(unsent.current, 10_000) },
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
      if (data.status !== "IN_PROGRESS") setEnded(data.status);
    }
    void beat();
    const id = window.setInterval(beat, HEARTBEAT_MS);
    return () => window.clearInterval(id);
  }, [attemptId, view.deadline_at, clock, failed, reached]);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  // While anything is unsent, closing the tab asks first (§ 6.3).
  useEffect(() => {
    if (save.unsent === 0) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [save.unsent]);

  const secondsLeft = clock.secondsLeft(deadline);
  void now; // re-rendered every second so the line above moves
  const ended = closed ?? (ready && secondsLeft <= 0 ? "TIME_UP" : null);
  useEffect(() => {
    unsent.current = save.unsent;
    locked.current = ended !== null;
  }, [save.unsent, ended]);

  // Time up: write what's typed and send everything now (the server allows 60 s of grace).
  useEffect(() => {
    if (ended !== "TIME_UP") return;
    writePending();
    void flush(true);
  }, [ended, writePending, flush]);

  const setAnswer = useCallback(
    (examQuestionId: string, value: AnswerValue, isTyping = false) => {
      if (locked.current) return;
      setAnswers((all) => ({ ...all, [examQuestionId]: value }));
      const waiting = typing.current.get(examQuestionId);
      if (waiting) window.clearTimeout(waiting.timer);
      if (!isTyping) {
        typing.current.delete(examQuestionId);
        void write(examQuestionId, value);
        return;
      }
      const timer = window.setTimeout(() => {
        typing.current.delete(examQuestionId);
        void write(examQuestionId, value);
      }, TEXT_DEBOUNCE_MS);
      typing.current.set(examQuestionId, { timer, value });
    },
    [write],
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
  };
}
