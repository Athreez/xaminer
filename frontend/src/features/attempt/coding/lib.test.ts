import { describe, expect, it } from "vitest";

import { diffLines, elapsed, visible } from "./lib";

describe("visible", () => {
  it("shows spaces, tabs and line endings", () => {
    expect(visible("a b\tc\r\n")).toBe("a·b→c␍↵\n");
    expect(visible("")).toBe("");
  });
});

describe("diffLines", () => {
  it("pairs lines and marks the different ones", () => {
    expect(diffLines("1\n2\n3\n", "1\n5\n3\n")).toEqual([
      { expected: "1", actual: "1", same: true },
      { expected: "2", actual: "5", same: false },
      { expected: "3", actual: "3", same: true },
    ]);
  });

  it("shows missing and extra lines", () => {
    expect(diffLines("1\n2", "1")).toEqual([
      { expected: "1", actual: "1", same: true },
      { expected: "2", actual: null, same: false },
    ]);
    expect(diffLines("1", "1\n2")[1]).toEqual({ expected: null, actual: "2", same: false });
  });

  it("ignores the empty line a final newline makes", () => {
    expect(diffLines("3\n", "3")).toEqual([{ expected: "3", actual: "3", same: true }]);
  });
});

describe("elapsed", () => {
  it("counts seconds, then minutes", () => {
    expect(elapsed(0, 4_200)).toBe("4 s");
    expect(elapsed(0, 65_000)).toBe("1 min 5 s");
  });
});
