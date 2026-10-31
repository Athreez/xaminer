// Liveness challenges (CALIPER's turn and blink challenges): a few times per exam the student is
// asked to turn their head or blink twice, and the face model checks it was done. A photo or a
// looped video held up to the camera can't answer. Pure (time and faces passed in) for tests.

export type ChallengeKind = "TURN" | "BLINK";
export type ChallengeState = "waiting" | "passed" | "failed" | "skipped";

export const CHALLENGE_MS = 10_000;
const TURN_DEG = 20; // either way: which sign is "left" depends on the camera
const BLINK_CLOSED = 0.5;
const BLINK_OPEN = 0.3;
const BLINKS = 2;
/** Without a face for most of the challenge it doesn't count: FACE_ABSENT covers that. */
const SEEN_SHARE = 0.5;

export const PROMPT: Record<ChallengeKind, string> = {
  TURN: "Turn your head to one side, then back",
  BLINK: "Blink twice",
};

export type SeenPose = { yaw: number | null; blink: number | null };

/** When the first challenge comes (3-8 min in) and the gap to the next (12-20 min). */
export function firstChallenge(start: number, random = Math.random): number {
  return start + (3 + random() * 5) * 60_000;
}

export function nextChallenge(now: number, random = Math.random): number {
  return now + (12 + random() * 8) * 60_000;
}

export function pickChallenge(random = Math.random): ChallengeKind {
  return random() < 0.5 ? "TURN" : "BLINK";
}

export class Challenge {
  readonly kind: ChallengeKind;
  readonly startedAt: number;
  private frames = 0;
  private withFace = 0;
  private restYaw: number | null = null;
  private closed = false;
  private blinks = 0;
  state: ChallengeState = "waiting";

  constructor(kind: ChallengeKind, startedAt: number) {
    this.kind = kind;
    this.startedAt = startedAt;
  }

  /** One analysed frame: the main face's pose, or null when there's no face. */
  frame(t: number, face: SeenPose | null): ChallengeState {
    if (this.state !== "waiting") return this.state;
    this.frames += 1;
    if (face) {
      this.withFace += 1;
      if (this.kind === "TURN" && face.yaw !== null) {
        this.restYaw ??= face.yaw;
        if (Math.abs(face.yaw - this.restYaw) > TURN_DEG) this.state = "passed";
      }
      if (this.kind === "BLINK" && face.blink !== null) {
        if (!this.closed && face.blink > BLINK_CLOSED) this.closed = true;
        else if (this.closed && face.blink < BLINK_OPEN) {
          this.closed = false;
          this.blinks += 1;
          if (this.blinks >= BLINKS) this.state = "passed";
        }
      }
    }
    if (this.state === "waiting" && t - this.startedAt >= CHALLENGE_MS) {
      this.state = this.withFace >= this.frames * SEEN_SHARE ? "failed" : "skipped";
    }
    return this.state;
  }
}
