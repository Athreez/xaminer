// Speech detection with Silero VAD v6 (vad-web), on the device only: the sound itself never
// leaves the browser (PRD PRC-08). Ported from CALIPER's SDK (caliper/frontend/src/sdk/audio.ts),
// moved from v5 to v6, which false-alarms far less on noise alone (CALIPER: 0.95 % vs 4.45 %).
import { MicVAD } from "@ricky0123/vad-web";

import { ASSETS } from "./vision";

/** The model's own thresholds, with hysteresis between them. */
const SPEECH_ON = 0.3;
const SPEECH_OFF = 0.25;

export class VoiceMonitor {
  private readonly vad: MicVAD;
  private constructor(vad: MicVAD) {
    this.vad = vad;
  }

  speaking = false;
  /** Milliseconds of speech heard so far, and the latest loudness (0..1). */
  speechMs = 0;
  level = 0;

  static async start(stream: MediaStream): Promise<VoiceMonitor> {
    let monitor: VoiceMonitor | null = null;
    let last = performance.now();
    const vad = await MicVAD.new({
      model: "v6",
      baseAssetPath: `${ASSETS}/vad/`,
      onnxWASMBasePath: `${ASSETS}/ort/`,
      ortConfig: (ort) => {
        // One thread: several need cross-origin isolation, which the app doesn't have.
        ort.env.wasm.numThreads = 1;
      },
      positiveSpeechThreshold: SPEECH_ON,
      negativeSpeechThreshold: SPEECH_OFF,
      getStream: async () => new MediaStream(stream.getAudioTracks()),
      pauseStream: async () => undefined,
      resumeStream: async (s) => s,
      startOnLoad: true,
      onFrameProcessed: (probabilities, frame) => {
        const now = performance.now();
        const m = monitor;
        if (!m) return;
        if (probabilities.isSpeech >= SPEECH_ON) m.speaking = true;
        else if (probabilities.isSpeech < SPEECH_OFF) m.speaking = false;
        if (m.speaking) m.speechMs += now - last;
        last = now;
        let sum = 0;
        for (const x of frame) sum += x * x;
        m.level = Math.min(1, Math.sqrt(sum / Math.max(1, frame.length)) * 8);
      },
    });
    monitor = new VoiceMonitor(vad);
    return monitor;
  }

  async stop(): Promise<void> {
    await this.vad.destroy();
  }
}
