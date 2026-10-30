import { describe, expect, it } from "vitest";

import { eulerFromMatrix, governedRate, LatencyTracker, median } from "./geometry";

/** A head turned `yaw` degrees and tilted `pitch`, 50 cm from the camera, as MediaPipe gives it
 *  (column-major, flat). */
function matrix(yaw: number, pitch: number, scale = 1): number[] {
  const [y, p] = [(yaw * Math.PI) / 180, (pitch * Math.PI) / 180];
  const ry = [
    [Math.cos(y), 0, Math.sin(y)],
    [0, 1, 0],
    [-Math.sin(y), 0, Math.cos(y)],
  ];
  const rx = [
    [1, 0, 0],
    [0, Math.cos(p), -Math.sin(p)],
    [0, Math.sin(p), Math.cos(p)],
  ];
  const r = ry.map((row) => [0, 1, 2].map((j) => row.reduce((s, v, k) => s + v * rx[k]![j]!, 0)));
  const m = [...r.map((row) => [...row.map((v) => v * scale), 0]), [0, 0, 0, 1]];
  m[2]![3] = -50;
  const flat: number[] = [];
  for (let c = 0; c < 4; c++) for (let row = 0; row < 4; row++) flat.push(m[row]![c]!);
  return flat;
}

describe("head pose from the face matrix", () => {
  it("reads a straight head as zero", () => {
    const { yaw, pitch, roll } = eulerFromMatrix(matrix(0, 0));
    for (const angle of [yaw, pitch, roll]) expect(angle).toBeCloseTo(0, 5);
  });

  it("reads a turn and a tilt, whatever the face's scale", () => {
    const pose = eulerFromMatrix(matrix(30, -15, 1.7));
    expect(pose.yaw).toBeCloseTo(30, 5);
    expect(pose.pitch).toBeCloseTo(-15, 5);
  });

  it("reads the same pose from a row-major matrix", () => {
    const col = matrix(-40, 10);
    const row = [0, 1, 2, 3].flatMap((r) => [0, 1, 2, 3].map((c) => col[c * 4 + r]!));
    expect(eulerFromMatrix(row).yaw).toBeCloseTo(-40, 5);
  });
});

describe("how often a check may run", () => {
  it("is capped by the target, else by the share of a core it may use", () => {
    expect(governedRate(8, 0.2, 20)).toBe(8); // 20 ms: 10 a second fit, 8 wanted
    expect(governedRate(8, 0.2, 100)).toBeCloseTo(2); // 100 ms: 2 a second fit in 20 %
    expect(governedRate(8, 0.2, 0)).toBe(8);
  });

  it("measures the median call time, leaving out the warm-up", () => {
    const t = new LatencyTracker(3);
    [900, 10, 30, 20].forEach((ms) => t.add(ms));
    expect(t.ms).toBe(20);
    t.add(40);
    t.add(50); // only the last 3 are kept
    expect(t.ms).toBe(40);
    expect(median([])).toBeNull();
  });
});
