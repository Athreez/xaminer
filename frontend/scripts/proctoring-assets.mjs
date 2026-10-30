// The proctoring models and their runtimes, served by the app itself at /proctoring/ so the exam
// never depends on a third-party site (PRD PRC-04, PRC-05). Runs before `npm run dev` and
// `npm run build`; files already there are kept. The folder is git-ignored.
//
// From node_modules: MediaPipe's WebAssembly, Silero VAD v6 with its audio worklet, and the ONNX
// Runtime it runs on. Downloaded once: MediaPipe Face Landmarker and EfficientDet-Lite0 (both
// Apache-2.0, the same files CALIPER benchmarked).
import { copyFileSync, existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const out = join(root, "public", "proctoring");
const nm = join(root, "node_modules");

const copies = {
  mediapipe: [
    "@mediapipe/tasks-vision/wasm/vision_wasm_internal.js",
    "@mediapipe/tasks-vision/wasm/vision_wasm_internal.wasm",
    "@mediapipe/tasks-vision/wasm/vision_wasm_nosimd_internal.js",
    "@mediapipe/tasks-vision/wasm/vision_wasm_nosimd_internal.wasm",
  ],
  vad: [
    "@ricky0123/vad-web/dist/vad.worklet.bundle.min.js",
    "@ricky0123/vad-web/dist/silero_vad_v6.onnx",
  ],
  ort: [
    "onnxruntime-web/dist/ort-wasm-simd-threaded.mjs",
    "onnxruntime-web/dist/ort-wasm-simd-threaded.wasm",
  ],
};

const MODELS = "https://storage.googleapis.com/mediapipe-models";
const downloads = {
  "face_landmarker.task": `${MODELS}/face_landmarker/face_landmarker/float16/1/face_landmarker.task`,
  "efficientdet_lite0.tflite": `${MODELS}/object_detector/efficientdet_lite0/float16/1/efficientdet_lite0.tflite`,
};

for (const [folder, files] of Object.entries(copies)) {
  mkdirSync(join(out, folder), { recursive: true });
  for (const file of files) {
    const target = join(out, folder, file.split("/").pop());
    const source = join(nm, file);
    if (!existsSync(target) || statSync(target).size !== statSync(source).size) {
      copyFileSync(source, target);
    }
  }
}

mkdirSync(join(out, "models"), { recursive: true });
for (const [name, url] of Object.entries(downloads)) {
  const target = join(out, "models", name);
  if (existsSync(target) && statSync(target).size > 0) continue;
  console.log(`downloading ${name}`);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  writeFileSync(target, Buffer.from(await response.arrayBuffer()));
}
