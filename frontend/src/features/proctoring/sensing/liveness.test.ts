import { describe, expect, it } from "vitest";

import { Challenge, CHALLENGE_MS, firstChallenge, nextChallenge } from "./liveness";

/** Frames at 10 a second for `ms`, from `from`. */
function run(
  c: Challenge,
  from: number,
  ms: number,
  pose: (t: number) => { yaw: number; blink: number } | null,
) {
  let state = c.state;
  for (let t = from; t < from + ms; t += 100) state = c.frame(t, pose(t));
  return state;
}

describe("liveness challenges", () => {
  it("passes a head turn either way, and fails a face that doesn't move", () => {
    const turn = new Challenge("TURN", 0);
    expect(run(turn, 0, 3000, (t) => ({ yaw: t > 1500 ? -15 + 10 : 10, blink: 0 }))).toBe(
      "waiting",
    );
    expect(run(turn, 3000, 1000, () => ({ yaw: 35, blink: 0 }))).toBe("passed");
    const photo = new Challenge("TURN", 0);
    expect(run(photo, 0, CHALLENGE_MS + 100, () => ({ yaw: 5, blink: 0 }))).toBe("failed");
  });

  it("counts two blinks, open-closed-open", () => {
    const blink = new Challenge("BLINK", 0);
    const twice = (t: number) => ({ yaw: 0, blink: t % 2000 < 200 ? 0.8 : 0.05 });
    expect(run(blink, 0, 1000, twice)).toBe("waiting"); // one
    expect(run(blink, 1000, 2500, twice)).toBe("passed");
    const still = new Challenge("BLINK", 0);
    expect(run(still, 0, CHALLENGE_MS + 100, () => ({ yaw: 0, blink: 0.1 }))).toBe("failed");
  });

  it("doesn't count when there's mostly no face (that's another event)", () => {
    const c = new Challenge("TURN", 0);
    expect(run(c, 0, CHALLENGE_MS + 100, (t) => (t < 2000 ? { yaw: 0, blink: 0 } : null))).toBe(
      "skipped",
    );
  });

  it("comes 3-8 minutes in, then every 12-20 minutes", () => {
    expect(firstChallenge(0, () => 0)).toBe(3 * 60_000);
    expect(firstChallenge(0, () => 1)).toBe(8 * 60_000);
    expect(nextChallenge(0, () => 0.5)).toBe(16 * 60_000);
  });
});
