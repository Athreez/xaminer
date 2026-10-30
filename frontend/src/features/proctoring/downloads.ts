import { FilesetResolver } from "@mediapipe/tasks-vision";

import { ASSETS } from "./sensing/vision";

/** The files the exam's sensors load, fetched once here so the browser has them cached before
 *  the exam starts (PRD § 6.6: the device check downloads the models). */
export async function proctoringFiles(audio: boolean): Promise<string[]> {
  const wasm = (await FilesetResolver.isSimdSupported())
    ? "vision_wasm_internal"
    : "vision_wasm_nosimd_internal";
  const files = [
    `${ASSETS}/mediapipe/${wasm}.js`,
    `${ASSETS}/mediapipe/${wasm}.wasm`,
    `${ASSETS}/models/face_landmarker.task`,
    `${ASSETS}/models/efficientdet_lite0.tflite`,
  ];
  if (audio) {
    files.push(
      `${ASSETS}/vad/vad.worklet.bundle.min.js`,
      `${ASSETS}/vad/silero_vad_v6.onnx`,
      `${ASSETS}/ort/ort-wasm-simd-threaded.mjs`,
      `${ASSETS}/ort/ort-wasm-simd-threaded.wasm`,
    );
  }
  return files;
}

/** Fetch every file, reporting bytes received so far and the total (when the server says). */
export async function download(
  files: string[],
  progress: (received: number, total: number | null) => void,
  signal: AbortSignal,
): Promise<void> {
  const responses = await Promise.all(files.map((f) => fetch(f, { signal })));
  const bad = responses.find((r) => !r.ok);
  if (bad) throw new Error(`Couldn't download ${new URL(bad.url).pathname} (${bad.status}).`);
  const sizes = responses.map((r) => Number(r.headers.get("Content-Length")));
  // Compressed responses report the compressed size, so the total is only a guide.
  const total = sizes.every((n) => n > 0) ? sizes.reduce((a, b) => a + b, 0) : null;
  let received = 0;
  await Promise.all(
    responses.map(async (r) => {
      const reader = r.body?.getReader();
      if (!reader) return;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        received += value.byteLength;
        progress(received, total);
      }
    }),
  );
}
