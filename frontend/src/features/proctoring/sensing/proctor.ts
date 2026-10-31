// Watching during the exam (PRD PRC-05, NFR-07; TCK-1003, TCK-1005): the face model on the
// camera at 3 frames a second (down to 1 on slow devices, by measured speed) and the voice model
// on the microphone, both on the device; the rules turn what they see into events. Sound never
// leaves the browser; camera pictures do, only for events (3 each: start, middle, latest) and as
// random spot checks every 20-40 s (TCK-1006). Also: the object model (EfficientDet-Lite0) as a
// trigger only, sending an extra spot check when it might see a phone or a book (the server
// decides); the student's face at the start, once, as the identity reference; and a few liveness
// challenges per exam (turn the head, blink twice).
//
// It runs on the page itself, not in a Web Worker: MediaPipe's loader doesn't work in module
// workers, and each analysis (~40 ms here) is short enough between keystrokes. The rate governor
// keeps it to a fifth of one core.
import { cameraPicture, type Purpose } from "../pictures";
import { governedRate, LatencyTracker } from "./geometry";
import {
  Challenge,
  CHALLENGE_MS,
  firstChallenge,
  nextChallenge,
  pickChallenge,
  type ChallengeKind,
} from "./liveness";
import { VoiceMonitor } from "./audio";
import { Rules, type RuleEvent, type RulesConfig } from "./rules";
import { area, VisionEngine } from "./vision";

const TARGET_HZ = 3;
const MIN_HZ = 1;
const BUDGET = 0.2; // share of one core for the face model
const SOUND_MS = 250;
/** This many failed analyses in a row: proctoring has broken (the server then sees no frames). */
const MAX_FAILURES = 10;
const SHOT_EVERY_MS = 3_000; // while an event's cause is in view
const SHOTS_KEPT = 21; // per event, thinned evenly beyond this
const EVENTS_WITH_PICTURES = 30;
const OBJECT_HZ = 2;
const OBJECT_MIN_HZ = 0.2;
const OBJECT_BUDGET = 0.1;
const TRIGGER_SCORE = 0.3; // a hint for the server's check, not a verdict
const TRIGGER_EVERY_MS = 10_000;
const REFERENCE_AREA = 0.02; // a clear, near face for the identity reference
const CHALLENGE_FRAME_MS = 100; // blinks are short: 10 frames a second during a challenge
const MAX_CHALLENGES = 3;
const RETRY_CHALLENGE_MS = 2 * 60_000;

export type Prompt = { kind: ChallengeKind; endsAt: number };

/** An event the proctor raised itself (the rules' events and failed challenges). */
export type ProctorEvent = {
  id: string;
  kind: string;
  at: number;
  durationMs: number;
  details?: Record<string, string | number>;
};

export type OnPicture = (purpose: Purpose, blob: Blob, eventId?: string) => void;

/** Spot checks come at random, so they can't be timed around. */
export function nextSpotCheck(now: number, random = Math.random): number {
  return now + 20_000 + random() * 20_000;
}

/** Pictures of each open event; when it ends, its first, middle and latest are kept. */
export class EventShots {
  private readonly shots = new Map<string, { at: number; blobs: Blob[] }>();
  private events = 0;

  due(id: string, now: number): boolean {
    const known = this.shots.get(id);
    if (!known) return this.events < EVENTS_WITH_PICTURES;
    return now - known.at >= SHOT_EVERY_MS;
  }

  add(id: string, now: number, blob: Blob): void {
    let known = this.shots.get(id);
    if (!known) {
      if (this.events >= EVENTS_WITH_PICTURES) return;
      this.events += 1;
      known = { at: now, blobs: [] };
      this.shots.set(id, known);
    }
    known.at = now;
    known.blobs.push(blob);
    if (known.blobs.length > SHOTS_KEPT) {
      known.blobs = known.blobs.filter((_, i) => i % 2 === 0 || i === known!.blobs.length - 1);
    }
  }

  /** Mark one as due now (taken but its picture not back yet). */
  touch(id: string, now: number): void {
    const known = this.shots.get(id);
    if (known) known.at = now;
  }

