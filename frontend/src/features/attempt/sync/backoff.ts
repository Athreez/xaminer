/**
 * Retry delays after a failed request (architecture § 9.6): 1 s doubling to 30 s, with "full
 * jitter" so a whole exam hall coming back online doesn't retry in step.
 */
export const BASE_MS = 1_000;
export const MAX_MS = 30_000;

export function backoffMs(failures: number, random: () => number = Math.random): number {
  if (failures <= 0) return 0;
  const ceiling = Math.min(MAX_MS, BASE_MS * 2 ** (failures - 1));
  // Never less than half the ceiling: retrying instantly after a failure helps nobody.
  return Math.round(ceiling / 2 + random() * (ceiling / 2));
}
