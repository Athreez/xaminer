import { describe, expect, it } from "vitest";

import { countdown, deviceNeeds, durationText } from "./lib";

describe("countdown", () => {
  it("is coarse far away and exact close by", () => {
    expect(countdown(3 * 86_400_000)).toBe("in 3 days");
    expect(countdown(86_400_000 + 2 * 3_600_000)).toBe("in 1 day 2 h");
    expect(countdown(3_900_000)).toBe("in 1 h 5 min");
    expect(countdown(7_200_000)).toBe("in 2 h");
    expect(countdown(250_000)).toBe("in 4 min 10 s");
    expect(countdown(9_400)).toBe("in 10 s");
    expect(countdown(-5)).toBe("in 0 s");
  });
});

describe("durationText", () => {
  it("reads naturally", () => {
    expect(durationText(90)).toBe("1 hour 30 minutes");
    expect(durationText(60)).toBe("1 hour");
    expect(durationText(45)).toBe("45 minutes");
    expect(durationText(1)).toBe("1 minute");
  });
});

describe("deviceNeeds", () => {
  it("asks for a camera only when proctored, and a bigger screen for code", () => {
    expect(deviceNeeds({ proctoring_mode: "OFF", has_coding: false })[0]).toContain("1024 × 768");
    expect(deviceNeeds({ proctoring_mode: "OFF", has_coding: true })[0]).toContain("1280 × 720");
    const proctored = deviceNeeds({ proctoring_mode: "VIDEO_AUDIO", has_coding: false });
    expect(proctored[0]).toContain("camera and microphone");
    expect(proctored).toHaveLength(3);
  });
});
