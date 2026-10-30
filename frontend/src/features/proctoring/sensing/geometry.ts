// Pure helpers of the proctoring sensors, ported from CALIPER's SDK (caliper/frontend/src/sdk:
// geometry.ts, timing.ts) with the same formulas, so its head-pose benchmark (MAE 3.2° on
// AFLW2000) holds here. No browser APIs, so they're unit-tested.

/** 4x4 row-major matrix from MediaPipe's flat `data`, detecting the layout: a rigid transform has
 *  a non-zero translation, and where it sits tells row-major from column-major. */
export function toRowMajor(data: ArrayLike<number>): number[][] {
  const at = (i: number) => data[i] ?? 0;
  const colMajor =
    Math.abs(at(12)) + Math.abs(at(13)) + Math.abs(at(14)) >
    Math.abs(at(3)) + Math.abs(at(7)) + Math.abs(at(11));
  return [0, 1, 2, 3].map((r) =>
    [0, 1, 2, 3].map((c) => (colMajor ? at(c * 4 + r) : at(r * 4 + c))),
  );
}

/** Head (yaw, pitch, roll) in degrees from the face's transformation matrix: Y-X-Z
 *  decomposition of the rotation part, scale removed per column. */
export function eulerFromMatrix(data: ArrayLike<number>): {
  yaw: number;
  pitch: number;
  roll: number;
} {
  const m = toRowMajor(data);
  const norms = [0, 1, 2].map((j) => Math.hypot(m[0]![j]!, m[1]![j]!, m[2]![j]!) || 1);
  const r = (i: number, j: number) => m[i]![j]! / norms[j]!;
  const deg = 180 / Math.PI;
  return {
    yaw: Math.atan2(r(0, 2), r(2, 2)) * deg,
    pitch: Math.asin(Math.max(-1, Math.min(1, -r(1, 2)))) * deg,
    roll: Math.atan2(r(1, 0), r(1, 1)) * deg,
  };
}

export function median(xs: readonly number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

/** Analyses per second the device can afford: min(target, budget / latency), budget being the
 *  share of one CPU core the sensor may use (PRD NFR-07: 30 % for all of proctoring). */
export function governedRate(targetHz: number, budget: number, latencyMs: number): number {
  if (latencyMs <= 0) return targetHz;
  return Math.min(targetHz, budget / (latencyMs / 1000));
}

/** Median of recent call times, leaving out the first (warm-up: shaders, graph set-up). */
export class LatencyTracker {
  private xs: number[] = [];
  private calls = 0;
  private readonly window: number;
  constructor(window = 15) {
    this.window = window;
  }
  add(ms: number): void {
    if (this.calls++ === 0) return;
    this.xs.push(ms);
    if (this.xs.length > this.window) this.xs.shift();
  }
  get ms(): number | null {
    return median(this.xs);
  }
  get count(): number {
    return this.xs.length;
  }
}
