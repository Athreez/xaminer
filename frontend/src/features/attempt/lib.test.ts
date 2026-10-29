import { describe, expect, it } from "vitest";

import {
  canOpen,
  connection,
  formatClock,
  isAnswered,
  navLabel,
  plainText,
  navState,
  restore,
  timeAnnouncement,
  timerLevel,
  type AttemptItem,
} from "./lib";
import type { Entry } from "./sync/outbox";

function item(id: string, extra: Partial<AttemptItem> = {}): AttemptItem {
  return {
    exam_question_id: id,
    position: 1,
    marked_for_review: false,
    answer: null,
    question: {
      id: `v-${id}`,
      type: "MCQ",
      body: "?",
      points: "1",
      negative_marks: "0",
      multiple_answers: false,
      msq_scoring: null,
      max_answer_length: null,
      options: [],
    },
    ...extra,
  };
}

function entry(kind: Entry["kind"], target: string, payload: Record<string, unknown>): Entry {
  return {
    key: `${kind}:a:${target}`,
    attemptId: "a",
    kind,
    target,
    payload,
    revision: 9,
    priority: 0,
    queuedAt: 0,
  };
}

describe("restore", () => {
  it("takes the server's answers, then lays what's still on the device on top", () => {
    const items = [
      item("q1", {
        answer: { selected_option_ids: ["o1"], text_answer: null, client_revision: 4 },
      }),
      item("q2", {
        marked_for_review: true,
        answer: { selected_option_ids: null, text_answer: "old", client_revision: 7 },
      }),
      item("q3"),
    ];
    const pending = [
      entry("answer", "q2", {
        exam_question_id: "q2",
        selected_option_ids: null,
        text_answer: "newer",
      }),
      entry("flag", "q2", { marked: false }),
      entry("flag", "q3", { marked: true }),
    ];
    const restored = restore(items, pending);
    expect(restored.answers).toEqual({
      q1: { selected_option_ids: ["o1"], text_answer: null },
      q2: { selected_option_ids: null, text_answer: "newer" },
    });
    expect(restored.flags).toEqual({ q1: false, q2: false, q3: true });
    expect(restored.revision).toBe(7); // new changes start above what the server has
  });
});

describe("navigator", () => {
  it("gives every state its own name", () => {
    expect(navState(false, false, false)).toBe("not-visited");
    expect(navState(false, false, true)).toBe("not-answered");
    expect(navState(true, false, true)).toBe("answered");
    expect(navState(false, true, true)).toBe("marked");
    expect(navState(true, true, true)).toBe("answered-marked");
    expect(navLabel(7, "answered-marked")).toBe("Question 7, answered, marked for review");
    expect(navLabel(2, "answered", true)).toBe("Question 2, answered, can't go back");
  });

  it("counts blank text and empty choices as not answered", () => {
    expect(isAnswered(null)).toBe(false);
    expect(isAnswered({ selected_option_ids: [], text_answer: null })).toBe(false);
    expect(isAnswered({ selected_option_ids: null, text_answer: "   " })).toBe(false);
    expect(isAnswered({ selected_option_ids: ["o1"], text_answer: null })).toBe(true);
  });

  it("closes earlier questions only in sequential exams", () => {
    expect(canOpen(false, 0, 5)).toBe(true);
    expect(canOpen(true, 4, 5)).toBe(false);
    expect(canOpen(true, 5, 5)).toBe(true);
    expect(canOpen(true, 8, 5)).toBe(true);
  });
});

describe("timer", () => {
  it("shows hours only when there are some", () => {
    expect(formatClock(5077)).toBe("1:24:37");
    expect(formatClock(545)).toBe("09:05");
    expect(formatClock(-3)).toBe("00:00");
  });

  it("turns to warning at 10 minutes and danger at 2", () => {
    expect(timerLevel(601)).toBe("normal");
    expect(timerLevel(600)).toBe("warning");
    expect(timerLevel(121)).toBe("warning");
    expect(timerLevel(120)).toBe("danger");
  });

  it("speaks at 30, 15, 10, 5, 2 and 1 minutes, once each", () => {
    expect(timeAnnouncement(1801, 1800)).toBe("30 minutes left");
    expect(timeAnnouncement(1800, 1799)).toBeNull();
    expect(timeAnnouncement(61, 60)).toBe("1 minute left");
    // A jump (e.g. the laptop slept) says only the latest point passed.
    expect(timeAnnouncement(1000, 200)).toBe("5 minutes left");
    expect(timeAnnouncement(3000, 2999)).toBeNull();
  });
});

describe("connection", () => {
  it("is reconnecting for 30 s of failures, then offline", () => {
    expect(connection(true, null, 1000)).toBe("online");
    expect(connection(true, 0, 29_999)).toBe("reconnecting");
    expect(connection(true, 0, 30_000)).toBe("offline");
    expect(connection(false, null, 0)).toBe("offline");
  });
});

describe("plainText", () => {
  it("drops Markdown marks, keeps words, and shortens", () => {
    expect(plainText("Index of the **first** element?")).toBe("Index of the first element?");
    expect(plainText("See [docs](http://x) and ![a](q.png)\n```py\nx=1\n```")).toBe(
      "See docs and [image] [code]",
    );
    expect(plainText("a".repeat(100), 10)).toBe("aaaaaaaaa…");
  });
});
