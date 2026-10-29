import { describe, expect, it } from "vitest";

import { errorText, unwrap } from "./api";

const apiError = (code: string, message: string, details?: Record<string, unknown>[]) => ({
  error: { code, message, details },
});

describe("errorText", () => {
  it("shows the server's message", () => {
    expect(errorText(apiError("EMAIL_TAKEN", "a@b.edu already has an account here."))).toBe(
      "a@b.edu already has an account here.",
    );
  });

  it("names the field for validation errors", () => {
    const error = apiError("VALIDATION_FAILED", "The request is not valid.", [
      { field: "body.full_name", message: "String should have at least 1 character" },
    ]);
    expect(errorText(error)).toBe("full name: String should have at least 1 character");
  });

  it("hides internal errors and handles no response", () => {
    expect(errorText(apiError("INTERNAL_ERROR", "boom"))).toBe(
      "Something went wrong. Try again in a moment.",
    );
    expect(errorText(new TypeError("Failed to fetch"))).toMatch(/Can't reach the server/);
  });
});

describe("unwrap", () => {
  it("returns data, accepts empty 204s and throws API errors", () => {
    expect(unwrap({ data: 5, response: new Response(null, { status: 200 }) })).toBe(5);
    expect(unwrap({ response: new Response(null, { status: 204 }) })).toBeUndefined();
    const error = apiError("NOT_FOUND", "Not found");
    expect(() => unwrap({ error, response: new Response(null, { status: 404 }) })).toThrow();
  });
});
