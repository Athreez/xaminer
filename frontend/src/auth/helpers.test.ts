import { describe, expect, it } from "vitest";

import { homeFor, lockedUntilText, safeNextPath, tokenFromHash } from "./helpers";

describe("safeNextPath (open-redirect protection)", () => {
  it.each([
    ["/teacher/exams", "/teacher/exams"],
    ["/student?tab=results", "/student?tab=results"],
    ["/admin/users#top", "/admin/users#top"],
  ])("accepts a path on this site: %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([
    null,
    "",
    "https://evil.example/phish",
    "//evil.example/phish",
    "/\\evil.example",
    "\\\\evil.example",
    "javascript:alert(1)",
    "/\t/evil.example",
    "/\n/evil.example",
    "evil.example",
    "/login",
    "/login?next=/admin",
  ])("refuses %j", (input) => {
    expect(safeNextPath(input)).toBeNull();
  });
});

describe("homeFor", () => {
  it("sends each role to its home", () => {
    expect(homeFor("ADMIN")).toBe("/admin/users");
    expect(homeFor("TEACHER")).toBe("/teacher");
    expect(homeFor("STUDENT")).toBe("/student");
  });

  it("an unknown role gets the forbidden page, not someone else's home", () => {
    expect(homeFor("SUPERUSER")).toBe("/403");
  });
});

describe("tokenFromHash", () => {
  it("reads the token after #", () => {
    expect(tokenFromHash("#token=abc123DEF_-xyz")).toBe("abc123DEF_-xyz");
  });

  it.each(["", "#", "#token=", "#token=short", "#other=abcdefghijkl"])("no token in %j", (hash) => {
    expect(tokenFromHash(hash)).toBeNull();
  });
});

describe("lockedUntilText", () => {
  it("shows a time", () => {
    expect(lockedUntilText("2026-10-27T14:32:00Z")).toMatch(/^Try again after \d{1,2}:\d{2}/);
  });

  it("falls back when missing or broken", () => {
    expect(lockedUntilText(undefined)).toBe("Try again later.");
    expect(lockedUntilText("not-a-date")).toBe("Try again later.");
  });
});
