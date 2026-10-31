// The proctoring rules (PRD § 6.5): what the camera and microphone saw, over time, turned into
// events for the teacher. Pure (time is passed in), so it's unit-tested on recorded timelines.
// The server sets each event's severity from its kind and length; nothing here decides that.
import { median } from "./geometry";

export type Sensitivity = "RELAXED" | "STANDARD" | "STRICT";
export type RuleKind = "FACE_ABSENT" | "MULTIPLE_FACES" | "GAZE_AWAY" | "VOICE_DETECTED";

export type RuleEvent = {
  /** Given when the event opens, so pictures taken meanwhile can name it. */
  id: string;
  kind: RuleKind;
  /** When it started (ms since epoch). */
  at: number;
  durationMs: number;
  details?: Record<string, string | number>;
};

export type SeenFace = { area: number; yaw: number | null; pitch: number | null };

export type RulesConfig = {
  sensitivity: Sensitivity;
  gaze: boolean;
  voice: boolean;
  /** When watching began on this page (settling counts from here). */
  startedAt: number;
};

/** Every time threshold is multiplied by this (PRD § 6.5 presets). */
export const SCALE: Record<Sensitivity, number> = { RELAXED: 1.5, STANDARD: 1, STRICT: 0.6 };

export const SETTLE_MS = 60_000; // no camera events at first (except a second face)
export const MERGE_MS = 10_000; // the same kind again this soon extends the event
export const COOLDOWN_MS = 60_000; // after an event ends, the same kind waits this long
const GAP_MS = 5_000; // frames this far apart: what happened between is unknown

const FACE_ABSENT_MS = 5_000;
const MULTIPLE_FACES_MS = 2_000;
const SECOND_FACE = 0.2; // of the main face's size
const GAZE_MS = 8_000;
const YAW_DEG = 35;
const UP_DEG = 25;
/** Head-pose resting point allowed (the camera may sit below or beside the screen). */
const BASELINE_MAX_DEG = 15;
const VOICE_WINDOW_MS = 10_000;
const VOICE_SHARE = 0.5;

/** One kind of event: the condition must hold `holdMs` to raise it; it then stays open until
 *  the condition has been gone for MERGE_MS, and ends when the condition was last seen. */
class Detector {
  private since: number | null = null;
  private open: {
    id: string;
    at: number;
    last: number;
    on: boolean;
    details?: Record<string, string | number>;
  } | null = null;
  private coolUntil = 0;
  private readonly kind: RuleKind;
  private readonly holdMs: number;
  private readonly leadMs: number;
  private readonly emit: (e: RuleEvent) => void;

  /** `leadMs`: the event started this long before the condition held (the voice window). */
  constructor(kind: RuleKind, holdMs: number, emit: (e: RuleEvent) => void, leadMs = 0) {
    this.kind = kind;
    this.holdMs = holdMs;
    this.emit = emit;
    this.leadMs = leadMs;
  }

  update(t: number, on: boolean, allowed = true, details?: Record<string, string | number>): void {
    if (this.open && t - this.open.last >= MERGE_MS) this.close();
    if (this.open) {
      this.open.on = on;
      if (on) {
        this.open.last = t;
        if (details) this.open.details = merge(this.open.details, details);
      }
      return;
    }
    if (!on || !allowed || t < this.coolUntil) {
      this.since = null;
      return;
    }
    this.since ??= t;
    if (t - this.since >= this.holdMs) {
      this.open = { id: crypto.randomUUID(), at: this.since - this.leadMs, last: t, on, details };
    }
  }

  /** The open event and how long it has lasted by `t` (for the teacher's live monitor). */
  ongoing(t: number): { kind: RuleKind; seconds: number } | null {
    return this.open ? { kind: this.kind, seconds: Math.round((t - this.open.at) / 1000) } : null;
  }

  /** The open event, while what raised it is still seen (pictures are taken then). */
  seen(): { id: string; kind: RuleKind } | null {
    return this.open?.on ? { id: this.open.id, kind: this.kind } : null;
  }

  /** What's known is lost (frames far apart): start counting again. */
  forget(): void {
    this.since = null;
  }

  close(): void {
    const open = this.open;
    if (!open) return;
    this.open = null;
    this.since = null;
    this.coolUntil = open.last + COOLDOWN_MS;
    this.emit({
      id: open.id,
      kind: this.kind,
      at: open.at,
      durationMs: open.last - open.at,
      ...(open.details ? { details: open.details } : {}),
    });
  }
}

/** Keep the largest count seen and the first direction. */
function merge(
  a: Record<string, string | number> | undefined,
  b: Record<string, string | number>,
): Record<string, string | number> {
  const out = { ...b, ...a };
  if (typeof a?.faces === "number" && typeof b.faces === "number") {
    out.faces = Math.max(a.faces, b.faces);
  }
  return out;
}

