import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it } from "vitest";

import { BASE_MS, MAX_MS, backoffMs } from "./backoff";
import { ServerClock } from "./clock";
import { Outbox } from "./outbox";
import { FAILING_AFTER_MS, SendError, Uploader, type AnswerOut, type Transport } from "./uploader";

const ATTEMPT = "attempt-1";

// ----------------------------------------------------------------------------- clock

describe("ServerClock", () => {
  it("takes the midpoint of the round trip", () => {
    const clock = new ServerClock(() => 10_000);
    // Sent at 1000, back at 1200: the server read its clock around 1100 (device time).
    clock.observe(1_000, 1_200, new Date(6_100).toISOString());
    expect(clock.offsetMs()).toBe(5_000);
    expect(clock.serverNow()).toBe(15_000);
  });

  it("trusts the sample with the shortest round trip", () => {
    const clock = new ServerClock(() => 10_000);
    clock.observe(1_000, 3_000, new Date(9_000).toISOString()); // slow: offset 7000
    clock.observe(4_000, 4_100, new Date(9_050).toISOString()); // fast: offset 5000
    clock.observe(5_000, 6_000, new Date(12_000).toISOString()); // slow again
    expect(clock.offsetMs()).toBe(5_000);
  });

  it("forgets old samples and ignores nonsense", () => {
    let now = 0;
    const clock = new ServerClock(() => now);
    clock.observe(0, 100, new Date(5_050).toISOString());
    now = 11 * 60 * 1000;
    expect(clock.offsetMs()).toBe(0);
    clock.observe(200, 100, new Date(0).toISOString()); // received before sent
    clock.observe(0, 100, "not a time");
    expect(clock.offsetMs()).toBe(0);
  });

  it("counts down from the server's time, never below zero", () => {
    const clock = new ServerClock(() => 0);
    clock.observe(0, 0, new Date(60_000).toISOString()); // device is a minute behind
    expect(clock.secondsLeft(new Date(120_500).toISOString())).toBe(60);
    expect(clock.secondsLeft(new Date(1_000).toISOString())).toBe(0);
  });
});

// ----------------------------------------------------------------------------- backoff

describe("backoffMs", () => {
  it("doubles from 1 s to a 30 s ceiling, with jitter in the upper half", () => {
    expect(backoffMs(0)).toBe(0);
    expect(backoffMs(1, () => 0)).toBe(BASE_MS / 2);
    expect(backoffMs(1, () => 1)).toBe(BASE_MS);
    expect(backoffMs(3, () => 1)).toBe(4_000);
    expect(backoffMs(50, () => 1)).toBe(MAX_MS);
    for (let i = 0; i < 20; i++) {
      const delay = backoffMs(10);
      expect(delay).toBeGreaterThanOrEqual(MAX_MS / 2);
      expect(delay).toBeLessThanOrEqual(MAX_MS);
    }
  });
});

// ----------------------------------------------------------------------------- outbox

