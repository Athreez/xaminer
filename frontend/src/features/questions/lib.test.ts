import { describe, expect, it } from "vitest";

import { fieldErrors, insertAt, parseTags } from "./lib";

describe("fieldErrors", () => {
  it("keys request and rule errors by form field", () => {
    const error = {
      error: {
        code: "VALIDATION_FAILED",
        message: "x",
        details: [
          { field: "body.points", message: "must be greater than 0" },
          { field: "options", message: "Mark exactly one option as correct." },
          { field: "options.1.label", message: "Option 2 is the same as option 1." },
          { field: "options", message: "second message for the same field is ignored" },
        ],
      },
    };
    expect(fieldErrors(error)).toEqual({
      points: "must be greater than 0",
      options: "Mark exactly one option as correct.",
      "options.1.label": "Option 2 is the same as option 1.",
    });
    expect(fieldErrors(new Error("offline"))).toEqual({});
  });
});

describe("parseTags", () => {
  it("trims, lower-cases and drops repeats and blanks", () => {
    expect(parseTags(" Arrays, easy ,arrays,, ")).toEqual(["arrays", "easy"]);
  });
});

describe("insertAt", () => {
  it("puts the snippet on its own line at the cursor", () => {
    expect(insertAt("ab", 1, 1, "X")).toBe("a\nX\nb");
    expect(insertAt("", 0, 0, "X")).toBe("X");
    expect(insertAt("line\n", 5, 5, "X")).toBe("line\nX");
    expect(insertAt("replace me", 0, 10, "X")).toBe("X");
  });
});