function clamp(x: number, limit: number): number {
  return Math.max(-limit, Math.min(limit, x));
}

export class Rules {
  private readonly config: RulesConfig;
  private readonly faceAbsent: Detector;
  private readonly multipleFaces: Detector;
  private readonly gazeAway: Detector;
  private readonly voice: Detector;
  private lastFrame: number | null = null;
  private readonly poses: { yaw: number; pitch: number }[] = [];
  private baseline: { yaw: number; pitch: number } | null = null;
  private readonly heard: { t: number; speaking: boolean }[] = [];
  private readonly windowMs: number;

  constructor(config: RulesConfig, emit: (e: RuleEvent) => void) {
    this.config = config;
    const k = SCALE[config.sensitivity];
    this.windowMs = VOICE_WINDOW_MS * k;
    this.faceAbsent = new Detector("FACE_ABSENT", FACE_ABSENT_MS * k, emit);
    this.multipleFaces = new Detector("MULTIPLE_FACES", MULTIPLE_FACES_MS * k, emit);
    this.gazeAway = new Detector("GAZE_AWAY", GAZE_MS * k, emit);
    this.voice = new Detector("VOICE_DETECTED", 0, emit, this.windowMs);
  }

  private settled(t: number): boolean {
    return t - this.config.startedAt >= SETTLE_MS;
  }

  /** One analysed camera frame: the faces found, biggest first. */
  frame(t: number, faces: readonly SeenFace[]): void {
    if (this.lastFrame !== null && t - this.lastFrame > GAP_MS) {
      this.faceAbsent.forget();
      this.multipleFaces.forget();
      this.gazeAway.forget();
    }
    this.lastFrame = t;
    const settled = this.settled(t);
    const main = faces[0];

    this.faceAbsent.update(t, !main, settled);

    const others = main ? faces.slice(1).filter((f) => f.area >= SECOND_FACE * main.area) : [];
    this.multipleFaces.update(t, others.length > 0, true, { faces: others.length + 1 });

    if (!this.config.gaze) return;
    const pose = main && main.yaw !== null && main.pitch !== null ? main : null;
    if (!settled) {
      // The student's resting pose, learned while settling.
      if (pose) this.poses.push({ yaw: pose.yaw!, pitch: pose.pitch! });
      return;
    }
    if (!this.baseline) {
      this.baseline = this.poses.length
        ? {
            yaw: clamp(median(this.poses.map((p) => p.yaw))!, BASELINE_MAX_DEG),
            pitch: clamp(median(this.poses.map((p) => p.pitch))!, BASELINE_MAX_DEG),
          }
        : { yaw: 0, pitch: 0 };
    }
    const direction = pose ? this.direction(pose.yaw!, pose.pitch!) : null;
    this.gazeAway.update(t, direction !== null, true, direction ? { direction } : undefined);
  }

  /** Where the head is turned, or null when facing the screen. Looking down (at the keyboard,
   *  at paper) is ignored. MediaPipe's pitch is negative with the chin up. */
  private direction(yaw: number, pitch: number): string | null {
    const dy = yaw - this.baseline!.yaw;
    const dp = pitch - this.baseline!.pitch;
    if (Math.abs(dy) > YAW_DEG) return "sideways";
    if (-dp > UP_DEG) return "up";
    return null;
  }

  /** The voice detector's latest answer: is someone speaking now. */
  sound(t: number, speaking: boolean): void {
    if (!this.config.voice) return;
    this.heard.push({ t, speaking });
    while (this.heard.length && this.heard[0]!.t < t - this.windowMs) this.heard.shift();
    const full = t - this.heard[0]!.t >= this.windowMs * 0.9;
    const share = this.heard.filter((h) => h.speaking).length / this.heard.length;
    this.voice.update(t, full && share >= VOICE_SHARE);
  }

  /** Camera events open now whose cause is still in view. */
  seen(): { id: string; kind: RuleKind }[] {
    return [this.faceAbsent, this.multipleFaces, this.gazeAway]
      .map((d) => d.seen())
      .filter((x) => x !== null);
  }

  /** Events open now and how long so far (sent with the heartbeat). */
  ongoing(t: number): { kind: RuleKind; seconds: number }[] {
    return [this.faceAbsent, this.multipleFaces, this.gazeAway, this.voice]
      .map((d) => d.ongoing(t))
      .filter((x) => x !== null);
  }

  /** The end (submitting, leaving): events still open are recorded now. */
  flush(): void {
    this.faceAbsent.close();
    this.multipleFaces.close();
    this.gazeAway.close();
    this.voice.close();
  }
}