describe("Outbox", () => {
  let factory: IDBFactory;
  beforeEach(() => {
    factory = new IDBFactory();
  });

  it("survives a reload, and revisions keep rising", async () => {
    const first = await Outbox.open(factory);
    await first.put(ATTEMPT, "answer", "q1", { exam_question_id: "q1", text_answer: "a" });
    await first.put(ATTEMPT, "answer", "q2", { exam_question_id: "q2", text_answer: "b" });
    first.close(); // the browser reloads

    const again = await Outbox.open(factory);
    const pending = await again.pending(ATTEMPT);
    expect(pending.map((e) => [e.target, e.revision])).toEqual([
      ["q1", 1],
      ["q2", 2],
    ]);
    const next = await again.put(ATTEMPT, "answer", "q3", { exam_question_id: "q3" });
    expect(next.revision).toBe(3);
  });

  it("keeps only the newest change per question", async () => {
    const outbox = await Outbox.open(factory);
    await outbox.put(ATTEMPT, "answer", "q1", { text_answer: "first" });
    await outbox.put(ATTEMPT, "answer", "q1", { text_answer: "second" });
    const [only, ...rest] = await outbox.pending(ATTEMPT);
    expect(rest).toEqual([]);
    expect(only?.payload).toEqual({ text_answer: "second" });
    expect(only?.revision).toBe(2);
  });

  it("starts above what the server already has", async () => {
    const outbox = await Outbox.open(factory);
    await outbox.ensureRevisionAbove(ATTEMPT, 41);
    expect((await outbox.put(ATTEMPT, "answer", "q1", {})).revision).toBe(42);
    await outbox.ensureRevisionAbove(ATTEMPT, 5); // never goes down
    expect((await outbox.put(ATTEMPT, "answer", "q2", {})).revision).toBe(43);
  });

  it("removes a sent change only if it wasn't changed again meanwhile", async () => {
    const outbox = await Outbox.open(factory);
    const sent = await outbox.put(ATTEMPT, "answer", "q1", { text_answer: "sent" });
    await outbox.put(ATTEMPT, "answer", "q1", { text_answer: "typed during upload" });
    await outbox.confirm([sent]);
    const [left] = await outbox.pending(ATTEMPT);
    expect(left?.payload).toEqual({ text_answer: "typed during upload" });
  });

  it("orders by priority, then age, and keeps attempts apart", async () => {
    const outbox = await Outbox.open(factory);
    await outbox.put(ATTEMPT, "flag", "q2", { marked: true }, 300);
    await outbox.put(ATTEMPT, "answer", "q1", {}, 100);
    await outbox.put("other-attempt", "answer", "q9", {}, 50);
    await outbox.put(ATTEMPT, "draft", "q3:python312", {}, 200);
    expect((await outbox.pending(ATTEMPT)).map((e) => e.target)).toEqual([
      "q1",
      "q3:python312",
      "q2",
    ]);
    await outbox.clear(ATTEMPT);
    expect(await outbox.pending(ATTEMPT)).toEqual([]);
    expect(await outbox.pending("other-attempt")).toHaveLength(1);
  });
});

// ----------------------------------------------------------------------------- uploader

type Call = { kind: string; detail: unknown };

function fakeTransport(behaviour: { fail?: SendError | Error | null } = {}) {
  const calls: Call[] = [];
  const transport: Transport = {
    saveAnswers: async (_attempt, answers: AnswerOut[]) => {
      calls.push({ kind: "answers", detail: answers });
      if (behaviour.fail) throw behaviour.fail;
      return {
        saved: answers.map((a) => a.exam_question_id),
        stale: [],
        server_time: "2026-11-01T10:00:00Z",
      };
    },
    setFlag: async (_attempt, question, marked) => {
      calls.push({ kind: "flag", detail: [question, marked] });
      if (behaviour.fail) throw behaviour.fail;
    },
    saveDraft: async (_attempt, question, draft) => {
      calls.push({ kind: "draft", detail: [question, draft] });
      if (behaviour.fail) throw behaviour.fail;
      return { saved: true, server_time: "2026-11-01T10:00:00Z" };
    },
  };
  return { calls, transport, behaviour };
}

