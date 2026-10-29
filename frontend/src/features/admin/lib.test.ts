import { describe, expect, it } from "vitest";

import { actionText, dayStart } from "./lib";

describe("dayStart", () => {
  it("is local midnight, and the next day for an end bound", () => {
    expect(new Date(dayStart("2026-03-10")).getHours()).toBe(0);
    expect(new Date(dayStart("2026-03-10")).getDate()).toBe(10);
    expect(new Date(dayStart("2026-03-31", 1)).getDate()).toBe(1); // rolls into April
  });
});

describe("actionText", () => {
  it("reads like a sentence", () => {
    expect(actionText("user.password_reset_sent")).toBe("User · password reset sent");
    expect(actionText("auth.login_failed")).toBe("Auth · login failed");
    expect(actionText("odd")).toBe("Odd");
  });
});