  take(id: string): Blob[] {
    const blobs = this.shots.get(id)?.blobs ?? [];
    this.shots.delete(id);
    if (blobs.length <= 3) return blobs;
    return [blobs[0]!, blobs[Math.floor(blobs.length / 2)]!, blobs.at(-1)!];
  }
}

export class Proctor {
  /** Frames analysed so far (sent with each heartbeat: the server notices when it stops). */
  frames = 0;
  private stopped = false;
  private timer = 0;
  private soundTimer = 0;
  private failures = 0;
  private spotAt = nextSpotCheck(Date.now());
  private objectTimer = 0;
  private triggeredAt = 0;
  private referenceTaken = false;
  private challenge: { id: string; check: Challenge } | null = null;
  private challengeAt = firstChallenge(Date.now());
  private challenges = 0;
  private readonly objectLatency = new LatencyTracker();
  private readonly latency = new LatencyTracker();
  private readonly engine: VisionEngine;
  private readonly video: HTMLVideoElement;
  private readonly rules: Rules;
  private readonly voice: VoiceMonitor | null;
  private readonly onBroken: () => void;
  private readonly onPicture: OnPicture;
  private readonly shots: EventShots;
  private readonly emit: (e: ProctorEvent) => void;
  private readonly onPrompt: (prompt: Prompt | null) => void;

  private constructor(
    engine: VisionEngine,
    video: HTMLVideoElement,
    rules: Rules,
    voice: VoiceMonitor | null,
    options: {
      onBroken: () => void;
      onPicture: OnPicture;
      emit: (e: ProctorEvent) => void;
      onPrompt: (prompt: Prompt | null) => void;
    },
    shots: EventShots,
  ) {
    this.engine = engine;
    this.video = video;
    this.rules = rules;
    this.voice = voice;
    this.onBroken = options.onBroken;
    this.onPicture = options.onPicture;
    this.emit = options.emit;
    this.onPrompt = options.onPrompt;
    this.shots = shots;
  }

  static async start(options: {
    video: HTMLVideoElement;
    camera: MediaStream;
    config: Omit<RulesConfig, "startedAt">;
    emit: (e: ProctorEvent) => void;
    onBroken: () => void;
    onPicture: OnPicture;
    onPrompt: (prompt: Prompt | null) => void;
  }): Promise<Proctor> {
    const engine = await VisionEngine.create({ objects: true });
    const microphone = options.config.voice && options.camera.getAudioTracks().length > 0;
    const voice = microphone ? await VoiceMonitor.start(options.camera) : null;
    const shots = new EventShots();
    const rules = new Rules({ ...options.config, startedAt: Date.now() }, (e: RuleEvent) => {
      for (const blob of shots.take(e.id)) options.onPicture("EVENT", blob, e.id);
      options.emit(e);
    });
    const proctor = new Proctor(engine, options.video, rules, voice, options, shots);
    proctor.tick();
    proctor.objectTick();
    if (voice) {
      proctor.soundTimer = window.setInterval(
        () => rules.sound(Date.now(), voice.speaking),
        SOUND_MS,
      );
    }
    return proctor;
  }

  private tick = () => {
    if (this.stopped) return;
    let ms = 0;
    if (this.video.readyState >= 2) {
      try {
        const seen = this.engine.faces(this.video);
        ms = seen.ms;
        this.latency.add(ms);
        const now = Date.now();
        const faces = seen.faces.map((f) => ({ area: area(f.box), yaw: f.yaw, pitch: f.pitch }));
        this.rules.frame(now, faces);
        this.frames += 1;
        this.failures = 0;
        this.pictures();
        if (!this.referenceTaken && faces.length === 1 && faces[0]!.area >= REFERENCE_AREA) {
          this.referenceTaken = true; // the face at the start, once (a repeat is dropped anyway)
          void cameraPicture(this.video).then((b) => b && this.onPicture("REFERENCE", b));
        }
        this.liveness(now, faces.length === 1 ? seen.faces[0]! : null, faces.length);
      } catch {
        if (++this.failures >= MAX_FAILURES) {
          this.stop();
          this.onBroken();
          return;
        }
      }
    }
    const hz = Math.max(MIN_HZ, governedRate(TARGET_HZ, BUDGET, this.latency.ms ?? ms));
    this.timer = window.setTimeout(this.tick, this.challenge ? CHALLENGE_FRAME_MS : 1000 / hz);
  };

