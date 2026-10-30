import { describe, expect, it } from "vitest";

import { markProblem, score } from "./lib";

describe("markProblem", () => {
  it("accepts 0 to points with up to 2 decimals", () => {
    expect(markProblem("0", "5.00")).toBeNull();
    expect(markProblem("4.5", "5.00")).toBeNull();
    expect(markProblem("5", "5.00")).toBeNull();
  });
  it("explains what's wrong", () => {
    expect(markProblem("", "5")).toBe("Enter a mark.");
    expect(markProblem("5.5", "5.00")).toBe("The most this question gives is 5.");
    expect(markProblem("2.555", "5")).toMatch(/2 decimals/);
    expect(markProblem("-1", "5")).toMatch(/number/);
  });
});

describe("score", () => {
  it("drops trailing zeros", () => {
    expect(score("7.50")).toBe("7.5");
    expect(score("10.00")).toBe("10");
    expect(score(null)).toBe("—");
  });
});
