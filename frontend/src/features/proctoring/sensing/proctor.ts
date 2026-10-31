// Watching during the exam (PRD PRC-05, NFR-07; TCK-1003, TCK-1005): the face model on the
// camera at 3 frames a second (down to 1 on slow devices, by measured speed) and the voice model
// on the microphone, both on the device; the rules turn what they see into events. Sound never
// leaves the browser; camera pictures do, only for events (3 each: start, middle, latest) and as
// random spot checks every 20-40 s (TCK-1006).
//
// It runs on the page itself, not in a Web Worker: MediaPipe's loader doesn't work in module
// workers, and each analysis (~40 ms here) is short enough between keystrokes. The rate governor
// keeps it to a fifth of one core.
import { cameraPicture, type Purpose } from "../pictures";
import { governedRate, LatencyTracker } from "./geometry";
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
  private readonly latency = new LatencyTracker();
  private readonly engine: VisionEngine;
  private readonly video: HTMLVideoElement;
  private readonly rules: Rules;
  private readonly voice: VoiceMonitor | null;
  private readonly onBroken: () => void;
  private readonly onPicture: OnPicture;
  private readonly shots: EventShots;

  private constructor(
    engine: VisionEngine,
    video: HTMLVideoElement,
    rules: Rules,
    voice: VoiceMonitor | null,
    onBroken: () => void,
    onPicture: OnPicture,
    shots: EventShots,
  ) {
    this.engine = engine;
    this.video = video;
    this.rules = rules;
    this.voice = voice;
    this.onBroken = onBroken;
    this.onPicture = onPicture;
    this.shots = shots;
  }

  static async start(options: {
    video: HTMLVideoElement;
    camera: MediaStream;
    config: Omit<RulesConfig, "startedAt">;
    emit: (e: RuleEvent) => void;
    onBroken: () => void;
    onPicture: OnPicture;
  }): Promise<Proctor> {
    const engine = await VisionEngine.create({ objects: false });
    const microphone = options.config.voice && options.camera.getAudioTracks().length > 0;
    const voice = microphone ? await VoiceMonitor.start(options.camera) : null;
    const shots = new EventShots();
    const rules = new Rules({ ...options.config, startedAt: Date.now() }, (e) => {
      for (const blob of shots.take(e.id)) options.onPicture("EVENT", blob, e.id);
      options.emit(e);
    });
    const proctor = new Proctor(
      engine,
      options.video,
      rules,
      voice,
      options.onBroken,
      options.onPicture,
      shots,
    );
    proctor.tick();
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
        this.rules.frame(
          Date.now(),
          seen.faces.map((f) => ({ area: area(f.box), yaw: f.yaw, pitch: f.pitch })),
        );
        this.frames += 1;
        this.failures = 0;
        this.pictures();
      } catch {
        if (++this.failures >= MAX_FAILURES) {
          this.stop();
          this.onBroken();
          return;
        }
      }
    }
    const hz = Math.max(MIN_HZ, governedRate(TARGET_HZ, BUDGET, this.latency.ms ?? ms));
    this.timer = window.setTimeout(this.tick, 1000 / hz);
  };

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
    window.clearInterval(this.soundTimer);
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