  /** The object model, as a trigger: a possible phone or book sends an extra spot check. */
  private objectTick = () => {
    if (this.stopped) return;
    let ms = 0;
    if (this.video.readyState >= 2 && !this.challenge) {
      try {
        const seen = this.engine.detect(this.video);
        ms = seen.ms;
        this.objectLatency.add(ms);
        const now = Date.now();
        const hint = seen.found.some(
          (d) => (d.label === "cell phone" || d.label === "book") && d.score >= TRIGGER_SCORE,
        );
        if (hint && now - this.triggeredAt >= TRIGGER_EVERY_MS) {
          this.triggeredAt = now;
          void cameraPicture(this.video).then((b) => b && this.onPicture("SPOT_CHECK", b));
        }
      } catch {
        // the face model's failures stop proctoring; this one only stops hinting
      }
    }
    const hz = Math.max(
      OBJECT_MIN_HZ,
      governedRate(OBJECT_HZ, OBJECT_BUDGET, this.objectLatency.ms ?? ms),
    );
    this.objectTimer = window.setTimeout(this.objectTick, 1000 / hz);
  };

  /** Start a challenge when due (one face, nothing else going on); check the one under way. */
  private liveness(
    now: number,
    face: { yaw: number | null; blink: number | null } | null,
    faceCount: number,
  ): void {
    if (!this.challenge) {
      const calm = faceCount === 1 && this.rules.ongoing(now).length === 0;
      if (this.challenges >= MAX_CHALLENGES || now < this.challengeAt || !calm) return;
      this.challenges += 1;
      const check = new Challenge(pickChallenge(), now);
      this.challenge = { id: crypto.randomUUID(), check };
      this.onPrompt({ kind: check.kind, endsAt: now + CHALLENGE_MS });
      return;
    }
    const { id, check } = this.challenge;
    const state = check.frame(now, face);
    if (state === "waiting") {
      if (this.shots.due(id, now)) {
        this.shots.touch(id, now);
        void cameraPicture(this.video).then((b) => b && this.shots.add(id, now, b));
      }
      return;
    }
    this.challenge = null;
    this.onPrompt(null);
    const shots = this.shots.take(id);
    if (state === "failed") {
      for (const blob of shots) this.onPicture("EVENT", blob, id);
      this.emit({
        id,
        kind: "LIVENESS_FAILED",
        at: check.startedAt,
        durationMs: now - check.startedAt,
        details: { challenge: check.kind.toLowerCase() },
      });
    }
    this.challengeAt = state === "skipped" ? now + RETRY_CHALLENGE_MS : nextChallenge(now);
  }

  /** Pictures for events in view, and the spot check when it's due. */
  private pictures(): void {
    const now = Date.now();
    for (const { id } of this.rules.seen()) {
      if (!this.shots.due(id, now)) continue;
      this.shots.touch(id, now);
      void cameraPicture(this.video).then((blob) => blob && this.shots.add(id, now, blob));
    }
    if (now >= this.spotAt) {
      this.spotAt = nextSpotCheck(now);
      void cameraPicture(this.video).then((blob) => blob && this.onPicture("SPOT_CHECK", blob));
    }
  }

  /** Stop watching; events still open are recorded first. */
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    window.clearTimeout(this.timer);
    window.clearTimeout(this.objectTimer);
    window.clearInterval(this.soundTimer);
    if (this.challenge) this.onPrompt(null);
    this.rules.flush();
    void this.voice?.stop();
    this.engine.close();
  }

  /** Events open now (for the heartbeat). */
  ongoing(): { kind: string; seconds: number }[] {
    return this.stopped ? [] : this.rules.ongoing(Date.now());
  }

  /** Record events still open without stopping (before submitting). */
  flush(): void {
    this.rules.flush();
  }
}
