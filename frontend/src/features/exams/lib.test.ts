import { describe, expect, it } from "vitest";

import { fixLink, fromLocalInput, toLocalInput, windowState } from "./lib";

describe("windowState", () => {
  const exam = { open_at: "2026-11-01T09:00:00Z", close_at: "2026-11-01T12:00:00Z" };
  it("follows the clock", () => {
    expect(windowState({ open_at: null, close_at: null })).toBe("NOT_SCHEDULED");
    expect(windowState(exam, new Date("2026-11-01T08:59:00Z"))).toBe("UPCOMING");
    expect(windowState(exam, new Date("2026-11-01T10:00:00Z"))).toBe("OPEN");
    expect(windowState(exam, new Date("2026-11-01T12:00:00Z"))).toBe("CLOSED");
  });
});

describe("local datetime inputs", () => {
  it("round-trip an instant", () => {
    const iso = "2026-11-01T09:30:00.000Z";
    expect(fromLocalInput(toLocalInput(iso))).toBe(iso);
    expect(toLocalInput(null)).toBe("");
    expect(fromLocalInput("")).toBeNull();
  });
});

describe("fixLink", () => {
  const base = "/teacher/exams/e1";
  const issue = (field: string | null, question_id: string | null = null) => ({
    code: "X",
    message: "x",
    field,
    question_id,
  });
  it("sends each issue to the page that fixes it", () => {
    expect(fixLink(base, issue("duration_min"))).toBe(`${base}/settings#duration_min`);
    expect(fixLink(base, issue(null, "q1"))).toBe(`${base}/questions`);
    expect(fixLink(base, issue("questions"))).toBe(`${base}/questions`);
    expect(fixLink(base, issue("assignments"))).toBe(`${base}/students`);
  });
});