describe("Uploader", () => {
  let outbox: Outbox;
  let now: number;
  beforeEach(async () => {
    outbox = await Outbox.open(new IDBFactory());
    now = 1_000_000;
  });
  const make = (
    transport: Transport,
    extra: Partial<ConstructorParameters<typeof Uploader>[3]> = {},
  ) => new Uploader(outbox, transport, ATTEMPT, { now: () => now, random: () => 1, ...extra });

  it("sends answers in one batch first, then the rest oldest first, and empties the queue", async () => {
    const { calls, transport } = fakeTransport();
    await outbox.put(ATTEMPT, "flag", "q2", { marked: true }, 1);
    await outbox.put(ATTEMPT, "answer", "q1", { exam_question_id: "q1", text_answer: "a" }, 2);
    await outbox.put(
      ATTEMPT,
      "answer",
      "q3",
      { exam_question_id: "q3", selected_option_ids: ["o1"] },
      3,
    );
    await outbox.put(
      ATTEMPT,
      "draft",
      "q4:python312",
      { exam_question_id: "q4", language_key: "python312", source: "print(1)" },
      4,
    );
    const uploader = make(transport);
    expect((await uploader.flush()).state).toBe("saved");
    // Answers go first, as one batch; flags and drafts follow, oldest first.
    expect(calls.map((c) => c.kind)).toEqual(["answers", "flag", "draft"]);
    const batch = (calls[0]?.detail ?? []) as AnswerOut[];
    expect(batch.map((a) => [a.exam_question_id, a.client_revision])).toEqual([
      ["q1", 2],
      ["q3", 3],
    ]);
    expect(await outbox.pending(ATTEMPT)).toEqual([]);
  });

  it("goes offline, backs off, then catches up; after 60 s it says changes aren't saved", async () => {
    const { calls, transport, behaviour } = fakeTransport({ fail: new SendError("network") });
    await outbox.put(ATTEMPT, "answer", "q1", { exam_question_id: "q1", text_answer: "a" });
    const uploader = make(transport);

    expect(await uploader.flush()).toEqual({ state: "offline", unsent: 1, refused: 0 });
    expect(uploader.retryAt()).toBe(now + BASE_MS); // first retry after 1 s
    await uploader.flush(); // too early: waits for the backoff, sends nothing
    expect(calls).toHaveLength(1);

    now += FAILING_AFTER_MS;
    expect((await uploader.flush()).state).toBe("failing");

    behaviour.fail = null; // the network is back
    now += 60_000;
    expect(await uploader.flush()).toEqual({ state: "saved", unsent: 0, refused: 0 });
  });

  it("keeps changes made during an upload", async () => {
    let release: () => void = () => undefined;
    const { transport } = fakeTransport();
    const slow: Transport = {
      ...transport,
      saveAnswers: async (attempt, answers) => {
        await new Promise<void>((resolve) => (release = resolve));
        return transport.saveAnswers(attempt, answers);
      },
    };
    await outbox.put(ATTEMPT, "answer", "q1", { exam_question_id: "q1", text_answer: "old" });
    const uploader = make(slow);
    const flushing = uploader.flush();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await outbox.put(ATTEMPT, "answer", "q1", { exam_question_id: "q1", text_answer: "new" });
    release();
    const status = await flushing;
    expect(status).toEqual({ state: "saving", unsent: 1, refused: 0 });
    expect((await outbox.pending(ATTEMPT))[0]?.payload).toMatchObject({ text_answer: "new" });
  });

  it("time up: everything still queued is kept aside and counted honestly", async () => {
    const { transport } = fakeTransport({ fail: new SendError("closed", "TIME_UP") });
    await outbox.put(ATTEMPT, "answer", "q1", { exam_question_id: "q1" });
    await outbox.put(ATTEMPT, "flag", "q2", { marked: true });
    const status = await make(transport).flush();
    expect(status).toEqual({ state: "saved", unsent: 0, refused: 2 });
    expect((await outbox.rejected(ATTEMPT)).map((e) => e.rejected)).toEqual(["closed", "closed"]);
  });

  it("an invalid change is set aside; the rest still goes", async () => {
    const { calls, transport } = fakeTransport();
    const picky: Transport = {
      ...transport,
      setFlag: async () => {
        throw new SendError("invalid", "VALIDATION_FAILED");
      },
    };
    await outbox.put(ATTEMPT, "flag", "q2", { marked: true });
    await outbox.put(ATTEMPT, "answer", "q1", { exam_question_id: "q1" });
    const status = await make(picky).flush();
    expect(status).toEqual({ state: "saved", unsent: 0, refused: 1 });
    expect(calls.map((c) => c.kind)).toEqual(["answers"]);
  });

  it("passes response times to the clock", async () => {
    const seen: [number, number, string][] = [];
    const { transport } = fakeTransport();
    await outbox.put(ATTEMPT, "answer", "q1", { exam_question_id: "q1" });
    await make(transport, { onServerTime: (a, b, t) => seen.push([a, b, t]) }).flush();
    expect(seen).toEqual([[now, now, "2026-11-01T10:00:00Z"]]);
  });
});
