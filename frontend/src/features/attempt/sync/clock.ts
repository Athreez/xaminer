/**
 * Server time for the exam timer (PRD ATT-04, FRONTEND_SPEC § 2.3). The device clock may be wrong
 * or changed by the student; only the gap between device and server is trusted.
 *
 * Each response with `server_time` gives a sample. The server read its clock somewhere between
 * sending and receiving, so the best guess is the midpoint, and the sample with the shortest
 * round trip is the most accurate. Samples older than 10 minutes are dropped (clocks drift).
 */

export interface Sample {
  offsetMs: number; // server time minus device time
  roundTripMs: number;
  takenAt: number; // device time, for expiry
}

const MAX_AGE_MS = 10 * 60 * 1000;
const MAX_SAMPLES = 8;

export class ServerClock {
  private samples: Sample[] = [];
  private readonly now: () => number;

  constructor(now: () => number = Date.now) {
    this.now = now;
  }

  /** Record a response: device time when sent and received, and the server's time in it. */
  observe(sentAt: number, receivedAt: number, serverTime: string): void {
    const server = Date.parse(serverTime);
    if (Number.isNaN(server) || receivedAt < sentAt) return;
    const midpoint = sentAt + (receivedAt - sentAt) / 2;
    this.samples.push({
      offsetMs: server - midpoint,
      roundTripMs: receivedAt - sentAt,
      takenAt: receivedAt,
    });
    this.samples = this.fresh().slice(-MAX_SAMPLES);
  }

  /** Server time minus device time, from the most accurate recent sample (0 before any). */
  offsetMs(): number {
    const best = this.fresh().reduce<Sample | null>(
      (a, b) => (a === null || b.roundTripMs < a.roundTripMs ? b : a),
      null,
    );
    return best?.offsetMs ?? 0;
  }

  /** The server's current time. */
  serverNow(): number {
    return this.now() + this.offsetMs();
  }

  /** Whole seconds until `deadline` by the server's clock, never below zero. */
  secondsLeft(deadline: string): number {
    return Math.max(0, Math.floor((Date.parse(deadline) - this.serverNow()) / 1000));
  }

  private fresh(): Sample[] {
    const now = this.now();
    return this.samples.filter((s) => now - s.takenAt <= MAX_AGE_MS);
  }
}
