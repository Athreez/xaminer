import { describe, expect, it } from "vitest";

import { copiedInside, normalise } from "./browserChecks";

describe("the paste rule", () => {
  const copies = [normalise("for i in range(n):\r\n    print(i)\n")];

  it("lets back in what was copied inside the exam, however line endings came out", () => {
    expect(copiedInside("for i in range(n):\n    print(i)", copies)).toBe(true);
    expect(copiedInside("  for i in range(n):\r\n    print(i)  ", copies)).toBe(true);
  });

  it("blocks anything else", () => {
    expect(copiedInside("def two_sum(nums, target):", copies)).toBe(false);
    expect(copiedInside("for i in range(n):", copies)).toBe(false); // part of it isn't the same
  });

  it("an empty paste is harmless", () => {
    expect(copiedInside("", [])).toBe(true);
  });
});
