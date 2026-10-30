// Watching during the exam (PRD PRC-05, NFR-07; TCK-1003, TCK-1005): the face model on the
// camera at 3 frames a second (down to 1 on slow devices, by measured speed) and the voice model
// on the microphone, both on the device; the rules turn what they see into events. No picture
// or sound leaves the browser here.
//
// It runs on the page itself, not in a Web Worker: MediaPipe's loader doesn't work in module
// workers, and each analysis (~40 ms here) is short enough between keystrokes. The rate governor
// keeps it to a fifth of one core.
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

export class Proctor {
  /** Frames analysed so far (sent with each heartbeat: the server notices when it stops). */
  frames = 0;
  private stopped = false;
  private timer = 0;
  private soundTimer = 0;
  private failures = 0;
  private readonly latency = new LatencyTracker();
  private readonly engine: VisionEngine;
  private readonly video: HTMLVideoElement;
  private readonly rules: Rules;
  private readonly voice: VoiceMonitor | null;
  private readonly onBroken: () => void;

  private constructor(
    engine: VisionEngine,
    video: HTMLVideoElement,
    rules: Rules,
    voice: VoiceMonitor | null,
    onBroken: () => void,
  ) {
    this.engine = engine;
    this.video = video;
    this.rules = rules;
    this.voice = voice;
    this.onBroken = onBroken;
  }

  static async start(options: {
    video: HTMLVideoElement;
    camera: MediaStream;
    config: Omit<RulesConfig, "startedAt">;
    emit: (e: RuleEvent) => void;
    onBroken: () => void;
  }): Promise<Proctor> {
    const engine = await VisionEngine.create({ objects: false });
    const microphone = options.config.voice && options.camera.getAudioTracks().length > 0;
    const voice = microphone ? await VoiceMonitor.start(options.camera) : null;
    const rules = new Rules({ ...options.config, startedAt: Date.now() }, options.emit);
    const proctor = new Proctor(engine, options.video, rules, voice, options.onBroken);
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

  /** Record events still open without stopping (before submitting). */
  flush(): void {
    this.rules.flush();
  }
}
