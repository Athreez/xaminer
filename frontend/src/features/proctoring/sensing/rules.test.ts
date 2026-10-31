import { describe, expect, it } from "vitest";

import { COOLDOWN_MS, Rules, SETTLE_MS, type RuleEvent, type RulesConfig } from "./rules";

const FACE = { area: 0.1, yaw: 0, pitch: 0 };
const SMALL = { area: 0.01, yaw: 0, pitch: 0 }; // a face far behind: under 20 % of the main one
const START = 1_000_000;

/** Feed frames at 3 per second from `from` to `to` seconds after the start. */
function run(rules: Rules, from: number, to: number, faces: (typeof FACE)[]) {
  for (let t = from * 1000; t < to * 1000; t += 333) rules.frame(START + t, faces);
}

function setup(config: Partial<RulesConfig> = {}) {
  const events: RuleEvent[] = [];
  const rules = new Rules(
    { sensitivity: "STANDARD", gaze: false, voice: false, startedAt: START, ...config },
    (e) => events.push(e),
  );
  return { rules, events };
}

describe("proctoring rules", () => {
  it("raises no face only after settling and after 5 s, with its whole length", () => {
    const { rules, events } = setup();
    run(rules, 0, 30, []); // settling: nothing
    run(rules, 30, 70, [FACE]);
    run(rules, 70, 74, []); // 4 s: too short
    run(rules, 74, 90, [FACE]);
    run(rules, 90, 110, []); // 20 s
    run(rules, 110, 140, [FACE]);
    expect(events).toHaveLength(1);
    const [e] = events;
    expect(e!.kind).toBe("FACE_ABSENT");
    expect(e!.at - START).toBe(90_000);
    expect(e!.durationMs).toBeGreaterThan(19_000);
    expect(e!.durationMs).toBeLessThanOrEqual(20_000);
  });

  it("raises a second face at once (no settling), ignores small ones, keeps the most faces", () => {
    const { rules, events } = setup();
    run(rules, 0, 10, [FACE, SMALL]);
    run(rules, 10, 13, [FACE, FACE]);
    run(rules, 13, 14, [FACE, FACE, FACE]);
    expect(rules.seen()).toEqual([{ id: expect.any(String), kind: "MULTIPLE_FACES" }]);
    expect(rules.ongoing(START + 14_000)).toEqual([{ kind: "MULTIPLE_FACES", seconds: 4 }]);
    run(rules, 14, 40, [FACE]);
    expect(rules.seen()).toEqual([]);
    expect(events).toEqual([
      expect.objectContaining({
        kind: "MULTIPLE_FACES",
        at: START + 10_000,
        details: { faces: 3 },
      }),
    ]);
  });

  it("merges a return within 10 s and waits out the cooldown after", () => {
    const { rules, events } = setup();
    run(rules, 0, 3, [FACE, FACE]);
    run(rules, 3, 8, [FACE]); // 5 s gap: the same event
    run(rules, 8, 10, [FACE, FACE]);
    run(rules, 10, 25, [FACE]); // ended
    expect(events).toHaveLength(1);
    expect(events[0]!.durationMs).toBeGreaterThan(9_000);
    run(rules, 25, 40, [FACE, FACE]); // within the cooldown: nothing
    run(rules, 40, 75, [FACE]);
    expect(events).toHaveLength(1);
    run(rules, 75, 80, [FACE, FACE]);
    rules.flush(); // the exam ends while it's open
    expect(events).toHaveLength(2);
    expect(events[1]!.at - START).toBeGreaterThan(10_000 + COOLDOWN_MS);
  });

  it("scales times with the sensitivity", () => {
    const strict = setup({ sensitivity: "STRICT" }); // no face 3 s is enough
    run(strict.rules, 0, 61, [FACE]);
    run(strict.rules, 61, 65, []);
    strict.rules.flush();
    expect(strict.events.map((e) => e.kind)).toEqual(["FACE_ABSENT"]);
    const relaxed = setup({ sensitivity: "RELAXED" }); // 7.5 s needed
    run(relaxed.rules, 0, 61, [FACE]);
    run(relaxed.rules, 61, 67, []);
    relaxed.rules.flush();
    expect(relaxed.events).toEqual([]);
  });

  it("forgets what it can't know: frames far apart restart the count", () => {
    const { rules, events } = setup();
    run(rules, 0, 61, [FACE]);
    rules.frame(START + 62_000, []);
    rules.frame(START + 69_000, []); // 7 s without frames (the page was hidden)
    rules.frame(START + 70_000, [FACE]);
    rules.flush();
    expect(events).toEqual([]);
  });

  it("measures the head turn from the student's resting pose, and ignores looking down", () => {
    const { rules, events } = setup({ gaze: true });
    const resting = { area: 0.1, yaw: 10, pitch: 12 }; // camera below and beside the screen
    run(rules, 0, 60, [resting]);
    run(rules, 60, 80, [{ ...resting, yaw: 40 }]); // 30° from rest: fine
    run(rules, 80, 100, [{ ...resting, pitch: 50 }]); // looking down: fine
    expect(events).toEqual([]);
    run(rules, 100, 110, [{ ...resting, yaw: -30 }]); // 40° the other way
    run(rules, 110, 130, [resting]);
    run(rules, 200, 212, [{ ...resting, pitch: -15 }]); // 27° up
    rules.flush();
    expect(events.map((e) => [e.kind, e.details])).toEqual([
      ["GAZE_AWAY", { direction: "sideways" }],
      ["GAZE_AWAY", { direction: "up" }],
    ]);
  });

  it("raises talking when half of 10 s is speech, from the start of that window", () => {
    const { rules, events } = setup({ voice: true });
    for (let t = 0; t < 20_000; t += 250) rules.sound(START + t, t % 1000 < 250); // 25 %
    expect(events).toEqual([]);
    for (let t = 20_000; t < 45_000; t += 250) rules.sound(START + t, t % 1000 < 750); // 75 %
    for (let t = 45_000; t < 70_000; t += 250) rules.sound(START + t, false);
    expect(events).toHaveLength(1);
    expect(events[0]!.kind).toBe("VOICE_DETECTED");
    expect(events[0]!.durationMs).toBeGreaterThan(20_000);
    expect(SETTLE_MS).toBe(60_000);
  });
});
